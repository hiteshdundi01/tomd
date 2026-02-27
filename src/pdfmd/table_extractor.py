"""Table extraction from PDFs using pdfplumber with markdown/HTML rendering."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTable:
    """A table extracted from a PDF page."""
    page_num: int
    rows: list[list[str]]
    bbox: tuple[float, float, float, float]
    has_merged_cells: bool = False


def extract_tables(pdf_path: str) -> list[ExtractedTable]:
    """Extract all tables from a PDF.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file.

    Returns
    -------
    list[ExtractedTable]
        All tables found across all pages.
    """
    tables: list[ExtractedTable] = []

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                page_tables = page.find_tables()

                for table_obj in page_tables:
                    raw_data = table_obj.extract()
                    if not raw_data:
                        continue

                    # Clean up extracted data
                    cleaned_rows: list[list[str]] = []
                    has_merged = False

                    for row in raw_data:
                        cleaned_row: list[str] = []
                        for cell in row:
                            if cell is None:
                                cleaned_row.append("")
                                has_merged = True
                            else:
                                # Clean whitespace and newlines within cells
                                cleaned = str(cell).strip().replace("\n", " ")
                                cleaned_row.append(cleaned)
                        cleaned_rows.append(cleaned_row)

                    if cleaned_rows:
                        tables.append(ExtractedTable(
                            page_num=page_idx + 1,
                            rows=cleaned_rows,
                            bbox=table_obj.bbox,
                            has_merged_cells=has_merged,
                        ))

    except Exception as exc:
        logger.warning("Table extraction failed: %s", exc)

    return tables


def _is_simple_table(table: ExtractedTable) -> bool:
    """Check if a table can be represented as a standard markdown table.

    A simple table has:
    - Uniform number of columns across all rows
    - No merged cells
    - At least 2 rows (header + data)
    """
    if table.has_merged_cells:
        return False
    if len(table.rows) < 2:
        return False
    col_count = len(table.rows[0])
    return all(len(row) == col_count for row in table.rows)


def _escape_md_table_cell(text: str) -> str:
    """Escape pipe characters in markdown table cells."""
    return text.replace("|", "\\|")


def table_to_markdown(table: ExtractedTable) -> str:
    """Convert a table to its best markdown representation.

    Simple tables → standard markdown table.
    Complex tables → HTML ``<table>``.

    Parameters
    ----------
    table : ExtractedTable
        The extracted table data.

    Returns
    -------
    str
        Markdown or HTML table string.
    """
    if _is_simple_table(table):
        return _render_markdown_table(table)
    else:
        return _render_html_table(table)


def _render_markdown_table(table: ExtractedTable) -> str:
    """Render a simple table as a standard markdown table."""
    if not table.rows:
        return ""

    header = table.rows[0]
    data_rows = table.rows[1:]

    # Calculate column widths for alignment
    col_widths = [max(3, len(cell)) for cell in header]
    for row in data_rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(cell))

    lines: list[str] = []

    # Header row
    header_cells = [
        f" {_escape_md_table_cell(cell).ljust(col_widths[i])} "
        for i, cell in enumerate(header)
    ]
    lines.append("|" + "|".join(header_cells) + "|")

    # Separator row
    sep_cells = [f" {'-' * col_widths[i]} " for i in range(len(header))]
    lines.append("|" + "|".join(sep_cells) + "|")

    # Data rows
    for row in data_rows:
        row_cells = [
            f" {_escape_md_table_cell(cell).ljust(col_widths[i] if i < len(col_widths) else 3)} "
            for i, cell in enumerate(row)
        ]
        lines.append("|" + "|".join(row_cells) + "|")

    return "\n".join(lines)


def _render_html_table(table: ExtractedTable) -> str:
    """Render a complex table as an HTML table for full fidelity."""
    if not table.rows:
        return ""

    lines: list[str] = ["<table>"]

    for row_idx, row in enumerate(table.rows):
        lines.append("  <tr>")
        tag = "th" if row_idx == 0 else "td"
        for cell in row:
            escaped = (
                cell.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            lines.append(f"    <{tag}>{escaped}</{tag}>")
        lines.append("  </tr>")

    lines.append("</table>")
    return "\n".join(lines)


def get_table_regions(pdf_path: str) -> list[tuple[int, tuple[float, float, float, float]]]:
    """Get the bounding boxes of all tables for exclusion during text extraction.

    Returns a list of (page_num, bbox) tuples.
    """
    tables = extract_tables(pdf_path)
    return [(t.page_num, t.bbox) for t in tables]
