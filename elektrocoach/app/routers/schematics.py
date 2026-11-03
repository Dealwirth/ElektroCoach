"""Schaltplan-Editor: Projekte, Symbolbibliothek, Pruefung und Export."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services import schematic

log = logging.getLogger(__name__)

router = APIRouter(tags=["schematic"])


@router.get("/schematic/library")
async def library() -> dict[str, Any]:
    return schematic.library()


@router.get("/schematic/projects")
async def list_projects() -> dict[str, Any]:
    return {"items": schematic.list_projects()}


class ProjectCreate(BaseModel):
    name: str = "Neues Projekt"
    description: str = ""
    data: dict[str, Any] | None = None


@router.post("/schematic/projects")
async def create_project(payload: ProjectCreate) -> dict[str, Any]:
    return schematic.create_project(payload.name, payload.description, payload.data)


@router.get("/schematic/projects/{project_id}")
async def get_project(project_id: str) -> dict[str, Any]:
    project = schematic.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    return project


class ProjectSave(BaseModel):
    name: str | None = None
    description: str | None = None
    data: dict[str, Any] | None = None


@router.put("/schematic/projects/{project_id}")
async def save_project(project_id: str, payload: ProjectSave) -> dict[str, Any]:
    project = schematic.save_project(project_id, payload.name, payload.description, payload.data)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    return project


@router.delete("/schematic/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, Any]:
    if not schematic.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    return {"ok": True}


@router.post("/schematic/projects/{project_id}/duplicate")
async def duplicate_project(project_id: str) -> dict[str, Any]:
    project = schematic.duplicate_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    return project


class DesignData(BaseModel):
    components: list[dict[str, Any]] = Field(default_factory=list)
    wires: list[dict[str, Any]] = Field(default_factory=list)
    junctions: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/schematic/validate")
async def validate(data: DesignData) -> dict[str, Any]:
    return schematic.validate_design(data.model_dump())


@router.post("/schematic/analyze")
async def analyze(data: DesignData) -> dict[str, Any]:
    payload = data.model_dump()
    return {
        "validation": schematic.validate_design(payload),
        "stats": schematic.design_stats(payload),
        "networks": schematic.connected_groups(payload),
    }


@router.get("/schematic/projects/{project_id}/export.svg")
async def export_svg(project_id: str) -> Any:
    svg = schematic.project_svg(project_id)
    if not svg:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/schematic/projects/{project_id}/export.json")
async def export_json(project_id: str) -> Any:
    project = schematic.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Projekt nicht gefunden")
    import json

    payload = json.dumps(project, ensure_ascii=False, indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{project["name"]}.json"'},
    )
