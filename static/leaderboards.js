// Leaderboard functionality
const leaderboard = {
    data: null,
    lastFetch: 0,
    FETCH_INTERVAL: 3600000, // 1 hour
};

// Fetch leaderboards from API
async function fetchLeaderboards() {
    try {
        // Check for both old and new config storage formats
        const oldApiKey = localStorage.getItem('tornApiKey');
        const config = JSON.parse(localStorage.getItem('torn_rw_config') || '{}');
        const apiKey = config.apiKey || oldApiKey;
        
        if (!apiKey) {
            console.log('No API key configured, skipping leaderboards');
            return null;
        }

        console.log('Fetching leaderboards...');
        const response = await fetch('/api/leaderboards', {
            headers: {
                'X-API-Key': apiKey,
            },
        });

        if (!response.ok) {
            console.error('Failed to fetch leaderboards:', response.status, response.statusText);
            const text = await response.text();
            console.error('Response:', text);
            return null;
        }

        const data = await response.json();
        console.log('Leaderboards data received:', data);
        leaderboard.data = data;
        leaderboard.lastFetch = Date.now();
        return data;
    } catch (error) {
        console.error('Error fetching leaderboards:', error);
        return null;
    }
}

// Render a single leaderboard entry
function renderLeaderboardEntry(entry, leaderboardId) {
    const div = document.createElement('div');
    div.className = `lb-entry rank-${entry.rank}`;
    
    const rank = document.createElement('span');
    rank.className = 'lb-rank';
    rank.textContent = `#${entry.rank}`;
    
    const name = document.createElement('span');
    name.className = 'lb-name';
    name.textContent = entry.player_name;
    name.title = entry.player_name; // Tooltip for overflow
    
    const value = document.createElement('span');
    value.className = 'lb-value';
    
    // Format value based on leaderboard type
    if (leaderboardId === 'hospital-week' && entry.value >= 3600) {
        // Hospital time: convert seconds to hours/minutes
        const hours = Math.floor(entry.value / 3600);
        const minutes = Math.floor((entry.value % 3600) / 60);
        value.textContent = `${hours}h ${minutes}m`;
    } else if (leaderboardId === 'gym-gains-week') {
        // Gym gains: show as percentage
        value.textContent = entry.value.toFixed(1) + '%';
    } else if (entry.value >= 1000000) {
        value.textContent = (entry.value / 1000000).toFixed(1) + 'M';
    } else if (entry.value >= 1000) {
        value.textContent = (entry.value / 1000).toFixed(1) + 'K';
    } else {
        value.textContent = Math.round(entry.value).toString();
    }
    
    div.appendChild(rank);
    div.appendChild(name);
    div.appendChild(value);
    
    return div;
}

// Render empty state
function renderEmptyLeaderboard() {
    const div = document.createElement('div');
    div.className = 'lb-entry empty';
    div.textContent = 'No data yet';
    return div;
}

// Update all leaderboards
function updateLeaderboards(data) {
    if (!data) {
        console.log('No leaderboard data to display');
        return;
    }
    
    console.log('Updating leaderboards with data:', data);
    
    const leaderboards = [
        { id: 'xanax-week', data: data.xanax_week },
        { id: 'xanax-month', data: data.xanax_month },
        { id: 'xanax-year', data: data.xanax_year },
        { id: 'overdoses-week', data: data.overdoses_week },
        { id: 'overdoses-month', data: data.overdoses_month },
        { id: 'overdoses-year', data: data.overdoses_year },
    ];
    
    leaderboards.forEach(({ id, data: lbData }) => {
        const container = document.getElementById(id);
        if (!container) {
            console.warn(`Container not found for leaderboard: ${id}`);
            return;
        }
        
        container.innerHTML = '';
        
        if (!lbData || lbData.length === 0) {
            console.log(`No data for leaderboard: ${id}`);
            container.appendChild(renderEmptyLeaderboard());
            return;
        }
        
        console.log(`Rendering ${lbData.length} entries for ${id}`);
        lbData.forEach(entry => {
            container.appendChild(renderLeaderboardEntry(entry, id));
        });
    });
}

// Setup leaderboard tab switching
function setupLeaderboardTabs() {
    const tabs = document.querySelectorAll('.lb-tab');
    
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.getAttribute('data-lb');
            const parent = tab.closest('.sidebar-section');
            
            // Update active tab
            parent.querySelectorAll('.lb-tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            
            // Show corresponding content
            const category = target.split('-')[0]; // 'xanax' or 'overdoses'
            parent.querySelectorAll('.leaderboard-content').forEach(content => {
                if (content.id === target) {
                    content.classList.remove('hidden');
                } else if (content.id.startsWith(category)) {
                    content.classList.add('hidden');
                }
            });
        });
    });
}

// Initialize leaderboards
async function initLeaderboards() {
    setupLeaderboardTabs();
    
    // Initial fetch
    const data = await fetchLeaderboards();
    if (data) {
        updateLeaderboards(data);
    }
    
    // Periodic refresh (every hour)
    setInterval(async () => {
        const data = await fetchLeaderboards();
        if (data) {
            updateLeaderboards(data);
        }
    }, leaderboard.FETCH_INTERVAL);
}

// Expose function to be called from main app when config is saved
window.refreshLeaderboards = async function() {
    console.log('Refreshing leaderboards after config update...');
    const data = await fetchLeaderboards();
    if (data) {
        updateLeaderboards(data);
    }
};

// Start leaderboards when page loads
document.addEventListener('DOMContentLoaded', () => {
    initLeaderboards();
});
