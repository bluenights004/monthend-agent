"""The human review gate: nothing is approved by an agent, nothing changed is released."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from monthend import pipeline
from monthend.review import GateError, ReleaseTicket, issue_release_ticket, record_decision
from monthend.store import Store
from monthend.variance import draft_rule_based

REVIEWERS = ["Alex Reviewer", "Sam Manager"]


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MONTHEND_VAR_DIR", str(tmp_path))
    monkeypatch.delenv("MONTHEND_AGENT_SESSION", raising=False)
    store = Store(tmp_path / "monthend.db")
    run = pipeline.prepare("harbour-joinery", "2026-09", backend_name="fixtures", store=store, actor="test")
    ctx = pipeline.load(run["run_id"], store)
    pipeline.save_commentary(run["run_id"], draft_rule_based(ctx.pack, pipeline.all_contexts(ctx)), actor="test", store=store)
    result = pipeline.finalise(run["run_id"], actor="test", store=store)
    assert result["state"] == "READY_FOR_REVIEW"
    return {"store": store, "run_id": run["run_id"], "bundle": result["bundle_sha256"], "outputs": Path(result["review_page"]).parent}


def approve(env, **overrides):
    args = dict(reviewer="Alex Reviewer", decision="approved", notes="Reviewed, agree.", confirm_hash_prefix=env["bundle"][:8],
                allowed_reviewers=REVIEWERS)
    args.update(overrides)
    record_decision(env["store"], env["run_id"], **args)


def test_cannot_release_before_approval(env):
    with pytest.raises(GateError, match="only APPROVED"):
        issue_release_ticket(env["store"], env["run_id"])


def test_agent_session_cannot_approve(env, monkeypatch):
    monkeypatch.setenv("MONTHEND_AGENT_SESSION", "claude-code")
    with pytest.raises(GateError, match="agent session"):
        approve(env)


def test_unknown_reviewer_and_wrong_code_refused(env):
    with pytest.raises(GateError, match="not an authorised reviewer"):
        approve(env, reviewer="Claude")
    with pytest.raises(GateError, match="confirmation code"):
        approve(env, confirm_hash_prefix="deadbeef")
    with pytest.raises(GateError, match="review note"):
        approve(env, notes=" ")


def test_approve_then_release_to_outbox(env):
    approve(env)
    ref = pipeline.release(env["run_id"], actor="test", channel="outbox", store=env["store"])
    assert ref.endswith(".eml") and Path(ref).exists()
    assert env["store"].run(env["run_id"])["state"] == "RELEASED"
    assert env["store"].verify_audit_chain() == []


def test_edit_after_approval_blocks_release(env):
    approve(env)
    commentary = env["outputs"] / "commentary.json"
    data = json.loads(commentary.read_text())
    data["summary"] += " Edited after approval."
    commentary.write_text(json.dumps(data))
    with pytest.raises(GateError, match="changed after approval"):
        issue_release_ticket(env["store"], env["run_id"])


def test_edit_before_approval_blocks_approval(env):
    (env["outputs"] / "pack.xlsx").write_bytes(b"tampered")
    with pytest.raises(GateError, match="changed after submission"):
        approve(env)


def test_tickets_cannot_be_forged_and_check_payload(env):
    with pytest.raises(GateError, match="issued only by"):
        ReleaseTicket("x", "y", {})
    approve(env)
    ticket = issue_release_ticket(env["store"], env["run_id"])
    pack = (env["outputs"] / "pack.xlsx").read_bytes()
    with pytest.raises(GateError, match="recipients"):
        ticket.check(subject=ticket.delivery["subject"], to=["someone@else.example"], cc=[], attachments=[("pack.xlsx", pack, "x")])
    with pytest.raises(GateError, match="not the approved version"):
        ticket.check_attachment("pack.xlsx", pack + b"x")
    with pytest.raises(GateError, match="draft-only"):
        ticket.check_send_allowed()


def test_changes_requested_then_revised_needs_resubmission(env):
    approve(env, decision="changes_requested", notes="Explain materials better.")
    ctx = pipeline.load(env["run_id"], env["store"])
    commentary = draft_rule_based(ctx.pack, pipeline.all_contexts(ctx))
    pipeline.save_commentary(env["run_id"], commentary, actor="test", store=env["store"])
    assert env["store"].run(env["run_id"])["state"] == "PREPARED"
    # Resubmitting the version the reviewer sent back is refused.
    unchanged = pipeline.finalise(env["run_id"], actor="test", store=env["store"])
    assert unchanged["state"] == "BLOCKED" and unchanged["blocking"][0]["code"] == "RESUBMITTED_UNCHANGED"
    commentary.items[1].text += " Timberco raised hardwood prices by 8% from 1 September."
    commentary.items[1].drivers[0].evidence.append("email:msg-timberco-0820")
    pipeline.save_commentary(env["run_id"], commentary, actor="test", store=env["store"])
    result = pipeline.finalise(env["run_id"], actor="test", store=env["store"])
    assert result["state"] == "READY_FOR_REVIEW"
    with pytest.raises(GateError, match="confirmation code"):
        approve(env)  # the old code belongs to the old version
    approve(env, confirm_hash_prefix=result["bundle_sha256"][:8])


def test_new_source_data_supersedes_and_unchanged_data_does_not(env, monkeypatch):
    again = pipeline.prepare("harbour-joinery", "2026-09", backend_name="fixtures", store=env["store"], skip_if_unchanged=True, actor="test")
    assert again["run_id"] == env["run_id"]
    newer = pipeline.prepare("harbour-joinery", "2026-09", backend_name="fixtures", store=env["store"],
                             overlays=[{"op": "remove_message", "id": "msg-sparky-0917"}], skip_if_unchanged=True, actor="test")
    assert newer["run_id"] != env["run_id"]
    assert env["store"].run(env["run_id"])["state"] == "SUPERSEDED"


def test_audit_chain_detects_tampering(env):
    with env["store"].connect() as db:
        db.execute("UPDATE events SET actor = 'someone-else' WHERE id = 2")
    assert env["store"].verify_audit_chain()
