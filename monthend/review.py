"""The human review gate.

Rules (enforced here, in code; hooks and agent tool lists are extra layers, not the control):

1. A run can be submitted for review only when every blocking check passes.
2. Submission freezes a manifest: SHA-256 of every deliverable, of the inputs, of the
   code and configuration, and the exact delivery payload (recipients, subject,
   attachment hashes). The manifest's own hash is the *bundle hash*.
3. Approval is recorded by a named reviewer from the client's reviewer list, who must
   type the first 8 characters of the bundle hash shown on the review page. That ties
   the decision to the exact version they looked at.
4. Approval is refused inside an agent session (MONTHEND_AGENT_SESSION is set by the
   hooks and the overnight runner) and there is no MCP tool for it.
5. Anything external (Outlook draft/send, SharePoint upload) needs a ReleaseTicket,
   issued only if the run is APPROVED and every file still matches the approved hash.
   The ticket then checks the payload it is asked to send is the approved payload.

Limitation: in a local CLI deployment the reviewer's identity is whatever they type,
plus the operating-system user. A hosted deployment should put approval behind SSO
(docs/09-security-and-controls.md).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from monthend.store import Store, default_store

DELIVERABLES = ("pack.xlsx", "workpapers.xlsx", "workpapers.md", "commentary.json", "validation.json", "delivery.json")
_TICKET_KEY = object()


class GateError(RuntimeError):
    """The review gate refused an action. The message says why, in plain English."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def code_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted((root / "monthend").rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def build_manifest(run: dict, config_paths: list[Path]) -> dict:
    run_dir = Path(run["run_dir"])
    outputs = run_dir / "outputs"
    files = {}
    for name in DELIVERABLES:
        path = outputs / name
        if not path.exists():
            raise GateError(f"cannot build manifest: {name} is missing")
        files[name] = _sha256(path)
    inputs_manifest = json.loads((run_dir / "inputs" / "inputs-manifest.json").read_text())
    manifest = {
        "run_id": run["run_id"],
        "client_id": run["client_id"],
        "period": run["period"],
        "files": files,
        "inputs_sha256": inputs_manifest["inputs_sha256"],
        "code_sha256": code_fingerprint(),
        "config_sha256": {p.name: _sha256(p) for p in config_paths},
        "delivery": json.loads((outputs / "delivery.json").read_text()),
    }
    manifest["bundle_sha256"] = _canonical(manifest)
    (outputs / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify_bundle(run: dict) -> list[str]:
    """Problems with the bundle as it is on disk now, compared with what was submitted."""
    from monthend.snapshot import verify_inputs

    run_dir = Path(run["run_dir"])
    manifest_path = run_dir / "outputs" / "manifest.json"
    if not manifest_path.exists():
        return ["no manifest: the run has not been submitted for review"]
    manifest = json.loads(manifest_path.read_text())
    problems = []
    body = {k: v for k, v in manifest.items() if k != "bundle_sha256"}
    if _canonical(body) != manifest.get("bundle_sha256"):
        problems.append("manifest.json has been edited")
    if run.get("bundle_sha256") and manifest.get("bundle_sha256") != run["bundle_sha256"]:
        problems.append("manifest does not match the bundle registered for review")
    for name, expected in manifest["files"].items():
        path = run_dir / "outputs" / name
        if not path.exists():
            problems.append(f"{name} is missing")
        elif _sha256(path) != expected:
            problems.append(f"{name} has changed since it was submitted for review")
    problems += [f"input {p}" for p in verify_inputs(run_dir / "inputs")]
    return problems


def submit_for_review(store: Store, run_id: str, config_paths: list[Path], actor: str) -> dict:
    run = store.run(run_id)
    if run is None:
        raise GateError(f"unknown run {run_id}")
    if run["state"] not in ("PREPARED", "BLOCKED", "CHANGES_REQUESTED"):
        raise GateError(f"run {run_id} is {run['state']}; only PREPARED, BLOCKED or CHANGES_REQUESTED runs can be submitted")
    validation = json.loads((Path(run["run_dir"]) / "outputs" / "validation.json").read_text())
    if validation.get("blocking"):
        raise GateError("blocking issues remain: " + "; ".join(i["message"] for i in validation["blocking"]))
    manifest = build_manifest(run, config_paths)
    sent_back = {d["bundle_sha256"] for d in store.decisions(run_id) if d["decision"] == "changes_requested"}
    if manifest["bundle_sha256"] in sent_back:
        raise GateError("this is the same version the reviewer sent back; make the requested changes before resubmitting")
    store.set_state(run_id, "READY_FOR_REVIEW", actor, "all blocking checks passed", bundle_sha256=manifest["bundle_sha256"])
    return manifest


def in_agent_session() -> bool:
    return bool(os.environ.get("MONTHEND_AGENT_SESSION"))


def record_decision(store: Store, run_id: str, *, reviewer: str, decision: str, notes: str, confirm_hash_prefix: str,
                    allowed_reviewers: list[str]) -> None:
    if in_agent_session():
        raise GateError("review decisions cannot be recorded from an agent session; a person must run this command in their own terminal")
    run = store.run(run_id)
    if run is None:
        raise GateError(f"unknown run {run_id}")
    if run["state"] != "READY_FOR_REVIEW":
        raise GateError(f"run {run_id} is {run['state']}, not READY_FOR_REVIEW")
    if reviewer not in allowed_reviewers:
        raise GateError(f"{reviewer!r} is not an authorised reviewer for this client ({', '.join(allowed_reviewers)})")
    if decision not in ("approved", "changes_requested"):
        raise GateError("decision must be 'approved' or 'changes_requested'")
    if not notes.strip():
        raise GateError("a review note is required, even if it is only 'reviewed, no changes'")
    bundle = run["bundle_sha256"] or ""
    if len(confirm_hash_prefix) < 8 or not bundle.startswith(confirm_hash_prefix.lower()):
        raise GateError("the confirmation code does not match the bundle hash on the review page; reopen the latest review page")
    problems = verify_bundle(run)
    if problems:
        raise GateError("the bundle changed after submission: " + "; ".join(problems))
    store.add_decision(run_id, reviewer, decision, notes, bundle)
    store.set_state(run_id, "APPROVED" if decision == "approved" else "CHANGES_REQUESTED", f"reviewer:{reviewer}", notes)


@dataclass(frozen=True)
class ReleaseTicket:
    run_id: str
    bundle_sha256: str
    delivery: dict
    attachment_hashes: dict = field(default_factory=dict)
    _key: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if self._key is not _TICKET_KEY:
            raise GateError("release tickets are issued only by monthend.review.issue_release_ticket")

    def check(self, *, subject: str, to: list[str], cc: list[str], attachments: list[tuple[str, bytes, str]]) -> None:
        if subject != self.delivery["subject"] or list(to) != self.delivery["to"] or list(cc) != self.delivery["cc"]:
            raise GateError("recipients or subject differ from the approved delivery payload")
        if sorted(name for name, _, _ in attachments) != sorted(self.attachment_hashes):
            raise GateError("attachments differ from the approved delivery payload")
        for name, data, _ in attachments:
            self.check_attachment(name, data)

    def check_attachment(self, filename: str, data: bytes) -> None:
        if hashlib.sha256(data).hexdigest() != self.attachment_hashes.get(filename):
            raise GateError(f"{filename} is not the approved version")

    def check_send_allowed(self) -> None:
        if self.delivery.get("mode") != "send":
            raise GateError("this client is configured for draft-only delivery; a person sends the email from Outlook")


def issue_release_ticket(store: Store, run_id: str) -> ReleaseTicket:
    run = store.run(run_id)
    if run is None:
        raise GateError(f"unknown run {run_id}")
    if run["state"] != "APPROVED":
        raise GateError(f"run {run_id} is {run['state']}; only APPROVED runs can be released")
    approvals = [d for d in store.decisions(run_id) if d["decision"] == "approved"]
    if not approvals or approvals[-1]["bundle_sha256"] != run["bundle_sha256"]:
        raise GateError("no approval matches the current bundle")
    problems = verify_bundle(run)
    if problems:
        raise GateError("the bundle changed after approval: " + "; ".join(problems))
    manifest = json.loads((Path(run["run_dir"]) / "outputs" / "manifest.json").read_text())
    delivery = manifest["delivery"]
    outputs = Path(run["run_dir"]) / "outputs"
    hashes = {name: _sha256(outputs / name) for name in delivery["attachments"]}
    return ReleaseTicket(run_id, run["bundle_sha256"], delivery, hashes, _TICKET_KEY)


def approval_status(store: Store | None, run_id: str) -> tuple[bool, str]:
    """Used by the PreToolUse hook: may an external write for this run proceed?"""
    store = store or default_store()
    try:
        issue_release_ticket(store, run_id)
        return True, "approved bundle verified"
    except GateError as exc:
        return False, str(exc)
