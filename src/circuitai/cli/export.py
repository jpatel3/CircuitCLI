"""Export CLI commands — CSV and JSON export."""

from __future__ import annotations

import csv
import io
import json
from typing import Any

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context


@click.group(cls=JsonGroup)
@pass_context
def export(ctx: CircuitContext) -> None:
    """Export data to CSV or JSON."""
    pass


@export.command("csv")
@click.option(
    "--entity", required=True,
    type=click.Choice(["bills", "accounts", "cards", "investments", "deadlines", "activities"]),
)
@click.option("--output", "-o", "output_file", default=None, help="Output file path (stdout if not specified).")
@pass_context
def export_csv(ctx: CircuitContext, entity: str, output_file: str | None) -> None:
    """Export data as CSV."""
    db = ctx.get_db()
    data = _get_entity_data(db, entity)

    if not data:
        ctx.formatter.info(f"No {entity} data to export.")
        return

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=data[0].keys())
    writer.writeheader()
    writer.writerows(data)

    csv_text = output.getvalue()
    if output_file:
        with open(output_file, "w") as f:
            f.write(csv_text)
        ctx.formatter.success(f"Exported {len(data)} {entity} records to {output_file}")
    else:
        click.echo(csv_text)


@export.command("json")
@click.option(
    "--entity", required=True,
    type=click.Choice(["bills", "accounts", "cards", "investments", "deadlines", "activities", "all"]),
)
@click.option("--output", "-o", "output_file", default=None)
@pass_context
def export_json(ctx: CircuitContext, entity: str, output_file: str | None) -> None:
    """Export data as JSON."""
    db = ctx.get_db()

    if entity == "all":
        data = {}
        for ent in ["bills", "accounts", "cards", "investments", "deadlines", "activities"]:
            data[ent] = _get_entity_data(db, ent)
    else:
        data = _get_entity_data(db, entity)  # type: ignore[assignment]

    json_text = json.dumps(data, indent=2, default=str)
    if output_file:
        with open(output_file, "w") as f:
            f.write(json_text)
        ctx.formatter.success(f"Exported to {output_file}")
    else:
        click.echo(json_text)


def _get_entity_data(db: Any, entity: str) -> list[dict[str, Any]]:
    """Get entity data as a list of dicts."""
    entity_map = {
        "bills": ("circuitai.services.bill_service", "BillService", "list_bills"),
        "accounts": ("circuitai.services.account_service", "AccountService", "list_accounts"),
        "cards": ("circuitai.services.card_service", "CardService", "list_cards"),
        "investments": ("circuitai.services.investment_service", "InvestmentService", "list_investments"),
        "deadlines": ("circuitai.services.deadline_service", "DeadlineService", "list_deadlines"),
        "activities": ("circuitai.services.activity_service", "ActivityService", "list_activities"),
    }

    if entity not in entity_map:
        return []

    module_name, class_name, method_name = entity_map[entity]
    import importlib
    module = importlib.import_module(module_name)
    svc_class = getattr(module, class_name)
    svc = svc_class(db)
    items = getattr(svc, method_name)(active_only=False)
    return [item.model_dump() for item in items]
