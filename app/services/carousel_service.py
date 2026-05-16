from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.domain import CarouselPlan, TemplatePackage, utc_now
from app.repositories import CarouselRepository, TemplateRepository
from app.services.agent_events import get_bus, new_session, unregister_bus
from app.services.image_generation import ImageGenerationService
from app.services.linkedin_auth import LinkedInAuthService
from app.services.linkedin_publishing import LinkedInPublishingService
from app.services.orchestrator import CarouselOrchestrator
from app.services.renderer import RenderService
from app.services.user_profile import UserProfile, UserProfileRepository


@dataclass
class GenerateCarouselSpec:
    template_id: str
    topic: str
    brief: str
    audience: str
    tone: str
    cta: str
    slide_count: int = 6
    generation_mode: str = "slot_fill"
    image_backend: str = "gemini"
    evaluation_modes: list[str] = field(default_factory=list)
    session_id: str | None = None  # for live agent flowchart events


@dataclass
class RegenerateSlideSpec:
    slide_index: int
    directive: str = ""


@dataclass
class PublishCarouselSpec:
    commentary: str = ""


class CarouselService:
    def __init__(
        self,
        template_repository: TemplateRepository,
        carousel_repository: CarouselRepository,
        orchestrator: CarouselOrchestrator,
        image_generation_service: ImageGenerationService,
        render_service: RenderService,
        linkedin_publishing_service: LinkedInPublishingService | None = None,
        linkedin_auth_service: LinkedInAuthService | None = None,
        user_profile_repository: UserProfileRepository | None = None,
    ) -> None:
        self.template_repository = template_repository
        self.carousel_repository = carousel_repository
        self.orchestrator = orchestrator
        self.image_generation_service = image_generation_service
        self.render_service = render_service
        self.linkedin_publishing_service = linkedin_publishing_service
        self.linkedin_auth_service = linkedin_auth_service
        self.user_profile_repository = user_profile_repository

    def _resolve_user_profile(self) -> UserProfile | None:
        """Return the merged UserProfile (LinkedIn OIDC + form-stored fields).
        Returns None if no profile system is wired (older callers/tests)."""
        if not self.user_profile_repository:
            return None
        sub = "_local"
        oidc: dict | None = None
        if self.linkedin_auth_service:
            try:
                status = self.linkedin_auth_service.get_status() or {}
                if status.get("connected"):
                    profile_oidc = status.get("profile") or {}
                    if profile_oidc.get("sub"):
                        sub = str(profile_oidc["sub"])
                    oidc = profile_oidc
            except Exception:
                pass
        profile = self.user_profile_repository.get(sub)
        profile.merge_linkedin_oidc(oidc)
        return profile

    def _resolve_signed_in_author(self, audience: str) -> dict[str, str]:
        """Pull the signed-in LinkedIn user's name/handle/picture for use as
        the carousel author. Falls back to audience-derived identity (with
        no picture) if no LinkedIn account is connected.

        Returns: {author_name, author_handle, author_initial, author_picture}
        """
        # Audience-derived defaults (always safe — no picture available)
        a = (audience or "").strip() or "Author"
        author = {
            "author_name":    a,
            "author_handle":  f"@{a.lower().replace(' ', '').replace('&','and')}",
            "author_initial": (a[:1] or "N").upper(),
            "author_picture": "",
        }
        if not self.linkedin_auth_service:
            return author
        try:
            status = self.linkedin_auth_service.get_status() or {}
        except Exception:
            return author
        if not status.get("connected"):
            return author
        profile = status.get("profile") or {}
        # OIDC fields from /v2/userinfo
        name = (profile.get("name") or "").strip()
        if not name:
            given = (profile.get("given_name") or "").strip()
            family = (profile.get("family_name") or "").strip()
            name = (given + " " + family).strip()
        if not name:
            return author
        handle_base = ""
        email = (profile.get("email") or "").strip()
        if email and "@" in email:
            handle_base = email.split("@", 1)[0]
        if not handle_base:
            handle_base = name.lower().replace(" ", "")
        # LinkedIn OIDC returns profile photo URL in the `picture` field
        picture_url = (profile.get("picture") or "").strip()
        return {
            "author_name":    name,
            "author_handle":  f"@{handle_base}",
            "author_initial": (name.split()[0][:1] + (name.split()[-1][:1] if len(name.split()) > 1 else "")).upper(),
            "author_picture": picture_url,
        }

    def generate(self, spec: GenerateCarouselSpec) -> CarouselPlan:
        bus = get_bus(spec.session_id) if spec.session_id else None
        try:
            plan = self._generate_inner(spec, bus)
        except Exception as exc:  # noqa: BLE001
            # Surface the failure to the dashboard so the flowchart can show
            # the real reason instead of hanging on the last "running" stage.
            if bus:
                bus.publish(
                    "pipeline_failed",
                    agent="Pipeline",
                    error=str(exc)[:240],
                    error_type=type(exc).__name__,
                )
                bus.publish("pipeline_finalised", agent="Pipeline")
            raise
        else:
            if bus:
                bus.publish("pipeline_finalised", agent="Pipeline")
            return plan

    def _generate_inner(self, spec: GenerateCarouselSpec, bus) -> CarouselPlan:  # noqa: PLR0912
        if bus:
            bus.publish("pipeline_started", agent="Pipeline",
                        topic=spec.topic, template_id=spec.template_id)
            bus.publish("stage_started", agent="Pipeline", stage="resolve_template")
        template = self.template_repository.get_template(spec.template_id)
        if bus:
            bus.publish("stage_completed", agent="Pipeline", stage="resolve_template",
                        template_name=template.manifest.name)
            bus.publish("stage_started", agent="Pipeline", stage="agents_planning")
        # Resolve author identity from the signed-in LinkedIn user (or fall back
        # to the audience field if no LinkedIn account is connected). Whichever
        # path wins, it is locked into IDENTITY_SLOTS so the AI can never overwrite it.
        author_override = self._resolve_signed_in_author(spec.audience)
        if bus:
            bus.publish("author_resolved", agent="Pipeline",
                        author_name=author_override.get("author_name"),
                        author_handle=author_override.get("author_handle"),
                        source="linkedin" if (self.linkedin_auth_service and
                                              (self.linkedin_auth_service.get_status() or {}).get("connected"))
                                else "audience_field")
        # Pull merged user profile (LinkedIn OIDC + settings form) for
        # injection into writer agent prompts as wiki-memory context.
        user_profile = self._resolve_user_profile()
        user_context = user_profile.to_writer_context() if user_profile else ""
        plan = self.orchestrator.build_plan(
            template,
            topic=spec.topic,
            brief=spec.brief,
            audience=spec.audience,
            tone=spec.tone,
            cta=spec.cta,
            slide_count=spec.slide_count,
            generation_mode=spec.generation_mode,
            image_backend=spec.image_backend,
            session_id=spec.session_id,
            author_override=author_override,
            user_context=user_context,
        )
        if bus:
            bus.publish("stage_completed", agent="Pipeline", stage="agents_planning",
                        slides=len(plan.slides))
            bus.publish("stage_started", agent="Pipeline", stage="image_generation")
        plan = self.image_generation_service.materialize(plan)
        if bus:
            bus.publish("stage_completed", agent="Pipeline", stage="image_generation")
            bus.publish("stage_started", agent="Pipeline", stage="html_rendering")
        plan = self.render_service.render(plan, template)
        if bus:
            bus.publish("stage_completed", agent="Pipeline", stage="html_rendering")
            bus.publish("stage_started", agent="Pipeline", stage="pdf_export_via_chromium")
        plan = self.render_service.export_pdf(plan)
        if bus:
            bus.publish("stage_completed", agent="Pipeline", stage="pdf_export_via_chromium",
                        pdf_path=plan.artifacts.get("pdf"))
        if spec.evaluation_modes:
            for mode in spec.evaluation_modes:
                comparison_plan = self.orchestrator.build_plan(
                    template,
                    topic=spec.topic,
                    brief=spec.brief,
                    audience=spec.audience,
                    tone=spec.tone,
                    cta=spec.cta,
                    slide_count=spec.slide_count,
                    generation_mode=mode,
                    image_backend=spec.image_backend,
                    carousel_id=plan.id,
                )
                comparison_plan = self.image_generation_service.materialize(comparison_plan)
                preview = ""
                if comparison_plan.generation_mode == "slot_fill":
                    preview = comparison_plan.slides[0].slot_values.get("image_primary", "")
                else:
                    preview = comparison_plan.slides[0].slot_values.get("generated_full_slide", "")
                plan = self.orchestrator.attach_evaluation_run(
                    plan,
                    mode=mode,
                    image_backend=spec.image_backend,
                    prompt_count=sum(len(slide.prompt_payloads) for slide in comparison_plan.slides),
                    artifact_preview=preview or None,
                )
        self.carousel_repository.save(plan)
        if bus:
            bus.publish("pipeline_completed", agent="Pipeline",
                        carousel_id=plan.id, status=plan.status)
        return plan

    def get(self, carousel_id: str) -> CarouselPlan:
        return self.carousel_repository.get(carousel_id)

    def regenerate_slide(self, carousel_id: str, spec: RegenerateSlideSpec) -> CarouselPlan:
        plan = self.carousel_repository.get(carousel_id)
        if spec.slide_index < 1 or spec.slide_index > len(plan.slides):
            raise ValueError("slide_index is out of range")
        template = self.template_repository.get_template(plan.template_id)
        plan = self.orchestrator.regenerate_slide(
            plan,
            template,
            slide_index=spec.slide_index,
            directive=spec.directive,
        )
        plan = self.image_generation_service.materialize(plan)
        plan = self.render_service.render(plan, template)
        plan = self.render_service.export_pdf(plan)
        self.carousel_repository.save(plan)
        return plan

    def export(self, carousel_id: str) -> CarouselPlan:
        plan = self.carousel_repository.get(carousel_id)
        template = self.template_repository.get_template(plan.template_id)
        plan = self.render_service.render(plan, template)
        plan = self.render_service.export_pdf(plan)
        plan.updated_at = utc_now()
        self.carousel_repository.save(plan)
        return plan

    def publish_to_linkedin(
        self,
        carousel_id: str,
        spec: PublishCarouselSpec | None = None,
    ) -> tuple[CarouselPlan, dict[str, object]]:
        if not self.linkedin_publishing_service:
            raise RuntimeError("LinkedIn publishing is not configured.")
        plan = self.carousel_repository.get(carousel_id)
        pdf_path = plan.artifacts.get("pdf")
        if not pdf_path:
            plan = self.export(carousel_id)
            pdf_path = plan.artifacts.get("pdf")
        commentary = (spec.commentary if spec else "").strip() or self._default_commentary(plan)
        # Build a topic-+-audience aware document title rather than just a filename.
        # LinkedIn shows this as the carousel's caption-bar title.
        topic = (plan.topic or "Carousel").strip()
        audience = (plan.audience or "").strip()
        if audience:
            doc_title = f"{topic} — for {audience}"
        else:
            doc_title = topic
        # Cap to LinkedIn's recommended ~100 chars
        if len(doc_title) > 100:
            doc_title = doc_title[:97].rstrip() + "…"
        result = self.linkedin_publishing_service.publish_carousel_pdf(
            pdf_path=self._path(pdf_path),
            title=doc_title,
            commentary=commentary,
        )
        plan.artifacts["linkedin_post_id"] = str(result.get("post_id") or "")
        plan.artifacts["linkedin_document_urn"] = str(result.get("document_urn") or "")
        plan.status = "published"
        plan.updated_at = utc_now()
        self.carousel_repository.save(plan)
        return plan, result

    def _default_commentary(self, plan: CarouselPlan) -> str:
        """Build a LinkedIn caption that respects the user-chosen tone.

        Pulls the strongest line from each of the first 3 slides (hero or head
        or quote, falling back to support/body), strips HTML, and assembles
        a tone-flavoured intro + bullet list + CTA.
        """
        # Pull the strongest hook line from each of the first 3 slides
        bullets: list[str] = []
        slot_priority = (
            "hero", "head", "quote", "headline",
            "support", "sub", "body_html", "lead_text", "body",
        )
        for slide in plan.slides[:3]:
            for key in slot_priority:
                value = slide.slot_values.get(key, "").strip()
                if value:
                    cleaned = re.sub(r"<[^>]+>", " ", value.replace("<br>", " "))
                    cleaned = " ".join(cleaned.split())
                    if cleaned:
                        bullets.append(cleaned[:140])
                        break

        tone = (plan.tone or "Direct").strip().lower()
        topic = plan.topic.strip() or "this carousel"

        # Tone-aware opening hook
        opening_by_tone = {
            "direct":      f"The truth about {topic.lower()} most {plan.audience.lower()} miss:",
            "premium":     f"A considered take on {topic.lower()}.",
            "clear":       f"Here's what works for {topic.lower()}, simplified.",
            "playful":     f"Let's talk {topic.lower()}. Buckle up.",
            "bold":        f"Most advice about {topic.lower()} is wrong. Here's why:",
            "professional":f"Insights on {topic.lower()} for {plan.audience.lower()}.",
            "warm":        f"A few honest thoughts on {topic.lower()}.",
        }
        opening = opening_by_tone.get(tone, f"On {topic.lower()}:")

        # Tone-aware closer
        closer_by_tone = {
            "direct":      "Save this if it lands.",
            "premium":     "Worth a read.",
            "clear":       "Hope this helps.",
            "playful":     "Thoughts? Drop them below 👇",
            "bold":        "Disagree? Tell me why.",
            "professional":"Open to perspectives.",
            "warm":        "Would love to hear how this lands for you.",
        }
        closer = closer_by_tone.get(tone, "")

        parts: list[str] = [opening, ""]
        for b in bullets[:3]:
            parts.append(f"→ {b}")
        if plan.cta:
            parts.extend(["", plan.cta])
        if closer and (plan.cta or bullets):
            parts.extend(["", closer])
        return "\n".join(parts).strip()

    def _path(self, value: str | None) -> Path:
        if not value:
            raise RuntimeError("Carousel PDF artifact is missing.")
        return Path(value)
