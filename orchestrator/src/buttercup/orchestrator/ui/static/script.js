// Global state
let tasks = [];
let allPovs = [];
let allPatches = [];
let dashboardStats = {
    activeTasks: 0,
    totalPovs: 0,
    totalPatches: 0,
    totalBundles: 0
};
let dashboardConfig = {
    crs_instance_id: null
};
let currentTab = 'tasks';

// API base URL - will be set dynamically
const API_BASE = '';

// DOM elements
const elements = {
    submitTaskBtn: document.getElementById('submit-task-btn'),
    submitExampleBtn: document.getElementById('submit-example-btn'),
    refreshBtn: document.getElementById('refresh-btn'),
    taskModal: document.getElementById('task-modal'),
    detailModal: document.getElementById('detail-modal'),
    taskModalContent: document.querySelector('#task-modal .modal-content'),
    detailModalContent: document.querySelector('#detail-modal .modal-content'),
    closeModal: document.getElementById('close-modal'),
    closeDetailModal: document.getElementById('close-detail-modal'),
    taskForm: document.getElementById('task-form'),
    cancelBtn: document.getElementById('cancel-btn'),
    tasksContainer: document.getElementById('tasks-container'),
    povsContainer: document.getElementById('povs-container'),
    patchesContainer: document.getElementById('patches-container'),
    statusFilter: document.getElementById('status-filter'),
    activeTasks: document.getElementById('active-tasks'),
    failedTasks: document.getElementById('failed-tasks'),
    totalPovs: document.getElementById('total-povs'),
    totalPatches: document.getElementById('total-patches'),
    totalBundles: document.getElementById('total-bundles'),
    detailTitle: document.getElementById('detail-title'),
    detailContent: document.getElementById('detail-content'),
    tabButtons: document.querySelectorAll('.tab-button'),
    tabPanes: document.querySelectorAll('.tab-pane'),
    notifications: document.getElementById('notifications')
};

// Initialize the dashboard
document.addEventListener('DOMContentLoaded', function() {
    // Preserve button widths to prevent size changes during refresh
    const buttons = ['refresh-btn', 'submit-task-btn', 'submit-example-btn'];
    buttons.forEach(id => {
        const button = document.getElementById(id);
        if (button) {
            button.style.width = button.offsetWidth + 'px';
        }
    });

    setupEventListeners();
    loadDashboard();

    // Set up auto-refresh every 5 seconds
    setInterval(loadDashboard, 5000);
});

// Event listeners
function setupEventListeners() {
    elements.submitTaskBtn.addEventListener('click', () => {
        elements.taskModal.style.display = 'block';
    });

    elements.submitExampleBtn.addEventListener('click', handleExampleTaskSubmission);

    elements.refreshBtn.addEventListener('click', loadDashboard);

    elements.closeModal.addEventListener('click', () => {
        elements.taskModal.style.display = 'none';
    });

    elements.closeDetailModal.addEventListener('click', () => {
        elements.detailModal.style.display = 'none';
    });

    elements.cancelBtn.addEventListener('click', () => {
        elements.taskModal.style.display = 'none';
    });

    elements.taskForm.addEventListener('submit', handleTaskSubmission);

    elements.statusFilter.addEventListener('change', filterTasks);

    // Tab navigation
    elements.tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const tabName = button.getAttribute('data-tab');
            switchTab(tabName);
        });
    });

    // Dashboard stat navigation
    elements.activeTasks.addEventListener('click', () => {
        switchTab('tasks');
    });

    elements.totalPovs.addEventListener('click', () => {
        switchTab('povs');
    });

    elements.totalPatches.addEventListener('click', () => {
        switchTab('patches');
    });

    // Close modals when clicking outside
    let mousePressedOutside = false;
    
    window.addEventListener('mousedown', (event) => {
        // Check if mouse was pressed outside both modal contents
        if (!elements.taskModalContent.contains(event.target) && !elements.detailModalContent.contains(event.target)) {
            mousePressedOutside = true;
        } else {
            mousePressedOutside = false;
        }
    });

    window.addEventListener('mouseup', (event) => {
        // Only close if mouse was pressed outside and released outside
        if (mousePressedOutside && !elements.taskModalContent.contains(event.target) && !elements.detailModalContent.contains(event.target)) {
            elements.taskModal.style.display = 'none';
            elements.detailModal.style.display = 'none';
        }
    });
}

