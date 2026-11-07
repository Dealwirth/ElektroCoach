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
import difflib
import io
import logging
import re
from pathlib import Path
from collections import Counter
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

# Prompt fuer einen kleinen Block (wenige Zeilen). Bewusst kurz und streng:
# nur abschreiben. Eine zusaetzliche Formatvorgabe (etwa "Brueche als
# (Zaehler) / (Nenner)") verleitet das Modell zum Rechnen und kostet
# Genauigkeit und viel Zeit.
GROUP_PROMPT = (
    "Transkribiere alle Zeilen dieses Ausschnitts. Eine Bildzeile ergibt eine "
    "Textzeile, in der Reihenfolge von oben nach unten. Schreibe Brueche in "
    "einer Zeile als Zaehler / Nenner. Nutze rho fuer den spezifischen "
    "Widerstand, L fuer die Laenge und A fuer den Querschnitt. "
    "Einheiten: (Ohm*mm2)/m, m, mm2, Ohm, mOhm, V, A. Dezimalzahlen mit Komma. "
    "Keine Erklaerung, keine Rechnung, kein Codeblock. Gib nur den Text aus."
)

# Fuer Bloecke mit einem Bruchstrich. Ein Bruch wird oft als "nur Zaehler"
# gelesen; die ausdrueckliche Nennung von Zaehler und Nenner holt den Nenner
# zurueck, der sonst verloren geht.
FRACTION_PROMPT = (
    "In diesem Ausschnitt steht mindestens ein Bruch (Zaehler, Bruchstrich, "
    "Nenner). Schreibe jede Bildzeile vollstaendig in EINER Textzeile ab: "
    "Zaehler, dann '/', dann der Nenner, dann das Gleichheitszeichen und das "
    "Ergebnis. Lasse den Nenner nie weg, auch wenn er klein unter dem Strich "
    "steht. Nutze rho fuer den spezifischen Widerstand, L fuer die Laenge, A "
    "fuer den Querschnitt, Ohm, mm2, mOhm, V und A als Einheiten. "
    "Rechne nichts aus und kuerze nichts. Keine Erklaerung, kein Codeblock. "
    "Gib nur die Zeilen aus."
)

# Einzelne Zeile (Rueckfall, wenn keine Segmentierung moeglich ist).
LINE_PROMPT = (
    "Schreibe genau ab, was in dieser Zeile steht. Nutze rho fuer den "
    "spezifischen Widerstand, L fuer die Laenge und A fuer den Querschnitt. "
    "Einheiten: (Ohm*mm2)/m, m, mm2, Ohm, mOhm, V, A. Dezimalzahlen mit Komma. "
    "Gib nur den Text dieser einen Zeile aus."
)

# Handschrift wird am besten in kleinen Bloecken gelesen: einzelne Zeilen sind
# zu kurz fuer den Kontext (Ziffern werden dann verwechselt), eine ganze Seite
# ist zu dicht (das Modell verliert den Faden und erfindet Zahlen). Drei Zeilen
# je Block haben sich als bester Kompromiss erwiesen.
GROUP_SIZE = 3
# Mehrfachlesung: denselben Block bei mehreren Hoehen lesen und den Konsens
# bilden. Schwere Ziffern (375, 3,56) werden so deutlich zuverlaessiger, weil
# ein einzelner Fehlversuch die Mehrheit nicht kippt. Kostet Zeit, nicht
# Genauigkeit.
GROUP_PASS_HEIGHTS = (256, 320, 384)
GROUP_PASSES = 3
# Blockhoehe unter diesem Wert wird hochskaliert (kurze Bloecke).
GROUP_MIN_HEIGHT = 256
# Hoehe der Gesamtseiten-Lesung. Sie ist der Gegenspieler zur Blocklesung:
# wo der Block ein Zeichen verliert, hat die Gesamtseite oft den Kontext.
FULL_PAGE_HEIGHT = 2048
# Abstand zwischen den Zeilen im Block (Pixel im Originalbild).
GROUP_GAP = 12
# Zeilen ueber dieser Breite werden zusaetzlich in Spalten geteilt (lange
# Rechenzeilen mit mehreren Termen). Typische Zeilen bleiben ungeteilt.
LINE_MAX_WIDTH = 3200
# Ohne Zeilensegmentierung wird die ganze Seite auf diese Breite skaliert.
VISION_TARGET_WIDTH = 1600
VISION_NUM_CTX = 8192
VISION_NUM_PREDICT = 1536
# Kontextfenster fuer den Blockaufruf.
LINE_NUM_CTX = 4096
LINE_NUM_PREDICT = 512

