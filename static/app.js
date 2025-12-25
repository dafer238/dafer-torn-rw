/**
 * Torn Ranked War Tracker - Frontend Application
 * 
 * Polls backend every 1 second for real-time updates.
 * Handles client-side countdown timers for smooth UX.
 */

// Configuration
const CONFIG = {
    POLL_INTERVAL: 3000,  // 3 seconds to reduce CPU usage
    TIMER_INTERVAL: 1000,  // 1 second for smooth client-side timers
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
        travel: 'all',
        levelMin: null,
        levelMax: null,
        statsMin: 0,
        statsMax: 999999999999
    },
    sortBy: 'timer',
    sortDir: 'asc',
    isConnected: true,
    timerInterval: null,
    pollInterval: null,
    // Prevent concurrent fetches
    isFetching: false,
    fetchRequestId: 0,
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
    elements.levelMin = document.getElementById('level-min');
    elements.levelMax = document.getElementById('level-max');
    elements.statsMin = document.getElementById('stats-min');
    elements.statsMax = document.getElementById('stats-max');
    
    // User status bar elements
    elements.userStatusBar = document.getElementById('user-status-bar');
    elements.healthFill = document.getElementById('health-fill');
    elements.healthText = document.getElementById('health-text');
    elements.energyFill = document.getElementById('energy-fill');
    elements.energyText = document.getElementById('energy-text');
    elements.nerveFill = document.getElementById('nerve-fill');
    elements.nerveText = document.getElementById('nerve-text');
    elements.drugCd = document.getElementById('drug-cd');
    elements.medicalCd = document.getElementById('medical-cd');
    elements.boosterCd = document.getElementById('booster-cd');
    elements.playerState = document.getElementById('player-state');
    elements.playerStatusItem = document.getElementById('player-status-item');
    
    // Chain elements
    elements.chainItem = document.getElementById('chain-item');
    elements.chainCount = document.getElementById('chain-count');
    elements.chainTimer = document.getElementById('chain-timer');
    elements.chainAlertOverlay = document.getElementById('chain-alert-overlay');
    elements.chainAlertText = document.getElementById('chain-alert-text');
    elements.chainAlertCount = document.getElementById('chain-alert-count');
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
    
    // Range filter inputs
    elements.levelMin.addEventListener('change', () => {
        state.filters.levelMin = elements.levelMin.value ? parseInt(elements.levelMin.value) : null;
        renderTargets();
    });
    elements.levelMax.addEventListener('change', () => {
        state.filters.levelMax = elements.levelMax.value ? parseInt(elements.levelMax.value) : null;
        renderTargets();
    });
    elements.statsMin.addEventListener('change', () => {
        state.filters.statsMin = parseInt(elements.statsMin.value) || 0;
        renderTargets();
    });
    elements.statsMax.addEventListener('change', () => {
        state.filters.statsMax = parseInt(elements.statsMax.value) || 999999999999;
        renderTargets();
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
    
    // Chain alert overlay - click to dismiss for current chain count
    if (elements.chainAlertOverlay) {
        elements.chainAlertOverlay.addEventListener('click', () => {
            elements.chainAlertOverlay.classList.remove('visible');
            // Remember the chain count when dismissed - only show again when chain increases
            userStatus.lastDismissedChainCount = userStatus.chain.current;
        });
    }
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
        case 'myclaims':
            state.filters.claim = 'myclaims';
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
    fetchUserStatus();
    state.pollInterval = setInterval(fetchStatus, CONFIG.POLL_INTERVAL);
    // Poll user status every 5 seconds (less frequent to save API calls)
    state.userStatusInterval = setInterval(fetchUserStatus, 5000);
    
    // Pause polling when tab is not visible to save CPU
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            // Tab hidden - clear intervals
            if (state.pollInterval) clearInterval(state.pollInterval);
            if (state.userStatusInterval) clearInterval(state.userStatusInterval);
        } else {
            // Tab visible - restart polling
            fetchStatus();
            fetchUserStatus();
            state.pollInterval = setInterval(fetchStatus, CONFIG.POLL_INTERVAL);
            state.userStatusInterval = setInterval(fetchUserStatus, 5000);
        }
    });
}

function startTimers() {
    // Update all timers every second for smooth countdown
    state.timerInterval = setInterval(() => {
        updateTimers();
        updateUserCooldowns();
        updateChainTimer();
    }, 1000);
}

// User status state
let userStatus = {
    cooldowns: { drug: 0, medical: 0, booster: 0 },  // Store end timestamps (not durations)
    chain: { current: 0, timeout: 0, cooldown: 0 },
    lastFetch: 0,
    lastDismissedChainCount: 0,  // Track chain count when alert was dismissed
};

