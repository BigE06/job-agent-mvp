window.currentJobs = [];
window.savedJobUrls = new Set(); // Track saved job URLs for heart state sync
window.jobsByUrl = new Map(); // Map URL -> job object for stable lookups

// --- HEART TOGGLE HELPER ---
function toggleHeartUI(jobUrl, isSaved) {
    // Skip invalid URLs
    if (!jobUrl || jobUrl === '#' || jobUrl.length < 5) {
        console.warn("toggleHeartUI: Invalid URL", jobUrl);
        return;
    }

    // Find all heart buttons on the page (search results, cards, etc.)
    document.querySelectorAll(`[data-job-url="${CSS.escape(jobUrl)}"]`).forEach(btn => {
        const icon = btn.querySelector('i.fa-heart') || btn.querySelector('i');
        if (icon) {
            if (isSaved) {
                icon.classList.remove('text-gray-300', 'text-gray-400');
                icon.classList.add('text-red-500');
                btn.classList.remove('opacity-0', 'group-hover:opacity-100');
                btn.classList.add('opacity-100');
                btn.title = 'Saved';
            } else {
                icon.classList.remove('text-red-500');
                icon.classList.add('text-gray-300');
                btn.classList.remove('opacity-100');
                btn.classList.add('opacity-0', 'group-hover:opacity-100');
                btn.title = 'Save to Board';
            }
        }
    });

    // Update global tracking
    if (isSaved) {
        window.savedJobUrls.add(jobUrl);
    } else {
        window.savedJobUrls.delete(jobUrl);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    // 1. Setup Tabs
    bindTab('btn-find-jobs', 'section-find-jobs');
    bindTab('btn-my-board', 'section-my-board', loadMyBoard);
    bindTab('btn-master-profile', 'section-master-profile', loadProfile);

    // 2. Setup Universal Search
    const btnSearch = document.getElementById('btn-search-universal');
    if (btnSearch) btnSearch.addEventListener('click', runUniversalSearch);

    // 3. Setup Enter Key for Search
    document.getElementById('inp-search-q')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') runUniversalSearch(); });
    document.getElementById('inp-search-loc')?.addEventListener('keypress', (e) => { if (e.key === 'Enter') runUniversalSearch(); });

    // 4. Setup Resume Upload
    const btnUpload = document.getElementById('btn-upload-resume');
    if (btnUpload) btnUpload.addEventListener('click', uploadResume);
});

// --- HELPER: TAB LOGIC ---
function bindTab(btnId, sectionId, callback) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tab-section').forEach(el => el.classList.add('hidden'));
        document.querySelectorAll('.nav-tab').forEach(el => {
            el.classList.remove('text-blue-600', 'border-blue-600');
            el.classList.add('text-gray-500');
        });
        document.getElementById(sectionId).classList.remove('hidden');
        btn.classList.remove('text-gray-500');
        btn.classList.add('text-blue-600', 'border-blue-600');
        if (callback) callback();
    });
}

