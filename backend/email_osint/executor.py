"""Asynchronous parallel task scheduler and executor for Email OSINT."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx

from .base_source import BaseEmailSource
from .cache import EmailOSINTCache
from .registry import EmailSourceRegistry
from .resilience import CircuitBreaker
from .schemas import EmailSourceResult, EmailSourceStatus


class EmailTaskExecutor:
    """Parallel, bounded async scheduler for executing Email OSINT source adapters."""

    def __init__(
        self,
        registry: EmailSourceRegistry,
        *,
        max_concurrency: int = 10,
        per_source_timeout: float = 6.0,
        global_timeout: float = 20.0,
        cache: EmailOSINTCache | None = None,
    ) -> None:
        self.registry = registry
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.per_source_timeout = per_source_timeout
        self.global_timeout = global_timeout
        self.cache = cache or EmailOSINTCache()
        self.circuit_breakers: dict[str, CircuitBreaker] = {
            s.name: CircuitBreaker(s.name) for s in registry
        }

    async def execute_all(
        self,
        email: str,
        *,
        context: dict[str, Any] | None = None,
        event_callback: Callable[[EmailSourceResult], Any] | None = None,
    ) -> list[EmailSourceResult]:
        """Run all eligible source adapters concurrently within bounded limits."""

        context = context or {}
        async with httpx.AsyncClient(
            timeout=self.per_source_timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=30),
        ) as client:
            ctx = {**context, "client": client}
            sources = self.registry.list_sources()

            tasks = [
                self._run_single_source(source, email, ctx, event_callback)
                for source in sources
            ]

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self.global_timeout,
                )
            except TimeoutError:
                results = []

            final_results: list[EmailSourceResult] = []
            for item in results:
                if isinstance(item, EmailSourceResult):
                    final_results.append(item)
                elif isinstance(item, Exception):
                    pass

            return final_results

    async def _run_single_source(
        self,
        source: BaseEmailSource,
        email: str,
        context: dict[str, Any],
        event_callback: Callable[[EmailSourceResult], Any] | None = None,
    ) -> EmailSourceResult:
        cache_key = f"email_osint:{source.name}:{email.casefold()}"
        cached = self.cache.get(cache_key)
        if cached and isinstance(cached, EmailSourceResult):
            if event_callback:
                try:
                    await event_callback(cached)
                except Exception:
                    pass
            return cached

        cb = self.circuit_breakers.setdefault(source.name, CircuitBreaker(source.name))
        if not cb.check_allowed():
            result = source._result(
                EmailSourceStatus.UNKNOWN,
                message=f"Circuit open for source {source.name} due to consecutive failures.",
            )
            return result

        async with self.semaphore:
            start = time.monotonic()
            try:
                result = await asyncio.wait_for(
                    source.check(email, context),
                    timeout=self.per_source_timeout,
                )
                cb.record_success()
            except TimeoutError:
                cb.record_failure()
                duration = (time.monotonic() - start) * 1000
                result = source._result(
                    EmailSourceStatus.TIMEOUT,
                    message=f"{source.name} request timed out after {self.per_source_timeout}s",
                    response_time_ms=duration,
                )
            except Exception as exc:
                cb.record_failure()
                duration = (time.monotonic() - start) * 1000
                result = source._result(
                    EmailSourceStatus.ERROR,
                    message=f"{type(exc).__name__}: {exc}",
                    response_time_ms=duration,
                )

            self.cache.set(cache_key, result)
            if event_callback:
                try:
                    res_coro = event_callback(result)
                    if asyncio.iscoroutine(res_coro):
                        await res_coro
                except Exception:
                    pass

            return result
