"""Image extraction from PDFs with Gemini-powered descriptions."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class ExtractedImage:
    """An image extracted from a PDF."""
    page_num: int
    image_index: int
    image_bytes: bytes
    mime_type: str
    width: int
    height: int
    bbox: tuple[float, float, float, float]
    description: str = ""


def extract_images(pdf_path: str) -> list[ExtractedImage]:
    """Extract all images from a PDF.

    Parameters
    ----------
    pdf_path : str
        Path to the PDF file.

    Returns
    -------
    list[ExtractedImage]
        All images found in the PDF with raw bytes and metadata.
    """
    doc = fitz.open(pdf_path)
    images: list[ExtractedImage] = []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        image_list = page.get_images(full=True)

        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]

            try:
                base_image = doc.extract_image(xref)
                if not base_image:
                    continue

                image_bytes = base_image["image"]
                ext = base_image.get("ext", "png")
                width = base_image.get("width", 0)
                height = base_image.get("height", 0)

                # Skip tiny images (likely icons/bullets, < 30x30)
                if width < 30 or height < 30:
                    continue

                # Map extension to MIME type
                mime_map = {
                    "png": "image/png",
                    "jpeg": "image/jpeg",
                    "jpg": "image/jpeg",
                    "webp": "image/webp",
                    "bmp": "image/bmp",
                    "tiff": "image/tiff",
                    "gif": "image/gif",
                }
                mime_type = mime_map.get(ext.lower(), f"image/{ext}")

                # Try to get image position on page
                bbox = (0.0, 0.0, float(width), float(height))
                for img_rect in page.get_image_rects(xref):
                    bbox = (
                        img_rect.x0,
                        img_rect.y0,
                        img_rect.x1,
                        img_rect.y1,
                    )
                    break

                # Convert to PNG if format might not be supported by Gemini
                if ext.lower() not in ("png", "jpeg", "jpg", "webp"):
                    try:
                        pil_img = Image.open(io.BytesIO(image_bytes))
                        buf = io.BytesIO()
                        pil_img.save(buf, format="PNG")
                        image_bytes = buf.getvalue()
                        mime_type = "image/png"
                    except Exception:
                        pass  # Keep original format

                images.append(ExtractedImage(
                    page_num=page_idx + 1,
                    image_index=img_idx,
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    width=width,
                    height=height,
                    bbox=bbox,
                ))

            except Exception as exc:
                logger.warning(
                    "Failed to extract image %d from page %d: %s",
                    img_idx, page_idx + 1, exc,
                )

    doc.close()
    return images


def describe_images_with_gemini(
    images: list[ExtractedImage],
    surrounding_text: str = "",
    use_batch: bool = False,
) -> list[ExtractedImage]:
    """Add Gemini-generated descriptions to extracted images.

    Parameters
    ----------
    images : list[ExtractedImage]
        Images to describe.
    surrounding_text : str
        Context from surrounding document text.
    use_batch : bool
        If True and there are ≥2 images, use the Batch API (50% cost).

    Returns
    -------
    list[ExtractedImage]
        Same images with ``description`` field populated.
    """
    if not images:
        return images

    context_snippet = surrounding_text[:500] if surrounding_text else ""

    # ── Batch path ──────────────────────────────────────────────────
    if use_batch and len(images) >= 2:
        try:
            from tomd.gemini_client import batch_describe_images

            items = [
                (img.image_bytes, img.mime_type, context_snippet)
                for img in images
            ]
            logger.info(
                "Batch-describing %d images via Batch API", len(items),
            )
            descriptions = batch_describe_images(items)

            for img, desc in zip(images, descriptions):
                img.description = desc

            return images
        except Exception as exc:
            logger.warning(
                "Batch image description failed, falling back to sequential: %s",
                exc,
            )
            # Fall through to the sequential path below

    # ── Sequential path (original) ──────────────────────────────────
    from tomd.gemini_client import describe_image

    for img in images:
        try:
            logger.info(
                "Describing image %d on page %d (%dx%d)",
                img.image_index, img.page_num, img.width, img.height,
            )
            img.description = describe_image(
                img.image_bytes,
                mime_type=img.mime_type,
                extra_context=context_snippet,
            )
        except Exception as exc:
            logger.warning(
                "Gemini image description failed for image %d on page %d: %s",
                img.image_index, img.page_num, exc,
            )
            img.description = (
                f"*[Image: {img.width}×{img.height}px on page {img.page_num}]*"
            )

    return images


def images_to_markdown(images: list[ExtractedImage]) -> dict[int, list[str]]:
    """Convert described images to markdown blocks grouped by page.

    Returns
    -------
    dict[int, list[str]]
        Mapping of page_num → list of markdown image description blocks.
    """
    result: dict[int, list[str]] = {}

    for img in images:
        block = (
            f"---\n\n"
            f"**📷 Image** (Page {img.page_num}, {img.width}×{img.height}px)\n\n"
            f"{img.description}\n\n"
            f"---"
        )
        result.setdefault(img.page_num, []).append(block)

    return result
