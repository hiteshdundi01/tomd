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

from fastapi import BackgroundTasks, FastAPI, File, Form, UploadFile, HTTPException
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
    use_batch: bool = Form(False),
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
        "use_batch": use_batch,
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
        use_batch=job.get("use_batch", False),
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
    use_batch: bool = False


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
        "use_batch": req.use_batch,
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
        use_batch=job.get("use_batch", False),
        progress_callback=on_progress,
    )
    job["result"] = result

    # Save result to file
    if result.markdown:
        md_path = UPLOAD_DIR / f"{job_id}.md"
        md_path.write_text(result.markdown, encoding="utf-8")

        # Track the image output directory for serving
        if result.output_dir:
            job["output_dir"] = result.output_dir


# ---------------------------------------------------------------------------
# Routes — Image serving for scrape jobs
# ---------------------------------------------------------------------------

@app.get("/images/{filename}")
async def serve_image(filename: str):
    """Serve downloaded images from scrape jobs."""
    # Search all active scrape jobs for the requested image
    for job in _jobs.values():
        if job.get("type") != "scrape":
            continue
        output_dir = job.get("output_dir")
        if not output_dir:
            continue
        img_path = Path(output_dir) / "images" / filename
        if img_path.exists() and img_path.is_file():
            return FileResponse(str(img_path))

    raise HTTPException(status_code=404, detail="Image not found")


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


def _cleanup_job(job_id: str) -> None:
    """Delete all temp files for a job after download."""
    job = _jobs.pop(job_id, None)
    if not job:
        return

    # Remove uploaded PDF
    pdf_path = job.get("pdf_path")
    if pdf_path:
        try:
            Path(pdf_path).unlink(missing_ok=True)
        except Exception:
            pass

    # Remove generated markdown
    for ext in (".md", ".zip"):
        try:
            (UPLOAD_DIR / f"{job_id}{ext}").unlink(missing_ok=True)
        except Exception:
            pass

    # Remove scrape image directory
    output_dir = job.get("output_dir")
    if output_dir and Path(output_dir).exists():
        try:
            shutil.rmtree(output_dir, ignore_errors=True)
        except Exception:
            pass

    logger.info("Cleaned up job %s", job_id)


@app.get("/api/download/{job_id}")
async def download(job_id: str, background_tasks: BackgroundTasks):
    """Download the generated markdown file (or zip with images for scrape jobs)."""
    import zipfile

    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    result = job.get("result")
    if not result or not result.markdown:
        raise HTTPException(status_code=400, detail="Conversion not complete or failed")

    md_path = UPLOAD_DIR / f"{job_id}.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    # Schedule cleanup after the response is sent
    background_tasks.add_task(_cleanup_job, job_id)

    # Determine filename
    job_type = job.get("type", "pdf")
    if job_type == "pdf":
        original_name = Path(job["pdf_path"]).stem + ".md"
        return FileResponse(
            path=str(md_path),
            filename=original_name,
            media_type="text/markdown",
        )

    # ── Scrape jobs: bundle markdown + images into a zip ──────────
    title = getattr(result, "title", "") or "article"
    safe_name = "".join(c if c.isalnum() or c in " -_" else "" for c in title)
    safe_name = safe_name.strip()[:80] or "article"

    output_dir = job.get("output_dir")
    images_dir = Path(output_dir) / "images" if output_dir else None
    has_images = images_dir and images_dir.exists() and any(images_dir.iterdir())

    if has_images:
        # Create a zip with the markdown + images/ folder
        zip_path = UPLOAD_DIR / f"{job_id}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(md_path, f"{safe_name}.md")
            for img_file in images_dir.iterdir():
                if img_file.is_file():
                    zf.write(img_file, f"images/{img_file.name}")

        return FileResponse(
            path=str(zip_path),
            filename=f"{safe_name}.zip",
            media_type="application/zip",
        )

    # No images — just return the markdown file
    return FileResponse(
        path=str(md_path),
        filename=f"{safe_name}.md",
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
