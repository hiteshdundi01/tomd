"""Download images referenced in Markdown and rewrite URLs to local paths."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

# Regex to find Markdown image references: ![alt](url)
_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

# Max image size to download (10 MB)
_MAX_IMAGE_BYTES = 10 * 1024 * 1024

# Common image extensions
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif"}


def download_images(
    markdown: str,
    base_url: str,
    output_dir: str,
) -> tuple[str, int]:
    """Download all images in Markdown and rewrite URLs to local paths.

    Parameters
    ----------
    markdown : str
        Markdown text containing image references.
    base_url : str
        Base URL for resolving relative image URLs.
    output_dir : str
        Directory to save downloaded images into (an ``images/``
        subfolder will be created).

    Returns
    -------
    tuple[str, int]
        Updated markdown with local image paths, and count of
        images downloaded.
    """
    images_dir = Path(output_dir) / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    url_to_local: dict[str, str] = {}

    # Collect all unique image URLs
    matches = _IMG_RE.findall(markdown)
    unique_urls = list(dict.fromkeys(url for _, url in matches))

    if not unique_urls:
        return markdown, 0

    logger.info("Found %d unique images to download", len(unique_urls))

    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        for img_url in unique_urls:
            # Resolve relative URLs
            absolute_url = img_url
            if not img_url.startswith(("http://", "https://")):
                absolute_url = urljoin(base_url, img_url)

            # Skip data URIs
            if absolute_url.startswith("data:"):
                continue

            try:
                local_path = _download_single(client, absolute_url, images_dir)
                if local_path:
                    # Use relative path from the output directory
                    rel_path = f"images/{local_path.name}"
                    url_to_local[img_url] = rel_path
                    downloaded += 1
            except Exception as exc:
                logger.warning("Failed to download %s: %s", absolute_url, exc)

    # Rewrite URLs in markdown
    if url_to_local:
        for original_url, local_path in url_to_local.items():
            # Escape special regex characters in URLs
            escaped = re.escape(original_url)
            markdown = re.sub(
                rf"!\[([^\]]*)\]\({escaped}\)",
                rf"![\1]({local_path})",
                markdown,
            )

    logger.info("Downloaded %d images", downloaded)
    return markdown, downloaded


def _download_single(
    client: httpx.Client,
    url: str,
    images_dir: Path,
) -> Path | None:
    """Download a single image and save it to the images directory.

    Uses a content-hash filename to avoid duplicates.
    """
    response = client.get(url)
    response.raise_for_status()

    content = response.content
    if len(content) > _MAX_IMAGE_BYTES:
        logger.warning("Image too large (%d bytes), skipping: %s", len(content), url)
        return None

    if not content:
        return None

    # Determine file extension
    ext = _guess_extension(url, response.headers.get("content-type", ""))
    if not ext:
        ext = ".jpg"  # safe default

    # Use content hash for deduplication
    content_hash = hashlib.sha256(content).hexdigest()[:12]
    filename = f"{content_hash}{ext}"
    filepath = images_dir / filename

    if not filepath.exists():
        filepath.write_bytes(content)
        logger.debug("Saved image: %s", filepath)

    return filepath


def _guess_extension(url: str, content_type: str) -> str:
    """Guess the file extension from URL or Content-Type header."""
    # Try URL path first
    parsed = urlparse(url)
    path = parsed.path.lower()
    for ext in _IMAGE_EXTENSIONS:
        if path.endswith(ext):
            return ext

    # Try Content-Type
    ct = content_type.lower()
    if "png" in ct:
        return ".png"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    if "svg" in ct:
        return ".svg"
    if "avif" in ct:
        return ".avif"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"

    return ""
