"""OCR extraction pipeline for scanned/image-based PDFs.

Uses PyMuPDF for page-to-image rendering (no Poppler dependency)
and Tesseract for text recognition.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)


def _check_dependencies() -> None:
    """Verify that OCR dependencies are available.

    On Windows, auto-detects common Tesseract install locations
    (Chocolatey, Program Files) so users don't need to configure PATH.
    """
    import platform
    import pytesseract

    # Auto-detect Tesseract on Windows
    if platform.system() == "Windows":
        _windows_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"C:\ProgramData\chocolatey\bin\tesseract.exe",
        ]
        for candidate in _windows_paths:
            if Path(candidate).exists():
                pytesseract.pytesseract.tesseract_cmd = candidate
                logger.info("Auto-detected Tesseract at %s", candidate)
                break

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise RuntimeError(
            "Tesseract OCR is not installed or not on PATH.\n"
            "  Windows:  choco install tesseract\n"
            "  macOS:    brew install tesseract\n"
            "  Linux:    apt install tesseract-ocr"
        ) from exc


def _render_page_to_pil(page: fitz.Page, dpi: int = 300) -> Image.Image:
    """Render a PyMuPDF page to a PIL Image at the given DPI."""
    zoom = dpi / 72  # 72 is the default PDF DPI
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def extract_text_ocr(
    pdf_path: str,
    language: str = "eng",
    dpi: int = 300,
) -> str:
    """Convert a scanned PDF to text using OCR.

    Uses PyMuPDF to render pages (no Poppler needed) and Tesseract for OCR.

    Parameters
    ----------
    pdf_path : str
        Path to the scanned PDF file.
    language : str
        Tesseract language code (e.g. ``"eng"``, ``"fra"``).
    dpi : int
        Resolution for rendering PDF pages.

    Returns
    -------
    str
        Extracted text from all pages.
    """
    _check_dependencies()
    import pytesseract

    logger.info("Starting OCR extraction for %s", pdf_path)

    doc = fitz.open(pdf_path)
    all_text: list[str] = []

    for i in range(len(doc)):
        logger.info("OCR processing page %d/%d", i + 1, len(doc))
        img = _render_page_to_pil(doc[i], dpi=dpi)

        text = pytesseract.image_to_string(
            img,
            lang=language,
            config="--psm 3 --oem 3",
        )
        all_text.append(text.strip())

    doc.close()
    return "\n\n---\n\n".join(all_text)


def extract_text_ocr_with_structure(
    pdf_path: str,
    language: str = "eng",
    dpi: int = 300,
) -> str:
    """Extended OCR that tries to preserve document structure.

    Uses Tesseract's hOCR output to detect headings (larger fonts)
    and basic structure. Renders pages via PyMuPDF (no Poppler needed).

    Parameters
    ----------
    pdf_path : str
        Path to the scanned PDF.
    language : str
        Tesseract language code.
    dpi : int
        DPI for page rendering.

    Returns
    -------
    str
        Markdown-formatted text with basic heading detection.
    """
    _check_dependencies()
    import pytesseract
    import re

    doc = fitz.open(pdf_path)
    md_parts: list[str] = []

    for i in range(len(doc)):
        logger.info("Structured OCR page %d/%d", i + 1, len(doc))
        img = _render_page_to_pil(doc[i], dpi=dpi)

        # Get hOCR output for structure analysis
        hocr = pytesseract.image_to_pdf_or_hocr(
            img,
            lang=language,
            config="--psm 3 --oem 3",
            extension="hocr",
        )
        hocr_text = hocr.decode("utf-8", errors="replace")

        # Also get plain text as fallback
        plain_text = pytesseract.image_to_string(
            img,
            lang=language,
            config="--psm 3 --oem 3",
        )

        # Try to detect font sizes from hOCR to identify headings
        font_sizes: list[tuple[float, str]] = []
        for match in re.finditer(
            r'x_fsize\s+(\d+(?:\.\d+)?)[^>]*>([^<]+)<', hocr_text
        ):
            size = float(match.group(1))
            text = match.group(2).strip()
            if text:
                font_sizes.append((size, text))

        if font_sizes:
            # Find median font size = body text
            sizes = sorted(s for s, _ in font_sizes)
            median_size = sizes[len(sizes) // 2]

            lines = plain_text.split("\n")
            structured_lines: list[str] = []

            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    structured_lines.append("")
                    continue

                is_heading = False
                for size, text in font_sizes:
                    if text in line_stripped and size > median_size * 1.3:
                        is_heading = True
                        level = 1 if size > median_size * 1.6 else 2
                        structured_lines.append(f"{'#' * level} {line_stripped}")
                        break

                if not is_heading:
                    structured_lines.append(line_stripped)

            md_parts.append("\n".join(structured_lines))
        else:
            md_parts.append(plain_text.strip())

    doc.close()
    return "\n\n---\n\n".join(md_parts)
