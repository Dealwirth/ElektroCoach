"""KI-Nutzungsprotokoll und Kontingentverwaltung.

Alle KI-Aufrufe werden protokolliert. Fuer Gemini wird das kostenlose
Tageskontingent mitgezaehlt, damit die App bei erschoepftem Kontingent
selbststaendig auf das lokale Modell ausweicht, statt Fehler zu erzeugen.
"""

from __future__ import annotations

import datetime as _dt
import logging
import threading
from typing import Any

from .. import db
from ..config import settings

log = logging.getLogger(__name__)

# Free-Tier-Richtwerte pro Tag (AI Studio, Projekt-Kontingent).
# Bewusst konservativ gewaehlt, damit das Limit nicht ueberschritten wird.
DAILY_LIMITS: dict[str, int] = {
    "gemini": 450,
}
GLOBAL_DAILY_LIMIT = 500

_lock = threading.Lock()


def _today() -> str:
    return _dt.date.today().isoformat()


def record(provider: str, model: str, task: str, ok: bool, error: str | None = None) -> None:
    """Protokolliert einen Aufruf. Ein Protokollfehler darf die KI nicht stoeren."""
    try:
        db.insert(
            "INSERT INTO ai_usage(id, provider, model, task, ok, error, day, created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (db.new_id(), provider, model, task, 1 if ok else 0, error, _today(), db.now()),
        )
    except Exception as exc:  # noqa: BLE001 - Protokoll ist nachrangig
        log.debug("Nutzung konnte nicht protokolliert werden: %s", exc)


def usage_today() -> dict[str, Any]:
    rows = db.query(
        "SELECT provider, COUNT(*) AS n, SUM(ok) AS ok "
        "FROM ai_usage WHERE day = ? GROUP BY provider",
        (_today(),),
    )
    out: dict[str, Any] = {}
    total = 0
    for row in rows:
        out[row["provider"]] = {"calls": row["n"], "ok": row["ok"] or 0}
        total += row["n"]
    out["total"] = total
    return out


def calls_today(provider: str) -> int:
    row = db.query_one(
        "SELECT COUNT(*) AS n FROM ai_usage WHERE day = ? AND provider = ?",
        (_today(), provider),
    )
    return int(row["n"]) if row else 0


def quota_state(provider: str) -> dict[str, Any]:
    used = calls_today(provider)
    limit = DAILY_LIMITS.get(provider, 0)
    return {
        "provider": provider,
        "used": used,
        "limit": limit,
        "remaining": max(limit - used, 0) if limit else None,
        "exhausted": bool(limit and used >= limit),
        "day": _today(),
    }


def can_use(provider: str) -> bool:
    limit = DAILY_LIMITS.get(provider)
    if provider == "gemini":
        # 0 bedeutet: keine Aufrufe erlaubt. Negative Werte = unbegrenzt.
        limit = settings.get_int("gemini_daily_limit", limit or 0)
    with _lock:
        used = calls_today(provider)
        if limit is not None and limit >= 0 and used >= limit:
            return False
        if provider == "gemini" and used >= GLOBAL_DAILY_LIMIT:
            return False
        return True


def recent_errors(limit: int = 10) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT provider, model, task, error, created_at FROM ai_usage "
        "WHERE ok = 0 ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]
