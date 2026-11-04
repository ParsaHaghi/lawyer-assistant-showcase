// State management
let currentWorkspace = '';
let activeClientName = null;
let clientsList = [];
let pendingAssocFilename = null;
let selectedAssocClient = null;
let associationSourceFolder = null;

// Persian text normalization (mirrors backend normalize_persian)
function normalizePersian(text) {
    if (!text) return text;
    // NFKC normalization
    text = text.normalize('NFKC');
    // Arabic Yeh (U+064A) -> Persian Yeh (U+06CC)
    text = text.replace(/\u064A/g, '\u06CC');
    // Arabic Kaf (U+0643) -> Persian Kaf (U+06A9)
    text = text.replace(/\u0643/g, '\u06A9');
    // Arabic Alef Maksura (U+0649) -> Persian Yeh (U+06CC)
    text = text.replace(/\u0649/g, '\u06CC');
    // Remove zero-width characters
    text = text.replace(/\u200C/g, ' ');
    text = text.replace(/\u200D/g, '');
    text = text.replace(/\u200B/g, '');
    text = text.replace(/\uFEFF/g, '');
    // Collapse multiple spaces
    text = text.replace(/\s+/g, ' ').trim();
    return text;
}

// Initialize Lucide Icons and app events when DOM loads
document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

function initApp() {
    // Initialize Lucide
    if (window.lucide) {
        window.lucide.createIcons();
    }

    // Load initial configuration
    loadWorkspaceConfig();

    // Event Listeners
    setupEventListeners();
}

// REST API Requests Helper
async function apiRequest(url, method = 'GET', data = null, isFormData = false) {
    const options = { method };
    
    if (data) {
        if (isFormData) {
            options.body = data;
        } else {
            options.headers = {
                'Content-Type': 'application/json'
            };
            options.body = JSON.stringify(data);
        }
    }

    try {
        const response = await fetch(url, options);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'خطایی در ارتباط با سرور رخ داد');
        }
        return result;
    } catch (error) {
        console.error(`API Error (${url}):`, error);
        showToast(error.message, 'error');
        throw error;
    }
}

// Load workspace path and then fetch clients
async function loadWorkspaceConfig() {
    try {
        const config = await apiRequest('/api/config');
        currentWorkspace = config.workspace_path;
        document.getElementById('workspacePathInput').value = currentWorkspace;
        document.getElementById('workspacePathModalInput').value = currentWorkspace;
        
        await fetchClients();
    } catch (e) {
        showToast('خطا در بارگذاری پیکربندی پوشه کاری', 'error');
    }
}

// Fetch all clients inside the workspace
async function fetchClients() {
    const clientListEl = document.getElementById('clientList');
    
    try {
        const data = await apiRequest('/api/clients');
        clientsList = data.clients || [];
        
        // Update counters
        document.getElementById('clientCountBadge').innerText = clientsList.length;
        document.getElementById('totalClientsCount').innerText = clientsList.length;
        
        let totalFiles = 0;
        clientsList.forEach(c => totalFiles += (c.files ? c.files.length : 0));
        document.getElementById('totalFilesCount').innerText = totalFiles;

        renderClientList(clientsList);
    } catch (e) {
        clientListEl.innerHTML = `
            <div class="loading-state">
                <i data-lucide="alert-circle" style="color: var(--danger)"></i>
                <span>خطا در دریافت لیست موکلین</span>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
    }
}

// Render client items in sidebar
function renderClientList(list) {
    const clientListEl = document.getElementById('clientList');
    
    if (list.length === 0) {
        clientListEl.innerHTML = `
            <div class="loading-state">
                <i data-lucide="folder-open"></i>
                <span>پرونده‌ای یافت نشد</span>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
        return;
    }

    clientListEl.innerHTML = '';
    list.forEach(client => {
        const li = document.createElement('li');
        const statusClass = client.status ? `status-${client.status}` : 'status-red';
        li.className = `client-item ${statusClass} ${activeClientName === client.name ? 'active' : ''}`;
        li.dataset.name = client.name;
        
        // Get client subtitle info (extract national ID or date if available)
        let subtitle = 'بدون مشخصات';
        if (client.metadata && Object.keys(client.metadata).length > 0) {
            const parts = [];
            if (client.metadata.id_number) parts.push(`کد ملی: ${client.metadata.id_number}`);
            if (client.metadata.client_number) parts.push(`قرارداد: ${client.metadata.client_number}`);
            if (parts.length > 0) {
                subtitle = parts.join(' | ');
            }
        }

        li.innerHTML = `
            <div class="client-item-icon">
                <i data-lucide="folder"></i>
            </div>
            <div class="client-item-info">
                <div class="client-item-name" title="${client.name}">${client.name}</div>
                <div class="client-item-meta" title="${subtitle}">${subtitle}</div>
            </div>
        `;

        li.addEventListener('click', () => selectClient(client.name));
        clientListEl.appendChild(li);
    });

    if (window.lucide) window.lucide.createIcons();
}