// --- SEARCH LOGIC ---
async function runUniversalSearch() {
    const q = document.getElementById('inp-search-q').value.trim();
    const loc = document.getElementById('inp-search-loc').value.trim();

    if (!q) { alert("Please enter a Job Title"); return; }

    const container = document.getElementById('jobs-container');
    container.innerHTML = `
        <div class="col-span-full text-center py-20">
            <i class="fas fa-satellite-dish fa-spin text-4xl text-blue-500 mb-4"></i>
            <p class="text-gray-600 font-medium">Scanning...</p>
        </div>`;

    try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(q)}&loc=${encodeURIComponent(loc)}`);
        const data = await res.json();

        if (data.jobs && data.jobs.length > 0) {
            renderJobs(data.jobs);
        } else {
            container.innerHTML = `
                <div class="col-span-full text-center py-10">
                    <p class="text-gray-500">No direct ATS links found for "${q}" in "${loc}".</p>
                    <p class="text-sm text-gray-400">Try broadening your search (e.g. just "Analyst").</p>
                </div>`;
        }
    } catch (e) {
        console.error(e);
        container.innerHTML = '<p class="col-span-full text-center text-red-500">Search Failed. Rate limit or connection error.</p>';
    }
}

// --- RENDER JOBS ---
function renderJobs(jobs, containerId = 'jobs-container', isSavedView = false) {
    // Force update global state
    window.currentJobs = jobs || [];
    window.jobsByUrl.clear(); // Reset URL map
    console.log("Global currentJobs updated:", window.currentJobs.length, "jobs");

    const container = document.getElementById(containerId);
    if (!container) {
        console.error("Container not found:", containerId);
        return;
    }
    container.innerHTML = '';

    if (!jobs || jobs.length === 0) {
        container.innerHTML = '<p class="col-span-full text-center py-10 text-gray-400">No jobs found.</p>';
        return;
    }

    console.log(`Rendering ${jobs.length} jobs to ${containerId}`);
    let renderedCount = 0;

    jobs.forEach((job, index) => {
        try {
            // Safe field fallbacks to prevent null errors
            const title = job.title || 'Untitled Role';
            const company = job.company || 'Unknown Company';
            const location = job.location || 'Remote';
            const snippet = job.snippet || '';
            const jobUrl = job.link || job.absolute_url || job.url || '';

            // Skip jobs with invalid URLs in search view (would cause ghost saves)
            if (!isSavedView && (!jobUrl || jobUrl === '#' || jobUrl.length < 5)) {
                console.warn("Skipping job with invalid URL:", title, jobUrl);
                return; // Skip this job
            }

            // Store in jobsByUrl map for stable lookups - Refactored to use URL reference
            if (jobUrl && jobUrl.length > 5) {
                window.jobsByUrl.set(jobUrl, job);
            }

            console.log("Rendering job:", title, "URL:", jobUrl.substring(0, 50));

            const card = document.createElement('div');
            card.className = 'bg-white rounded-xl shadow-sm border border-gray-200 hover:shadow-lg transition-all flex flex-col h-full relative group';

            let headerAction = '';
            if (isSavedView) {
                const statusColor = getStatusColor(job.status || 'Saved');
                const jobId = job.id || index;
                headerAction = `
                    <div class="absolute top-4 right-4 flex items-center space-x-2">
                        <select onchange="updateStatus(${jobId}, this.value)" class="text-xs font-bold uppercase px-2 py-1 rounded border-0 cursor-pointer outline-none ${statusColor}">
                            <option value="Saved" ${job.status === 'Saved' ? 'selected' : ''}>Saved</option>
                            <option value="Applied" ${job.status === 'Applied' ? 'selected' : ''}>Applied</option>
                            <option value="Interviewing" ${job.status === 'Interviewing' ? 'selected' : ''}>Interviewing</option>
                            <option value="Offer" ${job.status === 'Offer' ? 'selected' : ''}>Offer</option>
                            <option value="Rejected" ${job.status === 'Rejected' ? 'selected' : ''}>Rejected</option>
                        </select>
                        <button onclick="deleteJob(${jobId})" class="text-gray-300 hover:text-red-500 transition px-2"><i class="fas fa-trash-alt"></i></button>
                    </div>
                `;
            } else {
                // Search View: Heart Icon
                // Refactored to use data attributes to prevent index mismatch
                const isSaved = window.savedJobUrls.has(jobUrl);
                const heartColor = isSaved ? 'text-red-500' : 'text-gray-300';
                const heartOpacity = isSaved ? 'opacity-100' : 'opacity-0 group-hover:opacity-100';

                // Escape data for HTML attributes
                const safeTitle = (job.title || 'Unknown Role').replace(/"/g, '&quot;');
                const safeCompany = (job.company || 'Unknown').replace(/"/g, '&quot;');
                const safeLocation = (job.location || 'Remote').replace(/"/g, '&quot;');

                headerAction = `
                    <button onclick="saveJobDirect(this)" 
                        data-job-url="${jobUrl}"
                        data-job-title="${safeTitle}"
                        data-job-company="${safeCompany}"
                        data-job-location="${safeLocation}"
                        class="absolute top-4 right-4 ${heartColor} hover:text-red-500 transition text-xl bg-white rounded-full p-1 shadow-sm ${heartOpacity}"
                        title="${isSaved ? 'Saved' : 'Save to Board'}">
                        <i class="fas fa-heart"></i>
                    </button>`;
            }

            let bottomBtn = '';
            if (isSavedView) {
                bottomBtn = `
        <div class="grid grid-cols-2 gap-2 mt-3">
            <button onclick="generatePack(${index})" class="py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700">Cover Letter</button>
            <button onclick="openCVInterview(${index})" class="py-2 bg-indigo-600 text-white rounded text-sm font-medium hover:bg-indigo-700">Tailor CV</button>
            <button onclick="startInterview(${index})" class="py-2 bg-pink-600 text-white rounded text-sm font-medium hover:bg-pink-700">Practice</button>
            <button id="btn-email-${index}" onclick="openEmailDrafter(${index})" class="py-2 bg-teal-600 text-white rounded text-sm font-medium hover:bg-teal-700">Email</button>
        </div>`;
            }

            // Deadline badge for saved jobs
            let deadlineBadge = '';
            if (isSavedView && job.due_date) {
                const daysLeft = Math.ceil((new Date(job.due_date) - new Date()) / (1000 * 60 * 60 * 24));
                let colorClass = 'bg-gray-100 text-gray-600';
                let text = 'Expired';

                if (daysLeft >= 0) {
                    if (daysLeft <= 3) { colorClass = 'bg-red-100 text-red-800 border-red-200'; text = `Urgent: ${daysLeft}d`; }
                    else if (daysLeft <= 7) { colorClass = 'bg-yellow-100 text-yellow-800 border-yellow-200'; text = `${daysLeft} days`; }
                    else { colorClass = 'bg-blue-50 text-blue-600 border-blue-100'; text = new Date(job.due_date).toLocaleDateString(); }
                }

                deadlineBadge = `<div class="mb-3"><span class="text-xs font-bold px-2 py-1 rounded border ${colorClass}"><i class="far fa-clock mr-1"></i>${text}</span></div>`;
            }

            card.innerHTML = `
                ${headerAction}
                <div class="p-6 flex-grow">
                    <h3 class="font-bold text-gray-900 text-lg leading-tight mb-2 pr-12 line-clamp-2">${title}</h3>
                    <div class="text-sm text-gray-600 space-y-1">
                        <div><i class="fas fa-building w-5 text-gray-400"></i> ${company}</div>
                        <div><i class="fas fa-map-marker-alt w-5 text-gray-400"></i> ${location}</div>
                    </div>
                    ${deadlineBadge}
                </div>
                <div class="bg-gray-50 px-6 py-4 border-t border-gray-100 grid grid-cols-2 gap-3 mt-auto">
                    <button onclick="openJobDetails(${index})" class="py-2 px-3 bg-white border border-gray-300 rounded-lg text-sm font-medium hover:bg-gray-100">View Details</button>
                    ${bottomBtn}
                </div>
            `;
            container.appendChild(card);
        } catch (err) {
            console.error("Failed to render individual job at index", index, ":", job, err);
        }
    });

    console.log(`Finished rendering. Container has ${container.children.length} cards.`);
}

// --- DETAILS & ANALYSIS ---
function openJobDetails(index) {
    const job = window.currentJobs[index];
    if (!job) {
        console.error("Job not found at index:", index);
        return;
    }
    console.log("Opening modal for job:", job);

    // Robust URL fallback - check all possible fields
    const targetUrl = job.link || job.url || job.absolute_url || job.application_url || '#';
    console.log("Calculated Target URL:", targetUrl);

    const modalTitle = document.getElementById('modal-title');
    if (modalTitle) modalTitle.innerText = job.title;

    // Set the Go to Job button href
    const sourceBtn = document.getElementById('modal-source-btn');
    if (sourceBtn) {
        sourceBtn.href = targetUrl;
        // Hide button if no valid URL
        if (targetUrl === '#' || !targetUrl) {
            sourceBtn.style.display = 'none';
        } else {
            sourceBtn.style.display = '';
        }
    }

    // Notes
    const notesInput = document.getElementById('modal-notes');
    const saveBtn = document.getElementById('btn-save-notes');
    if (notesInput && saveBtn) {
        notesInput.value = job.notes || '';
        const newBtn = saveBtn.cloneNode(true);
        saveBtn.parentNode.replaceChild(newBtn, saveBtn);
        newBtn.onclick = () => saveNotes(job.id, notesInput.value);
    }

    // Set global ID for deadline update
    window.currentJobId = job.id;

    // Populate Deadline Picker
    const deadlineInput = document.getElementById('job-deadline');
    if (deadlineInput) {
        deadlineInput.value = job.due_date || '';
        updateDeadlineBadge(job.due_date);
    }

    const modal = document.getElementById('jobModal');
    if (modal) modal.classList.remove('hidden');

    const analysisResults = document.getElementById('analysis-results');
    if (analysisResults) analysisResults.classList.add('hidden');

    // Analyze
    const analyzeBtn = document.getElementById('analyze-btn');
    if (analyzeBtn) {
        analyzeBtn.innerText = "2. Analyze Match";
        const newAnalyzeBtn = analyzeBtn.cloneNode(true);
        analyzeBtn.parentNode.replaceChild(newAnalyzeBtn, analyzeBtn);

        newAnalyzeBtn.addEventListener('click', async () => {
            const text = document.getElementById('modal-description-input').value;
            if (!text) { alert("Paste description first!"); return; }

            newAnalyzeBtn.innerText = "Analyzing...";
            try {
                const res = await fetch('/api/analyze-text', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_description: text })
                });
                const data = await res.json();

                try {
                    const analysis = JSON.parse(data.analysis);
                    renderAnalysisVisuals(analysis);
                } catch (err) {
                    document.getElementById('analysis-results').innerText = data.analysis;
                }

                const resultsEl = document.getElementById('analysis-results');
                const scrollHint = document.getElementById('scroll-hint');
                const analysisFade = document.getElementById('analysis-fade');
                const scrollText = document.getElementById('scroll-text');
                if (resultsEl) resultsEl.classList.remove('hidden');
                if (scrollHint) scrollHint.classList.remove('hidden');
                if (analysisFade) analysisFade.classList.remove('hidden');
                if (scrollText) scrollText.classList.remove('hidden');
                newAnalyzeBtn.innerText = "2. Analyze Match";
            } catch (e) { newAnalyzeBtn.innerText = "Error"; console.error(e); }
        });
    }
}

function renderAnalysisVisuals(data) {
    const container = document.getElementById('analysis-results');
    let scoreColor = 'text-red-600';
    let ringColor = 'border-red-500';
    if (data.match_score >= 70) { scoreColor = 'text-green-600'; ringColor = 'border-green-500'; }
    else if (data.match_score >= 50) { scoreColor = 'text-yellow-600'; ringColor = 'border-yellow-500'; }

    container.innerHTML = `
        <div class="flex flex-col space-y-6 animate-fade-in">
            <div class="flex items-center space-x-6 p-4 bg-gray-50 rounded-lg border border-gray-100">
                <div class="relative w-20 h-20 flex items-center justify-center rounded-full border-4 ${ringColor} bg-white shadow-sm">
                    <span class="text-2xl font-bold ${scoreColor}">${data.match_score}%</span>
                </div>
                <div>
                    <h4 class="text-lg font-bold text-gray-800">${data.verdict}</h4>
                    <p class="text-sm text-gray-600">${data.summary}</p>
                </div>
            </div>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div class="bg-green-50 p-4 rounded-lg border border-green-100">
                    <h5 class="font-bold text-green-800 mb-2 flex items-center"><i class="fas fa-check-circle mr-2"></i> Strengths</h5>
                    <ul class="space-y-1">
                        ${data.strengths.map(s => `<li class="text-sm text-gray-700 flex items-start"><span class="mr-2">•</span>${s}</li>`).join('')}
                    </ul>
                </div>
                <div class="bg-red-50 p-4 rounded-lg border border-red-100">
                    <h5 class="font-bold text-red-800 mb-2 flex items-center"><i class="fas fa-exclamation-circle mr-2"></i> Gaps</h5>
                    <ul class="space-y-1">
                        ${data.gaps.map(s => `<li class="text-sm text-gray-700 flex items-start"><span class="mr-2">•</span>${s}</li>`).join('')}
                    </ul>
                </div>
            </div>
        </div>
    `;
}

// --- CRUD & UTILS ---

/**
 * NEW: saveJobDirect - reads ALL job data directly from button data attributes.
 * This eliminates array index bugs where clicking one job saves another.
 */
async function saveJobDirect(btnElement) {
    // Read ALL job data directly from button attributes
    const jobUrl = btnElement.dataset.jobUrl;
    const jobTitle = btnElement.dataset.jobTitle;
    const jobCompany = btnElement.dataset.jobCompany;
    const jobLocation = btnElement.dataset.jobLocation;

    console.log("saveJobDirect called - Title:", jobTitle, "URL:", jobUrl);

    // Validate URL
    if (!jobUrl || jobUrl === '#' || jobUrl.length < 5) {
        console.error("Invalid job URL from element:", jobUrl);
        return;
    }

    // Validate title (must have actual title, not placeholder)
    if (!jobTitle || jobTitle === 'Unknown Role') {
        console.error("Job title missing from button attributes:", jobTitle);
        alert("Could not retrieve job details. Please refresh and try again.");
        return;
    }

    // Check if already saved
    if (window.savedJobUrls.has(jobUrl)) {
        console.log("Job already saved:", jobUrl);
        toggleHeartUI(jobUrl, true);
        return;
    }

    // Create payload directly from button attributes - NO array lookup needed!
    const cleanPayload = {
        title: jobTitle,
        company: jobCompany || 'Unknown Company',
        location: jobLocation || 'Remote',
        link: jobUrl,
        snippet: '' // Snippet not stored in button for performance
    };
    console.log("saveJobDirect payload:", cleanPayload);

    // Show loading state
    btnElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    btnElement.disabled = true;

    try {
        const res = await fetch('/api/save-job', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cleanPayload)
        });

        // Mark as saved
        console.log("Save response status:", res.status);
        window.savedJobUrls.add(jobUrl);
        toggleHeartUI(jobUrl, true);

        btnElement.innerHTML = '<i class="fas fa-heart text-red-500"></i>';
        btnElement.classList.remove('text-gray-300', 'opacity-0', 'group-hover:opacity-100');
        btnElement.classList.add('text-red-500', 'opacity-100');
        btnElement.disabled = false;
        btnElement.title = 'Saved';
    } catch (e) {
        console.error("Save exception:", e);
        btnElement.innerHTML = '<i class="fas fa-heart"></i>';
        btnElement.disabled = false;
    }
}

/**
 * Legacy: saveJobByElement - kept for backward compatibility.
 * Uses array index lookup; prefer saveJobDirect for new code.
 */
async function saveJobByElement(btnElement) {
    // Redirect to saveJobDirect if data attributes are available
    if (btnElement.dataset.jobTitle) {
        return saveJobDirect(btnElement);
    }

    // Fallback to old index-based logic
    const jobUrl = btnElement.dataset.jobUrl;
    const jobIndex = parseInt(btnElement.dataset.jobIndex, 10);

    if (!jobUrl || jobUrl === '#') return;
    if (window.savedJobUrls.has(jobUrl)) {
        toggleHeartUI(jobUrl, true);
        return;
    }

    let job = window.currentJobs[jobIndex] || window.jobsByUrl.get(jobUrl);
    if (!job || !job.title) {
        alert("Could not retrieve job details. Please refresh and try again.");
        return;
    }

    btnElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
    btnElement.disabled = true;

    try {
        await fetch('/api/save-job', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: job.title,
                company: job.company || 'Unknown',
                location: job.location || 'Remote',
                link: jobUrl,
                snippet: job.snippet || ''
            })
        });
        window.savedJobUrls.add(jobUrl);
        toggleHeartUI(jobUrl, true);
        btnElement.innerHTML = '<i class="fas fa-heart text-red-500"></i>';
        btnElement.classList.add('text-red-500', 'opacity-100');
        btnElement.disabled = false;
    } catch (e) {
        console.error("Save exception:", e);
        btnElement.innerHTML = '<i class="fas fa-heart"></i>';
        btnElement.disabled = false;
    }
}

// Legacy function - kept for compatibility with other parts of code
async function saveJob(index, btnElement) {
    const job = window.currentJobs[index];
    if (!job) {
        console.error("Job not found at index:", index);
        return;
    }
    console.log("Original job object:", job);

    // Get job URL for tracking
    const jobUrl = job.link || job.absolute_url || job.url || '';

    // Check if already saved
    if (window.savedJobUrls.has(jobUrl)) {
        console.log("Job already saved:", jobUrl);
        // Already saved - just update the UI to red
        toggleHeartUI(jobUrl, true);
        if (btnElement) {
            const icon = btnElement.querySelector('i.fa-heart') || btnElement.querySelector('i');
            if (icon) {
                icon.classList.remove('text-gray-300', 'text-gray-400');
                icon.classList.add('text-red-500');
            }
            btnElement.classList.remove('opacity-0', 'group-hover:opacity-100');
            btnElement.classList.add('opacity-100');
        }
        return;
    }

    // Create clean payload
    const cleanPayload = {
        title: job.title || 'Unknown Role',
        company: job.company || 'Unknown',
        location: job.location || 'Remote',
        link: jobUrl,
        snippet: job.snippet || ''
    };
    console.log("Clean payload to save:", cleanPayload);

    // Show loading state
    if (btnElement) {
        btnElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        btnElement.disabled = true;
    }

    try {
        const res = await fetch('/api/save-job', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cleanPayload)
        });

        if (res.ok) {
            console.log("Save successful for:", jobUrl);
            // Add to saved set
            window.savedJobUrls.add(jobUrl);
            job.saved = true;

            // Toggle all hearts for this URL
            toggleHeartUI(jobUrl, true);

            // Also directly update this button
            if (btnElement) {
                btnElement.innerHTML = '<i class="fas fa-heart text-red-500"></i>';
                btnElement.classList.remove('text-gray-300', 'opacity-0', 'group-hover:opacity-100');
                btnElement.classList.add('text-red-500', 'opacity-100');
                btnElement.disabled = false;
                btnElement.title = 'Saved';
            }
        } else {
            console.log("Save response not OK, but treating as already saved");
            // Treat as already saved
            window.savedJobUrls.add(jobUrl);
            toggleHeartUI(jobUrl, true);

            if (btnElement) {
                btnElement.innerHTML = '<i class="fas fa-heart text-red-500"></i>';
                btnElement.classList.remove('text-gray-300', 'opacity-0', 'group-hover:opacity-100');
                btnElement.classList.add('text-red-500', 'opacity-100');
                btnElement.disabled = false;
            }
        }
    } catch (e) {
        console.error("Save exception:", e);
        if (btnElement) {
            btnElement.innerHTML = '<i class="fas fa-heart"></i>';
            btnElement.disabled = false;
        }
    }
}

async function updateStatus(id, newStatus) {
    try {
        await fetch('/api/update-status', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id, status: newStatus })
        });
    } catch (e) { console.error(e); }
}

async function deleteJob(id) {
    if (!confirm("Delete this job?")) return;

    // Find the job to get its URL before deleting
    const job = window.currentJobs.find(j => j.id === id);
    const jobUrl = job ? (job.link || job.url || '') : '';

    try {
        const res = await fetch(`/api/saved-jobs/${id}`, { method: 'DELETE' });
        if (res.ok) {
            // Toggle heart back to unsaved state
            if (jobUrl) toggleHeartUI(jobUrl, false);
            loadMyBoard();
        }
    } catch (e) { console.error(e); }
}

async function saveNotes(id, notes) {
    const btn = document.getElementById('btn-save-notes');
    const originalText = btn.innerText;
    const originalClass = btn.className;

    btn.innerText = "Saving...";
    btn.disabled = true;

    try {
        await fetch('/api/update-notes', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: id, notes: notes })
        });
        btn.innerText = "✓ Saved!";
        btn.className = originalClass.replace('bg-blue-600', 'bg-green-600').replace('hover:bg-blue-700', 'hover:bg-green-700');
        const job = window.currentJobs.find(j => j.id === id);
        if (job) job.notes = notes;

        setTimeout(() => {
            btn.innerText = originalText;
            btn.className = originalClass;
            btn.disabled = false;
        }, 3000);
    } catch (e) {
        btn.innerText = "Error";
        btn.disabled = false;
    }
}

function getStatusColor(status) {
    switch (status) {
        case 'Applied': return 'bg-blue-100 text-blue-800';
        case 'Interviewing': return 'bg-purple-100 text-purple-800';
        case 'Offer': return 'bg-green-100 text-green-800';
        case 'Rejected': return 'bg-red-100 text-red-800';
        default: return 'bg-gray-100 text-gray-600';
    }
}

// NOTE: loadMyBoard is defined later in file at "MY BOARD (Saved Jobs)" section with full Kanban support

async function saveProfile() {
    const r = document.getElementById('inp-resume').value;
    const s = document.getElementById('inp-skills').value;
    const btn = document.getElementById('btn-save-profile');
    btn.innerHTML = 'Saving...';
    await fetch('/api/save-profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resume_text: r, skills: s }) });
    btn.innerHTML = 'Saved!'; setTimeout(() => btn.innerHTML = 'Save Changes', 2000);
}

async function loadProfile() {
    try {
        const res = await fetch('/api/get-profile');
        const data = await res.json();
        if (data.resume_text) document.getElementById('inp-resume').value = data.resume_text;
        if (data.skills) document.getElementById('inp-skills').value = data.skills;
    } catch (e) { }
}

async function generatePack(index) {
    const job = window.currentJobs[index];
    if (!document.getElementById('genModal')) {
        const modalHTML = `
        <div id="genModal" class="fixed inset-0 bg-gray-900 bg-opacity-50 hidden flex items-center justify-center z-50">
            <div class="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4 flex flex-col max-h-[90vh]">
                <div class="p-6 border-b border-gray-100 flex justify-between items-center bg-blue-50 rounded-t-xl">
                    <h3 class="text-xl font-bold text-gray-800">✨ Cover Letter & Notes</h3>
                    <button onclick="document.getElementById('genModal').classList.add('hidden')" class="text-gray-400 hover:text-gray-600"><i class="fas fa-times text-xl"></i></button>
                </div>
                <div class="p-6 overflow-y-auto">
                    <label class="block text-sm font-semibold text-gray-700 mb-2">Cover Letter Draft</label>
                    <textarea id="gen-output" class="w-full h-64 p-4 border border-gray-300 rounded-lg font-mono text-sm leading-relaxed focus:ring-2 focus:ring-blue-500 outline-none"></textarea>
                </div>
                <div class="p-6 border-t border-gray-100 bg-gray-50 rounded-b-xl flex justify-end space-x-3">
                    <button onclick="document.getElementById('genModal').classList.add('hidden')" class="px-4 py-2 text-gray-600 font-medium hover:bg-gray-100 rounded-lg">Close</button>
                    <button onclick="navigator.clipboard.writeText(document.getElementById('gen-output').value); alert('Copied!')" class="px-4 py-2 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 shadow-sm">Copy to Clipboard</button>
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', modalHTML);
    }
    const modal = document.getElementById('genModal');
    const output = document.getElementById('gen-output');
    modal.classList.remove('hidden');
    output.value = "Generating...";
    try {
        const res = await fetch('/api/generate-pack', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: job.id })
        });
        const data = await res.json();
        output.value = data.pack_content;
    } catch (e) { output.value = "Error."; }
}

