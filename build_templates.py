"""
Build all 7 Noxlin templates verbatim from the master design file.
Reads: H:/System Media/Download/noxlin caraousel/Noxlin Carousel Templates.html
Writes: H:/cara/data/templates/{nox-*}/styles.css, head.html, render.html, variants/*.html, template_manifest.json
"""
from __future__ import annotations
import json
import re
from pathlib import Path

DESIGN_PATH = Path(__file__).parent / "Noxlin Carousel Templates.html"
OUT_ROOT = Path(__file__).parent / "app" / "builtin_templates"
DESIGN = DESIGN_PATH.read_text(encoding="utf-8")

# ---------------------------------------------------------------------
# Extract the shared CSS block (root vars + slide system, NO gallery scale)
# ---------------------------------------------------------------------

ROOT_BLOCK = """\
:root {
  --nx-blue: #0A66C2;
  --nx-blue-dark: #004182;
  --nx-blue-light: #70B5F9;
  --nx-blue-tint: #EEF5FF;
  --nx-cream: #F5F2EB;
  --nx-paper: #FAF8F3;
  --nx-white: #FFFFFF;
  --nx-black: #0A0A0A;
  --nx-ink: #111318;
  --nx-text2: #434649;
  --nx-muted: #86888A;
  --nx-border: #E3E1DB;
  --nx-border-cool: #DDE1E6;
  --nx-surface: #F3F6F8;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
.slide {
  width: 1080px; height: 1350px;
  position: relative;
  overflow: hidden;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
.slide * { box-sizing: border-box; }
"""

# Lines 315-1079 of design contain all the .nx-* rules + shared brand/author/arrow/stamp
def extract_block(start_marker: str, end_marker: str) -> str:
    start = DESIGN.find(start_marker)
    end = DESIGN.find(end_marker, start)
    assert start != -1 and end != -1, f"could not find block {start_marker[:40]} -> {end_marker[:40]}"
    return DESIGN[start:end]

SLIDE_SYSTEM_CSS = extract_block(
    "/* Shared Noxlin wordmark */",
    "/* ═══════════════════════════════════════════════════════\n   FOOTER",
)

