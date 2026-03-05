/**
 * TOMD — Frontend application logic
 * Supports both PDF conversion and web article scraping
 */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let currentMode = 'pdf';  // 'pdf' | 'scrape'
let selectedFile = null;
let currentJobId = null;
let pollInterval = null;

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// Mode tabs
const modeTabs = $$('.mode-tab');
const pdfMode = $('#pdf-mode');
const scrapeMode = $('#scrape-mode');

// PDF elements
const dropZone = $('#drop-zone');
const fileInput = $('#file-input');
const browseTrigger = $('#browse-trigger');
const fileInfo = $('#file-info');
const fileName = $('#file-name');
const fileSize = $('#file-size');
const removeFile = $('#remove-file');

// Scrape elements
const urlInput = $('#url-input');
const clearUrl = $('#clear-url');

// Shared elements
const smartMode = $('#smart-mode');
const convertBtn = $('#convert-btn');

// Sections
const uploadSection = $('#upload-section');
const progressSection = $('#progress-section');
const resultSection = $('#result-section');
const errorSection = $('#error-section');

// Progress
const progressBar = $('#progress-bar');
const progressPercent = $('#progress-percent');
const progressStep = $('#progress-step');
const progressPages = $('#progress-pages');
const currentPage = $('#current-page');
const totalPages = $('#total-pages');

// Result
const downloadBtn = $('#download-btn');
const newConversion = $('#new-conversion');
const markdownPreview = $('#markdown-preview');
const rawMarkdown = $('#raw-markdown');
const resultTabs = $$('.tab');
const articleInfo = $('#article-info');
const articleTitle = $('#article-title');
const articleAuthor = $('#article-author');

// Stats
const statPages = $('#stat-pages');
const statTables = $('#stat-tables');
const statImages = $('#stat-images');
const statTime = $('#stat-time');

// Error
const errorMessage = $('#error-message');
const retryBtn = $('#retry-btn');


// ---------------------------------------------------------------------------
// Mode switching
// ---------------------------------------------------------------------------

modeTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const mode = tab.dataset.mode;
        if (mode === currentMode) return;

        currentMode = mode;

        // Update tab styling
        modeTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');

        // Toggle content panels
        pdfMode.classList.toggle('active', mode === 'pdf');
        scrapeMode.classList.toggle('active', mode === 'scrape');

        // Update button text
        convertBtn.querySelector('.btn-text').textContent =
            mode === 'pdf' ? 'Convert to Markdown' : 'Scrape to Markdown';

        // Update enabled state
        updateConvertButton();
    });
});


// ---------------------------------------------------------------------------
// PDF — Drag & Drop + File selection
// ---------------------------------------------------------------------------

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
        const name = files[0].name.toLowerCase();
        const validExts = ['.pdf', '.docx', '.doc', '.rtf'];
        if (validExts.some(ext => name.endsWith(ext))) {
            selectFile(files[0]);
        }
    }
});

browseTrigger.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => {
    if (fileInput.files.length > 0) selectFile(fileInput.files[0]);
});

removeFile.addEventListener('click', () => {
    selectedFile = null;
    fileInfo.classList.add('hidden');
    dropZone.style.display = '';
    fileInput.value = '';
    updateConvertButton();
});

function selectFile(file) {
    selectedFile = file;
    fileName.textContent = file.name;
    fileSize.textContent = formatSize(file.size);
    fileInfo.classList.remove('hidden');
    dropZone.style.display = 'none';
    updateConvertButton();
}


// ---------------------------------------------------------------------------
// Scrape — URL input
// ---------------------------------------------------------------------------

urlInput.addEventListener('input', () => {
    clearUrl.classList.toggle('hidden', !urlInput.value);
    updateConvertButton();
});

clearUrl.addEventListener('click', () => {
    urlInput.value = '';
    clearUrl.classList.add('hidden');
    updateConvertButton();
    urlInput.focus();
});

// Allow Enter key to trigger scrape
urlInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !convertBtn.disabled) {
        convertBtn.click();
    }
});


// ---------------------------------------------------------------------------
// Shared — Convert button
// ---------------------------------------------------------------------------

function updateConvertButton() {
    if (currentMode === 'pdf') {
        convertBtn.disabled = !selectedFile;
    } else {
        convertBtn.disabled = !urlInput.value.trim();
    }
}

convertBtn.addEventListener('click', () => {
    if (currentMode === 'pdf') {
        startPdfConversion();
    } else {
        startScrape();
    }
});


// ---------------------------------------------------------------------------
// PDF Conversion
// ---------------------------------------------------------------------------

async function startPdfConversion() {
    if (!selectedFile) return;

    showSection('progress');
    resetProgress();

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('smart_mode', smartMode.checked);

    try {
        const resp = await fetch('/api/convert', { method: 'POST', body: formData });
        const data = await resp.json();

        if (!resp.ok) {
            showError(data.detail || 'Upload failed');
            return;
        }

        currentJobId = data.job_id;
        startPolling();
    } catch (err) {
        showError('Network error: ' + err.message);
    }
}


