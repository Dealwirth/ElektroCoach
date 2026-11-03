"""Bibliothek: Dokumente, Seiten, Abschnitte, Duplikaterkennung und Suche."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from .. import db
from ..config import settings
from ..security import safe_filename, sha256_file
from . import offline, samsung_notes
from .ocr import (
    HTML_SUFFIXES,
    IMAGE_SUFFIXES,
    TEXT_SUFFIXES,
    DocumentResult,
    process_container_choice,
    process_html,
    process_image,
    process_pdf,
    process_text,
)

log = logging.getLogger(__name__)


def documents_dir() -> Path:
    path = settings.data_dir / "documents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pages_dir() -> Path:
    path = settings.data_dir / "pages"
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# Duplikate
# ---------------------------------------------------------------------------
def find_duplicate(sha256: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT id, filename, created_at FROM documents WHERE sha256 = ?", (sha256,)
    )
    return dict(row) if row else None


def near_duplicate_chunks(text: str, threshold: float | None = None, limit: int = 1) -> list[dict[str, Any]]:
    """Findet inhaltlich sehr aehnliche Abschnitte (Shingles + Kosinus)."""
    if threshold is None:
        threshold = settings.get_float("dedupe_threshold", 0.92)
    terms = offline.term_frequencies(text)
    if not terms:
        return []
    candidates = db.query(
        "SELECT c.id, c.text, c.document_id, d.filename FROM chunks c "
        "JOIN documents d ON d.id = c.document_id ORDER BY c.created_at DESC LIMIT 500"
    )
    hits: list[dict[str, Any]] = []
    for row in candidates:
        similarity = offline.cosine_similarity(terms, offline.term_frequencies(row["text"]))
        if similarity >= threshold:
            hits.append({
                "chunk_id": row["id"],
                "document_id": row["document_id"],
                "filename": row["filename"],
                "similarity": round(similarity, 3),
            })
    hits.sort(key=lambda item: -item["similarity"])
    return hits[:limit]


# ---------------------------------------------------------------------------
# Verarbeitung
# ---------------------------------------------------------------------------
def process_file(path: Path) -> DocumentResult:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return process_pdf(path)
    if suffix in IMAGE_SUFFIXES:
        return process_image(path)
    if suffix in samsung_notes.SAMSUNG_SUFFIXES | {".zip"}:
        return samsung_notes.process_container(path)
    if suffix in HTML_SUFFIXES:
        return process_html(path)
    if suffix in TEXT_SUFFIXES:
        return process_text(path)
    return process_container_choice(path)


def store_document(
    path: Path,
    original_name: str,
    collection: str | None = None,
    source: str = "upload",
    sha256: str | None = None,
) -> dict[str, Any]:
    """Legt ein Dokument an, verarbeitet es und schreibt Seiten und Abschnitte."""
    safe = safe_filename(original_name)
    digest = sha256 or sha256_file(path)
    doc_id = db.new_id()
    stored = documents_dir() / f"{doc_id}_{safe}"
    shutil.copy2(path, stored)

    db.insert(
        "INSERT INTO documents(id, filename, stored_path, mime, sha256, size_bytes, "
        "source, collection, status, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (doc_id, safe, str(stored), _mime_for(safe), digest, stored.stat().st_size,
         source, collection, "processing", db.now(), db.now()),
    )

    try:
        result = process_file(stored)
    except Exception as exc:  # noqa: BLE001 - Fehler pro Datei duerfen den Import nicht stoppen
        log.exception("Verarbeitung fehlgeschlagen fuer %s", safe)
        with db.write() as conn:
            conn.execute(
                "UPDATE documents SET status='error', error=?, updated_at=? WHERE id=?",
                (str(exc)[:500], db.now(), doc_id),
            )
        return {"id": doc_id, "status": "error", "error": str(exc), "filename": safe}

    page_ids: list[str] = []
    chunk_rows: list[tuple] = []
    for page in result.pages:
        page_id = db.new_id()
        image_path = None
        if page.image_bytes and settings.get_bool("keep_page_images", True):
            image_file = pages_dir() / f"{page_id}.png"
            image_file.write_bytes(page.image_bytes)
            image_path = str(image_file)
        db.insert(
            "INSERT INTO pages(id, document_id, page_number, image_path, text, "
            "ocr_confidence, needs_review, meta_json, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (page_id, doc_id, page.page_number, image_path, page.text,
             page.confidence, 1 if page.needs_review else 0,
             db.json_dumps_safe(page.meta), db.now()),
        )
        page_ids.append(page_id)

        for chunk in offline.chunk_text(page.text):
            chunk_rows.append((
                db.new_id(), doc_id, page_id, page.page_number,
                int(chunk["ordinal"]), chunk.get("heading"), str(chunk["text"]),
                int(chunk["tokens"]), 1 if page.needs_review else 0, db.now(),
            ))

    if chunk_rows:
        db.executemany(
            "INSERT INTO chunks(id, document_id, page_id, page_number, ordinal, heading, "
            "text, tokens, needs_review, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            chunk_rows,
        )

    status = "needs_review" if result.needs_review else "ready"
    with db.write() as conn:
        conn.execute(
            "UPDATE documents SET status=?, page_count=?, meta_json=?, updated_at=? WHERE id=?",
            (status, len(result.pages), db.json_dumps_safe(result.meta), db.now(), doc_id),
        )

    return {
        "id": doc_id,
        "status": status,
        "filename": safe,
        "pages": len(result.pages),
        "chunks": len(chunk_rows),
        "needs_review": result.needs_review,
        "kind": result.kind,
        "duplicate_of": None,
    }


def _mime_for(name: str) -> str:
    suffix = Path(name).suffix.lower()
    mapping = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".html": "text/html",
        ".csv": "text/csv",
        ".json": "application/json",
    }
    return mapping.get(suffix, "application/octet-stream")


# ---------------------------------------------------------------------------
# Abfragen
# ---------------------------------------------------------------------------
def list_documents(
    limit: int = 50, offset: int = 0, status: str | None = None,
    collection: str | None = None, search: str | None = None,
) -> dict[str, Any]:
    where = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if collection:
        where.append("collection = ?")
        params.append(collection)
    if search:
        where.append("filename LIKE ?")
        params.append(f"%{search}%")
    clause = f"WHERE {' AND '.join(where)}" if where else ""

    total_row = db.query_one(f"SELECT COUNT(*) AS n FROM documents {clause}", params)  # noqa: S608
    rows = db.query(
        f"SELECT id, filename, size_bytes, page_count, source, collection, status, error, "  # noqa: S608
        f"needs_review_count, created_at, updated_at FROM ("
        f"  SELECT d.*, (SELECT COUNT(*) FROM pages p WHERE p.document_id = d.id AND p.needs_review = 1)"
        f"  AS needs_review_count FROM documents d) {clause} "
        f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    return {
        "total": total_row["n"] if total_row else 0,
        "items": [dict(r) for r in rows],
        "limit": limit,
        "offset": offset,
    }


def collections() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT COALESCE(collection, '(ohne Sammlung)') AS name, COUNT(*) AS n "
        "FROM documents GROUP BY name ORDER BY n DESC"
    )
    return [dict(r) for r in rows]


def get_document(document_id: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM documents WHERE id = ?", (document_id,))
    return dict(row) if row else None


def get_pages(document_id: str) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT id, page_number, text, ocr_confidence, needs_review, image_path, meta_json "
        "FROM pages WHERE document_id = ? ORDER BY page_number",
        (document_id,),
    )
    return [dict(r) for r in rows]


def get_chunks(document_id: str, limit: int = 500) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT id, page_number, ordinal, heading, text, tokens, needs_review "
        "FROM chunks WHERE document_id = ? ORDER BY page_number, ordinal LIMIT ?",
        (document_id, limit),
    )
    return [dict(r) for r in rows]


def delete_document(document_id: str) -> bool:
    doc = get_document(document_id)
    if not doc:
        return False
    for page in get_pages(document_id):
        if page.get("image_path"):
            try:
                Path(page["image_path"]).unlink(missing_ok=True)
            except OSError:
                pass
    try:
        Path(doc["stored_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    db.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    return True


def needs_review_chunks(limit: int = 100) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT c.id, c.text, c.page_number, c.document_id, d.filename "
        "FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE c.needs_review = 1 ORDER BY d.created_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def update_page_text(page_id: str, text: str, clear_review: bool = True) -> bool:
    with db.write() as conn:
        conn.execute(
            "UPDATE pages SET text = ?, needs_review = CASE WHEN ? THEN 0 ELSE needs_review END "
            "WHERE id = ?",
            (text, 1 if clear_review else 0, page_id),
        )
        row = conn.execute("SELECT document_id, page_number FROM pages WHERE id = ?", (page_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM chunks WHERE page_id = ?", (page_id,))
        document_id = row["document_id"]
        page_number = row["page_number"]
        for chunk in offline.chunk_text(text):
            conn.execute(
                "INSERT INTO chunks(id, document_id, page_id, page_number, ordinal, heading, "
                "text, tokens, needs_review, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (db.new_id(), document_id, page_id, page_number, int(chunk["ordinal"]),
                 chunk.get("heading"), str(chunk["text"]), int(chunk["tokens"]), 0, db.now()),
            )
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM pages WHERE document_id = ? AND needs_review = 1",
            (document_id,),
        ).fetchone()
        if remaining and remaining["n"] == 0:
            conn.execute(
                "UPDATE documents SET status = 'ready', updated_at = ? WHERE id = ? AND status != 'error'",
                (db.now(), document_id),
            )
    return True


def search(query: str, limit: int = 25) -> dict[str, Any]:
    chunk_hits = db.search_chunks(query, limit=limit)
    results = []
    for row in chunk_hits:
        snippet = row["text"][:400]
        results.append({
            "kind": "chunk",
            "document_id": row["document_id"],
            "filename": row["filename"],
            "page_number": row["page_number"],
            "heading": row["heading"],
            "text": snippet,
            "score": row["rank"],
        })
    return {"query": query, "results": results, "count": len(results)}