async function uploadResume() {
    const fileInput = document.getElementById('inp-resume-file');
    const file = fileInput.files[0];
    if (!file) { alert("Please select a PDF file first."); return; }
    const formData = new FormData();
    formData.append('file', file);
    const btn = document.getElementById('btn-upload-resume');
    const originalText = btn.innerText;
    btn.innerHTML = 'AI Reading (approx 10s)...';
    btn.disabled = true;
    try {
        const res = await fetch('/api/upload-resume', { method: 'POST', body: formData });
        if (res.ok) {
            const data = await res.json();
            document.getElementById('inp-resume').value = data.text;
            document.getElementById('inp-skills').value = data.skills;
            alert("Resume Analyzed Successfully!");
        } else { alert("Error parsing PDF."); }
    } catch (e) { console.error(e); alert("Upload failed."); } finally { btn.innerHTML = originalText; btn.disabled = false; }
}

// --- CURATED CV LOGIC ---

async function openCVInterview(index) {
    const job = window.currentJobs[index];
    const modal = document.getElementById('cvModal');
    const loading = document.getElementById('cv-loading');
    const questionsDiv = document.getElementById('cv-questions');

    if (!modal || !loading || !questionsDiv) {
        console.error("CV Modal elements not found");
        return;
    }

    modal.classList.remove('hidden');
    questionsDiv.innerHTML = '';
    loading.classList.remove('hidden');
    const generateBtn = document.getElementById('btn-generate-cv');
    if (generateBtn) generateBtn.style.display = 'none';

    try {
        // 1. Call the Gap-Fill Endpoint
        const res = await fetch('/api/gap-fill-interview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: job.id })
        });

        const data = await res.json();
        loading.classList.add('hidden');
        document.getElementById('btn-generate-cv').style.display = 'flex';

        // 2. Render Questions
        if (data.missing_skills && data.missing_skills.length > 0) {
            questionsDiv.innerHTML = `<div class="bg-yellow-50 p-4 rounded-lg border border-yellow-100 mb-4 text-sm text-yellow-800">
                <i class="fas fa-lightbulb mr-2"></i> We found <strong>${data.missing_skills.length} gaps</strong>. 
                Briefly explain your experience with them to add them to your CV.
            </div>`;

            data.missing_skills.forEach((skill, i) => {
                const qHtml = `
                <div class="gap-item">
                    <label class="block font-bold text-gray-700 mb-2">
                        Do you have experience with <span class="text-indigo-600">${skill}</span>?
                    </label>
                    <textarea id="gap-answer-${i}" class="w-full p-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none text-sm" rows="2" placeholder="e.g. Yes, I used ${skill} to build... (Leave blank if No)"></textarea>
                    <input type="hidden" id="gap-skill-${i}" value="${skill}">
                </div>`;
                questionsDiv.insertAdjacentHTML('beforeend', qHtml);
            });
        } else {
            questionsDiv.innerHTML = `<div class="text-center py-4 text-green-600 font-bold">
                <i class="fas fa-check-circle text-2xl mb-2"></i><br>
                Great match! No major gaps found.
            </div>`;
        }

        // Attach Generate Listener
        document.getElementById('btn-generate-cv').onclick = () => generateFinalCV(job.id, data.missing_skills ? data.missing_skills.length : 0);

    } catch (e) {
        console.error(e);
        loading.innerHTML = `<p class="text-red-500">Error analyzing gaps.</p>`;
    }
}

