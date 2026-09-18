"""Durable job scheduling and answer submission. PostgreSQL is the only queue."""

from uuid import UUID

from sqlalchemy import select

from backend.core.enums import SearchStatus
from backend.db.models import InvestigationJob, SearchRun, UserSearchContext
from backend.db.repositories import SearchLimits
from backend.investigation.orchestrator import _normalize_seed
from backend.investigation.username_questions import DISCOVERY_KINDS, variants_from_answer


async def enqueue(session, search_id):
    existing = await session.scalar(
        select(InvestigationJob).where(
            InvestigationJob.search_run_id == search_id, InvestigationJob.status == "PENDING"
        )
    )
    if existing:
        return existing
    job = InvestigationJob(search_run_id=search_id)
    session.add(job)
    await session.flush()
    return job


async def create_search(repository, settings, payload):
    search = await repository.create_search(
        payload.seed_type,
        payload.value,
        _normalize_seed(payload.seed_type, payload.value),
        scope=payload.scope,
        limits=SearchLimits(
            max_pivot_depth=settings.max_pivot_depth,
            max_questions=settings.max_questions,
            max_connector_runs=settings.max_connector_runs,
            max_candidates=settings.max_candidates,
            max_search_duration_seconds=settings.max_search_duration_seconds,
        ),
    )
    await enqueue(repository.session, search.id)
    if getattr(payload, "email_self_audit_confirmed", False):
        repository.session.add(
            UserSearchContext(
                search_run_id=search.id,
                context_type="EMAIL_SELF_AUDIT_CONSENT",
                value={"explicit_email_seed": True},
            )
        )
    return search


async def lock_search(session, search_id):
    search = await session.scalar(
        select(SearchRun)
        .where(SearchRun.id == UUID(str(search_id)))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if search is None:
        raise LookupError("search not found")
    return search


async def submit_answer(repository, search_id, question_id, value):
    search = await lock_search(repository.session, search_id)
    if search.status != SearchStatus.AWAITING_USER:
        raise ValueError("Search is not awaiting an answer.")
    question = await repository.get_question(question_id)
    if question is None or question.search_run_id != search.id:
        raise LookupError("question not found for this search")
    if question.status != "PENDING":
        raise ValueError("Question already answered.")
    context = question.context or {}
    kind = context.get("kind")
    if isinstance(value, list):
        allowed = {str(item.get("value")) for item in question.options} - {"skip"}
        if question.question_type != "MULTI_SELECT" or not value or len(value) > 10:
            raise ValueError("Invalid multiple selection")
        if any(item not in allowed for item in value):
            raise ValueError("Choose only available options")
        value = list(dict.fromkeys(value))
    else:
        value = value.strip()
    variants = ()
    if kind in DISCOVERY_KINDS:
        variants = variants_from_answer(kind, context["base_username"], value)
    elif not isinstance(value, list) and value not in {
        str(item.get("value")) for item in question.options
    }:
        raise ValueError("Choose an available answer.")
    payload = {
        "value": value,
        "generated_usernames": list(variants),
        "source": "USER_PROVIDED_SEARCH_HINT",
        "question_kind": kind,
        "selected_profile_ids": next(
            (
                item.get("profile_ids", [])
                for item in question.options
                if item.get("value") == value
            ),
            [],
        ),
        "effect": f"additional live searches for {', '.join(variants)}"
        if variants
        else "search direction updated; identity scores are unchanged",
    }
    result = await repository.answer_question(question.id, payload, skipped=value == "skip")
    repository.session.add(
        UserSearchContext(
            search_run_id=search.id,
            question_id=question.id,
            answer_id=result.answer.id,
            context_type="USERNAME_HINT" if kind in DISCOVERY_KINDS else "BRANCH_SELECTION",
            value=payload,
        )
    )
    search.status = SearchStatus.CONTINUING
    await enqueue(repository.session, search.id)
    await repository.session.flush()
    return search


async def continue_search(repository, search_id):
    search = await lock_search(repository.session, search_id)
    if search.status in {SearchStatus.CANCELLED, SearchStatus.COMPLETED, SearchStatus.FAILED}:
        return search
    pending = await repository.get_pending_question(search.id)
    if pending:
        try:
            return await submit_answer(repository, search.id, pending.id, "skip")
        except ValueError:
            return await repository.get_search(search.id) or search
    await enqueue(repository.session, search.id)
    return search


async def stop_search(repository, search_id):
    search = await lock_search(repository.session, search_id)
    if search.status == SearchStatus.COMPLETED:
        return search
    search = await repository.update_search(search.id, status=SearchStatus.CANCELLED)
    pending = await repository.get_pending_question(search.id)
    if pending:
        await repository.answer_question(
            pending.id, {"value": "skip", "effect": "search cancelled"}, skipped=True
        )
    jobs = (
        await repository.session.scalars(
            select(InvestigationJob).where(
                InvestigationJob.search_run_id == search.id,
                InvestigationJob.status.in_(["PENDING", "RUNNING", "WAITING"]),
            )
        )
    ).all()
    for job in jobs:
        job.status = "CANCELLED"
    return search
