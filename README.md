# Month-end agent

A Claude Code agent team that prepares month-end **management packs** to the firm's Excel template, builds **referenced workpapers** from source documents, and drafts **variance commentary**, with a **human review gate** before anything is sent. It connects to Xero and Microsoft 365 (Outlook, SharePoint, Excel) through MCP servers, runs unattended overnight, and has an evaluation harness that measures whether the output is *correct*, not just whether it ran.

> **Code computes every figure. Agents explain, reference and review. People approve and release.**

## Try it in two minutes (offline, no accounts needed)

```bash
python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-lock.txt && .venv/bin/python -m pip install -e .
```

```bash
.venv/bin/python -m monthend demo
```

Open the printed `review.html`. It shows a complete September 2026 pack for **Harbour Joinery Pty Ltd**, a fictional client with realistic problems: a new unmapped expense account, a bank fee missing from Xero, an aged debtor, and an accrual that differs from its invoice. Then run the agent team in Claude Code:

```
claude
> /month-end-close harbour-joinery 2026-09
```

## What is in the box

| Requirement | Where |
|---|---|
| Management pack to an Excel template | `monthend/pack.py`. Fills the template by row and column *keys*, so the firm's own styling survives. A *Checks* sheet recomputes every subtotal with live formulas. |
| Referenced workpapers from source documents | `monthend/workpapers.py`, `extraction.py`, `evidence.py`. Bank reconciliation, accruals and receivables. Every figure carries `doc:<file>#p1:L11 [sha256]`, and the reference is re-verified. |
| Variance commentary | `.claude/agents/variance-analyst.md` plus `variance-commentary` skill. A deterministic validator (`variance.py`) checks every number, direction word and citation. |
| Human review gate | `monthend/review.py`. Approval binds to a hash of the exact bundle, including recipients. Release needs a ticket only an approved, unchanged bundle can get. |
| MCP servers | `monthend/mcp_servers/`: `monthend` (workflow), `xero` (read-only), `m365` (Outlook/SharePoint/Excel plus one gated delivery tool), `datastore` (runs, decisions, audit) |
| Subagents, skills, hooks, CLAUDE.md | `.claude/agents/` (4 least-privilege agents), `.claude/skills/` (5), `.claude/hooks/` (guard, audit, stop gate, session start), `CLAUDE.md` |
| Multi-agent orchestration | `month-end-close` skill: pack-assembler → workpaper-preparer → variance-analyst → independent-reviewer, with one bounded feedback loop |
| Overnight unattended runs | `monthend/nightly.py` on the Claude Agent SDK: spend cap, allow and deny lists, idempotent, falls back safely, morning summary. `deploy/` has launchd and systemd units. |
| Xero API (OAuth, webhooks, rate limits) | `monthend/sources/xero.py`: rotating refresh tokens or custom connections, a 60/min pacer, `Retry-After`, pagination, HMAC webhook verification, read-only by construction |
| Microsoft Graph | `monthend/sources/graph.py`: app-only auth, throttling, paging. Write methods require a release ticket. |
| PDF structured extraction | `extraction.py` (deterministic) and `llm.extract_invoice_with_claude` (structured outputs), both grounded: every extracted amount must be found in the document text. |
| Evaluation | `monthend/evaluation.py`, `evals/`: 8 golden cases, reviewer-labelled causes, hallucination probes, and mutation tests of the validator itself. CI fails the build below threshold. |
| Documentation for a non-technical reader | `docs/`, below |

## Documentation

1. [What this does](docs/01-what-this-does.md): for partners and managers
2. [Reviewer guide](docs/02-reviewer-guide.md): how to review, approve and release
3. [Installation](docs/03-installation.md)
4. [Connecting Xero and Microsoft 365](docs/04-connecting-xero-and-microsoft-365.md)
5. [Operating runbook](docs/05-operating-runbook.md): monthly routine, statuses, fixing blocked runs, overnight runs
6. [Architecture](docs/06-architecture.md)
7. [Customising the template, mapping and materiality](docs/07-customising-the-template.md)
8. [Evaluation](docs/08-evaluation.md): how we know when the output is wrong
9. [Security and controls](docs/09-security-and-controls.md): control matrix and known limitations
10. [Handover checklist](docs/10-handover-checklist.md)

## Status

| Part | State |
|---|---|
| Pack, workpapers, validator, review gate, audit log, evaluation | Working and tested: 54 tests, and the offline evaluation passes every threshold |
| MCP servers, hooks, subagents, skills | Working. The tool surface, hook decisions and agent permissions are tested. |
| Xero and Graph connectors | Implemented and tested against mocked HTTP. **Not yet run against a real Xero organisation or Microsoft tenant.** Verify on one client first ([docs/04](docs/04-connecting-xero-and-microsoft-365.md)). |
| Claude-drafted commentary scores | Run `monthend eval --engine claude` with an API key (this costs money). The included report is for the offline rule-based baseline. |

All client data in `fixtures/` is fictional.

## Development

```bash
.venv/bin/python -m pytest -q
```

```bash
.venv/bin/python -m monthend eval
```

See `CLAUDE.md` for the rules that apply to any change, human or agent.