// ---------------------------------------------------------------------------
// Web Scrape
// ---------------------------------------------------------------------------

async function startScrape() {
    const url = urlInput.value.trim();
    if (!url) return;

    showSection('progress');
    resetProgress();

    try {
        const resp = await fetch('/api/scrape', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                smart_mode: smartMode.checked,
            }),
        });
        const data = await resp.json();

        if (!resp.ok) {
            showError(data.detail || 'Scrape request failed');
            return;
        }

        currentJobId = data.job_id;
        startPolling();
    } catch (err) {
        showError('Network error: ' + err.message);
    }
}


// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

function startPolling() {
    pollInterval = setInterval(async () => {
        try {
            const resp = await fetch(`/api/status/${currentJobId}`);
            const data = await resp.json();

            // Update progress UI
            progressBar.style.width = data.percent + '%';
            progressPercent.textContent = data.percent + '%';
            progressStep.textContent = data.step;

            // PDF-specific page progress
            if (data.type === 'pdf' && data.total_pages > 0) {
                progressPages.classList.remove('hidden');
                currentPage.textContent = data.current_page;
                totalPages.textContent = data.total_pages;
            } else {
                progressPages.classList.add('hidden');
            }

            if (data.done) {
                clearInterval(pollInterval);
                pollInterval = null;

                if (data.error || data.has_error) {
                    showError(data.error || data.conversion_error || data.scrape_error || 'Unknown error');
                } else {
                    showResult(data);
                }
            }
        } catch (err) {
            clearInterval(pollInterval);
            pollInterval = null;
            showError('Lost connection to server');
        }
    }, 500);
}


// ---------------------------------------------------------------------------
// Result display
// ---------------------------------------------------------------------------

async function showResult(data) {
    showSection('result');

    const jobType = data.type || 'pdf';

    // Toggle PDF-specific stats
    document.querySelectorAll('.stat-pdf').forEach(el => {
        el.style.display = (jobType === 'pdf' || jobType === 'docx') ? '' : 'none';
    });

    // Stats
    if (jobType === 'pdf' || jobType === 'docx') {
        statPages.textContent = data.page_count || 0;
        statTables.textContent = data.tables_found || 0;
        statImages.textContent = data.images_found || 0;
    } else {
        statImages.textContent = data.images_downloaded || 0;
    }
    statTime.textContent = (data.elapsed_seconds || 0).toFixed(1) + 's';

    // Article info (scrape only)
    if (jobType === 'scrape' && (data.title || data.author)) {
        articleInfo.classList.remove('hidden');
        articleTitle.textContent = data.title || '';
        articleAuthor.textContent = data.author ? `by ${data.author}` : '';
    } else {
        articleInfo.classList.add('hidden');
    }

    // Load preview
    try {
        const resp = await fetch(`/api/preview/${currentJobId}`);
        const previewData = await resp.json();

        if (previewData.markdown) {
            markdownPreview.innerHTML = marked.parse(previewData.markdown);
            rawMarkdown.textContent = previewData.markdown;

            // Highlight code blocks
            markdownPreview.querySelectorAll('pre code').forEach(block => {
                hljs.highlightElement(block);
            });
        }
    } catch (err) {
        markdownPreview.innerHTML = '<p>Failed to load preview</p>';
    }
}


// ---------------------------------------------------------------------------
// Download
// ---------------------------------------------------------------------------

downloadBtn.addEventListener('click', () => {
    if (currentJobId) {
        window.location.href = `/api/download/${currentJobId}`;
    }
});


// ---------------------------------------------------------------------------
// Tabs (Preview / Raw)
// ---------------------------------------------------------------------------

resultTabs.forEach(tab => {
    tab.addEventListener('click', () => {
        const target = tab.dataset.tab;
        resultTabs.forEach(t => t.classList.remove('active'));
        tab.classList.add('active');

        document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));
        document.getElementById(`tab-${target}`).classList.add('active');
    });
});


// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

newConversion.addEventListener('click', resetAll);
retryBtn.addEventListener('click', resetAll);

function resetAll() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
    currentJobId = null;
    selectedFile = null;
    fileInput.value = '';
    urlInput.value = '';
    clearUrl.classList.add('hidden');
    fileInfo.classList.add('hidden');
    dropZone.style.display = '';
    articleInfo.classList.add('hidden');
    updateConvertButton();
    showSection('upload');
}


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function showSection(name) {
    uploadSection.classList.toggle('hidden', name !== 'upload');
    progressSection.classList.toggle('hidden', name !== 'progress');
    resultSection.classList.toggle('hidden', name !== 'result');
    errorSection.classList.toggle('hidden', name !== 'error');
}

function resetProgress() {
    progressBar.style.width = '0%';
    progressPercent.textContent = '0%';
    progressStep.textContent = 'Initializing';
    progressPages.classList.add('hidden');
}

function showError(message) {
    errorMessage.textContent = message;
    showSection('error');
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}


// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

updateConvertButton();
