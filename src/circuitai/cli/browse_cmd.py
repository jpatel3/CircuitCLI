"""Browser automation CLI commands — login to financial sites and extract billing data."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context


@click.group(cls=JsonGroup)
@pass_context
def browse(ctx: CircuitContext) -> None:
    """Browser-based account sync — login to financial sites and import billing data."""
    pass


@browse.command("list-sites")
@pass_context
def browse_list_sites(ctx: CircuitContext) -> None:
    """Show all available site adapters."""
    from circuitai.services.sites import list_sites

    sites = list_sites()

    if ctx.json_mode:
        ctx.formatter.json(sites)
        return

    if not sites:
        ctx.formatter.info("No site adapters available.")
        return

    columns = [("Key", "bold"), ("Name", ""), ("Domain", "cyan"), ("Category", "dim")]
    rows = [[s["key"], s["name"], s["domain"], s["category"]] for s in sites]
    ctx.formatter.table("Available Sites", columns, rows, data_for_json=sites)


@browse.command("setup")
@click.argument("site")
@pass_context
def browse_setup(ctx: CircuitContext, site: str) -> None:
    """Configure credentials for a site (stored in system keychain)."""
    if ctx.json_mode:
        ctx.formatter.json_error("Browse setup requires interactive mode.", code=1)
        return

    from circuitai.services.browser_service import HAS_PLAYWRIGHT
    if not HAS_PLAYWRIGHT:
        ctx.formatter.error(
            "playwright package not installed.\n"
            "  Install with: pip install circuitai[browser]\n"
            "  Then run: playwright install chromium"
        )
        return

    from circuitai.services.sites import get_site
    try:
        site_cls = get_site(site)
    except KeyError as e:
        ctx.formatter.error(str(e))
        return

    ctx.formatter.print(f"\n[bold cyan]{site_cls.DISPLAY_NAME} Setup[/bold cyan]")
    ctx.formatter.print(f"Credentials will be stored in your system keychain.\n")

    username = click.prompt("Username / Email")
    password = click.prompt("Password", hide_input=True)

    if not username or not password:
        ctx.formatter.warning("No credentials provided. Setup cancelled.")
        return

    from circuitai.services.browser_service import BrowserService

    db = ctx.get_db()
    svc = BrowserService(db)
    svc.save_credentials(site, username, password)
    ctx.formatter.success(
        f"Credentials saved for {site_cls.DISPLAY_NAME}. "
        f"Run 'circuit browse sync {site}' to sync."
    )


@browse.command("sync")
@click.argument("site")
@pass_context
def browse_sync(ctx: CircuitContext, site: str) -> None:
    """Launch browser, login to a site, and import billing data."""
    from circuitai.services.browser_service import BrowserService, HAS_PLAYWRIGHT

    if not HAS_PLAYWRIGHT:
        ctx.formatter.error(
            "playwright package not installed.\n"
            "  Install with: pip install circuitai[browser]\n"
            "  Then run: playwright install chromium"
        )
        return

    from circuitai.services.sites import get_site
    try:
        site_cls = get_site(site)
    except KeyError as e:
        ctx.formatter.error(str(e))
        return

    db = ctx.get_db()
    svc = BrowserService(db)

    # Check credentials
    creds = svc.get_credentials(site)
    if not creds:
        ctx.formatter.error(
            f"No credentials found for {site}. Run 'circuit browse setup {site}' first."
        )
        return

    username, password = creds

    if not ctx.json_mode:
        ctx.formatter.info(f"Launching browser for {site_cls.DISPLAY_NAME}...")

    try:
        _browser, _context, page = svc.launch_browser()

        # Instantiate the site adapter
        site_adapter = site_cls(page, svc)

        # Login
        if not ctx.json_mode:
            ctx.formatter.info("Logging in...")
        success = site_adapter.login(username, password)
        if not success:
            ctx.formatter.error("Login failed. Check your credentials with 'circuit browse setup'.")
            return

        if not ctx.json_mode:
            ctx.formatter.success("Login successful.")

        # Extract billing data
        if not ctx.json_mode:
            ctx.formatter.info("Extracting billing data...")
        data = site_adapter.extract_billing()

        if data.get("error"):
            ctx.formatter.warning(f"Extraction issue: {data['error']}")

        # Route based on data type
        if data.get("data_type") == "lab_results":
            from circuitai.services.lab_service import LabService
            lab_svc = LabService(db)
            lab_results = data.get("results", [])
            new_count = 0
            dup_count = 0
            total_panels = 0
            total_markers = 0
            total_flagged = 0
            for result_data in lab_results:
                r = lab_svc.import_lab_data(result_data, source="browser")
                if r.get("duplicate"):
                    dup_count += 1
                else:
                    new_count += 1
                    total_panels += r["panels_imported"]
                    total_markers += r["markers_imported"]
                    total_flagged += r["flagged_count"]

            result = {
                "results_imported": new_count,
                "duplicates_skipped": dup_count,
                "panels_imported": total_panels,
                "markers_imported": total_markers,
                "flagged_count": total_flagged,
            }

            if ctx.json_mode:
                ctx.formatter.json(result)
                return

            msg = f"Imported {new_count} lab results — {total_panels} panels, {total_markers} markers"
            if total_flagged:
                msg += f" ({total_flagged} flagged)"
            if dup_count:
                msg += f"\n  {dup_count} duplicate(s) skipped"
            ctx.formatter.success(msg)
        else:
            # Standard billing data import
            result = svc.import_bill_data(site, data)

            if ctx.json_mode:
                ctx.formatter.json(result)
                return

            ctx.formatter.success(
                f"Bill: {result['bill_name']} — "
                f"${result['amount_cents'] / 100:.2f}\n"
                f"  Imported {result['imported']} payments, "
                f"skipped {result['skipped']} duplicates."
            )

    except Exception as e:
        if ctx.json_mode:
            ctx.formatter.json_error(str(e))
        else:
            ctx.formatter.error(f"Browser sync failed: {e}")
    finally:
        svc.close_browser()


@browse.command("status")
@pass_context
def browse_status(ctx: CircuitContext) -> None:
    """Show configured sites and credential status."""
    from circuitai.services.browser_service import BrowserService, HAS_PLAYWRIGHT
    from circuitai.services.sites import list_sites

    sites = list_sites()

    if not HAS_PLAYWRIGHT:
        status_data = {
            "playwright_installed": False,
            "sites": [],
        }
        if ctx.json_mode:
            ctx.formatter.json(status_data)
        else:
            ctx.formatter.print("\n[bold cyan]Browse Status[/bold cyan]")
            ctx.formatter.warning(
                "playwright not installed. Install with: pip install circuitai[browser]\n"
                "  Then run: playwright install chromium"
            )
        return

    db = ctx.get_db()
    svc = BrowserService(db)

    site_statuses = []
    for s in sites:
        has_creds = svc.has_credentials(s["key"])
        site_statuses.append({
            "key": s["key"],
            "name": s["name"],
            "domain": s["domain"],
            "credentials_configured": has_creds,
        })

    status_data = {
        "playwright_installed": True,
        "sites": site_statuses,
    }

    if ctx.json_mode:
        ctx.formatter.json(status_data)
        return

    ctx.formatter.print("\n[bold cyan]Browse Status[/bold cyan]")
    ctx.formatter.success("Playwright installed.")

    if not site_statuses:
        ctx.formatter.info("No site adapters available.")
        return

    columns = [("Site", "bold"), ("Domain", "cyan"), ("Credentials", "")]
    rows = []
    for s in site_statuses:
        cred_status = "[green]Configured[/green]" if s["credentials_configured"] else "[dim]Not set[/dim]"
        rows.append([s["name"], s["domain"], cred_status])
    ctx.formatter.table("Sites", columns, rows, data_for_json=site_statuses)
