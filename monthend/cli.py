"""Command line for operators and reviewers. Run `monthend --help` (or `python -m monthend --help`)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from monthend.review import GateError


def _print(data) -> None:
    print(json.dumps(data, indent=2, default=str))


def cmd_demo(args) -> int:
    from monthend import pipeline
    from monthend.variance import draft_rule_based

    run = pipeline.prepare(args.client, args.period, backend_name="fixtures", actor="operator:demo")
    ctx = pipeline.load(run["run_id"])
    commentary = draft_rule_based(ctx.pack, pipeline.all_contexts(ctx))
    pipeline.save_commentary(run["run_id"], commentary, actor="operator:demo")
    result = pipeline.finalise(run["run_id"], actor="operator:demo")
    print(f"Run:          {result['run_id']}")
    print(f"State:        {result['state']}")
    print(f"Blocking:     {len(result['blocking'])}   Warnings: {len(result['warnings'])}")
    if result["bundle_sha256"]:
        print(f"Confirm code: {result['bundle_sha256'][:8]}")
    print(f"Review page:  {result['review_page']}")
    print(f"Pack:         {Path(result['review_page']).with_name('pack.xlsx')}")
    print(f"Workpapers:   {Path(result['review_page']).with_name('workpapers.xlsx')}")
    print("\nThis demo used rule-based commentary. For Claude-drafted commentary run the month-end-close skill in Claude Code, "
          "or `monthend commentary draft --engine claude`.")
    return 0


def cmd_prepare(args) -> int:
    from monthend import pipeline

    run = pipeline.prepare(args.client, args.period, backend_name=args.backend, skip_if_unchanged=args.skip_if_unchanged,
                           actor="operator")
    _print({k: run[k] for k in ("run_id", "state", "run_dir", "inputs_sha256")})
    return 0


def cmd_runs(args) -> int:
    from monthend.store import default_store

    rows = default_store().runs(args.client, args.period, tuple(args.state or ()))
    for r in rows:
        print(f"{r['run_id']:58} {r['state']:18} {(r['bundle_sha256'] or '')[:8]:8} {r['state_reason'] or ''}")
    return 0


def cmd_context(args) -> int:
    from monthend import pipeline

    _print(pipeline.context_for(args.run, args.line))
    return 0


def cmd_commentary(args) -> int:
    from monthend import pipeline
    from monthend.variance import Commentary, draft_rule_based, validate_commentary

    if args.action == "draft":
        ctx = pipeline.load(args.run)
        if args.engine == "rules":
            commentary = draft_rule_based(ctx.pack, pipeline.all_contexts(ctx))
        else:
            from monthend.llm import draft_commentary_with_claude

            commentary, trace = draft_commentary_with_claude(ctx.pack, pipeline.all_contexts(ctx), ctx.index, model=args.model)
            _print({"attempts": trace})
        report = pipeline.save_commentary(args.run, commentary, actor=f"operator:{args.engine}")
    elif args.action == "import":
        commentary = Commentary.model_validate_json(Path(args.file).read_text())
        report = pipeline.save_commentary(args.run, commentary, actor="operator:import")
    else:
        ctx = pipeline.load(args.run)
        path = Path(args.file) if args.file else ctx.outputs / "commentary.json"
        report = validate_commentary(Commentary.model_validate_json(path.read_text()), ctx.pack, ctx.index)
    _print(report.to_json())
    return 0 if report.ok else 1


def cmd_finalise(args) -> int:
    from monthend import pipeline

    result = pipeline.finalise(args.run, actor="operator")
    _print(result)
    return 0 if result["state"] == "READY_FOR_REVIEW" else 1


def cmd_review(args) -> int:
    from monthend.config import load_client
    from monthend.review import record_decision
    from monthend.store import default_store

    store = default_store()
    run = store.run(args.run)
    if run is None:
        raise GateError(f"unknown run {args.run}")
    if args.action == "show":
        _print({"run": run, "decisions": store.decisions(args.run),
                "review_page": str(Path(run["run_dir"]) / "outputs" / "review.html")})
        return 0
    if not sys.stdin.isatty():
        raise GateError("review decisions must be made interactively by a person at a terminal")
    reviewer = args.reviewer or input("Your name (as listed for this client): ").strip()
    code = args.code or input("Confirmation code from the review page: ").strip()
    notes = args.notes or input("Review note: ").strip()
    decision = "approved" if args.action == "approve" else "changes_requested"
    if decision == "approved":
        answer = input(f"Approve {args.run} for release to {run['client_id']}? Type 'approve' to confirm: ").strip().lower()
        if answer != "approve":
            print("Not approved.")
            return 1
    record_decision(store, args.run, reviewer=reviewer, decision=decision, notes=notes, confirm_hash_prefix=code,
                    allowed_reviewers=load_client(run["client_id"]).reviewers)
    print(f"Recorded: {decision} by {reviewer}.")
    return 0


def cmd_release(args) -> int:
    from monthend import pipeline
    from monthend.store import os_user

    ref = pipeline.release(args.run, actor=f"operator:{os_user()}", channel=args.channel)
    print(f"Released: {ref}")
    return 0


def cmd_eval(args) -> int:
    from monthend.evaluation import run_evaluation

    report = run_evaluation(engine=args.engine, cases=args.case, judge=args.judge, trials=args.trials)
    print(report["markdown"])
    return 0 if report["passed"] else 1


def cmd_nightly(args) -> int:
    from monthend.nightly import run_nightly

    status = run_nightly(clients=args.client, period=args.period, agent=args.agent, max_budget_usd=args.max_budget_usd)
    _print(status)
    return 0 if status["ok"] else 1


def cmd_audit(args) -> int:
    from monthend.store import default_store

    problems = default_store().verify_audit_chain()
    print("Audit log intact." if not problems else "\n".join(problems))
    return 0 if not problems else 1


def cmd_connect(args) -> int:
    from monthend.connect import connect_xero

    connect_xero(port=args.port)
    return 0


def cmd_webhooks(args) -> int:
    from monthend.webhooks import serve

    serve(port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="monthend", description="Month-end packs, workpapers and commentary behind a human review gate.")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("demo", help="offline end-to-end demo on the synthetic client")
    s.add_argument("--client", default="harbour-joinery")
    s.add_argument("--period", default="2026-09")
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("prepare", help="snapshot sources and build pack + workpapers")
    s.add_argument("--client", required=True)
    s.add_argument("--period", required=True, help="YYYY-MM")
    s.add_argument("--backend", choices=["fixtures", "live"])
    s.add_argument("--skip-if-unchanged", action="store_true")
    s.set_defaults(func=cmd_prepare)

    s = sub.add_parser("runs", help="list runs")
    s.add_argument("--client")
    s.add_argument("--period")
    s.add_argument("--state", action="append")
    s.set_defaults(func=cmd_runs)

    s = sub.add_parser("context", help="print the variance context for one pack line")
    s.add_argument("--run", required=True)
    s.add_argument("--line", required=True)
    s.set_defaults(func=cmd_context)

    s = sub.add_parser("commentary", help="draft, import or validate commentary")
    s.add_argument("action", choices=["draft", "import", "validate"])
    s.add_argument("--run", required=True)
    s.add_argument("--engine", choices=["rules", "claude"], default="rules")
    s.add_argument("--model")
    s.add_argument("--file")
    s.set_defaults(func=cmd_commentary)

    s = sub.add_parser("finalise", help="render deliverables, run checks, submit for review")
    s.add_argument("--run", required=True)
    s.set_defaults(func=cmd_finalise)

    s = sub.add_parser("review", help="show a run, or record a human decision")
    s.add_argument("action", choices=["show", "approve", "request-changes"])
    s.add_argument("--run", required=True)
    s.add_argument("--reviewer")
    s.add_argument("--code", help="first 8 characters of the bundle hash on the review page")
    s.add_argument("--notes")
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("release", help="deliver an approved run (draft email / upload)")
    s.add_argument("--run", required=True)
    s.add_argument("--channel", choices=["outbox", "graph"])
    s.set_defaults(func=cmd_release)

    s = sub.add_parser("eval", help="run the evaluation harness")
    s.add_argument("--engine", default="rules", help="rules | claude | path to a commentary JSON for the base case")
    s.add_argument("--case", action="append", help="limit to case id (repeatable)")
    s.add_argument("--judge", action="store_true", help="add LLM rubric scores (calls the Claude API)")
    s.add_argument("--trials", type=int, default=1, help="repeat model-drafted cases to measure variability")
    s.set_defaults(func=cmd_eval)

    s = sub.add_parser("nightly", help="unattended overnight run")
    s.add_argument("--client", action="append", help="default: every client in config/schedule.json")
    s.add_argument("--period", help="default: previous calendar month")
    s.add_argument("--agent", choices=["sdk", "none"], default="sdk")
    s.add_argument("--max-budget-usd", type=float, default=5.0)
    s.set_defaults(func=cmd_nightly)

    s = sub.add_parser("audit", help="verify the hash-chained audit log")
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("connect", help="connect Xero (one-time OAuth consent)")
    s.add_argument("service", choices=["xero"])
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_connect)

    s = sub.add_parser("webhooks", help="receive Xero webhooks and queue re-runs")
    s.add_argument("--port", type=int, default=8780)
    s.set_defaults(func=cmd_webhooks)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.func(args)
    except GateError as exc:
        print(f"Refused by the review gate: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"Missing file: {exc}", file=sys.stderr)
        return 3
