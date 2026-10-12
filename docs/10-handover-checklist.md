# Handover checklist

*Use this when someone new takes over the system. When every box is ticked, the firm does not depend on the original builder.*

## Access

- [ ] Git repository: the new owner has admin rights, and CI is green on `main`.
- [ ] The machine or server that runs the overnight job: login, and where `var/` is backed up.
- [ ] Secret manager entries for Xero, Microsoft and Anthropic, with the date each secret expires.
- [ ] Xero developer portal: the app is owned by a firm account, not a personal one.
- [ ] Microsoft Entra: the app registration is owned by the firm's IT admin account.
- [ ] Anthropic Console: the organisation, the API key owner, and the spend limit.

## Knowledge

The new owner has, without help:

- [ ] Run `monthend demo` and opened the review page ([03](03-installation.md)).
- [ ] Run `/month-end-close` on the demo client in Claude Code.
- [ ] Approved and released a demo run in their own terminal ([02](02-reviewer-guide.md)).
- [ ] Fixed a blocked run, for example the `unmapped-account` case, by editing a mapping ([05](05-operating-runbook.md)).
- [ ] Run `monthend eval` and explained what each metric means ([08](08-evaluation.md)).
- [ ] Added an evaluation case for a made-up reviewer finding.
- [ ] Read the control matrix and limitations ([09](09-security-and-controls.md)).

## Ongoing ownership

| Task | Owner | How often |
|---|---|---|
| Read the morning status | Operator | Working days 1-10 |
| Review and approve packs | Reviewers named in client configs | Monthly |
| Mapping and template changes | Pack owner, with a reviewer | As needed |
| Secret rotation, backup restore test | IT | Quarterly |
| Evaluation after any change | Developer (CI enforces it) | Every change |
| Dependency updates (`requirements-lock.txt`) | Developer | Quarterly: update, run the tests and eval, commit |
