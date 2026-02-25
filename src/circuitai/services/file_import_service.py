"""File import service — detects dragged file paths and routes to the correct adapter."""

from __future__ import annotations

import os
import re
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import AdapterError

SUPPORTED_EXTENSIONS = {".csv", ".pdf"}


def looks_like_file_path(text: str) -> str | None:
    """Detect if text looks like a dragged-in file path.

    Handles:
    - Absolute paths: /Users/foo/file.csv
    - Quoted paths: '/Users/foo/my file.csv' or "/Users/foo/my file.csv"
    - Backslash-escaped spaces: /Users/foo/my\\ file.csv
    - Tilde paths: ~/Downloads/file.csv

    Returns the resolved path if it exists and has a supported extension, else None.
    """
    cleaned = text.strip()
    if not cleaned:
        return None

    # Strip surrounding quotes
    if (cleaned.startswith("'") and cleaned.endswith("'")) or (
        cleaned.startswith('"') and cleaned.endswith('"')
    ):
        cleaned = cleaned[1:-1]

    # Unescape backslash-escaped spaces
    cleaned = cleaned.replace("\\ ", " ")

    # Expand tilde
    cleaned = os.path.expanduser(cleaned)

    # Must be an absolute path
    if not os.path.isabs(cleaned):
        return None

    # Check extension
    _, ext = os.path.splitext(cleaned)
    if ext.lower() not in SUPPORTED_EXTENSIONS:
        return None

    # Check file exists
    if not os.path.isfile(cleaned):
        return None

    return cleaned


def get_file_type(path: str) -> str:
    """Return 'csv' or 'pdf' based on file extension."""
    _, ext = os.path.splitext(path)
    return ext.lower().lstrip(".")


def import_file(
    db: DatabaseConnection, file_path: str, account_id: str, **kwargs: Any
) -> dict[str, Any]:
    """Import a file using the appropriate adapter.

    For CSV: uses CsvImportAdapter.
    For PDF: uses PdfImportAdapter with mode from kwargs.get('mode', 'transactions').
    """
    file_type = get_file_type(file_path)

    if file_type == "csv":
        from circuitai.adapters.builtin.csv_import import CsvImportAdapter

        adapter = CsvImportAdapter()
        adapter.configure_for_file(
            file_path=file_path,
            account_id=account_id,
            date_column=kwargs.get("date_column", "date"),
            description_column=kwargs.get("description_column", "description"),
            amount_column=kwargs.get("amount_column", "amount"),
        )
        return adapter.sync(db)

    if file_type == "pdf":
        try:
            from circuitai.adapters.builtin.pdf_import import PdfImportAdapter
        except ImportError as e:
            raise AdapterError(
                "PDF import requires pdfplumber. Install with: pip install circuitai[pdf]"
            ) from e

        adapter = PdfImportAdapter()
        mode = kwargs.get("mode", "transactions")
        adapter.configure_for_file(file_path=file_path, account_id=account_id, mode=mode)
        return adapter.sync(db)

    raise AdapterError(f"Unsupported file type: {file_type}")
