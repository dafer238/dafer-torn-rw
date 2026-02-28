/**
 * Torn Ranked War Tracker - Frontend Application
 * 
 * Polls backend every 1 second for real-time updates.
 * Handles client-side countdown timers for smooth UX.
 */

// Configuration
const CONFIG = {
    POLL_INTERVAL: 1000,  // 1 second - VPS has plenty of bandwidth
    TIMER_INTERVAL: 1000,  // 1 second for smooth client-side timers
    API_BASE: '/api',
    TOAST_DURATION: 3000,
};

// State
let state = {
    targets: [],
    claims: [],
    lastUpdate: 0,
    targetsFetchTime: 0,  // Track when we fetched target data
    userId: null,
    userName: null,
    apiKey: null,
    maxClaimsPerUser: 3,
    isUserInfoLoaded: false, // Track if user info is loaded
    filters: {
        hospital: 'all',
        claim: 'all',
        online: 'all',
        travel: 'all',
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
    // Chain timer tracking
    lastChainCount: 0,
    chainTimerSnapshot: 0,  // When we took the snapshot
    chainTimeoutSnapshot: 0, // Timeout value at snapshot
    // Notification settings
    notifyClaimExpiry: true,
    chainWatch: false,
    // Tracking for notifications
    notifiedClaims: new Set(), // Track which claims we've already notified about
    notified30SecClaims: new Set(), // Track 30s warnings
    chainWatchCheckedTargets: new Set(), // Track which targets we've opened for chain watch
};

// DOM Elements
const elements = {};

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    cacheElements();
    setupEventListeners(); // Ensure event listeners are attached immediately
    // Fetch server config to get poll interval
    try {
        const resp = await fetch('/api/config');
        if (resp.ok) {
            const cfg = await resp.json();
            if (cfg.frontend_poll_interval) CONFIG.POLL_INTERVAL = cfg.frontend_poll_interval;
        }
    } catch (e) { /* use defaults */ }
    loadConfig();
    startTimers();
    // startPolling() will be called after user info is loaded
    // Always show config panel if API key is missing
    if (!localStorage.getItem('tornApiKey')) {
        elements.configPanel.classList.add('visible');
    }
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
    // Removed userId and userName fields (now fetched from backend)
    elements.apiKey = document.getElementById('api-key');
    elements.toastContainer = document.getElementById('toast-container');
    elements.targetTable = document.getElementById('target-table');
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
    
    // Settings
    elements.notifyClaimExpiry = document.getElementById('notify-claim-expiry');
    elements.chainWatch = document.getElementById('chain-watch');
}

