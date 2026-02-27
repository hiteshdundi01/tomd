"""Master converter orchestrator — coordinates all extraction modules."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConversionProgress:
    """Tracks conversion progress for the Web UI."""
    total_pages: int = 0
    current_page: int = 0
    step: str = "Initializing"
    percent: int = 0
    done: bool = False
    error: str = ""


@dataclass
class ConversionResult:
    """Result of a PDF→Markdown conversion."""
    markdown: str = ""
    page_count: int = 0
    images_found: int = 0
    tables_found: int = 0
    used_ocr: bool = False
    elapsed_seconds: float = 0.0
    error: str = ""


def convert_pdf_to_markdown(
    pdf_path: str,
    smart_mode: bool = False,
    progress_callback: Optional[Callable[[ConversionProgress], None]] = None,
) -> ConversionResult:
    """Convert a PDF file to Markdown.

    Parameters
    ----------
    pdf_path : str
        Path to the input PDF file.
    smart_mode : bool
        If True, run the output through Gemini for intelligent cleanup.
    progress_callback : callable, optional
        Called with ``ConversionProgress`` updates during conversion.

    Returns
    -------
    ConversionResult
        The conversion result with markdown text and metadata.
    """
    start_time = time.time()
    progress = ConversionProgress()
    result = ConversionResult()

    def _update(step: str, percent: int, page: int = 0) -> None:
        progress.step = step
        progress.percent = percent
        if page:
            progress.current_page = page
        if progress_callback:
            progress_callback(progress)

    try:
        # ── Step 1: Detect PDF type ─────────────────────────────────────
        _update("Analyzing PDF structure", 5)

        from pdfmd.text_extractor import is_digital_pdf, extract_text, pages_to_markdown
        use_ocr = not is_digital_pdf(pdf_path)
        result.used_ocr = use_ocr

        if use_ocr:
            logger.info("PDF appears to be scanned — using OCR pipeline")
        else:
            logger.info("PDF has selectable text — using digital pipeline")

        # ── Step 2: Get page count ──────────────────────────────────────
        import fitz
        doc = fitz.open(pdf_path)
        result.page_count = len(doc)
        progress.total_pages = result.page_count
        doc.close()

        _update("Extracting text content", 10)

        # ── Step 3: Extract text ────────────────────────────────────────
        if use_ocr:
            from pdfmd.ocr_extractor import extract_text_ocr_with_structure
            raw_text = extract_text_ocr_with_structure(pdf_path)
            _update("OCR extraction complete", 40)
        else:
            pages = extract_text(pdf_path)
            raw_text = pages_to_markdown(pages)
            _update("Text extraction complete", 30)

        # ── Step 4: Extract tables ──────────────────────────────────────
        _update("Extracting tables", 45)
        from pdfmd.table_extractor import extract_tables, table_to_markdown

        tables = extract_tables(pdf_path)
        result.tables_found = len(tables)

        if tables:
            logger.info("Found %d tables", len(tables))
            table_md_parts: list[str] = []
            for table in tables:
                table_md_parts.append(table_to_markdown(table))

            # Insert tables into the document
            # We append them in page order after the corresponding page text
            tables_section = "\n\n".join(table_md_parts)
            raw_text = _merge_tables(raw_text, tables, table_md_parts)

        _update("Tables processed", 55)

        # ── Step 5: Extract and describe images ─────────────────────────
        _update("Extracting images", 60)
        from pdfmd.image_handler import (
            extract_images,
            describe_images_with_gemini,
            images_to_markdown,
        )

        images = extract_images(pdf_path)
        result.images_found = len(images)

        if images:
            logger.info("Found %d images — sending to Gemini for description", len(images))
            _update(f"Describing {len(images)} images with AI", 65)

            try:
                images = describe_images_with_gemini(images, surrounding_text=raw_text[:1000])
                image_md = images_to_markdown(images)
                raw_text = _merge_images(raw_text, image_md, result.page_count)
            except Exception as exc:
                logger.warning("Image description failed: %s", exc)
                # Still include placeholder descriptions
                for img in images:
                    if not img.description:
                        img.description = f"*[Image: {img.width}×{img.height}px]*"
                image_md = images_to_markdown(images)
                raw_text = _merge_images(raw_text, image_md, result.page_count)

        _update("Images processed", 75)

        # ── Step 6: Detect math and code ────────────────────────────────
        _update("Detecting math and code blocks", 80)
        from pdfmd.math_code_detector import detect_math, detect_code_blocks

        raw_text = detect_math(raw_text)
        raw_text = detect_code_blocks(raw_text)

        _update("Content analysis complete", 85)

        # ── Step 7: Smart mode cleanup ──────────────────────────────────
        if smart_mode:
            _update("Running AI-powered cleanup (Smart Mode)", 88)
            try:
                from pdfmd.gemini_client import cleanup_markdown
                raw_text = cleanup_markdown(raw_text)
                _update("Smart Mode cleanup complete", 95)
            except Exception as exc:
                logger.warning("Smart Mode cleanup failed: %s — returning raw output", exc)

        # ── Step 8: Final cleanup ───────────────────────────────────────
        _update("Finalizing", 98)
        result.markdown = _final_cleanup(raw_text)
        result.elapsed_seconds = round(time.time() - start_time, 2)

        _update("Done", 100)
        progress.done = True
        if progress_callback:
            progress_callback(progress)

    except Exception as exc:
        logger.exception("Conversion failed")
        result.error = str(exc)
        progress.error = str(exc)
        progress.done = True
        if progress_callback:
            progress_callback(progress)

    return result


# ---------------------------------------------------------------------------
# Merge helpers
# ---------------------------------------------------------------------------

def _merge_tables(
    text: str,
    tables: list,
    table_md_parts: list[str],
) -> str:
    """Append table markdown at the end (simple strategy).

    A more sophisticated approach would insert tables at their exact
    page positions, but that requires positional matching.
    """
    if not table_md_parts:
        return text

    # Group tables by page
    from collections import defaultdict
    by_page: dict[int, list[str]] = defaultdict(list)
    for table, md in zip(tables, table_md_parts):
        by_page[table.page_num].append(md)

    # Try to insert after each page's content
    # We use page separator (---) as a rough anchor
    parts = text.split("\n\n---\n\n")
    if len(parts) > 1:
        result_parts: list[str] = []
        for i, part in enumerate(parts):
            page_num = i + 1
            result_parts.append(part)
            if page_num in by_page:
                for tmd in by_page[page_num]:
                    result_parts.append(f"\n\n{tmd}\n")
        return "\n\n---\n\n".join(result_parts)

    # Fallback: append all tables at the end
    return text + "\n\n" + "\n\n".join(table_md_parts)


def _merge_images(
    text: str,
    image_md: dict[int, list[str]],
    total_pages: int,
) -> str:
    """Insert image descriptions into the text at appropriate positions."""
    if not image_md:
        return text

    # Try page-separator-based insertion
    parts = text.split("\n\n---\n\n")
    if len(parts) > 1:
        result_parts: list[str] = []
        for i, part in enumerate(parts):
            page_num = i + 1
            result_parts.append(part)
            if page_num in image_md:
                for imd in image_md[page_num]:
                    result_parts.append(f"\n\n{imd}\n")
        return "\n\n---\n\n".join(result_parts)

    # Fallback: append all at end
    all_img_md = []
    for page_num in sorted(image_md.keys()):
        all_img_md.extend(image_md[page_num])
    return text + "\n\n" + "\n\n".join(all_img_md)


def _final_cleanup(text: str) -> str:
    """Final pass to clean up the markdown output."""
    import re

    # Remove excessive blank lines (max 2 consecutive)
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    # Remove trailing whitespace on each line
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Ensure file ends with newline
    if not text.endswith("\n"):
        text += "\n"

    return text
