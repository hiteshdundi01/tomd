"""FastAPI web application for PDF and web article to Markdown conversion."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="TOMD — Convert Anything to Markdown")

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

from tomd.converter import ConversionProgress, ConversionResult

_jobs: dict[str, dict] = {}  # job_id → { type, progress, result, ... }

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = Path(tempfile.gettempdir()) / "tomd_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Routes — General
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main UI."""
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Routes — PDF Conversion
# ---------------------------------------------------------------------------

@app.post("/api/convert")
async def convert(
    file: UploadFile = File(...),
    smart_mode: bool = Form(False),
):
    """Upload a PDF and start conversion."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF file.")

    job_id = str(uuid.uuid4())

    # Save uploaded file
    pdf_path = UPLOAD_DIR / f"{job_id}.pdf"
    with open(pdf_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # Initialize job
    _jobs[job_id] = {
        "type": "pdf",
        "progress": ConversionProgress(),
        "result": None,
        "pdf_path": str(pdf_path),
        "smart_mode": smart_mode,
    }

    # Run conversion in background
    asyncio.get_event_loop().run_in_executor(
        None, _run_conversion, job_id
    )

    return JSONResponse({"job_id": job_id})


def _run_conversion(job_id: str) -> None:
    """Run the PDF conversion (called in a thread pool)."""
    from tomd.converter import convert_pdf_to_markdown

    job = _jobs[job_id]

    def on_progress(p: ConversionProgress):
        job["progress"] = p

    result = convert_pdf_to_markdown(
        job["pdf_path"],
        smart_mode=job["smart_mode"],
        progress_callback=on_progress,
    )
    job["result"] = result

    # Save result to file
    if result.markdown:
        md_path = UPLOAD_DIR / f"{job_id}.md"
        md_path.write_text(result.markdown, encoding="utf-8")


# ---------------------------------------------------------------------------
# Routes — Web Scraper
# ---------------------------------------------------------------------------

class ScrapeRequest(BaseModel):
    url: str
    smart_mode: bool = False


@app.post("/api/scrape")
async def scrape(req: ScrapeRequest):
    """Start scraping a web article."""
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=400, detail="Please provide a URL.")

    from tomd.scraper.models import ScrapeProgress

    job_id = str(uuid.uuid4())

    _jobs[job_id] = {
        "type": "scrape",
        "progress": ScrapeProgress(),
        "result": None,
        "url": req.url.strip(),
        "smart_mode": req.smart_mode,
    }

    asyncio.get_event_loop().run_in_executor(
        None, _run_scrape, job_id
    )

    return JSONResponse({"job_id": job_id})


def _run_scrape(job_id: str) -> None:
    """Run the web scrape (called in a thread pool)."""
    from tomd.scraper.converter import scrape_to_markdown
    from tomd.scraper.models import ScrapeProgress

    job = _jobs[job_id]

    def on_progress(p: ScrapeProgress):
        job["progress"] = p

    result = scrape_to_markdown(
        job["url"],
        smart_mode=job["smart_mode"],
        progress_callback=on_progress,
    )
    job["result"] = result

    # Save result to file
    if result.markdown:
        md_path = UPLOAD_DIR / f"{job_id}.md"
        md_path.write_text(result.markdown, encoding="utf-8")


# ---------------------------------------------------------------------------
# Routes — Unified Status / Download / Preview
# ---------------------------------------------------------------------------

@app.get("/api/status/{job_id}")
async def status(job_id: str):
    """Get the current job progress (works for both PDF and scrape jobs)."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    progress = job["progress"]
    result = job.get("result")
    job_type = job.get("type", "pdf")

    response = {
        "type": job_type,
        "step": progress.step,
        "percent": progress.percent,
        "done": progress.done,
        "error": progress.error,
    }

    if job_type == "pdf":
        response["current_page"] = getattr(progress, "current_page", 0)
        response["total_pages"] = getattr(progress, "total_pages", 0)

        if result:
            response.update({
                "page_count": result.page_count,
                "images_found": result.images_found,
                "tables_found": result.tables_found,
                "used_ocr": result.used_ocr,
                "elapsed_seconds": result.elapsed_seconds,
                "has_error": bool(result.error),
                "conversion_error": result.error,
            })
    elif job_type == "scrape":
        if result:
            response.update({
                "title": result.title,
                "author": result.author,
                "date": result.date,
                "source_url": result.source_url,
                "images_downloaded": result.images_downloaded,
                "elapsed_seconds": result.elapsed_seconds,
                "has_error": bool(result.error),
                "scrape_error": result.error,
            })

    return JSONResponse(response)


@app.get("/api/download/{job_id}")
async def download(job_id: str):
    """Download the generated markdown file."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = job.get("result")
    if not result or not result.markdown:
        raise HTTPException(status_code=400, detail="Conversion not complete or failed")

    md_path = UPLOAD_DIR / f"{job_id}.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    # Determine filename
    job_type = job.get("type", "pdf")
    if job_type == "pdf":
        original_name = Path(job["pdf_path"]).stem + ".md"
    else:
        # Use article title or URL slug
        title = getattr(result, "title", "") or "article"
        # Sanitize for filename
        safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
        safe_name = safe_name.strip()[:80] or "article"
        original_name = safe_name + ".md"

    return FileResponse(
        path=str(md_path),
        filename=original_name,
        media_type="text/markdown",
    )


@app.get("/api/preview/{job_id}")
async def preview(job_id: str):
    """Get the markdown content for preview."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = job.get("result")
    if not result or not result.markdown:
        raise HTTPException(status_code=400, detail="Conversion not complete or failed")

    return JSONResponse({"markdown": result.markdown})


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    """Run the development server."""
    import uvicorn
    uvicorn.run(
        "tomd.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
