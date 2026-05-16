from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from uuid import uuid4

from app.domain import (
    CarouselPlan,
    EvaluationRun,
    SlideContent,
    SlidePromptPayload,
    TemplatePackage,
    utc_now,
)
from app.services.ai_clients import AnthropicClient, ProviderError
from app.services.agents import CaptainWritingAgent, InputAuthenticatorAgent
from app.services.agent_events import AgentEventBus, get_bus

log = logging.getLogger(__name__)


class CarouselOrchestrator:
    def __init__(self, claude_client: AnthropicClient | None = None) -> None:
        self.claude_client = claude_client

    def build_plan(
        self,
        template: TemplatePackage,
        *,
        topic: str,
        brief: str,
        audience: str,
        tone: str,
        cta: str,
        slide_count: int,
        generation_mode: str,
        image_backend: str,
        carousel_id: str | None = None,
        session_id: str | None = None,
        author_override: dict[str, str] | None = None,
        user_context: str = "",
    ) -> CarouselPlan:
        resolved_slide_count = self._resolve_slide_count(
            slide_count, template.manifest.allowed_slide_counts
        )
        roles = self._resolve_roles(template, resolved_slide_count)

        # ──────────────────────────────────────────────────────────────────
        # InputAuthenticator: clean typos in topic/brief/audience/tone/cta
        # BEFORE the Captain dispatches to the writers. Skipped silently if
        # Claude isn't configured. Always publishes events to the SSE bus.
        # ──────────────────────────────────────────────────────────────────
        if self.claude_client and self.claude_client.is_configured():
            event_bus: AgentEventBus | None = get_bus(session_id) if session_id else None
            input_auth = InputAuthenticatorAgent(
                client=self.claude_client, event_bus=event_bus,
            )
            cleaned = input_auth.review(
                topic=topic, brief=brief, audience=audience, tone=tone, cta=cta,
            )
            topic    = cleaned["topic"]
            brief    = cleaned["brief"]
            audience = cleaned["audience"]
            tone     = cleaned["tone"]
            cta      = cleaned["cta"]

        ai_slots = self._generate_ai_slot_values(
            template=template,
            topic=topic,
            brief=brief,
            audience=audience,
            tone=tone,
            cta=cta,
            slide_count=resolved_slide_count,
            roles=roles,
            session_id=session_id,
            user_context=user_context,
        )
        slides = [
            self._build_slide(
                template=template,
                index=index,
                role=role,
                topic=topic,
                brief=brief,
                audience=audience,
                tone=tone,
                cta=cta,
                slide_count=resolved_slide_count,
                generation_mode=generation_mode,
                image_backend=image_backend,
                ai_slot_values=ai_slots.get(index, {}),
                author_override=author_override,
            )
            for index, role in enumerate(roles, start=1)
        ]
        now = utc_now()
        return CarouselPlan(
            id=carousel_id or f"carousel-{uuid4().hex[:12]}",
            template_id=template.manifest.id,
            topic=topic,
            brief=brief,
            audience=audience,
            tone=tone,
            cta=cta,
            slide_count=resolved_slide_count,
            generation_mode=generation_mode,
            image_backend=image_backend,
            status="planning_complete",
            slides=slides,
            artifacts={},
            evaluation_runs=[],
            created_at=now,
            updated_at=now,
        )

    def regenerate_slide(
        self,
        plan: CarouselPlan,
        template: TemplatePackage,
        *,
        slide_index: int,
        directive: str = "",
    ) -> CarouselPlan:
        target = plan.slides[slide_index - 1]
        refreshed_slots = self._generate_ai_slot_values(
            template=template,
            topic=plan.topic,
            brief=f"{plan.brief} {directive}".strip(),
            audience=plan.audience,
            tone=plan.tone,
            cta=plan.cta,
            slide_count=1,
            roles=[target.role],
        )
        rebuilt = self._build_slide(
            template=template,
            index=slide_index,
            role=target.role,
            topic=plan.topic,
            brief=f"{plan.brief} {directive}".strip(),
            audience=plan.audience,
            tone=plan.tone,
            cta=plan.cta,
            slide_count=plan.slide_count,
            generation_mode=plan.generation_mode,
            image_backend=plan.image_backend,
            ai_slot_values=refreshed_slots.get(1, {}),
        )
        slides = list(plan.slides)
        slides[slide_index - 1] = rebuilt
        return replace(plan, slides=slides, updated_at=utc_now(), status="planning_complete")

    def attach_evaluation_run(
        self,
        plan: CarouselPlan,
        *,
        mode: str,
        image_backend: str,
        prompt_count: int,
        artifact_preview: str | None,
    ) -> CarouselPlan:
        runs = list(plan.evaluation_runs)
        runs.append(
            EvaluationRun(
                mode=mode,
                image_backend=image_backend,
                prompt_count=prompt_count,
                artifact_preview=artifact_preview,
                notes="Evaluation harness output for side-by-side generation mode comparison.",
            )
        )
        return replace(plan, evaluation_runs=runs, updated_at=utc_now())

    def _resolve_slide_count(self, requested: int, allowed: list[int]) -> int:
        if not allowed:
            return requested
        if requested in allowed:
            return requested
        return min(allowed, key=lambda item: abs(item - requested))

    def _resolve_roles(self, template: TemplatePackage, slide_count: int) -> list[str]:
        defaults = template.manifest.default_slide_roles
        if slide_count <= len(defaults):
            roles = defaults[:slide_count]
            if roles[-1] != "cta":
                roles[-1] = "cta"
            return roles
        # For slide_count > defaults: build cover + (slide_count-2) middles + final cta
        roles = list(defaults)
        # Strip trailing 'cta' so we can re-append exactly one at the end
        while roles and roles[-1] == "cta":
            roles.pop()
        # Pad with alternating insight/framework until we have slide_count-1 middles
        # (the last slot is reserved for the closing cta). We only use roles that
        # every template manifest declares — insight + framework are universal.
        declared = set(template.manifest.slide_roles.keys())
        rotation = [r for r in ("insight", "framework", "problem", "proof") if r in declared] or ["insight"]
        while len(roles) < slide_count - 1:
            roles.append(rotation[len(roles) % len(rotation)])
        roles = roles[: slide_count - 1] + ["cta"]
        return roles

    def _build_slide(
        self,
        *,
        template: TemplatePackage,
        index: int,
        role: str,
        topic: str,
        brief: str,
        audience: str,
        tone: str,
        cta: str,
        slide_count: int,
        generation_mode: str,
        image_backend: str,
        ai_slot_values: dict[str, str],
        author_override: dict[str, str] | None = None,
    ) -> SlideContent:
        slot_values = self._slot_values_for_role(
            template=template,
            role=role,
            topic=topic,
            brief=brief,
            audience=audience,
            tone=tone,
            cta=cta,
            index=index,
            slide_count=slide_count,
        )
        # If a signed-in author override was provided (e.g. from LinkedIn OIDC),
        # let it win over the audience-derived defaults BEFORE the merge so the
        # AI can still see fields it shouldn't fill, but the actual user info
        # appears on every slide.
        if author_override:
            for key in ("author_name", "author_handle", "author_initial", "author_picture"):
                if author_override.get(key) is not None:
                    slot_values[key] = author_override[key]
        # ──────────────────────────────────────────────────────────────────
        # Identity slots are USER input, not AI output. The writer agent
        # is creative with copy but must never invent author/handle/brand
        # values. Snapshot the deterministic identity slots BEFORE merge,
        # then force-restore them AFTER the AI merge so AI placeholders
        # (e.g. "Your Name", "@yourhandle") can never leak into output.
        # ──────────────────────────────────────────────────────────────────
        IDENTITY_SLOTS = (
            "author_name", "author_handle", "author_initial", "author_picture",
            "brand_name", "brand_site", "brand_handle",
            "page_number", "page_label",
            "swipe_label", "footer_label",
            "stamp_brand", "stamp_site",
        )
        identity_snapshot = {
            slot: slot_values.get(slot, "")
            for slot in IDENTITY_SLOTS
            if slot in slot_values
        }
        slot_values.update({key: value for key, value in ai_slot_values.items() if value})
        # Hard-restore identity slots — AI never wins on these
        for slot, value in identity_snapshot.items():
            if value:
                slot_values[slot] = value
        role_schema = template.manifest.slide_roles[role]
        filtered_slot_values = {
            slot: self._enforce_length(template, slot, slot_values.get(slot, ""))
            for slot in role_schema.slots
        }
        prompt_payloads = self._build_prompt_payloads(
            template=template,
            role=role,
            topic=topic,
            audience=audience,
            tone=tone,
            slide_index=index,
            slot_values=filtered_slot_values,
            image_backend=image_backend,
        )
        return SlideContent(
            index=index,
            role=role,
            title=filtered_slot_values.get("title", filtered_slot_values.get("cover_title", f"{topic} #{index}")),
            slot_values=filtered_slot_values,
            prompt_payloads=prompt_payloads,
            slide_purpose=role_schema.description,
            image_backend=image_backend,
            generation_mode=generation_mode,
        )

    def _generate_ai_slot_values(
        self,
        *,
        template: TemplatePackage,
        topic: str,
        brief: str,
        audience: str,
        tone: str,
        cta: str,
        slide_count: int,
        roles: list[str],
        session_id: str | None = None,
        user_context: str = "",
    ) -> dict[int, dict[str, str]]:
        """
        Fans out to 5 parallel writing agents via CaptainWritingAgent,
        then passes results through the AuthenticatorAgent.
        Falls back to empty dict if Claude is not configured.
        """
        if not self.claude_client or not self.claude_client.is_configured():
            return {}

        # Build slide specs — each agent only sees the slots it is allowed to fill
        slide_specs = [
            {
                "index": index,
                "role": role,
                "allowed_slots": template.manifest.slide_roles[role].slots,
                "slot_descriptions": {
                    slot: (template.manifest.slots[slot].name if slot in template.manifest.slots else slot)
                    for slot in template.manifest.slide_roles[role].slots
                },
                "slide_description": template.manifest.slide_roles[role].description,
                "max_chars": {
                    slot: (template.manifest.slots[slot].max_chars if slot in template.manifest.slots else 200)
                    for slot in template.manifest.slide_roles[role].slots
                },
            }
            for index, role in enumerate(roles, start=1)
        ]

        log.info(
            "Launching CaptainWritingAgent for %d slides on template '%s'",
            len(slide_specs),
            template.manifest.id,
        )

        event_bus: AgentEventBus | None = get_bus(session_id) if session_id else None
        # max_workers=2 keeps concurrent Claude calls under the 5-RPM Tier-1 limit.
        # With InputAuthenticator (1 call) + Captain dispatch (1) + AuthenticatorAgent (1)
        # already consuming the budget, we can only safely run 2 writers in parallel.
        # The remaining writers queue and complete sequentially.
        captain = CaptainWritingAgent(
            client=self.claude_client, max_workers=2, event_bus=event_bus,
            user_context=user_context,
        )
        return captain.run(
            slide_specs=slide_specs,
            topic=topic,
            brief=brief,
            audience=audience,
            tone=tone,
            cta=cta,
            template_id=template.manifest.id,
            template_name=template.manifest.name,
            prompt_hints=template.manifest.prompt_hints,
        )

    def _slot_values_for_role(
        self,
        *,
        template: TemplatePackage,
        role: str,
        topic: str,
        brief: str,
        audience: str,
        tone: str,
        cta: str,
        index: int,
        slide_count: int,
    ) -> dict[str, str]:
        template_id = template.manifest.id
        if template_id in {
            "nox-mono",
            "nox-paper",
            "nox-num",
            "nox-quote",
            "nox-grid",
            "nox-grad",
            "nox-cta",
            "nox-check",
        }:
            return self._gallery_slot_values(
                template_id=template_id,
                role=role,
                topic=topic,
                brief=brief,
                audience=audience,
                tone=tone,
                cta=cta,
                index=index,
                slide_count=slide_count,
            )
        base_body = brief.strip() or f"A concise, useful LinkedIn carousel about {topic}."
        role_map = {
            "cover": {
                "eyebrow": audience.upper()[:28],
                "title": topic,
                "body": f"{base_body}\n\nTone: {tone}.",
                "image_primary": f"Visual anchor for {topic}",
                "cta": cta,
            },
            "problem": {
                "title": f"The hidden cost of {topic.lower()}",
                "body": f"Most {audience.lower()} struggle because {base_body}",
                "image_primary": f"Show friction or bottleneck related to {topic}",
            },
            "insight": {
                "eyebrow": "KEY INSIGHT",
                "title": f"What changes when you rethink {topic.lower()}",
                "body": f"Shift the reader from confusion to clarity with a {tone.lower()} explanation tailored for {audience}.",
            },
            "framework": {
                "title": f"A simple framework for {topic.lower()}",
                "body": "1. Clarify the promise.\n2. Structure the narrative.\n3. Add proof.\n4. Close with an action.",
                "image_primary": f"Diagram or process illustration for {topic}",
            },
            "proof": {
                "eyebrow": "PROOF",
                "title": f"Why this works for {audience}",
                "body": f"Support the point with a concrete proof angle: trend, mini case study, or operating principle connected to {topic}.",
            },
            "cta": {
                "title": f"Use this to improve {topic.lower()}",
                "body": f"Recap the idea, keep the tone {tone.lower()}, and invite the reader to act.",
                "cta": cta,
            },
        }
        values = role_map.get(role, role_map["insight"]).copy()
        values["page_number"] = f"{index:02d}/{slide_count:02d}"
        return values

    def _gallery_slot_values(
        self,
        *,
        template_id: str,
        role: str,
        topic: str,
        brief: str,
        audience: str,
        tone: str,
        cta: str,
        index: int,
        slide_count: int,
    ) -> dict[str, str]:
        title = topic.strip() or "LinkedIn growth"
        brief_clean = brief.strip() or f"A practical LinkedIn carousel for {audience}."
        short_audience = audience.strip() or "founders"
        total_content_items = max(slide_count - 1, 1)
        page_num = f"{index:02d} / {slide_count:02d}"

        role_titles = {
            "problem":   f"Why {title.lower()} breaks momentum",
            "insight":   f"The shift that makes {title.lower()} work",
            "framework": f"A simple system for {title.lower()}",
            "proof":     f"What proves this works for {short_audience.lower()}",
            "cta":       f"Use this system for {title.lower()}",
        }
        role_bodies = {
            "problem":   f"Most {short_audience.lower()} lose consistency because {brief_clean[:1].lower() + brief_clean[1:] if len(brief_clean) > 1 else brief_clean}",
            "insight":   f"The advantage comes from making {title.lower()} repeatable, not more complicated.",
            "framework": "Clarify the hook. Match the template. Sequence the slides. Close with a decisive CTA.",
            "proof":     f"When the message and template align, {short_audience.lower()} understand the point faster and act sooner.",
            "cta":       f"{cta} Keep the tone {tone.lower()} and make the next step obvious.",
        }
        content_title = role_titles.get(role, f"How to improve {title.lower()}")
        content_body = role_bodies.get(role, brief_clean)
        author_initial = (short_audience[:1] or "N").upper()
        author_handle = f"@{short_audience.lower().replace(' ', '')}"
        # Universal Noxlin attribution stamp at bottom-right of every slide
        stamp_brand = "Noxlin"
        stamp_site = "noxlin.com"

        # Helper: wrap any per-template dict to always include the universal stamp slots
        def _with_stamp(d: dict[str, str]) -> dict[str, str]:
            d.setdefault("stamp_brand", stamp_brand)
            d.setdefault("stamp_site", stamp_site)
            return d

        if template_id == "nox-mono":
            kicker_map = {
                "cover":     f"— {tone.upper()} CAROUSEL",
                "problem":   "— THE PROBLEM",
                "insight":   "— THE INSIGHT",
                "framework": "— THE FRAMEWORK",
                "proof":     "— THE PROOF",
                "cta":       "— YOUR TURN",
            }
            return _with_stamp({
                "brand_name":     "noxlin",
                "page_number":    page_num,
                "kicker":         kicker_map.get(role, f"— {role.upper()}"),
                "hero":           title if role == "cover" else content_title,
                "support":        brief_clean if role != "cover" else "",
                "author_initial": author_initial,
                "author_name":    short_audience,
                "author_handle":  author_handle,
                # Always short — the .nx-arrow pill is sized for ~12 chars max
                "swipe_label":    "swipe →" if role == "cover" else "",
            })

        if template_id == "nox-paper":
            issue_num = 7 + index
            drop_cap = brief_clean[0] if brief_clean else "A"
            article_rest = brief_clean[1:] if len(brief_clean) > 1 else ""
            return _with_stamp({
                "brand_name":     "noxlin",
                "page_number":    page_num,
                "issue_label":    f"Essay № {issue_num:02d}",
                "issue_topic":    f"On {title.lower()}",
                "issue_date":     self._month_label(),
                "issue_chapter":  f"Chapter {self._roman(index)}",
                "hero_intro":     "A note on" if role == "cover" else "",
                "hero":           title if role == "cover" else content_title,
                "sub":            brief_clean if role == "cover" else "",
                "body_html":      f"<p><span class=\"drop-cap\">{drop_cap}</span>{article_rest}</p><p>{content_body}</p>",
                "author_initial": author_initial,
                "author_name":    short_audience,
                "author_handle":  author_handle,
                "swipe_label":    "→",
            })

        if template_id == "nox-num":
            # Numeral on cover = total list items; on content = ordinal of this item
            numeral = (
                str(total_content_items) if role == "cover" else str(max(index - 1, 1))
            )
            return _with_stamp({
                "brand_site":     "noxlin.com",
                "page_number":    page_num,
                "numeral":        numeral,
                "hero":           (
                    f"Reasons your {title.lower()} <em>stopped</em> growing."
                    if role == "cover"
                    else f"You {self._verb_for(role)} <em>{self._emphasis_word(content_body)}</em>."
                ),
                "sub":            brief_clean if role == "cover" else content_body,
                "author_initial": author_initial,
                "author_name":    short_audience,
                "author_handle":  author_handle,
            })

        if template_id == "nox-quote":
            return _with_stamp({
                "page_number":       page_num,
                "context_label":     f"— Pull-quote · {title}",
                "quote":             (
                    f"{title} is a <em>scheduling</em> problem,<br>not a creative one."
                    if role == "cover"
                    else f"People don't want <em>tools</em>.<br>They want {self._emphasis_word(content_body) or 'outcomes'}."
                ),
                "author_name":       short_audience,
                "attribution_topic": f"On {title.lower()}",
            })

        if template_id == "nox-grid":
            hero_parts = self._split_topic(title, 2)
            return _with_stamp({
                "brand_site":     "noxlin.com",
                "page_number":    f"{index:02d} / {slide_count:02d}",
                "section_label":  f"{short_audience.upper()} / <b>SYSTEM</b>",
                "page_label":     f"{index:02d} — {role.upper()}",
                "eyebrow":        f"— {tone} framework",
                "headline":       (
                    f"{hero_parts[0]}.<br>{hero_parts[1]} <em>out</em>."
                    if role == "cover"
                    else f"The system, <em>simplified</em>."
                ),
                "lead_text":      brief_clean,
                "stat_label":     "— Output",
                "stat_number":    str(total_content_items),
                "stat_sub":       f"slides, sequenced for {short_audience.lower()}",
                "c1_num":         "01 — INPUT",
                "c1_title":       "You describe the problem.",
                "c1_body":        f"One sentence is enough. {short_audience} don't configure anything.",
                "c2_num":         "02 — ENGINE",
                "c2_title":       "Noxlin writes & designs.",
                "c2_body":        f"AI drafts hooks, structures the carousel and renders every slide on brand in {tone.lower()} tone.",
                "c3_num":         "03 — DISTRIBUTION",
                "c3_title":       "It posts itself.",
                "c3_body":        f"Your calendar fills at the right times — {cta}",
                "author_initial": author_initial,
                "author_name":    short_audience,
                "author_handle":  author_handle,
            })

        if template_id == "nox-grad":
            hero_parts = self._split_topic(title, 3)
            stat_value = self._extract_numeric_emphasis(brief_clean)
            return _with_stamp({
                "brand_name":     "noxlin",
                "brand_site":     "noxlin.com",
                "brand_handle":   "@noxlin",
                "page_number":    str(index),
                "page_label":     page_num,
                "chip_label":     "LINKEDIN GROWTH" if role == "cover" else "THE NUMBERS",
                "pre_text":       brief_clean if role == "cover" else "",
                "hero_thin":      hero_parts[0],
                "hero_bold":      hero_parts[1] or "Compounds",
                "hero_italic":    hero_parts[2] or "daily.",
                "stat_big":       stat_value,
                "stat_unit":      "more opportunities",
                "stat_label":     f"— {title.upper()} / {tone.upper()}",
                "support":        content_body,
                # User identity (now in the bottom-pill, not the top brand)
                "author_initial": author_initial,
                "author_name":    short_audience,
                "author_handle":  author_handle,
            })

        if template_id == "nox-check":
            is_cover = role == "cover"
            is_final = role == "cta"
            # Step number: cover has no step; cta is the final tile; others count from 1
            step_position = max(index - 1, 1)
            step_num_str = f"{step_position:02d}"
            kicker_label = f"{tone.upper()} CHECKLIST"
            badge_label  = f"FOR {short_audience.upper()}"
            recap_label  = f"— RECAP · {title}".upper()
            # Two-line cover hero with italic accent on the last word
            step_total = max(slide_count - 2, 3)
            hero_cover = f"The {step_total}-step<br>{title} <em>checklist</em>"
            # Per-step content (deterministic fallback — AI overrides per slide)
            step_verbs = {1: "Set up", 2: "Sharpen", 3: "Ship", 4: "Sustain", 5: "Scale", 6: "Refine", 7: "Repeat", 8: "Review"}
            step_verb  = step_verbs.get(step_position, "Build")
            step_titles = {
                "framework": f"{step_verb} the {title.lower()} system",
                "insight":   f"Reframe how you think about {title.lower()}",
                "problem":   f"Find what's blocking your {title.lower()}",
                "proof":     f"Validate that {title.lower()} actually works",
            }
            step_title_default = step_titles.get(role, f"Move {title.lower()} forward")
            pull_options = [
                "But step 2 is the one most people skip →",
                "Here's where it gets interesting →",
                "The next step is where most decks fall apart →",
                "Save this — you'll come back to it →",
                "Watch what happens on the next slide →",
            ]
            pull = pull_options[(index - 1) % len(pull_options)]
            return _with_stamp({
                "page_number":    page_num,
                "kicker":         kicker_label,
                "hero":           hero_cover if is_cover else (
                    f"You don't need more {title.lower()}.<br>You need <em>fewer</em> moves."
                    if is_final else ""
                ),
                "sub":            (
                    brief_clean if is_cover
                    else (f"{brief_clean} {cta}".strip() if is_final else "")
                ),
                "badge_label":    badge_label,
                "swipe_label":    "swipe →",
                "step_num":       step_num_str,
                "step_eyebrow":   f"STEP {step_position:02d} · {role.upper()}",
                "step_title":     step_title_default,
                "item_1":         f"Pick one specific outcome — {short_audience.lower()} convert when the goal is concrete.",
                "item_2":         f"Block 30 minutes on your calendar this week to ship it.",
                "item_3":         f"Share it publicly so {short_audience.lower()} can react and you compound.",
                "pull_to_next":   pull if not is_final else "",
                "recap_label":    recap_label,
                "cta_label":      cta or "Save this checklist",
                "save_prompt":    "💾 SAVE FOR LATER · ♻ REPOST IF USEFUL",
                "author_initial": author_initial,
                "author_name":    short_audience,
                "author_handle":  author_handle,
            })

        # nox-cta
        head_parts = self._split_topic(title, 2)
        is_final = role == "cta"
        return _with_stamp({
            "brand_name":     "noxlin",
            "page_number":    f"{page_num} · END" if is_final else f"{page_num} · PAUSE",
            "chip_label":     "YOUR TURN" if is_final else "HALFWAY MARK",
            "head":           (
                f"Let {head_parts[0]} <em>handle</em> your {head_parts[1] or 'LinkedIn'}."
                if is_final
                else f"Still with <em>us</em>?<br>Good."
            ),
            "sub":            f"{brief_clean} {cta}".strip(),
            "cta_label":      cta or ("Try Noxlin free" if is_final else "Keep swiping"),
            "author_initial": author_initial,
            "author_name":    short_audience,
            "author_handle":  f"{author_handle} · noxlin.com",
            "footer_label":   "FOLLOW FOR MORE" if is_final else "SAVE FOR LATER",
        })

    def _emphasis_word(self, text: str) -> str:
        return self._pick_emphasis_word(text or "outcomes")

    def _verb_for(self, role: str) -> str:
        return {
            "problem":   "post in",
            "insight":   "need",
            "framework": "rely on",
            "proof":     "see results from",
            "cta":       "should try",
        }.get(role, "discover")

    def _roman(self, n: int) -> str:
        # Tiny roman numeral helper for chapter labels (1..20 covers all use)
        roman_map = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
        out = ""
        for value, sym in roman_map:
            while n >= value:
                out += sym
                n -= value
        return out or "I"

    def _split_topic(self, topic: str, parts: int) -> list[str]:
        words = topic.split()
        if not words:
            return ["LinkedIn", "growth", "system"][:parts]
        groups = [""] * parts
        for index, word in enumerate(words):
            groups[min(index, parts - 1)] += ("" if not groups[min(index, parts - 1)] else " ") + word
        fallback = ["LinkedIn", "growth", "system"]
        return [groups[index] or fallback[index] for index in range(parts)]

    def _pick_emphasis_word(self, text: str) -> str:
        words = [word.strip(".,!?") for word in text.split() if word.strip(".,!?")]
        for word in words:
            if len(word) >= 5:
                return word
        return words[0] if words else "visible"

    def _extract_numeric_emphasis(self, text: str) -> str:
        match = re.search(r"\b\d+[xX%]?\b", text)
        if match:
            value = match.group(0)
            return value.replace("X", "x") if value.lower().endswith("x") else value
        return "3x"

    def _month_label(self) -> str:
        from datetime import UTC, datetime

        return datetime.now(UTC).strftime("%B %Y")

    def _build_prompt_payloads(
        self,
        *,
        template: TemplatePackage,
        role: str,
        topic: str,
        audience: str,
        tone: str,
        slide_index: int,
        slot_values: dict[str, str],
        image_backend: str,
    ) -> list[SlidePromptPayload]:
        payloads: list[SlidePromptPayload] = []
        style_reference = str(template.manifest.prompt_hints.get("style", ""))
        for slot_name, value in slot_values.items():
            slot = template.manifest.slots.get(slot_name)
            if not slot or slot.slot_type != "image":
                continue
            prompt = (
                f"Backend: {image_backend}. Create a visually consistent carousel asset for slide {slide_index}. "
                f"Role: {role}. Topic: {topic}. Audience: {audience}. Tone: {tone}. "
                f"Template style: {style_reference}. Visual brief: {value}."
            )
            payloads.append(
                SlidePromptPayload(
                    slot_name=slot_name,
                    prompt=prompt,
                    negative_prompt="Avoid unreadable text, clutter, extra hands, inconsistent branding, and off-topic objects.",
                    consistency_anchor=f"{template.manifest.id}:{topic}:{audience}:{tone}",
                    style_reference=style_reference,
                )
            )
        if not payloads:
            payloads.append(
                SlidePromptPayload(
                    slot_name="full_slide",
                    prompt=(
                        f"Backend: {image_backend}. Generate a full-slide concept for slide {slide_index} in a "
                        f"{tone.lower()} tone about {topic}, aligned with template {template.manifest.id}."
                    ),
                    negative_prompt="Avoid layout drift, dense unreadable text, and inconsistent palette.",
                    consistency_anchor=f"{template.manifest.id}:{topic}:{audience}:{tone}",
                    style_reference=style_reference,
                )
            )
        return payloads

    def _enforce_length(self, template: TemplatePackage, slot_name: str, value: str) -> str:
        slot = template.manifest.slots.get(slot_name)
        if not slot or slot.max_chars is None:
            return value
        if len(value) <= slot.max_chars:
            return value
        cutoff = max(slot.max_chars - 3, 1)
        return value[:cutoff].rstrip() + "..."
