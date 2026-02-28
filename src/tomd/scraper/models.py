"""Data models for the web scraper module."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScrapeProgress:
    """Tracks scrape progress for the Web UI."""

    step: str = "Initializing"
    percent: int = 0
    done: bool = False
    error: str = ""


@dataclass
class FetchedPage:
    """Result of fetching a web page."""

    html: str = ""
    url: str = ""  # final URL after redirects
    status_code: int = 0
    error: str = ""


@dataclass
class ArticleData:
    """Extracted article content and metadata."""

    title: str = ""
    author: str = ""
    date: str = ""
    content_html: str = ""
    source_url: str = ""


@dataclass
class ScrapeResult:
    """Result of a web article → Markdown scrape."""

    markdown: str = ""
    title: str = ""
    author: str = ""
    date: str = ""
    source_url: str = ""
    images_downloaded: int = 0
    output_dir: str = ""  # temp directory containing downloaded images
    elapsed_seconds: float = 0.0
    error: str = ""
