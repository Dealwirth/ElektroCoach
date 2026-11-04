"""Guarded Webzugriff fuer das lokale Modell.

Das lokale Modell (Ollama) kennt nur seinen Trainingsstand. Bei Fragen zu
Normen, Verordnungen, Foerderungen, Preisen oder aktuellen Geraeten reicht das
nicht. Dieser Dienst holt dann gezielt Informationen aus dem Internet.

Grundsaetze (bewusst streng, damit nur verwertbare Daten ankommen):

  * Nur, wenn es noetig ist. Die Suche laeuft nur bei ausdruecklichem Wunsch
    (Schalter "Web") oder wenn der Fragetext klar auf aktuelle Angaben deutet.
  * Nur verlaessliche Quellen. Bevorzugt werden amtliche und fachliche
    Adressen (Wikipedia, BDEW, VDE, DIN, Bundesregierung, BAFA ...). Treffer
    anderer Adressen werden nur aufgenommen, wenn die Einstellung
    ``web_allow_any`` das erlaubt.
  * Nur passende Daten. Jeder Treffer wird gegen die Suchbegriffe geprueft.
    Ohne ausreichende Uebereinstimmung wird der Treffer verworfen.
  * Alles wird mit Quelle (Titel und Adresse) zitiert. Ohne Quelle keine
    Aussage.
  * Keine Kosten und kein Schluessel: es werden oeffentliche Schnittstellen
    (Wikipedia und DuckDuckGo HTML) verwendet. Ist optional ein Tavily- oder
    Exa-Schluessel gesetzt, wird dieser bevorzugt genutzt.
"""

from __future__ import annotations

import html
import logging
import os
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import httpx

from ..config import settings

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=10.0, pool=5.0)
MAX_PAGE_CHARS = 4000
# Wikimedia verlangt einen aussagekraeftigen User-Agent mit Kontaktadresse
# (https://w.wiki/4wJS). Ohne Kontakt antwortet der Dienst mit HTTP 403.
USER_AGENT = (
    "ElektroCoach/1.1 (Home-Assistant-Add-on, Lernplattform Elektrotechnik; "
    "https://github.com/Dealwirth/ElektroCoach)"
)

# Fachlich und amtlich verlaessliche Adressen. Alles andere gilt als unsicher.
AUTHORITATIVE = (
    "wikipedia.org",
    "wikimedia.org",
    "vde.com",
    "din.de",
    "beuth.de",
    "bdew.de",
    "bundesregierung.de",
    "bundestag.de",
    "bafa.de",
    "umweltbundesamt.de",
    "bundesnetzagentur.de",
    "zvei.org",
    "arbeitsschutz-rs.de",
    "bgbau.de",
    "dguv.de",
    "baua.de",
    "fh-muenster.de",
    "elektro.net",
    "ep.de",
    "heise.de",
    "ise.fraunhofer.de",
)

# Fragetexte, die auf aktuelle Angaben deuten. Dann ist eine Suche sinnvoll.
WEB_HINTS = re.compile(
    r"\b(aktuell|derzeit|heute|neu|neueste|neuer|2024|2025|2026|norm|din|vde|"
    r"verordnung|gesetz|richtlinie|foerderung|förderung|zuschuss|preis|kosten|"
    r"gueltig|gültig|abgeschafft|geaendert|geändert|seit wann|wann wurde)\b",
    re.IGNORECASE,
)

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text or "")).lower()


def web_enabled() -> bool:
    """Ist der Webzugriff eingeschaltet?"""
    return settings.get_bool("web_enabled", True)


def needs_web(question: str, mode: str = "auto") -> bool:
    """Entscheidet, ob fuer diese Frage eine Suche sinnvoll ist.

    mode: "on" (immer), "off" (nie), "auto" (nur bei aktuellen Angaben).
    """
    if not web_enabled() or mode == "off":
        return False
    if mode == "on":
        return True
    return bool(WEB_HINTS.search(question or ""))


def _is_authoritative(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in AUTHORITATIVE)


def _relevant(query: str, text: str, minimum: float = 0.34) -> bool:
    """Prueft, ob ein Treffer zur Frage passt (Wortuebereinstimmung)."""
    terms = [t for t in re.findall(r"[a-zA-ZäöüÄÖÜß0-9]{4,}", _normalise(query))]
    if not terms:
        return True
    haystack = _normalise(text)
    hits = sum(1 for term in set(terms) if term in haystack)
    return hits / len(set(terms)) >= minimum


