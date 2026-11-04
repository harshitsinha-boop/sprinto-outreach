# Decision log: northwind-pay.example

Status: **dry_run**
Started 2026-11-04T04:41:19+00:00; rubric icp.1; models {'fast': 'gemini-3.5-flash-lite', 'smart': 'gemini-3.8-flash'}.

## 1. Why this company
**Verdict: qualified** - score_min 70 >= qualify_min 60
Score 70 to 90 against threshold {'qualify_min': 60, 'reject_max': 45, 'reference_year': 2026}; rubric icp.1 (sha256 f4f5d4b507d8).

```
    qualified: score_min 70 >= qualify_min 60 | score_min 70, score_max 90 | rubric icp.1 sha256=f4f5d4b507d8
    gate G1_b2b pass: is_b2b=true
        "Northwind Pay is a B2B payments platform" (https://northwind-pay.example/)
    gate G3_size_ceiling pass: headcount=201-500
        "a team of about 300 people" (https://northwind-pay.example/)
    signal b2b_software (weight 10) +10 known - is_b2b=true
        "Northwind Pay is a B2B payments platform" (https://northwind-pay.example/)
    signal funding_stage (weight 10) +0..10 unknown - unknown: stage not stated
    signal headcount_band (weight 10) +5 known - headcount=201-500
        "a team of about 300 people" (https://northwind-pay.example/)
    signal compliance_pursuit (weight 25) +25 known - status=planned
        "plan to certify against ISO 27001 this year" (https://northwind-pay.example/)
    signal enterprise_customers (weight 15) +10 known - 2 customers
        "Fabrikam Bank and Tailspin Credit Union" (https://northwind-pay.example/)
        "Our customers include Fabrikam Bank and Tailspin Credit Union" (https://northwind-pay.example/)
    signal security_hiring (weight 15) +15 known - 1 matching role
        "We are hiring a Head of Security" (https://northwind-pay.example/)
    signal recent_funding (weight 10) +0..10 unknown - unknown: stage not stated
    signal regulated_vertical (weight 5) +5 known - matches payment
        "helps banks reconcile transfers" (https://northwind-pay.example/)
```

## 2. Why this person
**Maria Lopez, CISO** <maria@northwind-pay.example> (Hunter confidence 96, source fixture).
Size band: large (headcount 201-500). Maria Lopez, CISO: top title match for the large band (headcount 201-500), score 77.0; ahead of Ana (Director of Engineering, 40.0) on higher title rank.

Top candidates (3 seen):

| # | Name | Title | Category | Score | Notes |
|---|---|---|---|---|---|
| 1 | Maria Lopez | CISO | security_lead | 77.0 | security_lead rank 1 of 7 for the large band; verified valid |
| 2 | Ana Kim | Director of Engineering | eng_lead | 40.0 | eng_lead rank 4 of 7 for the large band; verified valid |

## 3. Why this email
Pain points (llm):
- Bank customers will ask for proof of ISO 27001 progress during security reviews. (role: a CISO owns security posture and proof to customers; evidence E1)
- A new Head of Security inherits evidence collection across teams. (role: a CISO owns the compliance program; evidence E2)

Subject: `iso 27001 timeline`

```
Hi Maria, saw Northwind Pay plans to certify against ISO 27001 and is hiring a Head of Security. For a security lead, that usually means chasing evidence across teams ahead of customer reviews from banks. Sprinto automates compliance for SOC 2, ISO 27001 and GDPR, with continuous monitoring and audit-ready evidence collection. Is that worth a look?

--
[Sender name], [Title], Sprinto
[Sender postal address]
You are receiving this one-time note because of your role at Northwind Pay. If you would rather not hear from us, reply "no" and I will not email again.
```

Hook-to-evidence map:

| Claim in the email | Evidence | Quote | Source |
|---|---|---|---|
| plans to certify against ISO 27001 | E1 | "plan to certify against ISO 27001 this year" | https://northwind-pay.example/ |
| hiring a Head of Security | E2 | "We are hiring a Head of Security" | https://northwind-pay.example/ |
| Sprinto automates compliance for SOC 2, ISO 27001 and GDPR | S1 (Sprinto whitelist) | - | - |
| continuous monitoring and audit-ready evidence collection | S2 (Sprinto whitelist) | - | - |

Validator: passed after 1 attempt(s).

## 4. Send
dry-run, Resend not called. From onboarding@resend.dev to owner@example.com (forced to the owner address).
Subject: `[TEST -> Maria Lopez <maria@northwind-pay.example>] iso 27001 timeline`
