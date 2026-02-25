"""Tests for file import detection and routing."""

from __future__ import annotations

import os
import tempfile

import pytest

from circuitai.services.file_import_service import get_file_type, looks_like_file_path


class TestLooksLikeFilePath:
    """Tests for looks_like_file_path()."""

    def test_absolute_csv_path(self, tmp_path):
        f = tmp_path / "statement.csv"
        f.write_text("date,description,amount\n")
        assert looks_like_file_path(str(f)) == str(f)

    def test_absolute_pdf_path(self, tmp_path):
        f = tmp_path / "bill.pdf"
        f.write_bytes(b"%PDF-1.4 fake")
        assert looks_like_file_path(str(f)) == str(f)

    def test_single_quoted_path(self, tmp_path):
        f = tmp_path / "my statement.csv"
        f.write_text("data\n")
        assert looks_like_file_path(f"'{f}'") == str(f)

    def test_double_quoted_path(self, tmp_path):
        f = tmp_path / "my bill.pdf"
        f.write_bytes(b"%PDF")
        assert looks_like_file_path(f'"{f}"') == str(f)

    def test_backslash_escaped_spaces(self, tmp_path):
        f = tmp_path / "my file.csv"
        f.write_text("data\n")
        escaped = str(f).replace(" ", "\\ ")
        assert looks_like_file_path(escaped) == str(f)

    def test_tilde_expansion(self):
        # Create a temp file in the real home directory
        home = os.path.expanduser("~")
        test_file = os.path.join(home, ".circuitai_test_import.csv")
        try:
            with open(test_file, "w") as f:
                f.write("data\n")
            result = looks_like_file_path("~/.circuitai_test_import.csv")
            assert result == test_file
        finally:
            os.unlink(test_file)

    def test_rejects_nonexistent_path(self):
        assert looks_like_file_path("/tmp/does_not_exist_12345.csv") is None

    def test_rejects_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.xlsx"
        f.write_bytes(b"fake")
        assert looks_like_file_path(str(f)) is None

    def test_rejects_txt_extension(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello\n")
        assert looks_like_file_path(str(f)) is None

    def test_rejects_normal_text(self):
        assert looks_like_file_path("what bills are due?") is None

    def test_rejects_slash_commands(self):
        assert looks_like_file_path("/bills list") is None

    def test_rejects_empty_string(self):
        assert looks_like_file_path("") is None

    def test_rejects_relative_path(self, tmp_path):
        f = tmp_path / "file.csv"
        f.write_text("data\n")
        assert looks_like_file_path("file.csv") is None

    def test_strips_whitespace(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("x\n")
        assert looks_like_file_path(f"  {f}  ") == str(f)

    def test_rejects_directory(self, tmp_path):
        d = tmp_path / "somedir.csv"
        d.mkdir()
        assert looks_like_file_path(str(d)) is None


class TestGetFileType:
    """Tests for get_file_type()."""

    def test_csv(self):
        assert get_file_type("/path/to/file.csv") == "csv"

    def test_pdf(self):
        assert get_file_type("/path/to/bill.pdf") == "pdf"

    def test_uppercase_extension(self):
        assert get_file_type("/path/to/FILE.CSV") == "csv"

    def test_pdf_uppercase(self):
        assert get_file_type("/path/to/BILL.PDF") == "pdf"