NOXLIN_OVERRIDES = """
/* ═══════════════════════════════════════════════════════
   NOXLIN OVERRIDES — alignment + readability fixes
   (applied on top of the design CSS, never replacing it)
   ═══════════════════════════════════════════════════════ */

/* 1. Make .nx-arrow flex with content, no more 4-line wrap */
.nx-arrow {
  width: auto;
  min-width: 92px;
  max-width: 280px;
  height: 52px;
  padding: 0 22px;
  white-space: nowrap;
  font-size: 22px;
  gap: 8px;
}

/* 2. Bottom-pill on nox-grad: allow handle to ellipsis if too long */
.nx-grad .bottom-pill {
  font-size: 16px;
  gap: 14px;
  flex-wrap: nowrap;
}
.nx-grad .bottom-pill > span {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 38%;
}
.nx-grad .bottom-pill > span:first-child { max-width: 32%; }
.nx-grad .bottom-pill > span:last-child  { max-width: 22%; }

/* 3. CTA button: never wrap, keep arrow attached */
.nx-cta .cta-button {
  white-space: nowrap;
  max-width: 760px;
}
.nx-cta .cta-button .arr { flex-shrink: 0; }

/* 4. Author name + handle: prevent line wrap that pushes layout */
.nx-author .name,
.nx-author .handle {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 380px;
}

/* 5. Bump small text up for readability (#4) */
.nx-grid.content .three-col .c-b { font-size: 21px; line-height: 1.55; }
.nx-grid.content .three-col .c-num { font-size: 13px; letter-spacing: 0.16em; }
.nx-num .sub  { font-size: 24px; line-height: 1.55; }
.nx-cta .sub  { font-size: 28px; }

/* 6. Hero / headline / quote — REDUCED sizes + word-break safety so even
       a single long word ("revolutionizing", "infrastructure") fits cleanly
       and never crops the right edge. Writer-agent word-length limits keep
       it tight; these CSS rules are the safety net. */
.nx-mono .hero, .nx-mono.content .hero,
.nx-cta .head, .nx-cta.content .head,
.nx-grad .hero,
.nx-paper .hero, .nx-paper.content .hero,
.nx-grid .headline, .nx-grid.content .headline,
.nx-quote .quote, .nx-num .hero {
  overflow-wrap: anywhere;
  word-break: break-word;
  hyphens: none;
  max-width: 920px;     /* leave breathing room — never butt the right edge */
}
.nx-mono .hero            { font-size: 138px; line-height: 0.96; max-width: 880px; }
.nx-mono.content .hero    { font-size: 104px; max-width: 880px; }
.nx-mono .kicker          { margin-top: 260px; }
.nx-mono.content .kicker  { margin-top: 180px; }
.nx-cta .head             { font-size: 92px;  max-width: 880px; }
.nx-cta.content .head     { font-size: 84px;  max-width: 880px; }
.nx-cta .final-chip       { margin-top: 200px; }
.nx-grad .hero            { font-size: 122px; max-width: 920px; }
.nx-paper .hero           { font-size: 96px;  max-width: 880px; }
.nx-paper.content .hero   { font-size: 64px;  max-width: 880px; }
.nx-grid .headline        { font-size: 104px; max-width: 920px; }
.nx-grid.content .headline { font-size: 72px; max-width: 920px; }
.nx-quote .quote          { font-size: 72px;  max-width: 880px; }
.nx-num .hero             { font-size: 64px;  max-width: 880px; }

/* 7. Stamp: don't collide with author block on left */
.nx-stamp { right: 80px; bottom: 22px; max-width: 380px; }
.nx-mono .nx-stamp,
.nx-cta .nx-stamp { bottom: 18px; }

/* 8. nox-paper sub line: cap width so it doesn't overlap the footer */
.nx-paper .sub { max-width: 720px; }

/* 9. nox-quote: ensure attribution rule + text don't overflow */
.nx-quote .attrib { max-width: 880px; flex-wrap: wrap; }

/* 10. Defensive — every slide gets bottom safe area for footer (110px) */
.slide { padding-bottom: 0; }

/* 11. Profile photo support — when author_picture is set, the LinkedIn
       photo covers the avatar circle. If empty, restore gradient + initials. */
.nx-author .av {
  background-size: cover !important;
  background-position: center !important;
  background-repeat: no-repeat !important;
  color: transparent;   /* hide initials when image is present */
  text-shadow: 0 0 6px rgba(0,0,0,0.4);
}
/* When inline url() is empty (no LinkedIn picture), restore design defaults */
.nx-author .av[style*="url('')"],
.nx-author .av[style*='url("")'] {
  background-image: linear-gradient(135deg, var(--nx-blue-light), var(--nx-blue-dark)) !important;
  color: #fff !important;
  text-shadow: none;
}
.nx-brand .nx-mark {
  background-size: cover;
  background-position: center;
}

/* 12. nox-grad user pill — replaces the generic noxlin.com/noxlin pill
       at the bottom. Avatar (with profile pic) + name + handle + page. */
.nx-grad .nx-user-pill {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 10px 14px 10px 10px;
}
.nx-grad .nx-user-pill .nx-user-av {
  width: 44px; height: 44px;
  border-radius: 50%;
  background: rgba(255,255,255,0.18);
  border: 2px solid rgba(255,255,255,0.35);
  background-size: cover;
  background-position: center;
  display: flex; align-items: center; justify-content: center;
  font-family: 'Instrument Serif', serif;
  font-style: italic;
  font-size: 22px;
  color: #fff;
  flex-shrink: 0;
}
.nx-grad .nx-user-pill .nx-user-av[style*="url('')"],
.nx-grad .nx-user-pill .nx-user-av[style*='url("")'] {
  background-image: none !important;
  background: rgba(255,255,255,0.20) !important;
  color: #fff !important;
}
/* When picture IS present, hide the initials so the photo reads cleanly */
.nx-grad .nx-user-pill .nx-user-av:not([style*="url('')"]):not([style*='url("")']) {
  color: transparent;
}
.nx-grad .nx-user-pill .nx-user-name {
  font-family: 'Manrope', sans-serif;
  font-weight: 600;
  font-size: 18px;
  color: #fff;
  margin-right: 4px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 280px;
}
.nx-grad .nx-user-pill .nx-user-handle {
  font-family: 'JetBrains Mono', monospace;
  font-size: 15px;
  color: rgba(255,255,255,0.7);
  flex: 1;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.nx-grad .nx-user-pill .nx-user-page {
  font-family: 'JetBrains Mono', monospace;
  font-size: 16px;
  color: rgba(255,255,255,0.85);
  flex-shrink: 0;
}
.nx-grad .nx-brand-spacer { width: 0; }

/* Top-strip user identity (replaces the old "noxlin" wordmark) */
.nx-user-brand {
  display: inline-flex !important;
  align-items: center !important;
  gap: 12px;
  font-family: 'Manrope', sans-serif;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: -0.005em;
}
.nx-user-brand .nx-mark {
  width: 38px; height: 38px;
  border-radius: 50%;
  background-size: cover !important;
  background-position: center !important;
  display: flex; align-items: center; justify-content: center;
  font-family: 'Instrument Serif', serif;
  font-style: italic;
  font-size: 18px;
  padding-bottom: 0 !important;
}
.nx-user-brand .nx-mark[style*="url('')"],
.nx-user-brand .nx-mark[style*='url("")'] {
  /* No picture set — use the design's blue mark with initials */
  background-image: none !important;
  background: var(--nx-blue) !important;
  color: #fff !important;
}
/* When picture present, hide initials text so photo reads cleanly */
.nx-user-brand .nx-mark:not([style*="url('')"]):not([style*='url("")']) {
  color: transparent;
}
.nx-user-brand .nx-user-name-top {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 280px;
}
/* Dark-bg templates — top text in white */
.nx-mono .nx-user-brand,
.nx-cta .nx-user-brand,
.nx-grad .nx-user-brand { color: #fff; }
.nx-paper .nx-user-brand { color: var(--nx-black); }

/* 13. Bigger small text across all templates — LinkedIn audience readability */
.nx-mono .top                          { font-size: 22px; }   /* was 18 */
.nx-paper .issue                       { font-size: 19px; }   /* was 16 */
.nx-num .top                           { font-size: 22px; }   /* was 20 */
.nx-quote .top                         { font-size: 20px; }   /* was 18 */
.nx-grid .top                          { font-size: 18px; }   /* was 16 */
.nx-grid .grid-body .lead              { font-size: 32px; line-height: 1.5; }
.nx-grid .grid-body .side .label       { font-size: 15px; }
.nx-grid .grid-body .side .stat        { font-size: 96px; }   /* was 88 */
.nx-grid .grid-body .side .statsub     { font-size: 24px; }
/* 3-column content grid — make each column substantially bigger.
   Wider gap, taller titles, bigger body text so even dense topics read clearly. */
.nx-grid.content .three-col            { gap: 36px; margin-top: 80px; }
.nx-grid.content .three-col .col       { padding-top: 26px; border-top-width: 3px; }
.nx-grid.content .three-col .c-num     { font-size: 15px; margin-bottom: 18px; letter-spacing: 0.18em; }
.nx-grid.content .three-col .c-t       { font-size: 38px; line-height: 1.12; margin-bottom: 18px; }
.nx-grid.content .three-col .c-b       { font-size: 24px; line-height: 1.55; }
.nx-grad .top                          { font-size: 20px; }   /* was 18 */
.nx-grad .pre                          { font-size: 27px; }   /* was 24 */
.nx-grad .chip                         { font-size: 17px; padding: 9px 24px; }
.nx-grad.content .stat .lbl            { font-size: 20px; }   /* was 18 */
.nx-grad.content .support              { font-size: 30px; }   /* was 27 */
.nx-cta .top                           { font-size: 20px; }   /* was 18 */
.nx-cta .final-chip                    { font-size: 16px; padding: 9px 20px; }
.nx-cta .sub                           { font-size: 30px; }   /* was 26→28→30 */
.nx-cta .cta-button                    { font-size: 26px; }   /* was 24 */
.nx-author .name                       { font-size: 24px; }   /* was 22 */
.nx-author .handle                     { font-size: 17px; }   /* was 16 */
.nx-stamp                              { font-size: 14px; }   /* was 13 */
.nx-stamp .sp-serif                    { font-size: 21px; }   /* was 19 */
"""

