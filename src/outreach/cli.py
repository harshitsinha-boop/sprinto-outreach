"""Commands: `run` (a file of domains), `skeleton` (one domain, dry run) and `smoke` (live proof).

`skeleton` never calls Resend. `run` is a dry run unless `--send` is passed; `smoke` sends
only to OWNER_EMAIL. Every send goes through the guarded `send_email`.
"""

import sys
from pathlib import Path
from typing import TextIO

import typer

from outreach.audit import RunStore
from outreach.config import ConfigError, Settings, configure_logging, load_settings, redact
from outreach.fetch import PageFetcher
from outreach.hunter import FixtureHunter, HunterClient
from outreach.llm import LLMClient
from outreach.runner import load_domains, render_summary, run_batch, write_summary
from outreach.skeleton import Context, run_one
from outreach.smoke import SMOKE_CHECKS, run_smoke

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Sprinto cold outreach pipeline: run (a file of domains), skeleton (one domain) and smoke.",
)


def build_context(
    settings: Settings,
    *,
    hunter_fixture: bool = False,
    dry_run: bool = True,
    out: TextIO | None = None,
) -> Context:
    """Wire the real clients into a Context. `sender` stays None: only the guarded
    `send_email` default (resend.Emails.send) can ever send, and only when dry_run is False."""
    hunter = (
        FixtureHunter()
        if hunter_fixture
        else HunterClient(
            settings.hunter_api_key.get_secret_value(),
            settings.cache_dir / "hunter",
            settings.hunter_monthly_budget,
        )
    )
    return Context(
        settings=settings,
        llm=LLMClient(settings.gemini_api_key.get_secret_value(), cache_dir=settings.cache_dir / "llm"),
        hunter=hunter,
        fetcher=PageFetcher(settings.cache_dir / "pages"),
        store=RunStore(settings.out_dir),
        dry_run=dry_run,
        sender=None,
        out=out,
    )


def _fail_config(e: ConfigError) -> "typer.Exit":
    typer.echo(str(e), err=True)  # names only, never values
    return typer.Exit(2)


@app.command()
def run(
    domains_file: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        metavar="DOMAINS_FILE",
        help="Text file with one company domain per line (# comments and blank lines are skipped).",
    ),
) -> None:
    """Run every domain in a file through the pipeline and print one summary table.

    A dry run: payloads are printed and Resend is never called.
    """
    configure_logging()
    require = ("GEMINI_API_KEY", "OWNER_EMAIL")
    try:
        settings = load_settings(require=require)
    except ConfigError as e:
        raise _fail_config(e) from None

    entries = load_domains(domains_file)
    n_domains = sum(1 for e in entries if isinstance(e, str))
    if n_domains == 0:
        typer.echo(f"no domains in {domains_file}", err=True)
        raise typer.Exit(2)

    typer.echo(
        f"MODE: dry-run (Resend will NOT be called) | recipient: {settings.owner_email} "
        f"| hunter: fixture (no credits; contact only for {FixtureHunter().fixture_domain}) "
        f"| domains: {n_domains}"
    )
    ctx = build_context(settings, hunter_fixture=True, dry_run=True)
    summary = run_batch(entries, ctx, hunter_label="fixture", progress=sys.stdout)
    path = write_summary(summary, settings.out_dir)
    typer.echo(render_summary(summary))
    typer.echo(f"batch=complete domains={len(summary.rows)} summary={path}")
    sys.stdout.flush()
    raise typer.Exit(0)


@app.command()
def skeleton(
    domain: str | None = typer.Option(
        None, "--domain", help="Company domain to run (default: SKELETON_DOMAIN)."
    ),
    hunter_fixture: bool = typer.Option(
        False,
        "--hunter-fixture",
        help="Use the captured Hunter fixture (contact only for its own domain) and spend no credit.",
    ),
) -> None:
    """Run one domain through scrape, extract, score, hunter, draft and a DRY-RUN send."""
    configure_logging()
    require = ("GEMINI_API_KEY", "OWNER_EMAIL") + (() if hunter_fixture else ("HUNTER_API_KEY",))
    try:
        settings = load_settings(require=require)
    except ConfigError as e:
        raise _fail_config(e) from None

    target = domain or settings.skeleton_domain
    if not target:
        typer.echo("pass --domain or set SKELETON_DOMAIN", err=True)
        raise typer.Exit(2)

    if hunter_fixture:
        hunter_note = f"fixture (contact only for {FixtureHunter().fixture_domain})"
    else:
        hunter_note = f"cache-first, budget {settings.hunter_monthly_budget}"
    typer.echo(
        f"MODE: dry-run (Resend will NOT be called) | recipient: {settings.owner_email} "
        f"| hunter: {hunter_note}"
    )

    ctx = build_context(settings, hunter_fixture=hunter_fixture, dry_run=True)
    try:
        rec = run_one(target, ctx)
    except Exception as exc:
        typer.echo(f"FAILED: {redact(f'{type(exc).__name__}: {exc}', settings)}", err=True)
        typer.echo(f"run_record={ctx.store.path_for(target)}", err=True)
        raise typer.Exit(1) from None

    counters = rec.counters
    if rec.status == "stopped":
        typer.echo(f"stop_reason={rec.stop_reason}")
    typer.echo(
        f"status={rec.status} run_record={ctx.store.path_for(target)} "
        f"llm_api_calls={counters.get('llm_api_calls', 0)} "
        f"llm_cache_hits={counters.get('llm_cache_hits', 0)} "
        f"hunter_live_calls={counters.get('hunter_live_calls', 0)}"
    )
    sys.stdout.flush()
    raise typer.Exit(0 if rec.status == "dry_run" else 2)


@app.command()
def smoke(
    only: str | None = typer.Option(
        None, "--only", help=f"Run one check family: {', '.join(SMOKE_CHECKS)}."
    ),
) -> None:
    """Prove the live integrations (Gemini, Hunter, Resend) with real keys. Exit 0 only if all pass."""
    if only is not None and only not in SMOKE_CHECKS:
        typer.echo(f"--only must be one of: {', '.join(SMOKE_CHECKS)}", err=True)
        raise typer.Exit(2)
    configure_logging()
    try:
        settings = load_settings()
    except ConfigError as e:
        raise _fail_config(e) from None

    results = run_smoke(settings, only=only)
    raise typer.Exit(0 if all(r.ok and not r.skipped for r in results) else 1)
