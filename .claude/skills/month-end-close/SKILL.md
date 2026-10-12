---
name: month-end-close
description: Run a client's month-end close - prepare the pack and workpapers from Xero and Microsoft 365, draft referenced variance commentary, get an independent agent review, and submit for human review. Use when asked to prepare, run or redo month-end, management accounts or a management pack.
argument-hint: <client_id> <YYYY-MM> [run_id=<existing run>]
---

# Month-end close

You orchestrate four specialist subagents. Code computes every figure. Agents explain, reference and review. A person approves and releases. Nothing is sent from this workflow.

## Steps

1. **Prepare.** If a `run_id` was given, use it and skip to step 2. Otherwise delegate to the **pack-assembler** subagent with the client id and period. Read its summary.
   - If any check is `block`, stop after step 1. Tell the user what blocks the run and what they need to do. Blocked runs cannot be reviewed, so drafting commentary would waste effort.

2. **Workpapers.** Delegate to the **workpaper-preparer** subagent with the run id.

3. **Commentary.** Delegate to the **variance-analyst** subagent with the run id. It iterates against the validator until the draft passes. If it reports that it could not pass, show the user the remaining issues and stop.

4. **Independent review.** Delegate to the **independent-reviewer** subagent with the run id. It records findings and cannot edit.
   - If it raises a `high` finding about the commentary, send the finding back to the variance-analyst once, then repeat the independent review once. Do not loop further. Leave the rest to the human reviewer.

5. **Finalise.** Call `mcp__monthend__finalise_run`. It renders the deliverables, runs every check and either submits the bundle for human review or marks it BLOCKED.

6. **Hand over.** Tell the user, in plain English:
   - the state, and if ready, the review page path and the 8-character confirmation code
   - the main points of the commentary, in one or two sentences
   - the warnings and independent-review findings that the reviewer should look at
   - the command the reviewer types in their own terminal: `monthend review approve --run <run_id>` (or `request-changes` to send it back)

## Rules

- Never compute, round or restate a figure differently from the tools.
- Never attempt to approve, request changes or release. Those commands are blocked for agents, and trying them is a failure of this skill.
- Never edit files under `var/`, `config/` or `evals/`. Proposed mapping changes go to the user as text.
- If a tool returns `refused_by_review_gate`, report the reason. Do not look for a way around it.