SHARED_CSS = ROOT_BLOCK + "\n" + SLIDE_SYSTEM_CSS + "\n" + NOXLIN_OVERRIDES

# ---------------------------------------------------------------------
# Standard <head> with Google Fonts
# ---------------------------------------------------------------------

HEAD_HTML = """\
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,300;12..96,400;12..96,500;12..96,600;12..96,700;12..96,800&family=Manrope:wght@300;400;500;600;700;800&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;500;600&family=Fraunces:ital,opsz,wght@0,9..144,300;0,9..144,400;0,9..144,600;0,9..144,800;0,9..144,900;1,9..144,300;1,9..144,400;1,9..144,600&display=swap" rel="stylesheet">
"""

# ---------------------------------------------------------------------
# Each template: parse <div class="slide nx-X"> ... </div> blocks
# from the design HTML, then convert design content to {{slot}} placeholders.
# ---------------------------------------------------------------------

def find_slide_block(class_match: str) -> str:
    """Return the HTML of one <div class="slide ..."> block ending at its closing </div>."""
    pattern = re.compile(
        r'<div class="slide ' + re.escape(class_match) + r'"[^>]*>',
    )
    m = pattern.search(DESIGN)
    if not m:
        raise ValueError(f"slide not found: {class_match}")
    start = m.start()
    depth = 0
    i = start
    while i < len(DESIGN):
        if DESIGN.startswith("<div", i):
            depth += 1
            i += 4
        elif DESIGN.startswith("</div>", i):
            depth -= 1
            i += 6
            if depth == 0:
                return DESIGN[start:i]
        else:
            i += 1
    raise ValueError(f"unterminated slide: {class_match}")


# ---------------------------------------------------------------------
# Template definitions: pull HTML, then map design literal text -> {{slot}}
# ---------------------------------------------------------------------

