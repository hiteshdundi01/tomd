# TOMD

**Convert Anything to Markdown — PDFs, Web Articles, Blog Posts & More**

AI-powered tool that converts PDF documents and web articles into clean, structured Markdown with OCR support, image downloading, and intelligent formatting cleanup.

![TOMD Screenshot](https://raw.githubusercontent.com/hiteshdundi01/tomd/main/docs/screenshot.png)

## ✨ Features

### PDF → Markdown
- **Digital & Scanned PDFs** — Extracts text from selectable PDFs using PyMuPDF; falls back to Tesseract OCR for scanned documents
- **Table Extraction** — Detects tables via pdfplumber; renders as Markdown or falls back to HTML for complex layouts
- **AI Image Descriptions** — Sends extracted images to Gemini for detailed, context-aware descriptions
- **Math & Code Detection** — Heuristically detects LaTeX formulas and code blocks, wrapping them in proper Markdown syntax
- **Multi-Column Layouts** — Correctly handles two-column academic papers and reports
- **Headings & Structure** — Infers heading hierarchy from font sizes and weights

### Web Article → Markdown *(NEW)*
- **Any Website** — Scrapes articles from Substack, Medium, WordPress, and most blog platforms
- **JavaScript Rendering** — Uses Playwright headless Chromium so JS-heavy pages are fully captured
- **Smart Extraction** — Readability-based boilerplate removal strips away nav, ads, and sidebars
- **Substack-Specific Parser** — High-fidelity extraction targeting Substack's DOM structure
- **Local Image Download** — Downloads article images alongside the `.md` file with content-hash deduplication
- **YAML Frontmatter** — Adds title, author, date, and source URL metadata

### Shared
- **Smart Mode** — Optional Gemini-powered post-processing that cleans up formatting and restructures headings
- **Web UI** — Drag-and-drop PDF upload or paste-a-URL with real-time progress, Markdown preview, and one-click download

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** — Fast Python package manager
- **[Tesseract OCR](https://github.com/tesseract-ocr/tesseract)** — Only needed for scanned PDFs
  - Windows: `choco install tesseract`
  - macOS: `brew install tesseract`
  - Linux: `apt install tesseract-ocr`
- **[Gemini API Key](https://aistudio.google.com/apikey)** — Required for image descriptions and Smart Mode

### Installation

```bash
git clone https://github.com/hiteshdundi01/tomd.git
cd tomd

# Create virtual environment & install
uv venv .venv
uv pip install -e .

# Install Playwright browser (for web scraping)
python -m playwright install chromium

# Configure your API key
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### Run

**Windows** — Double-click `start.bat`

**Command line:**
```bash
tomd
# or
python -m tomd.web.app
```

Open **http://127.0.0.1:8000** in your browser.

## 🔧 Usage

### Web UI

1. Open http://127.0.0.1:8000
2. Choose a mode: **📄 PDF** or **🌐 Web Article**
3. Upload a PDF or paste an article URL
4. Toggle **Smart Mode** for AI-powered cleanup
5. Click **Convert / Scrape to Markdown**
6. Preview the result and download the `.md` file

### Python API

```python
# PDF conversion
from tomd import convert_pdf_to_markdown

result = convert_pdf_to_markdown("document.pdf", smart_mode=True)
print(result.markdown)

# Web article scraping
from tomd import scrape_to_markdown

result = scrape_to_markdown("https://example.substack.com/p/article-title")
print(result.markdown)
print(f"Title: {result.title}")
print(f"Author: {result.author}")
print(f"Images: {result.images_downloaded}")
```

## 🏗️ Architecture

```
src/tomd/
├── converter.py          # PDF orchestrator (8-step pipeline)
├── text_extractor.py     # PyMuPDF — headings, columns, footnotes, links
├── ocr_extractor.py      # Tesseract OCR — scanned PDF support
├── table_extractor.py    # pdfplumber — Markdown/HTML tables
├── image_handler.py      # Image extraction + Gemini Vision descriptions
├── math_code_detector.py # LaTeX & code block detection
├── gemini_client.py      # Gemini API wrapper (Vision + cleanup)
├── scraper/
│   ├── converter.py      # Scraper orchestrator (7-step pipeline)
│   ├── fetcher.py        # Playwright headless page fetcher
│   ├── extractor.py      # Readability extraction + HTML→Markdown
│   ├── substack.py       # Substack-specific parser
│   ├── image_downloader.py # Image download + URL rewriting
│   └── models.py         # Data classes
└── web/
    ├── app.py            # FastAPI backend (PDF + scrape APIs)
    └── static/           # Frontend (HTML/CSS/JS)
```

## ⚙️ Configuration

| Environment Variable | Required | Description |
|---------------------|----------|-------------|
| `GEMINI_API_KEY` | Yes | Google AI Studio API key |

Create a `.env` file in the project root (see `.env.example`).

## 📦 Tech Stack

| Component | Library |
|-----------|---------|
| Text Extraction | [PyMuPDF](https://pymupdf.readthedocs.io/) |
| Table Extraction | [pdfplumber](https://github.com/jsvine/pdfplumber) |
| OCR | [Tesseract](https://github.com/tesseract-ocr/tesseract) via pytesseract |
| Web Scraping | [Playwright](https://playwright.dev/python/) + [readability-lxml](https://github.com/mozilla/readability) |
| HTML Parsing | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) |
| AI / Vision | [Google Gemini](https://ai.google.dev/) via google-genai |
| Web Framework | [FastAPI](https://fastapi.tiangolo.com/) |
| Frontend | Vanilla HTML/CSS/JS with glassmorphism design |

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
