"""Handschrift- und Formelerkennung mit einem lokalen Bildmodell (Ollama).

TrOCR liest einzelne Zeilen gedruckter oder sauberer Handschrift sehr gut, aber
Rechenwege mit Formelzeichen, Bruechen und Einheiten ueberfordern es. Ein
lokales Bildmodell (Standard: ``qwen2.5vl:3b``) sieht die ganze Seite und
erkennt den Zusammenhang: Formeln, Rechenoperatoren, Einheiten und die
Zuordnung von Aufgabennummern.

Der Ablauf ist zweistufig und bleibt vollstaendig offline:

  1. TrOCR liefert einen ersten Entwurf je Zeile (schnell, kostenlos).
  2. Das Bildmodell liest die Seite erneut und erhaelt den Entwurf als
     Hinweis. Es darf ihn korrigieren, aber nichts erfinden.

Ist kein Bildmodell vorhanden, bleibt der TrOCR-Entwurf erhalten. Es wird nie
Text geloescht, wenn das Modell nichts Brauchbares liefert.
"""

from __future__ import annotations

import base64
import io
import logging
import re
from typing import Any

from ..config import settings
from . import ollama

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# Aufgabenbezogene Systemanweisung. Bewusst knapp und streng: das Modell soll
# abschreiben, nicht erklaeren und nicht rechnen.
SYSTEM = (
    "Du bist ein praezises OCR-System fuer handgeschriebene Rechenwege und "
    "Formeln aus der Elektrotechnik-Ausbildung. "
    "Regeln: "
    "1) Schreibe genau ab, was auf dem Bild steht. Rechne nichts nach und "
    "erklaere nichts. "
    "2) Uebernimm Formelzeichen (R, I, U, P, A, l, rho), Indizes, Einheiten "
    "(mm2, m, V, A, Ohm) und Rechenoperatoren (+, -, *, /, =) exakt. "
    "3) Achte auf die Verwechslungsgefahr: 'rho' (ρ) ist der spezifische "
    "Widerstand, 'A' der Querschnitt, 'l' (kleines L) die Laenge und '1' die "
    "Ziffer Eins. Schreibe ρ als 'rho', das kleine L als 'l'. "
    "4) Schreibe Brueche als 'Zaehler / Nenner' in einer Zeile. "
    "5) Kennzeichne eine unleserliche Stelle mit [unklar]; rate nicht. "
    "6) Gib je Zeile des Blattes eine Zeile aus, in der Reihenfolge von oben "
    "nach unten. Nummeriere Aufgabenteile so, wie sie dastehen (z. B. '2. a)'). "
    "7) Antworte ausschliesslich mit dem abgeschriebenen Text, ohne Vorwort, "
    "ohne Codeblock und ohne Erklaerung."
)

PROMPT = (
    "Transkribiere den gesamten handschriftlichen Text dieses Blattes "
    "vollstaendig und zeilengetreu. Achte besonders auf Zahlen, Einheiten "
    "(mm2, m, V, A) und Formelzeichen. Gib nur den Text aus."
)

PROMPT_WITH_HINT = (
    "Ein Zeichenerkennungsprogramm hat folgenden Entwurf geliefert. Er ist "
    "fehlerhaft, besonders bei Formeln und Zahlen.\n\n"
    "ENTWURF:\n{draft}\n\n"
    "Lies nun das Bild und gib den korrigierten, vollstaendigen Text aus. "
    "Uebernimm die Zeilenstruktur des Bildes. Gib nur den Text aus."
)

MAX_DRAFT_CHARS = 4000

# Prompt fuer eine einzelne Zeile. Bewusst kurz und streng: nur abschreiben.
LINE_PROMPT = (
    "Schreibe genau ab, was in dieser Zeile steht. Nutze rho fuer den "
    "spezifischen Widerstand, L fuer die Laenge und A fuer den Querschnitt. "
    "Einheiten: (Ohm*mm2)/m, m, mm2, Ohm, mOhm, V, A. Schreibe Brueche als "
    "'(Zaehler) / (Nenner)'. Dezimalzahlen mit Komma. Gib nur den Text dieser "
    "einen Zeile aus, ohne Vorwort und ohne Erklaerung."
)

# Handschrift wird am besten Zeile fuer Zeile gelesen. Auf einer ganzen Seite
# verliert das Bildmodell bei dichten Rechenwegen den Faden und erfindet Zahlen.
# Jede Zeile wird daher einzeln auf diese Hoehe skaliert und getrennt gelesen.
LINE_TARGET_HEIGHT = 256
# Zeilen ueber dieser Breite werden zusaetzlich in Spalten geteilt (lange
# Rechenzeilen mit mehreren Termen). Typische Zeilen bleiben ungeteilt.
LINE_MAX_WIDTH = 3200
# Ohne Zeilensegmentierung wird die ganze Seite auf diese Breite skaliert.
VISION_TARGET_WIDTH = 1600
VISION_NUM_CTX = 8192
VISION_NUM_PREDICT = 1536
# Kontextfenster fuer den kurzen Aufruf je Zeile.
LINE_NUM_CTX = 4096
LINE_NUM_PREDICT = 256

