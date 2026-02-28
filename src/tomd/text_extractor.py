"""Extract structured text from digital (non-scanned) PDFs using PyMuPDF."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TextBlock:
    """A block of text with its metadata."""
    text: str
    bbox: tuple[float, float, float, float]  # (x0, y0, x1, y1)
    page_num: int
    font_size: float = 0.0
    font_name: str = ""
    is_bold: bool = False
    block_type: str = "paragraph"  # paragraph, heading, footnote, code


@dataclass
class Link:
    """A hyperlink extracted from the PDF."""
    text: str
    url: str
    page_num: int


@dataclass
class PageContent:
    """All extracted content for a single page."""
    page_num: int
    text_blocks: list[TextBlock] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _median_font_size(blocks: list[TextBlock]) -> float:
    """Get the median font size across all blocks (= body text size)."""
    sizes = [b.font_size for b in blocks if b.font_size > 0]
    if not sizes:
        return 12.0
    sizes.sort()
    mid = len(sizes) // 2
    return sizes[mid]


def _detect_columns(blocks: list[TextBlock], page_width: float) -> list[list[TextBlock]]:
    """Detect multi-column layout and return blocks grouped by column, ordered
    left-to-right then top-to-bottom."""
    if not blocks:
        return []

    # Cluster blocks by x-midpoint
    midpoints = [(b.bbox[0] + b.bbox[2]) / 2 for b in blocks]
    page_mid = page_width / 2

    # Simple two-column detection: if blocks cluster on both sides of the page
    left = [b for b, m in zip(blocks, midpoints) if m < page_mid * 0.85]
    right = [b for b, m in zip(blocks, midpoints) if m >= page_mid * 0.85]

    # Only treat as multi-column if both sides have meaningful content
    if len(left) >= 3 and len(right) >= 3:
        left_max_x = max(b.bbox[2] for b in left)
        right_min_x = min(b.bbox[0] for b in right)
        # There should be a clear gap between columns
        if right_min_x - left_max_x > page_width * 0.05:
            left.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
            right.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
            return [left, right]

    # Single column — sort top-to-bottom
    blocks_sorted = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    return [blocks_sorted]


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def extract_text(pdf_path: str) -> list[PageContent]:
    """Extract structured text from a digital PDF.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file.

    Returns
    -------
    list[PageContent]
        One ``PageContent`` per page with text blocks, links, and metadata.
    """
    doc = fitz.open(pdf_path)
    pages: list[PageContent] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_content = PageContent(
            page_num=page_idx + 1,
            width=page.rect.width,
            height=page.rect.height,
        )

        # --- Text blocks via dict extraction --------------------------------
        blocks_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

        for block in blocks_dict.get("blocks", []):
            if block.get("type") != 0:  # type 0 = text, 1 = image
                continue

            block_text_parts: list[str] = []
            block_fonts: list[float] = []
            block_font_names: list[str] = []
            block_bold = False

            for line in block.get("lines", []):
                line_text = ""
                for span in line.get("spans", []):
                    line_text += span.get("text", "")
                    block_fonts.append(span.get("size", 0))
                    block_font_names.append(span.get("font", ""))
                    flags = span.get("flags", 0)
                    if flags & 2 ** 4:  # bold flag
                        block_bold = True
                block_text_parts.append(line_text)

            full_text = "\n".join(block_text_parts).strip()
            if not full_text:
                continue

            avg_font = sum(block_fonts) / len(block_fonts) if block_fonts else 12.0
            primary_font = block_font_names[0] if block_font_names else ""

            bbox = (
                block["bbox"][0],
                block["bbox"][1],
                block["bbox"][2],
                block["bbox"][3],
            )

            tb = TextBlock(
                text=full_text,
                bbox=bbox,
                page_num=page_idx + 1,
                font_size=round(avg_font, 1),
                font_name=primary_font,
                is_bold=block_bold,
            )
            page_content.text_blocks.append(tb)

        # --- Links -----------------------------------------------------------
        for link in page.get_links():
            uri = link.get("uri", "")
            if uri:
                # Try to find the text at the link's rectangle
                rect = fitz.Rect(link.get("from", (0, 0, 0, 0)))
                link_text = page.get_text("text", clip=rect).strip()
                page_content.links.append(Link(
                    text=link_text or uri,
                    url=uri,
                    page_num=page_idx + 1,
                ))

        pages.append(page_content)

    doc.close()

    # --- Post-processing: classify blocks -----------------------------------
    all_blocks = [b for p in pages for b in p.text_blocks]
    body_size = _median_font_size(all_blocks)

    for page_content in pages:
        for block in page_content.text_blocks:
            # Heading detection: significantly larger than body, or bold + larger
            if block.font_size > body_size * 1.3:
                block.block_type = "heading"
            elif block.font_size > body_size * 1.1 and block.is_bold:
                block.block_type = "heading"
            # Footnote detection: small text near page bottom
            elif (
                block.font_size < body_size * 0.85
                and block.bbox[1] > page_content.height * 0.85
            ):
                block.block_type = "footnote"
            # Code detection: monospace font
            elif any(
                mono in block.font_name.lower()
                for mono in ("mono", "courier", "consolas", "menlo", "firacode")
            ):
                block.block_type = "code"

    return pages


def is_digital_pdf(pdf_path: str) -> bool:
    """Check if a PDF contains selectable text (i.e., is not purely scanned).

    Returns True if the PDF has substantial text content on at least one page.
    """
    doc = fitz.open(pdf_path)
    text_pages = 0
    total_pages = len(doc)

    for page_idx in range(min(total_pages, 5)):  # Check first 5 pages
        page = doc[page_idx]
        text = page.get_text("text").strip()
        if len(text) > 50:  # More than just artifacts
            text_pages += 1

    doc.close()
    return text_pages > 0


def pages_to_markdown(
    pages: list[PageContent],
) -> str:
    """Convert extracted page content into a markdown string.

    Parameters
    ----------
    pages : list[PageContent]
        Extracted page contents.

    Returns
    -------
    str
        Markdown text.
    """
    md_parts: list[str] = []
    all_blocks = [b for p in pages for b in p.text_blocks]
    body_size = _median_font_size(all_blocks)
    all_links = {l.text: l.url for p in pages for l in p.links}

    for page in pages:
        columns = _detect_columns(page.text_blocks, page.width)

        for col_blocks in columns:
            for block in col_blocks:
                text = block.text.strip()
                if not text:
                    continue

                if block.block_type == "heading":
                    # Determine heading level from relative size
                    ratio = block.font_size / body_size if body_size else 1.0
                    if ratio > 1.6:
                        level = 1
                    elif ratio > 1.3:
                        level = 2
                    else:
                        level = 3
                    # Clean up: headings should be single-line
                    heading_text = text.replace("\n", " ")
                    md_parts.append(f"{'#' * level} {heading_text}")

                elif block.block_type == "code":
                    md_parts.append(f"```\n{text}\n```")

                elif block.block_type == "footnote":
                    # Footnotes as blockquotes
                    footnote_text = text.replace("\n", " ")
                    md_parts.append(f"> *{footnote_text}*")

                else:
                    # Regular paragraph — merge lines that were split by PDF layout
                    paragraph = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
                    md_parts.append(paragraph)

        md_parts.append("")  # Page separator

    # Inject hyperlinks
    result = "\n\n".join(md_parts)
    for link_text, url in all_links.items():
        if link_text and link_text in result and link_text != url:
            result = result.replace(link_text, f"[{link_text}]({url})", 1)

    return result.strip()
