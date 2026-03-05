"""Word document converter — converts .docx, .doc, and .rtf files to Markdown.

Uses ``mammoth`` for .docx → HTML and ``markdownify`` for HTML → Markdown.
Legacy .doc/.rtf files are pre-converted to .docx via LibreOffice CLI.
"""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from tomd.converter import ConversionProgress, ConversionResult

logger = logging.getLogger(__name__)

# Supported extensions
DOCX_EXTENSIONS = frozenset({".docx"})
LEGACY_EXTENSIONS = frozenset({".doc", ".rtf"})
ALL_WORD_EXTENSIONS = DOCX_EXTENSIONS | LEGACY_EXTENSIONS


def convert_docx_to_markdown(
    file_path: str,
    smart_mode: bool = False,
    use_batch: bool = False,
    progress_callback: Optional[Callable[[ConversionProgress], None]] = None,
) -> ConversionResult:
    """Convert a Word document (.docx, .doc, .rtf) to Markdown.

    Parameters
    ----------
    file_path : str
        Path to the input Word document.
    smart_mode : bool
        If True, run the output through Gemini for intelligent cleanup.
    use_batch : bool
        If True, use the Gemini Batch API (50% cost, async processing).
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

    def _update(step: str, percent: int) -> None:
        progress.step = step
        progress.percent = percent
        if progress_callback:
            progress_callback(progress)

    try:
        ext = Path(file_path).suffix.lower()

        # ── Step 1: Pre-convert legacy formats ──────────────────────────
        if ext in LEGACY_EXTENSIONS:
            _update(f"Converting {ext} to .docx via LibreOffice", 5)
            file_path = _convert_legacy_to_docx(file_path)
            _update("Legacy format converted", 15)
        else:
            _update("Analyzing document", 5)

        # ── Step 2: Convert .docx → HTML via mammoth ────────────────────
        _update("Extracting document content", 20)

        import mammoth

        with open(file_path, "rb") as f:
            mammoth_result = mammoth.convert_to_html(f)

        html_content = mammoth_result.value
        messages = mammoth_result.messages

        if messages:
            for msg in messages:
                logger.debug("mammoth: %s", msg)

        if not html_content.strip():
            raise RuntimeError("No content could be extracted from the document")

        _update("Document content extracted", 40)

        # ── Step 3: Extract images from docx ────────────────────────────
        _update("Extracting images", 45)
        images_found = 0

        try:
            images_found = _count_docx_images(file_path)
        except Exception as exc:
            logger.debug("Image counting failed: %s", exc)

        result.images_found = images_found
        _update("Images processed", 55)

        # ── Step 4: Convert HTML → Markdown ─────────────────────────────
        _update("Converting to Markdown", 60)

        from markdownify import markdownify as md

        markdown = md(
            html_content,
            heading_style="ATX",
            bullets="-",
            strip=["img"],  # Images handled separately if needed
        )

        if not markdown.strip():
            raise RuntimeError("HTML to Markdown conversion produced empty output")

        _update("Markdown conversion complete", 75)

        # ── Step 5: Smart mode cleanup ──────────────────────────────────
        if smart_mode:
            _update("Running AI-powered cleanup (Smart Mode)", 80)
            try:
                if use_batch:
                    from tomd.gemini_client import batch_cleanup_markdown

                    max_chunk = 80_000
                    if len(markdown) <= max_chunk:
                        chunks = [markdown]
                    else:
                        chunks = []
                        current = ""
                        for paragraph in markdown.split("\n\n"):
                            if len(current) + len(paragraph) + 2 > max_chunk:
                                chunks.append(current)
                                current = paragraph
                            else:
                                current = (
                                    current + "\n\n" + paragraph
                                    if current
                                    else paragraph
                                )
                        if current:
                            chunks.append(current)

                    cleaned = batch_cleanup_markdown(chunks)
                    markdown = "\n\n".join(cleaned)
                else:
                    from tomd.gemini_client import cleanup_markdown

                    markdown = cleanup_markdown(markdown)

                _update("Smart Mode cleanup complete", 92)
            except Exception as exc:
                logger.warning(
                    "Smart Mode cleanup failed: %s — returning raw output", exc
                )

        # ── Step 6: Final cleanup ───────────────────────────────────────
        _update("Finalizing", 95)
        markdown = _final_cleanup(markdown)

        result.markdown = markdown
        result.page_count = 0  # Word docs don't expose page count easily
        result.elapsed_seconds = round(time.time() - start_time, 2)

        _update("Done", 100)
        progress.done = True
        if progress_callback:
            progress_callback(progress)

    except Exception as exc:
        logger.exception("Word document conversion failed")
        result.error = str(exc)
        progress.error = str(exc)
        progress.done = True
        if progress_callback:
            progress_callback(progress)

    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _convert_legacy_to_docx(file_path: str) -> str:
    """Convert a .doc or .rtf file to .docx using LibreOffice.

    Returns
    -------
    str
        Path to the converted .docx file.

    Raises
    ------
    RuntimeError
        If LibreOffice is not installed or conversion fails.
    """
    # Find LibreOffice executable
    soffice = shutil.which("soffice") or shutil.which("libreoffice")

    if not soffice:
        # Check common Windows install paths
        common_paths = [
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for p in common_paths:
            if os.path.exists(p):
                soffice = p
                break

    if not soffice:
        raise RuntimeError(
            "LibreOffice is required to convert .doc/.rtf files. "
            "Please install LibreOffice (https://www.libreoffice.org/download/) "
            "or convert your file to .docx format first."
        )

    # Convert to docx in a temp directory
    output_dir = tempfile.mkdtemp(prefix="tomd_docx_")

    try:
        cmd = [
            soffice,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            output_dir,
            file_path,
        ]
        logger.info("Running LibreOffice conversion: %s", " ".join(cmd))

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed (exit code {proc.returncode}): "
                f"{proc.stderr}"
            )

        # Find the output file
        stem = Path(file_path).stem
        docx_path = os.path.join(output_dir, f"{stem}.docx")

        if not os.path.exists(docx_path):
            # Try to find any .docx file in the output dir
            docx_files = list(Path(output_dir).glob("*.docx"))
            if docx_files:
                docx_path = str(docx_files[0])
            else:
                raise RuntimeError(
                    "LibreOffice conversion completed but no .docx file was produced"
                )

        logger.info("Converted to .docx: %s", docx_path)
        return docx_path

    except subprocess.TimeoutExpired:
        raise RuntimeError("LibreOffice conversion timed out after 120 seconds")


def _count_docx_images(file_path: str) -> int:
    """Count the number of images embedded in a .docx file."""
    import zipfile

    count = 0
    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            for name in zf.namelist():
                if name.startswith("word/media/"):
                    count += 1
    except Exception:
        pass
    return count


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
