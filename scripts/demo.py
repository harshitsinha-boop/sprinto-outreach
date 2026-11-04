"""Offline demo over six fixture domains: two fits, a non-fit, an unscrapeable site, an
unreachable site and a qualified company with no Hunter contact.

No network, no keys, no send: it drives the real pipeline through the test fakes and saves the
summary table, every decision log and the dry-run payloads under docs/demo/.

    .venv/bin/python scripts/demo.py
"""

from __future__ import annotations

import io
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "src"))

from conftest import CANARY_ENV, GOOD_BODY, FakeHunter, FakeLLM, default_llm_responses  # noqa: E402

from outreach.audit import RunStore  # noqa: E402
from outreach.config import load_settings  # noqa: E402
from outreach.models import (  # noqa: E402
    ClaimUsed, CompanyProfile, ComplianceMention, DraftLLM, EnterpriseCustomer, EvidencedBool,
    EvidencedText, HeadcountFact, HiringSignal, PageResult, PainPoint, PainPointSet,
)
from outreach.runner import render_summary, run_batch  # noqa: E402
from outreach.skeleton import Context  # noqa: E402

OUT = ROOT / "docs" / "demo"

NORTH_TEXT = (
    "Northwind Pay is a B2B payments platform that helps banks reconcile transfers every day. "
    "Our customers include Fabrikam Bank and Tailspin Credit Union, and they rely on us for "
    "audit trails across every ledger. We plan to certify against ISO 27001 this year and SOC 2 "
    "is on our roadmap. We are a team of about 300 people across three offices. We are hiring a "
    "Head of Security to lead our compliance program."
)
PETS_TEXT = (
    "Pocket Pals is a mobile game for kids and families, free to download on every app store. "
    "Collect pets, decorate your room and play with friends after school every single day. "
    "Parents can set screen time limits, and every pet has a unique story that unfolds as your "
    "child plays through the seasonal events we release each month. Download Pocket Pals today "
    "and start building the happiest pet village on your phone, with new friends to meet in "
    "every level and daily rewards waiting for you each morning when you log in again."
)


def north_profile(domain: str) -> CompanyProfile:
    url = f"https://{domain}/"

    def ev(q):
        return {"quote": q, "source_url": url}

    return CompanyProfile(
        name=EvidencedText(value="Northwind Pay", **ev("Northwind Pay is a B2B payments platform")),
        offering=EvidencedText(value="bank payment reconciliation", **ev("helps banks reconcile transfers")),
        is_b2b=EvidencedBool(value=True, **ev("Northwind Pay is a B2B payments platform")),
        stage=None,
        headcount=HeadcountFact(value="201-500", **ev("a team of about 300 people")),
        compliance_mentions=[
            ComplianceMention(framework="ISO 27001", status="planned", as_of=None, **ev("plan to certify against ISO 27001 this year"))
        ],
        hiring_signals=[HiringSignal(role="Head of Security", **ev("We are hiring a Head of Security"))],
        enterprise_customers=[
            EnterpriseCustomer(name="Fabrikam Bank", **ev("Our customers include Fabrikam Bank and Tailspin Credit Union")),
            EnterpriseCustomer(name="Tailspin Credit Union", **ev("Fabrikam Bank and Tailspin Credit Union")),
        ],
    )


def pets_profile(domain: str) -> CompanyProfile:
    url, q = f"https://{domain}/", "Pocket Pals is a mobile game for kids and families"
    return CompanyProfile(
        name=EvidencedText(value="Pocket Pals", quote=q, source_url=url),
        offering=EvidencedText(value="mobile game", quote=q, source_url=url),
        is_b2b=EvidencedBool(value=False, quote=q, source_url=url),
        stage=None, headcount=None, compliance_mentions=[], hiring_signals=[], enterprise_customers=[],
    )


NORTH_BODY = (
    "Hi Maria, saw Northwind Pay plans to certify against ISO 27001 and is hiring a Head of "
    "Security. For a security lead, that usually means chasing evidence across teams ahead of "
    "customer reviews from banks. Sprinto automates compliance for SOC 2, ISO 27001 and GDPR, "
    "with continuous monitoring and audit-ready evidence collection. Is that worth a look?"
)

