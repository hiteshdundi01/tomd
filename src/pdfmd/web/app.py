"""FastAPI web application for PDF-to-Markdown conversion."""

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="PDFMD — PDF to Markdown Converter")

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

from pdfmd.converter import ConversionProgress, ConversionResult

_jobs: dict[str, dict] = {}  # job_id → { progress, result, pdf_path }

STATIC_DIR = Path(__file__).parent / "static"
UPLOAD_DIR = Path(tempfile.gettempdir()) / "pdfmd_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main UI."""
    html_path = STATIC_DIR / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


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
    """Run the conversion (called in a thread pool)."""
    from pdfmd.converter import convert_pdf_to_markdown

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


@app.get("/api/status/{job_id}")
async def status(job_id: str):
    """Get the current conversion progress."""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    progress = job["progress"]
    result = job.get("result")

    response = {
        "step": progress.step,
        "percent": progress.percent,
        "current_page": progress.current_page,
        "total_pages": progress.total_pages,
        "done": progress.done,
        "error": progress.error,
    }

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

    # Use original filename with .md extension
    original_name = Path(job["pdf_path"]).stem + ".md"

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
        "pdfmd.web.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
