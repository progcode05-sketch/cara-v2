from __future__ import annotations

import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.bootstrap import ServiceContainer
from app.dependencies import get_container
from app.services.linkedin_auth import PUBLISH_SCOPE, SIGNIN_SCOPE

router = APIRouter(prefix="/auth/linkedin", tags=["linkedin-auth"])


@router.get("/status")
def linkedin_status(
    container: ServiceContainer = Depends(get_container),
) -> dict[str, object]:
    return container.linkedin_auth_service.get_status()


@router.get("/url")
def linkedin_url(
    mode: str = Query(default="signin"),
    container: ServiceContainer = Depends(get_container),
) -> dict[str, str]:
    scope = PUBLISH_SCOPE if mode == "publish" else SIGNIN_SCOPE
    return {
        "auth_url": container.linkedin_auth_service.build_authorization_url(
            container.settings.linkedin_redirect_uri,
            scope=scope,
        )
    }


@router.get("/start")
def linkedin_start(
    mode: str = Query(default="signin"),
    container: ServiceContainer = Depends(get_container),
) -> RedirectResponse:
    scope = PUBLISH_SCOPE if mode == "publish" else SIGNIN_SCOPE
    return RedirectResponse(
        container.linkedin_auth_service.build_authorization_url(
            container.settings.linkedin_redirect_uri,
            scope=scope,
        )
    )


@router.get("/callback", name="linkedin_callback")
def linkedin_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    container: ServiceContainer = Depends(get_container),
) -> RedirectResponse:
    if error:
        message = error_description or error
        return RedirectResponse(
            f"/dashboard?linkedin=error&message={urllib.parse.quote(message)}"
        )
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state in LinkedIn callback.")
    try:
        container.linkedin_auth_service.handle_callback(
            code,
            state,
            container.settings.linkedin_redirect_uri,
        )
    except ValueError as exc:
        return RedirectResponse(
            f"/dashboard?linkedin=error&message={urllib.parse.quote(str(exc))}"
        )
    return RedirectResponse("/dashboard?linkedin=connected")


@router.post("/disconnect")
def linkedin_disconnect(
    container: ServiceContainer = Depends(get_container),
) -> dict[str, bool]:
    container.linkedin_auth_service.disconnect()
    return {"ok": True}
