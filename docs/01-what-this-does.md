# What this system does

*For partners, managers and anyone deciding whether to rely on it. No technical knowledge needed.*

## In one paragraph

Each month the system takes a client's figures from Xero and their documents from SharePoint and Outlook. It produces three things a junior accountant would normally prepare: the **management pack** in the firm's Excel template, **workpapers** where every figure points to the exact line of the document it came from, and a **draft commentary** explaining the significant differences from budget. A qualified person reviews all three on one page. Nothing goes to the client until that person approves it, and once they have approved it, nothing can be changed without the approval lapsing.

## Who does what

| Step | Done by | Can it go wrong silently? |
|---|---|---|
| Copy the month's Xero data and client documents into a frozen snapshot | Software | No. Every file is fingerprinted (SHA-256). Any later change is detected. |
| Calculate the pack: actuals, budget, variances, balance sheet | Software, using exact decimal arithmetic | No. The pack is re-checked against the trial balance; the balance sheet must balance. |
| Build workpapers (bank reconciliation, accruals, receivables) | Software | No. Each figure is linked to a document line; the link is re-checked. |
| Explain judgement items in the workpapers (why, what to do) | Claude agent ("workpaper preparer") | Possibly. Notes are clearly labelled as agent notes and never change a figure. |
| Draft variance commentary | Claude agent ("variance analyst") | Partly. Every number and every cited document is checked automatically. Whether the stated *cause* is right is judged by the reviewer. |
| Second review before a person sees it | Claude agent ("independent reviewer"), read-only | It can miss things. It is an extra check, not a replacement for the reviewer. |
| **Approve** | **A named reviewer** | The reviewer types a code that matches the exact version they read. |
| Send to the client | Person-triggered, after approval | Only the approved files, to the approved recipients. By default it creates an Outlook *draft* that a person sends. |

## What the automatic checks guarantee

A pack cannot reach a reviewer if any of these fail:

- The Xero trial balance does not balance.
- An account is not mapped to a line in the pack.
- The pack's profit does not agree to Xero's profit, or the balance sheet does not balance.
- The bank reconciliation has an unexplained difference.
- Accruals or receivables do not agree to the ledger.
- A required source document, such as the bank statement, is missing.
- The commentary misses a significant variance, uses a figure that is not in the pack or the evidence, says "favourable" when it is unfavourable, or cites a document that does not exist.

Things a reviewer is shown but that do not stop the pack include a new account placed in a pack line by its account-code range, an aged debt, a bank fee not yet recorded in Xero, a missing supporting invoice, or commentary that hedges ("probably").

## What it does not do

- It never posts anything to Xero. It only reads.
- It never sends anything a person has not approved.
- It does not make tax or accounting-policy judgements. It flags them, for example "consider coding equipment hire to cost of sales".
- It does not replace the reviewer's professional judgement about *why* a number moved. It makes that judgement faster by putting the evidence next to the claim.

## How we know it works

There is a test set of client months with known answers and planted problems: a missing bank statement, an unexplained bank difference, an unmapped account, and so on. Every change to the system is run against it. The test set also checks the checker: we deliberately plant mistakes in a correct commentary (a wrong figure, a flipped direction, an invented document) and confirm every one is caught. See [08-evaluation.md](08-evaluation.md).

## Where to go next

- Reviewing a pack: [02-reviewer-guide.md](02-reviewer-guide.md)
- Running it day to day: [05-operating-runbook.md](05-operating-runbook.md)
- Controls and risks: [09-security-and-controls.md](09-security-and-controls.md)