// Tab switching
function switchTab(tabName) {
    currentTab = tabName;

    // Update tab buttons
    elements.tabButtons.forEach(button => {
        if (button.getAttribute('data-tab') === tabName) {
            button.classList.add('active');
        } else {
            button.classList.remove('active');
        }
    });

    // Update tab panes
    elements.tabPanes.forEach(pane => {
        if (pane.id === `${tabName}-tab`) {
            pane.classList.add('active');
        } else {
            pane.classList.remove('active');
        }
    });

    // Load content for the active tab
    if (tabName === 'povs') {
        loadAndRenderPovs();
    } else if (tabName === 'patches') {
        loadAndRenderPatches();
    }
}

// Load dashboard configuration
async function loadConfig() {
    try {
        const response = await fetch(`${API_BASE}/v1/dashboard/config`);
        if (response.ok) {
            dashboardConfig = await response.json();
            updatePageTitle();
        } else {
            console.warn('Config API not available');
        }
    } catch (error) {
        console.warn('Config API not available, using defaults');
    }
}

// Update page title with instance ID
function updatePageTitle() {
    const baseTitle = 'Buttercup CRS Dashboard';
    const navTitle = document.querySelector('.nav-title');
    const pageTitle = document.querySelector('title');

    if (dashboardConfig.crs_instance_id) {
        const newTitle = `${baseTitle} (${dashboardConfig.crs_instance_id})`;
        if (navTitle) navTitle.textContent = newTitle;
        if (pageTitle) pageTitle.textContent = newTitle;
    } else {
        if (navTitle) navTitle.textContent = baseTitle;
        if (pageTitle) pageTitle.textContent = baseTitle;
    }
}

// Load dashboard data
async function loadDashboard() {
    try {
        elements.refreshBtn.innerHTML = '<span class="spinner"></span>';

        // Load tasks, stats, and config in parallel
        await Promise.all([
            loadTasks(),
            loadStats(),
            loadAllPovs(),
            loadAllPatches(),
            loadConfig()
        ]);

        updateDashboard();

    } catch (error) {
        console.error('Error loading dashboard:', error);
        showNotification('Error loading dashboard data', 'error');
    } finally {
        elements.refreshBtn.innerHTML = 'Refresh';
    }
}

// Load tasks from API
async function loadTasks() {
    try {
        // Add timestamp to prevent caching
        const response = await fetch(`${API_BASE}/v1/dashboard/tasks?t=${Date.now()}`);
        if (response.ok) {
            tasks = await response.json();
        } else {
            // Fallback to mock data if API not available
            tasks = getMockTasks();
        }
    } catch (error) {
        console.warn('Tasks API not available, using mock data');
        tasks = getMockTasks();
    }
}

// Load dashboard stats
async function loadStats() {
    try {
        const response = await fetch(`${API_BASE}/v1/dashboard/stats`);
        if (response.ok) {
            dashboardStats = await response.json();
        } else {
            // Calculate stats from tasks
            calculateStatsFromTasks();
        }
    } catch (error) {
        console.warn('Stats API not available, calculating from tasks');
        calculateStatsFromTasks();
    }
}

// Load all PoVs from API
async function loadAllPovs() {
    try {
        const response = await fetch(`${API_BASE}/v1/dashboard/povs`);
        if (response.ok) {
            allPovs = await response.json();
        } else {
            // Fallback to extracting from tasks
            allPovs = extractPovsFromTasks();
        }
    } catch (error) {
        console.warn('PoVs API not available, extracting from tasks');
        allPovs = extractPovsFromTasks();
    }
}

// Load all patches from API
async function loadAllPatches() {
    try {
        const response = await fetch(`${API_BASE}/v1/dashboard/patches`);
        if (response.ok) {
            allPatches = await response.json();
        } else {
            // Fallback to extracting from tasks
            allPatches = extractPatchesFromTasks();
        }
    } catch (error) {
        console.warn('Patches API not available, extracting from tasks');
        allPatches = extractPatchesFromTasks();
    }
}

