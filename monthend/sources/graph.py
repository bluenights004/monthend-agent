"""Microsoft Graph client for Outlook, SharePoint and Excel.

Authentication is app-only (client credentials). Grant the narrowest permissions:
- Sites.Selected (then grant the app access to the one client-files site only)
- Mail.ReadWrite on the firm mailbox, restricted with an Exchange application access
  policy (RBAC for Applications) so the app cannot read any other mailbox.
- Mail.Send only if delivery.mode is "send"; "draft" mode never sends.

Write methods take a `ReleaseTicket`, which only `monthend.review.issue_release_ticket`
can create, and only for an approved, unchanged bundle. See docs/06-architecture.md.
"""

from __future__ import annotations

import base64
import os
import time
import urllib.parse
from typing import TYPE_CHECKING

from monthend.sources.http import IntegrationError, MinuteWindowLimiter, require_env, send_with_retries

if TYPE_CHECKING:
    from monthend.review import ReleaseTicket

GRAPH = "https://graph.microsoft.com/v1.0"
INLINE_ATTACHMENT_LIMIT = 3 * 1024 * 1024  # Graph inline attachments must be < 3 MB
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024       # conservative simple-upload size


class GraphClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, *, http=None, sleep=time.sleep):
        import httpx

        self.tenant_id, self.client_id, self.client_secret = tenant_id, client_id, client_secret
        self.http = http or httpx.Client(timeout=60, follow_redirects=True)
        self.sleep = sleep
        self.limiter = MinuteWindowLimiter(600, sleep=sleep)
        self._token: tuple[str, float] | None = None

    @classmethod
    def from_env(cls) -> "GraphClient":
        env = require_env("M365_TENANT_ID", "M365_CLIENT_ID", "M365_CLIENT_SECRET")
        return cls(env["M365_TENANT_ID"], env["M365_CLIENT_ID"], env["M365_CLIENT_SECRET"])

    # ------------------------------------------------------------------ transport

    def _access_token(self) -> str:
        if self._token and self._token[1] - 60 > time.time():
            return self._token[0]
        response = self.http.post(
            f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
            data={"client_id": self.client_id, "client_secret": self.client_secret,
                  "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials"},
        )
        if response.status_code != 200:
            raise IntegrationError(f"Microsoft identity platform returned {response.status_code}: {response.text[:200]}")
        body = response.json()
        self._token = (body["access_token"], time.time() + int(body.get("expires_in", 3599)))
        return self._token[0]

    def _request(self, method: str, url: str, **kwargs):
        url = url if url.startswith("http") else f"{GRAPH}/{url.lstrip('/')}"

        def send():
            self.limiter.acquire()
            headers = {"Authorization": f"Bearer {self._access_token()}", **kwargs.pop("headers", {})}
            return self.http.request(method, url, headers=headers, **kwargs)

        def drop_token():
            self._token = None

        response = send_with_retries(send, sleep=self.sleep, on_unauthorised=drop_token)
        if response.status_code >= 400:
            raise IntegrationError(f"Graph {method} {url} returned {response.status_code}: {response.text[:300]}")
        return response

    def _paged(self, url: str) -> list[dict]:
        items: list[dict] = []
        while url:
            body = self._request("GET", url).json()
            items.extend(body.get("value", []))
            url = body.get("@odata.nextLink")
        return items

    # ------------------------------------------------------------------ read

    def site_id(self, hostname: str, site_path: str) -> str:
        return self._request("GET", f"sites/{hostname}:/{site_path.strip('/')}").json()["id"]

    def folder_children(self, site_id: str, folder: str) -> list[dict]:
        path = urllib.parse.quote(folder.strip("/"))
        return self._paged(f"sites/{site_id}/drive/root:/{path}:/children")

    def download(self, site_id: str, item_id: str) -> bytes:
        return self._request("GET", f"sites/{site_id}/drive/items/{item_id}/content").content

    def read_range(self, site_id: str, item_id: str, sheet: str, address: str) -> list[list]:
        sheet_q = urllib.parse.quote(sheet)
        url = f"sites/{site_id}/drive/items/{item_id}/workbook/worksheets/{sheet_q}/range(address='{address}')"
        return self._request("GET", url).json().get("values", [])

    def list_messages(self, mailbox: str, received_from: str, received_to: str, top: int = 50) -> list[dict]:
        query = urllib.parse.urlencode({
            "$filter": f"receivedDateTime ge {received_from} and receivedDateTime le {received_to}",
            "$select": "id,subject,from,receivedDateTime,bodyPreview",
            "$orderby": "receivedDateTime desc",
            "$top": str(top),
        })
        return self._paged(f"users/{urllib.parse.quote(mailbox)}/messages?{query}")

    # ------------------------------------------------------------------ gated writes

    def create_draft(self, ticket: "ReleaseTicket", mailbox: str, subject: str, html_body: str,
                     to: list[str], cc: list[str], attachments: list[tuple[str, bytes, str]]) -> str:
        ticket.check(subject=subject, to=to, cc=cc, attachments=attachments)
        total = sum(len(data) for _, data, _ in attachments)
        if total >= INLINE_ATTACHMENT_LIMIT:
            raise IntegrationError("attachments exceed 3 MB; large-attachment upload sessions are not implemented")
        message = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html_body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to],
            "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
            "attachments": [{"@odata.type": "#microsoft.graph.fileAttachment", "name": name, "contentType": ctype,
                             "contentBytes": base64.b64encode(data).decode()} for name, data, ctype in attachments],
        }
        return self._request("POST", f"users/{urllib.parse.quote(mailbox)}/messages", json=message).json()["id"]

    def send_draft(self, ticket: "ReleaseTicket", mailbox: str, message_id: str) -> None:
        ticket.check_send_allowed()
        self._request("POST", f"users/{urllib.parse.quote(mailbox)}/messages/{message_id}/send")

    def upload(self, ticket: "ReleaseTicket", site_id: str, folder: str, filename: str, data: bytes) -> str:
        ticket.check_attachment(filename, data)
        if len(data) > SIMPLE_UPLOAD_LIMIT:
            raise IntegrationError("file exceeds the simple-upload limit; resumable upload is not implemented")
        path = urllib.parse.quote(f"{folder.strip('/')}/{filename}")
        return self._request("PUT", f"sites/{site_id}/drive/root:/{path}:/content", content=data).json()["id"]


def sharepoint_site() -> tuple[str, str]:
    """Hostname and site path for client files, e.g. ('yourfirm.sharepoint.com', 'sites/Clients')."""
    return os.environ.get("M365_SHAREPOINT_HOST", ""), os.environ.get("M365_SHAREPOINT_SITE", "")
