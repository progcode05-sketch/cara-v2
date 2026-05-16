from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.bootstrap import ServiceContainer
from app.dependencies import get_container
from app.schemas import TemplateImportRequest
from app.services.template_ingestion import TemplateImportSpec

router = APIRouter(prefix="/templates", tags=["templates"])


@router.get("/catalog")
def list_template_catalog(
    container: ServiceContainer = Depends(get_container),
) -> dict[str, object]:
    templates = [
        {
            "id": package.manifest.id,
            "name": package.manifest.name,
            "description": package.manifest.description,
            "allowed_slide_counts": package.manifest.allowed_slide_counts,
        }
        for package in container.template_repository.list_templates()
    ]
    return {"templates": templates}


@router.get("")
def list_templates(container: ServiceContainer = Depends(get_container)) -> dict[str, object]:
    templates = [package.to_dict() for package in container.template_repository.list_templates()]
    return {"templates": templates}


@router.get("/{template_id}")
def get_template(
    template_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, object]:
    try:
        package = container.template_repository.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return package.to_dict()


@router.post("/import")
def import_template(
    request: TemplateImportRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict[str, object]:
    spec = TemplateImportSpec(**request.model_dump())
    package = container.template_ingestion_service.import_template(spec)
    return package.to_dict()
