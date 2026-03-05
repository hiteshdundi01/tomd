"""Centralized Gemini API client for image descriptions and smart cleanup.

Uses the new ``google-genai`` SDK (replaces deprecated ``google-generativeai``).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    """Lazy-initialise and return the Gemini client."""
    global _client
    if _client is not None:
        return _client

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key or api_key == "your-gemini-api-key-here":
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Get one at https://aistudio.google.com/apikey and add it to .env"
        )

    _client = genai.Client(api_key=api_key)
    return _client


# ---------------------------------------------------------------------------
# Image description
# ---------------------------------------------------------------------------

_IMAGE_PROMPT = (
    "You are an expert document analyst. Describe this image in detail for "
    "inclusion in a Markdown document. Be specific about:\n"
    "- What type of visual it is (chart, diagram, photo, screenshot, etc.)\n"
    "- All text, labels, and data visible in the image\n"
    "- The layout and structure of the visual\n"
    "- Key takeaways or information conveyed\n\n"
    "Return ONLY the description, no preamble."
)


def describe_image(
    image_bytes: bytes,
    mime_type: str = "image/png",
    extra_context: str = "",
) -> str:
    """Send an image to Gemini Vision and get a textual description.

    Parameters
    ----------
    image_bytes : bytes
        Raw image data (PNG, JPEG, etc.).
    mime_type : str
        MIME type of the image.
    extra_context : str
        Optional surrounding text to give the model more context.

    Returns
    -------
    str
        A markdown-ready description of the image.
    """
    client = _get_client()

    prompt = _IMAGE_PROMPT
    if extra_context:
        prompt += f"\n\nSurrounding document context:\n{extra_context}"

    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=[prompt, image_part],
    )
    return response.text.strip()


# ---------------------------------------------------------------------------
# Smart-mode cleanup
# ---------------------------------------------------------------------------

_CLEANUP_PROMPT = (
    "You are a Markdown formatting expert. You will receive raw Markdown text "
    "extracted from a PDF document. Your job is to:\n\n"
    "1. Fix any formatting issues (broken headings, inconsistent lists, etc.)\n"
    "2. Restructure heading hierarchy so it flows logically (H1 → H2 → H3)\n"
    "3. Clean up OCR artifacts (garbled text, misrecognized characters)\n"
    "4. Merge fragmented paragraphs that were split across pages\n"
    "5. Preserve ALL original content — do NOT remove or summarize anything\n"
    "6. Preserve all tables, code blocks, math expressions, and links\n"
    "7. Ensure consistent formatting throughout\n\n"
    "Return ONLY the cleaned Markdown, no commentary."
)


def cleanup_markdown(raw_markdown: str) -> str:
    """Send raw markdown through Gemini for intelligent cleanup.

    Parameters
    ----------
    raw_markdown : str
        The raw extracted markdown text.

    Returns
    -------
    str
        Cleaned and restructured markdown.
    """
    client = _get_client()

    # For very long documents, chunk them to stay within context limits
    max_chunk = 80_000  # characters — well within Gemini's context window
    if len(raw_markdown) <= max_chunk:
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[_CLEANUP_PROMPT, raw_markdown],
        )
        return response.text.strip()

    # Chunk by double-newline boundaries
    chunks: list[str] = []
    current = ""
    for paragraph in raw_markdown.split("\n\n"):
        if len(current) + len(paragraph) + 2 > max_chunk:
            chunks.append(current)
            current = paragraph
        else:
            current = current + "\n\n" + paragraph if current else paragraph
    if current:
        chunks.append(current)

    cleaned_parts: list[str] = []
    for i, chunk in enumerate(chunks):
        context = f"(Part {i + 1} of {len(chunks)})\n\n"
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=[_CLEANUP_PROMPT + context, chunk],
        )
        cleaned_parts.append(response.text.strip())

    return "\n\n".join(cleaned_parts)


# ---------------------------------------------------------------------------
# Batch API helpers
# ---------------------------------------------------------------------------

_BATCH_POLL_INTERVAL = 10  # seconds between status checks

_COMPLETED_STATES = frozenset({
    "JOB_STATE_SUCCEEDED",
    "JOB_STATE_FAILED",
    "JOB_STATE_CANCELLED",
    "JOB_STATE_EXPIRED",
})


def _poll_batch_job(
    job_name: str,
    poll_interval: int = _BATCH_POLL_INTERVAL,
) -> object:
    """Poll a batch job until it reaches a terminal state.

    Parameters
    ----------
    job_name : str
        The batch job name (e.g. ``batches/123456``).
    poll_interval : int
        Seconds between polls.

    Returns
    -------
    object
        The completed batch job object.

    Raises
    ------
    RuntimeError
        If the job fails, is cancelled, or expires.
    """
    import time

    client = _get_client()
    logger.info("Polling batch job %s …", job_name)

    while True:
        batch_job = client.batches.get(name=job_name)
        state = batch_job.state.name

        if state in _COMPLETED_STATES:
            break

        logger.debug("Batch %s state: %s — waiting %ds", job_name, state, poll_interval)
        time.sleep(poll_interval)

    if state != "JOB_STATE_SUCCEEDED":
        raise RuntimeError(
            f"Batch job {job_name} ended with state {state}: "
            f"{getattr(batch_job, 'error', 'unknown error')}"
        )

    logger.info("Batch job %s succeeded", job_name)
    return batch_job


# ---------------------------------------------------------------------------
# Batch image description
# ---------------------------------------------------------------------------


def batch_describe_images(
    items: list[tuple[bytes, str, str]],
) -> list[str]:
    """Describe multiple images via the Batch API (50% cost).

    Parameters
    ----------
    items : list[tuple[bytes, str, str]]
        Each tuple is ``(image_bytes, mime_type, extra_context)``.

    Returns
    -------
    list[str]
        Descriptions in the same order as the input items.
    """
    if not items:
        return []

    client = _get_client()

    inline_requests = []
    for image_bytes, mime_type, extra_context in items:
        prompt = _IMAGE_PROMPT
        if extra_context:
            prompt += f"\n\nSurrounding document context:\n{extra_context}"

        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

        inline_requests.append({
            "contents": [{
                "parts": [
                    {"text": prompt},
                    image_part,
                ],
                "role": "user",
            }]
        })

    logger.info("Creating batch job for %d image descriptions", len(inline_requests))

    batch_job = client.batches.create(
        model="gemini-3-flash-preview",
        src=inline_requests,
        config={"display_name": "tomd-image-descriptions"},
    )

    completed = _poll_batch_job(batch_job.name)

    # Extract responses in order
    descriptions: list[str] = []
    for resp in completed.dest.inlined_responses:
        if resp.response:
            try:
                descriptions.append(resp.response.text.strip())
            except AttributeError:
                descriptions.append(str(resp.response))
        elif resp.error:
            logger.warning("Batch image description error: %s", resp.error)
            descriptions.append("*[Image description unavailable]*")
        else:
            descriptions.append("*[Image description unavailable]*")

    return descriptions


# ---------------------------------------------------------------------------
# Batch markdown cleanup
# ---------------------------------------------------------------------------


def batch_cleanup_markdown(chunks: list[str]) -> list[str]:
    """Clean multiple markdown chunks via the Batch API (50% cost).

    Parameters
    ----------
    chunks : list[str]
        Raw markdown chunks to clean.

    Returns
    -------
    list[str]
        Cleaned chunks in the same order.
    """
    if not chunks:
        return []

    client = _get_client()

    inline_requests = []
    for i, chunk in enumerate(chunks):
        context = f"(Part {i + 1} of {len(chunks)})\n\n" if len(chunks) > 1 else ""
        inline_requests.append({
            "contents": [{
                "parts": [{"text": _CLEANUP_PROMPT + context + "\n\n" + chunk}],
                "role": "user",
            }]
        })

    logger.info("Creating batch job for %d cleanup chunks", len(inline_requests))

    batch_job = client.batches.create(
        model="gemini-3-flash-preview",
        src=inline_requests,
        config={"display_name": "tomd-markdown-cleanup"},
    )

    completed = _poll_batch_job(batch_job.name)

    cleaned: list[str] = []
    for resp in completed.dest.inlined_responses:
        if resp.response:
            try:
                cleaned.append(resp.response.text.strip())
            except AttributeError:
                cleaned.append(str(resp.response))
        elif resp.error:
            logger.warning("Batch cleanup error: %s", resp.error)
            cleaned.append("")
        else:
            cleaned.append("")

    return cleaned