// Extract PoVs from tasks data
function extractPovsFromTasks() {
    const povs = [];
    tasks.forEach(task => {
        (task.povs || []).forEach(pov => {
            povs.push({
                task_id: task.task_id,
                task_name: task.name || task.project_name,
                pov: pov
            });
        });
    });
    return povs.sort((a, b) => new Date(b.pov.timestamp || 0) - new Date(a.pov.timestamp || 0));
}

// Extract patches from tasks data
function extractPatchesFromTasks() {
    const patches = [];
    tasks.forEach(task => {
        (task.patches || []).forEach(patch => {
            patches.push({
                task_id: task.task_id,
                task_name: task.name || task.project_name,
                patch: patch
            });
        });
    });
    return patches.sort((a, b) => new Date(b.patch.timestamp || 0) - new Date(a.patch.timestamp || 0));
}

// Calculate stats from tasks data
function calculateStatsFromTasks() {
    dashboardStats.activeTasks = tasks.filter(task => task.status === 'active').length;
    dashboardStats.totalPovs = tasks.reduce((sum, task) => sum + (task.povs || []).length, 0);
    dashboardStats.totalPatches = tasks.reduce((sum, task) => sum + (task.patches || []).length, 0);
    dashboardStats.totalBundles = tasks.reduce((sum, task) => sum + (task.bundles || []).length, 0);
}

// Update dashboard UI
function updateDashboard() {
    // Update stats
    elements.activeTasks.textContent = dashboardStats.activeTasks;
    elements.failedTasks.textContent = dashboardStats.failedTasks || 0;
    elements.totalPovs.textContent = dashboardStats.totalPovs;
    elements.totalPatches.textContent = dashboardStats.totalPatches;
    elements.totalBundles.textContent = dashboardStats.totalBundles;

    // Update current tab content
    if (currentTab === 'tasks') {
        renderTasks();
    } else if (currentTab === 'povs') {
        renderPovs();
    } else if (currentTab === 'patches') {
        renderPatches();
    }
}

// Load and render PoVs
async function loadAndRenderPovs() {
    await loadAllPovs();
    renderPovs();
}

// Load and render patches
async function loadAndRenderPatches() {
    await loadAllPatches();
    renderPatches();
}

// Render PoVs list
function renderPovs() {
    if (!elements.povsContainer) {
        console.error('PoVs container not found!');
        return;
    }
    
    if (allPovs.length === 0) {
        elements.povsContainer.innerHTML = `
            <div class="no-data">
                <div class="no-data-icon">🐛</div>
                <p>No PoVs found</p>
            </div>
        `;
        return;
    }

    elements.povsContainer.innerHTML = allPovs.map(item => `
        <div class="artifact-list-item" onclick="showArtifactDetail('pov', '${item.pov.pov_id}')">
            <div class="artifact-info">
                <div class="artifact-task-name">Task: ${item.task_name}</div>
                <div class="artifact-meta">
                    <span>ID: ${item.pov.pov_id}</span>
                    <span>Architecture: ${item.pov.architecture || 'N/A'}</span>
                    <span>Engine: ${item.pov.engine || 'N/A'}</span>
                </div>
                <div class="artifact-timestamp">${formatTimestamp(item.pov.timestamp)}</div>
            </div>
            <button class="download-button" onclick="event.stopPropagation(); downloadArtifact('pov', '${item.task_id}', '${item.pov.pov_id}')">
                Download
            </button>
        </div>
    `).join('');
}

// Render patches list
function renderPatches() {
    if (allPatches.length === 0) {
        elements.patchesContainer.innerHTML = `
            <div class="no-data">
                <div class="no-data-icon">🔧</div>
                <p>No patches found</p>
            </div>
        `;
        return;
    }

    elements.patchesContainer.innerHTML = allPatches.map(item => `
        <div class="artifact-list-item" onclick="showArtifactDetail('patch', '${item.patch.patch_id}')">
            <div class="artifact-info">
                <div class="artifact-task-name">Task: ${item.task_name}</div>
                <div class="artifact-meta">
                    <span>ID: ${item.patch.patch_id}</span>
                    <span>Size: ${(item.patch.patch || '').length} chars</span>
                </div>
                <div class="artifact-timestamp">${formatTimestamp(item.patch.timestamp)}</div>
            </div>
            <button class="download-button" onclick="event.stopPropagation(); downloadArtifact('patch', '${item.task_id}', '${item.patch.patch_id}')">
                Download
            </button>
        </div>
    `).join('');
}

