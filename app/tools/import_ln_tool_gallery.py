from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from app.bootstrap import build_container
from app.domain import RenderConfig, SlideRoleSchema, SlotDefinition, TemplateManifest, TemplatePackage


def text_slot(name: str, max_chars: int | None = None, required: bool = False) -> SlotDefinition:
    return SlotDefinition(name=name, slot_type="text", max_chars=max_chars, required=required, mode="deterministic")


def build_roles(cover_slots: list[str], content_slots: list[str]) -> dict[str, SlideRoleSchema]:
    return {
        "cover": SlideRoleSchema(
            role="cover",
            description="Open the carousel with the selected template's cover composition.",
            slots=cover_slots,
            render_variant="cover",
        ),
        "problem": SlideRoleSchema(
            role="problem",
            description="Present a pain point using the selected template's content composition.",
            slots=content_slots,
            render_variant="content",
        ),
        "insight": SlideRoleSchema(
            role="insight",
            description="Teach a key insight using the selected template's content composition.",
            slots=content_slots,
            render_variant="content",
        ),
        "framework": SlideRoleSchema(
            role="framework",
            description="Explain a framework or sequence using the selected template's content composition.",
            slots=content_slots,
            render_variant="content",
        ),
        "proof": SlideRoleSchema(
            role="proof",
            description="Add proof or evidence using the selected template's content composition.",
            slots=content_slots,
            render_variant="content",
        ),
        "cta": SlideRoleSchema(
            role="cta",
            description="Close the carousel using the selected template's content composition.",
            slots=content_slots,
            render_variant="content",
        ),
    }


@dataclass(frozen=True)
class GalleryTemplateSpec:
    template_id: str
    name: str
    tag: str
    description: str
    cover_marker: str
    content_marker: str
    cover_replacements: list[tuple[str, str]]
    content_replacements: list[tuple[str, str]]
    slots: dict[str, SlotDefinition]
    cover_slots: list[str]
    content_slots: list[str]
    prompt_style: str
    use_cases: list[str]