// --- HELPER: Print the CV (Must be global to be called by button) ---
window.printCV = function () {
    const content = window.generatedCVContent; // Access stored content
    if (!content) return;

    const win = window.open("", "Print CV", "width=850,height=1100");
    win.document.write(content);
    win.document.close();
    // Wait for content to load then print
    setTimeout(() => {
        win.focus();
        win.print();
    }, 500);
};

// --- MAIN GENERATION FUNCTION ---
async function generateFinalCV(jobId, gapCount) {
    const btn = document.getElementById('btn-generate-cv');
    const questionsDiv = document.getElementById('cv-questions');
    const originalText = btn.innerHTML;

    // 1. Loading State
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Writing CV...';
    btn.disabled = true;

    // 2. Collect Answers (if any)
    const gap_answers = [];
    for (let i = 0; i < gapCount; i++) {
        const skillEl = document.getElementById(`gap-skill-${i}`);
        const answerEl = document.getElementById(`gap-answer-${i}`);
        if (skillEl && answerEl && answerEl.value.trim().length > 0) {
            gap_answers.push({ skill: skillEl.value, experience: answerEl.value });
        }
    }

    try {
        // 3. Call API
        const res = await fetch('/api/generate-curated-cv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: jobId, gap_answers: gap_answers })
        });

        if (!res.ok) throw new Error("Server returned error");

        const data = await res.json();

        // 4. Store Content Globally (for the print button)
        window.generatedCVContent = data.cv_html;

        // 5. Render Preview INSIDE the Modal (Bypasses Pop-up Blocker)
        questionsDiv.innerHTML = `
            <div class="text-center mb-2 text-green-600 font-bold">
                <i class="fas fa-check-circle"></i> CV Generated! Preview below:
            </div>
            <div class="bg-white border border-gray-300 p-8 rounded shadow-inner overflow-y-auto max-h-[50vh] text-left font-serif text-sm leading-relaxed">
                ${data.cv_html}
            </div>
        `;

        // 6. Change "Generate" button to "Download"
        btn.innerHTML = '<i class="fas fa-file-pdf mr-2"></i> Download / Print PDF';
        btn.classList.remove('bg-indigo-600', 'hover:bg-indigo-700');
        btn.classList.add('bg-green-600', 'hover:bg-green-700');
        btn.onclick = window.printCV; // Switch the button action
        btn.disabled = false;

    } catch (e) {
        console.error(e);
        alert("Error generating CV. Please check the terminal for details.");
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

// --- INTERVIEW SIMULATOR LOGIC (ROBUST VERSION) ---

let recognition;
let interviewHistory = [];
let currentJobId = null;
let questionCount = 0;

// 1. Initialize Speech on Load
function initSpeech() {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        recognition.onstart = () => {
            const btn = document.getElementById('btn-mic');
            if (btn) btn.classList.add('bg-red-100', 'text-red-600', 'animate-pulse', 'border-red-500');
            document.getElementById('status-text').innerText = "Listening...";
        };

        recognition.onend = () => {
            const btn = document.getElementById('btn-mic');
            if (btn) btn.classList.remove('bg-red-100', 'text-red-600', 'animate-pulse', 'border-red-500');
            document.getElementById('status-text').innerText = "Click mic to speak";
        };

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            document.getElementById('user-response-input').value = transcript;
        };

        recognition.onerror = (event) => {
            console.error("Speech Error:", event.error);
            document.getElementById('status-text').innerText = "Error: " + event.error;
        };
    } else {
        console.warn("Speech API not supported in this browser");
    }
}