// Render tasks list
function renderTasks() {
    if (!elements.tasksContainer) {
        console.error('Tasks container not found!');
        return;
    }
    
    const filteredTasks = filterTasksByStatus(tasks);
    
    if (filteredTasks.length === 0) {
        elements.tasksContainer.innerHTML = `
            <div class="no-data">
                <div class="no-data-icon">📝</div>
                <p>No tasks found</p>
                <p class="no-data-subtitle">Create a new task to get started</p>
            </div>
        `;
        return;
    }

    elements.tasksContainer.innerHTML = filteredTasks.map(task => `
        <div class="task-item ${task.crs_submission_status === 'failed' ? 'task-failed' : ''}" onclick="showTaskDetail('${task.task_id}')">
            <div class="task-info">
                <div class="task-name">${task.name || task.project_name}</div>
                <div class="task-id">ID: ${task.task_id}</div>
                <div class="task-meta">
                    <span>Project: ${task.project_name}</span>
                    <span>Duration: ${formatDuration(task.duration)}</span>
                    <span>Created: ${formatTimestamp(task.created_at)}</span>
                    <span>Deadline: ${formatTimestamp(task.deadline)}</span>
                </div>
                ${task.crs_submission_error ? `
                    <div class="crs-error-details">
                        <strong>Error:</strong> ${task.crs_submission_error}
                    </div>
                ` : ''}
            </div>
            <div class="task-status">
                <span class="status-badge status-${task.status}">${task.status}</span>
            </div>
            <div class="task-stats">
                <div class="stat-item">
                    <span>🐛</span>
                    <span>${(task.povs || []).length}</span>
                </div>
                <div class="stat-item">
                    <span>🔧</span>
                    <span>${(task.patches || []).length}</span>
                </div>
                <div class="stat-item">
                    <span>📦</span>
                    <span>${(task.bundles || []).length}</span>
                </div>
            </div>
        </div>
    `).join('');
}

// Filter tasks by status
function filterTasksByStatus() {
    const filter = elements.statusFilter.value;
    if (filter === 'all') {
        return tasks;
    }
    return tasks.filter(task => task.status === filter);
}

// Filter tasks when dropdown changes
function filterTasks() {
    renderTasks();
}

// Handle task submission
// Handle example task submission
async function handleExampleTaskSubmission() {
    const exampleTaskData = {
        challenge_repo_url: "https://github.com/tob-challenges/example-libpng",
        challenge_repo_base_ref: "5bf8da2d7953974e5dfbd778429c3affd461f51a",
        challenge_repo_head_ref: "challenges/lp-delta-01",
        fuzz_tooling_url: "https://github.com/google/oss-fuzz",
        fuzz_tooling_ref: "master",
        fuzz_tooling_project_name: "libpng",
        duration: 1800
    };

    // Get submit button and show loading state
    const submitBtn = elements.submitExampleBtn;
    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span> Submitting...';

    try {
        const response = await fetch(`${API_BASE}/webhook/trigger_task`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(exampleTaskData)
        });
        
        const result = await response.json();
        console.log('Example task submission response:', result);
        console.log('Response message:', result.message);
        console.log('Response color:', result.color);
        
        if (response.ok) {
            // Check if the response indicates a CRS submission failure or setup failure
            if (result.message && (result.message.includes('failed to submit to CRS') || result.message.includes('failed during setup'))) {
                console.log('Example task creation/submission failed, showing error notification');
                // Task was created but failed - show notification with proper color
                showNotification(result.message, null, result.color);
                
                // Force refresh failed tasks and main tasks list
                setTimeout(async () => {
                    await forceRefreshFailedTasks();
                }, 1000);
            } else {
                // Complete success
                showNotification(result.message || 'Example libpng task submitted successfully!', 'success');
                
                // Refresh dashboard after a short delay
                setTimeout(loadDashboard, 1000);
            }
        } else {
            const error = await response.json();
            showNotification(`Error: ${error.message || 'Failed to submit example task'}`, 'error');
        }
    } catch (error) {
        console.error('Error submitting example task:', error);
        showNotification('Network error occurred', 'error');
    } finally {
        // Restore button state
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
    }
}

