# Customising the template, mapping and materiality

*For the person who looks after the firm's pack format.*

## Using the firm's own Excel template

The system fills the template by **keys**, not by cell addresses, so you can restyle it freely.

1. Open your template. On each data sheet (profit and loss, balance sheet):
   - In cell **A3**, type `#keys`. In the rest of **row 3**, type a column key above each figure column (keys below). Hide row 3 if you like.
   - In **column A** of each figure row, type the row key from the mapping file, such as `pl.rev.contract`. Hide column A if you like.
2. Anywhere in the workbook, these tokens are replaced: `{{client_name}}`, `{{period_label}}`, `{{currency}}`, `{{run_id}}`, `{{prepared_at}}`.
3. Optional sheets: if a sheet is named `Commentary`, the summary goes in B4 and items from row 6. If a sheet is named `Exceptions`, checks are listed from row 5.
4. Save it in `templates/` and point the client config's `template` at it.

Column keys:

| Profit and loss | Balance sheet |
|---|---|
| `month_actual`, `month_budget`, `month_var`, `month_var_pct`, `prior_month`, `ytd_actual`, `ytd_budget`, `ytd_var` | `closing`, `prior_closing`, `movement` |

If the template has no row for a pack line, the run stops with a message naming the missing key. That is deliberate: nothing is silently left out.

`scripts/build_template.py` generates a clean template from a mapping file. It also adds a *Checks* sheet with live Excel formulas that recompute every subtotal, so a reviewer can see the arithmetic hold inside Excel.

## Mapping Xero accounts to pack lines

`config/mappings/standard-au.json` lists the pack's rows in order. Each row is one of:

- `"type": "line"`: lists Xero account codes in `accounts`. Optional `ranges` (e.g. `[["400", "499"]]`) catch new accounts in that range. Those are placed but flagged for confirmation.
- `"type": "total"`: `sum` of other keys. Prefix a key with `-` to subtract.
- `"type": "earnings"`: current-year earnings, computed from the profit and loss.

`nature` (`income`, `expense`, `asset`, `liability`, `equity`) controls the presentation sign and what counts as favourable.

An account that matches nothing blocks the run. An account mapped to the wrong statement (for example a revenue account in a balance sheet line) also blocks it.

**Treat mapping changes like changes to the books.** Have them reviewed, commit them with a message saying why, and re-run any affected open month.

## Materiality

In each client config, `materiality`:

| Setting | Meaning |
|---|---|
| `abs_threshold` | A variance at least this size is material |
| `abs_floor` + `pct_threshold` | Smaller variances are material if they are at least `abs_floor` **and** at least `pct_threshold`% of budget, or the budget is nil |
| `bank_rec_tolerance` | Largest unexplained bank difference treated as reconciled |
| `accrual_support_tolerance` | Accrual-to-invoice difference that needs a note rather than a warning |
| `receivables_overdue_days` | Age at which an invoice is flagged |

Material lines must have commentary. The validator enforces this.
