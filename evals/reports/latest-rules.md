# Evaluation report - engine `rules`

**PASSED** on 8 cases, 2026-10-11 15:03 UTC.

| Metric | Value |
|---|---:|
| cases | 8 |
| state_accuracy | 1.0 |
| blocking_recall | 1.0 |
| false_blocks | 0 |
| warning_recall | 1.0 |
| pack_cell_accuracy | 1.0 |
| tie_accuracy | 1.0 |
| reference_integrity | 1.0 |
| commentary_coverage | 1.0 |
| numeric_faithfulness | 1.0 |
| direction_accuracy | 1.0 |
| evidence_validity | 1.0 |
| driver_recall | 0.375 |
| forbidden_claims | 0 |
| validator_mutation_detection | 1.0 |
| validator_gold_false_positives | 0 |

## Cases

- **bank-rec-difference** [ok] ended BLOCKED; blocking raised ['BANKREC_UNEXPLAINED']
- **base-clean** [ok] ended READY_FOR_REVIEW; blocking raised none
  - pl.rev.contract: missed driver xero:invoice:INV-1042
  - pl.rev.contract: missed driver email:msg-bayside-0922
  - pl.cos.materials: missed driver xero:invoice:TC-88801
  - pl.cos.subcontractors: missed driver email:msg-sparky-0917
- **evidence-removed** [ok] ended READY_FOR_REVIEW; blocking raised none
  - pl.rev.contract: missed driver xero:invoice:INV-1042
- **missing-statement** [ok] ended BLOCKED; blocking raised ['WP_SOURCE_MISSING']
- **missing-support** [ok] ended READY_FOR_REVIEW; blocking raised none
- **receivables-mismatch** [ok] ended BLOCKED; blocking raised ['RECEIVABLES_DO_NOT_TIE']
- **tb-out-of-balance** [ok] ended BLOCKED; blocking raised ['BS_DOES_NOT_BALANCE', 'TB_OUT_OF_BALANCE']
- **unmapped-account** [ok] ended BLOCKED; blocking raised ['BS_DOES_NOT_BALANCE', 'MAP_MISSING', 'PACK_MONTH_PROFIT_MISMATCH', 'PACK_YTD_PROFIT_MISMATCH']

## Validator mutation tests

| Planted defect | Must raise | Caught |
|---|---|---|
| changed figure in text | NUMBER_UNTRACEABLE | yes |
| flipped direction | DIRECTION_WRONG | yes |
| dropped a material line | MISSING_MATERIAL_LINE | yes |
| invented evidence id | EVIDENCE_UNKNOWN | yes |
| driver amount not in evidence | DRIVER_AMOUNT_UNSUPPORTED | yes |
| driver without evidence | DRIVER_NO_EVIDENCE | yes |
| unknown pack line | UNKNOWN_LINE | yes |
| wrong summary figure | NUMBER_UNTRACEABLE | yes |
| hedged speculation | SPECULATIVE_LANGUAGE | yes |
| inflated rounded figure | NUMBER_UNTRACEABLE | yes |
| wrong direction in summary | DIRECTION_WRONG | yes |
| missing summary | NO_SUMMARY | yes |
