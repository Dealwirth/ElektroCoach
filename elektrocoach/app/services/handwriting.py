"""Lokale Handschrifterkennung (HTR) mit TrOCR.

Tesseract erkennt gedruckten Text gut, Handschrift aber nur unzuverlaessig.
Dieses Modul ergaenzt deshalb ein auf deutsche Handschrift feinabgestimmtes
TrOCR-Modell, das vollstaendig offline und kostenlos als ONNX laeuft.

Ablauf je Seite:
  1. Vorverarbeitung: Graustufen, Hintergrundabgleich (gegen Schatten),
     Schraegstellung ausgleichen (Deskew).
  2. Zeilensegmentierung ueber die waagerechte Projektion der Tuschemaske.
  3. Je Zeile: TrOCR (Encoder + Decoder, gieriges Dekodieren).
  4. Zeilen zu einem Text zusammenfuegen.

Die Modelldateien liegen als int8-ONNX in einem Verzeichnis
(Standard: ``/app/models/trocr-de``, uebersteuerbar mit
``ELEKTROCOACH_TROCR_DIR``). Fehlen sie, meldet :func:`available` ``False``
und die OCR faellt auf Tesseract zurueck.

Das Modul ist bewusst ohne OpenCV umgesetzt: nur Pillow und NumPy. Das haelt
das Add-on-Basis-Image (Alpine/musl) klein und vermeidet Abhaengigkeiten, fuer
die es keine musl-Wheels gibt.
"""

from __future__ import annotations

import io
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MODEL_ENV = "ELEKTROCOACH_TROCR_DIR"
ENCODER_NAME = "encoder_int8.onnx"
DECODER_NAME = "decoder_int8.onnx"
REQUIRED_FILES = (
    ENCODER_NAME,
    DECODER_NAME,
    "tokenizer.json",
    "preprocessor_config.json",
)

IMAGE_SIZE = 384
DEFAULT_MAX_TOKENS = 128

# Segmentierung
MIN_LINE_HEIGHT = 8
MERGE_GAP = 12
INK_RATIO = 0.02
MAX_SEGMENT_WIDTH = 3200

# Seitenerkennung: heller Bereich innerhalb eines (evtl. dunklen) Rahmens.
PAGE_BRIGHT_MIN = 150
PAGE_RUN_RATIO = 0.30

# Adaptive Binarisierung: Schwelle aus dem lokalen Mittelwert.
ADAPTIVE_OFFSET = 18.0
ADAPTIVE_RADIUS_RATIO = 0.06
ADAPTIVE_RADIUS_MIN = 6.0
ADAPTIVE_RADIUS_MAX = 45.0

# Beam-Search beim Dekodieren (1 = gierig). Groesser = genauer, langsamer.
DEFAULT_BEAM_WIDTH = 2
BEAM_ENV = "ELEKTROCOACH_TROCR_BEAM"

# Deskew
DESKEW_RANGE = 6.0
DESKEW_STEP = 1.5

try:  # pragma: no cover - abhaengig von der Installation
    import numpy as np

    _HAVE_NUMPY = True
except Exception:  # pragma: no cover
    np = None  # type: ignore[assignment]
    _HAVE_NUMPY = False

try:  # pragma: no cover
    import onnxruntime as ort

    _HAVE_ORT = True
except Exception:  # pragma: no cover
    ort = None  # type: ignore[assignment]
    _HAVE_ORT = False

try:  # pragma: no cover
    from tokenizers import Tokenizer

    _HAVE_TOKENIZERS = True
except Exception:  # pragma: no cover
    Tokenizer = None  # type: ignore[assignment]
    _HAVE_TOKENIZERS = False

try:  # pragma: no cover
    from PIL import Image, ImageFilter, ImageOps

    _HAVE_PIL = True
except Exception:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    _HAVE_PIL = False


def model_dir() -> Path:
    """Verzeichnis der ONNX-Modelldateien."""
    override = os.environ.get(MODEL_ENV)
    if override:
        return Path(override)
    from ..config import settings

    baked = Path("/app/models/trocr-de")
    if baked.exists():
        return baked
    return settings.data_dir / "models" / "trocr-de"


def dependencies_ok() -> bool:
    return bool(_HAVE_NUMPY and _HAVE_ORT and _HAVE_TOKENIZERS and _HAVE_PIL)


