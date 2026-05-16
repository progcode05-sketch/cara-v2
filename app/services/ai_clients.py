from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProviderError(RuntimeError):
    pass


@dataclass
class AnthropicClient:
    api_key: str
    model: str
    api_url: str = "https://api.anthropic.com/v1/messages"

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1800,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        if not self.is_configured():
            raise ProviderError("Claude API key or model is missing.")
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        request = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        # Retry up to 5 times on transient network/SSL errors and 429 rate-limits.
        # 429 special-case: parse Retry-After header, sleep, then retry. Other 4xx
        # fail fast (won't be fixed by retry). Network errors get exponential backoff.
        last_exc: Exception | None = None
        max_attempts = 5
        for attempt in range(max_attempts):
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                if exc.code == 429:
                    # Honour Retry-After if Anthropic provided it, else exponential backoff.
                    retry_after_hdr = exc.headers.get("retry-after") if exc.headers else None
                    try:
                        wait_s = float(retry_after_hdr) if retry_after_hdr else 0.0
                    except (TypeError, ValueError):
                        wait_s = 0.0
                    if wait_s <= 0:
                        wait_s = min(2 ** attempt, 30)
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        time.sleep(wait_s)
                        continue
                if 400 <= exc.code < 500 and exc.code != 429:
                    raise ProviderError(f"Claude request failed: {detail or exc.reason}") from exc
                last_exc = exc
                if attempt < max_attempts - 1:
                    time.sleep(min(2 ** attempt, 10))
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    time.sleep(min(2 ** attempt, 10))
            except (ConnectionError, TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    time.sleep(min(2 ** attempt, 10))
            except Exception as exc:  # noqa: BLE001 — last-resort safety
                last_exc = exc
                if attempt < max_attempts - 1:
                    time.sleep(min(2 ** attempt, 10))
        else:
            reason = getattr(last_exc, "reason", None) or str(last_exc)
            raise ProviderError(f"Claude request failed after retries: {reason}") from last_exc

        text = self._extract_text(body)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            extracted = self._extract_json_block(text)
            return json.loads(extracted)

    def _extract_text(self, payload: dict[str, Any]) -> str:
        parts = payload.get("content", [])
        text_parts = [
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        text = "\n".join(part for part in text_parts if part.strip()).strip()
        if not text:
            raise ProviderError("Claude returned no text content.")
        return text

    def _extract_json_block(self, text: str) -> str:
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
        if fenced:
            return fenced.group(1)
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ProviderError("Claude returned text but not valid JSON.")
        return text[start : end + 1]


@dataclass
class GeminiImageClient:
    api_key: str
    model: str
    api_root: str = "https://generativelanguage.googleapis.com/v1beta/models"

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)

    def generate_image(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        output_path: Path,
    ) -> Path:
        if not self.is_configured():
            raise ProviderError("Gemini API key or image model is missing.")
        combined_prompt = prompt.strip()
        if negative_prompt.strip():
            combined_prompt += f"\n\nAvoid: {negative_prompt.strip()}"
        endpoint = f"{self.api_root}/{urllib.parse.quote(self.model)}:generateContent?key={urllib.parse.quote(self.api_key)}"
        payload = {
            "contents": [{"parts": [{"text": combined_prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ProviderError(f"Gemini image request failed: {detail or exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Gemini image request failed: {exc.reason}") from exc

        image_data = self._extract_inline_image(body)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(image_data))
        return output_path

    def _extract_inline_image(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates", [])
        for candidate in candidates:
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                inline_data = part.get("inlineData") or part.get("inline_data")
                if not inline_data:
                    continue
                data = inline_data.get("data")
                if data:
                    return data
        raise ProviderError("Gemini returned no inline image data.")
