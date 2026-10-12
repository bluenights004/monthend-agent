"""Build the delivery payload at submission time; deliver it only with a ReleaseTicket.

The payload (recipients, subject, body, attachment names) is written to
outputs/delivery.json *before* review, so the reviewer approves exactly what will be
sent. Delivery channels:

- outbox (default for fixtures): writes an .eml file to var/outbox/. Nothing leaves the machine.
- graph: creates an Outlook draft in the firm mailbox (mode "draft"), or creates and
  sends it (mode "send"), and uploads the pack to the client's SharePoint folder.
"""

from __future__ import annotations

import html
import json
from email.message import EmailMessage
from pathlib import Path

from monthend.config import ClientConfig, Period, var_dir
from monthend.review import ReleaseTicket

ATTACHMENTS = ("pack.xlsx",)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def build_payload(client: ClientConfig, period: Period, summary: str) -> dict:
    cfg = client.delivery
    subject = cfg.get("subject", "{client} management accounts {period_label}").format(
        client=client.name, period=period.key, period_label=period.label)
    body = (f"<p>Hello,</p><p>Please find attached the management accounts for {html.escape(client.name)} "
            f"for {html.escape(period.label)}.</p><p>{html.escape(summary)}</p>"
            "<p>Detailed commentary is on the Commentary sheet. Please let us know if you have any questions.</p>")
    return {
        "mode": cfg.get("mode", "draft"),
        "to": list(cfg.get("to", [])),
        "cc": list(cfg.get("cc", [])),
        "subject": subject,
        "html_body": body,
        "attachments": list(ATTACHMENTS),
        "sharepoint_folder": cfg.get("sharepoint_upload_folder", "").format(period=period.key),
        "mailbox": client.mailbox,
    }


def write_payload(outputs: Path, payload: dict) -> None:
    (outputs / "delivery.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def deliver(ticket: ReleaseTicket, outputs: Path, channel: str, graph=None) -> str:
    payload = ticket.delivery
    attachments = [(name, (outputs / name).read_bytes(), XLSX) for name in payload["attachments"]]
    ticket.check(subject=payload["subject"], to=payload["to"], cc=payload["cc"], attachments=attachments)

    if channel == "outbox":
        message = EmailMessage()
        message["Subject"] = payload["subject"]
        message["To"] = ", ".join(payload["to"])
        if payload["cc"]:
            message["Cc"] = ", ".join(payload["cc"])
        message["X-Monthend-Run"] = ticket.run_id
        message["X-Monthend-Bundle"] = ticket.bundle_sha256
        message.set_content("This message is HTML.")
        message.add_alternative(payload["html_body"], subtype="html")
        for name, data, ctype in attachments:
            maintype, subtype = ctype.split("/", 1)
            message.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
        outbox = var_dir() / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{ticket.run_id}.eml"
        path.write_bytes(bytes(message))
        return str(path)

    if channel == "graph":
        from monthend.sources.graph import GraphClient, sharepoint_site

        graph = graph or GraphClient.from_env()
        message_id = graph.create_draft(ticket, payload["mailbox"], payload["subject"], payload["html_body"],
                                        payload["to"], payload["cc"], attachments)
        refs = [f"outlook-draft:{message_id}"]
        if payload["mode"] == "send":
            graph.send_draft(ticket, payload["mailbox"], message_id)
            refs = [f"outlook-sent:{message_id}"]
        host, site_path = sharepoint_site()
        if host and payload.get("sharepoint_folder"):
            site = graph.site_id(host, site_path)
            for name, data, _ in attachments:
                refs.append(f"sharepoint:{graph.upload(ticket, site, payload['sharepoint_folder'], name, data)}")
        return " ".join(refs)

    raise ValueError(f"unknown delivery channel {channel!r}")
