from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.services.linkedin_auth import LinkedInAuthService


DOCUMENTS_URL = "https://api.linkedin.com/rest/documents"
POSTS_URL = "https://api.linkedin.com/rest/posts"


class LinkedInPublishError(RuntimeError):
    pass


@dataclass
class LinkedInPublishingService:
    settings: Settings
    auth_service: LinkedInAuthService

    def publish_carousel_pdf(
        self,
        *,
        pdf_path: Path,
        title: str,
        commentary: str,
    ) -> dict[str, Any]:
        session = self.auth_service.get_session()
        access_token = session.get("access_token")
        author_urn = session.get("author_urn")
        if not access_token:
            raise LinkedInPublishError("LinkedIn is not connected.")
        if not author_urn:
            raise LinkedInPublishError(
                "LinkedIn connected, but member profile ID is missing. Reconnect the account and try again."
            )
        if not pdf_path.exists():
            raise LinkedInPublishError("Carousel PDF was not found.")

        document_urn, upload_url = self._initialize_document_upload(
            access_token=access_token,
            owner_urn=author_urn,
        )
        self._upload_document(
            access_token=access_token,
            upload_url=upload_url,
            pdf_path=pdf_path,
        )
        document_state = self._wait_for_document(
            access_token=access_token,
            document_urn=document_urn,
        )
        post_id = self._create_document_post(
            access_token=access_token,
            author_urn=author_urn,
            document_urn=document_urn,
            commentary=commentary,
            title=title,
        )
        return {
            "ok": True,
            "post_id": post_id,
            "document_urn": document_urn,
            "document_status": document_state.get("status"),
            "author_urn": author_urn,
        }

    def _initialize_document_upload(
        self,
        *,
        access_token: str,
        owner_urn: str,
    ) -> tuple[str, str]:
        response = self._json_request(
            f"{DOCUMENTS_URL}?action=initializeUpload",
            method="POST",
            access_token=access_token,
            payload={"initializeUploadRequest": {"owner": owner_urn}},
        )
        value = response.get("value", {})
        document_urn = value.get("document")
        upload_url = value.get("uploadUrl")
        if not document_urn or not upload_url:
            raise LinkedInPublishError("LinkedIn did not return a document upload target.")
        return str(document_urn), str(upload_url)

    def _upload_document(
        self,
        *,
        access_token: str,
        upload_url: str,
        pdf_path: Path,
    ) -> None:
        request = urllib.request.Request(
            upload_url,
            data=pdf_path.read_bytes(),
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/pdf",
            },
            method="PUT",
        )
        try:
            with urllib.request.urlopen(request, timeout=90):
                return
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LinkedInPublishError(
                f"LinkedIn document upload failed: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LinkedInPublishError(f"LinkedIn document upload failed: {exc.reason}") from exc

    def _wait_for_document(
        self,
        *,
        access_token: str,
        document_urn: str,
    ) -> dict[str, Any]:
        encoded_urn = urllib.parse.quote(document_urn, safe="")
        last_payload: dict[str, Any] | None = None
        for _ in range(12):
            payload = self._json_request(
                f"{DOCUMENTS_URL}/{encoded_urn}",
                method="GET",
                access_token=access_token,
            )
            last_payload = payload
            status = str(payload.get("status", "")).upper()
            if status == "AVAILABLE":
                return payload
            if status == "PROCESSING_FAILED":
                raise LinkedInPublishError("LinkedIn document processing failed.")
            time.sleep(2)
        raise LinkedInPublishError(
            f"LinkedIn document processing did not complete in time. Last status: {last_payload.get('status') if last_payload else 'unknown'}"
        )

    def _create_document_post(
        self,
        *,
        access_token: str,
        author_urn: str,
        document_urn: str,
        commentary: str,
        title: str,
    ) -> str | None:
        payload = {
            "author": author_urn,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "content": {
                "media": {
                    "title": title,
                    "id": document_urn,
                }
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        headers, _ = self._json_request(
            POSTS_URL,
            method="POST",
            access_token=access_token,
            payload=payload,
            return_headers=True,
        )
        return headers.get("x-restli-id") or headers.get("X-RestLi-Id")

    def _json_request(
        self,
        url: str,
        *,
        method: str,
        access_token: str,
        payload: dict[str, Any] | None = None,
        return_headers: bool = False,
    ) -> Any:
        data = None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Linkedin-Version": self.settings.linkedin_api_version,
            "X-Restli-Protocol-Version": "2.0.0",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8", errors="ignore").strip()
                body = json.loads(raw) if raw else {}
                if return_headers:
                    return dict(response.headers.items()), body
                return body
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LinkedInPublishError(
                f"LinkedIn request failed: {detail or exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LinkedInPublishError(f"LinkedIn request failed: {exc.reason}") from exc
