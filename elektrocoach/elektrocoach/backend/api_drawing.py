"""Drawing editor endpoints: symbol library, save/load, validate, export."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .deps import get_context, translate_error
from ..backend.context import AppContext
from ..drawing.exporter import to_pdf, to_svg
from ..drawing.model import netlist, normalise_document, validate
from ..drawing.symbols import CATEGORIES, GRID_SIZE, get_symbol, library_as_list, search

logger = logging.getLogger("elektrocoach.api.drawing")

router = APIRouter(prefix="/api/drawing", tags=["drawing"])


class DrawingSaveRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    data: dict[str, Any]
    thumbnail: str | None = Field(default=None, max_length=400000)


class ValidateRequest(BaseModel):
    data: dict[str, Any]


class ExportRequest(BaseModel):
    data: dict[str, Any]
    title: str = Field(default="Schaltplan", max_length=120)
    grid: bool = True


@router.get("/library")
async def symbol_library(q: str | None = None) -> dict[str, Any]:
    symbols = search(q) if q else library_as_list()
    return {"items": symbols, "categories": CATEGORIES, "grid_size": GRID_SIZE,
            "count": len(symbols)}


@router.get("/library/{symbol_id}")
async def symbol_detail(symbol_id: str) -> dict[str, Any]:
    symbol = get_symbol(symbol_id)
    if symbol is None:
        raise HTTPException(status_code=404,
                            detail=f"Das Symbol „{symbol_id}“ existiert nicht.")
    return symbol


@router.get("/drawings")
async def list_drawings(context: AppContext = Depends(get_context)) -> dict[str, Any]:
    return {"items": context.repo.list_drawings(limit=200)}


@router.post("/drawings", status_code=status.HTTP_201_CREATED)
async def create_drawing(payload: DrawingSaveRequest,
                         context: AppContext = Depends(get_context)) -> dict[str, Any]:
    document = normalise_document(payload.data)
    try:
        drawing_id = context.repo.create_drawing(
            name=payload.name, data=document, thumbnail=payload.thumbnail,
        )
        context.repo.audit("drawing.create", target=payload.name, actor="user")
    except Exception as exc:  # noqa: BLE001
        raise translate_error(exc, context="Schaltplan speichern") from exc
    return {"id": drawing_id, "name": payload.name,
            "message": "Der Schaltplan wurde gespeichert."}


@router.get("/drawings/{drawing_id}")
async def get_drawing(drawing_id: int,
                      context: AppContext = Depends(get_context)) -> dict[str, Any]:
    drawing = context.repo.get_drawing(drawing_id)
    if drawing is None:
        raise HTTPException(status_code=404,
                            detail=f"Der Schaltplan {drawing_id} existiert nicht.")
    return drawing


@router.put("/drawings/{drawing_id}")
async def update_drawing(drawing_id: int, payload: DrawingSaveRequest,
                         context: AppContext = Depends(get_context)) -> dict[str, Any]:
    drawing = context.repo.get_drawing(drawing_id)
    if drawing is None:
        raise HTTPException(status_code=404,
                            detail=f"Der Schaltplan {drawing_id} existiert nicht.")
    document = normalise_document(payload.data)
    context.repo.update_drawing(drawing_id, name=payload.name, data=document,
                                thumbnail=payload.thumbnail)
    context.repo.audit("drawing.update", target=payload.name, actor="user")
    return {"id": drawing_id, "version": (context.repo.get_drawing(drawing_id) or {}).get("version"),
            "message": "Der Schaltplan wurde gespeichert."}


@router.delete("/drawings/{drawing_id}")
async def delete_drawing(drawing_id: int,
                         context: AppContext = Depends(get_context)) -> dict[str, Any]:
    drawing = context.repo.get_drawing(drawing_id)
    if drawing is None:
        raise HTTPException(status_code=404,
                            detail=f"Der Schaltplan {drawing_id} existiert nicht.")
    context.repo.delete_drawing(drawing_id)
    context.repo.audit("drawing.delete", target=str(drawing_id), actor="user")
    return {"deleted": drawing_id}


@router.post("/validate")
async def validate_drawing(payload: ValidateRequest) -> dict[str, Any]:
    document = normalise_document(payload.data)
    report = validate(document)
    result = report.as_dict()
    result["netlist"] = netlist(document)
    return result


@router.post("/export/svg")
async def export_svg(payload: ExportRequest) -> Response:
    document = normalise_document(payload.data)
    svg = to_svg(document, with_grid=payload.grid, title=payload.title)
    return Response(
        content=svg.encode("utf-8"),
        media_type="image/svg+xml",
        headers={"Content-Disposition": f'inline; filename="{_safe(payload.title)}.svg"'},
    )


@router.post("/export/pdf")
async def export_pdf(payload: ExportRequest) -> Response:
    document = normalise_document(payload.data)
    pdf = to_pdf(document, title=payload.title)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_safe(payload.title)}.pdf"'},
    )


def _safe(name: str) -> str:
    from ..backend.util import safe_filename

    return safe_filename(name, "schaltplan")
