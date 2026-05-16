from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse


router = APIRouter(tags=["dashboard"])


def _ui_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[2] / "ui" / filename


@router.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(_ui_path("dashboard.html"))


@router.get("/dashboard/linkedin-callback", include_in_schema=False)
def linkedin_callback() -> FileResponse:
    return FileResponse(_ui_path("linkedin_callback.html"))
