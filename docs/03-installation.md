# Installation

*For whoever sets up the machine that runs the system. About 20 minutes.*

## What you need

- A Mac, Linux server or Windows machine with WSL that stays on overnight, with reliable internet and backup power.
- Python 3.11 or newer (`python3 --version`).
- Claude Code (`npm install -g @anthropic-ai/claude-code`, then `claude` once to sign in). This runs the agent team, interactively and overnight.
- For live data: a Xero app and a Microsoft Entra app registration ([04-connecting-xero-and-microsoft-365.md](04-connecting-xero-and-microsoft-365.md)).

## Steps

1. Get the code:

```bash
git clone <your repository url> monthend-agent
```

2. Create the environment and install. Run these from inside the `monthend-agent` folder:

```bash
python3 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r requirements-lock.txt
```

```bash
.venv/bin/python -m pip install -e .
```

3. Check it works with the built-in demo client (no accounts or keys needed):

```bash
.venv/bin/python -m pytest -q
```

```bash
.venv/bin/python -m monthend demo
```

The demo prints the path to a review page. Open it in a browser. You are looking at a complete pack for the fictional client Harbour Joinery, with rule-based commentary.

4. Open Claude Code in the folder and run the agent team on the demo client:

```bash
claude
```

Then type `/month-end-close harbour-joinery 2026-09`. The first time, Claude Code asks you to trust the folder and approve the project's MCP servers. Say yes. It then runs the four agents and hands you a review page.

5. Optional: set up the overnight run ([05-operating-runbook.md](05-operating-runbook.md#overnight-runs)).

## Where things live

| Path | What |
|---|---|
| `config/clients/*.json` | One file per client: data source, template, materiality, workpapers, reviewers, delivery |
| `config/mappings/*.json` | Xero account to pack line mapping |
| `templates/` | Excel template(s) |
| `var/` | Runtime data: runs, database, tokens, logs. **Back this up. Never commit it.** |
| `evals/` | Test cases and reports |
| `.claude/` | Agent definitions, skills and hooks |
| `docs/` | This documentation |
