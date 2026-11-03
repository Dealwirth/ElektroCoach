"""Import, Dokumente, Seiten und Suche."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from .. import db
from ..config import settings
from ..security import is_allowed_upload, safe_filename
from ..services import library, samsung_notes
from ..workers import import_worker

log = logging.getLogger(__name__)

router = APIRouter(tags=["import"])

UPLOAD_DIR = settings.data_dir / "uploads"
MAX_UPLOAD_BYTES = 512 * 1024 * 1024


@router.get("/import/formats")
async def import_formats() -> dict[str, Any]:
    return samsung_notes.describe_import_formats()


@router.post("/import")
async def upload_and_import(
    files: list[UploadFile] = File(...),
    collection: str | None = Form(default=None),
) -> dict[str, Any]:
    """Nimmt mehrere Dateien an, speichert sie und startet den Hintergrundimport.

    Es wird bewusst nicht synchron verarbeitet: der Import laeuft im Worker,
    damit die Oberflaeche bedienbar bleibt und grosse Sammlungen das System
    nicht blockieren.
    """
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    accepted: list[tuple[str, str]] = []
    rejected: list[dict[str, str]] = []
    total_bytes = 0

    for upload in files:
        name = safe_filename(upload.filename or "datei")
        if not is_allowed_upload(name):
            rejected.append({"filename": name, "error": "Dateityp nicht unterstuetzt"})
            continue
        target = UPLOAD_DIR / f"{db.new_id()}_{name}"
        size = 0
        try:
            with target.open("wb") as handle:
                while True:
                    chunk = await upload.read(1 << 20)
                    if not chunk:
                        break
                    size += len(chunk)
                    total_bytes += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise ValueError("Datei groesser als 512 MB")
                    handle.write(chunk)
        except Exception as exc:  # noqa: BLE001
            target.unlink(missing_ok=True)
            rejected.append({"filename": name, "error": str(exc)[:200]})
            continue
        finally:
            await upload.close()
        accepted.append((str(target), name))

    if not accepted:
        raise HTTPException(
            status_code=400,
            detail={"message": "Keine verwertbaren Dateien empfangen", "rejected": rejected},
        )

    job_id = import_worker.create_job(accepted, collection=collection)
    import_worker.start_worker()
    import_worker.enqueue_job(job_id, [path for path, _ in accepted])

    return {
        "ok": True,
        "job_id": job_id,
        "accepted": len(accepted),
        "rejected": rejected,
        "total_bytes": total_bytes,
        "message": "Import gestartet. Der Fortschritt ist unter Import sichtbar.",
    }


@router.get("/import/jobs")
async def list_jobs(limit: int = 10) -> dict[str, Any]:
    from .. import db

    rows = db.query(
        "SELECT id, status, total_files, processed_files, failed_files, current_item, "
        "message, created_at, updated_at FROM import_jobs ORDER BY created_at DESC LIMIT ?",
        (max(1, min(50, limit)),),
    )
    return {"items": [dict(r) for r in rows], "queue": import_worker.queue_length()}


@router.get("/import/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job = import_worker.job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Importauftrag nicht gefunden")
    import json

    stats: dict[str, Any] = {}
    try:
        stats = json.loads(job.get("stats_json") or "{}")
    except json.JSONDecodeError:
        stats = {}
    job.pop("stats_json", None)
    job["results"] = stats.get("results", [])
    job["imported"] = stats.get("imported", 0)
    job["duplicates"] = stats.get("duplicates", 0)
    job["progress_percent"] = (
        round(100 * job["processed_files"] / job["total_files"], 1)
        if job["total_files"] else 0.0
    )
    return job


@router.post("/import/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    if not import_worker.request_cancel(job_id):
        raise HTTPException(status_code=400, detail="Auftrag kann nicht abgebrochen werden")
    return {"ok": True, "message": "Abbruch angefordert"}


@router.get("/documents")
async def list_documents(
    limit: int = 50, offset: int = 0, status: str | None = None,
    collection: str | None = None, search: str | None = None,
) -> dict[str, Any]:
    return library.list_documents(limit=limit, offset=offset, status=status,
                                  collection=collection, search=search)


@router.get("/documents/collections")
async def document_collections() -> dict[str, Any]:
    return {"items": library.collections()}


@router.get("/documents/{document_id}")
async def get_document(document_id: str) -> dict[str, Any]:
    document = library.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    document["pages"] = library.get_pages(document_id)
    return document


@router.get("/documents/{document_id}/chunks")
async def get_document_chunks(document_id: str, limit: int = 500) -> dict[str, Any]:
    return {"items": library.get_chunks(document_id, limit=limit)}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str) -> dict[str, Any]:
    if not library.delete_document(document_id):
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    return {"ok": True}


@router.get("/pages/{page_id}/image")
async def page_image(page_id: str) -> Any:
    from fastapi.responses import FileResponse
    from .. import db

    row = db.query_one("SELECT image_path FROM pages WHERE id = ?", (page_id,))
    if not row or not row["image_path"]:
        raise HTTPException(status_code=404, detail="Kein Seitenbild vorhanden")
    path = Path(row["image_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Bilddatei fehlt")
    return FileResponse(path, media_type="image/png")


class PageTextUpdate(BaseModel):
    text: str
    clear_review: bool = True


@router.put("/pages/{page_id}/text")
async def update_page_text(page_id: str, payload: PageTextUpdate) -> dict[str, Any]:
    if not library.update_page_text(page_id, payload.text, payload.clear_review):
        raise HTTPException(status_code=404, detail="Seite nicht gefunden")
    return {"ok": True}


@router.get("/review/pages")
async def review_pages(limit: int = 100) -> dict[str, Any]:
    from .. import db

    rows = db.query(
        "SELECT p.id, p.page_number, p.ocr_confidence, p.text, p.document_id, d.filename "
        "FROM pages p JOIN documents d ON d.id = p.document_id "
        "WHERE p.needs_review = 1 ORDER BY d.created_at DESC, p.page_number LIMIT ?",
        (max(1, min(500, limit)),),
    )
    return {"items": [dict(r) for r in rows], "count": len(rows)}


@router.get("/review/chunks")
async def review_chunks(limit: int = 100) -> dict[str, Any]:
    return {"items": library.needs_review_chunks(limit=limit)}


@router.get("/documents/{document_id}/export")
async def export_document(document_id: str) -> Any:
    """Exportiert die erkannten Texte eines Dokuments als Textdatei."""
    from fastapi.responses import PlainTextResponse

    document = library.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
    parts = [f"# {document['filename']}", ""]
    for page in library.get_pages(document_id):
        parts.append(f"## Seite {page['page_number']}")
        parts.append(page["text"] or "(kein Text erkannt)")
        parts.append("")
    return PlainTextResponse(
        "\n".join(parts),
        headers={"Content-Disposition": f'attachment; filename="{document["filename"]}.txt"'},
    )


@router.post("/documents/cleanup")
async def cleanup_uploads() -> dict[str, Any]:
    """Entfernt verwaiste Upload-Dateien, um Speicher zu sparen."""
    removed = 0
    if UPLOAD_DIR.exists():
        for item in UPLOAD_DIR.glob("*"):
            try:
                if item.is_file():
                    item.unlink()
                    removed += 1
            except OSError:
                pass
    tmp = settings.data_dir / "import_tmp"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    return {"ok": True, "removed": removed}
