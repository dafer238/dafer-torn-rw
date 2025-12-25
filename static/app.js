/**
 * Torn Ranked War Tracker - Frontend Application
 * 
 * Polls backend every 1 second for real-time updates.
 * Handles client-side countdown timers for smooth UX.
 */

// Configuration
const CONFIG = {
    POLL_INTERVAL: 1000,
    TIMER_INTERVAL: 100,
    API_BASE: '/api',
    TOAST_DURATION: 3000,
};

// State
let state = {
    targets: [],
    claims: [],
    lastUpdate: 0,
    userId: null,
    userName: null,
    apiKey: null,
    maxClaimsPerUser: 3,
    filters: {
        hospital: 'all',
        claim: 'all',
        online: 'all',
        travel: 'all'
    },
    sortBy: 'timer',
    sortDir: 'asc',
    isConnected: true,
    timerInterval: null,
    pollInterval: null,
};

// DOM Elements
const elements = {};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    cacheElements();
    loadConfig();
    setupEventListeners();
    startPolling();
    startTimers();
});

function cacheElements() {
    elements.targetList = document.getElementById('target-list');
    elements.connectionStatus = document.getElementById('connection-status');
    elements.lastUpdate = document.getElementById('last-update');
    elements.apiCalls = document.getElementById('api-calls');
    elements.totalTargets = document.getElementById('total-targets');
    elements.inHospital = document.getElementById('in-hospital');
    elements.outHospital = document.getElementById('out-hospital');
    elements.claimedCount = document.getElementById('claimed-count');
    elements.travelingCount = document.getElementById('traveling-count');
    elements.myClaimsCount = document.getElementById('my-claims-count');
    elements.configPanel = document.getElementById('config-panel');
    elements.userId = document.getElementById('user-id');
    elements.userName = document.getElementById('user-name');
    elements.apiKey = document.getElementById('api-key');
    elements.toastContainer = document.getElementById('toast-container');
    elements.targetTable = document.getElementById('target-table');
}

function loadConfig() {
    state.userId = localStorage.getItem('tornUserId');
    state.userName = localStorage.getItem('tornUserName');
    state.apiKey = localStorage.getItem('tornApiKey');
    
    if (state.userId) elements.userId.value = state.userId;
    if (state.userName) elements.userName.value = state.userName;
    if (state.apiKey) elements.apiKey.value = state.apiKey;
    
    if (!state.userId || !state.userName || !state.apiKey) {
        elements.configPanel.classList.add('visible');
    }
}

function saveConfig() {
    state.userId = elements.userId.value;
    state.userName = elements.userName.value;
    state.apiKey = elements.apiKey.value;
    
    if (state.userId && state.userName && state.apiKey) {
        localStorage.setItem('tornUserId', state.userId);
        localStorage.setItem('tornUserName', state.userName);
        localStorage.setItem('tornApiKey', state.apiKey);
        elements.configPanel.classList.remove('visible');
        showToast('Configuration saved!', 'success');
    } else {
        showToast('Please enter API key, ID and name', 'error');
    }
}

function setupEventListeners() {
    // Config
    document.getElementById('save-config').addEventListener('click', saveConfig);
    document.getElementById('toggle-config').addEventListener('click', () => {
        elements.configPanel.classList.toggle('visible');
    });
    
    // Refresh
    document.getElementById('refresh-btn').addEventListener('click', () => fetchStatus(true));
    
    // Filter buttons
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const filterType = e.target.dataset.filterType;
            const value = e.target.dataset.value;
            
            // Update button states for this filter group
            document.querySelectorAll(`.filter-btn[data-filter-type="${filterType}"]`)
                .forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            
            // Update state
            state.filters[filterType] = value;
            renderTargets();
        });
    });
    
    // Stats bar click filtering
    document.querySelectorAll('.stat.clickable').forEach(stat => {
        stat.addEventListener('click', (e) => {
            const filter = e.currentTarget.dataset.statFilter;
            applyStatFilter(filter);
        });
    });
    
    // Sortable headers
    document.querySelectorAll('.target-table th.sortable').forEach(th => {
        th.addEventListener('click', (e) => {
            const sortKey = e.currentTarget.dataset.sort;
            
            if (state.sortBy === sortKey) {
                state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
            } else {
                state.sortBy = sortKey;
                state.sortDir = 'asc';
            }
            
            updateSortIndicators();
            renderTargets();
        });
    });
}

