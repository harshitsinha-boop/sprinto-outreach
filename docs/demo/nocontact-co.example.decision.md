# Decision log: nocontact-co.example

Status: **stopped** (no_contact)
Started 2026-11-04T04:41:19+00:00; rubric icp.1; models {'fast': 'gemini-3.5-flash-lite', 'smart': 'gemini-3.8-flash'}.

## 1. Why this company
**Verdict: qualified** - score_min 80 >= qualify_min 60
Score 80 to 100 against threshold {'qualify_min': 60, 'reject_max': 45, 'reference_year': 2026}; rubric icp.1 (sha256 f4f5d4b507d8).

```
    qualified: score_min 80 >= qualify_min 60 | score_min 80, score_max 100 | rubric icp.1 sha256=f4f5d4b507d8
    gate G1_b2b pass: is_b2b=true
        "Acme Ledger is a B2B SaaS platform" (https://nocontact-co.example/)
    gate G3_size_ceiling pass: headcount=51-200
        "We are a team of about 80 people" (https://nocontact-co.example/)
    signal b2b_software (weight 10) +10 known - is_b2b=true
        "Acme Ledger is a B2B SaaS platform" (https://nocontact-co.example/)
    signal funding_stage (weight 10) +0..10 unknown - unknown: stage not stated
    signal headcount_band (weight 10) +10 known - headcount=51-200
        "We are a team of about 80 people" (https://nocontact-co.example/)
    signal compliance_pursuit (weight 25) +25 known - status=in_progress
        "working toward SOC 2 Type II certification" (https://nocontact-co.example/)
    signal enterprise_customers (weight 15) +15 known - 3 customers
        "Northwind Logistics, Contoso Freight and Globex Manufacturing" (https://nocontact-co.example/)
    signal security_hiring (weight 15) +15 known - 1 matching role
        "We are hiring a Security Engineer" (https://nocontact-co.example/)
    signal recent_funding (weight 10) +0..10 unknown - unknown: stage not stated
    signal regulated_vertical (weight 5) +5 known - matches accounts payable
        "automates accounts payable for finance teams" (https://nocontact-co.example/)
```

## 2. Why this person
No contact: Hunter returned no suitable named person for this company

## 3. Why this email
Not reached.
