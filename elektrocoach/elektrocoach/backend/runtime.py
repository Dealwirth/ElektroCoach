"""Runtime bridge between the async web layer and the synchronous worker thread.

The FastAPI application owns one asyncio event loop. Background jobs run in a
plain worker thread so that a long import cannot block the web server. When a
job needs to call an async component (for example the AI dispatcher), it uses
:func:`run_coroutine`, which submits the coroutine to the main loop and waits
for the result.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Coroutine, TypeVar

logger = logging.getLogger("elektrocoach.runtime")

T = TypeVar("T")

_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def get_main_loop() -> asyncio.AbstractEventLoop | None:
    return _main_loop


def run_coroutine(coro: Coroutine[Any, Any, T], *, timeout: float | None = None) -> T:
    """Run ``coro`` on the main loop from a worker thread and return its result.

    This is only safe from a *different* thread than the event loop. Calling it
    from inside the loop thread would block the loop while waiting for a result
    that can never be produced, so that case is detected and refused instead of
    deadlocking. Async callers must therefore either ``await`` the coroutine
    directly or hand blocking work to a thread (``asyncio.to_thread``).
    """

    loop = _main_loop
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        if loop is None or running is loop:
            # We are on the loop thread. Close the coroutine so Python does not
            # warn about a never-awaited object, and report the misuse clearly.
            coro.close()
            raise RuntimeError(
                "run_coroutine darf nicht aus dem Event-Loop-Thread aufgerufen "
                "werden. Bitte die Coroutine direkt mit await ausführen oder die "
                "blockierende Arbeit über asyncio.to_thread auslagern."
            )

    if loop is not None and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()
            raise TimeoutError("Die KI-Anfrage hat zu lange gedauert.") from None
    # No running loop (tests, CLI): run it directly.
    return asyncio.run(coro)
