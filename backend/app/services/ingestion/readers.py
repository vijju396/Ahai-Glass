"""Generic streaming readers for CSV, XLSX and XLSB.

Deliberately dataset-agnostic: nothing here knows an AIS column name. The
largest source file is 82 MB / 1.7 M rows, so every reader yields row tuples
rather than materialising a DataFrame - a whole-file read of the .xlsb costs
several GB and offers nothing a streaming pass does not.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# Excel's day-zero. Excel treats 1900 as a leap year, so serial 1 is
# 1900-01-01 and the correct origin for arithmetic is 1899-12-30
# (docs/DATA_CONTRACT.md rule C4).
EXCEL_EPOCH = datetime(1899, 12, 30)

#: Serials outside this band are not plausible dates in this dataset and are
#: reported rather than silently converted. 20000 ~ 1954-10, 60000 ~ 2064-03.
MIN_PLAUSIBLE_SERIAL = 20_000
MAX_PLAUSIBLE_SERIAL = 60_000


class SourceReadError(RuntimeError):
    """Raised when a source file cannot be read at all."""


@dataclass
class SheetInfo:
    name: str
    header: list[str]
    row_count: int


@dataclass
class ReadStats:
    """Counters a caller can assert on. Nothing here is inferred."""

    rows_read: int = 0
    rows_skipped_blank: int = 0
    header_columns: list[str] = field(default_factory=list)


def file_sha256(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# Excel serial dates (rule C4)
# --------------------------------------------------------------------------

def excel_serial_to_date(value: Any) -> date | None:
    """Convert an Excel serial to a date on the 1899-12-30 epoch.

    Returns None for anything that is not a plausible serial, so a caller can
    count and report the failures instead of inheriting a wrong date. Values
    that are already dates pass through.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        serial = float(value)
    except (TypeError, ValueError):
        return None
    if not (MIN_PLAUSIBLE_SERIAL <= serial <= MAX_PLAUSIBLE_SERIAL):
        return None
    return (EXCEL_EPOCH + timedelta(days=serial)).date()


def parse_loose_date(value: Any) -> date | None:
    """Parse a date that may arrive as a datetime, an Excel serial, or text.

    Explicitly returns None for the `0000-00-00` sentinel and other corrupt
    values found in the despatch-date column, rather than guessing (rule C14).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.startswith("0000-00-00") or text in {"None", "nan", "NaT"}:
        return None
    if text.replace(".", "", 1).isdigit() and "-" not in text:
        return excel_serial_to_date(text)
    for pattern in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    return None


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------

def read_csv_rows(
    path: Path, *, skip_rows: int = 0, encoding: str = "utf-8-sig"
) -> tuple[list[str], Iterator[list[str]]]:
    """Return (header, row iterator). `skip_rows` drops leading title rows."""
    handle = path.open("r", newline="", encoding=encoding, errors="replace")
    reader = csv.reader(handle)
    for _ in range(skip_rows):
        next(reader, None)
    header = next(reader, None)
    if header is None:
        handle.close()
        raise SourceReadError(f"{path.name} has no header row.")

    def rows() -> Iterator[list[str]]:
        try:
            yield from reader
        finally:
            handle.close()

    return [str(column).strip() for column in header], rows()


# --------------------------------------------------------------------------
# XLSX (openpyxl read-only, streaming)
# --------------------------------------------------------------------------

def xlsx_sheet_names(path: Path) -> list[str]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return list(workbook.sheetnames)
    finally:
        workbook.close()


def read_xlsx_rows(
    path: Path, *, sheet_name: str | None = None, skip_rows: int = 0
) -> tuple[list[str], Iterator[tuple[Any, ...]]]:
    """Stream an XLSX sheet. Trailing all-empty columns are trimmed from the
    header, because openpyxl reports a padded dimension (the stock file
    declares 26 columns but carries 10)."""
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook[sheet_name] if sheet_name else workbook.active
    iterator = worksheet.iter_rows(values_only=True)

    for _ in range(skip_rows):
        next(iterator, None)
    raw_header = next(iterator, None)
    if raw_header is None:
        workbook.close()
        raise SourceReadError(f"{path.name} sheet has no header row.")

    header = [("" if cell is None else str(cell).strip()) for cell in raw_header]
    while header and header[-1] == "":
        header.pop()
    width = len(header)

    def rows() -> Iterator[tuple[Any, ...]]:
        try:
            for row in iterator:
                yield row[:width]
        finally:
            workbook.close()

    return header, rows()


# --------------------------------------------------------------------------
# XLSB (pyxlsb, streaming)
# --------------------------------------------------------------------------

def xlsb_sheet_names(path: Path) -> list[str]:
    from pyxlsb import open_workbook

    with open_workbook(str(path)) as workbook:
        return list(workbook.sheets)


def read_xlsb_rows(
    path: Path, *, sheet_name: str, skip_rows: int = 0
) -> tuple[list[str], Iterator[tuple[Any, ...]]]:
    """Stream one XLSB sheet.

    pyxlsb needs its workbook and sheet handles held open for the life of the
    iterator, so both are closed in the generator's `finally` rather than by a
    context manager the caller cannot see.
    """
    from pyxlsb import open_workbook

    workbook = open_workbook(str(path))
    worksheet = workbook.get_sheet(sheet_name)
    iterator = worksheet.rows()

    for _ in range(skip_rows):
        next(iterator, None)
    raw_header = next(iterator, None)
    if raw_header is None:
        worksheet.close()
        workbook.close()
        raise SourceReadError(f"{path.name}:{sheet_name} has no header row.")

    header = [("" if cell.v is None else str(cell.v).strip()) for cell in raw_header]
    while header and header[-1] == "":
        header.pop()
    width = len(header)

    def rows() -> Iterator[tuple[Any, ...]]:
        try:
            for row in iterator:
                values = tuple(cell.v for cell in row)
                if len(values) < width:
                    values = values + (None,) * (width - len(values))
                yield values[:width]
        finally:
            worksheet.close()
            workbook.close()

    return header, rows()


# --------------------------------------------------------------------------
# Value normalisation (rules C6, C7)
# --------------------------------------------------------------------------

def normalize_key(value: Any) -> str:
    """TRIM then UPPER. The single normalisation used for every join key, so
    `Jaipur`, `JAIPUR` and `JODhPUR`-style variants collapse consistently."""
    if value is None:
        return ""
    return str(value).strip().upper()


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def to_int(value: Any) -> int | None:
    result = to_float(value)
    return None if result is None else int(result)
