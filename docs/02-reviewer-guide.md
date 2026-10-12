# Reviewer guide

*For the accountant who approves a pack before it goes to the client.*

## 1. Open the review page

When a pack is ready, you get its review page: a single file called `review.html`. The morning summary or the person who ran the close gives you the path. Open it in any browser. Everything you need is on that page:

1. **Status and what you are approving.** The recipients, subject and attachment that will be sent, plus an 8-character **confirmation code**.
2. **Checks.** Blocking issues (there will be none if the status is *Ready for review*) and warnings you should consider.
3. **Independent agent review.** Findings from a second, read-only agent. Treat them as a colleague's review notes.
4. **Commentary.** The summary and each variance explanation. Click *Evidence* to see the exact invoice, email or document line behind each statement.
5. **Profit and loss and balance sheet**, with material lines marked.
6. **Workpapers**, with every reference, tickmark and conclusion.
7. **Audit trail.** Who and what touched this run, and when.

The Excel files are in the same folder: `pack.xlsx` is what the client receives, and `workpapers.xlsx` stays with the firm.

## 2. What to check

The software has already proved the arithmetic, the tie-outs and that every cited figure exists. Spend your time on judgement:

- **Is the explanation the real reason?** The agent finds evidence, but it can pick a true fact that is not the main cause. Compare it with your knowledge of the client.
- **Timing versus permanent.** Does the commentary make clear when something will reverse next month?
- **Warnings.** For each one, is it explained, or does the client need to be asked? Typical warnings:
  - *Account placed in a pack line by its code range*: is that the right line?
  - *Bank items not in Xero*: the proposed adjustment is for the client to post.
  - *Aged receivable*: is a provision needed?
  - *Accrual differs from invoice* or *no supporting document*.
- **Tone.** Would the business owner understand it and not be alarmed or misled?
- **Questions for the client** listed under commentary items. Keep, edit or remove them.

## 3. Decide

Run these in **your own terminal**, not inside Claude. The system refuses decisions made from an agent session.

**Approve:**

```bash
monthend review approve --run <run id>
```

You will be asked for your name (it must be on the client's reviewer list), the confirmation code from the page, and a review note. Then type `approve` to confirm.

**Send back for changes:**

```bash
monthend review request-changes --run <run id>
```

Your note should say what to change, for example "Materials: say how much of the increase is the Bayside job versus the price rise". The preparer or agent revises the draft, and you get a new review page with a **new confirmation code**. The old code no longer works, and resubmitting the unchanged version is refused.

## 4. What approval locks

Your approval is tied to the exact version you saw: every file, the Xero snapshot, the configuration and the delivery details. If anything changes afterwards, even one character, the approval no longer applies and the system will not release the pack. If Xero data changes after you approve (a late journal, say), the overnight run prepares a new version, and you review that one.

## 5. Release

After approval, the operator, or you, releases the pack:

```bash
monthend release --run <run id>
```

By default this creates an **Outlook draft** in the firm's mailbox with the approved attachment and recipients. Someone opens Drafts and presses Send. Clients can be configured to send directly, but draft mode is recommended until the firm is comfortable with the system.

## If something looks wrong

- A figure in the pack is wrong: do not edit the Excel file. Request changes and say what is wrong. If the cause is the Xero data or the account mapping, it is fixed at source and the pack is regenerated.
- A reference does not show what the workpaper claims: request changes and quote the reference. Then tell the system owner, because it should never happen. It means a check needs strengthening (see [08-evaluation.md](08-evaluation.md), "When a reviewer finds an error").
