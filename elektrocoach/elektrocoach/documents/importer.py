"""Document import pipeline.

Flow for one uploaded file:

1. Reject duplicates by SHA-256 (re-importing the same file is a no-op).
2. Store the original under ``<data>/uploads`` and remember its metadata.
3. Split the file into pages. Digital PDF text is used directly; scanned pages
   and images are rasterised.
4. For each rasterised page:
   * printed text  -> local OCR (tesseract),
   * low confidence or handwriting -> Gemini vision (if configured),
   * no reliable result -> the page is stored and flagged ``needs_review``.
   **Nothing is invented.** Unreadable passages are marked as such.
5. Chunk the text, classify it with the keyword taxonomy, optionally refine with
   the local model, and store it in the knowledge base with source and page.

The whole pipeline is resumable: a failure marks the document ``failed`` with a
readable error, and the original file stays available for a retry.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..ai.base import AIError
from ..ai.gemini_client import encode_image_for_gemini
from ..backend.util import safe_filename, sha256_file, utcnow_iso
from . import pdf_tools
from .extractor import build_chunks, deduplicate, refine_with_ai
from .ocr import OcrEngine, OcrResult

logger = logging.getLogger("elektrocoach.documents.importer")

ProgressCallback = Callable[[float, str], None]

HANDWRITING_PROMPT = """Du wertest eine Seite aus den handschriftlichen oder \
gemischten Notizen eines Auszubildenden zum Elektroniker für Energie- und \
Gebäudetechnik aus.

Regeln:
- Erfinde niemals Inhalte. Wenn eine Stelle nicht sicher lesbar ist, schreibe \
an dieser Stelle [unleserlich] in den Text und führe sie in "uncertain" auf.
- Übernimm Fachbegriffe, Formeln, Einheiten und Zahlen exakt so, wie sie \
erkennbar sind.
- Beschreibe Schaltpläne und Zeichnungen sachlich in "drawing".