// 2. Start Interview Function
window.startInterview = async function (jobIndex) {
    const job = window.currentJobs[jobIndex];
    if (!job) {
        console.error("Job not found at index:", jobIndex);
        return;
    }
    currentJobId = job.id;
    interviewHistory = [];
    questionCount = 1;

    const interviewModal = document.getElementById('interviewModal');
    const interviewChat = document.getElementById('interview-chat');
    const interviewReport = document.getElementById('interview-report');
    const interviewControls = document.getElementById('interview-controls');

    if (!interviewModal || !interviewChat) {
        console.error("Interview modal elements not found");
        return;
    }

    interviewModal.classList.remove('hidden');
    interviewChat.innerHTML = '';
    if (interviewReport) interviewReport.classList.add('hidden');
    if (interviewControls) interviewControls.classList.remove('hidden');

    if (!recognition) initSpeech();

    addMessage('ai', 'Reading your resume and the job description...');

    try {
        const res = await fetch('/api/interview/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: job.id })
        });
        const data = await res.json();

        document.getElementById('interview-chat').innerHTML = '';
        addMessage('ai', data.question);
        interviewHistory.push({ role: 'ai', content: data.question });

        document.getElementById('q-counter').innerText = "1";

    } catch (e) {
        addMessage('system', 'Error starting interview. Check console.');
        console.error(e);
    }
};

