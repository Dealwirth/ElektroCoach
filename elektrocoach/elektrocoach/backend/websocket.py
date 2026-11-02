"""WebSocket endpoint for live progress updates.

One connection per browser tab, sending small JSON messages. To keep the load on
a Raspberry Pi low:

* the server pushes an update at most once per ``MIN_PUSH_INTERVAL`` seconds,
* only *changed* data is sent,
* each connection is closed by the client, and the server drops it on error.

Clients receive:

* ``jobs``      – queued/running/failed job counts,
* ``events``    – unresolved error/warning counts,
* ``system``    – a compact status summary (no full health report),
* ``progress``  – per-job progress for jobs that are currently running.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("elektrocoach.ws")

router = APIRouter()

MIN_PUSH_INTERVAL = 2.0
MAX_CONNECTIONS = 8


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> bool:
        await websocket.accept()
        async with self._lock:
            if len(self._connections) >= MAX_CONNECTIONS:
                # Never grow unbounded; the oldest connection is closed instead.
                oldest = self._connections.pop(0)
                try:
                    await oldest.close(code=1013)
                except Exception:  # noqa: BLE001
                    pass
            self._connections.append(websocket)
        return True

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]) -> int:
        payload = json.dumps(message, ensure_ascii=False, default=str)
        sent = 0
        async with self._lock:
            connections = list(self._connections)
        for websocket in connections:
            try:
                await websocket.send_text(payload)
                sent += 1
            except Exception:  # noqa: BLE001 - drop broken connections
                await self.disconnect(websocket)
        return sent

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


def _snapshot(context) -> dict[str, Any]:
    jobs = context.repo.job_counts()
    events = context.repo.event_counts()
    running = [j for j in context.repo.list_jobs(status="running", limit=10)]
    return {
        "type": "snapshot",
        "jobs": jobs,
        "events": events,
        "running": [
            {"id": j["id"], "type": j["type"], "progress": j.get("progress", 0),
             "message": j.get("message")}
            for j in running
        ],
        "worker_alive": context.worker.is_alive(),
        "due_cards": context.repo.count_due_cards(),
    }


@router.websocket("/api/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    context = websocket.app.state.context
    await manager.connect(websocket)
    last_snapshot: dict[str, Any] | None = None
    try:
        await websocket.send_text(json.dumps(_snapshot(context), default=str))
        while True:
            try:
                # Wait for a client message or the push interval.
                await asyncio.wait_for(websocket.receive_text(), timeout=MIN_PUSH_INTERVAL)
            except asyncio.TimeoutError:
                pass
            snapshot = _snapshot(context)
            comparable = {k: v for k, v in snapshot.items() if k != "type"}
            previous = {k: v for k, v in (last_snapshot or {}).items() if k != "type"}
            if comparable != previous:
                last_snapshot = snapshot
                await websocket.send_text(json.dumps(snapshot, default=str))
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - a websocket error must not log a traceback
        logger.debug("websocket closed: %s", exc)
    finally:
        await manager.disconnect(websocket)