TEMPLATES = [
    {
        "id": "nox-mono",
        "name": "Noxlin Mono",
        "description": "Pitch-black keynote canvas. Bricolage Grotesque hero with one Instrument-Serif italic accent. Type-only — best for hooks, announcements, contrarian takes.",
        "tag": "Keynote · Big statements",
        "cover_class": "nx-mono",
        "content_class": "nx-mono content",
        "background_color": "#0A0A0A",
    },
    {
        "id": "nox-paper",
        "name": "Noxlin Paper",
        "description": "Warm cream canvas, Fraunces display serif, Instrument Serif italic accent. Magazine-editorial feel for founder essays and opinion posts.",
        "tag": "Essays · Founder thinking",
        "cover_class": "nx-paper",
        "content_class": "nx-paper content",
        "background_color": "#F5F2EB",
    },
    {
        "id": "nox-num",
        "name": "Noxlin Big Number",
        "description": "Solid LinkedIn-blue cover with giant Fraunces numeral. Content slides invert to white with tinted numeral watermark. Perfect for list posts.",
        "tag": "Lists · 'N reasons' posts",
        "cover_class": "nx-num cover",
        "content_class": "nx-num content",
        "background_color": "#0A66C2",
    },
    {
        "id": "nox-quote",
        "name": "Noxlin Quote",
        "description": "Pull-quote slides with giant Fraunces quotation glyph. Light cream variant + dark black variant. Max 12 words.",
        "tag": "Quote cards · Reframes",
        "cover_class": "nx-quote",
        "content_class": "nx-quote content",
        "background_color": "#FAF8F3",
    },
    {
        "id": "nox-grid",
        "name": "Noxlin Grid",
        "description": "Swiss-grid discipline. Monospace meta strip, 12-column lead/side cover, 3-column breakdown content. For frameworks and how-it-works.",
        "tag": "Data · Frameworks",
        "cover_class": "nx-grid",
        "content_class": "nx-grid content",
        "background_color": "#FFFFFF",
    },
    {
        "id": "nox-grad",
        "name": "Noxlin Gradient",
        "description": "Atmospheric Noxlin-blue gradient with grain. Mixed-weight display type (thin + bold + italic-serif). Stat-mode content slide.",
        "tag": "Thought leadership · Stats",
        "cover_class": "nx-grad",
        "content_class": "nx-grad content",
        "background_color": "#0A66C2",
    },
    {
        "id": "nox-cta",
        "name": "Noxlin Swipe",
        "description": "Final closing slide with single CTA pill + circled-arrow button. Dark variant for the final close, light variant for mid-deck swipe prompts.",
        "tag": "Closing slide · CTA",
        "cover_class": "nx-cta",
        "content_class": "nx-cta content",
        "background_color": "#0A0A0A",
    },
]

# ---------------------------------------------------------------------
# Slot-fill recipes: replace literal design text with {{placeholders}}
# (uses a recipe per template so we don't accidentally overwrite the wrong text)
# ---------------------------------------------------------------------

def _replace_top_brand_with_user(html: str) -> str:
    """Swap the design's hard-coded <div class="nx-brand ...">noxlin</div>
    badge in the top strip for the user's avatar + name. Backs the avatar
    with the LinkedIn profile picture (if available); falls back to initials.
    Operates on whichever variant of nx-brand is present (ghost/light/plain).
    """
    return re.sub(
        r'<div class="nx-brand[^"]*"><div class="nx-mark">[^<]*</div>[^<]*</div>',
        '<div class="nx-brand ghost nx-user-brand">'
        '<div class="nx-mark" style="background-image:url(\'{{author_picture}}\')">{{author_initial}}</div>'
        '<span class="nx-user-name-top">{{author_name}}</span>'
        '</div>',
        html, count=1,
    )


def slotify_mono_cover(html: str) -> str:
    h = _replace_top_brand_with_user(html)
    h = h.replace(">01 / 07<", ">{{page_number}}<")
    h = h.replace("— A LINKEDIN GROWTH SYSTEM", "{{kicker}}")
    h = h.replace("Stop <em>posting</em>.<br>Start growing.", "{{hero}}")
    h = h.replace(">N<", ">{{author_initial}}<", 1)  # nx-mark
    h = h.replace(">N<", ">{{author_initial}}<", 1)  # nx-author av
    h = h.replace(">Noxlin<", ">{{author_name}}<")
    h = h.replace(">@noxlin<", ">{{author_handle}}<")
    h = h.replace("swipe →", "{{swipe_label}}")
    return h

def slotify_mono_content(html: str) -> str:
    h = _replace_top_brand_with_user(html)
    h = h.replace(">02 / 07<", ">{{page_number}}<")
    h = h.replace("— THE INSIGHT", "{{kicker}}")
    h = h.replace("You don't<br>need more <em>tools</em>.", "{{hero}}")
    h = h.replace("You need a <b>system</b> that takes a raw idea and returns a month of content, captions and scheduled posts — without asking you to learn anything.", "{{support}}")
    h = h.replace(">N<", ">{{author_initial}}<", 1)
    return h

def slotify_paper_cover(html: str) -> str:
    h = _replace_top_brand_with_user(html)
    h = h.replace("<b>Essay № 07</b>", "<b>{{issue_label}}</b>")
    h = h.replace("On LinkedIn growth", "{{issue_topic}}")
    h = h.replace("April 2026", "{{issue_date}}")
    h = h.replace("A note on", "{{hero_intro}}")
    h = h.replace("Building a brand you don't have time for.", "{{hero}}")
    h = h.replace('The myth of "one more founder who posts every day" — and the system that replaced it.', "{{sub}}")
    h = h.replace(">N<", ">{{author_initial}}<", 2)
    h = h.replace(">Noxlin<", ">{{author_name}}<")
    h = h.replace("@noxlin · 01 / 06", "{{author_handle}} · {{page_number}}")
    h = h.replace("→", "{{swipe_label}}", 1)
    return h

