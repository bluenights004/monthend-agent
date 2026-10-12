---
name: variance-commentary
description: The firm's written standard for management-pack variance commentary. Use when drafting, editing or reviewing commentary on budget variances.
---

# Variance commentary standard

The reader is a business owner, not an accountant. They want to know what happened, why, and whether it will happen again.

## What to write

For **each material line**, 2-4 sentences:

1. **The numbers.** "<Line> was <CUR> <actual> against a budget of <CUR> <budget>, a favourable/unfavourable variance of <CUR> <variance> (<pct>%)." Use the pack's figures to the dollar, with no decimals. Use the currency code. Write percentages to one decimal place, exactly as in the pack.
2. **The cause, with evidence.** Name the business event: the customer, supplier, job or decision. Do not name the account. Write "Bayside Medical's stage 2 claim was invoiced in September", not "Account 200 increased". Every cause is a driver that cites evidence ids.
3. **What it means next.** Say whether it is timing (it reverses next month), one-off, or ongoing. Say this only if the evidence supports it.

Then a **summary** of 2-3 sentences. The first sentence states net profit before tax against budget and says "ahead of" or "behind" budget, with the variance. The rest names the two or three biggest reasons.

## Direction words

- Income above budget is **favourable**. Costs above budget are **unfavourable**.
- "Above budget" and "below budget" describe the number. "Favourable" and "unfavourable" describe the effect on profit. Do not mix them up for cost lines: costs above budget are above budget *and* unfavourable.
- Only use direction words about the reporting month in the same sentence as that month's figures. Put statements about other months in separate sentences that name the month.

## Evidence

- Cite evidence ids exactly as the tools return them: `xero:invoice:INV-1042`, `email:msg-...`, `doc:<file>#p1:L6`, `wp:B1:B1.3`.
- A driver's `amount` is the amount shown in its evidence: an invoice line, a subtotal, an accrual. Never use a difference you calculated yourself. Use `null` if the cause is real but cannot be quantified from evidence.
- Only say "the client asked", "was approved" or "was agreed" if an email or document says so.
- If you cannot evidence a cause, do not guess. Add a question to `follow_up`, for example: "What caused the increase in motor vehicle costs?"

## Style

- Plain English. Short sentences. No jargon: write "billed", not "recognised", and "costs", not "opex".
- No hedging ("likely", "probably", "appears to", "may have been"). State what the evidence shows, or ask.
- Do not explain immaterial lines unless they help explain a material one.
- Each item stays under 900 characters.

## Example

> Materials were AUD 61,850 against a budget of AUD 52,000, an unfavourable variance of AUD 9,850 (18.9%). Two things drove this: AUD 19,850 of laminate and hardware for the Bayside Medical stage 2 job, which moved into September with the revenue (TC-88801), and Timberco's 8% price increase on hardwood from 1 September, reflected in the AUD 28,400 general stock invoice (TC-88790).
