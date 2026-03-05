"""tomd — Convert anything to Markdown (PDFs, Word docs, web articles, and more)."""

from tomd.converter import convert_pdf_to_markdown
from tomd.docx_converter import convert_docx_to_markdown
from tomd.scraper import scrape_to_markdown

__all__ = ["convert_pdf_to_markdown", "convert_docx_to_markdown", "scrape_to_markdown"]