def missing_files(directory: Path | None = None) -> list[str]:
    directory = directory or model_dir()
    return [name for name in REQUIRED_FILES if not (directory / name).is_file()]


def available() -> bool:
    """True, wenn Abhaengigkeiten und Modelldateien vorhanden sind."""
    if not dependencies_ok():
        return False
    return not missing_files()


def status() -> dict[str, Any]:
    directory = model_dir()
    missing = missing_files(directory)
    return {
        "available": available(),
        "dir": str(directory),
        "missing": missing,
        "dependencies": {
            "numpy": _HAVE_NUMPY,
            "onnxruntime": _HAVE_ORT,
            "tokenizers": _HAVE_TOKENIZERS,
            "pillow": _HAVE_PIL,
        },
    }


# ---------------------------------------------------------------------------
# Vorverarbeitung
# ---------------------------------------------------------------------------
def _to_gray_array(image: "Image.Image") -> "np.ndarray":
    """Graustufenbild als float-Array; groesste Kantenlaenge begrenzt."""
    image = image.convert("L")
    if max(image.size) > MAX_SEGMENT_WIDTH:
        ratio = MAX_SEGMENT_WIDTH / max(image.size)
        image = image.resize((max(1, int(image.width * ratio)), max(1, int(image.height * ratio))))
    return np.asarray(image, dtype=np.float32)


def _otsu_threshold(gray: "np.ndarray") -> int:
    hist = np.bincount(gray.astype(np.uint8).ravel(), minlength=256).astype(np.float64)
    total = gray.size
    sum_all = float(np.dot(np.arange(256), hist))
    sum_b = 0.0
    weight_b = 0.0
    best = -1.0
    threshold = 127
    for value in range(256):
        weight_b += hist[value]
        if weight_b == 0:
            continue
        weight_f = total - weight_b
        if weight_f == 0:
            break
        sum_b += value * hist[value]
        mean_b = sum_b / weight_b
        mean_f = (sum_all - sum_b) / weight_f
        variance = weight_b * weight_f * (mean_b - mean_f) ** 2
        if variance > best:
            best = variance
            threshold = value
    return threshold


