from __future__ import annotations

import logging
from pathlib import Path
from xml.sax.saxutils import escape

from app.domain import CarouselPlan, SlideContent, utc_now
from app.services.ai_clients import GeminiImageClient, ProviderError
from app.services.agents import VisualCaptain

log = logging.getLogger(__name__)


class ImageGenerationService:
    def __init__(
        self,
        artifacts_root: Path,
        gemini_client: GeminiImageClient | None = None,
    ) -> None:
        self.artifacts_root = artifacts_root
        self.gemini_client = gemini_client
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

    def materialize(self, plan: CarouselPlan) -> CarouselPlan:
        """
        Generates all images for a carousel plan using 5 parallel VisualAgents
        (A1-A5). Each agent owns a slice of image tasks and calls Gemini
        concurrently. Falls back to placeholder SVGs if Gemini is unavailable.
        """
        target_dir = self.artifacts_root / plan.id / "generated"
        target_dir.mkdir(parents=True, exist_ok=True)

        use_gemini = self._should_use_gemini(plan.image_backend)

        # ── Build the flat task list for VisualCaptain ────────────────
        tasks = []
        for slide in plan.slides:
            if plan.generation_mode == "slot_fill":
                for payload in slide.prompt_payloads:
                    if payload.slot_name == "full_slide":
                        continue
                    tasks.append({
                        "slide_index": slide.index,
                        "slot_name": payload.slot_name,
                        "prompt": payload.prompt,
                        "negative_prompt": payload.negative_prompt,
                        "consistency_anchor": payload.consistency_anchor,
                        "output_path": target_dir / f"slide-{slide.index:02d}-{payload.slot_name}.png",
                        "slide_title": slide.title,
                        "mode": "slot",
                    })
            else:
                if slide.prompt_payloads:
                    tasks.append({
                        "slide_index": slide.index,
                        "slot_name": "full_slide",
                        "prompt": slide.prompt_payloads[0].prompt,
                        "negative_prompt": slide.prompt_payloads[0].negative_prompt,
                        "consistency_anchor": "",
                        "output_path": target_dir / f"slide-{slide.index:02d}-full.png",
                        "slide_title": slide.title,
                        "mode": "full",
                    })

        # ── Run 5 Visual Agents in parallel (only if Gemini available) ─
        generated: dict[str, str] = {}
        if use_gemini and tasks:
            log.info("VisualCaptain: launching 5 agents for %d image tasks", len(tasks))
            captain = VisualCaptain(client=self.gemini_client, max_workers=5)
            generated = captain.run(tasks)

        # ── Merge results back into slides ────────────────────────────
        slides: list[SlideContent] = []
        for slide in plan.slides:
            slot_values = dict(slide.slot_values)

            if plan.generation_mode == "slot_fill":
                for payload in slide.prompt_payloads:
                    if payload.slot_name == "full_slide":
                        continue
                    key = f"{slide.index}:{payload.slot_name}"
                    path = generated.get(key, "")
                    if not path:
                        # Gemini failed or not configured → SVG placeholder
                        path = self._write_slot_svg(
                            target_dir=target_dir,
                            slide=slide,
                            slot_name=payload.slot_name,
                            prompt=payload.prompt,
                            consistency_anchor=payload.consistency_anchor,
                        )
                    slot_values[payload.slot_name] = path
            else:
                key = f"{slide.index}:full_slide"
                path = generated.get(key, "")
                if not path:
                    path = self._write_full_svg(target_dir=target_dir, slide=slide)
                slot_values["generated_full_slide"] = path

            slides.append(SlideContent(
                index=slide.index,
                role=slide.role,
                title=slide.title,
                slot_values=slot_values,
                prompt_payloads=slide.prompt_payloads,
                slide_purpose=slide.slide_purpose,
                image_backend=slide.image_backend,
                generation_mode=slide.generation_mode,
            ))

        plan.slides = slides
        plan.status = "assets_generated"
        plan.updated_at = utc_now()
        return plan

    # ── Helpers ───────────────────────────────────────────────────────

    def _should_use_gemini(self, image_backend: str) -> bool:
        if not self.gemini_client or not self.gemini_client.is_configured():
            return False
        return image_backend in {"gemini", "gemini_image", "nano_banana"}

    def _write_slot_svg(
        self,
        *,
        target_dir: Path,
        slide: SlideContent,
        slot_name: str,
        prompt: str,
        consistency_anchor: str,
    ) -> str:
        path = target_dir / f"slide-{slide.index:02d}-{slot_name}.svg"
        path.write_text(self._slot_svg(slide.index, slot_name, slide.title, prompt, consistency_anchor), encoding="utf-8")
        return str(path)

    def _write_full_svg(self, *, target_dir: Path, slide: SlideContent) -> str:
        path = target_dir / f"slide-{slide.index:02d}-full.svg"
        prompt = slide.prompt_payloads[0].prompt if slide.prompt_payloads else ""
        path.write_text(self._full_slide_svg(slide.index, slide.title, slide.slide_purpose, prompt), encoding="utf-8")
        return str(path)

    def _slot_svg(
        self, index: int, slot_name: str, title: str, prompt: str, consistency_anchor: str
    ) -> str:
        prompt_preview = escape(prompt[:180])
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="720" height="720" viewBox="0 0 720 720">
  <rect width="720" height="720" fill="#EEF5FF"/>
  <rect x="32" y="32" width="656" height="656" rx="24" fill="#FFFFFF" stroke="#0A66C2" stroke-width="4"/>
  <text x="64" y="112" font-family="Arial" font-size="28" fill="#0A66C2">Slide {index:02d} · {escape(slot_name)}</text>
  <text x="64" y="176" font-family="Arial" font-size="42" font-weight="700" fill="#0A0A0A">{escape(title[:40])}</text>
  <text x="64" y="240" font-family="Arial" font-size="22" fill="#434649">{prompt_preview}</text>
  <text x="64" y="620" font-family="Arial" font-size="18" fill="#86888A">{escape(consistency_anchor[:70])}</text>
</svg>"""

    def _full_slide_svg(self, index: int, title: str, purpose: str, prompt: str) -> str:
        prompt_preview = escape(prompt[:220])
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350">
  <rect width="1080" height="1350" fill="#0A66C2"/>
  <rect x="48" y="48" width="984" height="1254" rx="28" fill="#FFFFFF"/>
  <text x="96" y="180" font-family="Arial" font-size="34" fill="#0A66C2">AI GENERATED FULL SLIDE {index:02d}</text>
  <text x="96" y="280" font-family="Arial" font-size="82" font-weight="700" fill="#0A0A0A">{escape(title[:50])}</text>
  <text x="96" y="380" font-family="Arial" font-size="30" fill="#434649">{escape(purpose[:120])}</text>
  <text x="96" y="520" font-family="Arial" font-size="24" fill="#434649">{prompt_preview}</text>
</svg>"""
