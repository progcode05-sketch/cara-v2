"""
User profile API + settings form.

GET  /profile          → returns merged LinkedIn-OIDC + form-stored profile
PUT  /profile          → updates the form fields (identity comes from LinkedIn)
GET  /settings         → serves the settings form HTML
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.bootstrap import ServiceContainer
from app.dependencies import get_container
from app.services.user_profile import UserProfile, VOICE_PRESETS


router = APIRouter(tags=["profile"])


class ProfileUpdateRequest(BaseModel):
    headline:     str = ""
    industry:     str = ""
    audience:     str = ""
    voice_preset: str = Field(default="Direct")
    topics:       list[str] = Field(default_factory=list)
    about_blurb:  str = ""
    sample_posts: list[str] = Field(default_factory=list)
    do_not_say:   list[str] = Field(default_factory=list)


def _resolve_sub(container: ServiceContainer) -> str:
    """LinkedIn `sub` if signed in, else _local."""
    try:
        status = container.linkedin_auth_service.get_status() or {}
        profile = status.get("profile") or {}
        sub = profile.get("sub")
        if sub:
            return str(sub)
    except Exception:
        pass
    return "_local"


def _load_merged(container: ServiceContainer) -> UserProfile:
    sub = _resolve_sub(container)
    profile = container.user_profile_repository.get(sub)
    # Always overlay LinkedIn OIDC on top so name/email/photo stay current
    try:
        status = container.linkedin_auth_service.get_status() or {}
        oidc = status.get("profile") if status.get("connected") else None
    except Exception:
        oidc = None
    profile.merge_linkedin_oidc(oidc)
    return profile


@router.get("/profile")
def get_profile(container: ServiceContainer = Depends(get_container)) -> dict[str, object]:
    profile = _load_merged(container)
    return {
        "profile": profile.to_dict(),
        "voice_presets": list(VOICE_PRESETS),
        "linkedin_connected": bool(profile.sub and profile.sub != "_local"),
    }


@router.put("/profile")
def update_profile(
    request: ProfileUpdateRequest,
    container: ServiceContainer = Depends(get_container),
) -> dict[str, object]:
    sub = _resolve_sub(container)
    profile = container.user_profile_repository.get(sub)
    # Update only the form fields — identity stays from LinkedIn
    data = request.model_dump()
    if data["voice_preset"] not in VOICE_PRESETS:
        data["voice_preset"] = "Direct"
    profile.headline     = data["headline"].strip()
    profile.industry     = data["industry"].strip()
    profile.audience     = data["audience"].strip()
    profile.voice_preset = data["voice_preset"]
    profile.topics       = [t.strip() for t in data["topics"] if t.strip()][:8]
    profile.about_blurb  = data["about_blurb"].strip()
    profile.sample_posts = [p.strip() for p in data["sample_posts"] if p.strip()][:3]
    profile.do_not_say   = [d.strip() for d in data["do_not_say"] if d.strip()][:10]
    profile.sub          = sub
    container.user_profile_repository.save(profile)
    # Return the merged view (with LinkedIn OIDC on top)
    return get_profile(container)


@router.get("/settings", response_class=HTMLResponse)
def settings_page() -> str:
    settings_html = (
        Path(__file__).resolve().parent.parent.parent / "ui" / "settings.html"
    )
    if not settings_html.exists():
        raise HTTPException(status_code=404, detail="settings.html not found")
    return settings_html.read_text(encoding="utf-8")
