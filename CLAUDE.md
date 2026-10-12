# Month-end agent

Prepares month-end management packs to the firm's Excel template, builds referenced workpapers from source documents, and drafts variance commentary. A person must approve before anything leaves the firm.

## The one rule

**Code computes every figure. Agents explain, reference and review. People approve and release.**

- Figures come from `monthend/pack.py` and `monthend/workpapers.py`, in `Decimal`, from a frozen snapshot of the inputs. Never compute, round or restate a figure in prose or in a tool argument.
- Every claim in commentary cites an evidence id that `EvidenceIndex.resolve` can find (`monthend/evidence.py`).
- Approval and release happen only through `monthend/review.py`. No MCP tool approves anything. Agents cannot run the approve or release commands: the PreToolUse hook, the settings deny rules and `MONTHEND_AGENT_SESSION` all refuse them.

## Running it

| Task | How |
|---|---|
| Month-end for a client | `/month-end-close <client_id> <YYYY-MM>` (skill: `.claude/skills/month-end-close`) |
| Offline demo | `.venv/bin/python -m monthend demo` |
| Tests | `.venv/bin/python -m pytest` |
| Evaluation (offline) | `.venv/bin/python -m monthend eval` |
| Evaluation (Claude drafts) | `.venv/bin/python -m monthend eval --engine claude` (calls the API, costs money; ask first) |
| Overnight run | `.venv/bin/python -m monthend nightly` (see `docs/05-operating-runbook.md`) |

## Agent team (`.claude/agents/`)

`pack-assembler` prepares and triages checks. `workpaper-preparer` adds preparer notes. `variance-analyst` drafts commentary until the validator passes. `independent-reviewer` is read-only and records findings. The orchestrating session follows the `month-end-close` skill.

## MCP servers (`.mcp.json`, code in `monthend/mcp_servers/`)

`monthend` (workflow), `xero` (read-only Accounting API), `m365` (Outlook, SharePoint, Excel; one gated delivery tool), `datastore` (runs, decisions, audit log). Backend is `fixtures` or `live` per client config.

## Changing the code

- Keep `monthend/store.py`, `monthend/review.py`, `monthend/snapshot.py`, `monthend/config.py`, `monthend/money.py` and `monthend/sources/xero_parse.py` standard-library only. The hooks import them with the system Python.
- A change to pack, workpaper or validator logic needs the tests and `monthend eval` to pass. If you change what "correct" means, change `evals/cases/` in the same commit and say why in the commit message.
- Never weaken a check to make an eval pass. Fix the cause, or add a case that shows why the check was wrong. `docs/08-evaluation.md` has an example.
- Client-specific behaviour belongs in `config/`, not in code.
- `var/` holds runs, the database and secrets. It is never committed and never edited by hand.

## Modes

`MONTHEND_MODE=operate` (set by the overnight runner) also blocks file edits to code, config, evals and `.claude/`, and limits the shell to read-only `monthend` commands. In development mode those are open, but the review-gate protections always apply.
