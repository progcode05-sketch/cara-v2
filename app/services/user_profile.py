"""
User profile system — Option C from the agents discussion.

LinkedIn OIDC gives us identity (name, email, photo). For richer fields the
LinkedIn API doesn't expose without elevated scopes (headline, industry,
voice samples, etc.) we collect them via a settings form. The merged
UserProfile is then injected as context into every WritingAgent prompt so
the AI writes in the user's actual voice.

Storage: data/profiles/{linkedin_sub}.json — keyed by the LinkedIn `sub` so
multi-account use works. If no LinkedIn sub is available (unsigned-in user),
the profile is keyed by `_local`.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# Recognised voice presets — keep in sync with caption tones
VOICE_PRESETS = (
    "Direct", "Premium", "Clear", "Playful", "Bold", "Professional", "Warm",
)


@dataclass
class UserProfile:
    # Identity (filled from LinkedIn OIDC if signed in; settings form otherwise)
    sub:           str = ""           # LinkedIn member id (or "_local")
    name:          str = ""           # full display name
    email:         str = ""
    picture:       str = ""           # CDN URL
    handle:        str = ""           # @handle for the carousel author footer

    # Profile (from settings form — LinkedIn OIDC doesn't expose these)
    headline:      str = ""           # e.g. "Founder, Acme · helping SaaS scale"
    industry:      str = ""           # e.g. "B2B SaaS"
    audience:      str = ""           # e.g. "Solo founders building niche SaaS"
    voice_preset:  str = "Direct"     # one of VOICE_PRESETS
    topics:        list[str] = field(default_factory=list)  # 3-5 tags
    about_blurb:   str = ""           # 3-5 sentences about the user
    sample_posts:  list[str] = field(default_factory=list)  # 1-3 sample posts
    do_not_say:    list[str] = field(default_factory=list)  # banned words/phrases

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserProfile":
        # Tolerate unknown keys (forward-compatibility)
        valid_fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid_fields})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def merge_linkedin_oidc(self, oidc: dict[str, Any] | None) -> "UserProfile":
        """LinkedIn OIDC fields ALWAYS win for identity (name/email/picture)
        — the user can't override them in the form. Other fields are
        preserved from the form."""
        if not oidc:
            return self
        if oidc.get("sub"):     self.sub = str(oidc["sub"])
        if oidc.get("name"):    self.name = str(oidc["name"]).strip()
        if oidc.get("email"):   self.email = str(oidc["email"]).strip()
        if oidc.get("picture"): self.picture = str(oidc["picture"]).strip()
        # Derive handle from email username (override what's in the form)
        if self.email and "@" in self.email:
            self.handle = "@" + self.email.split("@", 1)[0]
        elif self.name:
            self.handle = "@" + self.name.lower().replace(" ", "")
        return self

    def has_writing_context(self) -> bool:
        """True if the user has filled in enough form fields to give the
        writer agents real personalization signal."""
        return bool(
            self.headline or self.industry or self.audience
            or self.about_blurb or self.sample_posts
        )

    def to_writer_context(self) -> str:
        """Render the profile as a system-prompt block for writer agents.
        Empty fields are skipped — never produces 'Headline: '."""
        if not self.has_writing_context() and not self.name:
            return ""
        lines = ["USER CONTEXT — write in this person's voice, do not invent facts about them:"]
        if self.name:        lines.append(f"  Name: {self.name}")
        if self.headline:    lines.append(f"  Headline: {self.headline}")
        if self.industry:    lines.append(f"  Industry: {self.industry}")
        if self.audience:    lines.append(f"  Audience: {self.audience}")
        if self.voice_preset: lines.append(f"  Voice preset: {self.voice_preset}")
        if self.topics:      lines.append(f"  Topics they post about: {', '.join(self.topics)}")
        if self.about_blurb: lines.append(f"  About: {self.about_blurb}")
        if self.sample_posts:
            lines.append("  Sample of their actual writing — match this voice and rhythm:")
            for i, p in enumerate(self.sample_posts[:3], 1):
                snippet = p.strip().replace("\n", " ")[:300]
                lines.append(f"    {i}. \"{snippet}\"")
        if self.do_not_say:
            lines.append(f"  Words/phrases to AVOID: {', '.join(self.do_not_say)}")
        lines.append("Match their tone, vocabulary, and sentence rhythm. NEVER fabricate facts.")
        return "\n".join(lines)


class UserProfileRepository:
    """JSON-per-user storage at data/profiles/{sub}.json"""

    def __init__(self, profiles_dir: Path) -> None:
        self.profiles_dir = profiles_dir
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, sub: str) -> Path:
        safe = "".join(c for c in (sub or "_local") if c.isalnum() or c in ("-", "_"))
        return self.profiles_dir / f"{safe or '_local'}.json"

    def get(self, sub: str) -> UserProfile:
        path = self._path_for(sub)
        if not path.exists():
            return UserProfile(sub=sub)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return UserProfile.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            return UserProfile(sub=sub)

    def save(self, profile: UserProfile) -> UserProfile:
        path = self._path_for(profile.sub or "_local")
        path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
        return profile
