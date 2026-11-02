"""OCR engine wrapper.

Uses the ``tesseract`` command line tool, which is available in the add-on
image (``tesseract-ocr`` + ``tesseract-ocr-deu``). When the binary is missing the
engine reports itself as unavailable instead of failing the whole import — the
caller can then fall back to Gemini for that page or mark it for manual review.

Handwriting recognition is deliberately **not** attempted here. Tesseract is
unreliable for German handwriting, so those pages are routed to Gemini and, when
Gemini is unavailable, flagged as "needs review" rather than guessed.
"""

from __future__ import annotations

import csv
import io
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("elektrocoach.documents.ocr")

# Below this mean word confidence a page is flagged for human review.
LOW_CONFIDENCE_THRESHOLD = 70.0
OCR_TIMEOUT_SECONDS = 180


@dataclass
class OcrResult:
    text: str
    confidence: float
    engine: str
    needs_review: bool
    word_count: int = 0


class OcrEngine:
    def __init__(self, languages: str = "deu+eng") -> None:
        self.languages = languages or "deu+eng"
        self._binary = shutil.which("tesseract")

    @property
    def available(self) -> bool:
        return self._binary is not None

    def languages_available(self) -> list[str]:
        if not self.available:
            return []
        try:
            output = subprocess.run(
                [self._binary, "--list-langs"],
                capture_output=True, text=True, timeout=20, check=False,
            )
            lines = [line.strip() for line in output.stdout.splitlines()]
            return [line for line in lines if line and "List of available" not in line]
        except (OSError, subprocess.SubprocessError):
            return []

    def status(self) -> dict:
        langs = self.languages_available()
        requested = [part for part in self.languages.split("+") if part]
        missing = [lang for lang in requested if lang not in langs]
        return {
            "available": self.available,
            "binary": self._binary,
            "languages": langs,
            "requested_languages": requested,
            "missing_languages": missing,
            "warning": (
                f"Die OCR-Sprachdaten {missing} fehlen. Installieren Sie im "
                f"Add-on die Pakete tesseract-ocr-{', tesseract-ocr-'.join(missing)}."
                if missing else None
            ),
        }

    def ocr_image(self, image_path: str | Path, *, languages: str | None = None,
                  timeout: int = OCR_TIMEOUT_SECONDS) -> OcrResult:
        if not self.available:
            return OcrResult(
                text="", confidence=0.0, engine="unavailable",
                needs_review=True, word_count=0,
            )
        lang = languages or self.languages
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                base = Path(tmpdir) / "out"
                completed = subprocess.run(
                    # ``tsv`` is a tesseract *config name*, not a ``--flag``.
                    [self._binary, str(image_path), str(base), "-l", lang, "tsv"],
                    capture_output=True, text=True, timeout=timeout, check=False,
                )
                tsv_path = Path(str(base) + ".tsv")
                if completed.returncode != 0 and not tsv_path.exists():
                    logger.warning("tesseract failed: %s", completed.stderr[:300])
                    return OcrResult(text="", confidence=0.0, engine="tesseract",
                                     needs_review=True)
                if not tsv_path.exists():
                    return OcrResult(text="", confidence=0.0, engine="tesseract",
                                     needs_review=True)
                return self._parse_tsv(tsv_path.read_text(encoding="utf-8", errors="replace"))
        except subprocess.TimeoutExpired:
            logger.warning("tesseract timed out on %s", image_path)
            return OcrResult(text="", confidence=0.0, engine="tesseract",
                             needs_review=True)
        except OSError as exc:
            logger.warning("tesseract could not run: %s", exc)
            return OcrResult(text="", confidence=0.0, engine="tesseract",
                             needs_review=True)

    @staticmethod
    def _parse_tsv(tsv_text: str) -> OcrResult:
        """Rebuild text from tesseract's TSV output and average the confidence."""

        reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
        words: list[str] = []
        confidences: list[float] = []
        lines: dict[tuple[int, int, int], list[str]] = {}
        for row in reader:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            try:
                conf = float(row.get("conf") or -1)
            except ValueError:
                conf = -1.0
            key = (
                int(row.get("block_num") or 0),
                int(row.get("par_num") or 0),
                int(row.get("line_num") or 0),
            )
            lines.setdefault(key, []).append(text)
            words.append(text)
            if conf >= 0:
                confidences.append(conf)

        text_out = "\n".join(" ".join(parts) for _, parts in sorted(lines.items()))
        confidence = round(sum(confidences) / len(confidences), 1) if confidences else 0.0
        word_count = len(words)
        needs_review = word_count == 0 or confidence < LOW_CONFIDENCE_THRESHOLD
        return OcrResult(
            text=text_out,
            confidence=confidence,
            engine="tesseract",
            needs_review=needs_review,
            word_count=word_count,
        )