async function handleTaskSubmission(event) {
    event.preventDefault();

    const formData = new FormData(elements.taskForm);
    const taskData = Object.fromEntries(formData.entries());

    // Convert checkbox and number values
    taskData.harnesses_included = formData.has('harnesses_included');
    taskData.duration = parseInt(taskData.duration);

    // Get submit button and show loading state
    const submitBtn = elements.taskForm.querySelector('button[type="submit"]');
    const originalText = submitBtn.textContent;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span> Submitting...';

    try {
        const response = await fetch(`${API_BASE}/webhook/trigger_task`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(taskData)
        });
        
        const result = await response.json();
        console.log('Task submission response:', result);
        console.log('Response message:', result.message);
        console.log('Response color:', result.color);
        
        if (response.ok) {
            // Check if the response indicates a CRS submission failure or setup failure
            if (result.message && (result.message.includes('failed to submit to CRS') || result.message.includes('failed during setup'))) {
                console.log('Task creation/submission failed, showing error notification');
                // Task was created but failed - show notification with proper color
                showNotification(result.message, null, result.color);
                elements.taskModal.style.display = 'none';
                elements.taskForm.reset();
                
                // Force refresh failed tasks and main tasks list
                setTimeout(async () => {
                    await forceRefreshFailedTasks();
                }, 1000);
            } else {
                // Complete success
                showNotification(result.message || 'Task submitted successfully!', 'success');
                elements.taskModal.style.display = 'none';
                elements.taskForm.reset();
                
                // Refresh dashboard after a short delay
                setTimeout(loadDashboard, 1000);
            }
        } else {
            // HTTP error - show error message
            const errorMessage = result.message || result.detail || 'Failed to submit task';
            showNotification(`Error: ${errorMessage}`, 'error');
        }
    } catch (error) {
        console.error('Error submitting task:', error);
        showNotification('Network error occurred', 'error');
    } finally {
        // Restore button state
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
    }
}

// Show task detail modal
async function showTaskDetail(taskId) {
    const task = tasks.find(t => t.task_id === taskId);
    if (!task) return;

    elements.detailTitle.textContent = `Task: ${task.name || task.project_name}`;

    // Try to load detailed data from API
    let detailData = task;
    try {
        const response = await fetch(`${API_BASE}/v1/dashboard/tasks/${taskId}`);
        if (response.ok) {
            detailData = await response.json();
        }
    } catch (error) {
        console.warn('Detail API not available, using cached data');
    }

    elements.detailContent.innerHTML = renderTaskDetail(detailData);
    elements.detailModal.style.display = 'block';
}

// Render task detail content
function renderTaskDetail(task) {
    return `
        <div style="padding: 1.5rem;">
            <div class="detail-section">
                <h3>Task Information</h3>
                <div class="detail-grid">
                    <div class="detail-label">Name:</div>
                    <div class="detail-value">${task.name || task.project_name}</div>
                    <div class="detail-label">ID:</div>
                    <div class="detail-value">${task.task_id}</div>
                    <div class="detail-label">Project:</div>
                    <div class="detail-value">${task.project_name}</div>
                    <div class="detail-label">Status:</div>
                    <div class="detail-value">
                        <span class="status-badge status-${task.status}">${task.status}</span>
                    </div>
                    <div class="detail-label">Created:</div>
                    <div class="detail-value">${formatTimestamp(task.created_at)}</div>
                    <div class="detail-label">Deadline:</div>
                    <div class="detail-value">${formatTimestamp(task.deadline)}</div>
                </div>
            </div>

            ${renderArtifacts('PoVs (Vulnerabilities)', task.povs || [], 'pov')}
            ${renderArtifacts('Patches', task.patches || [], 'patch')}
            ${renderArtifacts('Bundles', task.bundles || [], 'bundle')}
        </div>
    `;
}

// Render artifacts section
function renderArtifacts(title, artifacts, type) {
    if (artifacts.length === 0) {
        return `
            <div class="detail-section">
                <h3>${title} (0)</h3>
                <div class="no-data">
                    <p>No ${title.toLowerCase()} found</p>
                </div>
            </div>
        `;
    }

    return `
        <div class="detail-section">
            <h3>${title} (${artifacts.length})</h3>
            <div class="artifacts-list">
                ${artifacts.map(artifact => renderArtifact(artifact, type)).join('')}
            </div>
        </div>
    `;
}