// Chain bonus milestones
const CHAIN_BONUSES = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000];

function getNextBonus(current) {
    for (const bonus of CHAIN_BONUSES) {
        if (current < bonus) return bonus;
    }
    return null;
}

function getHitsToNextBonus(current) {
    const next = getNextBonus(current);
    return next ? next - current : null;
}

async function fetchUserStatus() {
    if (!state.apiKey) return;
    
    try {
        const response = await fetch(`${CONFIG.API_BASE}/me`, {
            headers: { 'X-API-Key': state.apiKey }
        });
        
        if (!response.ok) return;
        
        const data = await response.json();
        userStatus.lastFetch = Date.now();
        
        // Convert cooldown durations to end timestamps (server sends seconds remaining)
        const now = Math.floor(Date.now() / 1000);
        userStatus.cooldowns = {
            drug: data.cooldowns.drug > 0 ? now + data.cooldowns.drug : 0,
            medical: data.cooldowns.medical > 0 ? now + data.cooldowns.medical : 0,
            booster: data.cooldowns.booster > 0 ? now + data.cooldowns.booster : 0,
        };
        userStatus.chain = data.chain || { current: 0, timeout: 0, cooldown: 0 };
        
        // Update health bar
        if (elements.healthFill && elements.healthText) {
            elements.healthFill.style.width = `${data.health.percent}%`;
            elements.healthText.textContent = `${data.health.current}/${data.health.max}`;
        }
        
        // Update energy bar
        if (elements.energyFill && elements.energyText) {
            elements.energyFill.style.width = `${data.energy.percent}%`;
            elements.energyText.textContent = `${data.energy.current}/${data.energy.max}`;
        }
        
        // Update nerve bar
        if (elements.nerveFill && elements.nerveText) {
            elements.nerveFill.style.width = `${data.nerve.percent}%`;
            elements.nerveText.textContent = `${data.nerve.current}/${data.nerve.max}`;
        }
        
        // Update player status
        if (elements.playerState) {
            const statusState = data.status.state;
            let stateClass = 'okay';
            let stateText = statusState;
            
            if (statusState === 'Hospital') {
                stateClass = 'hospital';
                const remaining = data.status.until - Math.floor(Date.now() / 1000);
                if (remaining > 0) {
                    stateText = `🏥 ${formatCooldown(remaining)}`;
                }
            } else if (statusState === 'Jail') {
                stateClass = 'jail';
                stateText = '⛓️ Jail';
            } else if (data.travel.traveling) {
                stateClass = 'traveling';
                stateText = `✈️ ${data.travel.destination} (${formatCooldown(data.travel.time_left)})`;
            } else if (statusState === 'Okay') {
                stateText = '✅ Ready';
            }
            
            elements.playerState.textContent = stateText;
            elements.playerState.className = `status-state ${stateClass}`;
        }
        
        // Update chain display
        updateChainDisplay();
        
        // Initial cooldown update
        updateUserCooldowns();
        
    } catch (error) {
        console.error('Failed to fetch user status:', error);
    }
}

function updateChainDisplay() {
    const chain = userStatus.chain;
    const current = chain.current || 0;
    const timeout = chain.timeout || 0;
    const cooldown = chain.cooldown || 0;
    
    // Update chain count
    if (elements.chainCount) {
        elements.chainCount.textContent = current.toLocaleString();
        
        const hitsToBonus = getHitsToNextBonus(current);
        if (hitsToBonus !== null && hitsToBonus <= 10) {
            elements.chainCount.classList.add('bonus-close');
        } else {
            elements.chainCount.classList.remove('bonus-close');
        }
    }
    
    // Update chain item styling based on state
    if (elements.chainItem) {
        elements.chainItem.classList.remove('active', 'warning', 'critical');
        
        if (current > 0 && timeout > 0) {
            elements.chainItem.classList.add('active');
            
            // Timer-based warning
            if (timeout <= 60) {
                elements.chainItem.classList.add('critical');
            } else if (timeout <= 120) {
                elements.chainItem.classList.add('warning');
            }
        }
    }
    
    // Check for bonus alert (10 hits away from any bonus)
    checkChainBonusAlert(current);
}

