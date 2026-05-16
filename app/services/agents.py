"""
Noxlin parallel agent pipeline.

Writing pipeline  (5 agents, ThreadPoolExecutor):
  Agent 1 – Hook / Cover
  Agent 2 – Problem / Pain
  Agent 3 – Insight / Reframe
  Agent 4 – Framework / Proof
  Agent 5 – CTA / Closer

After all 5 complete → Authenticator Agent reviews the full deck.

Visual pipeline (5 agents, ThreadPoolExecutor):
  Agents A1-A5 each own a slice of the slides and call Gemini in parallel.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.ai_clients import AnthropicClient, GeminiImageClient, ProviderError
from app.services.agent_events import AgentEventBus

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role → agent assignment
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-template design rules — surfaced to the writer so it respects design grammar
# ---------------------------------------------------------------------------

TEMPLATE_DESIGN_RULES: dict[str, list[str]] = {
    "nox-mono": [
        "HERO: STRICT max 5 words on COVER, max 6 on content. Match the Apple-keynote feel of 'Stop posting. Start growing.' — short, decisive, no fluff.",
        "HERO: wrap exactly ONE word in <em></em> for the italic-serif accent (Instrument Serif).",
        "HERO: split into 2 lines via <br> when 4+ words. Each line should be 2-3 words.",
        "KICKER: a short typographic label, all caps, prefixed with em-dash, e.g. — THE INSIGHT (max 4 words after the dash).",
        "SUPPORT (content slides only): max 22 words, plainspoken, can use <b> on one phrase for emphasis.",
        "Background is pitch-black; assume light text on dark.",
    ],
    "nox-paper": [
        "HERO: a magazine-style headline. Max 8-10 words. Use <em></em> on one word for italic blue accent.",
        "HERO_INTRO (cover only): a short serif italic phrase like 'A note on' or 'On the matter of' (max 4 words).",
        "ISSUE_LABEL: e.g. 'Essay № 07' — short serial-style label.",
        "BODY_HTML (content slides): 2 short paragraphs, total ~50-60 words. Wrap the first letter of paragraph 1 in <span class=\"drop-cap\">X</span> for the magazine drop-cap.",
        "SUB: short uppercase tagline (max 12 words).",
    ],
    "nox-num": [
        "NUMERAL: a single digit (1-9). On the cover use the total number of items; on content slides use the ordinal of THIS item.",
        "HERO: max 8-10 words. Wrap one word in <em></em> for italic accent.",
        "SUB: 1-2 sentence supporting statement (~20-30 words).",
    ],
    "nox-quote": [
        "QUOTE: max 12 words total. The whole carousel hinges on this one line being screenshot-worthy.",
        "QUOTE: split into 2 lines with a <br>, with one word wrapped in <em></em> for italic blue accent.",
        "ATTRIBUTION_TOPIC: a short topical descriptor like 'On LinkedIn growth' or 'Founding principle' (max 5 words).",
        "Aim for aphorism, not summary. Mythbust, reframe, or compress a hard truth.",
    ],
    "nox-grid": [
        "HEADLINE: max 8 words. Use <em></em> on one word for italic blue accent.",
        "EYEBROW: short kicker prefixed with em-dash, e.g. '— The pipeline' (max 4 words).",
        "C1_TITLE / C2_TITLE / C3_TITLE: each ~5-8 words. Active, declarative.",
        "C1_BODY / C2_BODY / C3_BODY: ~15-22 words each. Specific, no fluff.",
        "STAT_NUMBER: a clean numeric value (e.g. '30', '12×', '3').",
        "LEAD_TEXT: ~25-35 words. One sentence is fine. Use <b></b> on the key noun phrase.",
    ],
    "nox-grad": [
        "HERO splits into THREE parts: hero_thin (1-2 words, light weight) + hero_bold (1-2 words, bold weight) + hero_italic (1-2 words, italic serif). STRICT — each part max 12 chars. Together they form a 3-line headline like 'Content / Compounds / daily.'",
        "PRE_TEXT (cover only): ~15-20 word lede above the hero.",
        "STAT_BIG (content only): a single dominant number or multiplier ('40×', '97%', '3M+').",
        "STAT_UNIT: 2-3 words explaining what the number measures.",
        "STAT_LABEL: a short uppercase source caption prefixed with em-dash.",
        "SUPPORT (content only): ~25-35 word explanation. Use <b></b> on the key phrase.",
    ],
    "nox-cta": [
        "HEAD: STRICT max 6 words. Wrap exactly ONE word in <em></em> for italic accent.",
        "HEAD: ALWAYS use <br> to split into 2 lines. Each line 2-3 words.",
        "SUB: ~22-28 words. One clear value prop. Use <b></b> on the key benefit phrase.",
        "CTA_LABEL: 2-3 word imperative button label, max 18 chars total ('Try free', 'Subscribe', 'Get playbook').",
        "CHIP_LABEL: short uppercase tag, max 14 chars ('YOUR TURN', 'HALFWAY', 'LAST SLIDE').",
    ],
    "nox-check": [
        # Cover
        "COVER HERO: max 8 words. Use <br> to split into 2 lines. Wrap ONE word in <em></em>.",
        "COVER HERO PATTERN: 'The {N}-step <br>{topic} <em>checklist</em>' or 'Stop {X}. <br>Start <em>{Y}</em>.'",
        "COVER SUB: one sentence, ~16-24 words. State the concrete promise (what the reader will be able to do after).",
        "BADGE_LABEL: short audience tag, ALL CAPS, max 24 chars ('FOR FOUNDERS', 'FOR SOLOPRENEURS').",
        # Step slides — the heart of this template
        "STEP_NUM: zero-padded 2-digit string ('01', '02', '03').",
        "STEP_EYEBROW: 'STEP 0X · ROLE' format, ALL CAPS, max 24 chars.",
        "STEP_TITLE: imperative verb sentence, max 8 words. Wrap ONE word in <em></em> for italic accent.",
        "STEP_TITLE PATTERN: 'Pick the <em>one</em> metric that matters' or 'Block <em>30 min</em> every Sunday'.",
        "ITEM_1, ITEM_2, ITEM_3: each is a concrete, actionable bullet, ~12-22 words. Start with imperative verbs.",
        "ITEMS RULE: name specific tools, time blocks, numbers, or named days. Wrong: 'plan content'. Right: 'block 90 min on Monday in Notion'.",
        "PULL_TO_NEXT: italic teaser ending in ' →'. Max 10 words. Creates a cliffhanger to the next slide.",
        "PULL_TO_NEXT PATTERN: 'But step 2 is the one most people skip →' or 'Watch what happens on the next slide →'.",
        # CTA
        "CTA HERO: max 7 words across 2 lines via <br>. Wrap ONE word in <em></em>.",
        "CTA SUB: one-line recap of what the reader just learned + the actual CTA, ~18-26 words.",
        "CTA_LABEL: 2-3 word imperative ('Save this guide', 'Get the template', 'Try Noxlin free'). Max 22 chars.",
        "RECAP_LABEL: '— RECAP · {topic}' format, ALL CAPS, max 32 chars.",
        "SAVE_PROMPT: include both a save AND a repost cue. Example: '💾 SAVE FOR LATER · ♻ REPOST IF USEFUL'.",
    ],
}


WRITING_AGENT_ROLES: dict[int, list[str]] = {
    1: ["cover"],
    2: ["problem"],
    3: ["insight"],
    4: ["framework", "proof"],
    5: ["cta"],
}

WRITING_AGENT_PERSONAS: dict[int, str] = {
    1: (
        "You are a LinkedIn hook specialist who has written 5,000+ scroll-stopping covers. "
        "Your ONLY job: cover slides that punch in under 2 seconds. Use one of these patterns:\n"
        "  • Bold claim that contradicts conventional wisdom (\"Posting daily is killing your reach\")\n"
        "  • A specific number ('$50K', '7 mistakes', '3 hours')\n"
        "  • A sharp question that names the reader's exact pain\n"
        "  • A pattern interrupt ('Stop X. Start Y.')\n"
        "Hard rules: NEVER open with 'I', 'We', 'In today's', 'Are you', or any greeting. "
        "Use concrete nouns over abstract concepts. Pick verbs that move. "
        "If the topic is vague, MAKE IT SPECIFIC — invent a sharp angle even from a generic brief."
    ),
    2: (
        "You are a problem-framing expert who has spent a decade in user research interviews. "
        "Write slides that make the reader think 'that's EXACTLY my situation' in 4 seconds. "
        "Heuristics:\n"
        "  • Use the reader's own vocabulary — not marketing language\n"
        "  • Name a specific moment, not an abstract pain ('Sunday at 9pm staring at a blank doc' "
        "    beats 'lacks consistency')\n"
        "  • Contrast what they tried vs what failed\n"
        "  • Show the cost in real units (hours, dollars, missed opportunities)\n"
        "Banned: 'struggle', 'pain points', 'overwhelmed', 'unlock', 'leverage', 'synergy'."
    ),
    3: (
        "You are an insight and reframe specialist. You write the 'aha moment' slides that "
        "shift perspective in one sentence. The insight must feel obvious in hindsight but "
        "surprising on first read. Heuristics:\n"
        "  • Use contrast: before vs after, myth vs reality, effort vs leverage\n"
        "  • Invert a common belief ('The best content is the content you'll actually publish')\n"
        "  • Compress a hard truth into one line — aphorism, not summary\n"
        "  • Name a specific behaviour the reader can change tomorrow\n"
        "Banned: 'game-changer', 'paradigm shift', 'revolutionary', 'unlock', 'level up'."
    ),
    4: (
        "You are a systems and frameworks expert who has shipped 50+ tools. You break complex "
        "ideas into clean, named models that feel immediately actionable. Heuristics:\n"
        "  • Every framework is OPINIONATED — tell the reader EXACTLY what to do\n"
        "  • Use 3 steps maximum (or 3 columns if the template is grid-based)\n"
        "  • Each step has a verb-led title and a one-line consequence\n"
        "  • Name your framework if it has earned a name (e.g. 'The Friday Loop')\n"
        "  • Pair each step with a specific tool, time, or measurable output\n"
        "Banned: 'optimize', 'streamline', 'unlock', 'transform' (unless real change is named)."
    ),
    5: (
        "You are a conversion copywriter who has written CTAs that drove $50M in pipeline. "
        "You write closing slides that turn readers into followers, leads, or customers. "
        "Heuristics:\n"
        "  • One clear action. One clear benefit. No hedging.\n"
        "  • The CTA must feel EARNED by the carousel, not tacked on\n"
        "  • Match the next-step weight to the user's relationship "
        "    ('Subscribe' for cold, 'Reply with X' for warm)\n"
        "  • Specific > abstract — 'Get the Friday playbook' beats 'Learn more'\n"
        "Banned: 'Reach out', 'Drop a line', 'DM me' (unless followed by a specific token)."
    ),
}


# ---------------------------------------------------------------------------
# Writing Agent
# ---------------------------------------------------------------------------

@dataclass
class WritingAgent:
    agent_id: int
    specialty_roles: list[str]
    client: AnthropicClient
    event_bus: AgentEventBus | None = None
    user_context: str = ""

    def run(
        self,
        *,
        slides: list[dict[str, Any]],
        topic: str,
        brief: str,
        audience: str,
        tone: str,
        cta: str,
        template_id: str,
        template_name: str,
        prompt_hints: dict[str, Any],
    ) -> dict[int, dict[str, str]]:
        """
        Given a list of slide specs assigned to this agent, call Claude once
        and return {slide_index: {slot_name: value}}.
        """
        if not slides:
            return {}

        agent_label = f"WritingAgent#{self.agent_id}"
        if self.event_bus:
            self.event_bus.publish(
                "agent_started",
                agent=agent_label,
                role_focus=self.specialty_roles,
                persona=WRITING_AGENT_PERSONAS[self.agent_id].split(".")[0],
                slide_indexes=[s["index"] for s in slides],
                has_user_context=bool(self.user_context),
            )

        # User profile context (from settings form + LinkedIn) — injected into
        # the system prompt so the writer matches the user's actual voice.
        user_block = f"\n\n{self.user_context}" if self.user_context else ""
        system_prompt = (
            f"{WRITING_AGENT_PERSONAS[self.agent_id]}{user_block}\n\n"
            "Return ONLY valid JSON — no markdown fences, no commentary.\n"
            "Schema: {\"slides\": [{\"index\": <int>, \"role\": <str>, \"slot_values\": {<slot>: <value>}}]}"
        )

        # Per-template design rules — these win over generic copywriting
        template_rules = TEMPLATE_DESIGN_RULES.get(template_id, [])

        user_prompt = json.dumps(
            {
                "topic": topic,
                "brief": brief,
                "audience": audience,
                "tone": tone,
                "cta": cta,
                "template_id": template_id,
                "template_name": template_name,
                "template_style": prompt_hints.get("style", ""),
                "visual_density": prompt_hints.get("visual_density", "low"),
                "slides_to_write": slides,
                "design_rules": template_rules,
                "rules": [
                    "Fill every allowed slot with concise, polished copy.",
                    f"Tone must be: {tone}.",
                    f"Audience: {audience}.",
                    "Never include placeholder text like [NAME], [INSERT], 'Your Name', 'Your Handle', '@yourhandle', or 'lorem ipsum'.",
                    "Respect max_chars limits — shorter is almost always better.",
                    "Return the same slide indexes you received.",
                    "OBEY design_rules above all — they are template-specific design constraints.",
                    "When a slot like 'hero' or 'head' or 'quote' or 'headline' supports italic accents, "
                    "wrap exactly ONE word in <em>...</em> tags to mark the italic accent. "
                    "Never use markdown asterisks for emphasis.",
                    "When a slot supports line breaks (like 'hero', 'head', 'quote', 'headline'), "
                    "use <br> tags to split into 2 short lines for visual rhythm.",
                    "DO NOT FILL these identity / chrome slots — leave them empty, the system "
                    "fills them from the user's actual input or design defaults: "
                    "author_name, author_handle, author_initial, brand_name, brand_site, "
                    "brand_handle, page_number, page_label, swipe_label, "
                    "footer_label, stamp_brand, stamp_site.",
                    "If you DO need to fill swipe_label or any 'arrow pill' style slot, "
                    "keep it under 12 characters total (e.g. 'swipe →', 'next →'). "
                    "These slots render in a fixed-size pill and longer text wraps badly.",
                    "If you fill cta_label, keep it under 24 characters.",
                    # ── WORD-LENGTH RULE — fixes 'incomplete word at edge of frame'
                    "WORD-LENGTH RULE: in hero/head/quote/headline/numeral slots, NEVER use a "
                    "single word longer than 13 characters. If the natural word is longer "
                    "(e.g. 'revolutionizing', 'infrastructure', 'democratization'), rewrite "
                    "with a shorter synonym ('reshapes', 'systems', 'opening up'). "
                    "Long words get cropped at the slide edge.",
                    # ── ANTI-SLOP — kills generic LLM voice
                    "BANNED PHRASES (never use, in any slot): 'in today's fast-paced world', "
                    "'leverage', 'synergy', 'game-changer', 'unlock', 'elevate', 'level up', "
                    "'paradigm shift', 'cutting-edge', 'best-in-class', 'world-class', "
                    "'thought leader', 'mission-critical', 'revolutionary', 'streamline', "
                    "'circle back', 'low-hanging fruit', 'move the needle', 'crush it', "
                    "'10x', 'hustle', 'grind', 'rise and shine', 'let's dive in', "
                    "'at the end of the day', 'it's important to note', 'as a Founder'. "
                    "Replace any of these with a concrete, specific verb or noun.",
                    # ── SPECIFICITY RULE — concrete > abstract
                    "SPECIFICITY RULE: name specific things — products, numbers, time units, "
                    "named days, named tools — instead of generic categories. "
                    "Wrong: 'spend a lot of time'. Right: 'spend 4 hours every Sunday'. "
                    "Wrong: 'use the right tool'. Right: 'open Notion at 7am'.",
                    # ── HUMAN-VOICE RULE
                    "HUMAN-VOICE RULE: contractions are encouraged ('don't', 'isn't', "
                    "'they're'). Use sentence fragments for emphasis. Avoid corporate hedging "
                    "('might', 'could potentially', 'one of the things to consider'). State "
                    "things plainly. The reader should feel a person wrote this, not a deck.",
                    # ── HOOK RULE — fixes 'no attention-grabber on slide 1'
                    "HOOK RULE: the cover slide MUST open with a question, a bold stat, "
                    "a contrarian claim, or a curiosity gap. Never open with 'In this carousel...' "
                    "or 'Today we'll talk about...'. Examples: 'Most carousels die on slide 2.', "
                    "'87% of LinkedIn posts get under 50 views.', 'Stop writing carousels.'",
                    # ── SAVE-WORTHY RULE — drives bookmarks, the #1 LinkedIn signal
                    "SAVE-WORTHY RULE: every carousel needs at least ONE slide a reader would "
                    "screenshot or save — a numbered list, a checklist, a concrete framework, "
                    "a swipe file, or a labelled diagram in copy form. Avoid pure inspiration.",
                    # ── CTA RULE — the closing slide does the conversion work
                    "CTA RULE: the final cta slide must include (a) a one-line recap of the "
                    "carousel's core promise, (b) a 'Save this for later' or 'Repost if useful' "
                    "prompt, and (c) the user's actual cta text. Never close with 'Thanks for "
                    "reading' or 'Hope this helps' — those are dead-air closers.",
                    # ── NAVIGATION RULE — keeps swipers swiping
                    "NAVIGATION RULE: middle slides should end on a hook that pulls to the next "
                    "slide ('But here's the catch →', 'The fix? →', 'Step 2 changes everything →'). "
                    "Treat each slide as a cliffhanger, not a paragraph break.",
                    # ── UNIQUENESS RULE — every slide must be distinct
                    "UNIQUENESS RULE: even if two slides share the same role, they MUST have "
                    "completely different hero/head/quote/headline and body/sub/support text. "
                    "Each slide advances the narrative — never repeat a phrase, stat, or idea "
                    "from another slide. Think of each slide as a new scene, not a copy.",
                ],
            },
            ensure_ascii=False,
        )

        try:
            payload = self.client.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                max_tokens=2500,
                temperature=0.7,
            )
        except Exception as exc:  # noqa: BLE001 — never let one writer crash the carousel
            log.warning("WritingAgent %d failed: %s", self.agent_id, exc)
            if self.event_bus:
                self.event_bus.publish(
                    "agent_failed",
                    agent=agent_label,
                    error=str(exc)[:160],
                )
            return {}

        result = self._parse(payload)
        if self.event_bus:
            sample = ""
            if result:
                first = next(iter(result.values()))
                hero = first.get("hero") or first.get("head") or first.get("quote") or first.get("headline") or ""
                sample = (hero[:80] + "…") if len(hero) > 80 else hero
            self.event_bus.publish(
                "agent_completed",
                agent=agent_label,
                slides_filled=len(result),
                slide_indexes=list(result.keys()),
                sample=sample,
            )
        return result

    def _parse(self, payload: dict[str, Any]) -> dict[int, dict[str, str]]:
        out: dict[int, dict[str, str]] = {}
        for item in payload.get("slides", []):
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item["index"])
            except (KeyError, TypeError, ValueError):
                continue
            sv = item.get("slot_values", {})
            if isinstance(sv, dict):
                out[idx] = {str(k): str(v).strip() for k, v in sv.items() if v is not None}
        return out


# ---------------------------------------------------------------------------
# Input Authenticator Agent
#   Runs BEFORE the writers. Cleans typos in topic/brief/audience/tone/cta,
#   normalizes capitalization, and returns a polished version for downstream
#   agents. Lightweight Claude call (~80 tokens out).
# ---------------------------------------------------------------------------

@dataclass
class InputAuthenticatorAgent:
    client: AnthropicClient
    event_bus: AgentEventBus | None = None

    SYSTEM = (
        "You are an input quality reviewer + brief enricher for a LinkedIn carousel "
        "generator. Users type fast — they make typos AND they often write briefs "
        "that are too vague for downstream writers to do their best work. You do "
        "TWO jobs:\n\n"
        "JOB 1 — TYPO/CASE CLEANUP\n"
        "  • Fix obvious typos ('lienkdin' -> 'LinkedIn', 'cusotmer' -> 'customer', "
        "    'profsional' -> 'Professional')\n"
        "  • Normalize capitalization (Title Case for topic, Sentence case for brief)\n"
        "  • Trim excessive punctuation\n"
        "  • Tone field: snap to the closest of: Direct, Premium, Clear, Playful, "
        "    Bold, Professional, Warm\n\n"
        "JOB 2 — BRIEF ENRICHMENT (the new bit)\n"
        "  • If the brief is shorter than ~10 words OR very generic (like 'Most "
        "    founders waste money on this'), expand it into a single sharper "
        "    sentence (~20-30 words) that:\n"
        "      - keeps the user's intent and angle\n"
        "      - adds ONE concrete example, named tool, or specific number\n"
        "      - doesn't fabricate facts about the user — only sharpen the framing\n"
        "  • If the brief is already specific and detailed, leave it alone.\n"
        "  • NEVER rewrite the topic itself — only fix typos in it.\n"
        "  • Audience: if blank, leave blank — don't invent.\n\n"
        "GLOBAL RULES\n"
        "  • Keep the user's voice and vocabulary\n"
        "  • If a field is already clean and specific, return unchanged\n"
        "  • Banned in any field: 'in today's fast-paced world', 'leverage', "
        "    'synergy', 'unlock', 'elevate', 'game-changer'\n\n"
        "Return ONLY valid JSON — no markdown, no commentary.\n"
        'Schema: {"topic": "...", "brief": "...", "audience": "...", '
        '"tone": "...", "cta": "...", "fixes": ["short list of what changed"]}'
    )

    def review(
        self,
        *,
        topic: str,
        brief: str,
        audience: str,
        tone: str,
        cta: str,
    ) -> dict[str, Any]:
        """
        Returns a dict with cleaned versions of each field plus a 'fixes' list.
        On failure, returns the inputs unchanged so the pipeline never breaks.
        """
        if self.event_bus:
            self.event_bus.publish(
                "agent_started",
                agent="InputAuthenticator",
                topic=topic[:80],
            )

        user_prompt = json.dumps(
            {"topic": topic, "brief": brief, "audience": audience, "tone": tone, "cta": cta},
            ensure_ascii=False,
        )

        try:
            payload = self.client.generate_json(
                system_prompt=self.SYSTEM,
                user_prompt=user_prompt,
                max_tokens=600,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001 — input cleanup is best-effort
            log.warning("InputAuthenticator failed: %s — passing through unchanged.", exc)
            if self.event_bus:
                self.event_bus.publish(
                    "agent_failed", agent="InputAuthenticator", error=str(exc)[:160],
                )
            return {
                "topic": topic, "brief": brief, "audience": audience,
                "tone": tone, "cta": cta, "fixes": [],
            }

        cleaned = {
            "topic":    str(payload.get("topic", topic)).strip() or topic,
            "brief":    str(payload.get("brief", brief)).strip() or brief,
            "audience": str(payload.get("audience", audience)).strip() or audience,
            "tone":     str(payload.get("tone", tone)).strip() or tone,
            "cta":      str(payload.get("cta", cta)).strip() or cta,
            "fixes":    [str(f) for f in payload.get("fixes", [])][:8],
        }

        if self.event_bus:
            changed = []
            if cleaned["topic"] != topic:    changed.append(f"topic: '{topic[:40]}' -> '{cleaned['topic'][:40]}'")
            if cleaned["audience"] != audience: changed.append(f"audience: '{audience[:30]}' -> '{cleaned['audience'][:30]}'")
            if cleaned["tone"] != tone:      changed.append(f"tone: {tone} -> {cleaned['tone']}")
            self.event_bus.publish(
                "agent_completed",
                agent="InputAuthenticator",
                changes=len(cleaned["fixes"]),
                fixes=cleaned["fixes"][:5],
                changed_fields=changed,
            )
        return cleaned


# ---------------------------------------------------------------------------
# Authenticator Agent
# ---------------------------------------------------------------------------

@dataclass
class AuthenticatorAgent:
    client: AnthropicClient
    event_bus: AgentEventBus | None = None
    user_context: str = ""

    SYSTEM = (
        "You are a senior LinkedIn content editor with a brutal eye for AI-slop and "
        "corporate filler. You receive a full carousel deck and audit EVERY slide "
        "against these criteria — be merciless:\n"
        "  1. HOOK STRENGTH — does the cover stop the scroll? If it could be "
        "     replaced with any other generic LinkedIn carousel cover, rewrite it.\n"
        "  2. SPECIFICITY — every claim must name a specific number, time, "
        "     tool, or named thing. 'Most founders' fails. '4 in 5 SaaS founders' passes.\n"
        "  3. TONE CONSISTENCY — same voice from slide 1 to last. Match the user's "
        "     sample posts (if provided in your context) — vocabulary, sentence "
        "     length, contractions.\n"
        "  4. ONE IDEA PER SLIDE — each slide must communicate exactly ONE idea. "
        "     If a slide has two ideas, pick the stronger one and rewrite.\n"
        "  5. ANTI-SLOP — kill any of these phrases on sight: 'in today's fast-paced "
        "     world', 'leverage', 'synergy', 'game-changer', 'unlock', 'elevate', "
        "     'level up', 'paradigm', 'cutting-edge', 'best-in-class', 'world-class', "
        "     'thought leader', 'mission-critical', 'revolutionary', 'streamline', "
        "     'circle back', 'move the needle', 'crush it', 'hustle', 'grind', "
        "     'let's dive in', 'at the end of the day'.\n"
        "  6. WORD-LENGTH — no word in hero/head/quote/headline longer than 13 "
        "     chars (it crops at the slide edge). If you find one, rewrite with "
        "     a shorter synonym.\n"
        "  7. CTA QUALITY — the final slide names a concrete next step.\n\n"
        "For any slide that fails, REWRITE the offending slot values to fix it. "
        "Preserve <em></em> italic accents and <br> line breaks where present.\n"
        "CRITICAL: only include slides in your response that you actually rewrote. "
        "Do NOT include slides that passed — omitting a slide means it is approved as-is. "
        "Each rewritten slide must have content that is completely different from every other slide.\n"
        "Return ONLY valid JSON — no markdown fences.\n"
        "Schema: {\"approved\": true|false, \"issues\": [<string>], "
        "\"slides\": [{\"index\": <int>, \"slot_values\": {<slot>: <value>}}]}"
    )

    def review(
        self,
        *,
        slides: list[dict[str, Any]],
        topic: str,
        audience: str,
        tone: str,
    ) -> tuple[bool, list[str], dict[int, dict[str, str]]]:
        """
        Returns (approved, issues, {slide_index: revised_slot_values}).
        If approved is False the orchestrator can retry or flag for user review.
        """
        if self.event_bus:
            self.event_bus.publish(
                "agent_started",
                agent="AuthenticatorAgent",
                deck_size=len(slides),
            )

        user_prompt = json.dumps(
            {
                "topic": topic,
                "audience": audience,
                "tone": tone,
                "deck": slides,
            },
            ensure_ascii=False,
        )

        try:
            sys_with_ctx = self.SYSTEM
            if self.user_context:
                sys_with_ctx = self.SYSTEM + "\n\n" + self.user_context
            payload = self.client.generate_json(
                system_prompt=sys_with_ctx,
                user_prompt=user_prompt,
                max_tokens=3500,
                temperature=0.2,
            )
        except Exception as exc:  # noqa: BLE001 — quality pass is best-effort
            log.warning("AuthenticatorAgent failed: %s — passing through unchanged.", exc)
            if self.event_bus:
                self.event_bus.publish(
                    "agent_failed",
                    agent="AuthenticatorAgent",
                    error=str(exc),
                )
            return True, [], {}

        approved: bool = bool(payload.get("approved", True))
        issues: list[str] = [str(i) for i in payload.get("issues", [])]
        revised: dict[int, dict[str, str]] = {}
        for item in payload.get("slides", []):
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item["index"])
            except (KeyError, TypeError, ValueError):
                continue
            sv = item.get("slot_values", {})
            if isinstance(sv, dict):
                revised[idx] = {str(k): str(v).strip() for k, v in sv.items() if v is not None}

        if self.event_bus:
            self.event_bus.publish(
                "agent_completed",
                agent="AuthenticatorAgent",
                approved=approved,
                issues=issues,
                slides_revised=len(revised),
            )
        return approved, issues, revised


# ---------------------------------------------------------------------------
# Captain Writing Agent  (coordinates the 5 writing agents + authenticator)
# ---------------------------------------------------------------------------

@dataclass
class CaptainWritingAgent:
    """
    Fans out work to 5 specialised writing agents in parallel,
    then sends the merged deck to the Authenticator Agent for review.
    """
    client: AnthropicClient
    max_workers: int = 5
    event_bus: AgentEventBus | None = None
    user_context: str = ""

    def run(
        self,
        *,
        slide_specs: list[dict[str, Any]],
        topic: str,
        brief: str,
        audience: str,
        tone: str,
        cta: str,
        template_id: str,
        template_name: str,
        prompt_hints: dict[str, Any],
    ) -> dict[int, dict[str, str]]:
        """
        Returns {slide_index: slot_values} for every slide in slide_specs,
        after writing + authentication passes.
        """
        # ── 1. Assign slides to agents by role ───────────────────────
        agent_assignments: dict[int, list[dict]] = {i: [] for i in WRITING_AGENT_ROLES}
        unmatched: list[dict] = []
        for spec in slide_specs:
            role = spec.get("role", "")
            assigned = False
            for agent_id, roles in WRITING_AGENT_ROLES.items():
                if role in roles:
                    agent_assignments[agent_id].append(spec)
                    assigned = True
                    break
            if not assigned:
                # insight is the safe default for unknown roles
                agent_assignments[3].append(spec)

        log.info(
            "CaptainWritingAgent: %d slides → %s",
            len(slide_specs),
            {aid: [s["index"] for s in slides] for aid, slides in agent_assignments.items() if slides},
        )

        if self.event_bus:
            self.event_bus.publish(
                "captain_dispatched",
                agent="Captain",
                total_slides=len(slide_specs),
                template_id=template_id,
                topic=topic,
                assignments={
                    f"WritingAgent#{aid}": [s["index"] for s in slides]
                    for aid, slides in agent_assignments.items() if slides
                },
            )

        # ── 2. Run all 5 writing agents in parallel ───────────────────
        merged_slots: dict[int, dict[str, str]] = {}
        shared_kwargs = dict(
            topic=topic, brief=brief, audience=audience, tone=tone, cta=cta,
            template_id=template_id, template_name=template_name,
            prompt_hints=prompt_hints,
        )

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="writing_agent") as pool:
            future_to_agent = {
                pool.submit(
                    WritingAgent(
                        agent_id=aid,
                        specialty_roles=WRITING_AGENT_ROLES[aid],
                        client=self.client,
                        event_bus=self.event_bus,
                        user_context=self.user_context,
                    ).run,
                    slides=slides,
                    **shared_kwargs,
                ): aid
                for aid, slides in agent_assignments.items()
                if slides  # skip agents with no assigned slides
            }

            for future in as_completed(future_to_agent):
                aid = future_to_agent[future]
                try:
                    result = future.result()
                    merged_slots.update(result)
                    log.info("WritingAgent %d completed: %d slides", aid, len(result))
                except Exception as exc:
                    log.error("WritingAgent %d raised: %s", aid, exc)

        # ── 3. Authenticator Agent reviews the merged deck ────────────
        deck_for_review = [
            {
                "index": spec["index"],
                "role": spec.get("role", ""),
                "slot_values": merged_slots.get(spec["index"], {}),
            }
            for spec in slide_specs
        ]

        auth = AuthenticatorAgent(
            client=self.client, event_bus=self.event_bus,
            user_context=self.user_context,
        )
        approved, issues, revised = auth.review(
            slides=deck_for_review,
            topic=topic,
            audience=audience,
            tone=tone,
        )

        if issues:
            log.info("AuthenticatorAgent issues: %s", issues)

        # Apply authenticator's revisions (only non-empty overwrites)
        for idx, slot_values in revised.items():
            if idx in merged_slots:
                merged_slots[idx].update(slot_values)
            else:
                merged_slots[idx] = slot_values

        if not approved:
            log.warning(
                "AuthenticatorAgent flagged deck as needing review. Issues: %s", issues
            )
            # We still return the revised content — user sees it in the approval step

        return merged_slots


# ---------------------------------------------------------------------------
# Visual Agent  (one Gemini call per task)
# ---------------------------------------------------------------------------

@dataclass
class VisualAgent:
    agent_id: int
    client: GeminiImageClient

    def run(
        self,
        *,
        tasks: list[dict[str, Any]],  # [{slide_index, slot_name, prompt, negative_prompt, output_path}]
    ) -> dict[str, str]:
        """
        Returns {task_key: generated_path_or_empty} for each task.
        task_key = "{slide_index}:{slot_name}"
        """
        results: dict[str, str] = {}
        for task in tasks:
            key = f"{task['slide_index']}:{task['slot_name']}"
            out_path: Path = task["output_path"]
            try:
                generated = self.client.generate_image(
                    prompt=task["prompt"],
                    negative_prompt=task.get("negative_prompt", ""),
                    output_path=out_path,
                )
                results[key] = str(generated)
                log.info("VisualAgent %d generated: %s", self.agent_id, key)
            except ProviderError as exc:
                log.warning("VisualAgent %d failed %s: %s", self.agent_id, key, exc)
                results[key] = ""
        return results


# ---------------------------------------------------------------------------
# Visual Captain  (distributes image tasks across 5 visual agents)
# ---------------------------------------------------------------------------

@dataclass
class VisualCaptain:
    client: GeminiImageClient
    max_workers: int = 5

    def run(self, tasks: list[dict[str, Any]]) -> dict[str, str]:
        """
        Splits tasks across 5 agents and runs them in parallel.
        Returns merged {task_key: path} dict.
        """
        if not tasks:
            return {}

        # Round-robin assignment across 5 agents
        agent_tasks: dict[int, list[dict]] = {i: [] for i in range(1, self.max_workers + 1)}
        for i, task in enumerate(tasks):
            agent_tasks[(i % self.max_workers) + 1].append(task)

        log.info(
            "VisualCaptain: %d tasks → %s agents",
            len(tasks),
            {aid: len(t) for aid, t in agent_tasks.items() if t},
        )

        merged: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="visual_agent") as pool:
            future_to_agent = {
                pool.submit(
                    VisualAgent(agent_id=aid, client=self.client).run,
                    tasks=agent_tasks[aid],
                ): aid
                for aid in range(1, self.max_workers + 1)
                if agent_tasks[aid]
            }

            for future in as_completed(future_to_agent):
                aid = future_to_agent[future]
                try:
                    result = future.result()
                    merged.update(result)
                    log.info("VisualAgent %d completed: %d images", aid, len(result))
                except Exception as exc:
                    log.error("VisualAgent %d raised: %s", aid, exc)

        return merged