// Render individual artifact
function renderArtifact(artifact, type) {
    let content = '';
    let artifactId = artifact.id || artifact.bundle_id || artifact.pov_id || artifact.patch_id;
    let taskId = ''; // We'll need to find this from the current task context

    // Find task ID for download button
    const currentTask = tasks.find(t =>
        (t.povs && t.povs.some(p => p.pov_id === artifactId)) ||
        (t.patches && t.patches.some(p => p.patch_id === artifactId)) ||
        (t.bundles && t.bundles.some(b => b.bundle_id === artifactId))
    );
    if (currentTask) {
        taskId = currentTask.task_id;
    }

    switch (type) {
        case 'pov':
            // Handle binary PoV data safely - show hexdump preview
            if (artifact.testcase) {
                if (typeof artifact.testcase === 'string') {
                    try {
                        // Try to decode base64 and create hexdump
                        const decoded = atob(artifact.testcase);
                        const hexPreview = createHexdumpPreview(decoded, 128); // First 128 bytes
                        content = `<div class="artifact-content">Type: Binary Data\nSize: ${decoded.length} bytes\nHex Preview:\n<pre class="hex-preview">${hexPreview}</pre></div>`;
                    } catch (e) {
                        // Not base64, show as text preview
                        const preview = artifact.testcase.length > 200
                            ? artifact.testcase.substring(0, 200) + '...'
                            : artifact.testcase;
                        content = `<div class="artifact-content">Type: Text Data\nSize: ${artifact.testcase.length} bytes\nPreview: ${preview}</div>`;
                    }
                } else {
                    content = `<div class="artifact-content">Type: Binary Data\nSize: ${JSON.stringify(artifact.testcase).length} bytes</div>`;
                }
            }
            break;
        case 'patch':
            // Decode patch content if it's base64
            let patchContent = artifact.patch || 'No patch content';
            if (typeof patchContent === 'string' && patchContent.length > 0) {
                try {
                    // Check if it looks like base64
                    if (patchContent.match(/^[A-Za-z0-9+/]+={0,2}$/)) {
                        patchContent = atob(patchContent);
                    }
                } catch (e) {
                    // Not base64, use as is
                }
            }
            const patchPreview = patchContent.length > 300
                ? patchContent.substring(0, 300) + '...'
                : patchContent;
            content = `<div class="artifact-content"><pre class="patch-preview">${patchPreview}</pre></div>`;
            break;
        case 'bundle':
            content = `<div class="artifact-content">${JSON.stringify(artifact, null, 2)}</div>`;
            break;
    }

    return `
        <div class="artifact-item" onclick="showArtifactDetail('${type}', '${artifactId}')">
            <div class="artifact-header">
                <div class="artifact-id">${artifactId}</div>
                <div class="artifact-timestamp">${formatTimestamp(artifact.timestamp || new Date().toISOString())}</div>
                ${taskId ? `<button class="download-button" onclick="event.stopPropagation(); downloadArtifact('${type}', '${taskId}', '${artifactId}')">Download</button>` : ''}
            </div>
            ${content}
        </div>
    `;
}

// Download artifact
async function downloadArtifact(type, taskId, artifactId) {
    try {
        const type_plural = type === 'patch' ? 'patches' : type === 'pov' ? 'povs' : type === 'bundle' ? 'bundles' : `${type}s`;
        const response = await fetch(`${API_BASE}/v1/dashboard/tasks/${taskId}/${type_plural}/${artifactId}/download`);
        if (response.ok) {
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;

            // Get filename from Content-Disposition header
            const contentDisposition = response.headers.get('Content-Disposition');
            let filename = `${type}_${artifactId}`;
            if (contentDisposition) {
                const match = contentDisposition.match(/filename="?([^"]+)"?/);
                if (match) {
                    filename = match[1];
                }
            }

            a.download = filename;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            showNotification('Download started', 'success');
        } else {
            showNotification('Download failed', 'error');
        }
    } catch (error) {
        console.error('Download error:', error);
        showNotification('Download error', 'error');
    }
}

