"""Substack-specific article parser for higher-fidelity extraction."""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from tomd.scraper.models import ArticleData

logger = logging.getLogger(__name__)


def is_substack(url: str) -> bool:
    """Check whether a URL belongs to a Substack publication.

    Matches patterns like:
    - ``*.substack.com``
    - Custom domains that use Substack (detected via HTML, not URL alone)
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return "substack.com" in host


def is_substack_html(html: str) -> bool:
    """Detect Substack from HTML content (for custom domains)."""
    # Substack always includes its JS bundles
    return "substackcdn.com" in html or "substack-post-media" in html


def extract_substack(html: str, url: str) -> ArticleData:
    """Extract article content from a Substack page.

    Targets Substack's specific DOM structure for higher fidelity
    than generic readability extraction.

    Parameters
    ----------
    html : str
        Full rendered HTML of the Substack page.
    url : str
        The article URL.

    Returns
    -------
    ArticleData
        Extracted title, author, date, subtitle, and content HTML.
    """
    soup = BeautifulSoup(html, "lxml")

    # --- Title ---
    title = ""
    title_el = soup.find("h1", class_="post-title") or soup.find("h1")
    if title_el:
        title = title_el.get_text(strip=True)

    # Fallback to <meta property="og:title">
    if not title:
        meta = soup.find("meta", attrs={"property": "og:title"})
        if meta and meta.get("content"):
            title = meta["content"].strip()

    # --- Subtitle ---
    subtitle = ""
    subtitle_el = soup.find("h3", class_="subtitle")
    if subtitle_el:
        subtitle = subtitle_el.get_text(strip=True)

    # --- Author ---
    author = ""
    # Try byline link first
    author_el = soup.find("a", class_=re.compile(r"byline.*author", re.I))
    if author_el:
        author = author_el.get_text(strip=True)
    else:
        # Fallback: meta author
        meta = soup.find("meta", attrs={"name": "author"})
        if meta and meta.get("content"):
            author = meta["content"].strip()

    # --- Date ---
    date = ""
    time_el = soup.find("time", attrs={"datetime": True})
    if time_el:
        date = time_el["datetime"].strip()
    else:
        meta = soup.find("meta", attrs={"property": "article:published_time"})
        if meta and meta.get("content"):
            date = meta["content"].strip()

    # --- Content ---
    # Substack article body is in div.body.markup or div.available-content
    content_el = (
        soup.find("div", class_="body markup")
        or soup.find("div", class_="available-content")
        or soup.find("div", class_="post-content")
    )

    if content_el:
        # Remove paywall prompts, subscribe buttons, etc.
        for unwanted in content_el.find_all(
            class_=re.compile(r"(paywall|subscribe|subscription-widget|footer)", re.I)
        ):
            unwanted.decompose()

        # Remove Substack-specific UI elements
        for unwanted in content_el.find_all("div", class_="captioned-button-wrap"):
            unwanted.decompose()

        content_html = str(content_el)
    else:
        # Fallback: grab the whole article element
        article = soup.find("article")
        content_html = str(article) if article else ""

    # Prepend subtitle to content if present
    if subtitle:
        content_html = f"<p><em>{subtitle}</em></p>\n{content_html}"

    return ArticleData(
        title=title,
        author=author,
        date=date,
        content_html=content_html,
        source_url=url,
    )