// Select a specific client folder and load details
async function selectClient(clientName) {
    activeClientName = clientName;
    
    // Highlight active in sidebar
    document.querySelectorAll('.client-item').forEach(el => {
        el.classList.toggle('active', el.dataset.name === clientName);
    });

    // Hide empty state, show dashboard
    document.getElementById('emptyState').style.display = 'none';
    document.getElementById('clientDashboard').style.display = 'flex';

    // Set title
    document.getElementById('activeClientTitle').innerText = clientName;
    document.getElementById('activeClientSubtitle').innerText = `پوشه: ${clientName}`;

    // Reset Form
    document.getElementById('metadataForm').reset();
    document.getElementById('customFieldsContainer').innerHTML = '';

    // Fetch fresh client data
    try {
        const clientData = await apiRequest(`/api/clients/${encodeURIComponent(clientName)}`);
        
        // Populate standard form fields
        const meta = clientData.metadata || {};
        
        const standardFields = ['first_name', 'last_name', 'id_number', 'fathername', 'client_number', 'contract_date', 'contract_amount', 'shomare_parvande'];
        standardFields.forEach(field => {
            const input = document.getElementById(`field_${field}`);
            if (input) {
                input.value = meta[field] || '';
            }
        });

        // Populate custom fields (non-standard ones)
        const customFieldsContainer = document.getElementById('customFieldsContainer');
        Object.entries(meta).forEach(([key, val]) => {
            if (!standardFields.includes(key)) {
                addCustomFieldRow(key, val);
            }
        });

        // Populate Files
        renderFileList(clientData.files || [], clientName);
        
        // Populate Photos
        renderPhotoGallery(clientData.photos || [], clientName);
    } catch (e) {
        showToast('خطا در دریافت مشخصات موکل', 'error');
    }
}

// Render files list for selected client
function renderFileList(files, clientName) {
    const fileListEl = document.getElementById('fileList');
    fileListEl.innerHTML = '';

    if (files.length === 0) {
        fileListEl.innerHTML = `
            <div class="loading-state" style="padding: 20px;">
                <span>هیچ فایلی در این پرونده موجود نیست</span>
            </div>
        `;
        return;
    }

    files.forEach(file => {
        const ext = file.name.split('.').pop().toLowerCase();
        let iconType = 'file';
        let iconClass = '';
        if (ext === 'pdf') {
            iconType = 'file-text';
            iconClass = 'pdf';
        } else if (ext === 'txt') {
            iconType = 'file-code';
            iconClass = 'txt';
        }

        const sizeKb = (file.size / 1024).toFixed(1) + ' KB';

        const li = document.createElement('li');
        li.className = 'file-item';
        li.innerHTML = `
            <div class="file-details">
                <div class="file-icon ${iconClass}">
                    <i data-lucide="${iconType}"></i>
                </div>
                <div class="file-name-wrapper">
                    <span class="name" title="${file.name}">${file.name}</span>
                    <span class="size">${sizeKb}</span>
                </div>
            </div>
            <div class="file-actions">
                <button class="file-btn view" title="مشاهده پیش‌نمایش">
                    <i data-lucide="eye"></i>
                </button>
                <a href="/api/clients/${encodeURIComponent(clientName)}/files/${encodeURIComponent(file.name)}?download=true" class="file-btn download" title="دانلود فایل">
                    <i data-lucide="download"></i>
                </a>
                <button class="file-btn delete" title="حذف فایل">
                    <i data-lucide="trash-2"></i>
                </button>
            </div>
        `;

        // Action events
        li.querySelector('.view').addEventListener('click', () => previewFile(clientName, file.name));
        li.querySelector('.delete').addEventListener('click', () => deleteFile(clientName, file.name));

        fileListEl.appendChild(li);
    });

    if (window.lucide) window.lucide.createIcons();
}

// renderParvandeBadges is kept as a no-op since the badge section was unified
// into the editable shomare_parvande input field
function renderParvandeBadges(csvValue) {
    // No-op: the parvande section is now the editable field_shomare_parvande input
}

// Add a custom key-value metadata row in the form
function addCustomFieldRow(label = '', value = '') {
    const container = document.getElementById('customFieldsContainer');
    const row = document.createElement('div');
    row.className = 'custom-field-row';
    row.innerHTML = `
        <input type="text" placeholder="برچسب فیلد (مثال: شعبه دادگاه)" class="custom-label" value="${label}" required>
        <input type="text" placeholder="مقدار فیلد" class="custom-value" value="${value}">
        <button type="button" class="delete-field-btn" title="حذف فیلد">
            <i data-lucide="minus-circle"></i>
        </button>
    `;
    
    row.querySelector('.delete-field-btn').addEventListener('click', () => {
        row.remove();
    });

    container.appendChild(row);
    if (window.lucide) window.lucide.createIcons();
}

