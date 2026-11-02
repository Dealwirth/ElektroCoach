"""Document import, OCR review and knowledge base endpoints."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from .deps import get_context, translate_error
from ..backend.context import AppContext
from ..backend.util import human_bytes, safe_filename
from ..documents.taxonomy import SUBJECTS

logger = logging.getLogger("elektrocoach.api.documents")

router = APIRouter(prefix="/api", tags=["documents"])

ALLOWED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


@router.get("/documents")
async def list_documents(context: AppContext = Depends(get_context),
                         limit: int = Query(default=100, ge=1, le=500),
                         offset: int = Query(default=0, ge=0),
                         status_filter: str | None = Query(default=None, alias="status"),
                         ) -> dict[str, Any]:
    documents = context.repo.list_documents(limit=limit, offset=offset, status=status_filter)
    for document in documents:
        document["size_human"] = human_bytes(document.get("size_bytes") or 0)
    return {
        "items": documents,
        "total": context.repo.count_documents(),
        "pages_needing_review": len(context.repo.pages_needing_review(limit=1000)),
    }


@router.post("/documents/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    context: AppContext = Depends(get_context),
    file: UploadFile = File(...),
    subject: str | None = Form(default=None),
    use_vision: bool = Form(default=True),
) -> dict[str, Any]:
    """Accept an upload and queue it for processing.

    The file is validated (extension, size, non-empty) and stored under a
    generated name; the original name is kept only as metadata. Path traversal
    is impossible because the stored name is derived from the content hash and a
    sanitised basename.
    """

    original = safe_filename(file.filename or "dokument")
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=(f"Das Dateiformat „{suffix or 'unbekannt'}“ wird nicht "
                    "unterstützt. Unterstützt werden PDF, PNG, JPG, WEBP, BMP und TIFF."),
        )
    if subject and subject not in SUBJECTS:
        subject = None

    upload_dir = context.opts.path("uploads") / "incoming"
    upload_dir.mkdir(parents=True, exist_ok=True)
    temporary = upload_dir / f"{safe_filename(original, 'upload')}.part"
    size = 0
    try:
        with temporary.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    handle.close()
                    temporary.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=(f"Die Datei ist zu groß. Maximal erlaubt sind "
                                f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB."),
                    )
                handle.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise translate_error(exc, context="Upload speichern") from exc
    finally:
        await file.close()

    if size == 0:
        temporary.unlink(missing_ok=True)
        raise HTTPException(status_code=400,
                            detail="Die hochgeladene Datei ist leer.")

    job_id = context.repo.enqueue_job(
        type="import_document",
        payload={"path": str(temporary), "original_name": original,
                 "mime": file.content_type, "subject": subject,
                 "use_vision": use_vision},
        priority=3,
    )
    context.repo.audit("document.upload", target=original,
                       detail={"size": size, "job_id": job_id}, actor="user")
    return {
        "job_id": job_id,
        "original_name": original,
        "size_bytes": size,
        "size_human": human_bytes(size),
        "message": ("Die Datei wurde hochgeladen und wird jetzt verarbeitet. "
                    "Der Fortschritt erscheint im Bereich „Dokumentenimport“."),
    }


@router.get("/documents/jobs")
async def document_jobs(context: AppContext = Depends(get_context),
                        limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
    jobs = context.repo.list_jobs(limit=limit)
    relevant = [j for j in jobs if j["type"] in {"import_document", "reprocess_document",
                                                 "generate_questions"}]
    return {"items": relevant, "counts": context.repo.job_counts()}


@router.get("/documents/{document_id}")
async def get_document(document_id: int,
                       context: AppContext = Depends(get_context)) -> dict[str, Any]:
    document = context.repo.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404,
                            detail=f"Das Dokument {document_id} existiert nicht.")
    pages = context.repo.list_pages(document_id)
    document["pages"] = pages
    document["size_human"] = human_bytes(document.get("size_bytes") or 0)
    document["knowledge_count"] = int(context.db.scalar(
        "SELECT COUNT(*) FROM knowledge_items WHERE document_id = ?",
        (document_id,), default=0))
    return document


@router.post("/documents/{document_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(document_id: int,
                             context: AppContext = Depends(get_context)) -> dict[str, Any]:
    document = context.repo.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404,
                            detail=f"Das Dokument {document_id} existiert nicht.")
    job_id = context.repo.enqueue_job(
        type="reprocess_document", payload={"document_id": document_id}, priority=4,
    )
    return {"job_id": job_id,
            "message": "Das Dokument wird erneut verarbeitet."}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: int,
                          context: AppContext = Depends(get_context),
                          confirmed: bool = Query(default=False),
                          delete_knowledge: bool = Query(default=True)) -> dict[str, Any]:
    """Delete a document. Requires ``confirmed=true`` (destructive)."""

    if not confirmed:
        raise HTTPException(
            status_code=400,
            detail=("Das Löschen eines Dokuments ist endgültig. Bestätigen Sie mit "
                    "„confirmed=true“. Erstellen Sie vorher ein Backup."),
        )
    document = context.repo.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404,
                            detail=f"Das Dokument {document_id} existiert nicht.")

    with context.db.transaction() as conn:
        knowledge_removed = 0
        if delete_knowledge:
            cursor = conn.execute("DELETE FROM knowledge_items WHERE document_id = ?",
                                  (document_id,))
            knowledge_removed = cursor.rowcount or 0
        else:
            conn.execute("UPDATE knowledge_items SET document_id = NULL WHERE document_id = ?",
                         (document_id,))
        conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))

    stored = context.opts.path("uploads") / document["stored_name"]
    stored.unlink(missing_ok=True)
    shutil.rmtree(context.opts.path("pages") / str(document_id), ignore_errors=True)

    context.repo.audit("document.delete", target=document["original_name"],
                       detail={"knowledge_removed": knowledge_removed}, actor="user")
    return {"deleted": document_id, "knowledge_removed": knowledge_removed,
            "message": f"Das Dokument „{document['original_name']}“ wurde gelöscht."}


# -- pages under review ------------------------------------------------------

@router.get("/documents/pages/review")
async def pages_under_review(context: AppContext = Depends(get_context),
                             limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
    pages = context.repo.pages_needing_review(limit=limit)
    for page in pages:
        page["text_preview"] = (page.get("text") or "")[:400]
        page["has_image"] = bool(page.get("image_path"))
    return {"items": pages, "count": len(pages)}


@router.get("/documents/pages/{page_id}/image")
async def page_image(page_id: int, context: AppContext = Depends(get_context)):
    from fastapi.responses import FileResponse

    page = context.repo.get_page(page_id)
    if page is None or not page.get("image_path"):
        raise HTTPException(status_code=404,
                            detail="Für diese Seite ist kein Bild gespeichert.")
    path = Path(page["image_path"])
    pages_root = context.opts.path("pages").resolve()
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Das Bild ist nicht lesbar.") from exc
    # Path traversal guard: the image must live inside the pages directory.
    if pages_root not in resolved.parents and resolved != pages_root:
        logger.warning("blocked out-of-tree page image request: %s", path)
        raise HTTPException(status_code=403, detail="Zugriff verweigert.")
    if not resolved.is_file():
        raise HTTPException(status_code=404,
                            detail="Die Bilddatei wurde nicht gefunden.")
    return FileResponse(resolved)


@router.patch("/documents/pages/{page_id}")
async def update_page(page_id: int, payload: dict[str, Any],
                      context: AppContext = Depends(get_context)) -> dict[str, Any]:
    """Correct a page's text after review, and refresh the knowledge items."""

    page = context.repo.get_page(page_id)
    if page is None:
        raise HTTPException(status_code=404, detail=f"Die Seite {page_id} existiert nicht.")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400,
                            detail="Der Text darf nicht leer sein.")
    context.repo.update_page(page_id, text=text, needs_review=0)
    context.repo.update_page(page_id, ocr_engine="manuell-korrigiert")
    context.repo.audit("page.correct", target=str(page_id), actor="user")
    return {"page_id": page_id, "text": text,
            "message": ("Der Text wurde gespeichert und die Seite ist nicht mehr "
                        "zur Prüfung markiert.")}


