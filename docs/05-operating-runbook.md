# Operating runbook

*For the person who runs month-end with the system. Written so the firm is not dependent on the person who built it.*

## A normal month

| When | What | Who |
|---|---|---|
| Overnight, working days 1-10 | The system prepares each scheduled client for last month. If the Xero data or documents have not changed since the last run, it does nothing. | Automatic |
| Each morning | Read `var/status/latest.md` (or the Teams/Slack message). For each client it says *ready for review*, *blocked* (with the reason), or *failed*. | Operator |
| As packs become ready | The reviewer opens the review page and approves or requests changes ([02-reviewer-guide.md](02-reviewer-guide.md)). | Reviewer |
| After approval | `monthend release --run <id>`. Then send the Outlook draft. | Operator |

To run a client by hand at any time, open Claude Code in the project folder and type:

```
/month-end-close <client_id> <YYYY-MM>
```

## Statuses

| Status | Meaning | What to do |
|---|---|---|
| PREPARED | Figures and workpapers built; commentary not finished | Wait for the agent, or run `/month-end-close` |
| BLOCKED | A blocking check failed | Read the reason on the review page and fix it at source (see below) |
| READY_FOR_REVIEW | All checks passed | Reviewer reviews |
| CHANGES_REQUESTED | Reviewer sent it back | Run `/month-end-close <client> <period> run_id=<id>`; the agent revises using the reviewer's note |
| APPROVED | Reviewer approved this exact version | Release |
| RELEASED | Delivered | Nothing |
| SUPERSEDED | Newer source data arrived; a newer run replaces this one | Use the newer run |

## Fixing blocked runs

| Message says | Usual cause | Fix |
|---|---|---|
| Account X is not mapped | New account in Xero | Add it to the right line in `config/mappings/<mapping>.json`, then re-run. *This is a configuration change; get it reviewed.* |
| Trial balance does not balance | Data problem in Xero, or Xero was mid-update | Re-run later; if it persists, check Xero |
| Unexplained bank reconciliation difference | Missing or duplicate transaction in Xero, or the wrong statement | Ask the client or bookkeeper to correct Xero; re-run |
| Bank statement not found | Statement not saved to the SharePoint period folder, or named differently | Save it as configured (`workpapers[].options.statement`) |
| Accruals/receivables do not agree to the ledger | Schedule out of date, or a manual journal | Update the schedule or correct the journal |
| Commentary issues | Agent could not evidence a number or cause | Re-run `/month-end-close`; if it still fails, the evidence may be missing (ask the client) |
| Same version the reviewer sent back | Revision made no change | Make the requested change |

After fixing at source, re-run. The new data creates a new run automatically.

## Overnight runs

The overnight job is `deploy/run-nightly.sh`. Install it once:

- **macOS:** edit the paths in `deploy/com.yourfirm.monthend.nightly.plist`, copy it to `~/Library/LaunchAgents/` and `launchctl load` it.
- **Linux:** copy `deploy/monthend-nightly.service` and `.timer` to `/etc/systemd/system/`, then `systemctl enable --now monthend-nightly.timer`.
- **Windows:** create a Task Scheduler task that runs `deploy\run-nightly.sh` under WSL at 02:00 on weekdays.

What it does, per client: prepare → Claude agent team (through the Claude Agent SDK, with a spending cap per client, set in `config/schedule.json`) → finalise → status file. If the agent stage fails (no network, API outage, cap reached), it falls back to rule-based commentary marked as such, so the reviewer still gets a pack and knows the commentary needs more care. It never approves or sends.

Health check: `var/status/heartbeat` holds the time the last run finished. If it is more than a day old on a working day, the job is not running. Check the logs in `var/logs/`.

## Adding a client

1. Copy `config/clients/harbour-joinery.json` to `config/clients/<new-id>.json` and edit it: name, tenant id, SharePoint folder, mapping, template, materiality, workpapers, reviewers and delivery.
2. If their chart of accounts differs, copy and adjust a mapping file ([07-customising-the-template.md](07-customising-the-template.md)).
3. Run one past month and compare it with Xero (see the checklist in [04-connecting-xero-and-microsoft-365.md](04-connecting-xero-and-microsoft-365.md)).
4. Add the id to `config/schedule.json`.

## Routine maintenance

| How often | Task |
|---|---|
| Weekly | `monthend audit`. It confirms the audit log has not been altered. |
| Monthly | Check `evals/reports/` after any change. CI runs the evaluation on every commit. |
| Quarterly | Rotate the Xero and Microsoft client secrets. Review the reviewer lists. Restore-test a backup of `var/`. |
| Every 60 days at most (standard Xero app) | Make sure each Xero connection is used at least once, or the refresh token expires. The nightly status reports "a person must reconnect Xero" if this happens; run `monthend connect xero`. |

## Costs

- Claude: the overnight cap per client is in `config/schedule.json` (default USD 5). Actual spend per run is in the morning status. Unchanged data costs nothing.
- Xero and Microsoft 365 API use is within the standard plans.

## Backups and recovery

Back up `var/` daily (runs, `monthend.db`, `secrets/`). To recover, restore `var/` and run `monthend audit` to confirm the log chain is intact. Runs are self-contained folders: each includes its inputs, outputs and manifest, so a restored run can be re-verified without Xero.