# Dritte Stufe: Formelzeichen berichtigen. Das Bildmodell liest Zahlen und
# Einheiten gut, verwechselt aber Zeichen wie rho (ϱ) mit "h" oder "g". Ein
# Textmodell mit Elektrotechnik-Kenntnis zieht solche Stellen auf die richtige
# Formel. Zahlen duerfen dabei nicht veraendert werden.
REFINE_SYSTEM = (
    "Du bist ein Korrektor fuer abgeschriebene Rechenwege aus der "
    "Elektrotechnik. Du erhaeltst einen Text, der mit Zeichenerkennung aus "
    "einem Bild entstanden ist. "
    "Regeln: "
    "1) Berichtige nur offensichtliche Zeichenfehler bei Formelzeichen und "
    "Einheiten, indem du die ueblichen Formeln der Elektrotechnik heranziehst "
    "(z. B. R = rho * l / A, U = R * I, P = U * I). "
    "2) Aendere NIEMALS eine Zahl. Keine Rechnung durchfuehren, keine Ergebnisse "
    "ersetzen. "
    "3) Uebliche Verwechslungen: rho wird oft als 'h', 'g' oder 'p' gelesen, "
    "der Querschnitt A als 'a', die Laenge l als '1' oder 'I'. "
    "4) Schreibe Formelzeichen als rho, A, l, R, U, I, P. Einheiten als "
    "mm2, m, V, A, Ohm. "
    "5) Behalte die Zeilenstruktur und die Aufgabennummern genau bei. "
    "6) Gib ausschliesslich den korrigierten Text aus, ohne Vorwort und ohne "
    "Codeblock."
)

REFINE_PROMPT = (
    "Hier der erkannte Text eines Elektrotechnik-Rechenwegs. Berichtige nur "
    "Formelzeichen und Einheiten, niemals Zahlen:\n\n{text}"
)


