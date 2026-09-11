"""Lease-based PostgreSQL worker. Run with python -m backend.worker."""

import asyncio
import json
import logging
import time
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select, text, update

from backend.core.config import get_settings
from backend.core.enums import SearchStatus
from backend.db.models import ConnectorRun, InvestigationJob, SearchRun, utc_now
from backend.db.repositories import PostgresInvestigationRepository
from backend.db.session import AsyncSessionFactory
from backend.events import emit
from backend.investigation.orchestrator import SearchOrchestrator

log = logging.getLogger("deus.worker")


async def claim(worker_id):
    async with AsyncSessionFactory() as session, session.begin():
        job = await session.scalar(
            select(InvestigationJob)
            .where(
                InvestigationJob.available_at <= utc_now(),
                or_(
                    InvestigationJob.status == "PENDING",
                    (InvestigationJob.status == "RUNNING")
                    & (InvestigationJob.lease_until < utc_now()),
                ),
            )
            .order_by(InvestigationJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        job.status = "RUNNING"
        job.attempt_count += 1
        job.worker_id = worker_id
        job.lease_until = utc_now() + timedelta(seconds=60)
        return job.id, job.search_run_id


async def execute(job_id, search_id, worker_id):
    # Hold a dedicated session-level lock across checkpoints and external I/O.
    # Different searches remain concurrent; one search never has two active collectors.
    async with AsyncSessionFactory() as guard:
        locked = await guard.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:search, 0))"),
            {"search": str(search_id)},
        )
        if not locked:
            async with AsyncSessionFactory() as session, session.begin():
                job = await session.get(InvestigationJob, job_id)
                if job.worker_id == worker_id and job.status == "RUNNING":
                    job.status = "PENDING"
                    job.available_at = utc_now() + timedelta(seconds=3)
                    job.lease_until = None
            return
        try:
            await execute_locked(job_id, search_id, worker_id)
        finally:
            await guard.execute(
                text("SELECT pg_advisory_unlock(hashtextextended(:search, 0))"),
                {"search": str(search_id)},
            )


async def execute_locked(job_id, search_id, worker_id):
    started = time.monotonic()
    task = asyncio.current_task()

    async def heartbeat():
        while True:
            await asyncio.sleep(2)
            async with AsyncSessionFactory() as session, session.begin():
                job = await session.get(InvestigationJob, job_id)
                status = await session.scalar(
                    select(SearchRun.status).where(SearchRun.id == search_id)
                )
                if (
                    job.worker_id != worker_id
                    or job.status == "CANCELLED"
                    or status == SearchStatus.CANCELLED
                ):
                    task.cancel()
                    return
                job.lease_until = utc_now() + timedelta(seconds=60)
                job.updated_at = utc_now()

    pulse = asyncio.create_task(heartbeat())
    outcome, error = "COMPLETED", None
    try:
        async with AsyncSessionFactory() as session:
            repository = PostgresInvestigationRepository(session)

            async def checkpoint():
                async with AsyncSessionFactory() as check:
                    job = await check.get(InvestigationJob, job_id)
                    status = await check.scalar(
                        select(SearchRun.status).where(SearchRun.id == search_id)
                    )
                    if status == SearchStatus.CANCELLED or job.worker_id != worker_id:
                        raise asyncio.CancelledError()
                await session.commit()

            search = await repository.get_search(search_id)
            if search.status == SearchStatus.CANCELLED:
                raise asyncio.CancelledError()
            elapsed = await session.scalar(
                select(func.coalesce(func.sum(InvestigationJob.runtime_seconds), 0)).where(
                    InvestigationJob.search_run_id == search_id
                )
            )
            # An interrupted run has no result; retain it as failed, never fabricate recovery.
            await session.execute(
                update(ConnectorRun)
                .where(ConnectorRun.search_run_id == search_id, ConnectorRun.status == "RUNNING")
                .values(
                    status="FAILED",
                    error="Worker interrupted before a result was persisted.",
                    completed_at=utc_now(),
                )
            )
            await session.commit()
            async with asyncio.timeout(max(0.01, search.max_search_duration_seconds - elapsed)):
                await SearchOrchestrator(
                    repository, get_settings(), checkpoint=checkpoint
                ).run_search(search_id)
            search = await repository.get_search(search_id)
            outcome = "WAITING" if search.status == SearchStatus.AWAITING_USER else "COMPLETED"
            await session.commit()
    except asyncio.CancelledError:
        outcome, error = "CANCELLED", "Cancelled or worker lease lost."
    except Exception as exc:
        outcome, error = "FAILED", _public_worker_error(exc)
        log.exception("Investigation failed")
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
        async with AsyncSessionFactory() as session, session.begin():
            job = await session.get(InvestigationJob, job_id)
            if job.worker_id == worker_id and job.status != "CANCELLED":
                job.status, job.last_error = outcome, error
                job.runtime_seconds += time.monotonic() - started
                job.lease_until = None
                job.updated_at = utc_now()
                search = await session.get(SearchRun, search_id)
                if outcome in {"FAILED", "CANCELLED"}:
                    await session.execute(
                        update(ConnectorRun)
                        .where(
                            ConnectorRun.search_run_id == search_id,
                            ConnectorRun.status == "RUNNING",
                        )
                        .values(status="FAILED", error=error, completed_at=utc_now())
                    )
                if outcome == "FAILED" and search.status != SearchStatus.CANCELLED:
                    search.status, search.error_summary = SearchStatus.FAILED, error
                    search.completed_at = utc_now()
                    emit(session, search.id, "FAILED", status="FAILED")
        log.info(
            json.dumps(
                {
                    "job_id": str(job_id),
                    "search_id": str(search_id),
                    "status": outcome,
                    "duration": time.monotonic() - started,
                    "error": error,
                }
            )
        )


def _public_worker_error(exc: Exception) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if "upsert_profile" in message:
        return "Email account discovery failed while saving profiles. Please retry the search."
    return message


async def main():
    worker_id = str(uuid4())
    while True:
        try:
            claimed = await claim(worker_id)
        except Exception:
            log.exception("Queue unavailable; retrying in five seconds")
            await asyncio.sleep(5)
            continue
        if claimed:
            await execute(*claimed, worker_id)
        else:
            await asyncio.sleep(1)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
