"""Generic article extractor using readability-lxml + BeautifulSoup."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag
from readability import Document

from tomd.scraper.models import ArticleData

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Article extraction (readability)
# ---------------------------------------------------------------------------


def extract_article(html: str, url: str) -> ArticleData:
    """Extract the main article content from raw HTML.

    Uses readability-lxml to strip boilerplate, then parses
    metadata from ``<meta>`` tags and common HTML patterns.

    Parameters
    ----------
    html : str
        Full rendered HTML of the page.
    url : str
        The page URL (used for resolving relative links).

    Returns
    -------
    ArticleData
        Extracted title, author, date, and content HTML.
    """
    doc = Document(html)

    title = doc.short_title() or ""
    content_html = doc.summary(html_partial=True) or ""

    # Parse metadata from the original HTML
    soup = BeautifulSoup(html, "lxml")
    author = _extract_author(soup)
    date = _extract_date(soup)

    # Resolve relative URLs in the content
    content_html = _resolve_urls(content_html, url)

    return ArticleData(
        title=title.strip(),
        author=author,
        date=date,
        content_html=content_html,
        source_url=url,
    )


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def _extract_author(soup: BeautifulSoup) -> str:
    """Try to extract the author from meta tags or common patterns."""
    # <meta name="author" content="...">
    meta = soup.find("meta", attrs={"name": "author"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    # <meta property="article:author" content="...">
    meta = soup.find("meta", attrs={"property": "article:author"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    # <meta property="og:article:author" content="...">
    meta = soup.find("meta", attrs={"property": "og:article:author"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    # <a rel="author">
    author_link = soup.find("a", attrs={"rel": "author"})
    if author_link:
        return author_link.get_text(strip=True)

    # Common class patterns
    for cls in ("author", "byline", "author-name", "post-author"):
        el = soup.find(class_=cls)
        if el:
            text = el.get_text(strip=True)
            # Clean up "By Author Name" patterns
            text = re.sub(r"^[Bb]y\s+", "", text)
            if text:
                return text

    return ""


def _extract_date(soup: BeautifulSoup) -> str:
    """Try to extract the publish date from meta tags or <time> elements."""
    # <meta property="article:published_time" content="...">
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    # <meta name="date" content="...">
    meta = soup.find("meta", attrs={"name": "date"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    # <meta property="og:updated_time" content="...">
    meta = soup.find("meta", attrs={"property": "og:updated_time"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    # <time datetime="...">
    time_el = soup.find("time", attrs={"datetime": True})
    if time_el:
        return time_el["datetime"].strip()

    return ""


def _resolve_urls(html: str, base_url: str) -> str:
    """Resolve relative URLs in the content HTML to absolute URLs."""
    soup = BeautifulSoup(html, "lxml")

    for tag in soup.find_all(["a", "img"]):
        attr = "href" if tag.name == "a" else "src"
        val = tag.get(attr, "")
        if val and not val.startswith(("http://", "https://", "data:", "#", "mailto:")):
            tag[attr] = urljoin(base_url, val)

    return str(soup)


# ---------------------------------------------------------------------------
# HTML → Markdown conversion
# ---------------------------------------------------------------------------


def html_to_markdown(html: str) -> str:
    """Convert cleaned article HTML to Markdown.

    Handles headings, paragraphs, lists, links, images, blockquotes,
    code blocks, bold, italic, and horizontal rules.

    Parameters
    ----------
    html : str
        Cleaned article HTML (from readability or a site-specific parser).

    Returns
    -------
    str
        Clean Markdown text.
    """
    soup = BeautifulSoup(html, "lxml")

    # Remove script/style tags
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()

    lines: list[str] = []
    _walk(soup, lines, indent=0)

    text = "\n".join(lines)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _walk(node, lines: list[str], indent: int = 0) -> None:
    """Recursively walk the DOM and emit Markdown lines."""
    if isinstance(node, NavigableString):
        text = str(node)
        # Collapse whitespace in inline text
        text = re.sub(r"\s+", " ", text)
        if text.strip():
            lines.append(text.strip())
        return

    if not isinstance(node, Tag):
        return

    tag = node.name

    # === Block elements ===

    # Headings
    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        text = node.get_text(strip=True)
        if text:
            lines.append("")
            lines.append(f"{'#' * level} {text}")
            lines.append("")
        return

    # Paragraphs
    if tag == "p":
        text = _inline_markdown(node)
        if text.strip():
            lines.append("")
            lines.append(text.strip())
            lines.append("")
        return

    # Blockquotes
    if tag == "blockquote":
        inner_lines: list[str] = []
        _walk_children(node, inner_lines, indent)
        for line in inner_lines:
            if line.strip():
                lines.append(f"> {line.strip()}")
            else:
                lines.append(">")
        lines.append("")
        return

    # Pre / code blocks
    if tag == "pre":
        code = node.find("code")
        if code:
            lang = ""
            classes = code.get("class", [])
            for cls in classes:
                if cls.startswith("language-"):
                    lang = cls[9:]
                    break
            lines.append("")
            lines.append(f"```{lang}")
            lines.append(code.get_text())
            lines.append("```")
            lines.append("")
        else:
            lines.append("")
            lines.append("```")
            lines.append(node.get_text())
            lines.append("```")
            lines.append("")
        return

    # Unordered lists
    if tag == "ul":
        lines.append("")
        for li in node.find_all("li", recursive=False):
            text = _inline_markdown(li)
            if text.strip():
                lines.append(f"{'  ' * indent}- {text.strip()}")
            # Handle nested lists
            for nested in li.find_all(["ul", "ol"], recursive=False):
                _walk(nested, lines, indent + 1)
        lines.append("")
        return

    # Ordered lists
    if tag == "ol":
        lines.append("")
        for i, li in enumerate(node.find_all("li", recursive=False), 1):
            text = _inline_markdown(li)
            if text.strip():
                lines.append(f"{'  ' * indent}{i}. {text.strip()}")
            for nested in li.find_all(["ul", "ol"], recursive=False):
                _walk(nested, lines, indent + 1)
        lines.append("")
        return

    # Images
    if tag == "img":
        src = node.get("src", "")
        alt = node.get("alt", "")
        if src:
            lines.append(f"![{alt}]({src})")
        return

    # Horizontal rules
    if tag == "hr":
        lines.append("")
        lines.append("---")
        lines.append("")
        return

    # Figure (image + caption)
    if tag == "figure":
        img = node.find("img")
        caption = node.find("figcaption")
        if img:
            src = img.get("src", "")
            alt = img.get("alt", "") or (caption.get_text(strip=True) if caption else "")
            lines.append(f"![{alt}]({src})")
            if caption:
                lines.append(f"*{caption.get_text(strip=True)}*")
            lines.append("")
        return

    # Default: recurse into children
    _walk_children(node, lines, indent)


def _walk_children(node: Tag, lines: list[str], indent: int) -> None:
    """Walk all children of a tag."""
    for child in node.children:
        _walk(child, lines, indent)


def _inline_markdown(node: Tag) -> str:
    """Convert inline HTML within a block element to Markdown."""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name in ("strong", "b"):
                text = child.get_text()
                parts.append(f"**{text}**")
            elif child.name in ("em", "i"):
                text = child.get_text()
                parts.append(f"*{text}*")
            elif child.name == "code":
                text = child.get_text()
                parts.append(f"`{text}`")
            elif child.name == "a":
                text = child.get_text()
                href = child.get("href", "")
                if href and text:
                    parts.append(f"[{text}]({href})")
                elif text:
                    parts.append(text)
            elif child.name == "img":
                src = child.get("src", "")
                alt = child.get("alt", "")
                if src:
                    parts.append(f"![{alt}]({src})")
            elif child.name == "br":
                parts.append("  \n")
            elif child.name in ("sup", "sub"):
                parts.append(child.get_text())
            else:
                parts.append(child.get_text())
    return "".join(parts)