function updateChainTimer() {
    const fetchAge = Math.floor((Date.now() - userStatus.lastFetch) / 1000);
    const timeout = userStatus.chain.timeout || 0;
    const remaining = Math.max(0, timeout - fetchAge);
    const current = userStatus.chain.current || 0;
    
    if (elements.chainTimer) {
        if (current === 0 || timeout === 0) {
            elements.chainTimer.textContent = '--:--';
            elements.chainTimer.className = 'chain-timer';
        } else if (remaining > 0) {
            elements.chainTimer.textContent = formatCooldown(remaining);
            elements.chainTimer.className = 'chain-timer';
            
            if (remaining <= 60) {
                elements.chainTimer.classList.add('critical');
            } else if (remaining <= 120) {
                elements.chainTimer.classList.add('warning');
            }
        } else {
            elements.chainTimer.textContent = 'EXPIRED';
            elements.chainTimer.className = 'chain-timer critical';
        }
    }
    
    // Update chain item styling based on timer
    if (elements.chainItem && current > 0) {
        elements.chainItem.classList.remove('warning', 'critical');
        if (remaining > 0) {
            elements.chainItem.classList.add('active');
            if (remaining <= 60) {
                elements.chainItem.classList.add('critical');
            } else if (remaining <= 120) {
                elements.chainItem.classList.add('warning');
            }
        }
    }
}

function checkChainBonusAlert(current) {
    const hitsToBonus = getHitsToNextBonus(current);
    const nextBonus = getNextBonus(current);
    
    // Only show alert if:
    // 1. We're within 10 hits of a bonus
    // 2. Chain count is greater than 0
    // 3. Chain count has increased since last dismissal (user dismissed at lower count)
    const shouldShowAlert = hitsToBonus !== null && 
                           hitsToBonus <= 10 && 
                           current > 0 && 
                           current > userStatus.lastDismissedChainCount;
    
    if (shouldShowAlert) {
        // Show big alert
        if (elements.chainAlertOverlay) {
            elements.chainAlertOverlay.classList.add('visible');
            
            if (elements.chainAlertText) {
                elements.chainAlertText.textContent = `CHAIN BONUS IN ${hitsToBonus} HITS!`;
            }
            if (elements.chainAlertCount) {
                elements.chainAlertCount.textContent = `${current.toLocaleString()} / ${nextBonus.toLocaleString()}`;
            }
        }
    } else {
        // Hide alert (but don't reset dismissal tracking)
        if (elements.chainAlertOverlay) {
            elements.chainAlertOverlay.classList.remove('visible');
        }
    }
}

function updateUserCooldowns() {
    const now = Math.floor(Date.now() / 1000);
    
    // Drug cooldown (cooldowns store end timestamps)
    if (elements.drugCd) {
        const drugRemaining = Math.max(0, userStatus.cooldowns.drug - now);
        if (drugRemaining > 0) {
            elements.drugCd.textContent = formatCooldown(drugRemaining);
            elements.drugCd.className = 'cooldown-value active';
        } else {
            elements.drugCd.textContent = 'Ready';
            elements.drugCd.className = 'cooldown-value ready';
        }
    }
    
    // Medical cooldown
    if (elements.medicalCd) {
        const medRemaining = Math.max(0, userStatus.cooldowns.medical - now);
        if (medRemaining > 0) {
            elements.medicalCd.textContent = formatCooldown(medRemaining);
            elements.medicalCd.className = 'cooldown-value active';
        } else {
            elements.medicalCd.textContent = 'Ready';
            elements.medicalCd.className = 'cooldown-value ready';
        }
    }
    
    // Booster cooldown
    if (elements.boosterCd) {
        const boostRemaining = Math.max(0, userStatus.cooldowns.booster - now);
        if (boostRemaining > 0) {
            elements.boosterCd.textContent = formatCooldown(boostRemaining);
            elements.boosterCd.className = 'cooldown-value active';
        } else {
            elements.boosterCd.textContent = 'Ready';
            elements.boosterCd.className = 'cooldown-value ready';
        }
    }
}

function formatCooldown(seconds) {
    if (seconds <= 0) return 'Ready';
    
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    
    if (h > 0) {
        return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }
    return `${m}:${s.toString().padStart(2, '0')}`;
}

