/**
 * Faction Overview - Leadership View
 * 
 * Shows current status of all faction members who have used the tracker.
 * Only accessible to whitelisted leadership IDs.
 */

// State
let factionState = {
    profiles: [],
    isAccessible: false,
    lastUpdate: 0,
    pollInterval: null,
};

/**
 * Check if user has access to faction overview
 */
async function checkFactionAccess() {
    const apiKey = localStorage.getItem('tornApiKey');
    if (!apiKey) {
        return false;
    }

    try {
        const response = await fetch('/api/faction-overview', {
            headers: {
                'X-API-Key': apiKey
            }
        });

        if (response.status === 403 || response.status === 401) {
            return false;
        }

        if (response.ok) {
            return true;
        }

        return false;
    } catch (error) {
        console.error('Error checking faction access:', error);
        return false;
    }
}

/**
 * Fetch faction profiles from API
 */
async function fetchFactionProfiles() {
    const apiKey = localStorage.getItem('tornApiKey');
    if (!apiKey) {
        return;
    }

    try {
        const response = await fetch('/api/faction-overview', {
            headers: {
                'X-API-Key': apiKey
            }
        });

        if (!response.ok) {
            if (response.status === 403) {
                console.log('No access to faction overview');
                return;
            }
            throw new Error('Failed to fetch faction profiles');
        }

        const profiles = await response.json();
        factionState.profiles = profiles;
        factionState.lastUpdate = Date.now();
        renderFactionTable();
    } catch (error) {
        console.error('Error fetching faction profiles:', error);
        const factionList = document.getElementById('faction-list');
        if (factionList) {
            factionList.innerHTML = '<tr><td colspan="9" class="error">Failed to load faction data</td></tr>';
        }
    }
}

/**
 * Format time remaining
 */
function formatTimeRemaining(seconds) {
    if (seconds <= 0) return '-';
    
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    
    if (hours > 0) {
        return `${hours}h ${mins}m`;
    } else if (mins > 0) {
        return `${mins}m ${secs}s`;
    } else {
        return `${secs}s`;
    }
}

/**
 * Format last seen time
 */
function formatLastSeen(timestamp) {
    const now = Math.floor(Date.now() / 1000);
    const elapsed = now - timestamp;
    
    if (elapsed < 60) return 'Just now';
    if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ago`;
    if (elapsed < 86400) return `${Math.floor(elapsed / 3600)}h ago`;
    return `${Math.floor(elapsed / 86400)}d ago`;
}

/**
 * Get status class for styling
 */
function getStatusClass(status) {
    const statusLower = status.toLowerCase();
    if (statusLower.includes('hospital')) return 'status-hospital';
    if (statusLower.includes('jail')) return 'status-jail';
    if (statusLower.includes('travel')) return 'status-traveling';
    if (statusLower === 'okay') return 'status-okay';
    return '';
}

/**
 * Render faction overview table
 */
function renderFactionTable() {
    const factionList = document.getElementById('faction-list');
    if (!factionList) return;

    if (factionState.profiles.length === 0) {
        factionList.innerHTML = '<tr><td colspan="9" class="no-data">No faction members have used the tracker yet</td></tr>';
        return;
    }

    const now = Math.floor(Date.now() / 1000);
    
    const rows = factionState.profiles.map(profile => {
        const lifePercent = profile.life_maximum > 0 ? (profile.life_current / profile.life_maximum * 100).toFixed(0) : 0;
        const energyPercent = profile.energy_maximum > 0 ? (profile.energy_current / profile.energy_maximum * 100).toFixed(0) : 0;
        
        const drugCd = profile.drug_cooldown || 0;
        const medCd = profile.medical_cooldown || 0;
        
        const hospitalTime = profile.hospital_timestamp > now ? profile.hospital_timestamp - now : 0;
        const hospitalStatus = hospitalTime > 0 ? formatTimeRemaining(hospitalTime) : '-';
        
        const statusClass = getStatusClass(profile.status);
        const lastSeen = formatLastSeen(profile.last_action);
        
        return `
            <tr>
                <td>
                    <a href="https://www.torn.com/profiles.php?XID=${profile.player_id}" target="_blank">
                        ${profile.name} [${profile.player_id}]
                    </a>
                </td>
                <td>${profile.level}</td>
                <td class="${statusClass}">${profile.status}</td>
                <td>
                    <div class="bar-mini">
                        <div class="bar-fill-mini life-bar-mini" style="width: ${lifePercent}%"></div>
                        <span class="bar-text-mini">${profile.life_current}/${profile.life_maximum}</span>
                    </div>
                </td>
                <td>
                    <div class="bar-mini">
                        <div class="bar-fill-mini energy-bar-mini" style="width: ${energyPercent}%"></div>
                        <span class="bar-text-mini">${profile.energy_current}/${profile.energy_maximum}</span>
                    </div>
                </td>
                <td>${formatTimeRemaining(drugCd)}</td>
                <td>${formatTimeRemaining(medCd)}</td>
                <td>${hospitalStatus}</td>
                <td>${lastSeen}</td>
            </tr>
        `;
    }).join('');
    
    factionList.innerHTML = rows;
}

/**
 * Setup view toggle handlers
 */
function setupViewToggle() {
    const toggleBtns = document.querySelectorAll('.toggle-btn');
    const targetsView = document.getElementById('targets-view');
    const factionView = document.getElementById('faction-view');
    
    toggleBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            
            // Update button states
            toggleBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Show/hide views
            if (view === 'targets') {
                targetsView.style.display = 'block';
                factionView.style.display = 'none';
                // Resume target polling
                if (window.state && window.state.pollInterval === null) {
                    window.startPolling();
                }
            } else if (view === 'faction') {
                targetsView.style.display = 'none';
                factionView.style.display = 'block';
                // Fetch faction data
                fetchFactionProfiles();
                // Start faction polling if not already running
                if (factionState.pollInterval === null) {
                    factionState.pollInterval = setInterval(fetchFactionProfiles, 30000); // 30 seconds
                }
            }
        });
    });
}

/**
 * Initialize faction overview on page load
 */
async function initFactionOverview() {
    // Check if user has access
    const hasAccess = await checkFactionAccess();
    factionState.isAccessible = hasAccess;
    
    if (hasAccess) {
        // Show the view toggle
        const viewToggle = document.getElementById('view-toggle');
        if (viewToggle) {
            viewToggle.style.display = 'flex';
        }
        
        // Setup toggle handlers
        setupViewToggle();
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        // Wait a bit for config to load
        setTimeout(initFactionOverview, 500);
    });
} else {
    setTimeout(initFactionOverview, 500);
}

// Expose for external use
window.initFactionOverview = initFactionOverview;
window.fetchFactionProfiles = fetchFactionProfiles;
