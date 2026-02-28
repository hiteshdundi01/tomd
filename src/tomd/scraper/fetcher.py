"""Playwright-based page fetcher with JavaScript rendering support."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from tomd.scraper.models import FetchedPage

logger = logging.getLogger(__name__)

# Default timeout for page loads (ms)
_TIMEOUT_MS = 30_000

# User-Agent to avoid bot detection
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _validate_url(url: str) -> str:
    """Normalise and validate a URL, raising ValueError on bad input."""
    url = url.strip()
    if not url:
        raise ValueError("URL cannot be empty")

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")

    return url


def fetch_page(url: str, timeout_ms: int = _TIMEOUT_MS) -> FetchedPage:
    """Fetch a web page using Playwright (headless Chromium).

    Renders JavaScript so that dynamically loaded content (Medium,
    some WordPress themes, etc.) is fully available.

    Parameters
    ----------
    url : str
        The article URL to fetch.
    timeout_ms : int
        Maximum time to wait for the page to load.

    Returns
    -------
    FetchedPage
        The rendered HTML, final URL, and HTTP status.
    """
    url = _validate_url(url)
    logger.info("Fetching %s", url)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(user_agent=_USER_AGENT)
            page = context.new_page()

            response = page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            status_code = response.status if response else 0

            # Wait a bit more for late-loading content
            page.wait_for_timeout(1000)

            html = page.content()
            final_url = page.url

            browser.close()

        logger.info("Fetched %s (status %d, %d chars)", final_url, status_code, len(html))
        return FetchedPage(html=html, url=final_url, status_code=status_code)

    except Exception as exc:
        logger.error("Failed to fetch %s: %s", url, exc)
        return FetchedPage(url=url, error=str(exc))
