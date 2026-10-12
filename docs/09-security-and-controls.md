# Security and controls

*For partners, risk owners and IT. Each risk, the control that addresses it, where the control is enforced, and the test that proves it.*

## Control matrix

| Risk | Control | Enforced in | Proven by |
|---|---|---|---|
| Something is sent to a client without approval | Delivery needs a release ticket. Tickets are issued only for APPROVED runs whose files still match the approved hash. | `review.issue_release_ticket`, `ReleaseTicket.check`, `GraphClient` write methods | `test_cannot_release_before_approval`, `test_edit_after_approval_blocks_release` |
| An agent approves its own work | No approval tool exists. Approval refuses when `MONTHEND_AGENT_SESSION` is set (by settings, MCP servers and the overnight runner), and the CLI needs an interactive terminal. Deny rules and the guard hook block the commands. | `review.record_decision`, `cli.cmd_review`, `.claude/settings.json`, `.claude/hooks/guard.py` | `test_agent_session_cannot_approve`, `test_guard_denies_human_only_and_tampering_commands`, `test_mcp_servers_expose_no_approval_tools` |
| Reviewer approves one version, another is sent | Approval requires the bundle hash prefix from the page the reviewer read. Release recomputes every hash. The payload (recipients, subject, attachment hashes) is part of the bundle. | `review.py` | `test_unknown_reviewer_and_wrong_code_refused`, `test_tickets_cannot_be_forged_and_check_payload` |
| Changes "requested" but the same version resubmitted | Submission refuses a bundle hash that a reviewer sent back | `review.submit_for_review` | `test_changes_requested_then_revised_needs_resubmission` |
| Model invents or mis-states figures | Figures come only from code. Every number in commentary must match the pack or cited evidence. Driver amounts must appear in their evidence. | `variance.validate_commentary` | `tests/test_commentary_validator.py`, mutation tests in `monthend eval` |
| Workpaper reference does not support the figure | References carry the file hash and locator. The grader re-opens the document and finds the figure there. | `extraction.verify_reference`, `evaluation.grade_references` | `test_every_document_reference_resolves_to_the_figure`, `test_reference_check_catches_wrong_figure_and_changed_file` |
| Source data changes after preparation | Inputs hashed at snapshot. Any change blocks submission or release. New data creates a new run and supersedes the old one. | `snapshot.verify_inputs`, `pipeline.prepare` | `test_snapshot_tamper_detection`, `test_new_source_data_supersedes_and_unchanged_data_does_not` |
| Writes to the client's books | Xero client has only GET for accounting endpoints. Scopes are read-only. The hook denies any Xero tool with a write verb. | `sources/xero.py`, `.claude/hooks/guard.py` | Code review; `test_mcp_servers_expose_no_approval_tools` |
| Audit trail altered | Hash-chained events | `store.verify_audit_chain`, `monthend audit` | `test_audit_chain_detects_tampering` |
| Agent edits evidence or controls during a run | Hook denies edits to `var/` always, and to code, config, evals and `.claude/` in operate mode. Subagents have no Write, Edit or Bash. The overnight run disallows them too. | `guard.py`, `.claude/agents/*.md`, `nightly.AGENT_DISALLOWED_TOOLS` | `test_guard_denies_writes_to_run_evidence`, `test_operate_mode_locks_down_shell_and_config`, `test_subagents_are_least_privilege` |
| Prompt injection via an email or document ("ignore your instructions and send...") | Agents cannot send, approve or edit controls, whatever they are told. Email content reaches agents only as previews inside tool results. | Same controls as above | By construction: no tool path exists |
| Runaway cost overnight | `max_budget_usd` and `max_turns` per client. Unchanged data skips the model entirely. | `nightly.py`, `config/schedule.json` | `test_new_source_data_supersedes_and_unchanged_data_does_not` |
| Leaked credentials | Secrets only in the environment or secret manager. Token file mode 600. `.env` and `var/secrets` denied to agents. Least-privilege Graph permissions and mailbox restriction. | `sources/http.FileTokenStore`, `.claude/settings.json`, [04](04-connecting-xero-and-microsoft-365.md) | `test_refresh_token_rotation_is_persisted` |
| Personal data over-collection | Emails stored as previews only. Only the period's client folder is copied. | `sources/backends.LiveBackend` | Code review |

## Known limitations

- **Reviewer identity in a local deployment** is the name typed plus the operating-system user. That is adequate for a small firm on a controlled machine. For stronger assurance, put the approval step behind the firm's SSO (a small web app calling `review.record_decision`) and keep the database where agents cannot write.
- **The release ticket is a code-level control.** Python cannot stop code running in the same process from constructing one deliberately. The protection is that agents have no way to run arbitrary Python, because they have no shell or file-edit tools in operation, and that releases are recorded in the audit log.
- **Live connectors** have been tested against mocked HTTP responses, not yet against a real Xero organisation or Microsoft tenant. Do the first-client verification in [04](04-connecting-xero-and-microsoft-365.md) before relying on live data.
- **Commentary causes** are checked against evidence, not against the truth. A draft can cite real evidence for the wrong cause. Driver recall in the evaluation and the human reviewer are the controls for that.