def _runs(flags: "np.ndarray") -> list[tuple[int, int]]:
    """Zusammenhaengende Bereiche, in denen ``flags`` wahr ist."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def _merge_runs(runs: list[tuple[int, int]], max_gap: int) -> list[tuple[int, int]]:
    """Fasst Bereiche zusammen, die nur durch eine schmale Luecke getrennt sind."""
    merged: list[tuple[int, int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= max_gap:
            merged[-1] = (merged[-1][0], run[1])
        else:
            merged.append(run)
    return merged


def _longest_run(runs: list[tuple[int, int]]) -> tuple[int, int]:
    return max(runs, key=lambda run: run[1] - run[0]) if runs else (0, 0)


def detect_page(image: "Image.Image") -> "Image.Image":
    """Schneidet die Papierseite aus einem (evtl. dunklen) Bildschirmfoto.

    Handy-Screenshots haben oft einen dunklen Rand oder eine dunkle
    Bedienleiste. Die Seite ist der groesste helle, ringsum eingerahmte
    Bereich. Findet sich kein solcher Rahmen, bleibt das Bild unveraendert -
    ein Scan ohne Rand darf nicht beschnitten werden.
    """
    if not _HAVE_NUMPY:
        return image
    gray = np.asarray(image.convert("L"), dtype=np.float32)
    if gray.size == 0:
        return image
    height, width = gray.shape
    bright = gray >= PAGE_BRIGHT_MIN

    row_runs = _merge_runs(_runs(bright.mean(axis=1) >= PAGE_RUN_RATIO), max(8, int(height * 0.02)))
    y0, y1 = _longest_run(row_runs)
    if y1 - y0 < height * 0.2:
        return image

    col_runs = _merge_runs(_runs(bright[y0:y1].mean(axis=0) >= PAGE_RUN_RATIO), max(8, int(width * 0.02)))
    x0, x1 = _longest_run(col_runs)
    if x1 - x0 < width * 0.2:
        return image

    margin_y = max(4, int(height * 0.015))
    margin_x = max(4, int(width * 0.015))
    framed = (
        y0 >= margin_y and height - y1 >= margin_y
        and x0 >= margin_x and width - x1 >= margin_x
    )
    if not framed:
        return image
    return image.crop((x0, y0, x1, y1))


def _background(gray: "np.ndarray") -> "np.ndarray":
    """Stark weichgezeichnete Naeherung des Papierhintergrunds."""
    radius = float(np.clip(min(gray.shape) * ADAPTIVE_RADIUS_RATIO,
                           ADAPTIVE_RADIUS_MIN, ADAPTIVE_RADIUS_MAX))
    blurred = Image.fromarray(gray.astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=radius))
    return np.asarray(blurred, dtype=np.float32)


def _ink_mask(gray: "np.ndarray") -> "np.ndarray":
    """Tuschemaske (Text = 1) mit lokaler Schwelle.

    Die feste Otsu-Schwelle versagt bei Schatten, Flecken und ungleichmaessiger
    Beleuchtung. Der Vergleich mit dem lokalen Hintergrundabzug ist robuster.
    """
    background = _background(gray)
    return (gray <= background - ADAPTIVE_OFFSET).astype(np.uint8)


def _estimate_skew(gray: "np.ndarray") -> float:
    """Schaetzt die Schraegstellung ueber die Projektionsvarianz.

    Bei geraden Zeilen ist die waagerechte Projektion stark gegliedert
    (hohe Varianz). Der Winkel mit der hoechsten Varianz ist der beste.
    """
    small = gray
    if max(gray.shape) > 800:
        from PIL import Image as _Image

        ratio = 800 / max(gray.shape)
        pil = _Image.fromarray(gray.astype(np.uint8)).resize(
            (max(1, int(gray.shape[1] * ratio)), max(1, int(gray.shape[0] * ratio)))
        )
        small = np.asarray(pil, dtype=np.float32)
    mask = _ink_mask(small)
    best_angle = 0.0
    best_score = -1.0
    angle = -DESKEW_RANGE
    while angle <= DESKEW_RANGE + 1e-6:
        if abs(angle) < 1e-6:
            rotated = mask
        else:
            rotated = _rotate_mask(mask, angle)
        projection = rotated.sum(axis=1).astype(np.float64)
        score = float(np.var(projection))
        if score > best_score:
            best_score = score
            best_angle = float(angle)
        angle += DESKEW_STEP
    return best_angle


def _rotate_mask(mask: "np.ndarray", angle: float) -> "np.ndarray":
    from PIL import Image as _Image

    pil = _Image.fromarray((mask * 255).astype(np.uint8))
    rotated = pil.rotate(angle, resample=_Image.BILINEAR, expand=False, fillcolor=0)
    return (np.asarray(rotated, dtype=np.float32) > 127).astype(np.uint8)


def _normalise_background(image: "Image.Image") -> "Image.Image":
    """Zieht ungleichmaessige Beleuchtung ab (Handyfoto mit Schatten)."""
    gray = image.convert("L")
    # Stark weichgezeichnete Version naehert den Papierhintergrund an.
    radius = max(8.0, min(gray.size) / 25.0)
    background = gray.filter(ImageFilter.GaussianBlur(radius=radius))
    arr = np.asarray(gray, dtype=np.float32)
    bg = np.asarray(background, dtype=np.float32)
    normalised = 255.0 * (arr / np.clip(bg, 1.0, 255.0))
    return Image.fromarray(np.clip(normalised, 0, 255).astype(np.uint8))


def preprocess(image: "Image.Image", deskew: bool = True) -> "Image.Image":
    """Bereitet ein Seitenbild fuer die Segmentierung auf.

    Zuerst wird die Papierseite aus einem moeglichen Bildschirmrahmen
    geschnitten, dann der Kontrast gestreckt und die Schraegstellung
    ausgeglichen.
    """
    image = detect_page(image)
    image = ImageOps.autocontrast(image.convert("L"))
    gray = _to_gray_array(image)
    if deskew:
        angle = _estimate_skew(gray)
        if abs(angle) >= DESKEW_STEP / 2:
            image = image.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)
    return image


# ---------------------------------------------------------------------------
# Zeilensegmentierung
# ---------------------------------------------------------------------------
def _denoise_mask(mask: "np.ndarray") -> "np.ndarray":
    """Entfernt einzelne Stoerpixel (Oeffnen: erst Erosion, dann Dilatation)."""
    image = Image.fromarray((mask * 255).astype(np.uint8))
    image = image.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return (np.asarray(image) > 127).astype(np.uint8)


def _split_band(
    projection: "np.ndarray", start: int, end: int, target: int, min_height: int
) -> list[tuple[int, int]]:
    """Teilt ein zu hohes Band an der schwaechsten Stelle (Tal der Projektion)."""
    if end - start <= target * 1.6:
        return [(start, end)]
    middle_lo = start + target // 2
    middle_hi = end - target // 2
    if middle_hi <= middle_lo:
        return [(start, end)]
    valley = middle_lo + int(np.argmin(projection[middle_lo:middle_hi]))
    if valley - start < min_height or end - valley < min_height:
        return [(start, end)]
    return _split_band(projection, start, valley, target, min_height) + _split_band(
        projection, valley, end, target, min_height
    )


def segment_lines(
    image: "Image.Image",
    min_height: int = MIN_LINE_HEIGHT,
    merge_gap: int = MERGE_GAP,
    ink_ratio: float = INK_RATIO,
) -> list["Image.Image"]:
    """Zerlegt eine Seite in Zeilenbilder (von oben nach unten).

    Die Zeilen werden ueber die waagerechte Projektion der (entrauschten)
    Tuschemaske gefunden. Zu hoch geratene Bloecke werden am schwaechsten
    Punkt geteilt, damit verschmolzene Zeilen wieder getrennt werden.
    """
    gray = _to_gray_array(image)
    mask = _denoise_mask(_ink_mask(gray))
    height, width = mask.shape
    projection = mask.sum(axis=1).astype(np.float64)
    if projection.max() == 0:
        return [image]

    window = max(3, int(height * 0.004))
    smooth = np.convolve(projection, np.ones(window) / window, mode="same")
    cutoff = max(1.0, width * max(ink_ratio, 0.03))

    bands: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(smooth):
        on = value > cutoff
        if on and start is None:
            start = index
        elif not on and start is not None:
            if index - start >= min_height:
                bands.append((start, index))
            start = None
    if start is not None and len(smooth) - start >= min_height:
        bands.append((start, len(smooth)))
    if not bands:
        return [image]

    bands = _merge_runs(bands, max(merge_gap, int(height * 0.006)))

    heights = sorted(b[1] - b[0] for b in bands)
    target = int(np.median(heights)) if heights else min_height
    split: list[tuple[int, int]] = []
    for band in bands:
        split.extend(_split_band(smooth, band[0], band[1], max(target, min_height), min_height))

    lines: list["Image.Image"] = []
    for y0, y1 in split:
        columns = mask[y0:y1].sum(axis=0)
        non_zero = np.nonzero(columns)[0]
        if len(non_zero) == 0:
            continue
        x0, x1 = int(non_zero[0]), int(non_zero[-1]) + 1
        pad_y = max(3, int((y1 - y0) * 0.18))
        pad_x = max(4, int((y1 - y0) * 0.10))
        box = (
            max(0, x0 - pad_x),
            max(0, y0 - pad_y),
            min(image.width, x1 + pad_x),
            min(image.height, y1 + pad_y),
        )
        lines.append(image.crop(box))
    return lines or [image]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
class _Engine:
    """Traegt die ONNX-Sitzungen und den Tokenizer (traege geladen)."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._lock = threading.Lock()
        self._encoder: Any = None
        self._decoder: Any = None
        self._tokenizer: Any = None
        self._preprocessor: dict[str, Any] = {}
        self._start_token = 2
        self._eos_tokens = {2}
        self._num_beams = DEFAULT_BEAM_WIDTH
        self._length_penalty = 1.0
        self._no_repeat_ngram = 0
        self._error: str | None = None

    @property
    def error(self) -> str | None:
        return self._error

    def _load(self) -> None:
        if self._encoder is not None:
            return
        with self._lock:
            if self._encoder is not None:
                return
            options = ort.SessionOptions()
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            options.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2)))
            self._encoder = ort.InferenceSession(
                str(self.directory / ENCODER_NAME), sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self._decoder = ort.InferenceSession(
                str(self.directory / DECODER_NAME), sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            self._tokenizer = Tokenizer.from_file(str(self.directory / "tokenizer.json"))
            self._preprocessor = json.loads(
                (self.directory / "preprocessor_config.json").read_text(encoding="utf-8")
            )
            generation_path = self.directory / "generation_config.json"
            if generation_path.is_file():
                generation = json.loads(generation_path.read_text(encoding="utf-8"))
                self._start_token = int(generation.get("decoder_start_token_id", 2))
                eos = generation.get("eos_token_id", 2)
                self._eos_tokens = set(eos if isinstance(eos, list) else [eos])
                beams = int(os.environ.get(BEAM_ENV, generation.get("num_beams", DEFAULT_BEAM_WIDTH)) or 1)
                self._num_beams = max(1, min(8, beams))
                self._length_penalty = float(generation.get("length_penalty", 1.0) or 1.0)
                self._no_repeat_ngram = int(generation.get("no_repeat_ngram_size", 0) or 0)
            log.info(
                "TrOCR-Modell geladen aus %s (Beams: %d)", self.directory, self._num_beams
            )

    def _pixel_values(self, image: "Image.Image") -> "np.ndarray":
        size = int(self._preprocessor.get("size", {}).get("height", IMAGE_SIZE))
        resized = image.convert("RGB").resize((size, size), Image.BICUBIC)
        array = np.asarray(resized, dtype=np.float32) / 255.0
        mean = np.array(self._preprocessor.get("image_mean", [0.5, 0.5, 0.5]), dtype=np.float32)
        std = np.array(self._preprocessor.get("image_std", [0.5, 0.5, 0.5]), dtype=np.float32)
        array = (array - mean) / std
        return array.transpose(2, 0, 1)[None].astype(np.float32)

    def _logits(self, tokens: list[int], hidden: "np.ndarray") -> "np.ndarray":
        return self._decoder.run(
            None,
            {
                "input_ids": np.array([tokens], dtype=np.int64),
                "encoder_hidden_states": hidden,
            },
        )[0][0, -1]

    def _greedy(self, hidden: "np.ndarray", max_tokens: int) -> tuple[list[int], list[float]]:
        tokens = [self._start_token]
        probabilities: list[float] = []
        for _ in range(max_tokens):
            step = self._logits(tokens, hidden)
            next_token = int(np.argmax(step))
            if next_token in self._eos_tokens:
                break
            probabilities.append(_softmax_max(step))
            tokens.append(next_token)
        return tokens, probabilities

    def _beam_search(self, hidden: "np.ndarray", max_tokens: int) -> tuple[list[int], list[float]]:
        """Beam-Search wie in der HuggingFace-Generierung (Laengenstrafe).

        Gieriges Dekodieren nimmt an jeder Stelle nur das wahrscheinlichste
        Zeichen. Ein einmal falsch gewaehltes Zeichen laesst sich nicht mehr
        zuruecknehmen. Die Suche behaelt mehrere Kandidaten und waehlt am Ende
        die insgesamt beste Folge.
        """
        beams: list[tuple[list[int], float, list[float]]] = [([self._start_token], 0.0, [])]
        finished: list[tuple[list[int], float, list[float]]] = []
        for _ in range(max_tokens):
            if not beams:
                break
            candidates: list[tuple[list[int], float, list[float]]] = []
            for tokens, score, probs in beams:
                step = self._logits(tokens, hidden)
                values = step.astype(np.float64)
                values = values - values.max()
                log_probs = values - np.log(np.exp(values).sum())
                top = np.argpartition(log_probs, -self._num_beams)[-self._num_beams :]
                for token in top:
                    token = int(token)
                    new_score = score + float(log_probs[token])
                    if token in self._eos_tokens:
                        finished.append((tokens, new_score, probs))
                        continue
                    if self._no_repeat_ngram > 1 and len(tokens) >= self._no_repeat_ngram:
                        tail = tokens[-(self._no_repeat_ngram - 1) :]
                        if any(
                            tokens[i : i + self._no_repeat_ngram - 1] == tail
                            for i in range(len(tokens) - self._no_repeat_ngram + 1)
                            if tokens[i + self._no_repeat_ngram - 1] == token
                        ):
                            continue
                    probability = float(np.exp(log_probs[token]))
                    candidates.append((tokens + [token], new_score, probs + [probability]))
            if not candidates:
                break
            penalty = self._length_penalty if self._length_penalty else 1.0
            candidates.sort(key=lambda item: item[1] / (len(item[0]) ** penalty), reverse=True)
            beams = candidates[: self._num_beams]
        pool = finished + beams
        if not pool:
            return [self._start_token], []
        penalty = self._length_penalty if self._length_penalty else 1.0
        best_tokens, _, best_probs = max(
            pool, key=lambda item: item[1] / (len(item[0]) ** penalty)
        )
        return best_tokens, best_probs

    def transcribe_line(
        self, image: "Image.Image", max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> dict[str, Any]:
        """Erkennt eine Zeile. Rueckgabe: {text, confidence} (0..100)."""
        self._load()
        pixel_values = self._pixel_values(image)
        hidden = self._encoder.run(None, {"pixel_values": pixel_values})[0]
        if self._num_beams > 1:
            tokens, probabilities = self._beam_search(hidden, max_tokens)
        else:
            tokens, probabilities = self._greedy(hidden, max_tokens)
        text = self._tokenizer.decode(tokens, skip_special_tokens=True)
        confidence = round(100.0 * sum(probabilities) / len(probabilities), 2) if probabilities else None
        return {"text": text, "confidence": confidence}


_engine: _Engine | None = None
_engine_lock = threading.Lock()


def _softmax_max(logits: "np.ndarray") -> float:
    """Groesste Softmax-Wahrscheinlichkeit eines Logit-Vektors."""
    values = logits.astype(np.float64)
    values = values - values.max()
    exp = np.exp(values)
    return float(exp.max() / exp.sum())


def _get_engine() -> _Engine:
    global _engine
    directory = model_dir()
    with _engine_lock:
        if _engine is None or _engine.directory != directory:
            _engine = _Engine(directory)
        return _engine


def reset() -> None:
    """Verwirft die geladenen Sitzungen (fuer Tests und Modellwechsel)."""
    global _engine
    with _engine_lock:
        _engine = None


# ---------------------------------------------------------------------------
# Oeffentliche Schnittstelle
# ---------------------------------------------------------------------------
def transcribe_image(
    image: "Image.Image",
    max_tokens: int = DEFAULT_MAX_TOKENS,
    deskew: bool = True,
) -> dict[str, Any]:
    """Erkennt Handschrift auf einem Seitenbild.

    Rueckgabe: ``{ok, text, lines, confidence, error}``. Bei fehlenden Modellen
    oder Fehlern ist ``ok`` ``False`` und ``error`` gesetzt; der Aufrufer faellt
    dann auf Tesseract zurueck.
    """
    if not dependencies_ok():
        return {"ok": False, "text": "", "lines": 0, "confidence": None,
                "error": "Abhaengigkeiten fehlen"}
    missing = missing_files()
    if missing:
        return {"ok": False, "text": "", "lines": 0, "confidence": None,
                "error": f"Modelldateien fehlen: {', '.join(missing)}"}
    try:
        prepared = preprocess(image, deskew=deskew)
        engine = _get_engine()
        lines = segment_lines(prepared)
        texts: list[str] = []
        confidences: list[float] = []
        for line in lines:
            result = engine.transcribe_line(line, max_tokens=max_tokens)
            if result["text"].strip():
                texts.append(result["text"].strip())
            if result["confidence"] is not None:
                confidences.append(float(result["confidence"]))
        text = "\n".join(texts)
        confidence = round(sum(confidences) / len(confidences), 2) if confidences else None
        return {"ok": True, "text": text, "lines": len(lines),
                "confidence": confidence, "error": None}
    except Exception as exc:  # noqa: BLE001 - jeder Fehler faellt auf Tesseract zurueck
        log.warning("TrOCR-Erkennung fehlgeschlagen: %s", exc)
        return {"ok": False, "text": "", "lines": 0, "confidence": None, "error": str(exc)[:300]}


def transcribe_bytes(data: bytes, **kwargs: Any) -> dict[str, Any]:
    if not _HAVE_PIL:
        return {"ok": False, "text": "", "lines": 0, "confidence": None, "error": "Pillow fehlt"}
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "text": "", "lines": 0, "confidence": None,
                "error": f"Bild nicht lesbar: {exc}"}
    return transcribe_image(image, **kwargs)
