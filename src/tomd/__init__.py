"""tomd — Convert anything to Markdown (PDFs, web articles, and more)."""

from tomd.converter import convert_pdf_to_markdown
from tomd.scraper import scrape_to_markdown

__all__ = ["convert_pdf_to_markdown", "scrape_to_markdown"]