// Show artifact detail modal
async function showArtifactDetail(type, artifactId) {
    try {
        const response = await fetch(`${API_BASE}/v1/dashboard/${type}s/${artifactId}`);
        let detailData;

        if (response.ok) {
            detailData = await response.json();
        } else {
            // Fallback to find in local data
            if (type === 'pov') {
                detailData = allPovs.find(p => p.pov.pov_id === artifactId);
            } else if (type === 'patch') {
                detailData = allPatches.find(p => p.patch.patch_id === artifactId);
            }
        }

        if (detailData) {
            elements.detailTitle.textContent = `${type.toUpperCase()}: ${artifactId}`;
            elements.detailContent.innerHTML = renderArtifactDetail(detailData, type);
            elements.detailModal.style.display = 'block';
        } else {
            showNotification('Artifact not found', 'error');
        }
    } catch (error) {
        console.error('Error loading artifact detail:', error);
        showNotification('Error loading artifact detail', 'error');
    }
}

// Render artifact detail
function renderArtifactDetail(detailData, type) {
    const artifact = detailData.pov || detailData.patch || detailData.bundle || detailData;
    const artifactId = artifact.id || artifact.bundle_id || artifact.pov_id || artifact.patch_id;

    let specificContent = '';

    switch (type) {
        case 'pov':
            // Show hexdump preview for PoV
            let testcasePreview = 'No testcase data';
            let testcaseSize = 0;
            if (artifact.testcase && typeof artifact.testcase === 'string') {
                try {
                    const decoded = atob(artifact.testcase);
                    testcaseSize = decoded.length;
                    testcasePreview = createHexdumpPreview(decoded, 128); // Use consistent 128 bytes like task detail
                } catch (e) {
                    testcaseSize = artifact.testcase.length;
                    testcasePreview = artifact.testcase.substring(0, 100) + '...';
                }
            }
            specificContent = `
                <div class="detail-label">Architecture:</div>
                <div class="detail-value">${artifact.architecture || 'N/A'}</div>
                <div class="detail-label">Engine:</div>
                <div class="detail-value">${artifact.engine || 'N/A'}</div>
                <div class="detail-label">Fuzzer:</div>
                <div class="detail-value">${artifact.fuzzer_name || 'N/A'}</div>
                <div class="detail-label">Sanitizer:</div>
                <div class="detail-value">${artifact.sanitizer || 'N/A'}</div>
                <div class="detail-label">Testcase Size:</div>
                <div class="detail-value">${testcaseSize} bytes</div>
                <div class="detail-label">Testcase Preview:</div>
                <div class="detail-value"><pre class="hex-preview">${testcasePreview}</pre></div>
            `;
            break;
        case 'patch':
            // Decode patch content if it's base64
            let patchContent = artifact.patch || 'No patch content';
            let originalSize = patchContent.length;
            if (typeof patchContent === 'string' && patchContent.length > 0) {
                try {
                    // Check if it looks like base64
                    if (patchContent.match(/^[A-Za-z0-9+/]+={0,2}$/)) {
                        patchContent = atob(patchContent);
                    }
                } catch (e) {
                    // Not base64, use as is
                }
            }
            const patchPreview = patchContent.length > 300 
                ? patchContent.substring(0, 300) + '...' 
                : patchContent;
            specificContent = `
                <div class="detail-label">Patch Size:</div>
                <div class="detail-value">${originalSize} characters (${patchContent.length} decoded)</div>
                <div class="detail-label">Patch Content:</div>
                <div class="detail-value"><pre style="white-space: pre-wrap; background: #f5f5f5; padding: 1rem; border-radius: 4px; max-height: 300px; overflow-y: auto;">${patchContent}</pre></div>
            `;
            break;
        case 'bundle':
            specificContent = `
                <div class="detail-label">Bundle Content:</div>
                <div class="detail-value"><pre style="white-space: pre-wrap; background: #f5f5f5; padding: 1rem; border-radius: 4px; max-height: 300px; overflow-y: auto;">${JSON.stringify(artifact, null, 2)}</pre></div>
            `;
            break;
    }

    return `
        <div style="padding: 1.5rem;">
            <div class="detail-section">
                <h3>Artifact Information</h3>
                <div class="detail-grid">
                    <div class="detail-label">ID:</div>
                    <div class="detail-value">${artifactId}</div>
                    <div class="detail-label">Task:</div>
                    <div class="detail-value">${detailData.task_name}</div>
                    <div class="detail-label">Task ID:</div>
                    <div class="detail-value">${detailData.task_id}</div>
                    <div class="detail-label">Timestamp:</div>
                    <div class="detail-value">${formatTimestamp(artifact.timestamp)}</div>
                    ${specificContent}
                </div>
                ${detailData.task_id ? `
                <div style="margin-top: 1.5rem;">
                    <button class="btn btn-primary" onclick="downloadArtifact('${type}', '${detailData.task_id}', '${artifactId}')">
                        Download ${type.toUpperCase()}
                    </button>
                </div>
                ` : ''}
            </div>
        </div>
    `;
}

