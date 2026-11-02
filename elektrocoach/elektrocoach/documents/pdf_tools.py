"""PDF and image helpers.

* Digital PDFs are read with ``pypdf`` (fast, no external binary needed).
* PDFs that contain no text layer (scans) are rasterised with ``pdftoppm``
  from ``poppler-utils`` and then processed with OCR or Gemini vision.
* Images are converted to a bounded resolution before OCR/vision to keep memory
  and Gemini token usage low.

Every external tool is optional at runtime: if it is missing the helper reports
that clearly instead of raising an opaque error.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("elektrocoach.documents.pdf")

RASTER_DPI = 200
MAX_IMAGE_EDGE = 2200  # px, keeps scans readable while bounding memory/tokens
RASTER_TIMEOUT = 300

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
PDF_SUFFIXES = {".pdf"}


@dataclass
class Page:
    number: int
    text: str
    image_path: Path | None = None
    source: str = "text"  # "text" | "raster" | "image"


def pdftoppm_available() -> bool:
    return shutil.which("pdftoppm") is not None


def extract_pdf_text(path: Path) -> list[str]:
    """Return the embedded text of each page (empty strings for image pages)."""

    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - pypdf is a hard dependency
        logger.error("pypdf is not installed; cannot read PDF text")
        return []

    try:
        reader = PdfReader(str(path))
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001 - password-protected files
                logger.warning("PDF %s is encrypted", path.name)
                return []
        pages: list[str] = []
        for page in reader.pages:
            try:
                pages.append((page.extract_text() or "").strip())
            except Exception as exc:  # noqa: BLE001 - a broken page must not abort
                logger.warning("text extraction failed for a page of %s: %s", path.name, exc)
                pages.append("")
        return pages
    except Exception as exc:  # noqa: BLE001
        logger.warning("could not read PDF %s: %s", path.name, exc)
        return []


def pdf_page_count(path: Path) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001
        return 0


def rasterize_pdf(path: Path, out_dir: Path, *, dpi: int = RASTER_DPI,
                  first: int | None = None, last: int | None = None) -> list[Path]:
    """Render PDF pages to PNG files. Returns the created files in page order."""

    if not pdftoppm_available():
        logger.warning("pdftoppm is not available; cannot rasterise %s", path.name)
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = out_dir / "page"
    command = ["pdftoppm", "-r", str(dpi), "-png"]
    if first is not None:
        command += ["-f", str(first)]
    if last is not None:
        command += ["-l", str(last)]
    command += [str(path), str(prefix)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   timeout=RASTER_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("rasterisation failed for %s: %s", path.name, exc)
        return []
    if completed.returncode != 0:
        logger.warning("pdftoppm failed for %s: %s", path.name, completed.stderr[:300])
    files = sorted(out_dir.glob("page*.png"))
    normalised: list[Path] = []
    for file in files:
        normalised.append(downscale_image(file))
    return normalised


def downscale_image(path: Path, max_edge: int = MAX_IMAGE_EDGE) -> Path:
    """Limit image size for OCR and vision. Returns the (possibly new) path."""

    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow is a hard dependency
        return path
    try:
        with Image.open(path) as image:
            width, height = image.size
            if max(width, height) <= max_edge:
                return path
            scale = max_edge / float(max(width, height))
            new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
            resized = image.convert("RGB").resize(new_size, Image.LANCZOS)
            resized.save(path, format="PNG", optimize=True)
        return path
    except Exception as exc:  # noqa: BLE001 - a failed resize is not fatal
        logger.warning("could not resize %s: %s", path.name, exc)
        return path


def prepare_pages(path: Path, work_dir: Path) -> list[Page]:
    """Turn a supported file into a list of :class:`Page` objects.

    PDF with a text layer -> text pages.
    PDF without a text layer -> rasterised pages for OCR/vision.
    Image -> a single rasterised page.
    """

    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        copied = work_dir / f"page-1{path.suffix.lower()}"
        work_dir.mkdir(parents=True, exist_ok=True)
        copied.write_bytes(path.read_bytes())
        return [Page(number=1, text="", image_path=downscale_image(copied), source="image")]

    if suffix in PDF_SUFFIXES:
        texts = extract_pdf_text(path)
        pages: list[Page] = []
        needs_raster: list[int] = []
        for index, text in enumerate(texts, start=1):
            if len(text.strip()) >= 40:
                pages.append(Page(number=index, text=text, source="text"))
            else:
                needs_raster.append(index)
                pages.append(Page(number=index, text=text, source="raster"))
        if needs_raster:
            images = rasterize_pdf(path, work_dir)
            # pdftoppm names files by page number; map them back by order.
            for offset, image in enumerate(images):
                if offset < len(needs_raster):
                    page_number = needs_raster[offset]
                    for page in pages:
                        if page.number == page_number:
                            page.image_path = image
                            break
        return pages

    raise ValueError(
        f"Das Dateiformat „{suffix or 'unbekannt'}“ wird nicht unterstützt. "
        "Unterstützt werden PDF, PNG, JPG, WEBP, BMP und TIFF."
    )


def tool_status() -> dict:
    return {
        "pdftoppm": pdftoppm_available(),
        "pypdf": _module_available("pypdf"),
        "pillow": _module_available("PIL"),
    }


def _module_available(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False
