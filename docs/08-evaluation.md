# Evaluation: how we know when the output is wrong

*For anyone who needs to trust the output, or change the system.*

"It ran" is not evidence of anything. This system measures **correctness** at three levels, and the same checks run in production on every pack.

## 1. Production checks on every run

Before a pack can reach a reviewer:

| Check | Catches |
|---|---|
| Trial balance balances; pack profit = Xero profit (recomputed from Xero's own account classes, not our mapping); balance sheet balances | Arithmetic and mapping errors |
| Every account mapped, and to the right statement | Silent omissions |
| Workpaper tie-outs to the ledger; unexplained bank difference within tolerance | Reconciliation errors |
| Commentary validator | Missing material lines, figures not in the pack or evidence, wrong direction words, invented or wrong citations, unsupported driver amounts |
| Input hashes unchanged | Anything altered after the snapshot |

The commentary validator (`monthend/variance.py`) is deliberately narrow. It checks only what is either true or false, so a "pass" means something. It does **not** judge whether the stated cause is the *real* cause. That is measured below, and judged by the reviewer.

## 2. Golden cases (`evals/cases/`)

Each case runs the **whole pipeline** on the synthetic client, with controlled defects planted in the source data, and grades the **files produced**:

| Case | Planted problem | Must end |
|---|---|---|
| base-clean | none (four reviewer warnings) | ready for review, every cell correct |
| unmapped-account | suspense account no mapping covers | blocked |
| tb-out-of-balance | one-sided journal | blocked |
| bank-rec-difference | 500 unexplained in cash | blocked, reconciliation shows 500 |
| missing-statement | bank statement not saved | blocked |
| missing-support | invoice behind an accrual missing | ready, with warning |
| receivables-mismatch | journal to debtors with no invoice | blocked |
| evidence-removed | the email explaining a revenue timing is gone | ready; commentary must not claim the client asked |

Expected pack values were derived by hand from the fixture inputs, not copied from the program's output. The grader reads the Excel file back, re-resolves every workpaper reference against the snapshot, and checks that each referenced document line really contains the figure.

### Commentary quality against reviewer labels

For each material line, a reviewer recorded which evidence explains it, as **driver groups**. Bayside revenue, for example, needs both the invoice *and* the email saying why it was billed early. Metrics:

- **driver recall**: share of labelled causes the draft cited. The rule-based baseline scores about 0.38. It picks the largest transaction, which is often not the cause. The threshold for model drafts is 0.8.
- **forbidden claims**: phrases a draft must not use because the evidence does not support them. This is a hallucination probe.
- **direction agreement** with the label.

An optional **LLM judge** (`--judge`) scores plain English, causal explanation, proportion and actionability from 1 to 5. It is advisory. Calibrate it against reviewer opinions before relying on it, and never use it as a gate.

## 3. Testing the tester: validator mutation tests

A validator that passes everything is worthless, and so is one that fails everything. So each evaluation run:

1. Checks a **reviewer-approved commentary** passes with no blocking issue (no false positives).
2. Plants 12 known defects in it (changed figure, flipped direction, dropped line, invented evidence, wrong driver amount, unknown line, wrong summary figure, wrong summary direction, hedging, inflated rounding, missing summary, driver without evidence) and checks **each one is caught**.

Both must be perfect for the evaluation to pass.

### A real example

The first run of the mutation tests found two faults in the system itself:

- The reviewer-approved draft was **rejected**. It said "October revenue will be correspondingly lower than budget", and the validator read that as a claim about September. The validator now checks direction only in sentences about the reporting month. A regression test pins this down.
- A planted defect ("AUD 62k" for AUD 61,850) was **not caught**, and that was correct: it is legitimate rounding. The test was wrong, not the validator, so the mutation was replaced with a genuinely wrong figure.

Without the mutation tests, the first fault would have shown up as "the agent can't pass validation" and pushed agents towards worse writing to satisfy a broken checker.

## Running it

```bash
.venv/bin/python -m monthend eval
```

That runs offline with the rule-based baseline, which is what CI runs on every commit.

```bash
.venv/bin/python -m monthend eval --engine claude --trials 3
```

That uses Claude drafts and repeats each case to measure variability. It calls the API and costs money. With `--judge` it also adds rubric scores. To score a draft saved from a Claude Code session, pass the file:

```bash
.venv/bin/python -m monthend eval --engine path/to/commentary.json --case base-clean
```

Reports are written to `evals/reports/latest-<engine>.md` and `.json`. Thresholds are in `evals/thresholds.json`. The command exits non-zero below threshold, so CI fails the build.

## When a reviewer finds an error

Every error a reviewer finds is a missing test. The routine:

1. Reproduce it: add a case to `evals/cases/` (an overlay that recreates the data situation) with the correct expected result and labels.
2. Confirm the evaluation **fails** on it.
3. Fix the code, the skill text or the mapping.
4. Confirm the evaluation passes, and that no other case got worse.
5. Commit the case and the fix together. The commit message says what the reviewer found.

Never weaken a check or a threshold to make an evaluation pass without a case that shows the check was wrong.
