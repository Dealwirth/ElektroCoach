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


def _ink_mask(gray: "np.ndarray") -> "np.ndarray":
    """Tuschemaske (Text = 1) nach Otsu-Schwelle."""
    threshold = _otsu_threshold(gray)
    return (gray <= threshold).astype(np.uint8)


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
    """Bereitet ein Seitenbild fuer die Segmentierung auf."""
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
def segment_lines(
    image: "Image.Image",
    min_height: int = MIN_LINE_HEIGHT,
    merge_gap: int = MERGE_GAP,
    ink_ratio: float = INK_RATIO,
) -> list["Image.Image"]:
    """Zerlegt eine Seite in Zeilenbilder (von oben nach unten)."""
    gray = _to_gray_array(image)
    mask = _ink_mask(gray)
    projection = mask.sum(axis=1)
    if projection.max() == 0:
        return [image]
    cutoff = max(1.0, projection.max() * ink_ratio)

    bands: list[list[int]] = []
    start: int | None = None
    for index, value in enumerate(projection):
        on = value > cutoff
        if on and start is None:
            start = index
        elif not on and start is not None:
            if index - start >= min_height:
                bands.append([start, index])
            start = None
    if start is not None:
        bands.append([start, len(projection)])

    merged: list[list[int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] < merge_gap:
            merged[-1][1] = band[1]
        else:
            merged.append(band)

    lines: list["Image.Image"] = []
    for y0, y1 in merged:
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
            log.info("TrOCR-Modell geladen aus %s", self.directory)

    def _pixel_values(self, image: "Image.Image") -> "np.ndarray":
        size = int(self._preprocessor.get("size", {}).get("height", IMAGE_SIZE))
        resized = image.convert("RGB").resize((size, size), Image.BICUBIC)
        array = np.asarray(resized, dtype=np.float32) / 255.0
        mean = np.array(self._preprocessor.get("image_mean", [0.5, 0.5, 0.5]), dtype=np.float32)
        std = np.array(self._preprocessor.get("image_std", [0.5, 0.5, 0.5]), dtype=np.float32)
        array = (array - mean) / std
        return array.transpose(2, 0, 1)[None].astype(np.float32)

    def transcribe_line(
        self, image: "Image.Image", max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> dict[str, Any]:
        """Erkennt eine Zeile. Rueckgabe: {text, confidence} (0..100)."""
        self._load()
        pixel_values = self._pixel_values(image)
        hidden = self._encoder.run(None, {"pixel_values": pixel_values})[0]
        tokens = [self._start_token]
        probabilities: list[float] = []
        for _ in range(max_tokens):
            logits = self._decoder.run(
                None,
                {
                    "input_ids": np.array([tokens], dtype=np.int64),
                    "encoder_hidden_states": hidden,
                },
            )[0]
            step = logits[0, -1]
            next_token = int(np.argmax(step))
            if next_token in self._eos_tokens:
                break
            probabilities.append(_softmax_max(step))
            tokens.append(next_token)
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
