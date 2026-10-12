"""The review page a person reads before approving: one self-contained HTML file."""

from __future__ import annotations

import html
from decimal import Decimal

from monthend.money import q2
from monthend.store import Store
from monthend.variance import Commentary

CSS = """
:root{--bg:#fff;--fg:#1d2433;--muted:#5b6475;--line:#d9dee7;--panel:#f5f7fa;--accent:#1f3a5f;--ok:#1d7a46;--warn:#9a6700;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#12161d;--fg:#e6e9ef;--muted:#9aa4b5;--line:#2b3340;--panel:#1a2029;--accent:#8fb4e3;--ok:#4cc38a;--warn:#e3b341;--bad:#ff7b72}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:32px 0 8px;color:var(--accent)}
.muted{color:var(--muted)}.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:12px 0}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:13px;border:1px solid currentColor}
.READY_FOR_REVIEW,.APPROVED,.RELEASED{color:var(--ok)}.BLOCKED,.SUPERSEDED{color:var(--bad)}.PREPARED,.CHANGES_REQUESTED{color:var(--warn)}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}tr.total td{font-weight:600}
.block{color:var(--bad)}.warn{color:var(--warn)}.info{color:var(--muted)}code{font-size:12.5px;word-break:break-all}
.code{font:600 22px ui-monospace,Menlo,monospace;letter-spacing:2px}.wrap{overflow-x:auto}details summary{cursor:pointer}
.mat{font-size:12px;font-weight:600;color:var(--warn)}
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _n(value) -> str:
    if value is None:
        return ""
    value = Decimal(str(value))
    text = f"{abs(q2(value)):,.0f}"
    return f"({text})" if value < 0 else text


def render_review_page(ctx, run: dict, validation: dict, commentary: Commentary, manifest: dict | None, store: Store) -> None:
    pack = ctx.pack
    bundle = run.get("bundle_sha256") or ""
    out = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>Review {_e(pack.client_name)} {_e(pack.period_label)}</title><style>{CSS}</style></head><body><main>"]
    out.append(f"<h1>{_e(pack.client_name)} - management pack {_e(pack.period_label)}</h1>")
    out.append(f"<div class='muted'>Run <code>{_e(run['run_id'])}</code> &middot; status <span class='badge {_e(run['state'])}'>"
               f"{_e(run['state'].replace('_', ' ').title())}</span></div>")

    if run["state"] == "READY_FOR_REVIEW" and manifest:
        delivery = manifest["delivery"]
        out.append("<div class='panel'><strong>What you are approving.</strong> Approving records your name against this exact version. "
                   "If any file changes afterwards, the approval no longer applies and nothing can be sent.")
        out.append(f"<p>Confirmation code: <span class='code'>{_e(bundle[:8])}</span> <span class='muted'>(first 8 characters of bundle "
                   f"<code>{_e(bundle)}</code>)</span></p>")
        out.append(f"<p>On release: {'an Outlook <b>draft</b> is created for a person to send' if delivery['mode'] == 'draft' else 'the email is <b>sent</b>'} "
                   f"to <b>{_e(', '.join(delivery['to']))}</b>{(' cc ' + _e(', '.join(delivery['cc']))) if delivery['cc'] else ''}, subject "
                   f"&ldquo;{_e(delivery['subject'])}&rdquo;, attaching {_e(', '.join(delivery['attachments']))}.</p>")
        out.append("<p>To approve, in your own terminal (not in Claude):<br><code>monthend review approve --run "
                   f"{_e(run['run_id'])} --reviewer \"Your Name\" --code {_e(bundle[:8])} --notes \"...\"</code><br>"
                   "To send it back: same command with <code>review request-changes</code>.</p></div>")
    elif run["state"] == "BLOCKED":
        out.append("<div class='panel block'><strong>Not ready for review.</strong> The blocking issues below must be resolved first. "
                   "This page is for information only.</div>")

    out.append("<h2>Checks</h2>")
    if not validation["blocking"] and not validation["warnings"]:
        out.append("<p>All checks passed with no warnings.</p>")
    out.append("<ul>")
    for item in validation["blocking"]:
        out.append(f"<li class='block'><b>Blocking</b> ({_e(item['source'])}): {_e(item['message'])}</li>")
    for item in validation["warnings"]:
        out.append(f"<li class='warn'><b>Check</b> ({_e(item['source'])}): {_e(item['message'])}</li>")
    out.append("</ul>")

    independent = validation.get("independent_review")
    out.append("<h2>Independent agent review</h2>")
    if independent and independent.get("findings"):
        out.append("<p class='muted'>A separate read-only agent reviewed the draft against the checklist. Its findings are advisory.</p><ul>")
        for f in independent["findings"]:
            out.append(f"<li class='{_e('block' if f['severity'] == 'high' else 'warn' if f['severity'] == 'medium' else 'info')}'>"
                       f"<b>{_e(f['severity'])}</b> {_e(f['area'])}: {_e(f['finding'])}</li>")
        out.append("</ul>")
    else:
        out.append("<p class='muted'>No independent agent review was recorded for this run.</p>")

    out.append("<h2>Commentary</h2>")
    out.append(f"<div class='panel'>{_e(commentary.summary)}</div><p class='muted'>Drafted by {_e(commentary.author or 'unknown')}. "
               f"Coverage {validation['commentary_metrics'].get('coverage', 0):.0%}, numbers traced "
               f"{validation['commentary_metrics'].get('numbers_traced', 0)}/{validation['commentary_metrics'].get('numbers_checked', 0)}.</p>")
    for item in commentary.items:
        try:
            line = pack.line(item.line_key)
        except KeyError:
            continue
        v = line.values
        out.append(f"<div class='panel'><b>{_e(line.label)}</b> <span class='muted'>actual {_n(v['month_actual'])} &middot; budget "
                   f"{_n(v['month_budget'])} &middot; variance {_n(v['month_var'])}</span><p>{_e(item.text)}</p>")
        if item.drivers:
            out.append("<details><summary>Evidence</summary><ul>")
            for driver in item.drivers:
                out.append(f"<li>{_e(driver.description)}{(' - ' + _n(driver.amount)) if driver.amount is not None else ''}<ul>")
                for ev_id in driver.evidence:
                    ev = ctx.index.resolve(ev_id)
                    out.append(f"<li><code>{_e(ev_id)}</code>: {_e(ev.text if ev else 'NOT FOUND')}</li>")
                out.append("</ul></li>")
            out.append("</ul></details>")
        if item.follow_up:
            out.append("<p class='warn'>Questions for the client: " + _e(" ".join(item.follow_up)) + "</p>")
        out.append("</div>")

    out.append(f"<h2>Profit and loss ({_e(pack.currency)})</h2><div class='wrap'><table><tr><th>Line</th><th class='n'>Actual</th>"
               "<th class='n'>Budget</th><th class='n'>Variance</th><th class='n'>Var %</th><th class='n'>Prior month</th>"
               "<th class='n'>YTD actual</th><th class='n'>YTD budget</th></tr>")
    for line in pack.lines:
        if line.statement != "pl":
            continue
        v = line.values
        flag = " <span class='mat'>MATERIAL</span>" if line.material else ""
        pct = f"{v['month_var_pct']}%" if v.get("month_var_pct") is not None else ""
        out.append(f"<tr class='{'total' if line.type == 'total' else ''}'><td>{_e(line.label)}{flag}</td><td class='n'>{_n(v['month_actual'])}</td>"
                   f"<td class='n'>{_n(v['month_budget'])}</td><td class='n'>{_n(v['month_var'])}</td><td class='n'>{_e(pct)}</td>"
                   f"<td class='n'>{_n(v['prior_month'])}</td><td class='n'>{_n(v['ytd_actual'])}</td><td class='n'>{_n(v['ytd_budget'])}</td></tr>")
    out.append("</table></div>")
    out.append(f"<h2>Balance sheet ({_e(pack.currency)})</h2><div class='wrap'><table><tr><th>Line</th><th class='n'>This month</th>"
               "<th class='n'>Prior month</th><th class='n'>Movement</th></tr>")
    for line in pack.lines:
        if line.statement == "bs":
            v = line.values
            out.append(f"<tr class='{'total' if line.type == 'total' else ''}'><td>{_e(line.label)}</td><td class='n'>{_n(v['closing'])}</td>"
                       f"<td class='n'>{_n(v['prior_closing'])}</td><td class='n'>{_n(v['movement'])}</td></tr>")
    out.append("</table></div>")

    out.append("<h2>Workpapers</h2>")
    for paper in ctx.papers:
        out.append(f"<div class='panel'><b>{_e(paper.code)} {_e(paper.title)}</b><p class='muted'>{_e(paper.objective)}</p>"
                   "<div class='wrap'><table><tr><th>Ref</th><th>Description</th><th class='n'>Amount</th><th>Tick</th><th>Source</th></tr>")
        for row in paper.rows:
            refs = "<br>".join(f"<code>{_e(r.evidence_id)}</code> <span class='muted'>[{_e(r.source_hash)}] {_e(r.quote[:90])}</span>" for r in row.refs)
            note = f"<div class='muted'>{_e(row.note)}</div>" if row.note else ""
            out.append(f"<tr class='{'total' if row.kind in ('total', 'difference') else ''}'><td>{_e(row.ref_no)}</td><td>{_e(row.description)}{note}</td>"
                       f"<td class='n'>{_n(row.amount) if row.amount is not None else ''}</td><td>{_e(row.tick)}</td><td>{refs}</td></tr>")
        out.append(f"</table></div><p><b>Conclusion:</b> {_e(paper.conclusion)}</p>")
        for note in paper.preparer_notes:
            out.append(f"<p class='muted'>Preparer note (agent): {_e(note)}</p>")
        out.append("</div>")

    out.append("<h2>Audit trail</h2><div class='wrap'><table><tr><th>When (UTC)</th><th>Who</th><th>What</th></tr>")
    for event in store.events(run["run_id"], limit=40):
        out.append(f"<tr><td>{_e(event['ts'])}</td><td>{_e(event['actor'])}</td><td>{_e(event['kind'])}</td></tr>")
    out.append("</table></div></main></body></html>")
    (ctx.outputs / "review.html").write_text("".join(out))
