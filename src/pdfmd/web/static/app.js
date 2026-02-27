/* ===================================================================
   PDFMD — Application Logic
   =================================================================== */

(() => {
    'use strict';

    // DOM elements
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const browseTrigger = document.getElementById('browse-trigger');
    const fileInfo = document.getElementById('file-info');
    const fileName = document.getElementById('file-name');
    const fileSize = document.getElementById('file-size');
    const removeFile = document.getElementById('remove-file');
    const smartMode = document.getElementById('smart-mode');
    const convertBtn = document.getElementById('convert-btn');

    const uploadSection = document.getElementById('upload-section');
    const progressSection = document.getElementById('progress-section');
    const resultSection = document.getElementById('result-section');
    const errorSection = document.getElementById('error-section');

    const progressBar = document.getElementById('progress-bar');
    const progressPercent = document.getElementById('progress-percent');
    const progressStep = document.getElementById('progress-step');
    const progressPages = document.getElementById('progress-pages');
    const currentPageEl = document.getElementById('current-page');
    const totalPagesEl = document.getElementById('total-pages');

    const downloadBtn = document.getElementById('download-btn');
    const newConversion = document.getElementById('new-conversion');
    const retryBtn = document.getElementById('retry-btn');
    const errorMessage = document.getElementById('error-message');

    const markdownPreview = document.getElementById('markdown-preview');
    const rawMarkdown = document.getElementById('raw-markdown');

    const statPages = document.getElementById('stat-pages');
    const statTables = document.getElementById('stat-tables');
    const statImages = document.getElementById('stat-images');
    const statTime = document.getElementById('stat-time');

    let selectedFile = null;
    let currentJobId = null;
    let pollInterval = null;

    // ----------------------------------------------------------------
    // File selection
    // ----------------------------------------------------------------

    browseTrigger.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
    });

    dropZone.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            selectFile(e.target.files[0]);
        }
    });

    // Drag and drop
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
        if (files.length > 0 && files[0].type === 'application/pdf') {
            selectFile(files[0]);
        }
    });

    removeFile.addEventListener('click', () => {
        selectedFile = null;
        fileInput.value = '';
        fileInfo.classList.add('hidden');
        dropZone.classList.remove('hidden');
        convertBtn.disabled = true;
    });

    function selectFile(file) {
        if (!file.name.toLowerCase().endsWith('.pdf')) {
            alert('Please select a PDF file.');
            return;
        }
        selectedFile = file;
        fileName.textContent = file.name;
        fileSize.textContent = formatSize(file.size);
        fileInfo.classList.remove('hidden');
        dropZone.classList.add('hidden');
        convertBtn.disabled = false;
    }

    function formatSize(bytes) {
        if (bytes < 1024) return bytes + ' B';
        if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    }

    // ----------------------------------------------------------------
    // Conversion
    // ----------------------------------------------------------------

    convertBtn.addEventListener('click', startConversion);

    async function startConversion() {
        if (!selectedFile) return;

        // Show progress
        showSection('progress');

        const formData = new FormData();
        formData.append('file', selectedFile);
        formData.append('smart_mode', smartMode.checked ? 'true' : 'false');

        try {
            const resp = await fetch('/api/convert', { method: 'POST', body: formData });
            if (!resp.ok) {
                const err = await resp.json();
                throw new Error(err.detail || 'Upload failed');
            }
            const data = await resp.json();
            currentJobId = data.job_id;
            startPolling();
        } catch (err) {
            showError(err.message);
        }
    }

    function startPolling() {
        if (pollInterval) clearInterval(pollInterval);
        pollInterval = setInterval(pollStatus, 800);
    }

    async function pollStatus() {
        if (!currentJobId) return;

        try {
            const resp = await fetch(`/api/status/${currentJobId}`);
            if (!resp.ok) throw new Error('Status check failed');
            const data = await resp.json();

            // Update progress UI
            progressBar.style.width = data.percent + '%';
            progressPercent.textContent = data.percent + '%';
            progressStep.textContent = data.step;

            if (data.total_pages > 0) {
                progressPages.classList.remove('hidden');
                currentPageEl.textContent = data.current_page;
                totalPagesEl.textContent = data.total_pages;
            }

            if (data.done) {
                clearInterval(pollInterval);
                pollInterval = null;

                if (data.error || data.has_error) {
                    showError(data.error || data.conversion_error || 'Conversion failed');
                    return;
                }

                // Load preview
                await loadPreview();

                // Update stats
                statPages.textContent = data.page_count || 0;
                statTables.textContent = data.tables_found || 0;
                statImages.textContent = data.images_found || 0;
                statTime.textContent = (data.elapsed_seconds || 0) + 's';

                showSection('result');
            }
        } catch (err) {
            console.error('Polling error:', err);
        }
    }

    async function loadPreview() {
        try {
            const resp = await fetch(`/api/preview/${currentJobId}`);
            if (!resp.ok) return;
            const data = await resp.json();

            // Render markdown preview
            markdownPreview.innerHTML = marked.parse(data.markdown);

            // Apply syntax highlighting to code blocks
            markdownPreview.querySelectorAll('pre code').forEach((block) => {
                hljs.highlightElement(block);
            });

            // Set raw markdown
            rawMarkdown.textContent = data.markdown;
        } catch (err) {
            console.error('Preview error:', err);
            markdownPreview.innerHTML = '<p>Failed to load preview</p>';
        }
    }

    // ----------------------------------------------------------------
    // Download
    // ----------------------------------------------------------------

    downloadBtn.addEventListener('click', () => {
        if (currentJobId) {
            window.location.href = `/api/download/${currentJobId}`;
        }
    });

    // ----------------------------------------------------------------
    // Tabs
    // ----------------------------------------------------------------

    document.querySelectorAll('.tab').forEach((tab) => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
        });
    });

    // ----------------------------------------------------------------
    // Navigation
    // ----------------------------------------------------------------

    newConversion.addEventListener('click', resetUI);
    retryBtn.addEventListener('click', resetUI);

    function resetUI() {
        selectedFile = null;
        fileInput.value = '';
        currentJobId = null;

        fileInfo.classList.add('hidden');
        dropZone.classList.remove('hidden');
        convertBtn.disabled = true;
        progressBar.style.width = '0%';
        progressPercent.textContent = '0%';
        progressStep.textContent = 'Initializing';
        progressPages.classList.add('hidden');

        showSection('upload');
    }

    // ----------------------------------------------------------------
    // Section management
    // ----------------------------------------------------------------

    function showSection(name) {
        uploadSection.classList.add('hidden');
        progressSection.classList.add('hidden');
        resultSection.classList.add('hidden');
        errorSection.classList.add('hidden');

        switch (name) {
            case 'upload': uploadSection.classList.remove('hidden'); break;
            case 'progress': progressSection.classList.remove('hidden'); break;
            case 'result': resultSection.classList.remove('hidden'); break;
            case 'error': errorSection.classList.remove('hidden'); break;
        }
    }

    function showError(msg) {
        errorMessage.textContent = msg;
        showSection('error');
    }
})();