async function fetchStatus(forceRefresh = false) {
    // Don't fetch if no API key configured
    if (!state.apiKey) {
        updateConnectionStatus(false, 'No API key');
        return;
    }
    
    // Prevent concurrent fetches - skip if already fetching
    if (state.isFetching) {
        return;
    }
    
    state.isFetching = true;
    const thisRequestId = ++state.fetchRequestId;
    
    try {
        const url = forceRefresh 
            ? `${CONFIG.API_BASE}/status?force_refresh=true`
            : `${CONFIG.API_BASE}/status`;
        
        const response = await fetch(url, {
            headers: {
                'X-API-Key': state.apiKey
            }
        });
        
        // Check if this request is still the latest one
        if (thisRequestId !== state.fetchRequestId) {
            return; // A newer request was started, discard this result
        }
        
        if (response.status === 401) {
            showToast('Invalid API key', 'error');
            elements.configPanel.classList.add('visible');
            return;
        }
        
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        
        const data = await response.json();
        
        // Double-check this is still the latest request
        if (thisRequestId !== state.fetchRequestId) {
            return;
        }
        
        // Get max claims config
        if (data.max_claims_per_user !== undefined) {
            state.maxClaimsPerUser = data.max_claims_per_user;
        }
        
        // Use server data directly - server is the single source of truth
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
    } finally {
        state.isFetching = false;
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

function formatStats(total) {
    if (!total || total <= 0) return '-';
    if (total >= 1e12) return (total / 1e12).toFixed(1) + 'T';
    if (total >= 1e9) return (total / 1e9).toFixed(1) + 'B';
    if (total >= 1e6) return (total / 1e6).toFixed(1) + 'M';
    if (total >= 1e3) return (total / 1e3).toFixed(1) + 'K';
    return total.toString();
}

function filterTargets(targets) {
    return targets.filter(t => {
        // Hospital filter
        if (state.filters.hospital === 'in' && t.hospital_status === 'out') return false;
        if (state.filters.hospital === 'out' && t.hospital_status !== 'out') return false;
        
        // Claim filter
        if (state.filters.claim === 'unclaimed' && t.claimed_by) return false;
        if (state.filters.claim === 'claimed' && !t.claimed_by) return false;
        if (state.filters.claim === 'myclaims' && t.claimed_by_id !== parseInt(state.userId)) return false;
        
        // Online filter
        if (state.filters.online === 'online' && t.estimated_online !== 'online') return false;
        if (state.filters.online === 'offline' && t.estimated_online === 'online') return false;
        
        // Travel filter
        if (state.filters.travel === 'local' && t.traveling) return false;
        if (state.filters.travel === 'traveling' && !t.traveling) return false;
        
        // Level range filter
        if (state.filters.levelMin !== null && t.level < state.filters.levelMin) return false;
        if (state.filters.levelMax !== null && t.level > state.filters.levelMax) return false;
        
        // Battle stats filter (using estimated stats)
        const totalStats = t.estimated_stats || 0;
        if (totalStats < state.filters.statsMin) return false;
        if (totalStats > state.filters.statsMax) return false;
        
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
            case 'stats':
                const aStats = a.estimated_stats || 0;
                const bStats = b.estimated_stats || 0;
                cmp = aStats - bStats;
                break;
            case 'online':
                const onlineOrder = { online: 0, idle: 1, offline: 2, unknown: 3 };
                cmp = (onlineOrder[a.estimated_online] || 3) - (onlineOrder[b.estimated_online] || 3);
                break;
            case 'claimed':
                // Sort by: my claims first, then other claims, then unclaimed
                const aClaimOrder = a.claimed_by_id === parseInt(state.userId) ? 0 : (a.claimed_by ? 1 : 2);
                const bClaimOrder = b.claimed_by_id === parseInt(state.userId) ? 0 : (b.claimed_by ? 1 : 2);
                if (aClaimOrder !== bClaimOrder) {
                    cmp = aClaimOrder - bClaimOrder;
                } else {
                    // Within same claim status, sort by claimer name
                    cmp = (a.claimed_by || '').localeCompare(b.claimed_by || '');
                }
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
            <tr><td colspan="8" class="loading">
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
    
    // Battle stats (estimated based on level)
    const hasStats = target.estimated_stats && target.estimated_stats > 0;
    const statsHtml = hasStats 
        ? `<span class="stats-value" title="Estimated based on level">${target.estimated_stats_formatted}</span>`
        : '<span class="stats-value">-</span>';
    
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
            <td class="${timerClass}">${timerText}</td>
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
            <td class="stats-cell ${hasStats ? 'has-stats' : ''}">${statsHtml}</td>
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
    
    const tid = parseInt(targetId);
    
    try {
        const response = await fetch(`${CONFIG.API_BASE}/claim`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'X-API-Key': state.apiKey
            },
            body: JSON.stringify({
                target_id: tid,
                claimer_id: parseInt(state.userId),
                claimer_name: state.userName
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast(data.message, 'success');
        } else {
            showToast(data.message || 'Failed to claim target', 'error');
        }
    } catch (error) {
        console.error('Claim error:', error);
        showToast('Network error claiming target', 'error');
    }
    
    // Refresh to get latest server data
    fetchStatus(true);
}

async function handleUnclaim(targetId) {
    if (!state.userId) return;
    
    const tid = parseInt(targetId);
    
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
        } else {
            showToast(data.detail || 'Failed to release claim', 'error');
        }
    } catch (error) {
        console.error('Unclaim error:', error);
        showToast('Network error releasing claim', 'error');
    }
    
    // Refresh to get latest server data
    fetchStatus(true);
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
