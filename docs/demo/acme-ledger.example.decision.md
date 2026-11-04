# Decision log: acme-ledger.example

Status: **dry_run**
Started 2026-11-04T04:41:19+00:00; rubric icp.1; models {'fast': 'gemini-3.5-flash-lite', 'smart': 'gemini-3.8-flash'}.

## 1. Why this company
**Verdict: qualified** - score_min 80 >= qualify_min 60
Score 80 to 100 against threshold {'qualify_min': 60, 'reject_max': 45, 'reference_year': 2026}; rubric icp.1 (sha256 f4f5d4b507d8).

```
    qualified: score_min 80 >= qualify_min 60 | score_min 80, score_max 100 | rubric icp.1 sha256=f4f5d4b507d8
    gate G1_b2b pass: is_b2b=true
        "Acme Ledger is a B2B SaaS platform" (https://acme-ledger.example/)
    gate G3_size_ceiling pass: headcount=51-200
        "We are a team of about 80 people" (https://acme-ledger.example/)
    signal b2b_software (weight 10) +10 known - is_b2b=true
        "Acme Ledger is a B2B SaaS platform" (https://acme-ledger.example/)
    signal funding_stage (weight 10) +0..10 unknown - unknown: stage not stated
    signal headcount_band (weight 10) +10 known - headcount=51-200
        "We are a team of about 80 people" (https://acme-ledger.example/)
    signal compliance_pursuit (weight 25) +25 known - status=in_progress
        "working toward SOC 2 Type II certification" (https://acme-ledger.example/)
    signal enterprise_customers (weight 15) +15 known - 3 customers
        "Northwind Logistics, Contoso Freight and Globex Manufacturing" (https://acme-ledger.example/)
    signal security_hiring (weight 15) +15 known - 1 matching role
        "We are hiring a Security Engineer" (https://acme-ledger.example/)
    signal recent_funding (weight 10) +0..10 unknown - unknown: stage not stated
    signal regulated_vertical (weight 5) +5 known - matches accounts payable
        "automates accounts payable for finance teams" (https://acme-ledger.example/)
```

## 2. Why this person
**Richard Hendricks, CEO** <richard@piedpiper.com> (Hunter confidence 99, source fixture).
Size band: mid (headcount 51-200). Richard Hendricks, CEO: top title match for the mid band (headcount 51-200), score 11.0.

Top candidates (1 seen):

| # | Name | Title | Category | Score | Notes |
|---|---|---|---|---|---|
| 1 | Richard Hendricks | CEO | ceo_founder | 11.0 | ceo_founder rank 8 of 8 for the mid band; verified valid |

## 3. Why this email
Pain points (llm):
- Enterprise security reviews can slow deals while SOC 2 is in progress. (role: a CEO owns deal speed; evidence E1)
- A new security hire inherits evidence collection for the whole program. (role: a CEO owns hiring and focus; evidence E2)

Subject: `your soc 2 timeline`

```
Hi Richard, I saw you are working toward SOC 2 Type II and are hiring a Security Engineer to own the program. Teams in that spot often lose weeks of focus to evidence collection and security reviews while enterprise deals wait. Sprinto automates compliance for SOC 2, ISO 27001 and GDPR, with continuous monitoring and audit-ready evidence collection. Would a short walkthrough be useful?

--
[Sender name], [Title], Sprinto
[Sender postal address]
You are receiving this one-time note because of your role at Acme Ledger. If you would rather not hear from us, reply "no" and I will not email again.
```

Hook-to-evidence map:

| Claim in the email | Evidence | Quote | Source |
|---|---|---|---|
| working toward SOC 2 Type II | E1 | "working toward SOC 2 Type II certification" | https://acme-ledger.example/ |
| hiring a Security Engineer | E2 | "We are hiring a Security Engineer" | https://acme-ledger.example/ |
| Sprinto automates compliance for SOC 2, ISO 27001 and GDPR | S1 (Sprinto whitelist) | - | - |
| continuous monitoring and audit-ready evidence collection | S2 (Sprinto whitelist) | - | - |

Validator: passed after 1 attempt(s).

## 4. Send
dry-run, Resend not called. From onboarding@resend.dev to owner@example.com (forced to the owner address).
Subject: `[TEST -> Richard Hendricks <richard@piedpiper.com>] your soc 2 timeline`