// Preview PDF or Text File
function previewFile(clientName, fileName) {
    const previewPane = document.getElementById('previewPane');
    const previewFileName = document.getElementById('previewFileName');
    const previewBody = document.getElementById('previewBody');

    previewFileName.innerText = fileName;
    previewPane.style.display = 'flex';

    const fileUrl = `/api/clients/${encodeURIComponent(clientName)}/files/${encodeURIComponent(fileName)}`;
    const ext = fileName.split('.').pop().toLowerCase();

    if (ext === 'pdf') {
        // Embed PDF using standard browser capability
        previewBody.innerHTML = `<iframe src="${fileUrl}"></iframe>`;
    } else if (['png', 'jpg', 'jpeg'].includes(ext)) {
        previewBody.innerHTML = `<div class="image-preview-container"><img src="${fileUrl}" alt="${fileName}" class="preview-image"></div>`;
    } else if (ext === 'txt') {
        previewBody.innerHTML = `<div class="loading-state"><div class="spinner"></div></div>`;
        fetch(fileUrl)
            .then(res => {
                if (!res.ok) throw new Error();
                return res.text();
            })
            .then(text => {
                previewBody.innerHTML = `<pre class="text-viewer">${escapeHTML(text)}</pre>`;
            })
            .catch(() => {
                previewBody.innerHTML = `<div class="loading-state"><span>خطا در بارگذاری محتوای متنی</span></div>`;
            });
    } else {
        previewBody.innerHTML = `
            <div class="loading-state">
                <i data-lucide="eye-off"></i>
                <span>پیش‌نمایش برای این نوع فایل پشتیبانی نمی‌شود</span>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
    }
}

// Close preview pane
function closePreview() {
    document.getElementById('previewPane').style.display = 'none';
    document.getElementById('previewBody').innerHTML = '';
}

// Save Metadata to مشخصات موکل.txt
async function saveMetadata(e) {
    e.preventDefault();
    if (!activeClientName) return;

    // Gather standard fields
    const metadata = {};
    const inputs = document.querySelectorAll('#metadataForm input[data-key]');
    inputs.forEach(input => {
        const key = input.getAttribute('data-key');
        if (input.value.trim() !== '') {
            metadata[key] = input.value.trim();
        }
    });

    // Gather custom fields
    const customRows = document.querySelectorAll('.custom-field-row');
    customRows.forEach(row => {
        const label = row.querySelector('.custom-label').value.trim();
        const val = row.querySelector('.custom-value').value.trim();
        if (label !== '' && val !== '') {
            metadata[label] = val;
        }
    });

    try {
        await apiRequest(`/api/clients/${encodeURIComponent(activeClientName)}/save-info`, 'POST', metadata);
        showToast('مشخصات موکل با موفقیت ذخیره شد', 'success');
        // Refresh client list meta in sidebar
        await fetchClients();
    } catch (e) {
        // Error toast handled by apiRequest
    }
}

// Delete file inside a client folder
async function deleteFile(clientName, fileName) {
    if (!confirm(`آیا از حذف فایل "${fileName}" اطمینان دارید؟ این عمل غیرقابل بازگشت است.`)) {
        return;
    }

    try {
        await apiRequest(`/api/clients/${encodeURIComponent(clientName)}/files/${encodeURIComponent(fileName)}`, 'DELETE');
        showToast('فایل با موفقیت حذف شد', 'success');
        
        // Close preview if we just deleted the previewed file
        const currentPreview = document.getElementById('previewFileName').innerText;
        if (currentPreview === fileName) {
            closePreview();
        }

        // Reload active client view
        selectClient(clientName);
    } catch (e) {}
}

// Upload file to active client folder
async function uploadToClient(files) {
    if (!activeClientName || files.length === 0) return;

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) {
        formData.append('files', files[i]);
    }

    showToast('در حال بارگذاری فایل‌ها...', 'info');
    try {
        await apiRequest(`/api/clients/${encodeURIComponent(activeClientName)}/upload`, 'POST', formData, true);
        showToast('فایل‌ها با موفقیت اضافه شدند', 'success');
        selectClient(activeClientName);
    } catch (e) {}
}

// General PDF processing drag & drop
async function processPDFs(files) {
    if (files.length === 0) return;

    // Filter only PDF files
    const pdfFiles = Array.from(files).filter(file => file.name.toLowerCase().endsWith('.pdf'));
    if (pdfFiles.length === 0) {
        showToast('لطفاً فقط فایل PDF انتخاب کنید', 'error');
        return;
    }

    // Process one by one
    for (let file of pdfFiles) {
        const formData = new FormData();
        formData.append('file', file);
        
        showToast(`در حال پردازش سند: ${file.name}...`, 'info');
        
        try {
            const result = await apiRequest('/api/process-pdf', 'POST', formData, true);
            
            // Reload workspace
            await fetchClients();
            
            if (result.matched === false) {
                showToast(result.message || 'سند غیرمرتبط شناسایی شد.', 'info');
                openAssociationModal(result.filename || file.name);
            } else {
                showToast(result.message, result.success ? 'success' : 'error');
                
                // If auto-matched by case number, show top-right action notification
                if (result.auto_matched_by_case) {
                    showActionNotification(result.filename || file.name, result.folder_name);
                }
                
                // If successfully processed, select this client
                if (result.success && result.folder_name) {
                    selectClient(result.folder_name);
                }
            }
        } catch (e) {
            // Error toast handled by apiRequest
        }
    }
}

// Update single client from files
async function updateClientFromFiles() {
    if (!activeClientName) return;
    
    showToast('در حال بررسی فایل‌ها و به‌روزرسانی اطلاعات...', 'info');
    try {
        const result = await apiRequest(`/api/clients/${encodeURIComponent(activeClientName)}/update-from-files`, 'POST');
        if (result.updated) {
            showToast(result.message, 'success');
            await fetchClients();
            selectClient(activeClientName);
        } else {
            showToast('اطلاعات جدیدی یافت نشد.', 'info');
        }
    } catch (e) {}
}

// Update all clients from files
async function updateAllClients() {
    if (!confirm('آیا مایل به بررسی مجدد تمامی فایل‌های موکلین و به‌روزرسانی اطلاعات هستید؟ این عملیات ممکن است زمان‌بر باشد.')) {
        return;
    }
    showToast('در حال بررسی تمامی پرونده‌ها... لطفاً شکیبا باشید.', 'info');
    try {
        const result = await apiRequest(`/api/clients/update-all-from-files`, 'POST');
        showToast(result.message, 'success');
        await fetchClients();
        if (activeClientName) {
            selectClient(activeClientName);
        }
    } catch (e) {}
}

// Rename client folder
async function renameClient() {
    if (!activeClientName) return;
    
    const newName = prompt('نام جدید پوشه را وارد کنید:', activeClientName);
    if (!newName || newName.trim() === '' || newName === activeClientName) return;

    try {
        const result = await apiRequest(`/api/clients/${encodeURIComponent(activeClientName)}/rename`, 'POST', { new_name: newName.trim() });
        showToast('نام پوشه با موفقیت تغییر کرد', 'success');
        activeClientName = result.new_name;
        await fetchClients();
        selectClient(activeClientName);
    } catch (e) {}
}

// Delete client folder
async function deleteClient() {
    if (!activeClientName) return;

    if (!confirm(`آیا از حذف کامل پوشه پرونده "${activeClientName}" و تمامی اسناد آن اطمینان دارید؟\nاین عمل پرونده را به صورت فیزیکی از روی دیسک کامپیوتر حذف می‌کند و غیرقابل بازگشت است.`)) {
        return;
    }

    try {
        await apiRequest(`/api/clients/${encodeURIComponent(activeClientName)}`, 'DELETE');
        showToast('پرونده موکل با موفقیت حذف شد', 'success');
        
        // Reset state
        activeClientName = null;
        closePreview();
        document.getElementById('clientDashboard').style.display = 'none';
        document.getElementById('emptyState').style.display = 'flex';
        
        await fetchClients();
    } catch (e) {}
}

// Create Manual Client
async function handleNewClientSubmit(e) {
    e.preventDefault();
    
    const first_name = document.getElementById('new_first_name').value.trim();
    const last_name = document.getElementById('new_last_name').value.trim();
    
    const metadata = {
        first_name,
        last_name,
        id_number: document.getElementById('new_id_number').value.trim(),
        fathername: document.getElementById('new_fathername').value.trim(),
        client_number: document.getElementById('new_client_number').value.trim(),
        contract_date: document.getElementById('new_contract_date').value.trim(),
        contract_amount: document.getElementById('new_contract_amount').value.trim()
    };

    try {
        const result = await apiRequest('/api/clients/create', 'POST', metadata);
        showToast(result.message, 'success');
        
        // Close modal
        closeAllModals();
        
        // Reload list and select new client
        await fetchClients();
        selectClient(result.folder_name);
        
        // Reset form
        document.getElementById('newClientForm').reset();
    } catch (e) {}
}

// Set up UI Event Listeners
function setupEventListeners() {
    // Refresh button
    document.getElementById('refreshWorkspaceBtn').addEventListener('click', loadWorkspaceConfig);

    // Search Box Filtering (with Persian normalization)
    document.getElementById('searchClientInput').addEventListener('input', (e) => {
        const rawQuery = e.target.value.trim();
        if (rawQuery === '') {
            renderClientList(clientsList);
        } else {
            const query = normalizePersian(rawQuery).toLowerCase();
            const filtered = clientsList.filter(client => {
                const normalizedName = normalizePersian(client.name).toLowerCase();
                const nameMatch = normalizedName.includes(query);
                const idMatch = client.metadata && client.metadata.id_number && normalizePersian(client.metadata.id_number).includes(query);
                const clientNumMatch = client.metadata && client.metadata.client_number && normalizePersian(client.metadata.client_number).includes(query);
                const parvandeMatch = client.metadata && client.metadata.shomare_parvande && client.metadata.shomare_parvande.includes(query);
                return nameMatch || idMatch || clientNumMatch || parvandeMatch;
            });
            renderClientList(filtered);
        }
    });

    // Workspace change triggers modal
    document.getElementById('changeWorkspaceBtn').addEventListener('click', () => {
        openModal('workspaceModal');
    });
    document.getElementById('workspacePathInput').addEventListener('click', () => {
        openModal('workspaceModal');
    });

    // Save workspace button
    document.getElementById('saveWorkspaceBtn').addEventListener('click', async () => {
        const newPath = document.getElementById('workspacePathModalInput').value.trim();
        if (newPath === '') return;

        try {
            await apiRequest('/api/config', 'POST', { workspace_path: newPath });
            showToast('مسیر پوشه کاری ذخیره شد', 'success');
            closeAllModals();
            loadWorkspaceConfig();
        } catch (e) {}
    });

    // New Client manual modal triggers
    document.getElementById('newClientBtn').addEventListener('click', () => {
        openModal('newClientModal');
    });

    document.getElementById('updateAllClientsBtn').addEventListener('click', updateAllClients);

    document.getElementById('newClientForm').addEventListener('submit', handleNewClientSubmit);

    // Smart Assistant Toggle
    const smartAssistantBtn = document.getElementById('smartAssistantBtn');
    const smartAssistantMenu = document.getElementById('smartAssistantMenu');
    if (smartAssistantBtn && smartAssistantMenu) {
        smartAssistantBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            smartAssistantMenu.style.display = smartAssistantMenu.style.display === 'none' ? 'block' : 'none';
        });
        
        // Hide menu when clicking outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.smart-assistant-container')) {
                smartAssistantMenu.style.display = 'none';
            }
        });
    }

    // Auto Download Contracts action
    const autoDownloadBtn = document.getElementById('autoDownloadContractsBtn');
    const cancelAutomationBtn = document.getElementById('cancelAutomationBtn');
    
    async function runAutomation() {
        showToast('در حال شروع اتوماسیون هوشمند... لطفاً مرورگر باز شده را نبندید.', 'info');
        if(cancelAutomationBtn) cancelAutomationBtn.style.display = 'flex';
        
        try {
            const result = await apiRequest('/api/automation/auto-contract', 'POST');
            showToast(result.message, result.success ? 'success' : 'error');
            await fetchClients();
        } catch (error) {
            showToast('خطا در اجرای اتوماسیون', 'error');
        } finally {
            if(cancelAutomationBtn) cancelAutomationBtn.style.display = 'none';
            window._pendingAutomation = false;
        }
    }

    if (autoDownloadBtn) {
        autoDownloadBtn.addEventListener('click', async () => {
            smartAssistantMenu.style.display = 'none';
            try {
                const settings = await apiRequest('/api/automation/settings', 'GET');
                if (!settings.national_code || !settings.password) {
                    const sanaNationalCodeInput = document.getElementById('sanaNationalCode');
                    const sanaPasswordInput = document.getElementById('sanaPassword');
                    if (sanaNationalCodeInput) sanaNationalCodeInput.value = '';
                    if (sanaPasswordInput) sanaPasswordInput.value = '';
                    openModal('sanaSettingsModal');
                    window._pendingAutomation = true;
                    return;
                }
                
                await runAutomation();
            } catch (error) {
                showToast('خطا در بررسی تنظیمات', 'error');
            }
        });
    }

    // Document Downloader action
    const downloadClientDocsBtn = document.getElementById('downloadClientDocsBtn');
    let pollingInterval = null;

    if (downloadClientDocsBtn) {
        downloadClientDocsBtn.addEventListener('click', async () => {
            const nationalId = document.getElementById('field_id_number').value.trim();
            const contractDate = document.getElementById('field_contract_date').value.trim();

            if (!nationalId || !contractDate) {
                showToast('خطا: شماره ملی یا تاریخ قرارداد موکل در مشخصات موجود نیست. ابتدا آن‌ها را وارد کنید.', 'error');
                return;
            }

            try {
                showToast('در حال شروع عملیات دریافت لوایح...', 'info');
                const result = await apiRequest('/api/automation/document-downloader/start', 'POST', {
                    client_id: activeClientName,
                    national_id: nationalId,
                    contract_date: contractDate
                });

                if (result.success) {
                    if (cancelAutomationBtn) cancelAutomationBtn.style.display = 'flex';
                    startPollingDownloaderStatus();
                } else {
                    showToast(result.message, 'error');
                }
            } catch (e) {
                showToast('خطا در شروع عملیات', 'error');
            }
        });
    }

    function startPollingDownloaderStatus() {
        if (pollingInterval) clearInterval(pollingInterval);
        pollingInterval = setInterval(async () => {
            try {
                const statusData = await apiRequest('/api/automation/document-downloader/status', 'GET');
                if (statusData.status === 'RUNNING') {
                    if (cancelAutomationBtn) cancelAutomationBtn.style.display = 'flex';
                    // We can log the status message if we had a dedicated progress UI
                } else if (statusData.status === 'ERROR' || statusData.status === 'NONE') {
                    clearInterval(pollingInterval);
                    if (statusData.status !== 'NONE') {
                        showToast(statusData.message, 'error');
                    }
                    if (cancelAutomationBtn) cancelAutomationBtn.style.display = 'none';
                    await fetchClients();
                    selectClient(activeClientName);
                } else if (statusData.status === 'DONE') {
                    clearInterval(pollingInterval);
                    if (cancelAutomationBtn) cancelAutomationBtn.style.display = 'none';
                    showToast(statusData.message, 'success');
                    await fetchClients();
                    selectClient(activeClientName);
                }
            } catch (e) {
                console.error("Status check failed", e);
            }
        }, 3000);
    }

    if (cancelAutomationBtn) {
        cancelAutomationBtn.addEventListener('click', async () => {
            try {
                cancelAutomationBtn.innerHTML = '<i data-lucide="loader" class="spin"></i><span>در حال توقف...</span>';
                if (window.lucide) window.lucide.createIcons();
                
                const result = await apiRequest('/api/automation/cancel', 'POST');
                showToast(result.message, result.success ? 'success' : 'error');
            } catch (error) {
                showToast('خطا در توقف اتوماسیون', 'error');
            } finally {
                cancelAutomationBtn.innerHTML = '<i data-lucide="stop-circle"></i><span>متوقف کردن اتوماسیون</span>';
                if (window.lucide) window.lucide.createIcons();
            }
        });
    }

    // Automation Settings Modal
    const automationSettingsBtn = document.getElementById('automationSettingsBtn');
    const sanaSettingsModal = document.getElementById('sanaSettingsModal');
    const saveSanaSettingsBtn = document.getElementById('saveSanaSettingsBtn');
    const skipSanaSettingsBtn = document.getElementById('skipSanaSettingsBtn');
    const sanaNationalCodeInput = document.getElementById('sanaNationalCode');
    const sanaPasswordInput = document.getElementById('sanaPassword');

    if (automationSettingsBtn && sanaSettingsModal) {
        automationSettingsBtn.addEventListener('click', async () => {
            try {
                const settings = await apiRequest('/api/automation/settings', 'GET');
                sanaNationalCodeInput.value = settings.national_code || '';
                sanaPasswordInput.value = settings.password || '';
                openModal('sanaSettingsModal');
                window._pendingAutomation = false; // Just opening settings
            } catch (e) {
                showToast('خطا در دریافت تنظیمات ثنا', 'error');
            }
        });
    }

    if (skipSanaSettingsBtn) {
        skipSanaSettingsBtn.addEventListener('click', () => {
            closeAllModals();
            if (window._pendingAutomation) {
                runAutomation();
            }
        });
    }

    if (saveSanaSettingsBtn) {
        saveSanaSettingsBtn.addEventListener('click', async () => {
            const data = {
                national_code: sanaNationalCodeInput.value.trim(),
                password: sanaPasswordInput.value.trim()
            };
            try {
                const result = await apiRequest('/api/automation/settings', 'POST', data);
                if (result.success) {
                    showToast(result.message, 'success');
                    closeAllModals();
                    if (window._pendingAutomation) {
                        runAutomation();
                    }
                }
            } catch (error) {
                showToast('خطا در ذخیره تنظیمات ثنا', 'error');
            }
        });
    }

    // Metadata Save submit
    document.getElementById('metadataForm').addEventListener('submit', saveMetadata);

    // Metadata Custom field button
    document.getElementById('addCustomFieldBtn').addEventListener('click', () => {
        addCustomFieldRow();
    });

    // Client Dashboard buttons
    document.getElementById('updateClientFilesBtn').addEventListener('click', updateClientFromFiles);
    document.getElementById('renameClientBtn').addEventListener('click', renameClient);
    document.getElementById('deleteClientBtn').addEventListener('click', deleteClient);

    // Photos panel toggle (collapsible)
    document.getElementById('photosToggleBtn').addEventListener('click', () => {
        const body = document.getElementById('photosCollapsible');
        const icon = document.getElementById('photosToggleIcon');
        const isOpen = body.style.display !== 'none';
        body.style.display = isOpen ? 'none' : 'block';
        icon.style.transform = isOpen ? '' : 'rotate(180deg)';
    });

    // Close preview button
    document.getElementById('closePreviewBtn').addEventListener('click', closePreview);

    // Close Modals buttons
    document.querySelectorAll('.close-modal-btn').forEach(btn => {
        btn.addEventListener('click', closeAllModals);
    });

    // Association Modal Search Filtering
    document.getElementById('searchAssocClientInput').addEventListener('input', (e) => {
        const rawQuery = e.target.value.trim();
        if (rawQuery === '') {
            renderAssocClientsList(clientsList);
        } else {
            const query = normalizePersian(rawQuery).toLowerCase();
            const filtered = clientsList.filter(client => {
                const normalizedName = normalizePersian(client.name).toLowerCase();
                const nameMatch = normalizedName.includes(query);
                const idMatch = client.metadata && client.metadata.id_number && normalizePersian(client.metadata.id_number).includes(query);
                const clientNumMatch = client.metadata && client.metadata.client_number && normalizePersian(client.metadata.client_number).includes(query);
                const parvandeMatch = client.metadata && client.metadata.shomare_parvande && client.metadata.shomare_parvande.includes(query);
                return nameMatch || idMatch || clientNumMatch || parvandeMatch;
            });
            renderAssocClientsList(filtered);
        }
    });

    // Association Modal Confirm button
    document.getElementById('confirmAssocBtn').addEventListener('click', async () => {
        if (!pendingAssocFilename || !selectedAssocClient) return;
        
        try {
            const response = await apiRequest('/api/associate-pending', 'POST', {
                filename: pendingAssocFilename,
                client_folder: selectedAssocClient,
                source_folder: associationSourceFolder
            });
            
            showToast(response.message, 'success');
            closeAllModals();
            
            // Reload client list and select associated client
            await fetchClients();
            selectClient(selectedAssocClient);
        } catch (e) {
            // Error already toasted by apiRequest
        }
    });

    // Go Home button click
    document.getElementById('goHomeBtn').addEventListener('click', goHome);

    // Setup drag and drop for global dropzone
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('pdfFileInput');

    dropZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => processPDFs(e.target.files));

    setupDragDropEvents(dropZone, (files) => processPDFs(files));

    // Setup drag and drop for client-specific dropzone
    const clientDropZone = document.getElementById('clientDropZone');
    const clientFileInput = document.getElementById('clientFileInput');

    clientDropZone.addEventListener('click', () => clientFileInput.click());
    clientFileInput.addEventListener('change', (e) => uploadToClient(e.target.files));

    setupDragDropEvents(clientDropZone, (files) => uploadToClient(files));

    // Setup drag and drop for photo dropzone
    const photoDropZone = document.getElementById('photoDropZone');
    const photoFileInput = document.getElementById('photoFileInput');

    photoDropZone.addEventListener('click', () => photoFileInput.click());
    photoFileInput.addEventListener('change', (e) => uploadPhotos(e.target.files));

    setupDragDropEvents(photoDropZone, (files) => uploadPhotos(files));
}

// Drag & Drop event bindings helper
function setupDragDropEvents(element, onDropCallback) {
    ['dragenter', 'dragover'].forEach(eventName => {
        element.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            element.classList.add('dragover');
        }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
        element.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            element.classList.remove('dragover');
        }, false);
    });

    element.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        onDropCallback(files);
    }, false);
}

// Modal actions
function openModal(modalId) {
    document.getElementById(modalId).style.display = 'flex';
}

function closeAllModals() {
    document.querySelectorAll('.modal-overlay').forEach(el => {
        el.style.display = 'none';
    });
}

// Toast Helper
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = 'info';
    if (type === 'success') icon = 'check-circle';
    if (type === 'error') icon = 'alert-triangle';

    toast.innerHTML = `
        <i data-lucide="${icon}"></i>
        <span>${message}</span>
    `;

    container.appendChild(toast);
    if (window.lucide) window.lucide.createIcons();

    // Auto-remove toast
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

// Render photo gallery for selected client
function renderPhotoGallery(photos, clientName) {
    const galleryEl = document.getElementById('photosGallery');
    galleryEl.innerHTML = '';

    // Update badge count
    document.getElementById('photosCountBadge').innerText = photos.length;

    if (photos.length === 0) {
        galleryEl.innerHTML = `
            <div class="loading-state" style="padding: 20px;">
                <i data-lucide="image-off"></i>
                <span>هیچ عکسی در این پرونده موجود نیست</span>
            </div>
        `;
        if (window.lucide) window.lucide.createIcons();
        return;
    }

    photos.forEach(photo => {
        const photoUrl = `/api/clients/${encodeURIComponent(clientName)}/photos/${encodeURIComponent(photo.name)}`;
        const div = document.createElement('div');
        div.className = 'photo-thumb';
        div.innerHTML = `
            <img src="${photoUrl}" alt="${photo.name}" loading="lazy">
            <div class="photo-overlay">
                <span class="photo-name" title="${photo.name}">${photo.name}</span>
                <div class="photo-actions">
                    <button class="photo-btn view" title="مشاهده">
                        <i data-lucide="maximize-2"></i>
                    </button>
                    <button class="photo-btn delete" title="حذف">
                        <i data-lucide="trash-2"></i>
                    </button>
                </div>
            </div>
        `;

        div.querySelector('.view').addEventListener('click', () => previewPhoto(clientName, photo.name));
        div.querySelector('.delete').addEventListener('click', () => deletePhoto(clientName, photo.name));

        galleryEl.appendChild(div);
    });

    if (window.lucide) window.lucide.createIcons();
}

// Preview a photo in the preview pane
function previewPhoto(clientName, fileName) {
    const previewPane = document.getElementById('previewPane');
    const previewFileName = document.getElementById('previewFileName');
    const previewBody = document.getElementById('previewBody');

    previewFileName.innerText = fileName;
    previewPane.style.display = 'flex';

    const photoUrl = `/api/clients/${encodeURIComponent(clientName)}/photos/${encodeURIComponent(fileName)}`;
    previewBody.innerHTML = `<div class="image-preview-container"><img src="${photoUrl}" alt="${fileName}" class="preview-image"></div>`;
}

// Upload photos to client's عکس folder
async function uploadPhotos(files) {
    if (!activeClientName || files.length === 0) return;

    const formData = new FormData();
    let hasValid = false;
    for (let i = 0; i < files.length; i++) {
        const ext = files[i].name.split('.').pop().toLowerCase();
        if (['png', 'jpg', 'jpeg'].includes(ext)) {
            formData.append('files', files[i]);
            hasValid = true;
        }
    }

    if (!hasValid) {
        showToast('لطفاً فقط فایل‌های PNG یا JPG انتخاب کنید', 'error');
        return;
    }

    showToast('در حال بارگذاری عکس‌ها...', 'info');
    try {
        await apiRequest(`/api/clients/${encodeURIComponent(activeClientName)}/upload-photo`, 'POST', formData, true);
        showToast('عکس‌ها با موفقیت اضافه شدند', 'success');
        selectClient(activeClientName);
    } catch (e) {}
}

// Delete a photo from client's عکس folder
async function deletePhoto(clientName, fileName) {
    if (!confirm(`آیا از حذف عکس "${fileName}" اطمینان دارید؟`)) {
        return;
    }

    try {
        await apiRequest(`/api/clients/${encodeURIComponent(clientName)}/photos/${encodeURIComponent(fileName)}`, 'DELETE');
        showToast('عکس با موفقیت حذف شد', 'success');
        
        // Close preview if we just deleted the previewed photo
        const currentPreview = document.getElementById('previewFileName').innerText;
        if (currentPreview === fileName) {
            closePreview();
        }

        selectClient(clientName);
    } catch (e) {}
}

// HTML Escape Helper
function escapeHTML(str) {
    return str.replace(/[&<>'"]/g, 
        tag => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        }[tag] || tag)
    );
}

// Open Manual Association Modal
function openAssociationModal(filename, sourceFolder = null) {
    pendingAssocFilename = filename;
    selectedAssocClient = null;
    associationSourceFolder = sourceFolder;
    
    // Set file name in modal
    document.getElementById('assocFileName').innerText = filename;
    
    // Reset selection input and confirm button
    document.getElementById('searchAssocClientInput').value = '';
    document.getElementById('confirmAssocBtn').disabled = true;
    
    // Populate client list
    renderAssocClientsList(clientsList);
    
    // Display modal overlay
    openModal('associationModal');
}

// Go to home screen view
function goHome() {
    activeClientName = null;
    document.querySelectorAll('.client-item').forEach(el => {
        el.classList.remove('active');
    });
    document.getElementById('clientDashboard').style.display = 'none';
    document.getElementById('emptyState').style.display = 'flex';
    closePreview();
}

// Show Action Notification at Top Right for Auto-Associated documents
function showActionNotification(filename, clientName) {
    const container = document.getElementById('topRightNotificationContainer');
    if (!container) return;
    
    const notification = document.createElement('div');
    notification.className = 'action-notification';
    const notificationId = `assoc_notif_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    notification.id = notificationId;
    
    notification.innerHTML = `
        <div class="action-notification-text">
            سند <strong>"${escapeHTML(filename)}"</strong> به صورت خودکار به پرونده <strong>"${escapeHTML(clientName)}"</strong> متصل شد.
        </div>
        <div class="action-notification-actions">
            <button class="action-notification-btn cancel">لغو</button>
            <button class="action-notification-btn change">تغییر پرونده</button>
        </div>
    `;
    
    // Wire up events
    notification.querySelector('.cancel').addEventListener('click', async () => {
        showToast('در حال لغو عملیات...', 'info');
        try {
            await apiRequest('/api/cancel-association', 'POST', {
                filename: filename,
                client_folder: clientName
            });
            showToast('عملیات لغو شد و فایل حذف گردید', 'success');
            notification.remove();
            
            // Reload and navigate home
            await fetchClients();
            goHome();
        } catch (e) {
            // Error already handled
        }
    });
    
    notification.querySelector('.change').addEventListener('click', () => {
        notification.remove();
        openAssociationModal(filename, clientName);
    });
    
    container.appendChild(notification);
    
    // Auto-remove after 15 seconds
    setTimeout(() => {
        if (document.getElementById(notificationId)) {
            notification.remove();
        }
    }, 15000);
}

// Render clients list for association search
function renderAssocClientsList(list) {
    const listEl = document.getElementById('assocClientsList');
    listEl.innerHTML = '';
    
    if (list.length === 0) {
        listEl.innerHTML = `
            <div class="loading-state" style="padding: 20px;">
                <span>موکلی پیدا نشد</span>
            </div>
        `;
        return;
    }
    
    list.forEach(client => {
        const li = document.createElement('li');
        li.className = `assoc-client-item ${selectedAssocClient === client.name ? 'selected' : ''}`;
        li.dataset.name = client.name;
        
        let subtitle = 'بدون مشخصات';
        if (client.metadata && Object.keys(client.metadata).length > 0) {
            const parts = [];
            if (client.metadata.id_number) parts.push(`کد ملی: ${client.metadata.id_number}`);
            if (client.metadata.client_number) parts.push(`قرارداد: ${client.metadata.client_number}`);
            if (parts.length > 0) {
                subtitle = parts.join(' | ');
            }
        }
        
        li.innerHTML = `
            <div class="assoc-client-item-name">${client.name}</div>
            <div class="assoc-client-item-meta">${subtitle}</div>
        `;
        
        li.addEventListener('click', () => {
            // Remove previous selections
            document.querySelectorAll('.assoc-client-item').forEach(el => {
                el.classList.remove('selected');
            });
            
            // Add current selection
            li.classList.add('selected');
            selectedAssocClient = client.name;
            document.getElementById('confirmAssocBtn').disabled = false;
        });
        
        listEl.appendChild(li);
    });
}