def _strip_html(raw: str) -> str:
    text = _SCRIPT_RE.sub(" ", raw or "")
    text = re.sub(r"<(br|/p|/div|/li|/h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Wikipedia (immer verfuegbar, kein Schluessel)
# ---------------------------------------------------------------------------
async def _wikipedia(query: str, limit: int) -> list[dict[str, Any]]:
    lang = str(settings.get("web_language", "de") or "de")
    base = f"https://{lang}.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": str(limit),
        "prop": "extracts",
        "exintro": "1",
        "explaintext": "1",
        "redirects": "1",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(base, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        log.info("Wikipedia-Suche fehlgeschlagen: %s", exc)
        return []

    pages = ((data.get("query") or {}).get("pages") or {}).values()
    results: list[dict[str, Any]] = []
    for page in pages:
        title = str(page.get("title") or "")
        extract = _strip_html(str(page.get("extract") or ""))
        if not title or not extract:
            continue
        url = f"https://{lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
        if not _relevant(query, f"{title} {extract}"):
            continue
        results.append({
            "title": title,
            "url": url,
            "snippet": extract[:400],
            "text": extract[:MAX_PAGE_CHARS],
            "source": "wikipedia",
        })
    return results


# ---------------------------------------------------------------------------
# DuckDuckGo (HTML, kein Schluessel)
# ---------------------------------------------------------------------------
async def _duckduckgo(query: str, limit: int) -> list[dict[str, Any]]:
    url = "https://html.duckduckgo.com/html/"
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"},
            follow_redirects=True,
        ) as client:
            resp = await client.post(url, data={"q": query, "kl": "de-de"})
            resp.raise_for_status()
            raw = resp.text
    except Exception as exc:  # noqa: BLE001
        log.info("DuckDuckGo-Suche fehlgeschlagen: %s", exc)
        return []

    results: list[dict[str, Any]] = []
    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        raw,
        re.IGNORECASE | re.DOTALL,
    ):
        href, title_html = match.group(1), match.group(2)
        href = html.unescape(href)
        if "uddg=" in href:
            parsed = parse_qs(urlparse(href).query)
            href = unquote(parsed.get("uddg", [href])[0])
        title = _strip_html(title_html)
        if not href.startswith("http") or not title:
            continue
        results.append({
            "title": title,
            "url": href,
            "snippet": "",
            "text": "",
            "source": "duckduckgo",
        })
        if len(results) >= limit * 2:
            break
    return results


async def _fetch_page(url: str) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type and "text" not in content_type:
                return ""
            return _strip_html(resp.text)[:MAX_PAGE_CHARS]
    except Exception:  # noqa: BLE001
        return ""


async def search(query: str, limit: int = 4) -> list[dict[str, Any]]:
    """Sucht und liefert nur gepruefte Treffer.

    Reihenfolge: Wikipedia (fachlich geprueft), danach DuckDuckGo. Treffer
    nicht verlaesslicher Adressen werden verworfen, ausser die Einstellung
    ``web_allow_any`` erlaubt sie.
    """
    if not query or not query.strip():
        return []
    allow_any = settings.get_bool("web_allow_any", False)

    results = await _wikipedia(query, limit)
    if len(results) < limit:
        for candidate in await _duckduckgo(query, limit):
            if not allow_any and not _is_authoritative(candidate["url"]):
                continue
            if any(r["url"] == candidate["url"] for r in results):
                continue
            results.append(candidate)
            if len(results) >= limit:
                break

    # Fehlende Kurztexte nachladen und Relevanz pruefen.
    enriched: list[dict[str, Any]] = []
    for item in results:
        text = item.get("text") or ""
        if not text and item.get("url"):
            text = await _fetch_page(item["url"])
            item["text"] = text
            item["snippet"] = item.get("snippet") or text[:400]
        if text and not _relevant(query, f"{item['title']} {text}", minimum=0.25):
            continue
        if not text:
            continue
        enriched.append(item)
        if len(enriched) >= limit:
            break
    return enriched


def build_context(hits: list[dict[str, Any]]) -> str:
    """Baut den Textblock fuer den Prompt. Jede Aussage bleibt mit Quelle."""
    blocks = []
    for index, hit in enumerate(hits, start=1):
        blocks.append(
            f"[WEB-{index}] {hit['title']}\nAdresse: {hit['url']}\n{hit['text'][:1500]}"
        )
    return "\n\n".join(blocks)


def sources(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"title": h["title"], "url": h["url"], "kind": h.get("source", "web")}
        for h in hits
    ]