// 3. Toggle Mic (Called by HTML)
window.toggleMic = function () {
    if (!recognition) initSpeech();
    if (recognition) {
        try { recognition.start(); }
        catch (e) { console.log("Mic already active"); }
    } else {
        alert("Microphone not supported in this browser.");
    }
};

// 4. Handle Send (Called by HTML)
window.handleSend = async function () {
    const input = document.getElementById('user-response-input');
    const answer = input.value.trim();
    if (!answer) return;

    addMessage('user', answer);
    interviewHistory.push({ role: 'user', content: answer });
    input.value = '';

    if (questionCount >= 5) {
        finishInterview();
        return;
    }

    addMessage('system', 'Analyzing answer...');

    try {
        const res = await fetch('/api/interview/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: currentJobId, history: interviewHistory })
        });
        const data = await res.json();

        const chat = document.getElementById('interview-chat');
        if (chat.lastElementChild.innerText.includes('Analyzing')) {
            chat.lastElementChild.remove();
        }

        if (data.question) {
            addMessage('ai', data.question);
            interviewHistory.push({ role: 'ai', content: data.question });
            questionCount++;
            document.getElementById('q-counter').innerText = questionCount;
        } else {
            finishInterview();
        }
    } catch (e) {
        console.error(e);
        addMessage('system', 'Error fetching reply.');
    }
};

// 5. Helpers
function addMessage(role, text) {
    const chat = document.getElementById('interview-chat');
    let html = '';
    if (role === 'ai') {
        html = `<div class="flex justify-start mb-4"><div class="bg-white border border-gray-200 p-4 rounded-2xl rounded-tl-none max-w-[80%] shadow-sm text-gray-800 font-medium">${text}</div></div>`;
    } else if (role === 'user') {
        html = `<div class="flex justify-end mb-4"><div class="bg-indigo-600 text-white p-4 rounded-2xl rounded-tr-none max-w-[80%] shadow-md">${text}</div></div>`;
    } else {
        html = `<div class="text-center text-xs text-gray-400 italic my-2">${text}</div>`;
    }
    chat.insertAdjacentHTML('beforeend', html);
    chat.scrollTop = chat.scrollHeight;
}

async function finishInterview() {
    document.getElementById('interview-controls').classList.add('hidden');
    addMessage('system', 'Generating Performance Report...');

    try {
        const res = await fetch('/api/interview/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: currentJobId, history: interviewHistory })
        });
        const data = await res.json();
        renderReport(data);
    } catch (e) {
        alert("Error generating report");
    }
}

function renderReport(data) {
    document.getElementById('interview-report').classList.remove('hidden');

    const ctx = document.getElementById('scoreChart').getContext('2d');
    if (window.myRadarChart) window.myRadarChart.destroy();

    window.myRadarChart = new Chart(ctx, {
        type: 'radar',
        data: {
            labels: ['Technical', 'Clarity', 'STAR Format', 'Culture'],
            datasets: [{
                label: 'Your Score',
                data: [
                    data.scores.technical_accuracy,
                    data.scores.communication_clarity,
                    data.scores.star_format_adherence,
                    data.scores.cultural_fit
                ],
                backgroundColor: 'rgba(79, 70, 229, 0.2)',
                borderColor: 'rgba(79, 70, 229, 1)',
                borderWidth: 2
            }]
        },
        options: {
            scales: { r: { beginAtZero: true, max: 100 } }
        }
    });

    const avg = Object.values(data.scores).reduce((a, b) => a + b, 0) / 4;
    document.getElementById('report-verdict').innerText = avg > 75 ? "Excellent! You are ready." : "Good effort. Focus on the improvements below.";

    document.getElementById('report-strengths').innerHTML = data.feedback_points.strengths.map(x => `<li>${x}</li>`).join('');
    document.getElementById('report-improvements').innerHTML = data.feedback_points.improvements.map(x => `<li>${x}</li>`).join('');
}

window.closeInterview = function () {
    document.getElementById('interviewModal').classList.add('hidden');
};

// --- COLD EMAIL LOGIC (Modal-First UX) ---

