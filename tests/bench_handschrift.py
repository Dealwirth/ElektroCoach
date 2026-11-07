"""Manueller Vergleich der Handschrifterkennung gegen einen Solltext.

Kein pytest-Test (der Name beginnt nicht mit ``test_``), sondern ein Werkzeug
fuer die Entwicklung: es liest ein Bild mit der vollen Pipeline und vergleicht
das Ergebnis mit ``tests/data/handschrift_rechnungen_gt.txt``.

Aufruf::

    ELEKTROCOACH_TROCR_DIR=elektrocoach/models/trocr-de \
    ELEKTROCOACH_OLLAMA_URL=http://localhost:11434 \
    .venv/bin/python tests/bench_handschrift.py [BILD] [--model NAME]

Kennzahlen: CER (Zeichenfehlerrate, kleiner ist besser) und der Anteil der
Zahlen aus dem Solltext, die im Ergebnis vorkommen.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import os
import re
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "elektrocoach"))

os.environ.setdefault("ELEKTROCOACH_DATA", str(Path("/tmp") / "ec_bench"))

from PIL import Image  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import handwriting, handwriting_post, handwriting_vision  # noqa: E402

DEFAULT_IMAGE = Path("/workspace/testdata/user/Screenshot_20261104-173132.png")
GT_FILE = Path(__file__).resolve().parent / "data" / "handschrift_rechnungen_gt.txt"


def _norm(text: str) -> str:
    # Hochgestellte Zeichen (mm²) entfernen, sonst zaehlt die 2 als Ziffer.
    return re.sub(r"[ \t]+", " ", text.replace("\u00b2", "").replace("\u00b3", "")).strip()


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?", _norm(text))


def _cer(reference: str, hypothesis: str) -> float:
    ratio = difflib.SequenceMatcher(None, _norm(reference), _norm(hypothesis)).ratio()
    return (1 - ratio) * 100


def _number_score(reference: str, hypothesis: str) -> tuple[int, int, list[str]]:
    expected = _numbers(reference)
    found = _numbers(hypothesis)
    hit = [n for n in expected if n in found]
    return len(hit), len(expected), [n for n in expected if n not in found]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", default=str(DEFAULT_IMAGE))
    parser.add_argument("--model", default="qwen2.5vl:7b")
    parser.add_argument("--passes", type=int, default=None)
    parser.add_argument("--no-refine", action="store_true")
    args = parser.parse_args()

    settings.set_runtime("ollama_enabled", True)
    settings.set_runtime("ollama_url", os.environ.get("ELEKTROCOACH_OLLAMA_URL", "http://localhost:11434"))
    settings.set_runtime("ollama_vision_model", args.model)
    if args.passes is not None:
        settings.set_runtime("ocr_vision_passes", args.passes)
    if args.no_refine:
        settings.set_runtime("ocr_refine_formulas", False)

    reference = GT_FILE.read_text(encoding="utf-8")
    page = handwriting.preprocess(Image.open(args.image).convert("RGB"))
    lines = handwriting.segment_lines(page)
    print(f"Bild {args.image}  {page.size}  {len(lines)} Zeilen  Modell {args.model}")

    started = time.time()
    result = asyncio.run(handwriting_vision.transcribe(page, model_name=args.model))
    elapsed = time.time() - started
    raw = str(result.get("text") or "")
    print(f"\n--- Roh ({elapsed:.0f}s, ok={result.get('ok')}) ---\n{raw}")

    post = handwriting_post.postprocess(raw, "formula")
    print(f"\n--- Nachbearbeitet ---\n{post}")

    hit, total, missing = _number_score(reference, post)
    print(
        f"\nCER {_cer(reference, post):.1f}%  "
        f"Zahlen {hit}/{total} = {hit / total * 100:.0f}%  fehlt {missing}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