# Lesezeitlimit fuer Bildaufrufe (Sekunden). Auf einem Raspberry Pi 4 kann ein
# Seitenaufruf mehrere Minuten dauern; das Standardlimit von 180 s wuerde ihn
# abbrechen. Zeit ist hier zweitrangig, Vollstaendigkeit nicht.
OCR_TIMEOUT_SECONDS = 900


def _ocr_timeout() -> int:
    try:
        return max(30, int(settings.get("ocr_timeout_seconds", OCR_TIMEOUT_SECONDS)))
    except (TypeError, ValueError):
        return OCR_TIMEOUT_SECONDS


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


def _line_image(line: Any, height: int = GROUP_MIN_HEIGHT) -> Any:
    """Skaliert eine Zeile auf die Lesehoehe des Bildmodells."""
    if line.height <= 0 or line.height >= height:
        return line
    factor = height / line.height
    return line.resize((int(round(line.width * factor)), height), Image.LANCZOS)


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


def _block_image(lines: list[Any], height: int = GROUP_MIN_HEIGHT) -> Any:
    """Setzt mehrere Zeilen untereinander zu einem Blockbild zusammen."""
    parts: list[Any] = []
    for line in lines:
        parts.extend(_line_slices(line))
    width = max(part.width for part in parts)
    total = sum(part.height for part in parts) + GROUP_GAP * (len(parts) - 1)
    canvas = Image.new("RGB", (width, max(1, total)), "white")
    y = 0
    for part in parts:
        canvas.paste(part, (0, y))
        y += part.height + GROUP_GAP
    if canvas.height < height:
        factor = height / canvas.height
        canvas = canvas.resize((int(round(canvas.width * factor)), height), Image.LANCZOS)
    return canvas


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


def _consensus(variants: list[str]) -> str:
    """Waehlt aus mehreren Lesungen desselben Blocks den besten Text.

    Grundlage ist die Zahl der uebereinstimmenden Zahlen: eine Zahl, die
    mehrere Durchgaenge gleich lesen, ist fast immer richtig. Unter den
    Lesungen, die diese Zahlen enthalten, gewinnt die vollstaendigere. So geht
    ein Bruch-Nenner nicht verloren, den nur ein Durchgang gesehen hat. Es wird
    nie Inhalt erfunden, nur eine der vorhandenen Lesungen ausgewaehlt.
    """
    return _pick_line(variants)


def _pass_heights() -> list[int]:
    try:
        passes = int(settings.get("ocr_vision_passes", GROUP_PASSES))
    except (TypeError, ValueError):
        passes = GROUP_PASSES
    passes = max(1, min(len(GROUP_PASS_HEIGHTS), passes))
    return list(GROUP_PASS_HEIGHTS[:passes])


def _vision_models(default: str) -> list[str]:
    """Modelle, mit denen gelesen wird.

    Sind mehrere Bildmodelle eingerichtet, liest jedes den Block. Die
    Mehrfachlesung ueber verschiedene Modelle ist die staerkste Absicherung
    gegen Ziffernfehler: ein einzelnes Modell verliest sich, zwei selten an
    derselben Stelle gleich. Ohne Einstellung wird nur das Standardmodell
    verwendet.
    """
    raw = str(settings.get("ocr_vision_models", "") or "")
    models = [name.strip() for name in raw.split(",") if name.strip()]
    if not models:
        return [default]
    if default not in models:
        models.insert(0, default)
    # Reihenfolge erhalten, Wiederholungen entfernen.
    seen: set[str] = set()
    unique = []
    for name in models:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique


