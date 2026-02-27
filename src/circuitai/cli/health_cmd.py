"""Health tracking CLI commands — lab results import and management."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context
from circuitai.output.formatter import format_date


@click.group(cls=JsonGroup)
@pass_context
def health(ctx: CircuitContext) -> None:
    """Health tracking (lab results, import, flagged markers)."""
    pass


@health.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include soft-deleted results.")
@pass_context
def health_list(ctx: CircuitContext, show_all: bool) -> None:
    """List lab results."""
    from circuitai.services.lab_service import LabService

    db = ctx.get_db()
    svc = LabService(db)
    results = svc.list_results(active_only=not show_all)

    if ctx.json_mode:
        ctx.formatter.json([r.model_dump() for r in results])
        return

    if not results:
        ctx.formatter.info(
            "No lab results found. Import one:\n\n"
            "  /health import-lab --file /path/to/report.pdf\n"
            "  /browse sync labcorp"
        )
        return

    rows = []
    for r in results:
        panels = svc.get_panels(r.id)
        flagged = svc.get_flagged_markers(r.id)
        panel_count = len(panels)
        flagged_count = len(flagged)

        flag_str = f"[red]{flagged_count} flagged[/red]" if flagged_count else "[green]all normal[/green]"
        status_str = _status_style(r.status)

        rows.append([
            format_date(r.result_date),
            r.provider or "Unknown",
            status_str,
            str(panel_count),
            flag_str,
        ])

    ctx.formatter.table(
        title="Lab Results",
        columns=[
            ("Date", "cyan"),
            ("Provider", "bold"),
            ("Status", ""),
            ("Panels", "dim"),
            ("Markers", ""),
        ],
        rows=rows,
    )


@health.command("import-lab")
@click.option("--file", "file_path", type=click.Path(exists=True), help="Path to lab report PDF.")
@pass_context
def health_import_lab(ctx: CircuitContext, file_path: str | None) -> None:
    """Import lab results from a PDF report."""
    if not file_path:
        if ctx.json_mode:
            ctx.formatter.json_error("--file is required in JSON mode.")
            return
        file_path = click.prompt("Path to lab report PDF")

    if not file_path.lower().endswith(".pdf"):
        ctx.formatter.error("Only PDF files are supported.")
        return

    try:
        from circuitai.services.lab_service import LabService, HAS_PDFPLUMBER

        if not HAS_PDFPLUMBER:
            ctx.formatter.error(
                "pdfplumber package not installed.\n"
                "  Install with: pip install pdfplumber"
            )
            return

        db = ctx.get_db()
        svc = LabService(db)
        result = svc.import_from_pdf(file_path)

        if ctx.json_mode:
            ctx.formatter.json(result)
            return

        if result.get("duplicate"):
            ctx.formatter.warning(
                f"This report was already imported on {result.get('existing_date', 'unknown')}."
            )
            return

        ctx.formatter.success(
            f"Imported lab report:\n"
            f"  Panels: {result['panels_imported']}\n"
            f"  Markers: {result['markers_imported']}"
        )
        if result["flagged_count"]:
            ctx.formatter.warning(f"  Flagged markers: {result['flagged_count']}")

        # Show a quick detail view of what was imported
        detail = svc.get_result_detail(result["result_id"])
        _print_result_detail(ctx, detail)

    except Exception as e:
        if ctx.json_mode:
            ctx.formatter.json_error(str(e))
        else:
            ctx.formatter.error(f"Import failed: {e}")


@health.command("show")
@click.argument("result_id", required=False)
@pass_context
def health_show(ctx: CircuitContext, result_id: str | None) -> None:
    """Show detailed lab result with panels and markers."""
    from circuitai.services.lab_service import LabService

    db = ctx.get_db()
    svc = LabService(db)

    if not result_id:
        results = svc.list_results()
        if not results:
            ctx.formatter.info("No lab results found.")
            return

        if not ctx.json_mode:
            ctx.formatter.print("\n[bold]Select a lab result:[/bold]")
            for i, r in enumerate(results, 1):
                ctx.formatter.print(
                    f"  {i}. {format_date(r.result_date)} — {r.provider} ({r.status})"
                )
            choice = click.prompt("Number", type=int) - 1
            if choice < 0 or choice >= len(results):
                ctx.formatter.error("Invalid selection.")
                return
            result_id = results[choice].id
        else:
            ctx.formatter.json_error("result_id is required in JSON mode.")
            return

    detail = svc.get_result_detail(result_id)

    if ctx.json_mode:
        json_data = detail["result"].model_dump()
        json_data["panels"] = []
        for pd in detail["panels"]:
            panel_data = pd["panel"].model_dump()
            panel_data["markers"] = [m.model_dump() for m in pd["markers"]]
            json_data["panels"].append(panel_data)
        ctx.formatter.json(json_data)
        return

    _print_result_detail(ctx, detail)


@health.command("review")
@click.argument("result_id", required=False)
@pass_context
def health_review(ctx: CircuitContext, result_id: str | None) -> None:
    """Mark a lab result as reviewed."""
    from circuitai.services.lab_service import LabService

    db = ctx.get_db()
    svc = LabService(db)

    if not result_id:
        # Show unreviewed results
        unreviewed = [r for r in svc.list_results() if r.status != "reviewed"]
        if not unreviewed:
            ctx.formatter.info("No unreviewed lab results.")
            return

        if not ctx.json_mode:
            ctx.formatter.print("\n[bold]Unreviewed results:[/bold]")
            for i, r in enumerate(unreviewed, 1):
                ctx.formatter.print(
                    f"  {i}. {format_date(r.result_date)} — {r.provider}"
                )
            choice = click.prompt("Number", type=int) - 1
            if choice < 0 or choice >= len(unreviewed):
                ctx.formatter.error("Invalid selection.")
                return
            result_id = unreviewed[choice].id
        else:
            ctx.formatter.json_error("result_id is required in JSON mode.")
            return

    result = svc.mark_reviewed(result_id)

    if ctx.json_mode:
        ctx.formatter.json({"reviewed": result.id})
    else:
        ctx.formatter.success(
            f"Marked as reviewed: {result.provider} — {format_date(result.result_date)}"
        )


@health.command("flagged")
@pass_context
def health_flagged(ctx: CircuitContext) -> None:
    """Show all flagged/abnormal markers across unreviewed results."""
    from circuitai.services.lab_service import LabService

    db = ctx.get_db()
    svc = LabService(db)
    flagged = svc.markers.get_all_flagged()

    if ctx.json_mode:
        ctx.formatter.json([m.model_dump() for m in flagged])
        return

    if not flagged:
        ctx.formatter.success("No flagged markers in unreviewed results.")
        return

    rows = []
    for m in flagged:
        flag_style = _flag_style(m.flag)
        rows.append([
            m.marker_name,
            m.value,
            m.unit,
            m.reference_range,
            flag_style,
        ])

    ctx.formatter.table(
        title="Flagged Markers (unreviewed results)",
        columns=[
            ("Marker", "bold"),
            ("Value", ""),
            ("Unit", "dim"),
            ("Reference", "dim"),
            ("Flag", ""),
        ],
        rows=rows,
    )


@health.command("summary")
@pass_context
def health_summary(ctx: CircuitContext) -> None:
    """Health tracking overview."""
    from circuitai.services.lab_service import LabService

    db = ctx.get_db()
    svc = LabService(db)
    summary = svc.get_summary()

    if ctx.json_mode:
        ctx.formatter.json(summary)
        return

    ctx.formatter.print("\n[bold cyan]Health Summary[/bold cyan]")
    ctx.formatter.print(f"  Total lab results: {summary['total_results']}")
    ctx.formatter.print(f"  Unreviewed: {summary['unreviewed_count']}")
    ctx.formatter.print(f"  Flagged markers: {summary['flagged_marker_count']}")

    if summary["recent_results"]:
        ctx.formatter.print("\n  [bold]Recent Results:[/bold]")
        for r in summary["recent_results"]:
            ctx.formatter.print(
                f"    {format_date(r.get('result_date'))} — "
                f"{r.get('provider', 'Unknown')} ({r.get('status', '')})"
            )


# ── Helpers ───────────────────────────────────────────────────

def _status_style(status: str) -> str:
    if status == "reviewed":
        return "[green]reviewed[/green]"
    if status == "completed":
        return "[yellow]completed[/yellow]"
    return f"[dim]{status}[/dim]"


def _flag_style(flag: str) -> str:
    if flag == "high":
        return "[red]HIGH[/red]"
    if flag == "low":
        return "[blue]LOW[/blue]"
    if flag == "critical":
        return "[bold red]CRITICAL[/bold red]"
    return "[green]normal[/green]"


def _print_result_detail(ctx: CircuitContext, detail: dict) -> None:
    """Print a detailed lab result with Rich formatting."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    result = detail["result"]

    # Header
    header = (
        f"[bold]Patient:[/bold] {result.patient_name or 'N/A'}\n"
        f"[bold]Physician:[/bold] {result.ordering_physician or 'N/A'}\n"
        f"[bold]Status:[/bold] {_status_style(result.status)}"
    )

    panels_content = []
    for pd in detail["panels"]:
        panel = pd["panel"]
        markers = pd["markers"]

        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("Marker", style="bold")
        table.add_column("Value", justify="right")
        table.add_column("Unit", style="dim")
        table.add_column("Reference", style="dim")
        table.add_column("Flag")

        for m in markers:
            flag_str = _flag_style(m.flag)
            table.add_row(
                m.marker_name,
                m.value,
                m.unit,
                m.reference_range,
                flag_str if m.is_flagged else "",
            )

        panel_status = panel.status
        if panel_status == "abnormal":
            panel_title = f"[yellow]{panel.panel_name} (abnormal)[/yellow]"
        elif panel_status == "critical":
            panel_title = f"[red]{panel.panel_name} (critical)[/red]"
        else:
            panel_title = f"[green]{panel.panel_name} (normal)[/green]"

        panels_content.append(Panel(table, title=panel_title, border_style="dim"))

    title = f"Lab Results: {result.provider or 'Unknown'} — {format_date(result.result_date)}"
    console.print()
    console.print(Panel(header, title=title, border_style="cyan"))
    for p in panels_content:
        console.print(p)
