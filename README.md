# PDFMD

**AI-Powered PDF → Markdown Converter**

Convert PDF documents to clean, structured Markdown with OCR support, AI-powered image descriptions, and intelligent formatting cleanup.

![PDFMD Screenshot](https://raw.githubusercontent.com/hiteshdundi01/pdfmd/main/docs/screenshot.png)

## ✨ Features

- **Digital & Scanned PDFs** — Extracts text from selectable PDFs using PyMuPDF; falls back to Tesseract OCR for scanned documents
- **Table Extraction** — Detects tables via pdfplumber; renders as Markdown or falls back to HTML for complex layouts
- **AI Image Descriptions** — Sends extracted images to Gemini for detailed, context-aware descriptions
- **Math & Code Detection** — Heuristically detects LaTeX formulas and code blocks, wrapping them in proper Markdown syntax
- **Multi-Column Layouts** — Correctly handles two-column academic papers and reports
- **Headings & Structure** — Infers heading hierarchy from font sizes and weights
- **Footnotes & Links** — Preserves hyperlinks and footnotes from the original PDF
- **Smart Mode** — Optional Gemini-powered post-processing that cleans OCR artifacts, fixes formatting, and restructures headings
- **Web UI** — Drag-and-drop upload with real-time progress, Markdown preview, and one-click download

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
git clone https://github.com/hiteshdundi01/pdfmd.git
cd pdfmd

# Create virtual environment & install
uv venv .venv
uv pip install -e .

# Configure your API key
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### Run the Web UI

```bash
pdfmd
# or
python -m pdfmd.web.app
```

Open **http://127.0.0.1:8000** in your browser.

## 🔧 Usage

### Web UI

1. Open http://127.0.0.1:8000
2. Drag and drop a PDF (or click to browse)
3. Toggle **Smart Mode** for AI-powered cleanup
4. Click **Convert to Markdown**
5. Preview the result and download the `.md` file

### Python API

```python
from pdfmd import convert_pdf_to_markdown

result = convert_pdf_to_markdown(
    "document.pdf",
    smart_mode=True,
)

print(result.markdown)
print(f"Pages: {result.page_count}")
print(f"Tables: {result.tables_found}")
print(f"Images: {result.images_found}")
```

## 🏗️ Architecture

```
src/pdfmd/
├── converter.py          # Master orchestrator (8-step pipeline)
├── text_extractor.py     # PyMuPDF — headings, columns, footnotes, links
├── ocr_extractor.py      # Tesseract OCR — scanned PDF support
├── table_extractor.py    # pdfplumber — Markdown/HTML tables
├── image_handler.py      # Image extraction + Gemini Vision descriptions
├── math_code_detector.py # LaTeX & code block detection
├── gemini_client.py      # Gemini API wrapper (Vision + cleanup)
└── web/
    ├── app.py            # FastAPI backend
    └── static/           # Frontend (HTML/CSS/JS)
```

### Conversion Pipeline

1. **Detect PDF type** — digital vs. scanned
2. **Extract text** — PyMuPDF or Tesseract OCR
3. **Extract tables** — pdfplumber → Markdown/HTML
4. **Extract & describe images** — PyMuPDF + Gemini Vision
5. **Detect math/code** — Heuristic pattern matching
6. **Smart Mode** *(optional)* — Gemini cleanup pass
7. **Final cleanup** — Normalize whitespace and formatting

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
| AI / Vision | [Google Gemini](https://ai.google.dev/) via google-genai |
| Web Framework | [FastAPI](https://fastapi.tiangolo.com/) |
| Frontend | Vanilla HTML/CSS/JS with glassmorphism design |

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
