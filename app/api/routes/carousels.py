from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.bootstrap import ServiceContainer
from app.dependencies import get_container
from app.schemas import GenerateCarouselRequest, PublishCarouselRequest, RegenerateSlideRequest
from app.services.carousel_service import GenerateCarouselSpec, PublishCarouselSpec, RegenerateSlideSpec
from app.services.linkedin_publishing import LinkedInPublishError

router = APIRouter(prefix="/carousels", tags=["carousels"])


@router.post("/generate")
def generate_carousel(
    request: GenerateCarouselRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict[str, object]:
    try:
        plan = container.carousel_service.generate(GenerateCarouselSpec(**request.model_dump()))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return plan.to_dict()


@router.get("/{carousel_id}")
def get_carousel(
    carousel_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, object]:
    try:
        plan = container.carousel_service.get(carousel_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return plan.to_dict()


@router.post("/{carousel_id}/regenerate-slide")
def regenerate_slide(
    carousel_id: str,
    request: RegenerateSlideRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict[str, object]:
    try:
        plan = container.carousel_service.regenerate_slide(
            carousel_id, RegenerateSlideSpec(**request.model_dump())
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return plan.to_dict()


@router.post("/{carousel_id}/export")
def export_carousel(
    carousel_id: str, container: ServiceContainer = Depends(get_container)
) -> dict[str, object]:
    try:
        plan = container.carousel_service.export(carousel_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return plan.to_dict()


@router.post("/{carousel_id}/publish-linkedin")
def publish_carousel_to_linkedin(
    carousel_id: str,
    request: PublishCarouselRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict[str, object]:
    try:
        plan, result = container.carousel_service.publish_to_linkedin(
            carousel_id,
            PublishCarouselSpec(**request.model_dump()),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LinkedInPublishError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"carousel": plan.to_dict(), "publish_result": result}