function applyStatFilter(filter) {
    // Reset all filters
    state.filters = { hospital: 'all', claim: 'all', online: 'all', travel: 'all' };
    
    // Apply specific filter
    switch (filter) {
        case 'hospital':
            state.filters.hospital = 'in';
            break;
        case 'out':
            state.filters.hospital = 'out';
            break;
        case 'claimed':
            state.filters.claim = 'claimed';
            break;
        case 'traveling':
            state.filters.travel = 'traveling';
            break;
        case 'total':
        default:
            // All filters already reset
            break;
    }
    
    // Update UI buttons
    updateFilterButtons();
    renderTargets();
}

function updateFilterButtons() {
    Object.keys(state.filters).forEach(filterType => {
        document.querySelectorAll(`.filter-btn[data-filter-type="${filterType}"]`)
            .forEach(btn => {
                btn.classList.toggle('active', btn.dataset.value === state.filters[filterType]);
            });
    });
}

function updateSortIndicators() {
    document.querySelectorAll('.target-table th.sortable').forEach(th => {
        const sortKey = th.dataset.sort;
        const icon = th.querySelector('.sort-icon');
        
        if (sortKey === state.sortBy) {
            th.classList.add('sorted');
            icon.textContent = state.sortDir === 'asc' ? '▼' : '▲';
        } else {
            th.classList.remove('sorted');
            icon.textContent = '';
        }
    });
}

function startPolling() {
    fetchStatus();
    state.pollInterval = setInterval(fetchStatus, CONFIG.POLL_INTERVAL);
}

function startTimers() {
    state.timerInterval = setInterval(updateTimers, CONFIG.TIMER_INTERVAL);
}

async function fetchStatus(forceRefresh = false) {
    // Don't fetch if no API key configured
    if (!state.apiKey) {
        updateConnectionStatus(false, 'No API key');
        return;
    }
    
    try {
        const url = forceRefresh 
            ? `${CONFIG.API_BASE}/status?force_refresh=true`
            : `${CONFIG.API_BASE}/status`;
        
        const response = await fetch(url, {
            headers: {
                'X-API-Key': state.apiKey
            }
        });
        
        if (response.status === 401) {
            showToast('Invalid API key', 'error');
            elements.configPanel.classList.add('visible');
            return;
        }
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const data = await response.json();
        
        // Get max claims config
        if (data.max_claims_per_user !== undefined) {
            state.maxClaimsPerUser = data.max_claims_per_user;
        }
        
        state.targets = data.targets || [];
        state.claims = data.active_claims || [];
        state.lastUpdate = data.last_updated;
        state.isConnected = true;
        
        updateConnectionStatus(true);
        updateStats(data);
        updateApiInfo(data);
        renderTargets();
        updateTimers();  // Immediately update timers after render
        
    } catch (error) {
        console.error('Fetch error:', error);
        state.isConnected = false;
        updateConnectionStatus(false);
    }
}

function updateConnectionStatus(connected, message = null) {
    if (connected) {
        elements.connectionStatus.textContent = '● Connected';
        elements.connectionStatus.className = 'status-indicator connected';
    } else {
        elements.connectionStatus.textContent = message ? `● ${message}` : '● Disconnected';
        elements.connectionStatus.className = 'status-indicator disconnected';
    }
}

function updateStats(data) {
    elements.totalTargets.textContent = data.total_targets || 0;
    elements.inHospital.textContent = data.in_hospital || 0;
    elements.outHospital.textContent = data.out_of_hospital || 0;
    elements.claimedCount.textContent = data.claimed || 0;
    
    // Count traveling
    const traveling = state.targets.filter(t => t.traveling).length;
    elements.travelingCount.textContent = traveling;
    
    // Count my claims
    const myClaims = state.userId 
        ? state.targets.filter(t => t.claimed_by_id === parseInt(state.userId)).length
        : 0;
    elements.myClaimsCount.textContent = myClaims;
}

function updateApiInfo(data) {
    const age = data.cache_age_seconds ? data.cache_age_seconds.toFixed(1) : '0.0';
    elements.lastUpdate.textContent = `Data: ${age}s`;
    elements.apiCalls.textContent = `API: ${data.api_calls_remaining || '--'}/100`;
}