// Utility functions
function formatDuration(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
}

function formatTimestamp(timestamp) {
    if (!timestamp) return 'N/A';
    return new Date(timestamp).toLocaleString();
}

function showNotification(message, type = 'info', color = null) {
    // If color is provided from backend Message, use it to override type
    if (color === 'error') {
        type = 'error';
    } else if (color === 'warning') {
        type = 'warning';
    } else if (color === 'success') {
        type = 'success';
    }
    
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    // Add to notifications container
    const container = document.getElementById('notifications') || document.body;
    container.appendChild(notification);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (notification.parentNode) {
            notification.remove();
        }
    }, 5000);
}

// Mock data for development/fallback
// Helper function to create hexdump preview
function createHexdumpPreview(data, maxBytes = 128) {
    const bytes = [];
    for (let i = 0; i < Math.min(data.length, maxBytes); i++) {
        bytes.push(data.charCodeAt(i) & 0xFF);
    }

    let result = '';
    for (let i = 0; i < bytes.length; i += 16) {
        // Address
        const addr = i.toString(16).padStart(8, '0');
        result += addr + '  ';

        // Hex bytes
        const lineBytes = bytes.slice(i, i + 16);
        for (let j = 0; j < 16; j++) {
            if (j < lineBytes.length) {
                result += lineBytes[j].toString(16).padStart(2, '0') + ' ';
            } else {
                result += '   ';
            }
            if (j === 7) result += ' ';
        }

        // ASCII representation
        result += ' |';
        for (let j = 0; j < lineBytes.length; j++) {
            const byte = lineBytes[j];
            if (byte >= 32 && byte <= 126) {
                result += String.fromCharCode(byte);
            } else {
                result += '.';
            }
        }
        result += '|\n';
    }

    if (data.length > maxBytes) {
        result += `\n... (${data.length - maxBytes} more bytes)`;
    }

    return result;
}

function getMockTasks() {
    const now = new Date();
    const deadline1 = new Date(now.getTime() + 2 * 60 * 60 * 1000); // 2 hours from now
    const deadline2 = new Date(now.getTime() - 1 * 60 * 60 * 1000); // 1 hour ago

    return [
        {
            task_id: "12345678-1234-1234-1234-123456789abc",
            name: "libpng-analysis",
            project_name: "libpng",
            status: "active",
            duration: 1800,
            created_at: new Date(now.getTime() - 30 * 60 * 1000).toISOString(), // 30 minutes ago
            deadline: deadline1.toISOString(),
            challenge_repo_url: "https://github.com/pnggroup/libpng",
            challenge_repo_head_ref: "libpng16",
            challenge_repo_base_ref: "v1.6.39",
            povs: [
                {
                    pov_id: "pov-001",
                    testcase: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                    timestamp: new Date().toISOString()
                }
            ],
            patches: [
                {
                    patch_id: "patch-001",
                    patch: "--- a/png.c\n+++ b/png.c\n@@ -123,7 +123,7 @@\n    if (size > MAX_SIZE)\n-      return NULL;\n+      return png_error(png_ptr, \"Size too large\");",
                    timestamp: new Date().toISOString()
                }
            ],
            bundles: [
                {
                    bundle_id: "bundle-001",
                    patches: ["patch-001"],
                    timestamp: new Date().toISOString()
                }
            ]
        },
        {
            task_id: "87654321-4321-4321-4321-cba987654321",
            name: "libxml2-fuzzing",
            project_name: "libxml2",
            status: "expired",
            duration: 1800,
            created_at: new Date(now.getTime() - 90 * 60 * 1000).toISOString(), // 1.5 hours ago
            deadline: deadline2.toISOString(),
            challenge_repo_url: "https://github.com/GNOME/libxml2",
            challenge_repo_head_ref: "master",
            povs: [],
            patches: [],
            bundles: []
        }
    ];
}