async function openEmailDrafter(index) {
    const job = window.currentJobs[index];

    // Create email modal if it doesn't exist (same pattern as generatePack)
    if (!document.getElementById('emailModal')) {
        const modalHTML = `
        <div id="emailModal" class="fixed inset-0 bg-gray-900 bg-opacity-50 hidden flex items-center justify-center z-50">
            <div class="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4 flex flex-col max-h-[90vh]">
                <div class="p-6 border-b border-gray-100 flex justify-between items-center bg-teal-50 rounded-t-xl">
                    <h3 class="text-xl font-bold text-gray-800">📧 Cold Email Draft</h3>
                    <button onclick="document.getElementById('emailModal').classList.add('hidden')" class="text-gray-400 hover:text-gray-600"><i class="fas fa-times text-xl"></i></button>
                </div>
                <div class="p-6 overflow-y-auto space-y-4">
                    <div>
                        <label class="block text-sm font-semibold text-gray-700 mb-2">Subject Line</label>
                        <input id="email-subject" type="text" class="w-full p-3 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-teal-500 outline-none">
                    </div>
                    <div>
                        <label class="block text-sm font-semibold text-gray-700 mb-2">Email Body</label>
                        <textarea id="email-body" class="w-full h-48 p-4 border border-gray-300 rounded-lg font-mono text-sm leading-relaxed focus:ring-2 focus:ring-teal-500 outline-none"></textarea>
                    </div>
                </div>
                <div class="p-6 border-t border-gray-100 bg-gray-50 rounded-b-xl flex justify-end space-x-3">
                    <button onclick="document.getElementById('emailModal').classList.add('hidden')" class="px-4 py-2 text-gray-600 font-medium hover:bg-gray-100 rounded-lg">Close</button>
                    <button onclick="copyEmail()" class="px-4 py-2 bg-teal-600 text-white font-medium rounded-lg hover:bg-teal-700 shadow-sm">Copy to Clipboard</button>
                </div>
            </div>
        </div>`;
        document.body.insertAdjacentHTML('beforeend', modalHTML);
    }

    // Open modal immediately (no lag!)
    const modal = document.getElementById('emailModal');
    const subjectEl = document.getElementById('email-subject');
    const bodyEl = document.getElementById('email-body');

    modal.classList.remove('hidden');
    subjectEl.value = "Generating subject...";
    bodyEl.value = "✨ Generating cold email draft...\n\nPlease wait while AI crafts your personalized outreach.";

    // THEN fetch the API
    try {
        const res = await fetch('/api/generate-cold-email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: job.id })
        });

        if (!res.ok) throw new Error("Failed to generate");

        const data = await res.json();
        subjectEl.value = data.subject;
        bodyEl.value = data.body;

    } catch (e) {
        subjectEl.value = "Error";
        bodyEl.value = "Error generating email. Please try again.";
        console.error(e);
    }
}

function copyEmail() {
    const sub = document.getElementById('email-subject').value;
    const body = document.getElementById('email-body').value;
    const text = `Subject: ${sub}\n\n${body}`;

    navigator.clipboard.writeText(text).then(() => {
        alert("Copied to clipboard!");
    });
}

// --- DEADLINE LOGIC ---

async function updateDeadline() {
    const dateVal = document.getElementById('job-deadline').value;
    const jobId = window.currentJobId;

    try {
        const res = await fetch('/api/update-deadline', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: jobId, due_date: dateVal })
        });

        if (res.ok) {
            // Update local state and re-render to show badge
            const jobIndex = window.currentJobs.findIndex(j => j.id === jobId);
            if (jobIndex > -1) {
                window.currentJobs[jobIndex].due_date = dateVal;
                loadMyBoard(); // Refresh the board
                updateDeadlineBadge(dateVal);
            }
        }
    } catch (e) {
        console.error("Error updating deadline", e);
    }
}

function updateDeadlineBadge(dateStr) {
    const badge = document.getElementById('deadline-status');
    if (!badge) return;

    if (!dateStr) {
        badge.classList.add('hidden');
        return;
    }

    const daysLeft = Math.ceil((new Date(dateStr) - new Date()) / (1000 * 60 * 60 * 24));
    badge.classList.remove('hidden', 'bg-red-100', 'text-red-800', 'bg-yellow-100', 'text-yellow-800', 'bg-green-100', 'text-green-800', 'bg-gray-100', 'text-gray-600');

    if (daysLeft < 0) {
        badge.innerText = "Expired";
        badge.classList.add('bg-gray-100', 'text-gray-600');
    } else if (daysLeft <= 3) {
        badge.innerText = `Urgent: ${daysLeft} days left`;
        badge.classList.add('bg-red-100', 'text-red-800');
    } else if (daysLeft <= 7) {
        badge.innerText = `${daysLeft} days left`;
        badge.classList.add('bg-yellow-100', 'text-yellow-800');
    } else {
        badge.innerText = `Due: ${dateStr}`;
        badge.classList.add('bg-green-100', 'text-green-800');
    }
}

// --- PROFILE MANAGEMENT ---
async function loadProfile() {
    try {
        const res = await fetch('/api/get-profile');
        const data = await res.json();

        if (data.resume_text) {
            document.getElementById('inp-resume').value = data.resume_text;
        }
        if (data.skills) {
            document.getElementById('inp-skills').value = data.skills;
        }

        // Wire up save button
        const saveBtn = document.getElementById('btn-save-profile');
        if (saveBtn) {
            saveBtn.onclick = saveProfile;
        }
    } catch (e) {
        console.error("Error loading profile:", e);
    }
}

async function saveProfile() {
    const btn = document.getElementById('btn-save-profile');
    const originalText = btn.innerText;
    btn.innerText = "Saving...";
    btn.disabled = true;

    const resumeText = document.getElementById('inp-resume').value;
    const skills = document.getElementById('inp-skills').value;

    try {
        await fetch('/api/save-profile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ resume_text: resumeText, skills: skills })
        });

        btn.innerText = "✓ Saved!";
        btn.classList.replace('bg-gray-900', 'bg-green-600');

        setTimeout(() => {
            btn.innerText = originalText;
            btn.classList.replace('bg-green-600', 'bg-gray-900');
            btn.disabled = false;
        }, 3500);
    } catch (e) {
        console.error("Error saving profile:", e);
        btn.innerText = "Error";
        btn.disabled = false;
    }
}

