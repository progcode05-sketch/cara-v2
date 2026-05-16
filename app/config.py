from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    data_dir: Path
    templates_dir: Path
    carousels_dir: Path
    artifacts_dir: Path
    oauth_dir: Path
    builtin_templates_dir: Path
    app_base_url: str
    linkedin_client_id: str
    linkedin_client_secret: str
    linkedin_redirect_uri: str
    gemini_api_key: str
    gemini_image_model: str
    claude_api_key: str
    claude_model: str
    linkedin_api_version: str

    @classmethod
    def load(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parent.parent
        data_dir = Path(os.environ["DATA_DIR"]) if "DATA_DIR" in os.environ else base_dir / "data"
        app_base_url = os.environ.get("NOXLIN_APP_BASE_URL", "http://localhost:3002").rstrip("/")
        return cls(
            base_dir=base_dir,
            data_dir=data_dir,
            templates_dir=data_dir / "templates",
            carousels_dir=data_dir / "carousels",
            artifacts_dir=data_dir / "artifacts",
            oauth_dir=data_dir / "oauth",
            builtin_templates_dir=base_dir / "app" / "builtin_templates",
            app_base_url=app_base_url,
            linkedin_client_id=os.environ.get("LINKEDIN_CLIENT_ID", ""),
            linkedin_client_secret=os.environ.get("LINKEDIN_CLIENT_SECRET", ""),
            linkedin_redirect_uri=os.environ.get(
                "LINKEDIN_REDIRECT_URI",
                "http://localhost:3002/auth/linkedin/callback",
            ),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            gemini_image_model=os.environ.get(
                "GEMINI_IMAGE_MODEL",
                "gemini-2.5-flash-preview-image-generation",
            ),
            claude_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            claude_model=os.environ.get(
                "ANTHROPIC_MODEL",
                "claude-sonnet-4-5",
            ),
            linkedin_api_version=os.environ.get(
                "LINKEDIN_API_VERSION",
                "202604",
            ),
        )
