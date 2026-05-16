from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from xml.sax.saxutils import escape

from app.domain import CarouselPlan, TemplatePackage, utc_now

log = logging.getLogger(__name__)


class RenderService:
    def __init__(self, artifacts_root: Path) -> None:
        self.artifacts_root = artifacts_root
        self.artifacts_root.mkdir(parents=True, exist_ok=True)

    def render(self, plan: CarouselPlan, template: TemplatePackage) -> CarouselPlan:
        target_dir = self.artifacts_root / plan.id / "rendered"
        target_dir.mkdir(parents=True, exist_ok=True)
        rendered_slides: list[str] = []
        preview_paths: list[str] = []
        for slide in plan.slides:
            base_html = self._resolve_variant_html(template, slide.role)
            slide_html = self._render_slide_html(base_html, slide.slot_values, target_dir)
            html_path = target_dir / f"slide-{slide.index:02d}.html"
            html_path.write_text(slide_html, encoding="utf-8")
            preview_path = target_dir / f"slide-{slide.index:02d}-preview.svg"
            preview_path.write_text(
                self._preview_svg(
                    index=slide.index,
                    title=slide.title,
                    body=slide.slot_values.get("body", ""),
                    cta=slide.slot_values.get("cta", ""),
                    page_number=slide.slot_values.get("page_number", ""),
                    full_slide=slide.slot_values.get("generated_full_slide"),
                ),
                encoding="utf-8",
            )
            rendered_slides.append(slide_html)
            preview_paths.append(str(preview_path))
        deck_path = target_dir / "deck.html"
        deck_path.write_text(
            self._wrap_deck_html(rendered_slides, template.styles_css, template.head_html),
            encoding="utf-8",
        )
        plan.artifacts["deck_html"] = str(deck_path)
        plan.artifacts["preview_manifest"] = str(target_dir / "preview-manifest.txt")
        (target_dir / "preview-manifest.txt").write_text("\n".join(preview_paths), encoding="utf-8")
        if preview_paths:
            plan.artifacts["first_preview"] = preview_paths[0]
        plan.status = "rendered"
        plan.updated_at = utc_now()
        return plan

    def export_pdf(self, plan: CarouselPlan) -> CarouselPlan:
        target_dir = self.artifacts_root / plan.id / "export"
        target_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = target_dir / "carousel.pdf"
        deck_html_path = plan.artifacts.get("deck_html")
        if not deck_html_path or not Path(deck_html_path).exists():
            raise RuntimeError(
                "Cannot export PDF: deck.html not found. Run renderer.render() first."
            )
        # No silent fallback. If Playwright fails, the request fails loudly.
        # The hand-rolled PDF generator below is preserved for emergency CLI debugging only.
        self._export_pdf_via_browser(Path(deck_html_path), pdf_path, plan)
        plan.artifacts["pdf"] = str(pdf_path)
        plan.status = "ready_for_review"
        plan.updated_at = utc_now()
        return plan

    def _export_pdf_via_browser(
        self,
        deck_html_path: Path,
        pdf_out: Path,
        plan: CarouselPlan,
    ) -> None:
        """Render each slide HTML to a 1080x1350 PDF page via headless Chromium.

        Also writes a 540x675 PNG thumbnail per slide (real preview images for
        the dashboard, replacing the generic gray boxes).
        """
        from playwright.sync_api import sync_playwright

        rendered_dir = deck_html_path.parent
        slide_html_paths = sorted(rendered_dir.glob("slide-*.html"))
        if not slide_html_paths:
            raise RuntimeError("no slide-*.html files in rendered directory")

        deck_html = deck_html_path.read_text(encoding="utf-8")
        head_block = ""
        link_match = re.findall(r'<link[^>]+>', deck_html)
        for link in link_match:
            head_block += link + "\n"
        style_match = re.search(r'<style>(.*?)</style>', deck_html, re.DOTALL)
        if style_match:
            head_block += "<style>\n" + style_match.group(1) + "\n</style>"

        per_slide_pdfs: list[bytes] = []
        png_paths: list[Path] = []
        with sync_playwright() as pw:
            # Resolve Chromium executable. Some environments fail Playwright's
            # internal existence check even when the binary is present on disk
            # (path discovery via LOCALAPPDATA, subprocess env inheritance, etc.).
            # We try the SDK-reported path first; if the binary exists, pin it
            # explicitly so launch() bypasses re-discovery. Falls back to the
            # default behaviour if no path can be confirmed.
            launch_kwargs: dict = {"headless": True}
            # Prefer the headless_shell binary (what Playwright's default headless
            # mode uses on Windows). Pinning the path bypasses an environment-
            # dependent discovery bug that hits some users on Windows where
            # LOCALAPPDATA isn't visible to the uvicorn subprocess.
            import os as _os
            candidates: list[Path] = []
            roots_to_try: list[Path] = []

            # Linux/Render: check PLAYWRIGHT_BROWSERS_PATH first, then ~/.cache
            pw_browsers = _os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
            if pw_browsers:
                roots_to_try.append(Path(pw_browsers))
            home = _os.environ.get("HOME", "")
            if home:
                roots_to_try.append(Path(home) / ".cache" / "ms-playwright")

            # Windows: check LOCALAPPDATA and common fallbacks
            for env_var in ("LOCALAPPDATA", "USERPROFILE"):
                env_val = _os.environ.get(env_var, "")
                if env_val:
                    if env_var == "LOCALAPPDATA":
                        roots_to_try.append(Path(env_val) / "ms-playwright")
                    else:
                        roots_to_try.append(Path(env_val) / "AppData" / "Local" / "ms-playwright")
            try:
                roots_to_try.append(Path.home() / "AppData" / "Local" / "ms-playwright")
            except Exception:  # noqa: BLE001
                pass

            seen: set[str] = set()
            for ms in roots_to_try:
                key = str(ms).lower()
                if key in seen or not ms.is_dir():
                    continue
                seen.add(key)
                # Linux binaries
                shells_linux = sorted(ms.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"), reverse=True)
                chromes_linux = sorted(ms.glob("chromium-*/chrome-linux64/chrome"), reverse=True)
                # Windows binaries
                shells_win = sorted(ms.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"), reverse=True)
                chromes_win = sorted(ms.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)
                candidates.extend(shells_linux)
                candidates.extend(chromes_linux)
                candidates.extend(shells_win)
                candidates.extend(chromes_win)
            for candidate in candidates:
                if candidate.is_file():
                    launch_kwargs["executable_path"] = str(candidate)
                    break
            diag_msg = (
                f"Playwright launch: roots_tried={len(roots_to_try)} "
                f"candidates={len(candidates)} "
                f"exec={launch_kwargs.get('executable_path', '<default>')}"
            )
            log.info(diag_msg)
            try:
                browser = pw.chromium.launch(**launch_kwargs)
            except Exception as launch_exc:
                # Re-raise with diagnostic info so it shows in the dashboard error message
                raise RuntimeError(
                    f"{launch_exc} | DIAG: {diag_msg} | "
                    f"roots: {[str(r) for r in roots_to_try]}"
                ) from launch_exc
            try:
                for slide_html_file in slide_html_paths:
                    slide_inner = slide_html_file.read_text(encoding="utf-8")
                    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>slide</title>
{head_block}
<style>
  html, body {{ margin: 0; padding: 0; background: transparent; width: 1080px; height: 1350px; }}
  body {{ display: block; overflow: hidden; }}
  body > .slide {{ display: block; }}
</style>
</head>
<body>
{slide_inner}
</body>
</html>"""
                    tmp_html = slide_html_file.with_suffix(".pdfpage.html")
                    tmp_html.write_text(page_html, encoding="utf-8")

                    page = browser.new_page(viewport={"width": 1080, "height": 1350})
                    # 'load' fires when the page has loaded all resources
                    # (incl. Google Fonts) but doesn't wait for hanging XHRs
                    # like 'networkidle' does. 60s buffer for slow font CDNs.
                    page.goto(tmp_html.as_uri(), wait_until="load", timeout=60000)
                    # Tiny extra buffer to give @font-face declarations time to swap
                    page.wait_for_timeout(400)

                    # 1) Real PNG thumbnail (600x750 — half the canvas, fits the dashboard grid)
                    png_path = slide_html_file.with_suffix(".png")
                    png_path.write_bytes(
                        page.screenshot(
                            type="png",
                            full_page=False,
                            clip={"x": 0, "y": 0, "width": 1080, "height": 1350},
                        )
                    )
                    png_paths.append(png_path)

                    # 2) Per-slide PDF page
                    pdf_bytes = page.pdf(
                        width="1080px",
                        height="1350px",
                        margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
                        print_background=True,
                        prefer_css_page_size=False,
                    )
                    per_slide_pdfs.append(pdf_bytes)
                    page.close()
                    try:
                        tmp_html.unlink()
                    except OSError:
                        pass
            finally:
                browser.close()

        if not per_slide_pdfs:
            raise RuntimeError("no PDF pages were produced")

        merged = self._merge_pdf_pages(per_slide_pdfs)
        pdf_out.write_bytes(merged)

        # Update preview manifest to point at the real PNG thumbnails
        if png_paths:
            preview_manifest = rendered_dir / "preview-manifest.txt"
            preview_manifest.write_text(
                "\n".join(str(p) for p in png_paths),
                encoding="utf-8",
            )
            plan.artifacts["preview_manifest"] = str(preview_manifest)
            plan.artifacts["first_preview"] = str(png_paths[0])

    def _merge_pdf_pages(self, pdf_pages: list[bytes]) -> bytes:
        """Merge a list of single-page PDFs into one multi-page PDF.

        Prefers `pypdf` if available; falls back to writing the first page only
        (a single-page PDF is still better than a broken merge).
        """
        try:
            from pypdf import PdfWriter, PdfReader
            import io

            writer = PdfWriter()
            for pdf_bytes in pdf_pages:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    writer.add_page(page)
            buf = io.BytesIO()
            writer.write(buf)
            return buf.getvalue()
        except ImportError:
            # Last resort: return the first page only
            return pdf_pages[0]

    def _render_slide_html(
        self,
        html: str,
        slot_values: dict[str, str],
        rendered_dir: Path,
    ) -> str:
        rendered = html
        for name, value in slot_values.items():
            replacement = value
            if name.startswith("image_") and self._is_image_asset(value):
                replacement = (
                    f'<img src="{self._to_artifact_src(value, rendered_dir)}" alt="{name}" '
                    'style="width:100%;height:100%;object-fit:cover;border-radius:24px;">'
                )
            rendered = rendered.replace(f"{{{{{name}}}}}", replacement)
        leftovers = set(re.findall(r"{{\s*([a-zA-Z0-9_]+)\s*}}", rendered))
        for placeholder in leftovers:
            rendered = rendered.replace(f"{{{{{placeholder}}}}}", "")
        return rendered

    def _resolve_variant_html(self, template: TemplatePackage, role: str) -> str:
        role_schema = template.manifest.slide_roles.get(role)
        if role_schema and role_schema.render_variant:
            return template.render_variants.get(role_schema.render_variant, template.render_html)
        if role == "cover" and "cover" in template.render_variants:
            return template.render_variants["cover"]
        if role != "cover" and "content" in template.render_variants:
            return template.render_variants["content"]
        return template.render_html

    def _wrap_deck_html(self, slides: list[str], styles_css: str, head_html: str) -> str:
        slides_markup = "\n".join(
            f'<section class="deck-slide">{slide}</section>' for slide in slides
        )
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Carousel Deck</title>
  {head_html}
  <style>
    body {{ margin: 0; background: #0A0A0A; display: grid; gap: 24px; padding: 24px; }}
    .deck-slide {{ background: #FFFFFF; width: fit-content; }}
    {styles_css}
  </style>
</head>
<body>
  {slides_markup}
</body>
</html>
"""

    def _preview_svg(
        self,
        *,
        index: int,
        title: str,
        body: str,
        cta: str,
        page_number: str,
        full_slide: str | None,
    ) -> str:
        if full_slide:
            full_slide_path = Path(full_slide)
            if full_slide_path.suffix.lower() == ".svg":
                return full_slide_path.read_text("utf-8")
            return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350">
  <rect width="1080" height="1350" fill="#F8FAFC"/>
  <rect x="40" y="40" width="1000" height="1270" rx="24" fill="#FFFFFF" stroke="#DDE1E6" stroke-width="4"/>
  <text x="88" y="148" font-family="Arial" font-size="28" fill="#0A66C2">Generated image slide {index:02d}</text>
  <text x="88" y="276" font-family="Arial" font-size="78" font-weight="700" fill="#0A0A0A">{escape(title[:55])}</text>
  <text x="88" y="420" font-family="Arial" font-size="32" fill="#434649">{escape(full_slide_path.name)}</text>
</svg>"""
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="1350" viewBox="0 0 1080 1350">
  <rect width="1080" height="1350" fill="#FFFFFF"/>
  <rect x="40" y="40" width="1000" height="1270" rx="24" fill="#FFFFFF" stroke="#DDE1E6" stroke-width="4"/>
  <text x="88" y="148" font-family="Arial" font-size="28" fill="#0A66C2">Preview slide {index:02d}</text>
  <text x="88" y="276" font-family="Arial" font-size="78" font-weight="700" fill="#0A0A0A">{escape(title[:55])}</text>
  <text x="88" y="420" font-family="Arial" font-size="32" fill="#434649">{escape(body[:260])}</text>
  <text x="88" y="1220" font-family="Arial" font-size="28" fill="#0A66C2">{escape(cta[:70])}</text>
  <text x="950" y="1220" font-family="Arial" font-size="24" fill="#86888A">{escape(page_number)}</text>
</svg>"""

    def _build_pdf(self, plan: CarouselPlan) -> bytes:
        width = 540
        height = 675
        objects: list[str] = []
        page_ids: list[int] = []
        font_regular_obj_id = 3
        font_bold_obj_id = 4

        def add_object(content: str) -> int:
            objects.append(content)
            return len(objects)

        add_object("<< /Type /Catalog /Pages 2 0 R >>")
        add_object("<< /Type /Pages /Kids [] /Count 0 >>")
        add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

        for slide in plan.slides:
            page_stream = self._pdf_page_stream(
                slide=slide,
                width=width,
                height=height,
            )
            stream = f"<< /Length {len(page_stream.encode('latin-1', 'replace'))} >>\nstream\n{page_stream}\nendstream"
            content_id = add_object(stream)
            page_obj = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
                f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_regular_obj_id} 0 R /F2 {font_bold_obj_id} 0 R >> >> >>"
            )
            page_ids.append(add_object(page_obj))

        kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
        objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>"

        pdf = "%PDF-1.4\n"
        offsets = [0]
        for index, content in enumerate(objects, start=1):
            offsets.append(len(pdf.encode("latin-1", "replace")))
            pdf += f"{index} 0 obj\n{content}\nendobj\n"
        xref_start = len(pdf.encode("latin-1", "replace"))
        pdf += f"xref\n0 {len(objects) + 1}\n"
        pdf += "0000000000 65535 f \n"
        for offset in offsets[1:]:
            pdf += f"{offset:010d} 00000 n \n"
        pdf += f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF"
        return pdf.encode("latin-1", "replace")

    def _pdf_page_stream(self, *, slide, width: int, height: int) -> str:
        is_cover = slide.role == "cover"
        bg = "0.05 0.05 0.06" if is_cover else "1 1 1"
        panel = "0.09 0.40 0.76" if is_cover else "0.94 0.97 1"
        ink = "1 1 1" if is_cover else "0.07 0.09 0.13"
        muted = "0.82 0.88 0.94" if is_cover else "0.38 0.45 0.55"
        accent = "0.44 0.71 0.98" if is_cover else "0.04 0.40 0.76"

        lines = self._slide_display_lines(slide.slot_values)
        stream: list[str] = [
            f"{bg} rg",
            f"0 0 {width} {height} re f",
            f"{panel} rg",
            "28 618 160 28 re f",
            f"{accent} rg",
            "28 30 484 4 re f",
        ]

        top_label = self._escape_pdf((slide.slot_values.get("top_center") or slide.role.upper())[:60])
        page_number = self._escape_pdf((slide.slot_values.get("page_number") or f"{slide.index:02d}")[:20])
        title = self._escape_pdf(slide.title[:72])

        stream.extend(
            [
                f"{ink} rg",
                "BT",
                "/F1 11 Tf",
                f"1 0 0 1 36 627 Tm",
                f"({top_label}) Tj",
                "ET",
                f"{muted} rg",
                "BT",
                "/F1 10 Tf",
                f"1 0 0 1 476 627 Tm",
                f"({page_number}) Tj",
                "ET",
                f"{ink} rg",
                "BT",
                "/F2 24 Tf",
                f"1 0 0 1 36 560 Tm",
                f"({title}) Tj",
                "ET",
            ]
        )

        y = 510
        for index, line in enumerate(lines[:10]):
            wrapped = self._wrap_pdf_text(line, 38)
            if not wrapped:
                continue
            font = "/F2 15 Tf" if index < 2 else "/F1 13 Tf"
            color = ink if index < 2 else muted
            stream.append(f"{color} rg")
            stream.append("BT")
            stream.append(font)
            stream.append(f"1 0 0 1 36 {y} Tm")
            for line_index, part in enumerate(wrapped):
                if line_index == 0:
                    stream.append(f"({self._escape_pdf(part)}) Tj")
                else:
                    stream.append("0 -30 Td")
                    stream.append(f"({self._escape_pdf(part)}) Tj")
            stream.append("ET")
            y -= 42 + max(0, len(wrapped) - 1) * 20
            if y < 110:
                break

        cta = self._extract_cta_text(slide.slot_values)
        if cta:
            cta_text = self._escape_pdf(cta[:90])
            stream.extend(
                [
                    f"{accent} rg",
                    "BT",
                    "/F2 14 Tf",
                    "1 0 0 1 36 54 Tm",
                    f"({cta_text}) Tj",
                    "ET",
                ]
            )

        handle = self._escape_pdf((slide.slot_values.get("brand_handle") or "@noxlin")[:60])
        stream.extend(
            [
                f"{muted} rg",
                "BT",
                "/F1 10 Tf",
                "1 0 0 1 392 54 Tm",
                f"({handle}) Tj",
                "ET",
            ]
        )
        return "\n".join(stream)

    def _slide_display_lines(self, slot_values: dict[str, str]) -> list[str]:
        ignored = {
            "page_number",
            "brand_handle",
            "generated_full_slide",
        }
        preferred_order = [
            "pill_tag",
            "hero_prefix",
            "hero_gradient",
            "body",
            "body_html",
            "body_lead",
            "body_support",
            "cover_title",
            "cover_subtitle",
            "content_title",
            "content_title_html",
            "content_body_html",
            "support_text_html",
            "subline_main",
            "subline_offset",
            "mid_pill",
            "hero_sub_prefix",
            "hero_sub_highlight",
            "feature_1_html",
            "feature_2_html",
            "feature_3_html",
            "article_html",
        ]
        lines: list[str] = []
        seen: set[str] = set()
        for key in preferred_order + [key for key in slot_values.keys() if key not in preferred_order]:
            if key in ignored or key in seen:
                continue
            seen.add(key)
            raw = slot_values.get(key, "")
            text = self._clean_pdf_text(raw)
            if text:
                lines.append(text)
        return lines

    def _extract_cta_text(self, slot_values: dict[str, str]) -> str:
        for key in ("cta", "cta_label", "mid_pill", "hero_sub_highlight"):
            value = self._clean_pdf_text(slot_values.get(key, ""))
            if value:
                return value
        return ""

    def _clean_pdf_text(self, value: str) -> str:
        text = html.unescape(str(value or ""))
        text = re.sub(r"<br\s*/?>", " | ", text, flags=re.IGNORECASE)
        text = re.sub(r"</p\s*>", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = " ".join(text.split())
        return text

    def _wrap_pdf_text(self, text: str, max_chars: int) -> list[str]:
        if not text:
            return []
        words = text.split()
        if not words:
            return []
        lines = [words[0]]
        for word in words[1:]:
            candidate = f"{lines[-1]} {word}"
            if len(candidate) <= max_chars:
                lines[-1] = candidate
            else:
                lines.append(word)
        return lines

    def _pdf_text_block(self, title: str, body: str, page_number: str) -> str:
        lines = [title] + [line for line in body.splitlines() if line.strip()] + [page_number]
        sanitized = [self._escape_pdf(line[:90]) for line in lines]
        commands = ["BT", "/F1 30 Tf", "80 1260 Td"]
        current_y = 0
        for line in sanitized:
            commands.append(f"0 {-current_y} Td ({line}) Tj")
            current_y = 46
        commands.append("ET")
        return "\n".join(commands)

    def _escape_pdf(self, value: str) -> str:
        # Transliterate common unicode punctuation to ASCII equivalents
        # so the PDF latin-1 encoder never chokes
        _UNICODE_MAP = str.maketrans({
            "\u2014": "--",   # em dash
            "\u2013": "-",    # en dash
            "\u2018": "'",    # left single quote
            "\u2019": "'",    # right single quote
            "\u201c": '"',    # left double quote
            "\u201d": '"',    # right double quote
            "\u2026": "...",  # ellipsis
            "\u00b7": ".",    # middle dot
            "\u2022": "*",    # bullet
            "\u00e9": "e",    # é
            "\u00e8": "e",    # è
            "\u00e0": "a",    # à
            "\u00fc": "u",    # ü
            "\u00f6": "o",    # ö
            "\u00e4": "a",    # ä
        })
        value = value.translate(_UNICODE_MAP)
        # Strip anything still outside latin-1
        value = value.encode("latin-1", "ignore").decode("latin-1")
        return (
            value.replace("\\", "\\\\")
            .replace("(", "\\(")
            .replace(")", "\\)")
        )

    def _is_image_asset(self, value: str) -> bool:
        return value.lower().endswith((".svg", ".png", ".jpg", ".jpeg", ".webp"))

    def _to_artifact_src(self, value: str, rendered_dir: Path) -> str:
        asset_path = Path(value)
        try:
            relative = asset_path.relative_to(self.artifacts_root)
            return f"/artifacts/{relative.as_posix()}"
        except ValueError:
            pass
        try:
            return asset_path.relative_to(rendered_dir).as_posix()
        except ValueError:
            return value