GALLERY_SPECS: list[GalleryTemplateSpec] = [
    GalleryTemplateSpec(
        template_id="ln-dark",
        name="LN Dark",
        tag="Feature launches · Announcements",
        description="Pitch-black canvas with an electric LinkedIn-blue gradient hero and bold parallel-system messaging.",
        cover_marker='<div class="slide ln-dark">',
        content_marker='<div class="slide ln-dark content">',
        cover_replacements=[
            ("LinkedIn Growth", "{{top_center}}"),
            ("01 / 07", "{{page_number}}"),
            ("✦ Auto-schedule 30 days", "{{pill_tag}}"),
            ('Your LinkedIn<br><span class="grad">runs itself</span><span class="star">✦</span>', '{{hero_prefix}}<br><span class="grad">{{hero_gradient}}</span><span class="star">✦</span>'),
            (
                "Set your niche, tone and posting days once. <b>Five AI agents</b> turn your inputs into a 30-day calendar — written, designed and scheduled without you touching a thing.",
                "{{body_html}}",
            ),
            ("LN Tool · @lntool", "{{brand_handle}}"),
        ],
        content_replacements=[
            ("How it works", "{{top_center}}"),
            ("03 / 07", "{{page_number}}"),
            (
                '<div class="col"><b>Orchestrator</b> reads your niche + audience and writes the full 30-day plan as structured JSON.</div>',
                '<div class="col">{{feature_1_html}}</div>',
            ),
            (
                '<div class="col"><b>Writer + Visual</b> agents run in parallel — 60 LLM calls in 4 seconds, not 2 minutes.</div>',
                '<div class="col">{{feature_2_html}}</div>',
            ),
            (
                '<div class="col"><b>Scheduler</b> finds your best posting times and fires Celery jobs at the exact eta you want.</div>',
                '<div class="col">{{feature_3_html}}</div>',
            ),
            ('<div class="pill">Five agents. One click.</div>', '<div class="pill">{{mid_pill}}</div>'),
            ('Parallel beats <span class="w-blue">sequential</span>*', '{{hero_sub_prefix}} <span class="w-blue">{{hero_sub_highlight}}</span>*'),
            ("LN Tool · @lntool", "{{brand_handle}}"),
        ],
        slots={
            "top_center": text_slot("top_center", 40),
            "page_number": text_slot("page_number", 12, required=True),
            "pill_tag": text_slot("pill_tag", 48),
            "hero_prefix": text_slot("hero_prefix", 40, required=True),
            "hero_gradient": text_slot("hero_gradient", 22, required=True),
            "body_html": text_slot("body_html", 320),
            "brand_handle": text_slot("brand_handle", 40),
            "feature_1_html": text_slot("feature_1_html", 220),
            "feature_2_html": text_slot("feature_2_html", 220),
            "feature_3_html": text_slot("feature_3_html", 220),
            "mid_pill": text_slot("mid_pill", 48),
            "hero_sub_prefix": text_slot("hero_sub_prefix", 28),
            "hero_sub_highlight": text_slot("hero_sub_highlight", 20),
        },
        cover_slots=["top_center", "page_number", "pill_tag", "hero_prefix", "hero_gradient", "body_html", "brand_handle"],
        content_slots=[
            "top_center",
            "page_number",
            "feature_1_html",
            "feature_2_html",
            "feature_3_html",
            "mid_pill",
            "hero_sub_prefix",
            "hero_sub_highlight",
            "brand_handle",
        ],
        prompt_style="Dark launch-style carousel, pitch-black base, cobalt gradient emphasis, premium product-announcement mood.",
        use_cases=["Product launches", "Announcements", "Feature reveals", "Bold statements"],
    ),
    GalleryTemplateSpec(
        template_id="ln-big-number",
        name="LN Big Number",
        tag='Listicles · "N reasons" posts',
        description="Solid LinkedIn-blue cover with giant Fraunces numerals and a pale-blue number watermark on content slides.",
        cover_marker='<div class="slide ln-number cover">',
        content_marker='<div class="slide ln-number content">',
        cover_replacements=[
            ("01 / 06", "{{page_number}}"),
            ('<div class="big-num">5</div>', '<div class="big-num">{{cover_number}}</div>'),
            ("Reasons your LinkedIn stopped&nbsp;growing", "{{cover_title}}"),
            ("and the fix for each — based on 2M posts analysed by LN Tool", "{{cover_subtitle}}"),
        ],
        content_replacements=[
            ("02 / 06", "{{page_number}}"),
            ('<div class="big-num">1</div>', '<div class="big-num">{{item_number}}</div>'),
            ("You post in bursts, then disappear", "{{content_title}}"),
            (
                "LinkedIn's algorithm rewards frequency consistency far more than quality spikes. A steady 3-posts-a-week account beats a 10-post binge every time.",
                "{{body_lead}}",
            ),
            (
                'LN Tool\'s Scheduler agent locks in your cadence and fires posts automatically so the "I\'ll post more next week" loop ends here.',
                "{{body_support}}",
            ),
        ],
        slots={
            "page_number": text_slot("page_number", 12, required=True),
            "cover_number": text_slot("cover_number", 4, required=True),
            "cover_title": text_slot("cover_title", 84, required=True),
            "cover_subtitle": text_slot("cover_subtitle", 140),
            "item_number": text_slot("item_number", 4, required=True),
            "content_title": text_slot("content_title", 86, required=True),
            "body_lead": text_slot("body_lead", 220),
            "body_support": text_slot("body_support", 220),
        },
        cover_slots=["page_number", "cover_number", "cover_title", "cover_subtitle"],
        content_slots=["page_number", "item_number", "content_title", "body_lead", "body_support"],
        prompt_style="Number-led LinkedIn listicle with a solid cobalt cover, oversized serif numeral, and editorial whitespace.",
        use_cases=['5 reasons…', '7 ways to…', '3 myths about…', 'Counted frameworks'],
    ),
    GalleryTemplateSpec(
        template_id="ln-gradient-grain",
        name="LN Gradient Grain",
        tag="Thought leadership · Stats & insights",
        description="Navy-to-blue gradient with grain overlay, pill headers, and stat-first content moments.",
        cover_marker='<div class="slide ln-gradient">',
        content_marker='<div class="slide ln-gradient content">',
        cover_replacements=[
            ("LINKEDIN GROWTH", "{{top_center}}"),
            ('<div class="page-circle">1</div>', '<div class="page-circle">{{page_badge}}</div>'),
            (
                "Every time you skip posting on LinkedIn, someone in your niche gets the attention that could have been yours.",
                "{{mid_text}}",
            ),
            (
                '<div class="hero"><span class="thin">Content</span><br><span class="bold">Compounds</span><br><span class="thin">daily</span></div>',
                '<div class="hero"><span class="thin">{{hero_line_1}}</span><br><span class="bold">{{hero_line_2}}</span><br><span class="thin">{{hero_line_3}}</span></div>',
            ),
            ("+91 000 000 000", "{{footer_left}}"),
            ("@lntool", "{{footer_right}}"),
        ],
        content_replacements=[
            ("THE NUMBERS", "{{top_center}}"),
            ('<div class="page-circle">4</div>', '<div class="page-circle">{{page_badge}}</div>'),
            ('<div class="big-stat">40×</div>', '<div class="big-stat">{{stat_value}}</div>'),
            ('<div class="stat-unit">more opportunities</div>', '<div class="stat-unit">{{stat_unit}}</div>'),
            ('<div class="stat-label">LINKEDIN / 2024 EXECUTIVE REPORT</div>', '<div class="stat-label">{{stat_label}}</div>'),
            (
                "Executives with a <b>complete personal brand</b> receive 40× more inbound opportunities than those who stay silent on the platform.",
                "{{support_text_html}}",
            ),
            ("lntool.io", "{{footer_left}}"),
            ("@lntool", "{{footer_right}}"),
        ],
        slots={
            "top_center": text_slot("top_center", 30),
            "page_badge": text_slot("page_badge", 4, required=True),
            "mid_text": text_slot("mid_text", 180),
            "hero_line_1": text_slot("hero_line_1", 20, required=True),
            "hero_line_2": text_slot("hero_line_2", 20, required=True),
            "hero_line_3": text_slot("hero_line_3", 20, required=True),
            "footer_left": text_slot("footer_left", 28),
            "footer_right": text_slot("footer_right", 28),
            "stat_value": text_slot("stat_value", 10, required=True),
            "stat_unit": text_slot("stat_unit", 36),
            "stat_label": text_slot("stat_label", 40),
            "support_text_html": text_slot("support_text_html", 240),
        },
        cover_slots=["top_center", "page_badge", "mid_text", "hero_line_1", "hero_line_2", "hero_line_3", "footer_left", "footer_right"],
        content_slots=["top_center", "page_badge", "stat_value", "stat_unit", "stat_label", "support_text_html", "footer_left", "footer_right"],
        prompt_style="Navy-to-cobalt gradient with tactile grain, pill labels, and corporate thought-leadership energy.",
        use_cases=["Industry reports", "Stat hooks", "Corporate insights", "Why this matters"],
    ),
    GalleryTemplateSpec(
        template_id="ln-fresh-block",
        name="LN Fresh Block",
        tag="Question hooks · Relatable posts",
        description="Bright LinkedIn-blue cover with cream cut-paper blocks, serif italics, and high-contrast question-led composition.",
        cover_marker='<div class="slide ln-fresh cover">',
        content_marker='<div class="slide ln-fresh content">',
        cover_replacements=[
            (
                '<div class="hero"><span class="italic-serif">Are you </span>invisible<br>on LinkedIn?</div>',
                '<div class="hero"><span class="italic-serif">{{hero_italic}}</span>{{hero_line_1}}<br>{{hero_line_2}}</div>',
            ),
            (
                '3 reasons your posts get zero\n            <span class="offset">reach — and what to do instead</span>',
                '{{subline_main}}\n            <span class="offset">{{subline_offset}}</span>',
            ),
            ("lntool.io", "{{url_text}}"),
        ],
        content_replacements=[
            (
                'You\'re not <span class="highlight">invisible</span>.<br>You\'re just<br><em>unscheduled.</em>',
                '{{content_line_prefix}} <span class="highlight">{{content_highlight}}</span>.<br>{{content_line_2}}<br><em>{{content_emphasis}}</em>',
            ),
            (
                "Posting when you feel like it is why 90% of accounts plateau. <b>Consistency beats quality</b> at the frequency range most founders live in — and consistency is a scheduling problem, not a creative one.",
                "{{content_body_html}}",
            ),
        ],
        slots={
            "hero_italic": text_slot("hero_italic", 24, required=True),
            "hero_line_1": text_slot("hero_line_1", 24, required=True),
            "hero_line_2": text_slot("hero_line_2", 28, required=True),
            "subline_main": text_slot("subline_main", 60),
            "subline_offset": text_slot("subline_offset", 60),
            "url_text": text_slot("url_text", 24),
            "content_line_prefix": text_slot("content_line_prefix", 28, required=True),
            "content_highlight": text_slot("content_highlight", 24, required=True),
            "content_line_2": text_slot("content_line_2", 24, required=True),
            "content_emphasis": text_slot("content_emphasis", 24, required=True),
            "content_body_html": text_slot("content_body_html", 260),
        },
        cover_slots=["hero_italic", "hero_line_1", "hero_line_2", "subline_main", "subline_offset", "url_text"],
        content_slots=["content_line_prefix", "content_highlight", "content_line_2", "content_emphasis", "content_body_html"],
        prompt_style="Bold LinkedIn-blue block layout with paper-cut contrast and a question-led, scroll-stopping voice.",
        use_cases=["Question hooks", "Relatable founder posts", "Contrarian takes", "Are you… openers"],
    ),
    GalleryTemplateSpec(
        template_id="ln-editorial",
        name="LN Editorial",
        tag="Founder essays · Long-form thinking",
        description="Paper-texture editorial template with Fraunces serif, Instrument Serif accents, and magazine-style long-form composition.",
        cover_marker='<div class="slide ln-editorial">',
        content_marker='<div class="slide ln-editorial content">',
        cover_replacements=[
            (
                '<b>Essay № 14</b><br>\n              On building LinkedIn growth<br>\n              April 2026',
                "{{issue_meta_html}}",
            ),
            ("A note on", "{{cover_intro}}"),
            ("Building a brand you don't have time for", "{{cover_title}}"),
            (
                'THE MYTH OF "ONE MORE FOUNDER WHO POSTS EVERY DAY" — AND THE SYSTEM THAT REPLACED IT',
                "{{cover_subline}}",
            ),
            ('<div class="label">READ</div>', '<div class="label">{{cta_label}}</div>'),
            ('<div class="page-num">01 / <b>05</b></div>', '<div class="page-num">{{page_number_html}}</div>'),
        ],
        content_replacements=[
            (
                '<b>Essay № 14</b><br>\n              Chapter 01',
                "{{issue_meta_html}}",
            ),
            ("You don't need more <em>time</em>. You need a system.", "{{content_title_html}}"),
            (
                '<p><span class="drop-cap">T</span>he founders we watched grow fastest on LinkedIn this year weren\'t the ones writing the most. They were the ones who\'d <em>stopped writing in real time</em> altogether — replacing the "I should post today" panic with a calendar that was set once and forgot.</p>\n            <p>What looks like consistency from the outside is almost always a system on the inside.</p>',
                "{{article_html}}",
            ),
            ('<div class="page-num">02 / <b>05</b></div>', '<div class="page-num">{{page_number_html}}</div>'),
        ],
        slots={
            "issue_meta_html": text_slot("issue_meta_html", 120),
            "cover_intro": text_slot("cover_intro", 32),
            "cover_title": text_slot("cover_title", 90, required=True),
            "cover_subline": text_slot("cover_subline", 180),
            "cta_label": text_slot("cta_label", 12),
            "page_number_html": text_slot("page_number_html", 24, required=True),
            "content_title_html": text_slot("content_title_html", 120, required=True),
            "article_html": text_slot("article_html", 520),
        },
        cover_slots=["issue_meta_html", "cover_intro", "cover_title", "cover_subline", "cta_label", "page_number_html"],
        content_slots=["issue_meta_html", "content_title_html", "article_html", "page_number_html"],
        prompt_style="Premium editorial essay layout with off-white paper tone, serif hierarchy, and restrained blue emphasis.",
        use_cases=["Founder essays", "Long-form opinion", "Notes from a founder", "Premium thought pieces"],
    ),
]


