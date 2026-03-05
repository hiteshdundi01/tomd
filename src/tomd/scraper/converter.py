"""Scraper orchestrator — coordinates fetch, extract, and convert pipeline."""

from __future__ import annotations

import logging
import tempfile
import time
from typing import Callable, Optional

from tomd.scraper.models import ScrapeProgress, ScrapeResult

logger = logging.getLogger(__name__)


def scrape_to_markdown(
    url: str,
    smart_mode: bool = False,
    use_batch: bool = False,
    download_images_flag: bool = True,
    progress_callback: Optional[Callable[[ScrapeProgress], None]] = None,
) -> ScrapeResult:
    """Scrape a web article and convert it to Markdown.

    Pipeline
    --------
    1. Fetch the page (Playwright, JS rendering)
    2. Detect site type (Substack vs. generic)
    3. Extract article content and metadata
    4. Convert HTML → Markdown
    5. Add YAML frontmatter
    6. Download images locally  *(optional)*
    7. Gemini smart-mode cleanup  *(optional)*

    Parameters
    ----------
    url : str
        The article URL to scrape.
    smart_mode : bool
        If True, run the output through Gemini for intelligent cleanup.
    use_batch : bool
        If True, use the Gemini Batch API (50% cost, async processing).
    download_images_flag : bool
        If True, download images locally and rewrite URLs.
    progress_callback : callable, optional
        Called with ScrapeProgress as each step completes.

    Returns
    -------
    ScrapeResult
        The scrape result with markdown and metadata.
    """
    result = ScrapeResult(source_url=url)
    progress = ScrapeProgress()
    start = time.time()

    def _update(step: str, percent: int) -> None:
        progress.step = step
        progress.percent = percent
        if progress_callback:
            progress_callback(progress)

    try:
        # ── Step 1: Fetch page ──────────────────────────────────────
        _update("Fetching page...", 10)

        from tomd.scraper.fetcher import fetch_page

        fetched = fetch_page(url)
        if fetched.error:
            raise RuntimeError(f"Failed to fetch page: {fetched.error}")
        if not fetched.html:
            raise RuntimeError("No HTML content received from page")

        logger.info("Page fetched: %s (%d chars)", fetched.url, len(fetched.html))

        # ── Step 2: Detect site type ────────────────────────────────
        _update("Analyzing page...", 20)

        from tomd.scraper.substack import is_substack, is_substack_html

        use_substack = is_substack(fetched.url) or is_substack_html(fetched.html)

        if use_substack:
            logger.info("Detected Substack article")
        else:
            logger.info("Using generic readability extractor")

        # ── Step 3: Extract article ─────────────────────────────────
        _update("Extracting article content...", 35)

        if use_substack:
            from tomd.scraper.substack import extract_substack

            article = extract_substack(fetched.html, fetched.url)
        else:
            from tomd.scraper.extractor import extract_article

            article = extract_article(fetched.html, fetched.url)

        result.title = article.title
        result.author = article.author
        result.date = article.date

        if not article.content_html.strip():
            raise RuntimeError("No article content could be extracted from the page")

        logger.info("Extracted: '%s' by %s", article.title, article.author or "unknown")

        # ── Step 4: Convert HTML → Markdown ─────────────────────────
        _update("Converting to Markdown...", 50)

        from tomd.scraper.extractor import html_to_markdown

        markdown = html_to_markdown(article.content_html)

        if not markdown.strip():
            raise RuntimeError("HTML to Markdown conversion produced empty output")

        # ── Step 5: Add YAML frontmatter ────────────────────────────
        _update("Adding metadata...", 60)

        frontmatter = _build_frontmatter(
            title=article.title,
            author=article.author,
            date=article.date,
            source_url=article.source_url or fetched.url,
        )
        markdown = frontmatter + "\n\n" + markdown

        # ── Step 6: Download images ─────────────────────────────────
        if download_images_flag:
            _update("Downloading images...", 70)

            from tomd.scraper.image_downloader import download_images

            output_dir = tempfile.mkdtemp(prefix="tomd_scrape_")
            markdown, images_count = download_images(
                markdown, fetched.url, output_dir
            )
            result.images_downloaded = images_count
            result.output_dir = output_dir
            logger.info("Downloaded %d images to %s", images_count, output_dir)

        # ── Step 7: Smart Mode (Gemini cleanup) ─────────────────────
        if smart_mode:
            _update("Running AI cleanup (Smart Mode)...", 85)
            try:
                if use_batch:
                    from tomd.gemini_client import batch_cleanup_markdown
                    cleaned = batch_cleanup_markdown([markdown])
                    markdown = cleaned[0] if cleaned else markdown
                else:
                    from tomd.gemini_client import cleanup_markdown
                    markdown = cleanup_markdown(markdown)

                _update("Smart Mode cleanup complete", 95)
            except Exception as exc:
                logger.warning("Smart Mode failed (non-fatal): %s", exc)

        # ── Done ────────────────────────────────────────────────────
        result.markdown = markdown
        result.elapsed_seconds = round(time.time() - start, 2)

        progress.step = "Complete"
        progress.percent = 100
        progress.done = True
        if progress_callback:
            progress_callback(progress)

        logger.info(
            "Scrape complete: '%s' in %.1fs (%d images)",
            result.title,
            result.elapsed_seconds,
            result.images_downloaded,
        )

    except Exception as exc:
        logger.error("Scrape failed: %s", exc)
        result.error = str(exc)
        result.elapsed_seconds = round(time.time() - start, 2)

        progress.step = "Failed"
        progress.percent = 0
        progress.done = True
        progress.error = str(exc)
        if progress_callback:
            progress_callback(progress)

    return result


def _build_frontmatter(
    title: str, author: str, date: str, source_url: str
) -> str:
    """Build a YAML frontmatter block for the article."""
    lines = ["---"]

    if title:
        # Escape quotes in title
        safe_title = title.replace('"', '\\"')
        lines.append(f'title: "{safe_title}"')
    if author:
        safe_author = author.replace('"', '\\"')
        lines.append(f'author: "{safe_author}"')
    if date:
        lines.append(f"date: {date}")
    if source_url:
        lines.append(f"source: {source_url}")

    lines.append("---")
    return "\n".join(lines)