def slotify_paper_content(html: str) -> str:
    h = _replace_top_brand_with_user(html)
    h = h.replace("<b>Essay № 07</b>", "<b>{{issue_label}}</b>")
    h = h.replace("Chapter one", "{{issue_chapter}}")
    h = h.replace("You don't need more <em>time</em>.<br>You need a system.", "{{hero}}")
    # Replace the body — paragraphs are templated
    body_open = h.find('<div class="body">')
    body_close = h.find("</div>", body_open) + len("</div>")
    h = h[:body_open] + '<div class="body">{{body_html}}</div>' + h[body_close:]
    h = h.replace(">N<", ">{{author_initial}}<", 1)
    return h

def slotify_num_cover(html: str) -> str:
    h = html
    h = h.replace(">noxlin.com<", ">{{brand_site}}<")
    h = h.replace(">01 / 06<", ">{{page_number}}<")
    h = h.replace('<div class="numeral">5</div>', '<div class="numeral">{{numeral}}</div>')
    h = h.replace("Reasons your LinkedIn <em>stopped</em> growing.", "{{hero}}")
    h = h.replace("And the fix for each — based on 2M posts analysed by Noxlin.", "{{sub}}")
    h = h.replace(">N<", ">{{author_initial}}<", 1)
    h = h.replace(">Noxlin<", ">{{author_name}}<")
    h = h.replace(">@noxlin<", ">{{author_handle}}<")
    return h

def slotify_num_content(html: str) -> str:
    h = html
    h = h.replace(">noxlin.com<", ">{{brand_site}}<")
    h = h.replace(">02 / 06<", ">{{page_number}}<")
    h = h.replace('<div class="numeral">1</div>', '<div class="numeral">{{numeral}}</div>')
    h = h.replace("You post in <em>bursts</em>, then disappear.", "{{hero}}")
    h = h.replace("LinkedIn rewards frequency consistency far more than quality spikes. A steady 3-posts-a-week account outgrows a 10-post binge every time.", "{{sub}}")
    h = h.replace(">N<", ">{{author_initial}}<", 1)
    h = h.replace(">Noxlin<", ">{{author_name}}<")
    h = h.replace(">@noxlin<", ">{{author_handle}}<")
    return h

def slotify_quote_cover(html: str) -> str:
    h = html
    h = h.replace("— Pull-quote · Essay № 07", "{{context_label}}")
    h = h.replace(">04 / 06<", ">{{page_number}}<")
    h = h.replace("Consistency is a <em>scheduling</em> problem,<br>not a creative one.", "{{quote}}")
    h = h.replace("Noxlin — <b>On LinkedIn growth</b>", "{{author_name}} — <b>{{attribution_topic}}</b>")
    return h

def slotify_quote_content(html: str) -> str:
    h = html
    h = h.replace("— Pull-quote · Essay № 07", "{{context_label}}")
    h = h.replace(">05 / 06<", ">{{page_number}}<")
    h = h.replace("People don't want <em>tools</em>.<br>They want outcomes.", "{{quote}}")
    h = h.replace("Noxlin — <b>Founding principle</b>", "{{author_name}} — <b>{{attribution_topic}}</b>")
    return h

def slotify_grid_cover(html: str) -> str:
    h = html
    h = h.replace("NOXLIN / <b>SYSTEM</b>", "{{section_label}}")
    h = h.replace(">03 — HOW IT WORKS<", ">{{page_label}}<")
    h = h.replace(">PAGE 01 / 05<", ">PAGE {{page_number}}<")
    h = h.replace("— The pipeline", "{{eyebrow}}")
    h = h.replace("Idea in.<br>Calendar <em>out</em>.", "{{headline}}")
    h = h.replace("Noxlin turns one raw idea into <b>30 days of content</b> — written, designed, captioned and scheduled — without you opening a single tool.", "{{lead_text}}")
    h = h.replace("— Output", "{{stat_label}}")
    h = h.replace('<div class="stat">30</div>', '<div class="stat">{{stat_number}}</div>')
    h = h.replace("posts, designed and scheduled in a single click", "{{stat_sub}}")
    h = h.replace(">N<", ">{{author_initial}}<", 1)
    h = h.replace(">Noxlin<", ">{{author_name}}<")
    h = h.replace(">@noxlin<", ">{{author_handle}}<")
    h = h.replace(">noxlin.com<", ">{{brand_site}}<")
    return h

