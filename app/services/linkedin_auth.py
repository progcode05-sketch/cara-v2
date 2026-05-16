from __future__ import annotations

import json
import secrets
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain import utc_now


AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
SIGNIN_SCOPE = "openid profile"
PUBLISH_SCOPE = "openid profile w_member_social"


@dataclass
class LinkedInAuthService:
    settings: Settings

    def __post_init__(self) -> None:
        self.settings.oauth_dir.mkdir(parents=True, exist_ok=True)
        self._state_path = self.settings.oauth_dir / "linkedin_state.json"
        self._session_path = self.settings.oauth_dir / "linkedin_session.json"

    def get_status(self) -> dict[str, Any]:
        session = self._read_json(self._session_path, default={})
        scope = session.get("scope")
        return {
            "connected": bool(session.get("connected")),
            "profile": session.get("profile"),
            "member_id": session.get("member_id"),
            "author_urn": session.get("author_urn"),
            "connected_at": session.get("connected_at"),
            "scope": scope,
            "expires_in": session.get("expires_in"),
            "redirect_uri": session.get("redirect_uri", self.settings.linkedin_redirect_uri),
            "can_post": bool(
                session.get("access_token")
                and session.get("author_urn")
                and "w_member_social" in str(scope or "")
            ),
        }

    def build_authorization_url(
        self,
        redirect_uri: str | None = None,
        *,
        scope: str | None = None,
    ) -> str:
        resolved_redirect_uri = redirect_uri or self.settings.linkedin_redirect_uri
        resolved_scope = scope or SIGNIN_SCOPE
        state = secrets.token_urlsafe(24)
        self._write_json(
            self._state_path,
            {
                "state": state,
                "created_at": utc_now(),
                "redirect_uri": resolved_redirect_uri,
                "scope": resolved_scope,
            },
        )
        params = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.linkedin_client_id,
                "redirect_uri": resolved_redirect_uri,
                "scope": resolved_scope,
                "state": state,
            }
        )
        return f"{AUTH_URL}?{params}"

    def handle_callback(
        self,
        code: str,
        state: str,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        state_payload = self._read_json(self._state_path, default={})
        expected = state_payload.get("state")
        if not expected or expected != state:
            raise ValueError("State verification failed.")
        requested_scope = state_payload.get("scope") or SIGNIN_SCOPE
        resolved_redirect_uri = (
            redirect_uri
            or state_payload.get("redirect_uri")
            or self.settings.linkedin_redirect_uri
        )

        payload = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": resolved_redirect_uri,
                "client_id": self.settings.linkedin_client_id,
                "client_secret": self.settings.linkedin_client_secret,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                token_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ValueError(f"LinkedIn token exchange failed: {detail or exc.reason}") from exc

        profile = self._fetch_userinfo(token_data.get("access_token"))
        member_id = profile.get("sub") if isinstance(profile, dict) else None
        session = {
            "connected": True,
            "connected_at": utc_now(),
            "access_token": token_data.get("access_token"),
            "expires_in": token_data.get("expires_in"),
            "scope": token_data.get("scope", requested_scope),
            "token_type": token_data.get("token_type", "Bearer"),
            "redirect_uri": resolved_redirect_uri,
            "profile": profile,
            "member_id": member_id,
            "author_urn": f"urn:li:person:{member_id}" if member_id else None,
        }
        self._write_json(self._session_path, session)
        self._write_json(self._state_path, {})
        return session

    def disconnect(self) -> None:
        self._write_json(self._session_path, {})
        self._write_json(self._state_path, {})

    def get_session(self) -> dict[str, Any]:
        return self._read_json(self._session_path, default={})

    def _fetch_userinfo(self, access_token: str | None) -> dict[str, Any] | None:
        if not access_token:
            return None
        request = urllib.request.Request(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    def _read_json(self, path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
        if not path.exists():
            return dict(default)
        try:
            return json.loads(path.read_text("utf-8"))
        except json.JSONDecodeError:
            return dict(default)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