Antworte ausschließlich mit JSON in genau dieser Form:
{
  "text": "der erkannte Text, Absätze mit \\n getrennt",
  "confidence": 0.0,
  "uncertain": ["unleserliche Stelle 1", "..."],
  "contains_drawing": false,
  "drawing": "kurze Beschreibung des Schaltplans oder der Zeichnung",
  "subject_hint": "vermutetes Fachgebiet oder null"
}
"confidence" ist eine Zahl zwischen 0 und 1 für die gesamte Seite."""


@dataclass
class ImportSummary:
    document_id: int
    pages: int = 0
    pages_ocr: int = 0
    pages_vision: int = 0
    pages_needing_review: int = 0
    knowledge_created: int = 0
    knowledge_duplicate: int = 0
    refined_by_ai: int = 0
    duplicate_of: int | None = None
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "pages": self.pages,
            "pages_ocr": self.pages_ocr,
            "pages_vision": self.pages_vision,
            "pages_needing_review": self.pages_needing_review,
            "knowledge_created": self.knowledge_created,
            "knowledge_duplicate": self.knowledge_duplicate,
            "refined_by_ai": self.refined_by_ai,
            "duplicate_of": self.duplicate_of,
            "warnings": self.warnings,
        }


class DocumentImporter:
    def __init__(self, repo, opts, dispatcher=None, ocr: OcrEngine | None = None) -> None:
        self.repo = repo
        self.opts = opts
        self.dispatcher = dispatcher
        self.ocr = ocr or OcrEngine(getattr(opts, "ocr_language", "deu+eng"))

    # -- public API -----------------------------------------------------------

    def import_file(self, source_path: str | Path, *, original_name: str | None = None,
                    mime: str | None = None, subject: str | None = None,
                    use_vision: bool = True,
                    progress: ProgressCallback | None = None) -> ImportSummary:
        source = Path(source_path)
        if not source.is_file():
            raise FileNotFoundError(f"Die Datei {source} wurde nicht gefunden.")
        original = safe_filename(original_name or source.name, "dokument")
        digest = sha256_file(source)

        existing = self.repo.find_document_by_hash(digest)
        if existing:
            logger.info("document %s is a duplicate of %s", original, existing["id"])
            summary = ImportSummary(document_id=int(existing["id"]),
                                    duplicate_of=int(existing["id"]))
            summary.warnings.append(
                f"Die Datei „{original}“ wurde bereits am "
                f"{existing['created_at']} importiert. Es wurden keine Duplikate angelegt."
            )
            return summary

        stored_name = f"{digest[:12]}_{original}"
        stored_path = self.opts.path("uploads") / stored_name
        self.opts.path("uploads").mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, stored_path)

        document_id = self.repo.create_document(
            original_name=original, stored_name=stored_name, mime=mime or _guess_mime(original),
            size_bytes=stored_path.stat().st_size, sha256=digest,
            status="processing", subject=subject, source="upload",
        )
        summary = ImportSummary(document_id=document_id)

        try:
            self._process(document_id, stored_path, original, summary, subject, use_vision,
                          progress)
        except Exception as exc:  # noqa: BLE001 - the document keeps its error state
            logger.exception("import failed for %s", original)
            self.repo.update_document(document_id, status="failed", error=str(exc)[:500])
            self.repo.add_event(
                level="error", category="documents",
                message=f"Import von „{original}“ fehlgeschlagen: {exc}",
                details={"document_id": document_id},
            )
            raise

        self.repo.audit("document.import", target=original, detail=summary.as_dict())
        return summary

    # -- pipeline -------------------------------------------------------------

    def _process(self, document_id: int, stored_path: Path, original: str,
                 summary: ImportSummary, subject: str | None, use_vision: bool,
                 progress: ProgressCallback | None) -> None:
        def report(value: float, message: str) -> None:
            if progress:
                progress(max(0.0, min(1.0, value)), message)

        report(0.05, "Seiten werden erkannt …")
        work_dir = self.opts.path("tmp") / f"import-{document_id}"
        work_dir.mkdir(parents=True, exist_ok=True)
        pages_dir = self.opts.path("pages") / str(document_id)
        pages_dir.mkdir(parents=True, exist_ok=True)

        try:
            pages = pdf_tools.prepare_pages(stored_path, work_dir)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        if not pages:
            raise ValueError(
                f"Aus „{original}“ konnten keine Seiten gelesen werden. "
                "Die Datei ist möglicherweise beschädigt."
            )

        summary.pages = len(pages)
        total = len(pages)
        all_chunks = []

        for index, page in enumerate(pages, start=1):
            base = 0.1 + (index - 1) / total * 0.75
            report(base, f"Seite {index} von {total} wird verarbeitet …")
            stored_image: Path | None = None
            if page.image_path and page.image_path.exists():
                stored_image = pages_dir / f"page-{page.number:04d}.png"
                shutil.copy2(page.image_path, stored_image)

            text = page.text
            engine: str | None = "pdf-text" if page.source == "text" else None
            # Confidence is stored as a percentage (0-100) for every engine.
            confidence: float | None = 100.0 if page.source == "text" else None
            needs_review = False

            if page.source != "text":
                ocr_result = self._run_ocr(page.image_path) if page.image_path else None
                if ocr_result and ocr_result.word_count > 0:
                    text = ocr_result.text
                    engine = ocr_result.engine
                    confidence = ocr_result.confidence
                    needs_review = ocr_result.needs_review
                    summary.pages_ocr += 1

                needs_vision = (
                    use_vision
                    and self.dispatcher is not None
                    and page.image_path is not None
                    and (not text.strip() or needs_review)
                )
                if needs_vision:
                    vision = self._run_vision(page.image_path)
                    if vision is not None:
                        vision_text, vision_conf, vision_uncertain, drawing = vision
                        if vision_text.strip():
                            text = vision_text
                            engine = "gemini-vision"
                            confidence = vision_conf
                            needs_review = bool(vision_uncertain)
                            summary.pages_vision += 1
                        if drawing:
                            all_chunks.extend(self._drawing_chunks(
                                drawing, original, page.number, vision_conf
                            ))

                if not text.strip() and not needs_review:
                    needs_review = True

            if needs_review:
                summary.pages_needing_review += 1

            page_id = self.repo.add_page(
                document_id=document_id, page_number=page.number,
                image_path=str(stored_image) if stored_image else None,
                text=text or None, ocr_engine=engine, ocr_confidence=confidence,
                needs_review=needs_review,
            )

            if text.strip():
                chunks = build_chunks(
                    text, source_label=original, page_number=page.number,
                    page_quality=(confidence or 0.0) / 100.0,
                    page_uncertain=needs_review,
                )
                for chunk in chunks:
                    chunk.metadata["page_id"] = page_id
                all_chunks.extend(chunks)

        report(0.88, "Inhalte werden sortiert und gespeichert …")
        all_chunks = deduplicate(all_chunks)

        if self.dispatcher is not None and all_chunks:
            refined = self._safe_refine(all_chunks)
            summary.refined_by_ai = refined

        for chunk in all_chunks:
            _, created = self.repo.upsert_knowledge(
                title=chunk.title,
                content=chunk.content,
                subject=subject or chunk.subject,
                topic=chunk.topic,
                document_id=document_id,
                page_id=chunk.metadata.get("page_id"),
                source_label=original,
                page_number=chunk.metadata.get("page"),
                quality=float(chunk.metadata.get("quality") or 0.8),
                uncertainty=chunk.uncertainty,
            )
            if created:
                summary.knowledge_created += 1
            else:
                summary.knowledge_duplicate += 1

        if summary.pages_needing_review:
            summary.warnings.append(
                f"{summary.pages_needing_review} Seite(n) konnten nicht sicher erkannt "
                "werden und sind zur Prüfung markiert. Bitte im Bereich "
                "„Dokumentenimport“ prüfen und den Text bei Bedarf korrigieren."
            )
        if summary.knowledge_created == 0 and summary.pages:
            summary.warnings.append(
                "Es wurde kein Textinhalt gespeichert. Möglicherweise enthält das "
                "Dokument nur Zeichnungen oder die Erkennung ist fehlgeschlagen."
            )

        self.repo.update_document(
            document_id, status="processed", page_count=len(pages),
            error=None if not summary.pages_needing_review else "review_needed",
        )
        report(1.0, "Import abgeschlossen.")

        # Clean up the temporary rasterised pages.
        shutil.rmtree(work_dir, ignore_errors=True)

    # -- steps ----------------------------------------------------------------

    def _run_ocr(self, image_path: Path) -> OcrResult | None:
        if not self.ocr.available:
            return None
        return self.ocr.ocr_image(image_path)

    def _run_vision(self, image_path: Path) -> tuple[str, float, list[str], str] | None:
        """Ask Gemini to read a page. Returns ``(text, confidence, uncertain, drawing)``."""

        assert self.dispatcher is not None
        try:
            image = encode_image_for_gemini(str(image_path))
        except AIError as exc:
            logger.warning("vision skipped: %s", exc)
            return None
        try:
            payload = self._run_vision_sync(image)
        except Exception as exc:  # noqa: BLE001 - vision is best effort
            logger.warning("gemini vision failed: %s", exc)
            self.repo.add_event(
                level="warning", category="documents",
                message=f"Handschrifterkennung über Gemini fehlgeschlagen: {exc}",
                details={"image": image_path.name},
            )
            return None
        if not isinstance(payload, dict):
            return None
        text = str(payload.get("text") or "")
        try:
            confidence = float(payload.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        uncertain = [str(x) for x in (payload.get("uncertain") or []) if str(x).strip()]
        drawing = str(payload.get("drawing") or "").strip()
        if payload.get("contains_drawing") and not drawing:
            drawing = "Zeichnung erkannt, aber nicht beschrieben."
        return text, max(0.0, min(1.0, confidence)) * 100.0, uncertain, drawing

    def _run_vision_sync(self, image: dict[str, str]) -> Any:
        """Bridge the async dispatcher for the synchronous job worker."""

        import asyncio

        from ..backend.runtime import run_coroutine

        payload, _ = run_coroutine(
            self.dispatcher.ask_json(
                "handwriting", HANDWRITING_PROMPT, images=[image], max_tokens=2048,
                use_cache=False,
            )
        )
        return payload

    def _drawing_chunks(self, description: str, source_label: str, page_number: int,
                        confidence: float) -> list:
        from .extractor import Chunk

        subject, topic, _ = _classify_drawing(description)
        return [Chunk(
            title=f"Schaltplan/Zeichnung auf Seite {page_number}",
            content=description,
            subject=subject,
            topic=topic,
            confidence=0.0,
            uncertainty=False,
            metadata={"source": source_label, "page": page_number,
                      "quality": (confidence or 50) / 100.0, "kind": "drawing"},
        )]

    def _safe_refine(self, chunks: list) -> int:
        import asyncio

        from ..backend.runtime import run_coroutine

        try:
            return run_coroutine(refine_with_ai(self.dispatcher, chunks))
        except Exception as exc:  # noqa: BLE001 - optional step
            logger.debug("AI refinement skipped: %s", exc)
            return 0

    # -- helpers --------------------------------------------------------------

    def reprocess(self, document_id: int, *, use_vision: bool = True,
                  progress: ProgressCallback | None = None) -> ImportSummary:
        """Re-run processing for an existing document (e.g. after a failure)."""

        document = self.repo.get_document(document_id)
        if document is None:
            raise ValueError(f"Das Dokument {document_id} existiert nicht.")
        stored_path = self.opts.path("uploads") / document["stored_name"]
        if not stored_path.is_file():
            raise FileNotFoundError(
                f"Die gespeicherte Datei „{document['stored_name']}“ fehlt. "
                "Bitte das Dokument erneut importieren."
            )
        # Clear previous pages/knowledge for this document so a retry is clean.
        self.repo.db.execute("DELETE FROM knowledge_items WHERE document_id = ?", (document_id,))
        self.repo.db.execute("DELETE FROM document_pages WHERE document_id = ?", (document_id,))
        self.repo.update_document(document_id, status="processing", error=None)

        summary = ImportSummary(document_id=document_id)
        self._process(document_id, stored_path, document["original_name"], summary,
                      document.get("subject"), use_vision, progress)
        return summary


def _guess_mime(name: str) -> str:
    import mimetypes

    mime, _ = mimetypes.guess_type(name)
    return mime or "application/octet-stream"


def _classify_drawing(text: str) -> tuple[str | None, str | None, float]:
    from .taxonomy import classify

    return classify(text)
