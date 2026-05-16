from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.agent_stream import router as agent_stream_router
from app.api.routes.auth import router as auth_router
from app.api.routes.carousels import router as carousels_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.profile import router as profile_router
from app.api.routes.templates import router as templates_router
from app.config import Settings

settings = Settings.load()

# Ensure all data subdirectories exist (important on first boot with empty persistent disk)
for _subdir in ["carousels", "templates", "artifacts", "profiles", "oauth"]:
    (settings.data_dir / _subdir).mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Carousel Backend", version="0.1.0")
app.include_router(auth_router)
app.include_router(templates_router)
app.include_router(carousels_router)
app.include_router(dashboard_router)
app.include_router(agent_stream_router)
app.include_router(profile_router)

app.mount("/artifacts", StaticFiles(directory=str(settings.artifacts_dir)), name="artifacts")


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/dashboard")