function loadConfig() {
    state.apiKey = localStorage.getItem('tornApiKey');
    if (state.apiKey) elements.apiKey.value = state.apiKey;
    
    // Load notification settings
    const notifyClaimExpiry = localStorage.getItem('notifyClaimExpiry');
    state.notifyClaimExpiry = notifyClaimExpiry === null ? true : notifyClaimExpiry === 'true';
    if (elements.notifyClaimExpiry) elements.notifyClaimExpiry.checked = state.notifyClaimExpiry;
    
    const chainWatch = localStorage.getItem('chainWatch');
    state.chainWatch = chainWatch === 'true';
    if (elements.chainWatch) elements.chainWatch.checked = state.chainWatch;
    
    // Request notification permission if needed
    if (state.notifyClaimExpiry && 'Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
    
    if (!state.apiKey) {
        elements.configPanel.classList.add('visible');
    } else {
        // Fetch user info from backend, then start polling and load targets immediately
        (async () => {
            try {
                await fetchUserInfoFromApiKey(state.apiKey, false);
                state.isUserInfoLoaded = true;
                startPolling();
                // Force immediate target load after API key is set
                await fetchStatus();
            } catch (e) {
                // Error already handled in fetchUserInfoFromApiKey
                console.error('Failed to initialize on load:', e);
            }
        })();
    }
}

async function saveConfig() {
    state.apiKey = elements.apiKey.value;
    const oldChainWatch = state.chainWatch;
    state.notifyClaimExpiry = elements.notifyClaimExpiry.checked;
    state.chainWatch = elements.chainWatch.checked;
    
    if (state.apiKey) {
        localStorage.setItem('tornApiKey', state.apiKey);
        localStorage.setItem('notifyClaimExpiry', state.notifyClaimExpiry);
        localStorage.setItem('chainWatch', state.chainWatch);
        
        // Request notification permission if enabled
        if (state.notifyClaimExpiry && 'Notification' in window && Notification.permission === 'default') {
            Notification.requestPermission();
        }
        
        // Handle chain watch interval
        if (state.chainWatch && !oldChainWatch) {
            // Chain watch was just enabled - start it
            if (state.isUserInfoLoaded) {
                checkChainWatch();
                state.chainWatchInterval = setInterval(checkChainWatch, 10000);
            }
        } else if (!state.chainWatch && oldChainWatch) {
            // Chain watch was just disabled - stop it
            if (state.chainWatchInterval) {
                clearInterval(state.chainWatchInterval);
                state.chainWatchInterval = null;
            }
        }
        
        // Fetch user info from backend, then start polling
        try {
            await fetchUserInfoFromApiKey(state.apiKey, true);
            // User info loaded successfully - now start polling and fetch targets
            state.isUserInfoLoaded = true;
            startPolling();
            // Ensure targets are fetched immediately
            await fetchStatus();
        } catch (e) {
            console.error('Failed to initialize after saving config:', e);
        }
    } else {
        showToast('Please enter your API key', 'error');
    }
}

function setupEventListeners() {
    // Config
    document.getElementById('save-config').addEventListener('click', saveConfig);
    document.getElementById('toggle-config').addEventListener('click', () => {
        elements.configPanel.classList.toggle('visible');
    });
    
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

    // Tooltip logic for stats and travel columns (click/tap and hover)
    setupTooltipListeners();
}

function setupTooltipListeners() {
    function showTooltip(el) {
        // Remove any existing tooltips first
        document.querySelectorAll('.custom-tooltip').forEach(tip => tip.remove());
        const tooltip = document.createElement('div');
        tooltip.className = 'custom-tooltip';
        tooltip.textContent = el.dataset.tooltip;
        document.body.appendChild(tooltip);
        const rect = el.getBoundingClientRect();
        tooltip.style.left = `${rect.left + window.scrollX}px`;
        tooltip.style.top = `${rect.bottom + window.scrollY + 4}px`;
        el._tooltip = tooltip;
    }

    function hideTooltip(el) {
        if (el._tooltip) {
            el._tooltip.remove();
            el._tooltip = null;
        }
    }

    // Click/tap to toggle tooltip (works on mobile and desktop)
    document.body.addEventListener('click', e => {
        const el = e.target.closest('.tooltip-trigger');
        if (el) {
            e.preventDefault();
            if (el._tooltip) {
                hideTooltip(el);
            } else {
                showTooltip(el);
            }
        } else {
            // Click outside - hide all tooltips
            document.querySelectorAll('.custom-tooltip').forEach(tip => tip.remove());
        }
    });

    // Hover for desktop
    document.body.addEventListener('mouseover', e => {
        const el = e.target.closest('.tooltip-trigger');
        if (el && window.innerWidth > 800 && !el._tooltip) {
            showTooltip(el);
        }
    });

    document.body.addEventListener('mouseout', e => {
        const el = e.target.closest('.tooltip-trigger');
        if (el) {
            hideTooltip(el);
        }
    });
}

function applyStatFilter(filter) {
    // Reset all filters
    state.filters = { hospital: 'all', claim: 'all', online: 'all', travel: 'all', statsMin: state.filters.statsMin, statsMax: state.filters.statsMax };
    
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

function stopPolling() {
    if (state.pollInterval) { clearInterval(state.pollInterval); state.pollInterval = null; }
    if (state.userStatusInterval) { clearInterval(state.userStatusInterval); state.userStatusInterval = null; }
    if (state.chainWatchInterval) { clearInterval(state.chainWatchInterval); state.chainWatchInterval = null; }
}

function startPolling() {
    if (!state.isUserInfoLoaded) return; // Don't start polling until user info is loaded

    // Clear any existing intervals to prevent stacking
    stopPolling();

    fetchStatus();
    fetchUserStatus();
    state.pollInterval = setInterval(fetchStatus, CONFIG.POLL_INTERVAL);
    // Poll user status every 5 seconds
    state.userStatusInterval = setInterval(fetchUserStatus, 5000);
    
    // Start chain watch if enabled
    if (state.chainWatch) {
        checkChainWatch();
        state.chainWatchInterval = setInterval(checkChainWatch, 10000); // Check every 10 seconds
    }

    // Initialize faction overview check (only once, after user info is confirmed)
    if (!state._factionOverviewInitialized && typeof window.initFactionOverview === 'function') {
        state._factionOverviewInitialized = true;
        window.initFactionOverview();
    }
    
    // Pause polling when tab is not visible to save CPU (register only once)
    if (!state._visibilityListenerAdded) {
        state._visibilityListenerAdded = true;
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                stopPolling();
            } else {
                // Tab visible - restart polling
                if (state.isUserInfoLoaded) {
                    fetchStatus();
                    fetchUserStatus();
                    state.pollInterval = setInterval(fetchStatus, CONFIG.POLL_INTERVAL);
                    state.userStatusInterval = setInterval(fetchUserStatus, 5000);
                    if (state.chainWatch) {
                        checkChainWatch();
                        state.chainWatchInterval = setInterval(checkChainWatch, 10000);
                    }
                }
            }
        });
    }
}