def slotify_grid_content(html: str) -> str:
    h = html
    h = h.replace("NOXLIN / <b>SYSTEM</b>", "{{section_label}}")
    h = h.replace(">03 — HOW IT WORKS<", ">{{page_label}}<")
    h = h.replace(">PAGE 03 / 05<", ">PAGE {{page_number}}<")
    h = h.replace("— Three layers, one pipeline", "{{eyebrow}}")
    h = h.replace("The system, <em>simplified</em>.", "{{headline}}")
    h = h.replace("01 — INPUT", "{{c1_num}}")
    h = h.replace("You describe the problem.", "{{c1_title}}")
    h = h.replace("One sentence is enough. Niche, audience and tone are inferred — you don't configure anything.", "{{c1_body}}")
    h = h.replace("02 — ENGINE", "{{c2_num}}")
    h = h.replace("Noxlin writes & designs.", "{{c2_title}}")
    h = h.replace("AI drafts the hooks, structures the carousel, writes the caption, and renders every slide to brand.", "{{c2_body}}")
    h = h.replace("03 — DISTRIBUTION", "{{c3_num}}")
    h = h.replace("It posts itself.", "{{c3_title}}")
    h = h.replace("Your calendar fills at the right times, on the right days, across the platforms that matter.", "{{c3_body}}")
    h = h.replace(">N<", ">{{author_initial}}<", 1)
    h = h.replace(">Noxlin<", ">{{author_name}}<")
    h = h.replace(">@noxlin<", ">{{author_handle}}<")
    h = h.replace(">noxlin.com<", ">{{brand_site}}<")
    return h

def slotify_grad_cover(html: str) -> str:
    """nox-grad cover: drop top-left noxlin badge, put user info in the
    bottom-pill (avatar + name + handle), keep page counter on the right."""
    h = html
    # Remove the redundant top-left noxlin wordmark — chip + page counter remain
    h = re.sub(
        r'<div class="nx-brand ghost"><div class="nx-mark">[^<]*</div>[^<]*</div>',
        '<div class="nx-brand-spacer"></div>',
        h, count=1,
    )
    h = h.replace(">LINKEDIN GROWTH<", ">{{chip_label}}<")
    h = h.replace('<div class="page-c">1</div>', '<div class="page-c">{{page_number}}</div>')
    h = h.replace("Every time you skip posting, someone else in your niche gets the attention that should have been yours.", "{{pre_text}}")
    h = h.replace('<span class="thin">Content</span>', '<span class="thin">{{hero_thin}}</span>')
    h = h.replace('<span class="bold">Compounds</span>', '<span class="bold">{{hero_bold}}</span>')
    h = h.replace("<em>daily.</em>", "<em>{{hero_italic}}</em>")
    # Rewrite the bottom-pill so it shows the USER (avatar + name + handle),
    # not the generic noxlin.com/noxlin/page.
    h = re.sub(
        r'<div class="bottom-pill">.*?</div>\s*</div>\s*$',
        (
            '<div class="bottom-pill nx-user-pill">'
            '<span class="nx-user-av" style="background-image:url(\'{{author_picture}}\')">{{author_initial}}</span>'
            '<span class="nx-user-name">{{author_name}}</span>'
            '<span class="nx-user-handle">{{author_handle}}</span>'
            '<span class="nx-user-page">{{page_label}}</span>'
            '</div>\n        </div>'
        ),
        h, count=1, flags=re.DOTALL,
    )
    return h

def slotify_grad_content(html: str) -> str:
    h = html
    h = re.sub(
        r'<div class="nx-brand ghost"><div class="nx-mark">[^<]*</div>[^<]*</div>',
        '<div class="nx-brand-spacer"></div>',
        h, count=1,
    )
    h = h.replace(">THE NUMBERS<", ">{{chip_label}}<")
    h = h.replace('<div class="page-c">3</div>', '<div class="page-c">{{page_number}}</div>')
    h = h.replace('<div class="big">40×</div>', '<div class="big">{{stat_big}}</div>')
    h = h.replace('<div class="unit">more opportunities</div>', '<div class="unit">{{stat_unit}}</div>')
    h = h.replace("— LinkedIn Executive Report, 2024", "{{stat_label}}")
    h = h.replace("Executives with a <b>complete personal brand</b> receive 40× more inbound opportunities than those who stay silent on the platform.", "{{support}}")
    h = re.sub(
        r'<div class="bottom-pill">.*?</div>\s*</div>\s*$',
        (
            '<div class="bottom-pill nx-user-pill">'
            '<span class="nx-user-av" style="background-image:url(\'{{author_picture}}\')">{{author_initial}}</span>'
            '<span class="nx-user-name">{{author_name}}</span>'
            '<span class="nx-user-handle">{{author_handle}}</span>'
            '<span class="nx-user-page">{{page_label}}</span>'
            '</div>\n        </div>'
        ),
        h, count=1, flags=re.DOTALL,
    )
    return h

def slotify_cta_cover(html: str) -> str:
    h = _replace_top_brand_with_user(html)
    h = h.replace("07 / 07 · END", "{{page_number}}")
    h = h.replace("YOUR TURN", "{{chip_label}}")
    h = h.replace("Let Noxlin <em>handle</em> your LinkedIn.", "{{head}}")
    h = h.replace("Describe the problem. Get a <b>full month of content, designed and scheduled</b> — without learning another tool.", "{{sub}}")
    h = h.replace("Try Noxlin free", "{{cta_label}}")
    h = h.replace(">N<", ">{{author_initial}}<", 2)
    h = h.replace(">Noxlin<", ">{{author_name}}<")
    h = h.replace("@noxlin · noxlin.com", "{{author_handle}}")
    h = h.replace("FOLLOW FOR MORE", "{{footer_label}}")
    return h