// --- MY BOARD (Saved Jobs) ---
async function loadMyBoard() {
    const container = document.getElementById('section-my-board');
    if (!container) return;

    // Show loading state
    container.innerHTML = `
        <div class="text-center py-20">
            <i class="fas fa-spinner fa-spin text-4xl text-blue-500 mb-4"></i>
            <p class="text-gray-600">Loading saved jobs...</p>
        </div>`;

    try {
        const res = await fetch('/api/saved-jobs');
        const data = await res.json();

        // Robustly extract the array (API might return wrapped object)
        let jobs = Array.isArray(data) ? data : (data.saved_jobs || data.jobs || []);
        console.log("Loaded jobs array:", jobs);

        // Clear and populate savedJobUrls for heart sync - filter out bad data
        window.savedJobUrls = new Set();
        jobs.forEach(job => {
            const url = job.url || job.link || '';
            // Only add valid URLs (not empty, not '#')
            if (url && url !== '#' && url.length > 1) {
                window.savedJobUrls.add(url);
            }
        });
        console.log("savedJobUrls populated:", window.savedJobUrls.size, "valid URLs");

        if (jobs.length === 0) {
            container.innerHTML = `
                <div class="text-center py-20 bg-white rounded-xl border border-gray-200 border-dashed">
                    <i class="fas fa-columns text-4xl text-gray-300 mb-4"></i>
                    <h2 class="text-2xl font-bold text-gray-400">No Saved Jobs</h2>
                    <p class="text-gray-400 mt-2">Search and save jobs to see them here.</p>
                </div>`;
            return;
        }

        // Refactored Kanban to dynamic generation with 5 columns
        const statuses = ['Saved', 'Applied', 'Interviewing', 'Offer', 'Rejected'];
        const statusColors = {
            'Saved': { bg: 'bg-blue-50', border: 'border-blue-200', header: 'bg-blue-100 text-blue-800' },
            'Applied': { bg: 'bg-yellow-50', border: 'border-yellow-200', header: 'bg-yellow-100 text-yellow-800' },
            'Interviewing': { bg: 'bg-purple-50', border: 'border-purple-200', header: 'bg-purple-100 text-purple-800' },
            'Offer': { bg: 'bg-green-50', border: 'border-green-200', header: 'bg-green-100 text-green-800' },
            'Rejected': { bg: 'bg-red-50', border: 'border-red-200', header: 'bg-red-100 text-red-800' }
        };

        container.innerHTML = `
            <div class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
                ${statuses.map(status => `
                    <div class="kanban-column ${statusColors[status].bg} rounded-xl ${statusColors[status].border} border-2 p-3 min-h-[350px]">
                        <div class="flex items-center justify-between mb-3">
                            <h3 class="font-bold text-xs ${statusColors[status].header} px-2 py-1 rounded-lg">${status}</h3>
                            <span id="col-count-${status}" class="text-xs text-gray-500 px-2 py-0.5 bg-white rounded-full">0</span>
                        </div>
                        <div id="kanban-${status}" class="space-y-2"></div>
                    </div>
                `).join('')}
            </div>
        `;

        // Store jobs globally for Kanban
        window.currentJobs = jobs;

        // Populate each column with null safety checks
        statuses.forEach(status => {
            const columnEl = document.getElementById(`kanban-${status}`);
            const countEl = document.getElementById(`col-count-${status}`);

            if (!columnEl) {
                console.error(`Column element not found: kanban-${status}`);
                return;
            }

            const statusJobs = jobs.filter(j => (j.status || 'Saved') === status);
            if (countEl) countEl.textContent = statusJobs.length;

            statusJobs.forEach((job, idx) => {
                const card = createKanbanCard(job, jobs.indexOf(job));
                columnEl.appendChild(card);
            });
        });

    } catch (e) {
        console.error("Error loading My Board:", e);
        container.innerHTML = `
            <div class="text-center py-20 text-red-500">
                <i class="fas fa-exclamation-triangle text-4xl mb-4"></i>
                <p>Failed to load saved jobs.</p>
            </div>`;
    }
}

// Create a compact Kanban card with status dropdown and action buttons
function createKanbanCard(job, index) {
    const card = document.createElement('div');
    card.className = 'bg-white rounded-lg shadow-sm border border-gray-200 p-3 hover:shadow-md transition';

    const title = job.title || 'Untitled Role';
    const company = job.company || 'Unknown Company';
    const jobId = job.id || index;
    const currentStatus = job.status || 'Saved';

    card.innerHTML = `
        <h4 class="font-semibold text-gray-900 text-sm line-clamp-2 mb-1">${title}</h4>
        <p class="text-xs text-gray-500 mb-3"><i class="fas fa-building mr-1"></i>${company}</p>
        
        <!-- Action Buttons 2x2 Grid with Text Labels -->
        <div class="grid grid-cols-2 gap-2 mb-3">
            <button onclick="generatePack(${index})" class="py-1.5 px-2 bg-blue-600 text-white text-xs font-medium rounded hover:bg-blue-700 transition">
                Cover Letter
            </button>
            <button onclick="openCVInterview(${index})" class="py-1.5 px-2 bg-indigo-600 text-white text-xs font-medium rounded hover:bg-indigo-700 transition">
                Tailor CV
            </button>
            <button onclick="startInterview(${index})" class="py-1.5 px-2 bg-pink-600 text-white text-xs font-medium rounded hover:bg-pink-700 transition">
                Practice
            </button>
            <button onclick="openEmailDrafter(${index})" class="py-1.5 px-2 bg-teal-600 text-white text-xs font-medium rounded hover:bg-teal-700 transition">
                Email
            </button>
        </div>
        
        <div class="flex items-center justify-between text-xs">
            <select onchange="updateJobStatus(${jobId}, this.value)" 
                class="text-xs px-2 py-1 rounded border border-gray-200 bg-gray-50 cursor-pointer outline-none flex-1 mr-2">
                <option value="Saved" ${currentStatus === 'Saved' ? 'selected' : ''}>Saved</option>
                <option value="Applied" ${currentStatus === 'Applied' ? 'selected' : ''}>Applied</option>
                <option value="Interviewing" ${currentStatus === 'Interviewing' ? 'selected' : ''}>Interviewing</option>
                <option value="Offer" ${currentStatus === 'Offer' ? 'selected' : ''}>Offer</option>
                <option value="Rejected" ${currentStatus === 'Rejected' ? 'selected' : ''}>Rejected</option>
            </select>
            
            <div class="flex space-x-1">
                <button onclick="openJobDetails(${index})" class="text-blue-500 hover:text-blue-700 p-1" title="View Details">
                    <i class="fas fa-eye text-xs"></i>
                </button>
                <button onclick="deleteJob(${jobId})" class="text-gray-400 hover:text-red-500 p-1" title="Delete">
                    <i class="fas fa-trash-alt text-xs"></i>
                </button>
            </div>
        </div>
    `;
    return card;
}

// Update job status via API
async function updateJobStatus(jobId, newStatus) {
    console.log("Updating job", jobId, "to status:", newStatus);
    try {
        const res = await fetch('/api/update-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: jobId, status: newStatus })
        });

        if (res.ok) {
            // Reload Kanban to reflect changes
            loadMyBoard();
        } else {
            console.error("Failed to update status:", res.status);
        }
    } catch (e) {
        console.error("Error updating status:", e);
    }
}