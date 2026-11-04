# ICP rubric calibration

## icp.1 -> icp.2 (recalibrated after seeing real scores)

icp.2 is a **post-hoc recalibration**. It was made after the deployed app ran six real
domains under icp.1, so it is not an untouched out-of-sample result and must not be presented as one.

### The six live results under icp.1

| Domain | icp.1 score (min..max) | Outcome | Note |
|---|---|---|---|
| clerk.com | 25..45 | insufficient_data | min could not reach 60 |
| stytch.com | 10..50 | insufficient_data | min could not reach 60 |
| airbyte.com | 1..46 | insufficient_data | min could not reach 60 |
| posthog.com | max 30 | disqualified | max below 45; already SOC 2 certified (penalty) |
| supabase.com | max 20 | disqualified | max below 45; already SOC 2 certified (penalty) |
| hightouch.com | max 28 | disqualified | max below 45; already SOC 2 certified (penalty) |

Only the maximum is recorded for the three disqualified companies. The icp.2 outcomes for these
six domains were **not** re-run when icp.2 was written (no live calls were made); the weights were
not tuned against them beyond the one change below.

### Root cause

30 of the 100 points (funding_stage 10, headcount_band 10, recent_funding 10) depended on facts that
company websites rarely state. The minimum therefore could not reach 60, and signals still unknown
after the research loop were counted as 0 in the minimum.

### What changed and why

| Item | icp.1 | icp.2 | Why |
|---|---|---|---|
| b2b_software | 10 | 10 | unchanged |
| funding_stage | 10 | 5 | rarely stated |
| headcount_band | 10 | 5 | rarely stated |
| recent_funding | 10 | removed | rarely stated, and dependent on a date |
| compliance_pursuit | 25 | 30 | observable on trust/security pages |
| enterprise_customers | 15 | 20 | observable on customers pages |
| security_hiring | 15 | 20 | observable on careers pages |
| regulated_vertical | 5 | 10 | observable from the offering |
| **Weights total** | 100 | 100 | |
| qualify_min / reject_max | 60 / 45 | 60 / 45 | unchanged |
| unknown_credit | n/a | 0.5 | an unresolved unknown counts for half its weight in score_expected |
| qualify_expected | n/a | 55 | new threshold, used only after research |
| Gates (consumer product, >1000 employees), penalties P1/P2 | | unchanged | already-certified companies should score lower |

`score_expected = score_min + unknown_credit x (score_max - score_min)`.

Decision rules in icp.2:

- **disqualified** if a hard gate fails or `score_max < reject_max` (45);
- **qualified** if `score_min >= qualify_min` (60), **or** if the research loop has run (and did not end
  on tool errors), at least 2 signals are known from validated evidence, something is still unknown, and
  `score_expected >= qualify_expected` (55). The reason then reads "qualified on expected score X (min..max)"
  and lists the unresolved signals, because it is an estimate and not a certainty;
- otherwise **insufficient_data**.

Known weakness to watch: a company with only cheap facts known (B2B, headcount, vertical) and nothing
learned about compliance, customers or hiring can still reach an expected score near the threshold,
because unknowns are credited at half weight. Check the holdout for this.

### Status of the thresholds

The icp.2 weights and thresholds above are now **fixed**. They must not be changed in response to the six
domains in this file. A **separate holdout set, not used for tuning, will be run afterwards** and reported as
is, whatever it shows. Any later change means a new rubric version (icp.3) and a new entry here.

## Offline calibration fixtures

`tests/fixtures/icp_calibration.json` (rubric_version `icp.2`), asserted by `tests/test_qualify.py`.
Each expected score was re-derived with the icp.2 scorer; these are synthetic profiles, not real companies.

| Case | min..max (expected) | Verdict |
|---|---|---|
| fit_series_b_full_signals | 100..100 (100.0) | qualified |
| fit_series_a_planned | 92..92 (92.0) | qualified |
| fit_unknown_stage | 83..88 (85.5) | qualified |
| reject_consumer_app | 4..9 (6.5) | disqualified (gate G1_b2b) |
| reject_over_1000 | 63..63 (63.0) | disqualified (gate G3_size_ceiling) |
| reject_mature_certified | 10..10 (10.0) | disqualified (penalty P1) |
| gray_thin_seed | 18..88 (53.0) | insufficient_data (thin company stays undecided) |
| gray_fully_known | 52..52 (52.0) | disqualified (fully known, below 60) |
| fit_expected_after_research | 47..77 (62.0) | qualified on expected score, only when research has run; insufficient_data without it |

The version, weights, thresholds and penalties are pinned in `test_repo_rubric_thresholds_are_pinned`.

## Headcount band consistency check (extraction fix, not a rubric change)

Live, attio.com was disqualified by hard gate G3_size_ceiling (headcount 1001+) although the careers
page says "190+ team members": the model mapped the quote to the wrong band, and the quote-substring
check only proved the quote was on the page, not that it supported the band. `validate_profile` now
checks the band against the numbers in the quote (`1,200`, `10k`, `2.5k`, `190+` read as 190, ranges by
overlap, "thousands of employees" and "1000+ employees" for 1001+). A band the quote does not support is
dropped to null with reason `headcount_band_mismatch` (or `headcount_no_number` when the quote has no
number), so the rubric treats it as unknown. `qualify.score_profile` repeats the check, so G3 can only fire
from a band that passed it. The `Series X` letter of a funding stage is checked the same way
(`stage_mismatch`). Rubric weights and thresholds are unchanged, so icp.2 stays fixed; no calibration
fixture needed updating.