def slotify_cta_content(html: str) -> str:
    h = _replace_top_brand_with_user(html)
    h = h.replace("04 / 07 · PAUSE", "{{page_number}}")
    h = h.replace("HALFWAY MARK", "{{chip_label}}")
    h = h.replace("Still with <em>us</em>?<br>Good.", "{{head}}")
    h = h.replace("The <b>three slides ahead</b> are the ones most readers screenshot. Save this post now — you'll want to come back.", "{{sub}}")
    h = h.replace("Keep swiping", "{{cta_label}}")
    h = h.replace(">N<", ">{{author_initial}}<", 2)
    h = h.replace(">Noxlin<", ">{{author_name}}<")
    h = h.replace("@noxlin · noxlin.com", "{{author_handle}}")
    h = h.replace("SAVE FOR LATER", "{{footer_label}}")
    return h

SLOTIFIERS = {
    ("nox-mono", "cover"):    slotify_mono_cover,
    ("nox-mono", "content"):  slotify_mono_content,
    ("nox-paper", "cover"):   slotify_paper_cover,
    ("nox-paper", "content"): slotify_paper_content,
    ("nox-num", "cover"):     slotify_num_cover,
    ("nox-num", "content"):   slotify_num_content,
    ("nox-quote", "cover"):   slotify_quote_cover,
    ("nox-quote", "content"): slotify_quote_content,
    ("nox-grid", "cover"):    slotify_grid_cover,
    ("nox-grid", "content"):  slotify_grid_content,
    ("nox-grad", "cover"):    slotify_grad_cover,
    ("nox-grad", "content"):  slotify_grad_content,
    ("nox-cta", "cover"):     slotify_cta_cover,
    ("nox-cta", "content"):   slotify_cta_content,
}

# ---------------------------------------------------------------------
# Slot definitions per template (max chars, mode)
# ---------------------------------------------------------------------

def slot(name: str, max_chars: int, required: bool = False) -> dict:
    return {
        "name": name,
        "slot_type": "text",
        "required": required,
        "max_chars": max_chars,
        "mode": "deterministic",
        "prompt_role": None,
    }

_STAMP_SLOTS = [
    slot("stamp_brand", 24), slot("stamp_site", 32),
    # Universal LinkedIn-OIDC-derived slots, present on every template
    slot("author_picture", 600),  # URL — long max for CDN paths
]

SLOTS_BY_TEMPLATE = {
    "nox-mono": _STAMP_SLOTS + [
        slot("brand_name", 24), slot("brand_site", 32), slot("page_number", 12, True),
        slot("kicker", 64, True), slot("hero", 200, True), slot("support", 360),
        slot("author_initial", 4), slot("author_name", 40), slot("author_handle", 40),
        slot("swipe_label", 24),
    ],
    "nox-paper": _STAMP_SLOTS + [
        slot("brand_name", 24), slot("page_number", 12, True),
        slot("issue_label", 32), slot("issue_topic", 60), slot("issue_date", 32), slot("issue_chapter", 32),
        slot("hero_intro", 32), slot("hero", 200, True), slot("sub", 240),
        slot("body_html", 1200),
        slot("author_initial", 4), slot("author_name", 40), slot("author_handle", 60),
        slot("swipe_label", 24),
    ],
    "nox-num": _STAMP_SLOTS + [
        slot("brand_site", 32), slot("page_number", 12, True),
        slot("numeral", 6, True), slot("hero", 200, True), slot("sub", 360),
        slot("author_initial", 4), slot("author_name", 40), slot("author_handle", 40),
    ],
    "nox-quote": _STAMP_SLOTS + [
        slot("page_number", 12, True), slot("context_label", 60),
        slot("quote", 180, True), slot("author_name", 40), slot("attribution_topic", 60),
    ],
    "nox-grid": _STAMP_SLOTS + [
        slot("brand_site", 32), slot("page_number", 12, True),
        slot("section_label", 48), slot("page_label", 48),
        slot("eyebrow", 64), slot("headline", 180, True), slot("lead_text", 360),
        slot("stat_label", 32), slot("stat_number", 12), slot("stat_sub", 120),
        slot("c1_num", 32), slot("c1_title", 64), slot("c1_body", 240),
        slot("c2_num", 32), slot("c2_title", 64), slot("c2_body", 240),
        slot("c3_num", 32), slot("c3_title", 64), slot("c3_body", 240),
        slot("author_initial", 4), slot("author_name", 40), slot("author_handle", 40),
    ],
    "nox-grad": _STAMP_SLOTS + [
        slot("brand_name", 24), slot("brand_site", 32), slot("brand_handle", 40),
        slot("page_number", 8), slot("page_label", 16),
        slot("chip_label", 32),
        slot("pre_text", 240),
        slot("hero_thin", 32), slot("hero_bold", 32), slot("hero_italic", 32),
        slot("stat_big", 12), slot("stat_unit", 32), slot("stat_label", 60),
        slot("support", 360),
        # User identity (now lives in the bottom-pill instead of "noxlin.com / @noxlin")
        slot("author_initial", 4), slot("author_name", 60), slot("author_handle", 60),
    ],
    "nox-cta": _STAMP_SLOTS + [
        slot("brand_name", 24), slot("page_number", 32),
        slot("chip_label", 32),
        slot("head", 200, True), slot("sub", 360),
        slot("cta_label", 40),
        slot("author_initial", 4), slot("author_name", 40), slot("author_handle", 60),
        slot("footer_label", 32),
    ],
}