def extract_tag_lines(text: str) -> str:
    head_match = re.search(r"<head>([\s\S]*?)</head>", text)
    if not head_match:
        raise ValueError("Could not find <head> in gallery source.")
    head = head_match.group(1)
    links = re.findall(r"<link[^>]+>", head)
    return "\n".join(links)


def extract_style_block(text: str) -> str:
    style_match = re.search(r"<style>([\s\S]*?)</style>", text)
    if not style_match:
        raise ValueError("Could not find <style> block in gallery source.")
    return style_match.group(1).strip()


def extract_div_block(text: str, marker: str) -> str:
    start = text.find(marker)
    if start == -1:
        raise ValueError(f"Could not find marker {marker!r}")
    token_pattern = re.compile(r"<div\b|</div>")
    depth = 0
    for match in token_pattern.finditer(text, start):
        token = match.group(0)
        if token == "<div":
            depth += 1
            if depth == 1:
                block_start = match.start()
        else:
            depth -= 1
            if depth == 0:
                return text[block_start : match.end()]
    raise ValueError(f"Unbalanced div structure for marker {marker!r}")


def apply_replacements(html: str, replacements: list[tuple[str, str]]) -> str:
    updated = html
    for original, replacement in replacements:
        if original not in updated:
            raise ValueError(f"Expected snippet not found during tokenization: {original[:80]!r}")
        updated = updated.replace(original, replacement)
    return updated


