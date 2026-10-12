---
name: workpaper-standards
description: The firm's workpaper standard - referencing, tickmarks, preparer notes and what makes a workpaper complete. Use when preparing or reviewing month-end workpapers.
---

# Workpaper standard

A workpaper must let a reviewer re-perform the work without asking the preparer anything.

## Every workpaper has

- **Objective.** What the workpaper proves, in one sentence.
- **Rows.** Each figure has a reference, a tickmark and, where needed, a note.
- **Tie-out.** The workpaper balance agrees to the ledger (Xero trial balance), and the difference is shown even when it is nil.
- **Conclusion.** One sentence that follows from the rows. "Reconciled" is only acceptable when the unexplained difference is within tolerance.
- **Preparer notes.** Judgement and follow-ups. Notes never change a figure.

## References

A reference is an evidence id plus the SHA-256 prefix of the source file, for example `doc:bank-statement-090-2026-09#p1:L11 [3147b7d8abc3]`. The text at that location must contain the figure. If you open a reference and it does not say what the row claims, that is a `REFERENCE PROBLEM` note. It goes to the reviewer and blocks nothing on its own.

## Tickmarks

| Mark | Meaning |
|---|---|
| X | Agreed to Xero ledger / trial balance |
| S | Agreed to source document |
| E | Agreed to subsequent evidence dated after period end |
| C | Cast / recalculated |
| ! | Exception: a note is required |

## Writing preparer notes

Write each note as: **what** it is, **why** it matters (amount, recurrence, risk), and the **proposed action**, with who does it.

- Proposed adjustments are proposals for the client to post. This system never posts journals.
- Missing support: name the document and who should provide it.
- Aged receivables: give the age, the amount, any correspondence found (cited), and whether a provision should be discussed.