COMPANIES = {
    # domain: (page text, profile builder, Hunter emails or None for the captured fixture)
    "acme-ledger.example": (None, None, None),
    "northwind-pay.example": (NORTH_TEXT, north_profile, [
        {"value": "maria@northwind-pay.example", "first_name": "Maria", "last_name": "Lopez",
         "position": "CISO", "confidence": 96, "seniority": "executive", "decision_maker": True,
         "linkedin": "https://www.linkedin.com/in/maria-lopez-demo", "verification": {"status": "valid"}},
        {"value": "tom@northwind-pay.example", "first_name": "Tom", "last_name": "Reed",
         "position": "VP Sales", "confidence": 99, "seniority": "executive", "verification": {"status": "valid"}},
        {"value": "ana@northwind-pay.example", "first_name": "Ana", "last_name": "Kim",
         "position": "Director of Engineering", "confidence": 90, "seniority": "senior", "verification": {"status": "valid"}},
    ]),
    "pocket-pals.example": (PETS_TEXT, pets_profile, None),
    "ghost-site.example": ("x" * 30, None, None),  # thin page: nothing usable reaches the LLM
    "unreachable.example": (None, None, None),  # every fetch errors
    "nocontact-co.example": (None, None, []),  # qualifies, Hunter has nobody
}


class DemoFetcher:
    def fetch(self, url, site=None):
        from conftest import SAMPLE_PAGE_TEXT

        host = url.split("/")[2]
        domain = next((d for d in COMPANIES if host == d or host.endswith("." + d)), "")
        if domain == "unreachable.example":
            return PageResult(url=url, status="error", error="DNS resolution failed")
        text = COMPANIES.get(domain, (None,))[0] or SAMPLE_PAGE_TEXT
        return PageResult(url=url, status="ok", text=text, chars=len(text))


class DemoLLM(FakeLLM):
    def _domain(self, prompt: str) -> str:
        for d, (_, _, _) in COMPANIES.items():
            if d in prompt:
                return d
        if "Northwind Pay" in prompt:
            return "northwind-pay.example"
        return "acme-ledger.example"

    def generate_structured(self, *, model, system, prompt, schema, purpose, **kw):
        domain = self._domain(prompt)
        if domain == "northwind-pay.example" and purpose in ("extract", "draft", "pain_points"):
            if purpose == "extract":
                self.responses["extract"] = north_profile(domain)
            elif purpose == "draft":
                self.responses["draft"] = DraftLLM(subject="iso 27001 timeline", body=NORTH_BODY, claims_used=[
                    ClaimUsed(claim="plans to certify against ISO 27001", evidence_id="E1"),
                    ClaimUsed(claim="hiring a Head of Security", evidence_id="E2"),
                ])
            else:
                self.responses["pain_points"] = PainPointSet(pain_points=[
                    PainPoint(pain="Bank customers will ask for proof of ISO 27001 progress during security reviews.",
                              role_link="a CISO owns security posture and proof to customers", evidence_id="E1"),
                    PainPoint(pain="A new Head of Security inherits evidence collection across teams.",
                              role_link="a CISO owns the compliance program", evidence_id="E2"),
                ])
        elif domain == "pocket-pals.example" and purpose == "extract":
            self.responses["extract"] = pets_profile(domain)
        elif purpose == "extract":
            self.responses["extract"] = default_llm_responses()["extract"]
        elif purpose == "draft":
            self.responses["draft"] = default_llm_responses()["draft"]
        return super().generate_structured(model=model, system=system, prompt=prompt, schema=schema, purpose=purpose, **kw)


class DemoHunter(FakeHunter):
    def domain_search(self, domain):
        emails = COMPANIES.get(domain, (None, None, None))[2]
        self.emails_override = emails
        return super().domain_search(domain)


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="outreach-demo-"))
    settings = load_settings(env=CANARY_ENV).model_copy(update={"cache_dir": work / ".cache", "out_dir": work / "out"})
    payloads = io.StringIO()
    ctx = Context(settings=settings, llm=DemoLLM(), hunter=DemoHunter(), fetcher=DemoFetcher(),
                  store=RunStore(settings.out_dir), dry_run=True, out=payloads)
    summary = run_batch(list(COMPANIES), ctx, hunter_label="fixture")

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    (OUT / "summary.txt").write_text(render_summary(summary) + "\n")
    (OUT / "dry_run_payloads.txt").write_text(payloads.getvalue())
    for domain in COMPANIES:
        decision = settings.out_dir / domain / "decision.md"
        if decision.exists():
            shutil.copy(decision, OUT / f"{domain}.decision.md")
        else:
            rec = ctx.store.load(domain)
            (OUT / f"{domain}.decision.md").write_text(
                f"# Decision log: {domain}\n\nStatus: **{rec.status if rec else 'unknown'}**"
                + (f"\n\n{[s.error for s in rec.stages if s.error]}" if rec else "") + "\n"
            )
    print(render_summary(summary))
    print(f"\nsaved under {OUT}")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