async def _read_block_variants(lines: list[Any], models: list[str]) -> list[str]:
    """Liest einen Block mehrfach: je Modell bei verschiedenen Hoehen."""
    variants: list[str] = []
    heights = _pass_heights()
    images = {height: _block_image(lines, height) for height in heights}
    for model in models:
        for height in heights:
            text = await _read_image(images[height], GROUP_PROMPT, model)
            if text:
                variants.append(text)
    return variants


async def _read_image(image: Any, prompt: str, selected: str, *, predict: int = LINE_NUM_PREDICT) -> str | None:
    """Liest ein Bild. Gibt ``None`` zurueck, wenn das Modell scheitert."""
    image_b64 = base64.b64encode(_page_image_bytes(image)).decode("ascii")
    result = await ollama.chat(
        prompt,
        system=SYSTEM,
        images=[image_b64],
        task="handwriting_vision",
        temperature=0.0,
        num_ctx=LINE_NUM_CTX,
        model_name=selected,
        num_predict=predict,
        timeout_seconds=_ocr_timeout(),
    )
    if not result.get("ok"):
        return None
    text = _clean(str(result.get("text") or ""))
    return text or None


def _stack(images: list[Any], gap: int = GROUP_GAP) -> Any:
    """Setzt mehrere Bilder untereinander, Breite = groesste Breite."""
    width = max(image.width for image in images)
    total = sum(image.height for image in images) + gap * (len(images) - 1)
    canvas = Image.new("RGB", (width, max(1, total)), "white")
    y = 0
    for image in images:
        canvas.paste(image, (0, y))
        y += image.height + gap
    return canvas


def _scale_height(image: Any, height: int) -> Any:
    if image.height <= 0 or image.height >= height:
        return image
    factor = height / image.height
    return image.resize((int(round(image.width * factor)), height), Image.LANCZOS)


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


async def _read_windows(
    lines: list[Any],
    models: list[str],
    *,
    height: int,
    size: int,
) -> list[str]:
    """Liest jede Zeile als erste Zeile eines eigenen Fensters.

    Die erste Zeile eines Ausschnitts liest das Modell am zuverlaessigsten
    (die Probe auf dem Testbild: die erste Zeile eines Dreierblocks ist
    vollstaendig, dieselbe Zeile mitten im Block verliert den Nenner). Deshalb
    beginnt fuer jede Zeile ein eigenes Fenster; gelesen wird nur die erste
    Zeile. Das kostet einen Aufruf je Zeile, liefert aber die beste Lesung.
    """
    out: list[str] = []
    for start in range(len(lines)):
        window = lines[start:start + size]
        image = _block_image(window, height)
        variants: list[str] = []
        for model in models:
            text = await _read_image(image, GROUP_PROMPT, model)
            if text:
                variants.append(text)
        readings = _split_lines(_consensus(variants))
        out.append(readings[0] if readings else "")
    return out


async def _read_isolated(lines: list[Any], models: list[str], *, height: int) -> list[str]:
    """Liest jede Zeile einzeln (nur diese Zeile im Bild).

    Ohne Nachbarzeilen faellt die Verwechslung benachbarter Zahlen weg. Diese
    Lesung ist die genaueste; sie liefert den Bezug fuer den Zeilenabgleich.
    """
    out: list[str] = []
    for line in lines:
        image = _block_image([line], height)
        variants: list[str] = []
        for model in models:
            text = await _read_image(image, LINE_PROMPT, model)
            if text:
                variants.append(text)
        readings = _split_lines(_consensus(variants))
        out.append(readings[0] if readings else "")
    return out


async def _read_in_blocks(
    lines: list[Any],
    models: list[str],
    *,
    height: int,
    size: int,
    prompt: str = GROUP_PROMPT,
) -> list[str]:
    """Liest die Seite blockweise und liefert je Bildzeile einen Text.

    Jeder Block hat eine bekannte Zeilenzahl. Das Modell haengt gelegentlich
    eine erfundene Zeile an; mehr Zeilen als im Ausschnitt koennen nicht
    richtig sein und werden abgeschnitten.
    """
    out: list[str] = []
    for start in range(0, len(lines), size):
        block = lines[start:start + size]
        expected = len(block)
        image = _block_image(block, height)
        variants: list[str] = []
        for model in models:
            text = await _read_image(image, prompt, model)
            if text:
                variants.append(text)
        out.extend(_split_lines(_consensus(variants))[:expected])
    return out


