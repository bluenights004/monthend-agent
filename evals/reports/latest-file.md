# Evaluation report - engine `evals/cases/base-clean.gold-commentary.json`

**PASSED** on 1 cases, 2026-10-11 14:52 UTC.

| Metric | Value |
|---|---:|
| cases | 1 |
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
| driver_recall | 1.0 |
| forbidden_claims | 0 |
| validator_mutation_detection | 1.0 |
| validator_gold_false_positives | 0 |

## Cases

- **base-clean** [ok] ended READY_FOR_REVIEW; blocking raised none

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
