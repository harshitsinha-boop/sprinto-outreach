---
schema_version: 1
open_count: 1
waived_count: 0
fixed_count: 0
total_count: 1
last_updated: 2026-11-03T10:03:54.525Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 01 | unrun-verify | .planning/phases/01-foundation-and-walking-skeleton/01-04-SUMMARY.md |  | Smoke email inbox arrival (Resend id 01a1a0db-bce1-7892-80d2-f213f192aba1) owner-pending | open |  | 2026-11-03T10:03:54.525Z |  |

````json
[
  {
    "id": 1,
    "kind": "unrun-verify",
    "phase": "01",
    "file": ".planning/phases/01-foundation-and-walking-skeleton/01-04-SUMMARY.md",
    "line": null,
    "description": "Smoke email inbox arrival (Resend id 01a1a0db-bce1-7892-80d2-f213f192aba1) owner-pending",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-11-03T10:03:54.525Z",
    "resolved_at": null,
    "milestone": null
  }
]
````
