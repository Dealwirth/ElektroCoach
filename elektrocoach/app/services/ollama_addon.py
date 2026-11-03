"""Verwaltung des Ollama-Add-ons ueber den Home-Assistant-Supervisor.

Die Lernplattform laeuft als eigenes Add-on neben einem Ollama-Add-on. Damit
der lokale KI-Betrieb ohne Handarbeit funktioniert, kann dieses Modul:

  * pruefen, ob ein Ollama-Add-on installiert und gestartet ist,
  * es aus dem Add-on-Store installieren und starten,
  * Modelle ueber die Ollama-Schnittstelle des Add-ons herunterladen,
  * die passende Netzwerkadresse ermitteln.

Wichtig zur Netzwerkadresse:
  Add-ons ohne Host-Netzwerk teilen sich ein Docker-Netz. Sie erreichen sich
  gegenseitig ueber den DNS-Namen des Containers. Der Supervisor liefert
  diesen Namen als "hostname" des Add-ons (z. B. "76e18fb5-ollama"). Eine
  feste Adresse wie "localhost:11434" waere falsch, weil "localhost" im
  ElektroCoach-Container auf diesen selbst zeigt.

Es werden ausschliesslich kostenlose, oertliche Ablaeufe ausgeloest. Es findet
keine Aktivierung von Abrechnung oder kostenpflichtigen Diensten statt.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from ..config import SUPERVISOR_TOKEN, SUPERVISOR_URL, settings

log = logging.getLogger(__name__)

# Suchbegriffe, mit denen ein Ollama-Add-on im Store/der Add-on-Liste erkannt
# wird. Das offizielle Add-on heisst "Ollama", es gibt aber auch Nachbauten.
OLLAMA_HINTS = ("ollama",)
# Zeitlimits: Installation und Modell-Download dauern auf dem Pi laenger.
INSTALL_TIMEOUT = 1800.0
PULL_TIMEOUT = 3600.0
INFO_TIMEOUT = 20.0


class SupervisorError(RuntimeError):
    """Fehler beim Zugriff auf den Supervisor."""


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }


def available() -> bool:
    return bool(SUPERVISOR_TOKEN)


def unwrap(data: Any) -> Any:
    """Der Supervisor verpackt jede Antwort in {"result": "ok", "data": ...}.

    Ohne dieses Auspacken liest die Add-on-Erkennung immer eine leere Liste
    und meldet faelschlich "nicht installiert". Bei Fehlern liefert der
    Supervisor {"result": "error", "message": ...}; daraus wird ein
    SupervisorError mit der Originalmeldung.
    """
    if isinstance(data, dict) and "result" in data:
        if data.get("result") == "error":
            message = data.get("message") or "Unbekannter Supervisor-Fehler"
            raise SupervisorError(str(message))
        if "data" in data:
            return data["data"]
    return data


async def _request(
    method: str,
    endpoint: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = INFO_TIMEOUT,
) -> Any:
    if not available():
        raise SupervisorError("Kein Supervisor-Token verfuegbar (kein Home-Assistant-OS).")
    url = f"{SUPERVISOR_URL}{endpoint}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
        resp = await client.request(method, url, headers=_headers(), json=json_body)
    if resp.status_code >= 400:
        raise SupervisorError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    if not resp.content:
        return None
    try:
        return unwrap(resp.json())
    except ValueError:
        return {"raw": resp.text[:500]}


async def _all_addons() -> list[dict[str, Any]]:
    """Alle installierten Add-ons. Faellt auf die V2-Route zurueck.

    Der Supervisor liefert je nach Version ein Objekt ``{"addons": [...]}``
    oder direkt eine Liste. Beide Formen werden verarbeitet. Scheitern alle
    Routen, wird der letzte Fehler weitergereicht, damit die Oberflaeche eine
    Ursache statt eines stillen "nicht installiert" anzeigen kann.
    """
    last_error: SupervisorError | None = None
    for endpoint in ("/addons", "/apps"):
        try:
            data = await _request("GET", endpoint)
        except SupervisorError as exc:
            last_error = exc
            continue
        if isinstance(data, list):
            items = data
        else:
            items = (data or {}).get("addons") or (data or {}).get("apps") or []
        if items:
            return list(items)
    if last_error is not None:
        raise last_error
    return []


def _is_ollama(addon: dict[str, Any]) -> bool:
    haystack = f"{addon.get('slug', '')} {addon.get('name', '')}".lower()
    return any(hint in haystack for hint in OLLAMA_HINTS)


async def find_installed() -> dict[str, Any] | None:
    """Erstes installiertes Ollama-Add-on, sonst None."""
    for addon in await _all_addons():
        if _is_ollama(addon):
            return addon
    return None


async def addon_info(slug: str) -> dict[str, Any] | None:
    for endpoint in (f"/addons/{slug}/info", f"/apps/{slug}/info"):
        try:
            data = await _request("GET", endpoint)
        except SupervisorError:
            continue
        if isinstance(data, dict) and data.get("slug"):
            return data
    return None


async def find_in_store() -> dict[str, Any] | None:
    """Erstes Ollama-Add-on im Store, das installiert werden koennte."""
    for endpoint in ("/store/addons", "/store/apps"):
        try:
            data = await _request("GET", endpoint)
        except SupervisorError:
            continue
        items = (data or {}).get("addons") or (data or {}).get("apps") or []
        for addon in items:
            if _is_ollama(addon):
                return addon
    return None


def _slug_from_hostname(hostname: str) -> str:
    """Wandelt einen Add-on-Hostnamen in eine nutzbare Adresse um.

    "76e18fb5-ollama" wird zu "http://76e18fb5-ollama:11434".
    """
    host = hostname.strip().lower()
    host = re.sub(r"[^a-z0-9-]", "-", host).strip("-")
    return host


def url_from_addon(addon: dict[str, Any], port: int = 11434) -> str | None:
    """Ermittelt die Ollama-Adresse aus den Add-on-Angaben."""
    hostname = addon.get("hostname") or addon.get("slug")
    if not hostname:
        return None
    host = _slug_from_hostname(str(hostname))
    if not host:
        return None
    return f"http://{host}:{port}"


def _port_from_addon(addon: dict[str, Any], default: int = 11434) -> int:
    network = addon.get("network") or {}
    for key in network:
        match = re.match(r"^(\d+)/tcp$", str(key))
        if match:
            return int(match.group(1))
    return default


async def _wait_until_up(base_url: str, attempts: int = 60, delay: float = 3.0) -> bool:
    """Wartet, bis die Ollama-Schnittstelle antwortet."""
    url = f"{base_url.rstrip('/')}/api/tags"
    for _ in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                resp = await client.get(url)
                if resp.status_code < 400:
                    return True
        except Exception:  # noqa: BLE001 - Start dauert, Fehler sind erwartbar
            pass
        await asyncio.sleep(delay)
    return False


async def ensure_running(
    wait_attempts: int = 30, wait_delay: float = 3.0
) -> dict[str, Any]:
    """Stellt sicher, dass ein Ollama-Add-on laeuft, und gibt seine Adresse zurueck.

    Ablauf:
      1. Installiertes Add-on suchen. Gefunden -> starten, falls nicht gestartet.
      2. Sonst im Store suchen und installieren.
      3. Adresse ermitteln, Erreichbarkeit abwarten und in den Einstellungen
         hinterlegen.

    Das Warten ist begrenzt (Standard 90 s), damit die Weboberflaeche hinter dem
    Ingress nicht in eine Zeitueberschreitung laeuft. Laenger dauernde Starts
    werden ueber /ai/ollama/addon (Status) erneut geprueft.
    """
    if not available():
        return {
            "ok": False,
            "supervisor": False,
            "error": "Kein Supervisor-Token (kein Home-Assistant-OS).",
        }

    installed = await find_installed()
    created = False
    if installed is None:
        store_entry = await find_in_store()
        if store_entry is None:
            return {
                "ok": False,
                "error": "Kein Ollama-Add-on im Store gefunden. Bitte zuerst den "
                         "Add-on-Store aktualisieren oder Ollama manuell installieren.",
            }
        slug = store_entry.get("slug")
        log.info("Installiere Ollama-Add-on %s", slug)
        try:
            await _request(
                "POST", f"/store/addons/{slug}/install",
                json_body={"background": False}, timeout=INSTALL_TIMEOUT,
            )
        except SupervisorError as exc:
            return {"ok": False, "error": f"Installation fehlgeschlagen: {exc}"}
        created = True
        installed = await find_installed() or store_entry

    slug = installed.get("slug")
    state = str(installed.get("state") or "")
    started = False
    if state != "started":
        log.info("Starte Ollama-Add-on %s", slug)
        try:
            await _request("POST", f"/addons/{slug}/start", timeout=INSTALL_TIMEOUT)
        except SupervisorError as exc:
            # V2-Route als Rueckfall.
            try:
                await _request("POST", f"/apps/{slug}/start", timeout=INSTALL_TIMEOUT)
            except SupervisorError:
                return {"ok": False, "error": f"Start fehlgeschlagen: {exc}"}
        started = True

    info = await addon_info(slug) or installed
    port = _port_from_addon(info)
    url = url_from_addon(info, port)
    if not url:
        return {"ok": False, "error": "Add-on-Hostname konnte nicht ermittelt werden."}

    reachable = await _wait_until_up(url, attempts=wait_attempts, delay=wait_delay)
    if reachable:
        settings.set_runtime("ollama_url", url)
        from .. import db

        db.set_setting("ollama_url", url)
        settings.set_runtime("ollama_enabled", True)
        db.set_setting("ollama_enabled", "True")

    return {
        "ok": reachable,
        "slug": slug,
        "url": url,
        "installed": True,
        "started": started,
        "created": created,
        "reachable": reachable,
        "state": (info or {}).get("state"),
        "error": None if reachable else "Add-on laeuft, antwortet aber noch nicht.",
    }


async def pull_model(model: str) -> dict[str, Any]:
    """Laedt ein Modell in das laufende Ollama-Add-on (kostenlos, lokal)."""
    base = str(settings.get("ollama_url", "") or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "Keine Ollama-Adresse bekannt. Bitte zuerst einrichten."}
    model = (model or "").strip()
    if not model:
        return {"ok": False, "error": "Kein Modellname angegeben."}
    payload = {"name": model, "stream": False}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(PULL_TIMEOUT)) as client:
            resp = await client.post(f"{base}/api/pull", json=payload)
            if resp.status_code >= 400:
                return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        return {"ok": True, "model": model}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


async def installed_models() -> dict[str, Any]:
    base = str(settings.get("ollama_url", "") or "").rstrip("/")
    if not base:
        return {"ok": False, "models": [], "error": "Keine Ollama-Adresse bekannt."}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(f"{base}/api/tags")
            resp.raise_for_status()
            data = resp.json()
        models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        return {"ok": True, "models": models, "url": base}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "models": [], "url": base, "error": str(exc)[:200]}


async def status() -> dict[str, Any]:
    """Kurzer Status fuer die Oberflaeche."""
    result: dict[str, Any] = {
        "supervisor": available(),
        "installed": False,
        "state": None,
        "slug": None,
        "url": str(settings.get("ollama_url", "") or ""),
    }
    if not available():
        return result
    try:
        addon = await find_installed()
    except SupervisorError as exc:
        result["error"] = str(exc)
        return result
    if addon:
        result["installed"] = True
        result["state"] = addon.get("state")
        result["slug"] = addon.get("slug")
        suggested = url_from_addon(addon)
        if suggested:
            result["suggested_url"] = suggested
    else:
        # Kein Ollama-Add-on erkannt: die tatsaechlich sichtbaren Add-ons
        # mitliefern, damit die Ursache sichtbar ist (z. B. fehlende Rechte).
        try:
            seen = await _all_addons()
            result["addons_seen"] = [
                {"slug": a.get("slug"), "name": a.get("name"), "state": a.get("state")}
                for a in seen
            ]
        except SupervisorError as exc:
            result["error"] = str(exc)
    return result
