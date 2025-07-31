// Global state
let tasks = [];
let dashboardStats = {
    activeTasks: 0,
    totalPovs: 0,
    totalPatches: 0,
    totalBundles: 0
};

// API base URL - will be set dynamically
const API_BASE = '';

// DOM elements
const elements = {
    submitTaskBtn: document.getElementById('submit-task-btn'),
    refreshBtn: document.getElementById('refresh-btn'),
    taskModal: document.getElementById('task-modal'),
    detailModal: document.getElementById('detail-modal'),
    closeModal: document.getElementById('close-modal'),
    closeDetailModal: document.getElementById('close-detail-modal'),
    taskForm: document.getElementById('task-form'),
    cancelBtn: document.getElementById('cancel-btn'),
    tasksContainer: document.getElementById('tasks-container'),
    statusFilter: document.getElementById('status-filter'),
    activeTasks: document.getElementById('active-tasks'),
    totalPovs: document.getElementById('total-povs'),
    totalPatches: document.getElementById('total-patches'),
    totalBundles: document.getElementById('total-bundles'),
    detailTitle: document.getElementById('detail-title'),
    detailContent: document.getElementById('detail-content')
};

// Initialize the dashboard
document.addEventListener('DOMContentLoaded', function() {
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
    
    // Close modals when clicking outside
    window.addEventListener('click', (event) => {
        if (event.target === elements.taskModal) {
            elements.taskModal.style.display = 'none';
        }
        if (event.target === elements.detailModal) {
            elements.detailModal.style.display = 'none';
        }
    });
}

// Load dashboard data
async function loadDashboard() {
    try {
        elements.refreshBtn.innerHTML = '<span class="spinner"></span>';
        
        // Load tasks and stats in parallel
        await Promise.all([
            loadTasks(),
            loadStats()
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
        const response = await fetch(`${API_BASE}/v1/dashboard/tasks`);
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
    elements.totalPovs.textContent = dashboardStats.totalPovs;
    elements.totalPatches.textContent = dashboardStats.totalPatches;
    elements.totalBundles.textContent = dashboardStats.totalBundles;
    
    // Update tasks list
    renderTasks();
}

// Render tasks list
function renderTasks() {
    const filteredTasks = filterTasksByStatus();
    
    if (filteredTasks.length === 0) {
        elements.tasksContainer.innerHTML = `
            <div class="no-data">
                <div class="no-data-icon">📋</div>
                <p>No tasks found</p>
            </div>
        `;
        return;
    }
    
    elements.tasksContainer.innerHTML = filteredTasks.map(task => `
        <div class="task-item" onclick="showTaskDetail('${task.task_id}')">
            <div class="task-info">
                <div class="task-name">${task.name || task.project_name}</div>
                <div class="task-id">ID: ${task.task_id}</div>
                <div class="task-meta">
                    <span>Project: ${task.project_name}</span>
                    <span>Duration: ${formatDuration(task.duration)}</span>
                    <span>Deadline: ${formatTimestamp(task.deadline)}</span>
                </div>
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
async function handleTaskSubmission(event) {
    event.preventDefault();
    
    const formData = new FormData(elements.taskForm);
    const taskData = Object.fromEntries(formData.entries());
    
    // Convert checkbox and number values
    taskData.harnesses_included = formData.has('harnesses_included');
    taskData.duration = parseInt(taskData.duration);
    
    try {
        const response = await fetch(`${API_BASE}/webhook/trigger_task`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(taskData)
        });
        
        if (response.ok) {
            const result = await response.json();
            showNotification('Task submitted successfully!', 'success');
            elements.taskModal.style.display = 'none';
            elements.taskForm.reset();
            
            // Refresh dashboard after a short delay
            setTimeout(loadDashboard, 1000);
        } else {
            const error = await response.json();
            showNotification(`Error: ${error.message || 'Failed to submit task'}`, 'error');
        }
    } catch (error) {
        console.error('Error submitting task:', error);
        showNotification('Network error occurred', 'error');
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
                    <div class="detail-label">Task ID:</div>
                    <div class="detail-value">${task.task_id}</div>
                    <div class="detail-label">Name:</div>
                    <div class="detail-value">${task.name || 'N/A'}</div>
                    <div class="detail-label">Project:</div>
                    <div class="detail-value">${task.project_name}</div>
                    <div class="detail-label">Status:</div>
                    <div class="detail-value">
                        <span class="status-badge status-${task.status}">${task.status}</span>
                    </div>
                    <div class="detail-label">Duration:</div>
                    <div class="detail-value">${formatDuration(task.duration)}</div>
                    <div class="detail-label">Deadline:</div>
                    <div class="detail-value">${formatTimestamp(task.deadline)}</div>
                    <div class="detail-label">Repository:</div>
                    <div class="detail-value">${task.challenge_repo_url || 'N/A'}</div>
                    <div class="detail-label">Head Ref:</div>
                    <div class="detail-value">${task.challenge_repo_head_ref || 'N/A'}</div>
                    <div class="detail-label">Base Ref:</div>
                    <div class="detail-value">${task.challenge_repo_base_ref || 'N/A'}</div>
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
    
    switch (type) {
        case 'pov':
            // Handle binary PoV data safely
            if (artifact.testcase) {
                if (typeof artifact.testcase === 'string') {
                    // If it's already a string, show it (might be base64)
                    const preview = artifact.testcase.length > 200 
                        ? artifact.testcase.substring(0, 200) + '...' 
                        : artifact.testcase;
                    content = `<div class="artifact-content">Type: Binary Data\nSize: ${artifact.testcase.length} bytes\nPreview (Base64): ${preview}</div>`;
                } else {
                    content = `<div class="artifact-content">Type: Binary Data\nSize: ${JSON.stringify(artifact.testcase).length} bytes</div>`;
                }
            }
            break;
        case 'patch':
            content = `<div class="artifact-content">${artifact.patch || 'No patch content'}</div>`;
            break;
        case 'bundle':
            content = `<div class="artifact-content">${JSON.stringify(artifact, null, 2)}</div>`;
            break;
    }
    
    return `
        <div class="artifact-item">
            <div class="artifact-header">
                <div class="artifact-id">${artifact.id || artifact.pov_id || artifact.patch_id || artifact.bundle_id}</div>
                <div class="artifact-timestamp">${formatTimestamp(artifact.timestamp || new Date().toISOString())}</div>
            </div>
            ${content}
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

function showNotification(message, type = 'info') {
    // Create a simple notification system
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    
    // Add notification styles if not already added
    if (!document.querySelector('style[data-notifications]')) {
        const style = document.createElement('style');
        style.setAttribute('data-notifications', 'true');
        style.textContent = `
            .notification {
                position: fixed;
                top: 20px;
                right: 20px;
                padding: 1rem 1.5rem;
                border-radius: 4px;
                color: white;
                font-weight: 500;
                z-index: 2000;
                animation: slideIn 0.3s ease;
            }
            .notification-success { background-color: #4caf50; }
            .notification-error { background-color: #f44336; }
            .notification-info { background-color: #2196f3; }
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
        `;
        document.head.appendChild(style);
    }
    
    document.body.appendChild(notification);
    
    // Remove notification after 5 seconds
    setTimeout(() => {
        notification.remove();
    }, 5000);
}

// Mock data for development/fallback
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
            deadline: deadline2.toISOString(),
            challenge_repo_url: "https://github.com/GNOME/libxml2",
            challenge_repo_head_ref: "master",
            povs: [],
            patches: [],
            bundles: []
        }
    ];
}