# All slot names every role gets (varies by template)
def role_schema(template_id: str) -> dict[str, dict]:
    slot_names = [s["name"] for s in SLOTS_BY_TEMPLATE[template_id]]
    return {
        "cover": {
            "role": "cover",
            "description": "Opening hook slide for this template.",
            "slots": slot_names,
            "render_variant": "cover",
        },
        "insight": {
            "role": "insight",
            "description": "Insight or reframe slide.",
            "slots": slot_names,
            "render_variant": "content",
        },
        "problem": {
            "role": "problem",
            "description": "Pain point slide.",
            "slots": slot_names,
            "render_variant": "content",
        },
        "framework": {
            "role": "framework",
            "description": "Framework or principle slide.",
            "slots": slot_names,
            "render_variant": "content",
        },
        "cta": {
            "role": "cta",
            "description": "Closing slide.",
            "slots": slot_names,
            "render_variant": "content",
        },
    }

# ---------------------------------------------------------------------
# WRITE EVERYTHING
# ---------------------------------------------------------------------

def write_template(t: dict) -> None:
    out_dir = OUT_ROOT / t["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "variants").mkdir(parents=True, exist_ok=True)

    # 1. styles.css — full slide system shared by every template
    (out_dir / "styles.css").write_text(SHARED_CSS, encoding="utf-8")

    # 2. head.html — Google Fonts
    (out_dir / "head.html").write_text(HEAD_HTML, encoding="utf-8")

    # 3. variants/cover.html and variants/content.html — extracted + slotified
    cover_html = find_slide_block(t["cover_class"])
    content_html = find_slide_block(t["content_class"])

    cover_slot = SLOTIFIERS[(t["id"], "cover")](cover_html)
    content_slot = SLOTIFIERS[(t["id"], "content")](content_html)

    # Inject background-image:url('{{author_picture}}') into the .nx-author .av
    # element so the LinkedIn profile photo backs the avatar (initials fallback).
    # Use a lambda to avoid re.sub's special-character handling in the replacement.
    AV_REPLACEMENT = (
        '<div class="av" style="background-image:url(&apos;{{author_picture}}&apos;)">'
        '{{author_initial}}</div>'
    )
    def _wire_author_av(slide_html: str) -> str:
        return re.sub(
            r'<div class="av">\{\{author_initial\}\}</div>',
            lambda m: AV_REPLACEMENT,
            slide_html,
        )
    cover_slot = _wire_author_av(cover_slot)
    content_slot = _wire_author_av(content_slot)

    # Inject the .nx-stamp "CRAFTED BY Noxlin · noxlin.com" branding before </div>
    # of the slide root, so every template carries the unified Noxlin attribution.
    stamp_markup = (
        '<div class="nx-stamp">'
        '<span class="sp-dot"></span>'
        'CRAFTED BY <span class="sp-serif">{{stamp_brand}}</span>'
        ' · {{stamp_site}}'
        '</div>'
    )

    def _inject_stamp(slide_html: str) -> str:
        # Insert before the final </div> of the outer <div class="slide ...">
        idx = slide_html.rfind("</div>")
        if idx == -1:
            return slide_html
        return slide_html[:idx] + "\n          " + stamp_markup + "\n        " + slide_html[idx:]

    cover_slot = _inject_stamp(cover_slot)
    content_slot = _inject_stamp(content_slot)

    (out_dir / "variants" / "cover.html").write_text(cover_slot, encoding="utf-8")
    (out_dir / "variants" / "content.html").write_text(content_slot, encoding="utf-8")
    (out_dir / "render.html").write_text(cover_slot, encoding="utf-8")

    # 4. template_manifest.json
    slots = SLOTS_BY_TEMPLATE[t["id"]]
    manifest = {
        "id": t["id"],
        "name": t["name"],
        "description": t["description"],
        "source_type": "html",
        "exact_source": True,
        "allowed_slide_counts": [5, 6, 7, 8, 9, 10],
        "default_slide_roles": ["cover", "insight", "insight", "insight", "cta"],
        "slots": {s["name"]: s for s in slots},
        "slide_roles": role_schema(t["id"]),
        "overflow_rules": {"hero": "shrink_then_truncate"},
        "prompt_hints": {
            "style": t["description"],
            "tag": t["tag"],
            "palette": ["#0A66C2", "#70B5F9", t["background_color"]],
            "visual_density": "low",
        },
        "render_config": {
            "width": 1080,
            "height": 1350,
            "export_format": "pdf",
            "preview_format": "svg",
            "background_color": t["background_color"],
        },
    }
    (out_dir / "template_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8",
    )
    print(f"[OK] {t['id']}")


def main() -> None:
    for t in TEMPLATES:
        write_template(t)
    print(f"\nDone. {len(TEMPLATES)} templates written to {OUT_ROOT}")


if __name__ == "__main__":
    main()