def _page_image_bytes(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def is_enabled() -> bool:
    return settings.get_bool("ocr_use_vision_model", False)


async def installed_vision_models() -> list[str]:
    health = await ollama.health()
    return [name for name in health.get("models", []) if ollama.is_vision_model(name)]


async def available() -> bool:
    """True, wenn Ollama laeuft und ein Bildmodell installiert ist."""
    if not ollama.is_enabled():
        return False
    models = await installed_vision_models()
    if not models:
        return False
    wanted = ollama.vision_model()
    return any(name == wanted or name.startswith(wanted.split(":")[0]) for name in models)


def _clean(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> list[str]:
    return _NUMBER_RE.findall(text or "")


def refine_enabled() -> bool:
    return settings.get_bool("ocr_refine_formulas", False)


async def refine_formulas(text: str, *, model_name: str | None = None) -> dict[str, Any]:
    """Berichtigt Formelzeichen mit dem lokalen Textmodell.

    Der Text des Bildmodells ist bei Zahlen und Einheiten gut, verwechselt aber
    Formelzeichen. Das Textmodell zieht diese Stellen auf die uebliche Formel.
    Die Zahlen muessen unveraendert bleiben; sonst wird das Ergebnis verworfen.
    """
    if not ollama.is_enabled():
        return {"ok": False, "text": text, "error": "Ollama ist deaktiviert"}
    source = (text or "").strip()
    if not source:
        return {"ok": False, "text": text, "error": "leerer Text"}
    result = await ollama.chat(
        REFINE_PROMPT.format(text=source[:MAX_DRAFT_CHARS]),
        system=REFINE_SYSTEM,
        task="handwriting_refine",
        temperature=0.0,
        num_ctx=4096,
        model_name=model_name,
        num_predict=2048,
    )
    if not result.get("ok"):
        return {"ok": False, "text": text, "error": result.get("error")}
    refined = _clean(str(result.get("text") or ""))
    if not refined:
        return {"ok": False, "text": text, "error": "Leere Antwort"}
    if _numbers(refined) != _numbers(source):
        # Zahlen wurden angetastet: Ergebnis ist unbrauchbar.
        return {"ok": False, "text": text, "error": "Zahlen wurden veraendert"}
    return {"ok": True, "text": refined, "model": result.get("model"), "error": None}


def _scaled(image: Any, target_width: int = VISION_TARGET_WIDTH) -> Any:
    """Skaliert ein Bild auf die Zielbreite (nie verkleinern unter das Original)."""
    width, height = image.size
    if width <= 0 or height <= 0:
        return image
    if width >= target_width:
        return image
    factor = target_width / width
    return image.resize((int(round(width * factor)), int(round(height * factor))), Image.LANCZOS)


def _line_image(line: Any) -> Any:
    """Skaliert eine Zeile auf die Lesehoehe des Bildmodells."""
    if line.height <= 0 or line.height >= LINE_TARGET_HEIGHT:
        return line
    factor = LINE_TARGET_HEIGHT / line.height
    return line.resize((int(round(line.width * factor)), LINE_TARGET_HEIGHT), Image.LANCZOS)


def _line_slices(line: Any) -> list[Any]:
    """Teilt eine ueberlange Zeile in lesbare Spalten."""
    if line.width <= LINE_MAX_WIDTH:
        return [line]
    parts = int(line.width / LINE_MAX_WIDTH) + 1
    width = line.width // parts
    overlap = int(width * 0.05)
    crops = []
    for index in range(parts):
        left = max(0, index * width - overlap)
        right = min(line.width, (index + 1) * width + overlap)
        crops.append(line.crop((left, 0, right, line.height)))
    return crops


def _merge_lines(lines: list[str]) -> str:
    """Fuegt Zeilentexte zusammen und entfernt Wiederholungen an den Nahten."""
    merged: list[str] = []
    for line in lines:
        text = (line or "").strip()
        if not text:
            continue
        if merged and text == merged[-1]:
            continue
        merged.append(text)
    return "\n".join(merged)


async def _read_line(image: Any, prompt: str, selected: str) -> str | None:
    """Liest ein Zeilenbild. Gibt ``None`` zurueck, wenn das Modell scheitert."""
    image_b64 = base64.b64encode(_page_image_bytes(image)).decode("ascii")
    result = await ollama.chat(
        prompt,
        system=SYSTEM,
        images=[image_b64],
        task="handwriting_vision",
        temperature=0.0,
        num_ctx=LINE_NUM_CTX,
        model_name=selected,
        num_predict=LINE_NUM_PREDICT,
    )
    if not result.get("ok"):
        return None
    text = _clean(str(result.get("text") or ""))
    return text or None


async def transcribe(
    image: Any,
    draft: str | None = None,
    *,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Liest eine Seite mit dem lokalen Bildmodell, Zeile fuer Zeile.

    Handschrift wird am zuverlaessigsten Zeile fuer Zeile gelesen: jede Zeile
    wird auf Lesehoehe skaliert und einzeln erkannt. So erfindet das Modell
    keine Zahlen, wie es auf einer dichten Gesamtseite passiert.

    Rueckgabe: ``{ok, text, model, error}``.
    """
    if not ollama.is_enabled():
        return {"ok": False, "text": "", "model": None, "error": "Ollama ist deaktiviert"}

    selected = model_name or ollama.vision_model()
    used_model = selected

    lines: list[str] = []
    try:
        from . import handwriting

        segments = handwriting.segment_lines(image) if handwriting.available() else []
    except Exception as exc:  # noqa: BLE001
        log.warning("Zeilensegmentierung fehlgeschlagen: %s", exc)
        segments = []

    if segments:
        for segment in segments:
            for part in _line_slices(_line_image(segment)):
                text = await _read_line(part, LINE_PROMPT, selected)
                if text is None:
                    continue
                lines.append(text)
        if lines:
            return {"ok": True, "text": _merge_lines(lines), "model": used_model, "error": None}

    # Keine Zeilen oder kein Ergebnis: die ganze Seite in einem Zug lesen.
    draft_text = (draft or "").strip()[:MAX_DRAFT_CHARS]
    prompt = PROMPT_WITH_HINT.format(draft=draft_text) if draft_text else PROMPT
    image_b64 = base64.b64encode(_page_image_bytes(_scaled(image))).decode("ascii")
    result = await ollama.chat(
        prompt,
        system=SYSTEM,
        images=[image_b64],
        task="handwriting_vision",
        temperature=0.0,
        num_ctx=VISION_NUM_CTX,
        model_name=selected,
        num_predict=VISION_NUM_PREDICT,
    )
    if not result.get("ok"):
        return {"ok": False, "text": "", "model": selected, "error": result.get("error")}
    text = _clean(str(result.get("text") or ""))
    if not text:
        return {"ok": False, "text": "", "model": selected, "error": "Leere Antwort"}
    return {"ok": True, "text": text, "model": result.get("model") or selected, "error": None}


def status() -> dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "model": ollama.vision_model(),
        "recommended": ollama.VISION_MODELS,
    }