async function checkChainWatch() {
    if (!state.chainWatch || !state.apiKey) return;
    
    try {
        // Fetch user's target list from Torn API
        const response = await fetch(`https://api.torn.com/user/?selections=targets&key=${state.apiKey}`);
        if (!response.ok) return;
        
        const data = await response.json();
        if (!data.targets) return;
        
        // Check each target for panic/chain notes (case-insensitive)
        const panicRegex = /panic|chain/i;
        
        // Find all targets with matching notes that haven't been checked yet
        const matchingTargets = [];
        for (const [targetId, targetData] of Object.entries(data.targets)) {
            const note = targetData.note || '';
            
            // Check if note contains panic or chain (case-insensitive)
            if (panicRegex.test(note) && !state.chainWatchCheckedTargets.has(targetId)) {
                matchingTargets.push({ id: targetId, data: targetData });
            }
        }
        
        // Reset checked targets that went back to hospital (allow re-trigger when they come out)
        state.chainWatchCheckedTargets.forEach(id => {
            const info = state.targets.find(t => t.user_id === parseInt(id));
            if (info && info.hospital_status !== 'out') {
                state.chainWatchCheckedTargets.delete(id);
            }
        });
        
        // Find the first target that is NOT in hospital
        for (const { id: targetId, data: targetData } of matchingTargets) {
            // Check if target is attackable by looking at our loaded targets
            const targetInfo = state.targets.find(t => t.user_id === parseInt(targetId));
            
            // Target is attackable if: out of hospital AND not traveling
            const isAttackable = targetInfo && 
                                 targetInfo.hospital_status === 'out' && 
                                 !targetInfo.traveling;
            
            if (isAttackable) {
                // Mark as checked so we don't open again (until they go back to hospital)
                state.chainWatchCheckedTargets.add(targetId);
                
                // Open attack page
                const attackUrl = `https://www.torn.com/loader.php?sid=attack&user2ID=${targetId}`;
                window.open(attackUrl, '_blank');
                
                // Show toast notification
                showToast(`Chain Watch: Opening attack on ${targetData.name || 'target'}`, 'success');
                
                // Stop after opening the first one
                break;
            }
        }
        
        // Clean up checked targets that are no longer in the target list
        const currentTargetIds = new Set(Object.keys(data.targets));
        state.chainWatchCheckedTargets.forEach(id => {
            if (!currentTargetIds.has(id)) {
                state.chainWatchCheckedTargets.delete(id);
            }
        });
        
    } catch (error) {
        console.error('Chain watch error:', error);
    }
}

function startTimers() {
    // Update all timers every second for smooth countdown
    state.timerInterval = setInterval(() => {
        updateTimers();
        updateUserCooldowns();
        updateChainTimer();
        checkClaimNotifications();
    }, 1000);
}

