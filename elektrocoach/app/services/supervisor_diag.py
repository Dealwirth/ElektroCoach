"""Diagnose des Supervisor-Zugriffs aus dem Add-on heraus.

Die Oberflaeche meldete "Ollama nicht installiert", obwohl das Add-on lief.
Ursache war ein 403 des Supervisors auf ``GET /addons``. Diese Diagnose
zeigt in einem Aufruf, ob der Token gueltig ist, welche Rechte das Add-on
hat und was der Supervisor zu einem abgelehnten Zugriff protokolliert.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ..config import SUPERVISOR_TOKEN, SUPERVISOR_URL
from . import ollama_addon

log = logging.getLogger(__name__)

# Bekannte, aussagekraeftige Protokollzeilen des Supervisors.
_LOG_HINTS = re.compile(
    r"403|Forbidden|missing API permission|no role|Invalid token|elektrocoach|addons",
    re.IGNORECASE,
)


def _mask(token: str) -> str:
    if not token:
        return ""
    return f"{token[:4]}...{token[-4:]} ({len(token)} Zeichen)"


async def _try(method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
    try:
        data = await ollama_addon._request(method, endpoint, **kwargs)
    except ollama_addon.SupervisorError as exc:
        return {"ok": False, "endpoint": endpoint, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "endpoint": endpoint, "error": repr(exc)}
    if isinstance(data, dict):
        keys = sorted(data.keys())
        count = len(data.get("addons") or data.get("apps") or [])
        summary: Any = {"keys": keys, "count": count}
    elif isinstance(data, list):
        summary = {"list_len": len(data)}
    else:
        summary = data
    return {"ok": True, "endpoint": endpoint, "result": summary}


async def diagnostics() -> dict[str, Any]:
    result: dict[str, Any] = {
        "token_present": bool(SUPERVISOR_TOKEN),
        "token": _mask(SUPERVISOR_TOKEN),
        "supervisor_url": SUPERVISOR_URL,
    }
    if not SUPERVISOR_TOKEN:
        result["hint"] = (
            "Kein Supervisor-Token. Das Add-on laeuft nicht unter Home Assistant OS "
            "oder ohne supervisor_api."
        )
        return result

    probes = [
        ("/supervisor/info", "GET"),
        ("/info", "GET"),
        ("/addons", "GET"),
        ("/addons/self/info", "GET"),
        ("/supervisor/logs", "GET"),
    ]
    checks = {}
    logs_text = ""
    for endpoint, method in probes:
        out = await _try(method, endpoint)
        checks[endpoint] = out
        if endpoint == "/supervisor/logs" and out.get("ok"):
            data = out.get("result")
            logs_text = data if isinstance(data, str) else str(data)
    result["checks"] = checks

    self_info = checks.get("/addons/self/info", {})
    result["self"] = self_info.get("result") if self_info.get("ok") else None

    # Rechte aus der eigenen Add-on-Info ableiten.
    addons_ok = checks.get("/addons", {}).get("ok")
    if addons_ok:
        result["verdict"] = "ok"
        result["hint"] = "Der Supervisor-Zugriff funktioniert."
    else:
        result["verdict"] = "denied"
        result["hint"] = (
            "Der Supervisor lehnt /addons ab. Meist fehlt die Berechtigung "
            "hassio_api oder die Rolle ist zu niedrig (hassio_role: manager)."
        )

    if logs_text:
        hits = [line for line in logs_text.splitlines() if _LOG_HINTS.search(line)]
        result["supervisor_log_matches"] = hits[-25:]
    return result
