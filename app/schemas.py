from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TemplateImportRequest(BaseModel):
    name: str
    source_type: str = Field(pattern="^(html|pdf)$")
    source_name: str
    template_id: str | None = None
    description: str = ""
    html_content: str | None = None
    css_content: str = ""
    extracted_text: str = ""
    exact_html: bool = False
    prompt_style_hints: dict[str, str] = Field(default_factory=dict)
    allowed_slide_counts: list[int] = Field(default_factory=lambda: [5, 6, 7, 8, 9, 10])


class GenerateCarouselRequest(BaseModel):
    template_id: str
    topic: str
    brief: str
    audience: str
    tone: str
    cta: str
    slide_count: int = Field(default=6, ge=5, le=10)
    generation_mode: str = Field(default="slot_fill", pattern="^(slot_fill|full_slide)$")
    image_backend: str = "gemini"
    evaluation_modes: list[str] = Field(default_factory=list)
    session_id: str | None = None  # for live agent flowchart streaming


class RegenerateSlideRequest(BaseModel):
    slide_index: int
    directive: str = ""


class PublishCarouselRequest(BaseModel):
    commentary: str = ""


class CarouselResponse(BaseModel):
    payload: dict[str, Any]
