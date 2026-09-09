"""Bounded non-interactive child processes; cancellation terminates the owned process group."""

import asyncio
import os
import signal


async def run_process(*args, cwd=None, budget_seconds=60, max_bytes=2_000_000):
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    async def read(stream):
        result = bytearray()
        while chunk := await stream.read(16384):
            result.extend(chunk)
            if len(result) > max_bytes:
                raise ValueError("Connector output exceeds byte budget")
        return bytes(result)

    tasks = [asyncio.create_task(read(process.stdout)), asyncio.create_task(read(process.stderr))]
    try:
        async with asyncio.timeout(budget_seconds):
            out, err = await asyncio.gather(*tasks)
            await process.wait()
        return process.returncode, out, err
    finally:
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
