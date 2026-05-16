from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class SlotDefinition:
    name: str
    slot_type: str
    required: bool = False
    max_chars: int | None = None
    mode: str = "slot_fill"
    prompt_role: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SlotDefinition":
        return cls(**payload)


@dataclass
class SlideRoleSchema:
    role: str
    description: str
    slots: list[str]
    render_variant: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SlideRoleSchema":
        return cls(**payload)


@dataclass
class RenderConfig:
    width: int = 1080
    height: int = 1350
    export_format: str = "pdf"
    preview_format: str = "svg"
    background_color: str = "#FFFFFF"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RenderConfig":
        return cls(**payload)


@dataclass
class TemplateManifest:
    id: str
    name: str
    description: str
    source_type: str
    exact_source: bool
    allowed_slide_counts: list[int]
    default_slide_roles: list[str]
    slots: dict[str, SlotDefinition]
    slide_roles: dict[str, SlideRoleSchema]
    overflow_rules: dict[str, str]
    prompt_hints: dict[str, Any]
    render_config: RenderConfig
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["slots"] = {name: asdict(slot) for name, slot in self.slots.items()}
        payload["slide_roles"] = {
            name: asdict(schema) for name, schema in self.slide_roles.items()
        }
        payload["render_config"] = asdict(self.render_config)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TemplateManifest":
        return cls(
            id=payload["id"],
            name=payload["name"],
            description=payload["description"],
            source_type=payload["source_type"],
            exact_source=payload["exact_source"],
            allowed_slide_counts=list(payload["allowed_slide_counts"]),
            default_slide_roles=list(payload["default_slide_roles"]),
            slots={
                name: SlotDefinition.from_dict(slot)
                for name, slot in payload["slots"].items()
            },
            slide_roles={
                name: SlideRoleSchema.from_dict(schema)
                for name, schema in payload["slide_roles"].items()
            },
            overflow_rules=dict(payload.get("overflow_rules", {})),
            prompt_hints=dict(payload.get("prompt_hints", {})),
            render_config=RenderConfig.from_dict(payload["render_config"]),
            created_at=payload.get("created_at", utc_now()),
        )


@dataclass
class TemplatePackage:
    manifest: TemplateManifest
    render_html: str
    styles_css: str = ""
    head_html: str = ""
    render_variants: dict[str, str] = field(default_factory=dict)
    assets: list[str] = field(default_factory=list)
    storage_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest": self.manifest.to_dict(),
            "render_html": self.render_html,
            "styles_css": self.styles_css,
            "head_html": self.head_html,
            "render_variants": dict(self.render_variants),
            "assets": list(self.assets),
            "storage_path": self.storage_path,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TemplatePackage":
        return cls(
            manifest=TemplateManifest.from_dict(payload["manifest"]),
            render_html=payload["render_html"],
            styles_css=payload.get("styles_css", ""),
            head_html=payload.get("head_html", ""),
            render_variants=dict(payload.get("render_variants", {})),
            assets=list(payload.get("assets", [])),
            storage_path=payload.get("storage_path"),
        )


@dataclass
class SlidePromptPayload:
    slot_name: str
    prompt: str
    negative_prompt: str
    consistency_anchor: str
    style_reference: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SlidePromptPayload":
        return cls(**payload)


@dataclass
class SlideContent:
    index: int
    role: str
    title: str
    slot_values: dict[str, str]
    prompt_payloads: list[SlidePromptPayload]
    slide_purpose: str
    image_backend: str
    generation_mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "role": self.role,
            "title": self.title,
            "slot_values": dict(self.slot_values),
            "prompt_payloads": [asdict(item) for item in self.prompt_payloads],
            "slide_purpose": self.slide_purpose,
            "image_backend": self.image_backend,
            "generation_mode": self.generation_mode,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SlideContent":
        return cls(
            index=payload["index"],
            role=payload["role"],
            title=payload["title"],
            slot_values=dict(payload["slot_values"]),
            prompt_payloads=[
                SlidePromptPayload.from_dict(item)
                for item in payload.get("prompt_payloads", [])
            ],
            slide_purpose=payload["slide_purpose"],
            image_backend=payload["image_backend"],
            generation_mode=payload["generation_mode"],
        )


@dataclass
class EvaluationRun:
    mode: str
    image_backend: str
    prompt_count: int
    artifact_preview: str | None
    notes: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvaluationRun":
        return cls(**payload)


@dataclass
class CarouselPlan:
    id: str
    template_id: str
    topic: str
    brief: str
    audience: str
    tone: str
    cta: str
    slide_count: int
    generation_mode: str
    image_backend: str
    status: str
    slides: list[SlideContent]
    artifacts: dict[str, str]
    evaluation_runs: list[EvaluationRun]
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "template_id": self.template_id,
            "topic": self.topic,
            "brief": self.brief,
            "audience": self.audience,
            "tone": self.tone,
            "cta": self.cta,
            "slide_count": self.slide_count,
            "generation_mode": self.generation_mode,
            "image_backend": self.image_backend,
            "status": self.status,
            "slides": [slide.to_dict() for slide in self.slides],
            "artifacts": dict(self.artifacts),
            "evaluation_runs": [asdict(run) for run in self.evaluation_runs],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CarouselPlan":
        return cls(
            id=payload["id"],
            template_id=payload["template_id"],
            topic=payload["topic"],
            brief=payload["brief"],
            audience=payload["audience"],
            tone=payload["tone"],
            cta=payload["cta"],
            slide_count=payload["slide_count"],
            generation_mode=payload["generation_mode"],
            image_backend=payload["image_backend"],
            status=payload["status"],
            slides=[SlideContent.from_dict(item) for item in payload["slides"]],
            artifacts=dict(payload.get("artifacts", {})),
            evaluation_runs=[
                EvaluationRun.from_dict(item)
                for item in payload.get("evaluation_runs", [])
            ],
            created_at=payload.get("created_at", utc_now()),
            updated_at=payload.get("updated_at", utc_now()),
        )


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