// User status state
let userStatus = {
    cooldowns: { drug: 0, medical: 0, booster: 0 },  // Store original cooldown durations from server
    cooldownsFetchTime: 0,  // When we fetched the cooldowns
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

let ownStatusCountdown = { type: null, until: 0, destination: null, snapshot: 0, duration: 0 };
function updateOwnStatusCountdown() {
    if (!elements.playerState) return;
    if (!ownStatusCountdown.type) return;
    const now = Math.floor(Date.now() / 1000);
    const elapsed = now - ownStatusCountdown.snapshot;
    const remaining = Math.max(0, ownStatusCountdown.duration - elapsed);
    let text = '';
    if (ownStatusCountdown.type === 'hospital') {
        text = `🏥 ${formatTime(remaining)}`;
    } else if (ownStatusCountdown.type === 'travel') {
        text = `✈️ ${ownStatusCountdown.destination} (${formatTime(remaining)})`;
    }
    if (remaining > 0) {
        elements.playerState.textContent = text;
    }
}
setInterval(updateOwnStatusCountdown, 1000);

async function fetchUserStatus() {
    if (!state.apiKey) return;
    
    try {
        const response = await fetch(`${CONFIG.API_BASE}/me`, {
            headers: { 'X-API-Key': state.apiKey }
        });
        
        if (!response.ok) return;
        
        const data = await response.json();
        
        // Only update cooldown values if 30+ seconds have passed since last update
        // Otherwise keep counting down smoothly client-side
        const timeSinceLastCooldownUpdate = Date.now() - userStatus.cooldownsFetchTime;
        if (timeSinceLastCooldownUpdate >= 60000 || userStatus.cooldownsFetchTime === 0) {
            // 30+ seconds passed or first fetch - update cooldown values
            userStatus.cooldowns = {
                drug: data.cooldowns.drug || 0,
                medical: data.cooldowns.medical || 0,
                booster: data.cooldowns.booster || 0,
            };
            userStatus.cooldownsFetchTime = Date.now();
        }
        // If less than 30s, don't update cooldowns - let client-side countdown continue
        
        userStatus.lastFetch = Date.now();
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
            ownStatusCountdown.type = null;
            if (statusState === 'Hospital') {
                stateClass = 'hospital';
                const until = data.status.until;
                const now = Math.floor(Date.now() / 1000);
                const duration = until - now;
                if (duration > 0) {
                    stateText = `🏥 ${formatTime(duration)}`;
                    ownStatusCountdown.type = 'hospital';
                    ownStatusCountdown.snapshot = now;
                    ownStatusCountdown.duration = duration;
                }
            } else if (statusState === 'Jail') {
                stateClass = 'jail';
                stateText = '⛓️ Jail';
            } else if (data.travel.traveling) {
                stateClass = 'traveling';
                const now = Math.floor(Date.now() / 1000);
                const duration = data.travel.time_left || 0;
                stateText = `✈️ ${data.travel.destination} (${formatTime(duration)})`;
                ownStatusCountdown.type = 'travel';
                ownStatusCountdown.snapshot = now;
                ownStatusCountdown.duration = duration;
                ownStatusCountdown.destination = data.travel.destination;
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
    
    // If chain count changed, update snapshot for client-side countdown
    if (current !== state.lastChainCount) {
        state.lastChainCount = current;
        state.chainTimerSnapshot = Date.now();
        state.chainTimeoutSnapshot = timeout;
    }
    
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
    // Use client-side countdown from snapshot for smooth timer
    const elapsed = Math.floor((Date.now() - state.chainTimerSnapshot) / 1000);
    const remaining = Math.max(0, state.chainTimeoutSnapshot - elapsed);
    const current = state.lastChainCount;
    
    if (elements.chainTimer) {
        if (current === 0 || state.chainTimeoutSnapshot === 0) {
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
    // Calculate elapsed time since we fetched cooldowns from server
    const elapsedSeconds = Math.floor((Date.now() - userStatus.cooldownsFetchTime) / 1000);
    
    // Drug cooldown (original value minus elapsed time)
    if (elements.drugCd) {
        const drugRemaining = Math.max(0, userStatus.cooldowns.drug - elapsedSeconds);
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
        const medRemaining = Math.max(0, userStatus.cooldowns.medical - elapsedSeconds);
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
        const boostRemaining = Math.max(0, userStatus.cooldowns.booster - elapsedSeconds);
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

function formatTime(seconds) {
    if (seconds <= 0) return 'OUT';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
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
        if (!response.ok) {
            const errorText = await response.text();
            console.error('Failed to load targets:', response.status, errorText);
            elements.targetList.innerHTML = `<tr><td colspan="8" class="loading">Error loading targets: ${response.status}</td></tr>`;
            updateConnectionStatus(false, `Error ${response.status}`);
            return;
        }
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
        state.targetsFetchTime = Date.now();  // Track when we got this data
        state.isConnected = true;
        
        updateConnectionStatus(true);
        updateStats(data);
        updateApiInfo(data);
        renderTargets();
        updateTimers();  // Immediately update timers after render
        
    } catch (error) {
        console.error('Fetch error:', error);
        elements.targetList.innerHTML = `<tr><td colspan="8" class="loading">Error loading targets: ${error}</td></tr>`;
        state.isConnected = false;
        updateConnectionStatus(false, 'Fetch error');
    } finally {
        state.isFetching = false;
    }
}

function updateConnectionStatus(connected, message = null) {
    if (connected) {
        const nameLabel = state.userName ? ` as ${state.userName}` : '';
        elements.connectionStatus.textContent = `● Connected${nameLabel}`;
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
    const remaining = data.api_calls_remaining;
    const apiText = remaining !== null && remaining !== undefined ? `API: ${remaining}/100` : 'API: --/100';
    elements.apiCalls.textContent = apiText;
    // Color code: green if > 50, yellow if > 20, red if <= 20
    if (remaining !== null && remaining !== undefined) {
        if (remaining <= 20) {
            elements.apiCalls.style.color = '#ff4444';
        } else if (remaining <= 50) {
            elements.apiCalls.style.color = '#ffaa00';
        } else {
            elements.apiCalls.style.color = '';
        }
    }
}

function updateTimers() {
    // Use current time in seconds (UTC)
    const now = Math.floor(Date.now() / 1000);
    // Calculate how many seconds have elapsed since we fetched the data
    const elapsedSinceFetch = Math.floor((Date.now() - state.targetsFetchTime) / 1000);
    
    document.querySelectorAll('tr[data-hospital-until]').forEach(row => {
        const hospitalUntil = parseInt(row.dataset.hospitalUntil) || 0;
        const timerCell = row.querySelector('.timer-cell');
        
        if (!timerCell) return;
        
        // Calculate remaining time: use hospital_until minus elapsed time since fetch
        // This prevents jumps when server data refreshes
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

function checkClaimNotifications() {
    if (!state.notifyClaimExpiry || !state.userId) return;
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    
    const now = Math.floor(Date.now() / 1000);
    
    // Check my claimed targets
    const myClaims = state.targets.filter(t => t.claimed_by_id === parseInt(state.userId));
    
    // Track current claim IDs to clean up old notifications
    const currentClaimIds = new Set(myClaims.map(t => t.user_id));
    
    // Clean up notification tracking for claims that no longer exist
    state.notifiedClaims.forEach(id => {
        if (!currentClaimIds.has(id)) {
            state.notifiedClaims.delete(id);
            state.notified30SecClaims.delete(id);
        }
    });
    
    myClaims.forEach(target => {
        const targetId = target.user_id;
        const targetName = target.name;
        const claimExpires = target.claim_expires || 0;
        const hospitalUntil = target.hospital_until || 0;
        const hospitalRemaining = hospitalUntil > 0 ? Math.max(0, hospitalUntil - now) : 0;
        const isInHospital = target.hospital_status !== 'out' && hospitalRemaining > 0;
        
        // Check for claim expiry (5 minutes expired)
        if (claimExpires > 0 && now >= claimExpires && !state.notifiedClaims.has(targetId)) {
            state.notifiedClaims.add(targetId);
            sendNotification(
                '⏱️ Claim Expired',
                `Your claim on ${targetName} has expired (5 minutes)`,
                `https://www.torn.com/loader.php?sid=attack&user2ID=${targetId}`
            );
        }
        
        // Check for 30 second warning (only if in hospital)
        if (isInHospital && hospitalRemaining <= 30 && hospitalRemaining > 0 
            && !state.notified30SecClaims.has(targetId)) {
            state.notified30SecClaims.add(targetId);
            sendNotification(
                '⚠️ Target Almost Out',
                `${targetName} leaves hospital in ${hospitalRemaining}s`,
                `https://www.torn.com/loader.php?sid=attack&user2ID=${targetId}`
            );
        }
    });
}

function sendNotification(title, body, url = null) {
    if (!('Notification' in window) || Notification.permission !== 'granted') return;
    
    const notification = new Notification(title, {
        body: body,
        icon: '/static/favicon.svg',
        badge: '/static/favicon.svg',
        requireInteraction: false,
        tag: body // Prevent duplicate notifications
    });
    
    if (url) {
        notification.onclick = function() {
            window.open(url, '_blank');
            notification.close();
        };
    }
    
    // Auto-close after 10 seconds
    setTimeout(() => notification.close(), 10000);
}

function getFairFightColor(ff) {
    if (ff === null || ff === undefined) return { color: '#4fc3f7', bg: 'rgba(79,195,247,0.15)' };
    const stops = [
        { val: 1.0, r: 33,  g: 150, b: 243 },  // Blue
        { val: 2.0, r: 0,   g: 188, b: 212 },  // Cyan
        { val: 3.0, r: 76,  g: 175, b: 80  },  // Green
        { val: 4.0, r: 255, g: 193, b: 7   },  // Yellow
        { val: 5.0, r: 244, g: 67,  b: 54  },  // Red
    ];
    let r, g, b;
    if (ff <= stops[0].val) {
        r = stops[0].r; g = stops[0].g; b = stops[0].b;
    } else if (ff >= stops[stops.length - 1].val) {
        r = stops[stops.length - 1].r; g = stops[stops.length - 1].g; b = stops[stops.length - 1].b;
    } else {
        for (let i = 0; i < stops.length - 1; i++) {
            if (ff <= stops[i + 1].val) {
                const t = (ff - stops[i].val) / (stops[i + 1].val - stops[i].val);
                r = Math.round(stops[i].r + t * (stops[i + 1].r - stops[i].r));
                g = Math.round(stops[i].g + t * (stops[i + 1].g - stops[i].g));
                b = Math.round(stops[i].b + t * (stops[i + 1].b - stops[i].b));
                break;
            }
        }
    }
    return { color: `rgb(${r},${g},${b})`, bg: `rgba(${r},${g},${b},0.15)` };
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
    
    // Row classes based on hospital status
    let rowClass = '';
    if (isTraveling) rowClass += ' traveling';
    if (isOut) rowClass += ' out';
    else if (remaining <= 30) rowClass += ' about-to-exit';
    if (isClaimed) rowClass += isMyTarget ? ' claimed-by-me' : ' claimed';
    
    // Timer class - updateTimers() will fill in the text
    let timerClass = 'timer-cell';
    if (isOut) {
        timerClass += ' out';
    } else if (remaining <= 10) {
        timerClass += ' critical';
    } else if (remaining <= 30) {
        timerClass += ' warning';
    } else {
        timerClass += ' safe';
    }
    
    // Online status
    const onlineClass = target.estimated_online || 'unknown';
    const onlineText = { online: 'Online', idle: 'Idle', offline: 'Offline', unknown: '?' }[onlineClass];
    
    // Battle stats - use best available source: FFScouter > YATA > level estimate
    const hasFF = target.ff_estimated_stats && target.ff_estimated_stats > 0;
    const hasYata = target.yata_estimated_stats && target.yata_estimated_stats > 0;
    const statsSource = target.stats_source || 'none';
    
    // Determine which stats to display (best available)
    let displayStats = 0;
    let displayStatsFormatted = '-';
    let hasStats = false;
    
    let statsHtml;
    if (hasFF) {
        displayStats = target.ff_estimated_stats;
        displayStatsFormatted = target.ff_estimated_stats_formatted || formatStats(displayStats);
        hasStats = true;
        
        const ffScore = target.ff_fair_fight !== null && target.ff_fair_fight !== undefined 
            ? `FF Score: ${target.ff_fair_fight.toFixed(2)}` : '';
        const estimateDate = target.ff_timestamp ? new Date(target.ff_timestamp * 1000).toLocaleString() : 'Unknown';
        
        let tooltip = `FFScouter Estimate`;
        if (ffScore) tooltip += `\n${ffScore}`;
        tooltip += `\nEstimate Date: ${estimateDate}`;
        if (hasYata) {
            tooltip += `\n\nYATA Estimate: ${target.yata_estimated_stats_formatted || '?'}`;
            if (target.yata_build_type) tooltip += `\nYATA Type: ${target.yata_build_type}`;
        }
        
        statsHtml = `<span class="stats-value ffscouter" title="${tooltip}">${displayStatsFormatted}</span>`;
        const ffScoreVal = target.ff_fair_fight;
        if (ffScoreVal !== null && ffScoreVal !== undefined) {
            const ffColors = getFairFightColor(ffScoreVal);
            statsHtml += `<span class="stats-source ff-score" style="color:${ffColors.color};background:${ffColors.bg}">${ffScoreVal.toFixed(2)}</span>`;
        } else {
            statsHtml += `<span class="stats-source ff">FF</span>`;
        }
    } else if (hasYata) {
        displayStats = target.yata_estimated_stats;
        displayStatsFormatted = target.yata_estimated_stats_formatted || formatStats(displayStats);
        hasStats = true;
        
        const buildType = target.yata_build_type || 'Unknown';
        const estimateDate = target.yata_timestamp ? new Date(target.yata_timestamp * 1000).toLocaleString() : 'Unknown';
        
        const tooltip = `YATA ML Estimate\nType: ${buildType}\nSkewness: ${target.yata_skewness || 0}\nScore: ${target.yata_score || 0}\nEstimate Date: ${estimateDate}`;
        
        statsHtml = `<span class="stats-value yata" title="${tooltip}">${displayStatsFormatted}</span>`;
        statsHtml += `<span class="stats-source yata">Y</span>`;
    } else {
        statsHtml = '<span class="stats-value">-</span>';
    }
    
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
    
    if (!state.isUserInfoLoaded) {
        claimButton = `<button class="btn btn-claim" disabled>Loading...</button>`;
    } else if (!state.userId || !state.userName) {
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
    
    // Torn Wiki travel times in seconds
    // Source: https://wiki.torn.com/wiki/Travel
    const travelTimes = {
        "Mexico":           { airstrip: 1080, businessClass: 480 },   // 18min / 8min
        "Cayman Islands":   { airstrip: 1500, businessClass: 660 },   // 25min / 11min
        "Canada":           { airstrip: 1740, businessClass: 720 },   // 29min / 12min
        "Hawaii":           { airstrip: 5640, businessClass: 2400 },  // 1h34m / 40min
        "United Kingdom":   { airstrip: 6660, businessClass: 2880 },  // 1h51m / 48min
        "Argentina":        { airstrip: 7020, businessClass: 3000 },  // 1h57m / 50min
        "Switzerland":      { airstrip: 7380, businessClass: 3180 },  // 2h3m / 53min
        "Japan":            { airstrip: 9480, businessClass: 4080 },  // 2h38m / 1h8m
        "China":            { airstrip: 10140, businessClass: 4320 }, // 2h49m / 1h12m
        "UAE":              { airstrip: 11400, businessClass: 4860 }, // 3h10m / 1h21m
        "South Africa":     { airstrip: 12480, businessClass: 5340 }, // 3h28m / 1h29m
        "Torn":             { airstrip: 0, businessClass: 0 }         // Already in Torn
    };
    
    // Extract country name from full travel text like "Traveling to Japan" or "Returning to Torn from Cayman Islands"
    function extractCountryFromTravelText(text) {
        if (!text) return null;
        
        // Match "Traveling to [Country]" or "In [Country]"
        let match = text.match(/^(?:Traveling to|In)\s+(.+)$/i);
        if (match) return match[1].trim();
        
        // Match "Returning to Torn from [Country]"
        match = text.match(/^Returning to Torn from\s+(.+)$/i);
        if (match) return match[1].trim();
        
        // Match "Returning from [Country]"
        match = text.match(/^Returning from\s+(.+)$/i);
        if (match) return match[1].trim();
        
        // If it's just a country name, return as-is
        if (travelTimes[text] !== undefined) return text;
        
        return null;
    }

    // Helper: get time left and landing time for both airstrip and business class
    function getTravelInfo(target) {
        if (!target.traveling || !target.travel_destination) return null;
        const now = Math.floor(Date.now() / 1000);
        
        // Extract country name from travel_destination which might be full text
        const country = extractCountryFromTravelText(target.travel_destination);
        const durations = (country && travelTimes[country]) ? travelTimes[country] : { airstrip: 1800, businessClass: 900 };
        
        // Use travel_started if available (tracked server-side)
        // Fall back to travel_until if not (use actual API landing time)
        if (target.travel_started) {
            const landingAirstrip = target.travel_started + durations.airstrip;
            const landingBC = target.travel_started + durations.businessClass;
            const timeLeftAirstrip = Math.max(0, landingAirstrip - now);
            const timeLeftBC = Math.max(0, landingBC - now);
            
            return {
                destination: target.travel_destination,
                country: country,
                airstrip: { timeLeft: timeLeftAirstrip, landing: landingAirstrip },
                businessClass: { timeLeft: timeLeftBC, landing: landingBC }
            };
        } else if (target.travel_until) {
            // Fallback: use actual API landing time (we don't know the travel method)
            const timeLeft = Math.max(0, target.travel_until - now);
            return {
                destination: target.travel_destination,
                country: country,
                airstrip: { timeLeft: timeLeft, landing: target.travel_until },
                businessClass: { timeLeft: timeLeft, landing: target.travel_until },
                isActualTime: true  // Flag to indicate this is the actual time, not an estimate
            };
        }
        
        return null;
    }

    // Reason column logic
    let reasonHtml = '';
    let reasonTooltip = '';
    const travelInfo = getTravelInfo(target);
    if (travelInfo) {
        // Build the display text with timer (using airstrip time)
        const dest = travelInfo.destination;
        const timerTextAirstrip = formatTime(travelInfo.airstrip.timeLeft);
        const timerTextBC = formatTime(travelInfo.businessClass.timeLeft);
        let displayText = '';
        
        // Check if destination already contains full travel text (from API)
        const isFullTravelText = /^(Traveling|Returning|In |Landed)/i.test(dest);

        if (isFullTravelText) {
            // Use as-is - the API already gave us the full description
            displayText = dest;
        } else if (dest === 'Torn') {
            // Returning to Torn from somewhere
            const origin = target.travel_origin || 'abroad';
            displayText = `Returning from ${origin}`;
        } else {
            // Traveling to a destination
            displayText = `Traveling to ${dest}`;
        }

        // HTML with timer span for live updates (airstrip time)
        reasonHtml = `${escapeHtml(displayText)} (<span class="travel-timer">${timerTextAirstrip}</span>)`;

        // Tooltip shows both airstrip and business class times with landing times
        const arrivalAirstrip = new Date(travelInfo.airstrip.landing * 1000).toLocaleTimeString();
        const arrivalBC = new Date(travelInfo.businessClass.landing * 1000).toLocaleTimeString();
        
        if (travelInfo.isActualTime) {
            // Fallback: using actual API time, not estimate
            reasonTooltip = `${displayText}\n\nActual landing: ${arrivalAirstrip}\nTime left: ${timerTextAirstrip}`;
        } else {
            // Full estimate display
            reasonTooltip = `${displayText}\n\nAirstrip:\n  Time left: ${timerTextAirstrip}\n  Landing: ${arrivalAirstrip}\n\nBusiness Class:\n  Time left: ${timerTextBC}\n  Landing: ${arrivalBC}`;
        }
    } else if (target.traveling && target.travel_destination) {
        // No travel_started timestamp available, show without timer
        const dest = target.travel_destination;
        let displayText = '';
        
        // Check if destination already contains full travel text (from API)
        const isFullTravelText = /^(Traveling|Returning|In |Landed)/i.test(dest);

        if (isFullTravelText) {
            // Use as-is
            displayText = dest;
        } else if (dest === 'Torn') {
            const origin = target.travel_origin || 'abroad';
            displayText = `Returning from ${origin}`;
        } else {
            displayText = `Traveling to ${dest}`;
        }

        reasonHtml = escapeHtml(displayText);
        reasonTooltip = `${displayText}\nTravel time unknown (no start time available)`;
    } else if (target.hospital_reason) {
        // Hospital reason - show full text in tooltip for mobile
        reasonHtml = escapeHtml(target.hospital_reason);
        reasonTooltip = target.hospital_reason;
    } else if (target.in_hospital && target.hospital_until) {
        // In hospital but no specific reason
        const remaining = target.hospital_until - Math.floor(Date.now() / 1000);
        if (remaining > 0) {
            reasonHtml = `In hospital (<span class="timer">${formatTime(remaining)}</span>)`;
            reasonTooltip = `In hospital (${formatTime(remaining)})\nReleased at: ${new Date(target.hospital_until * 1000).toLocaleTimeString()}`;
        } else {
            reasonHtml = 'Out of hospital';
            reasonTooltip = 'Out of hospital';
        }
    } else {
        reasonHtml = '-';
        reasonTooltip = '';
    }

    // Stats column tooltip logic
    let statsCellTooltip = '';
    if (hasFF) {
        statsCellTooltip = `FFScouter Estimate\nFF Score: ${target.ff_fair_fight?.toFixed(2) || ''}\nEstimate Date: ${target.ff_timestamp ? new Date(target.ff_timestamp * 1000).toLocaleString() : 'Unknown'}`;
        if (hasYata) statsCellTooltip += `\nYATA Estimate: ${target.yata_estimated_stats_formatted || '?'}`;
    } else if (hasYata) {
        statsCellTooltip = `YATA ML Estimate\nType: ${target.yata_build_type || 'Unknown'}\nSkewness: ${target.yata_skewness || 0}\nScore: ${target.yata_score || 0}\nEstimate Date: ${target.yata_timestamp ? new Date(target.yata_timestamp * 1000).toLocaleString() : 'Unknown'}`;
    }

    // Tooltip HTML helper (no underline)
    function tooltipSpan(html, tooltip, cls) {
        return `<span class="${cls || ''} tooltip-trigger no-underline" tabindex="0" data-tooltip="${escapeHtml(tooltip)}">${html}</span>`;
    }

    // Stats cell with tooltip (click/tap always works)
    let statsCellHtml = statsHtml;
    if (statsCellTooltip) {
        statsCellHtml = tooltipSpan(statsHtml, statsCellTooltip, 'stats-cell-inner');
    }

    // Reason cell with tooltip
    let reasonCellHtml = reasonHtml;
    if (reasonTooltip) {
        reasonCellHtml = tooltipSpan(reasonHtml, reasonTooltip, 'reason-cell-inner');
    }

    return `
        <tr class="${rowClass}" 
            data-target-id="${target.user_id}" 
            data-hospital-until="${target.hospital_until || 0}">
            <td class="${timerClass}"></td>
            <td class="name-cell">
                <div class="player-links">
                    <a href="https://www.torn.com/loader.php?sid=attack&user2ID=${target.user_id}" 
                       target="_blank" rel="noopener" class="attack-link" title="Attack">⚔</a>
                    <a href="https://www.torn.com/profiles.php?XID=${target.user_id}" 
                       target="_blank" rel="noopener" class="profile-link">
                        ${escapeHtml(target.name)}
                    </a>
                    ${badges}
                    <span class="player-links-spacer"></span>
                    <button class="copy-target-btn" data-target-id="${target.user_id}" 
                            data-target-name="${escapeHtml(target.name)}" 
                            data-online-status="${onlineClass}"
                            data-stats="${hasStats ? displayStatsFormatted : '-'}"
                            data-ff-score="${hasFF && target.ff_fair_fight != null ? target.ff_fair_fight.toFixed(2) : ''}"
                            title="Copy target info">📋</button>
                </div>
            </td>
            <td>${target.level}</td>
            <td class="stats-cell ${hasStats ? 'has-stats' : ''}">${statsCellHtml}</td>
            <td class="online-cell">
                <div class="online-content">
                    <span class="online-dot ${onlineClass}"></span>
                    <span class="online-text">${onlineText}</span>
                </div>
            </td>
            <td class="reason-cell">${reasonCellHtml}</td>
            <td class="claim-cell">
                ${isClaimed ? escapeHtml(target.claimed_by) : '-'}
            </td>
            <td>${claimButton}</td>
        </tr>
    `;
}

function renderTargets() {
    let targets = state.targets || [];
    // Apply filters
    targets = targets.filter(target => {
        // Hospital filter
        if (state.filters.hospital === 'in' && !target.in_hospital) return false;
        if (state.filters.hospital === 'out' && target.in_hospital) return false;
        // Claim filter
        if (state.filters.claim === 'claimed' && !target.claimed_by) return false;
        if (state.filters.claim === 'unclaimed' && target.claimed_by) return false;
        if (state.filters.claim === 'myclaims' && target.claimed_by_id !== parseInt(state.userId)) return false;
        // Online filter
        if (state.filters.online === 'online' && target.estimated_online !== 'online') return false;
        if (state.filters.online === 'offline' && target.estimated_online !== 'offline') return false;
        // Travel filter
        if (state.filters.travel === 'traveling' && !target.traveling) return false;
        if (state.filters.travel === 'local' && target.traveling) return false;
        // Stats filter
        const stats = target.ff_estimated_stats || target.yata_estimated_stats || target.estimated_stats || 0;
        if (stats < state.filters.statsMin || stats > state.filters.statsMax) return false;
        return true;
    });
    if (targets.length === 0) {
        elements.targetList.innerHTML = `<tr><td colspan="8" class="loading">${state.targets.length === 0 
            ? 'No targets loaded. Check API configuration.' 
            : 'No targets match the current filters.'}</td></tr>`;
        return;
    }
    // Table sorting
    if (state.sortBy) {
        const sortKey = state.sortBy;
        const dir = state.sortDir === 'asc' ? 1 : -1;
        targets.sort((a, b) => {
            let va = a[sortKey], vb = b[sortKey];
            // For stats, use best available
            if (sortKey === 'stats') {
                va = a.ff_estimated_stats || a.yata_estimated_stats || a.estimated_stats || 0;
                vb = b.ff_estimated_stats || b.yata_estimated_stats || b.estimated_stats || 0;
            }
            if (typeof va === 'string' && typeof vb === 'string') {
                return va.localeCompare(vb) * dir;
            }
            return (va - vb) * dir;
        });
    }
    const html = targets.map(target => renderTargetRow(target)).join('');
    elements.targetList.innerHTML = html;
    updateTimers();
}

// Fetch user info from backend using API key
async function fetchUserInfoFromApiKey(apiKey, closePanelOnSuccess = false, onSuccess = null) {
    state.isUserInfoLoaded = false;
    try {
        const response = await fetch('/api/me', {
            headers: { 'X-API-Key': apiKey }
        });
        if (!response.ok) throw new Error('Invalid API key');
        const data = await response.json();
        if (data && data.player_id && data.name) {
            state.userId = data.player_id;
            state.userName = data.name;
            localStorage.setItem('tornUserId', state.userId);
            localStorage.setItem('tornUserName', state.userName);
            state.isUserInfoLoaded = true;
            if (closePanelOnSuccess) {
                elements.configPanel.classList.remove('visible');
                showToast('Configuration saved!', 'success');
            }
            if (typeof onSuccess === 'function') onSuccess();
            return true; // Success
        } else {
            throw new Error('Could not fetch user info');
        }
    } catch (e) {
        showToast('Invalid API key or unable to fetch user info', 'error');
        elements.configPanel.classList.add('visible');
        state.isUserInfoLoaded = false;
        throw e; // Rethrow so callers can handle
    }
}

async function handleClaim(targetId) {
    if (!state.userId || !state.userName) {
        showToast('Please configure your API key first', 'error');
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
                target_id: tid
                // claimer_id and claimer_name will be filled in backend
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            // Claim successful
            showToast(`Claimed ${data.target.name} (${data.target.user_id})`, 'success');
            // Update local state immediately
            const target = state.targets.find(t => t.user_id === tid);
            if (target) {
                target.claimed_by_id = state.userId;
                target.claimed_by = state.userName;
            }
            // Refresh targets display
            renderTargets();
        } else {
            // Handle specific error messages from server
            let errorMessage = 'Failed to claim target';
            if (data.error) {
                errorMessage = data.error;
            } else if (response.status === 403) {
                errorMessage = 'You are not allowed to claim this target';
            } else if (response.status === 404) {
                errorMessage = 'Target not found';
            }
            showToast(errorMessage, 'error');
        }
    } catch (error) {
        console.error('Claim error:', error);
        showToast('Error processing claim', 'error');
    }
}

function escapeHtml(unsafe) {
    return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

//# sourceMappingURL=app.js.map
