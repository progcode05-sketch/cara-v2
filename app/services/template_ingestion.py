from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.domain import RenderConfig, SlideRoleSchema, SlotDefinition, TemplateManifest, TemplatePackage
from app.repositories import TemplateRepository


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


@dataclass
class TemplateImportSpec:
    name: str
    source_type: str
    source_name: str
    template_id: str | None = None
    description: str = ""
    html_content: str | None = None
    css_content: str = ""
    extracted_text: str = ""
    exact_html: bool = False
    prompt_style_hints: dict[str, str] = field(default_factory=dict)
    allowed_slide_counts: list[int] = field(default_factory=lambda: [5, 6, 7, 8])


class TemplateIngestionService:
    def __init__(self, template_repository: TemplateRepository) -> None:
        self.template_repository = template_repository

    def import_template(self, spec: TemplateImportSpec) -> TemplatePackage:
        template_id = spec.template_id or self._slugify(spec.name)
        if spec.source_type == "html":
            package = self._from_html(template_id, spec)
        elif spec.source_type == "pdf":
            package = self._from_pdf(template_id, spec)
        else:
            raise ValueError(f"Unsupported source_type: {spec.source_type}")
        return self.template_repository.save_template(package)

    def _from_html(self, template_id: str, spec: TemplateImportSpec) -> TemplatePackage:
        html = spec.html_content or self._default_html_template(spec.name)
        slots = self._derive_slots(html)
        slide_roles = self._build_slide_roles(slots)
        manifest = TemplateManifest(
            id=template_id,
            name=spec.name,
            description=spec.description or f"Exact HTML template imported from {spec.source_name}",
            source_type="html",
            exact_source=True if spec.exact_html else False,
            allowed_slide_counts=spec.allowed_slide_counts,
            default_slide_roles=["cover", "problem", "insight", "framework", "proof", "cta"],
            slots=slots,
            slide_roles=slide_roles,
            overflow_rules={
                "title": "shrink_then_truncate",
                "body": "truncate",
                "cta": "truncate",
            },
            prompt_hints={
                "style": spec.prompt_style_hints.get(
                    "style",
                    "Use the imported HTML template as the source of truth for composition and visual tone.",
                ),
                "source_name": spec.source_name,
            },
            render_config=RenderConfig(),
        )
        return TemplatePackage(
            manifest=manifest,
            render_html=html,
            styles_css=spec.css_content,
        )

    def _from_pdf(self, template_id: str, spec: TemplateImportSpec) -> TemplatePackage:
        html = self._default_html_template(spec.name, pdf_mode=True)
        slots = self._derive_slots(html)
        slide_roles = self._build_slide_roles(slots)
        manifest = TemplateManifest(
            id=template_id,
            name=spec.name,
            description=spec.description or f"Editable variant derived from PDF reference {spec.source_name}",
            source_type="pdf",
            exact_source=False,
            allowed_slide_counts=spec.allowed_slide_counts,
            default_slide_roles=["cover", "problem", "insight", "proof", "cta"],
            slots=slots,
            slide_roles=slide_roles,
            overflow_rules={
                "title": "shrink_then_truncate",
                "body": "summarize_then_truncate",
                "cta": "truncate",
            },
            prompt_hints={
                "style": spec.prompt_style_hints.get(
                    "style",
                    "Rebuild the PDF inspiration into an editable business carousel with consistent spacing.",
                ),
                "reference_excerpt": spec.extracted_text[:400],
                "source_name": spec.source_name,
            },
            render_config=RenderConfig(),
        )
        return TemplatePackage(
            manifest=manifest,
            render_html=html,
            styles_css=spec.css_content,
        )

    def _derive_slots(self, html: str) -> dict[str, SlotDefinition]:
        discovered = list(dict.fromkeys(PLACEHOLDER_PATTERN.findall(html)))
        if not discovered:
            discovered = ["eyebrow", "title", "body", "image_primary", "cta", "page_number"]
        slots: dict[str, SlotDefinition] = {}
        for name in discovered:
            slot_type = "image" if "image" in name or "visual" in name else "text"
            max_chars = None
            if slot_type == "text":
                if "title" in name:
                    max_chars = 80
                elif "body" in name:
                    max_chars = 240
                elif "cta" in name:
                    max_chars = 60
                else:
                    max_chars = 40
            slots[name] = SlotDefinition(
                name=name,
                slot_type=slot_type,
                required=name in {"title", "page_number"},
                max_chars=max_chars,
                mode="slot_fill" if slot_type == "image" else "deterministic",
                prompt_role="hero_visual" if name == "image_primary" else None,
            )
        return slots

    def _build_slide_roles(
        self, slots: dict[str, SlotDefinition]
    ) -> dict[str, SlideRoleSchema]:
        available = list(slots.keys())
        base_text = [name for name in available if slots[name].slot_type == "text"]
        has_image = any(slot.slot_type == "image" for slot in slots.values())
        common_slots = [slot for slot in ("eyebrow", "title", "body", "cta", "page_number") if slot in slots]
        if not common_slots:
            common_slots = base_text[:3]
        roles = {
            "cover": SlideRoleSchema(
                role="cover",
                description="Introduce the core hook and visual theme.",
                slots=[slot for slot in ("eyebrow", "title", "body", "image_primary", "page_number") if slot in slots],
            ),
            "problem": SlideRoleSchema(
                role="problem",
                description="Frame the pain point or friction.",
                slots=[slot for slot in ("title", "body", "image_primary", "page_number") if slot in slots],
            ),
            "insight": SlideRoleSchema(
                role="insight",
                description="Teach a key insight or perspective shift.",
                slots=[slot for slot in ("eyebrow", "title", "body", "page_number") if slot in slots],
            ),
            "framework": SlideRoleSchema(
                role="framework",
                description="Show a process, framework, or sequence.",
                slots=[slot for slot in ("title", "body", "image_primary", "page_number") if slot in slots],
            ),
            "proof": SlideRoleSchema(
                role="proof",
                description="Add credibility, data, or a case study note.",
                slots=[slot for slot in ("eyebrow", "title", "body", "page_number") if slot in slots],
            ),
            "cta": SlideRoleSchema(
                role="cta",
                description="Close with a strong action or takeaway.",
                slots=[slot for slot in ("title", "body", "cta", "page_number") if slot in slots],
            ),
        }
        if not has_image:
            for schema in roles.values():
                schema.slots = [slot for slot in schema.slots if slot != "image_primary"]
        if not common_slots:
            for schema in roles.values():
                schema.slots = available
        return roles

    def _default_html_template(self, name: str, pdf_mode: bool = False) -> str:
        accent = "#111827" if pdf_mode else "#0A66C2"
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{name}</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #F3F6F8;
    }}
    .slide {{
      width: 1080px;
      height: 1350px;
      background: #FFFFFF;
      color: #0A0A0A;
      padding: 96px;
      box-sizing: border-box;
      position: relative;
      display: grid;
      grid-template-columns: 1.2fr 0.8fr;
      gap: 48px;
    }}
    .eyebrow {{
      font-size: 24px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: {accent};
      margin-bottom: 24px;
    }}
    .title {{
      font-size: 78px;
      line-height: 1.05;
      margin: 0 0 24px 0;
    }}
    .body {{
      font-size: 34px;
      line-height: 1.4;
      color: #434649;
      margin: 0;
      white-space: pre-wrap;
    }}
    .visual {{
      border: 2px dashed #DDE1E6;
      border-radius: 24px;
      background: #EEF5FF;
      display: flex;
      align-items: center;
      justify-content: center;
      color: {accent};
      font-size: 28px;
      text-align: center;
      padding: 32px;
      min-height: 720px;
    }}
    .footer {{
      position: absolute;
      left: 96px;
      right: 96px;
      bottom: 72px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: #86888A;
      font-size: 24px;
    }}
    .cta {{
      color: {accent};
      font-weight: 700;
    }}
  </style>
</head>
<body>
  <article class="slide">
    <section>
      <div class="eyebrow">{{{{eyebrow}}}}</div>
      <h1 class="title">{{{{title}}}}</h1>
      <p class="body">{{{{body}}}}</p>
    </section>
    <aside class="visual">{{{{image_primary}}}}</aside>
    <footer class="footer">
      <span class="cta">{{{{cta}}}}</span>
      <span>{{{{page_number}}}}</span>
    </footer>
  </article>
</body>
</html>
"""

    def _slugify(self, value: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.lower()).strip("-")
        return normalized or "template"