function updateTimers() {
    // Use current time in seconds (UTC)
    const now = Math.floor(Date.now() / 1000);
    
    document.querySelectorAll('tr[data-hospital-until]').forEach(row => {
        const hospitalUntil = parseInt(row.dataset.hospitalUntil) || 0;
        const timerCell = row.querySelector('.timer-cell');
        
        if (!timerCell) return;
        
        // Calculate remaining time: hospital_until is UTC timestamp from Torn
        const remaining = hospitalUntil > 0 ? Math.max(0, hospitalUntil - now) : 0;
        
        if (remaining <= 0) {
            timerCell.textContent = 'OUT';
            timerCell.className = 'timer-cell out';
            row.classList.remove('in-hospital', 'about-to-exit');
            row.classList.add('out');
        } else {
            timerCell.textContent = formatTime(remaining);
            
            if (remaining <= 10) {
                timerCell.className = 'timer-cell critical';
                row.classList.add('about-to-exit');
            } else if (remaining <= 30) {
                timerCell.className = 'timer-cell warning';
                row.classList.add('about-to-exit');
            } else {
                timerCell.className = 'timer-cell safe';
            }
        }
    });
}

function formatTime(seconds) {
    if (seconds <= 0) return 'OUT';
    
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    
    if (h > 0) {
        return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function filterTargets(targets) {
    return targets.filter(t => {
        // Hospital filter
        if (state.filters.hospital === 'in' && t.hospital_status === 'out') return false;
        if (state.filters.hospital === 'out' && t.hospital_status !== 'out') return false;
        
        // Claim filter
        if (state.filters.claim === 'unclaimed' && t.claimed_by) return false;
        if (state.filters.claim === 'claimed' && !t.claimed_by) return false;
        
        // Online filter
        if (state.filters.online === 'online' && t.estimated_online !== 'online') return false;
        if (state.filters.online === 'offline' && t.estimated_online === 'online') return false;
        
        // Travel filter
        if (state.filters.travel === 'local' && t.traveling) return false;
        if (state.filters.travel === 'traveling' && !t.traveling) return false;
        
        return true;
    });
}

function sortTargets(targets) {
    const sorted = [...targets];
    const dir = state.sortDir === 'asc' ? 1 : -1;
    
    sorted.sort((a, b) => {
        let cmp = 0;
        
        switch (state.sortBy) {
            case 'timer':
                // Out first (0), then by remaining time
                const aOut = a.hospital_status === 'out' ? 0 : 1;
                const bOut = b.hospital_status === 'out' ? 0 : 1;
                if (aOut !== bOut) {
                    cmp = aOut - bOut;
                } else {
                    cmp = (a.hospital_remaining || 0) - (b.hospital_remaining || 0);
                }
                break;
            case 'name':
                cmp = a.name.localeCompare(b.name);
                break;
            case 'level':
                cmp = a.level - b.level;
                break;
            case 'online':
                const onlineOrder = { online: 0, idle: 1, offline: 2, unknown: 3 };
                cmp = (onlineOrder[a.estimated_online] || 3) - (onlineOrder[b.estimated_online] || 3);
                break;
        }
        
        return cmp * dir;
    });
    
    return sorted;
}

function renderTargets() {
    let targets = filterTargets(state.targets);
    targets = sortTargets(targets);
    
    if (targets.length === 0) {
        elements.targetList.innerHTML = `
            <tr><td colspan="7" class="loading">
                ${state.targets.length === 0 
                    ? 'No targets loaded. Check API configuration.' 
                    : 'No targets match the current filters.'}
            </td></tr>
        `;
        return;
    }
    
    const html = targets.map(target => renderTargetRow(target)).join('');
    elements.targetList.innerHTML = html;
    
    // Attach event listeners
    document.querySelectorAll('.claim-btn').forEach(btn => {
        btn.addEventListener('click', () => handleClaim(btn.dataset.targetId));
    });
    
    document.querySelectorAll('.unclaim-btn').forEach(btn => {
        btn.addEventListener('click', () => handleUnclaim(btn.dataset.targetId));
    });
}

function renderTargetRow(target) {
    // Calculate remaining for row classes only (updateTimers will handle display)
    const now = Math.floor(Date.now() / 1000);
    const hospitalUntil = target.hospital_until || 0;
    const remaining = hospitalUntil > 0 ? Math.max(0, hospitalUntil - now) : 0;
    const isOut = remaining <= 0 || target.hospital_status === 'out';
    
    const isMyTarget = state.userId && target.claimed_by_id === parseInt(state.userId);
    const isClaimed = !!target.claimed_by;
    const isTraveling = target.traveling;
    
    // Row classes
    let rowClass = '';
    if (isTraveling) rowClass += ' traveling';
    if (isOut) rowClass += ' out';
    else if (remaining <= 30) rowClass += ' about-to-exit';
    if (isClaimed) rowClass += isMyTarget ? ' claimed-by-me' : ' claimed';
    
    // Timer
    let timerClass = 'timer-cell';
    let timerText = 'OUT';
    if (!isOut) {
        timerText = formatTime(remaining);
        if (remaining <= 10) timerClass += ' critical';
        else if (remaining <= 30) timerClass += ' warning';
        else timerClass += ' safe';
    } else {
        timerClass += ' out';
    }
    
    // Online status
    const onlineClass = target.estimated_online || 'unknown';
    const onlineText = { online: 'Online', idle: 'Idle', offline: 'Offline', unknown: '?' }[onlineClass];
    
    // Badges
    let badges = '';
    if (target.medding) badges += '<span class="badge medding">MED</span>';
    if (isTraveling) badges += '<span class="badge traveling">✈</span>';
    
    // Claim button
    let claimButton = '';
    const myClaims = state.userId 
        ? state.targets.filter(t => t.claimed_by_id === parseInt(state.userId)).length
        : 0;
    const atClaimLimit = myClaims >= state.maxClaimsPerUser;
    
    if (!state.userId || !state.userName) {
        claimButton = `<button class="btn btn-claim" disabled>Config</button>`;
    } else if (isMyTarget) {
        claimButton = `<button class="btn btn-unclaim unclaim-btn" data-target-id="${target.user_id}">Release</button>`;
    } else if (isClaimed) {
        claimButton = `<button class="btn btn-claim claimed" disabled>Taken</button>`;
    } else if (atClaimLimit) {
        claimButton = `<button class="btn btn-claim" disabled title="Max ${state.maxClaimsPerUser} claims">Limit</button>`;
    } else {
        claimButton = `<button class="btn btn-claim claim-btn" data-target-id="${target.user_id}">Claim</button>`;
    }
    
    return `
        <tr class="${rowClass}" 
            data-target-id="${target.user_id}" 
            data-hospital-until="${target.hospital_until || 0}">
            <td class="${timerClass}">--:--</td>
            <td class="name-cell">
                <div class="player-links">
                    <a href="https://www.torn.com/profiles.php?XID=${target.user_id}" 
                       target="_blank" rel="noopener" class="profile-link">
                        ${escapeHtml(target.name)}
                    </a>
                    <a href="https://www.torn.com/loader.php?sid=attack&user2ID=${target.user_id}" 
                       target="_blank" rel="noopener" class="attack-link" title="Attack">⚔</a>
                    ${badges}
                </div>
            </td>
            <td>${target.level}</td>
            <td class="online-cell">
                <span class="online-dot ${onlineClass}"></span>
                <span class="online-text">${onlineText}</span>
            </td>
            <td class="reason-cell" title="${escapeHtml(target.hospital_reason || '')}">
                ${escapeHtml(target.hospital_reason || '-')}
            </td>
            <td class="claim-cell">
                ${isClaimed ? escapeHtml(target.claimed_by) : '-'}
            </td>
            <td>${claimButton}</td>
        </tr>
    `;
}

async function handleClaim(targetId) {
    if (!state.userId || !state.userName) {
        showToast('Please configure your user ID and name first', 'error');
        elements.configPanel.classList.add('visible');
        return;
    }
    
    // Check claim limit
    const myClaims = state.targets.filter(t => t.claimed_by_id === parseInt(state.userId)).length;
    if (myClaims >= state.maxClaimsPerUser) {
        showToast(`Maximum ${state.maxClaimsPerUser} claims reached`, 'warning');
        return;
    }
    
    try {
        const response = await fetch(`${CONFIG.API_BASE}/claim`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-API-Key': state.apiKey
            },
            body: JSON.stringify({
                target_id: parseInt(targetId),
                claimer_id: parseInt(state.userId),
                claimer_name: state.userName
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(data.message, 'success');
            fetchStatus(true);
        } else {
            showToast(data.message || 'Failed to claim target', 'error');
        }
    } catch (error) {
        console.error('Claim error:', error);
        showToast('Network error claiming target', 'error');
    }
}

async function handleUnclaim(targetId) {
    if (!state.userId) return;
    
    try {
        const response = await fetch(
            `${CONFIG.API_BASE}/claim/${targetId}?claimer_id=${state.userId}`,
            { 
                method: 'DELETE',
                headers: { 'X-API-Key': state.apiKey }
            }
        );
        
        const data = await response.json();
        
        if (data.success) {
            showToast('Claim released', 'success');
            fetchStatus(true);
        } else {
            showToast(data.detail || 'Failed to release claim', 'error');
        }
    } catch (error) {
        console.error('Unclaim error:', error);
        showToast('Network error releasing claim', 'error');
    }
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    
    elements.toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideIn 0.2s ease reverse';
        setTimeout(() => toast.remove(), 200);
    }, CONFIG.TOAST_DURATION);
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