async def _read_full_page(lines: list[Any], models: list[str], *, height: int) -> list[str]:
    """Liest alle Zeilen in einem Bild bei hoher Aufloesung."""
    page = _scale_height(_stack(lines), height)
    variants: list[str] = []
    for model in models:
        text = await _read_image(page, GROUP_PROMPT, model, predict=VISION_NUM_PREDICT)
        if text:
            variants.append(text)
    return _split_lines(_consensus(variants))


def _align_to(reference: list[str], reading: list[str]) -> list[str]:
    """Bildet eine Lesung auf die Zeilen der Referenz ab.

    Die Modelle verschieben gelegentlich eine Zeile (sie haengen etwa die
    Ueberschrift an die Formel). Ein Vergleich ueber die Zeilennummer wuerde
    dann alle folgenden Zeilen verwerfen. Deshalb werden gleiche Zeilen
    zugeordnet und Luecken aufgefuellt.
    """
    if not reading:
        return [""] * len(reference)
    aligned: list[str] = [""] * len(reference)
    matcher = difflib.SequenceMatcher(None, reference, reading, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                aligned[i1 + offset] = reading[j1 + offset]
        elif tag == "replace":
            ref_span = i2 - i1
            read_span = j2 - j1
            for offset in range(ref_span):
                index = j1 + min(offset, read_span - 1)
                aligned[i1 + offset] = reading[index]
        # "delete"/"insert" lassen die Referenzzeile leer.
    return aligned


def _reference_weight() -> int:
    try:
        return max(1, int(settings.get("ocr_vision_reference_weight", 2) or 2))
    except (TypeError, ValueError):
        return 2


def _merge_readings(
    readings: list[list[str]],
    count: int,
    reference: list[str] | None = None,
    *,
    reference_weight: int | None = None,
) -> str:
    """Fuehrt mehrere vollstaendige Lesungen Zeile fuer Zeile zusammen.

    Jede Zeile wird aus allen Lesungen gewaehlt: die Lesung mit den meisten
    uebereinstimmenden Zahlen gewinnt. Stimmen zwei Lesungen bei einer Ziffer
    ueberein, setzt sich diese gegen einen einzelnen Fehlversuch durch. Bei
    Gleichstand gewinnt die vollstaendigere (laengere) Zeile, damit ein
    Bruch-Nenner nicht verloren geht.

    ``reference`` ist die zuverlaessigste Lesung (jede Zeile einzeln gelesen).
    Sie hat genau so viele Eintraege wie Bildzeilen und in derselben Reihenfolge
    - deshalb ist sie die beste Grundlage fuer den Zeilenabgleich der uebrigen
    Lesungen. Ihre Stimmen zaehlen ``reference_weight``-fach: die isolierte
    Lesung ist genauer, ein einzelner Ausreisser soll sie nicht kippen.
    """
    usable = [r for r in readings if r]
    if not usable:
        return ""
    # Referenz: die isolierte Lesung, sonst die Lesung mit der erwarteten
    # Zeilenzahl, sonst die laengste.
    if reference:
        base = reference
    else:
        base = min(usable, key=lambda r: (abs(len(r) - count), -len(r)))
    if reference_weight is None:
        reference_weight = _reference_weight()
    weight = max(1, reference_weight)
    # Die Bezugslesung steckt bereits als ``base`` in den Kandidaten; sie darf
    # nicht ein zweites Mal als gewoehnliche Stimme zaehlen.
    others = [r for r in usable if r is not base]
    aligned = [_align_to(base, reading) for reading in others]
    merged: list[str] = []
    for index in range(len(base)):
        candidates: list[str] = []
        weights: list[int] = []
        if index < len(base) and base[index].strip():
            candidates.append(base[index])
            weights.append(weight)
        for reading in aligned:
            if index < len(reading) and reading[index].strip():
                candidates.append(reading[index])
                weights.append(1)
        text = _pick_line(candidates, weights)
        if text:
            merged.append(text)
    return _merge_lines(merged)


def _pick_line(candidates: list[str], weights: list[int] | None = None) -> str:
    cleaned = [c.strip() for c in candidates if c and c.strip()]
    if not cleaned:
        return ""
    if weights is None:
        weights = [1] * len(cleaned)
    else:
        weights = [w for c, w in zip(candidates, weights) if c and c.strip()]
        if len(weights) != len(cleaned):
            weights = [1] * len(cleaned)
    if len(cleaned) == 1:
        return cleaned[0]
    counter: Counter[str] = Counter()
    for candidate, weight in zip(cleaned, weights):
        for number in set(_numbers(candidate)):
            counter[number] += weight

    def key(text: str) -> tuple[int, int, float, int, int, int, int]:
        # 1. Stimmen: die Summe der Bestaetigungen aller Zahlen der Zeile.
        #    Eine Zahl, die mehrere Lesungen gleich sehen, wiegt schwer, aber
        #    eine Zeile mit mehreren bestaetigten Zahlen schlaegt eine mit nur
        #    einer - so geht kein Bruch-Nenner verloren.
        # 2. Bruch mit Nenner: eine Zeile, die den Bruch behaelt, ist
        #    vollstaendiger.
        # 3. Aehnlichkeit zu allen anderen Lesungen: die mittlere Lesung ist
        #    robuster als eine einzelne Ausreisser-Lesung.
        # 4. Vollstaendigkeit, dann Zahl der Zahlen.
        # 5. Erst als letzter Gleichstand: eine Rechnung, die auf beiden Seiten
        #    aufgeht, ist der zerrissenen Lesung vorzuziehen. Bewusst ganz
        #    hinten - eine erfundene, aber saubere Rechnung darf eine
        #    mehrfach bestaetigte Lesung nicht verdraengen.
        numbers = set(_numbers(text))
        votes = sum(counter[number] for number in numbers)
        denominator = 1 if re.search(r"/\s*\d", text) else 0
        similarity = sum(
            difflib.SequenceMatcher(None, text, other, autojunk=False).ratio()
            for other in cleaned
            if other is not text
        )
        ok, bad = _arithmetic_score(text)
        return (votes, denominator, similarity, len(text), len(numbers), ok, -bad)
    return max(cleaned, key=key)


_ARITH_RE = re.compile(
    r"(\d+(?:[.,]\d+)?(?:\s*[/*·×:]\s*\d+(?:[.,]\d+)?)+)\s*=\s*(\d+(?:[.,]\d+)?)"
)
_ARITH_TERM = re.compile(r"\d+(?:[.,]\d+)?|[/*·×:]")


def _arithmetic_score(text: str) -> tuple[int, int]:
    """Zaehlt aufgehende und nicht aufgehende Rechnungen ``term ... = ergebnis``.

    Verkettete Ausdruecke wie ``0,0178 * 100 / 0,3 = 5,93`` werden von links
    nach rechts ausgewertet, damit eine korrekte Kette nicht faelschlich als
    Fehler zaehlt.
    """
    ok = bad = 0
    for match in _ARITH_RE.finditer(text):
        parts = _ARITH_TERM.findall(match.group(1))
        try:
            value = _to_float(parts[0])
            for operator, term in zip(parts[1::2], parts[2::2]):
                number = _to_float(term)
                if operator == "/" and number == 0:
                    raise ValueError
                value = value * number if operator in "·×*" else value / number
            result = _to_float(match.group(2))
        except (ValueError, IndexError):
            continue
        if abs(value - result) <= max(0.005, abs(result) * 0.005):
            ok += 1
        else:
            bad += 1
    return ok, bad


def _to_float(token: str) -> float:
    return float(token.replace(".", "").replace(",", ".")) if "," in token else float(token)


def _debug_dump(readings: list[list[str]], count: int) -> None:
    """Schreibt alle Lesungen als JSON, wenn ELEKTROCOACH_OCR_DEBUG gesetzt ist."""
    try:
        import json
        import os

        path = os.environ.get("ELEKTROCOACH_OCR_DEBUG")
        if not path:
            return
        payload = {
            "count": count,
            "readings": readings,
            "merged": _merge_readings([r for r in readings if r], count).splitlines(),
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")
    except Exception as exc:  # pragma: no cover - nur Diagnose
        log.warning("OCR-Diagnose fehlgeschlagen: %s", exc)


async def transcribe(
    image: Any,
    draft: str | None = None,
    *,
    model_name: str | None = None,
) -> dict[str, Any]:
    """Liest eine Seite mit dem lokalen Bildmodell in mehreren Durchgaengen.

    Handschrift wird am zuverlaessigsten in kleinen Bloecken gelesen: eine
    einzelne Zeile ist zu kurz (Ziffern werden verwechselt), die ganze Seite zu
    dicht (das Modell verliert den Faden und rechnet). Deshalb wird die Seite
    mehrfach gelesen - blockweise bei mehreren Hoehen und einmal als Ganzes -
    und Zeile fuer Zeile zum Konsens zusammengefuehrt.

    Rueckgabe: ``{ok, text, model, error}``.
    """
    if not ollama.is_enabled():
        return {"ok": False, "text": "", "model": None, "error": "Ollama ist deaktiviert"}

    selected = model_name or ollama.vision_model()
    used_model = selected
    models = _vision_models(selected)

    try:
        from . import handwriting

        segments = handwriting.segment_lines(image) if handwriting.available() else []
    except Exception as exc:  # noqa: BLE001
        log.warning("Zeilensegmentierung fehlgeschlagen: %s", exc)
        segments = []

    if segments:
        size = max(1, int(settings.get("ocr_vision_group_size", GROUP_SIZE) or GROUP_SIZE))
        heights = _pass_heights()
        readings: list[list[str]] = []
        # Grundlage: jede Zeile einzeln lesen. Ohne Nachbarzeilen faellt die
        # Verwechslung benachbarter Zahlen weg; diese Lesung ist die genaueste
        # und die einzige, die jede Bildzeile genau einmal abdeckt. Sie dient
        # deshalb auch als Bezug fuer den Zeilenabgleich der uebrigen Lesungen.
        isolated: list[str] = []
        if settings.get_bool("ocr_vision_isolated", True):
            isolated = await _read_isolated(segments, models, height=heights[0])
        # Rueckfall: je Zeile ein eigenes Fenster, gelesen wird die erste Zeile.
        windows: list[str] = []
        if not any(isolated) and settings.get_bool("ocr_vision_windows", True):
            windows = await _read_windows(segments, models, height=heights[0], size=size)
        reference = isolated if any(isolated) else windows
        if any(reference):
            readings.append(reference)
        # Blockweise Lesung bei mehreren Hoehen als weitere Stimmen.
        for height in heights:
            readings.append(await _read_in_blocks(segments, models, height=height, size=size))
        # Die ganze Seite in einem Bild. Wo der Block ein Zeichen verliert,
        # hat die Gesamtseite oft den Kontext.
        if settings.get_bool("ocr_vision_full_page", True):
            page_read = await _read_full_page(segments, models, height=FULL_PAGE_HEIGHT)
            if page_read:
                readings.append(page_read)
        # Bruch-Prompt auf denselben Bloecken: holt Nenner zurueck, die sonst
        # verloren gehen.
        if settings.get_bool("ocr_vision_fraction_pass", True):
            fraction = await _read_in_blocks(
                segments, models, height=heights[0], size=size, prompt=FRACTION_PROMPT
            )
            if fraction:
                readings.append(fraction)
        text = _merge_readings(
            [r for r in readings if r], len(segments), reference=reference or None
        )
        _debug_dump(readings, len(segments))
        if text.strip():
            return {"ok": True, "text": text, "model": used_model, "error": None}

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
        timeout_seconds=_ocr_timeout(),
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