def build_manifest(spec: GalleryTemplateSpec, source_name: str) -> TemplateManifest:
    return TemplateManifest(
        id=spec.template_id,
        name=spec.name,
        description=spec.description,
        source_type="html",
        exact_source=True,
        allowed_slide_counts=[5, 6, 7, 8],
        default_slide_roles=["cover", "problem", "insight", "framework", "proof", "cta"],
        slots=spec.slots,
        slide_roles=build_roles(spec.cover_slots, spec.content_slots),
        overflow_rules={
            "cover_title": "truncate",
            "content_title": "truncate",
            "body_html": "summarize_then_truncate",
            "article_html": "summarize_then_truncate",
        },
        prompt_hints={
            "tag": spec.tag,
            "style": spec.prompt_style,
            "use_cases": spec.use_cases,
            "source_name": source_name,
            "gallery_family": spec.template_id,
            "visual_strategy": "deterministic_html_css",
        },
        render_config=RenderConfig(
            width=1080,
            height=1350,
            export_format="pdf",
            preview_format="svg",
            background_color="#FFFFFF",
        ),
    )


def import_gallery_templates(source_path: Path) -> list[TemplatePackage]:
    text = source_path.read_text(encoding="utf-8")
    head_html = extract_tag_lines(text)
    styles_css = extract_style_block(text)
    container = build_container()
    packages: list[TemplatePackage] = []
    for spec in GALLERY_SPECS:
        cover_html = apply_replacements(extract_div_block(text, spec.cover_marker), spec.cover_replacements)
        content_html = apply_replacements(extract_div_block(text, spec.content_marker), spec.content_replacements)
        package = TemplatePackage(
            manifest=build_manifest(spec, source_path.name),
            render_html=cover_html,
            styles_css=styles_css,
            head_html=head_html,
            render_variants={"cover": cover_html, "content": content_html},
        )
        container.template_repository.save_template(package)
        packages.append(package)
    return packages


def main() -> None:
    parser = argparse.ArgumentParser(description="Import LN Tool gallery templates into the local template library.")
    parser.add_argument("--source", required=True, help="Path to LNTool_Carousel_Templates.html")
    args = parser.parse_args()
    source_path = Path(args.source)
    packages = import_gallery_templates(source_path)
    print(f"Imported {len(packages)} templates:")
    for package in packages:
        print(f"- {package.manifest.id}: {package.manifest.name}")


if __name__ == "__main__":
    main()
