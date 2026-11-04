# Decision log: pocket-pals.example

Status: **stopped** (disqualified)
Started 2026-11-04T04:41:19+00:00; rubric icp.1; models {'fast': 'gemini-3.5-flash-lite', 'smart': 'gemini-3.8-flash'}.

## 1. Why this company
**Verdict: disqualified** - gate G1_b2b failed: is_b2b=false
Score 0 to 85 against threshold {'qualify_min': 60, 'reject_max': 45, 'reference_year': 2026}; rubric icp.1 (sha256 f4f5d4b507d8).
Decided with unknown signals: compliance_pursuit, enterprise_customers, security_hiring, funding_stage, headcount_band, recent_funding.

```
    disqualified: gate G1_b2b failed: is_b2b=false | score_min 0, score_max 85 | rubric icp.1 sha256=f4f5d4b507d8
    gate G1_b2b fail: is_b2b=false
        "Pocket Pals is a mobile game for kids and families" (https://pocket-pals.example/)
    gate G3_size_ceiling unknown: headcount not stated
    signal b2b_software (weight 10) +0 known - is_b2b=false
        "Pocket Pals is a mobile game for kids and families" (https://pocket-pals.example/)
    signal funding_stage (weight 10) +0..10 unknown - unknown: stage not stated
    signal headcount_band (weight 10) +0..10 unknown - unknown: headcount not stated
    signal compliance_pursuit (weight 25) +0..25 unknown - unknown: no security page read
    signal enterprise_customers (weight 15) +0..15 unknown - unknown: no customers page read
    signal security_hiring (weight 15) +0..15 unknown - unknown: no careers page read
    signal recent_funding (weight 10) +0..10 unknown - unknown: stage not stated
    signal regulated_vertical (weight 5) +0 known - no vertical keyword
        "Pocket Pals is a mobile game for kids and families" (https://pocket-pals.example/)
```

## 2. Why this person
Not reached (the company did not qualify, so Hunter was never called).

## 3. Why this email
Not reached.