# -- knowledge base ----------------------------------------------------------

@router.get("/knowledge")
async def list_knowledge(context: AppContext = Depends(get_context),
                         limit: int = Query(default=50, ge=1, le=200),
                         offset: int = Query(default=0, ge=0),
                         subject: str | None = None,
                         topic: str | None = None,
                         uncertainty_only: bool = False) -> dict[str, Any]:
    items = context.repo.list_knowledge(limit=limit, offset=offset, subject=subject,
                                        topic=topic, uncertainty_only=uncertainty_only)
    return {
        "items": items,
        "total": context.repo.count_knowledge(),
        "topics": context.repo.knowledge_topics(),
    }


@router.get("/knowledge/search")
async def search_knowledge(context: AppContext = Depends(get_context),
                           q: str = Query(min_length=1, max_length=200),
                           limit: int = Query(default=25, ge=1, le=100),
                           subject: str | None = None) -> dict[str, Any]:
    results = context.repo.search_knowledge(q, limit=limit, subject=subject)
    return {
        "items": results,
        "count": len(results),
        "engine": "fts5" if context.db.fts5_available else "like",
        "query": q,
    }


@router.get("/knowledge/{item_id}")
async def get_knowledge(item_id: int,
                        context: AppContext = Depends(get_context)) -> dict[str, Any]:
    item = context.repo.get_knowledge(item_id)
    if item is None:
        raise HTTPException(status_code=404,
                            detail=f"Der Wissenseintrag {item_id} existiert nicht.")
    return item


@router.patch("/knowledge/{item_id}")
async def update_knowledge(item_id: int, payload: dict[str, Any],
                           context: AppContext = Depends(get_context)) -> dict[str, Any]:
    item = context.repo.get_knowledge(item_id)
    if item is None:
        raise HTTPException(status_code=404,
                            detail=f"Der Wissenseintrag {item_id} existiert nicht.")
    allowed = {k: v for k, v in payload.items()
               if k in {"title", "content", "subject", "topic", "subtopic",
                        "quality", "uncertainty", "source_label", "page_number"}}
    if not allowed:
        raise HTTPException(status_code=400,
                            detail="Es wurden keine änderbaren Felder übergeben.")
    context.repo.update_knowledge(item_id, **allowed)
    context.repo.audit("knowledge.update", target=str(item_id), actor="user")
    return context.repo.get_knowledge(item_id)


@router.delete("/knowledge/{item_id}")
async def delete_knowledge(item_id: int,
                           context: AppContext = Depends(get_context)) -> dict[str, Any]:
    item = context.repo.get_knowledge(item_id)
    if item is None:
        raise HTTPException(status_code=404,
                            detail=f"Der Wissenseintrag {item_id} existiert nicht.")
    context.repo.delete_knowledge(item_id)
    context.repo.audit("knowledge.delete", target=str(item_id), actor="user")
    return {"deleted": item_id}
