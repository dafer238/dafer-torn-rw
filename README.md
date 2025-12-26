# Torn Ranked War Tracker

Real-time situational awareness for Torn ranked wars. Track hospital timers, online status, and coordinate attacks with your faction.

## Features

- **Hospital Timers**: Real-time countdown timers with sub-second client-side updates
- **Online Detection**: Inferred online status from last action timestamps
- **Med Detection**: Alerts when targets leave hospital early (medding out)
- **Hit Claiming**: Coordinate attacks to prevent overlap
- **Smart Caching**: Aggressive polling while respecting Torn's rate limits

## Architecture

- **Backend**: FastAPI (Python) with async HTTP client
- **Frontend**: Static HTML/CSS/JS with client-side timers
- **Polling**: Backend polls Torn API every 2 seconds, frontend polls backend every 1 second
- **Deployment**: Vercel serverless functions + static hosting

## Rate Limits

Torn allows **100 API requests per minute per user**. This app:
- Polls enemy faction data every 2 seconds (30 req/min)
- Leaves room for multiple API keys for higher throughput
- Uses caching to serve frontend requests instantly

## Setup

### 1. Clone and Install

```bash
cd torn_rw
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in:

```env
# Required: Enemy factions to track
ENEMY_FACTION_IDS=12345,67890

# Optional: Restrict access to your faction only
FACTION_ID=your_faction_id

# Optional: Upstash Redis for shared claim state (auto-configured on Vercel)
# KV_REST_API_URL=https://...
# KV_REST_API_TOKEN=...
```

**Note**: Users will provide their own API keys via the frontend. No central API key needed!

### 3. Run Locally

```bash
python main.py
```

Open http://localhost:8000 in your browser.

### 4. Deploy to Vercel

```bash
npm i -g vercel
vercel login
vercel --prod
```

Set secrets in Vercel dashboard:
- `ENEMY_FACTION_IDS` (required) - Comma-separated faction IDs to track
- `FACTION_ID` (optional) - If set, only members of this faction can use the tracker
- `KV_REST_API_URL` - Upstash Redis URL (auto-configured if using Vercel Storage)
- `KV_REST_API_TOKEN` - Upstash Redis token (auto-configured if using Vercel Storage)

**Faction Restriction**: When `FACTION_ID` is set, the tracker validates each API key to ensure the user belongs to your faction. This prevents unauthorized access from other players. Leave unset to allow anyone with a valid Torn API key to use it.

## User Authentication

Users provide their own API keys via the frontend. The tracker:
1. Validates the API key with Torn's API
2. Checks faction membership (if `FACTION_ID` is configured)
3. Caches validation for 5 minutes to reduce API calls
4. Uses the API key to fetch target data on their behalf

This means:
- No central API key needed (users bring their own)
- Each user stays within their own rate limits
- Faction restriction ensures only teammates can access

## API Endpoints

| Endpoint          | Method | Description                          |
| ----------------- | ------ | ------------------------------------ |
| `/api/status`     | GET    | Get all targets with hospital timers |
| `/api/claim`      | POST   | Claim a target                       |
| `/api/claim/{id}` | DELETE | Release a claim                      |
| `/api/claims`     | GET    | List all active claims               |
| `/api/health`     | GET    | Health check                         |
| `/api/stats`      | GET    | Cache and rate limit stats           |

## Frontend Configuration

On first load, enter your Torn ID and name. This is stored locally in your browser and used for:
- Identifying your claims
- Showing which targets you've claimed

## Polling Strategy

The app uses a two-tier polling strategy for perceived real-time updates:

1. **Backend → Torn API**: Every 2 seconds
   - Fetches faction member data
   - Updates hospital timers
   - Detects medding behavior

2. **Frontend → Backend**: Every 1 second
   - Gets cached data instantly
   - Smooth countdown timers (100ms client-side updates)
   - Claim state synchronization

## Security

- **User-provided API keys**: Each user brings their own API key, sent via `X-API-Key` header
- **Faction validation**: Optional `FACTION_ID` restricts access to faction members only
- **Validation caching**: Faction membership cached for 5 minutes to reduce API calls
- **CORS configured**: Prevents unauthorized cross-origin access
- **Rate limiting**: Each user operates within their own Torn API rate limits

## Data Model

### PlayerStatus
```json
{
    "user_id": 1234567,
    "name": "TargetPlayer",
    "level": 75,
    "hospital_until": 1703500000,
    "hospital_remaining": 45,
    "hospital_status": "about_to_exit",
    "estimated_online": "online",
    "medding": false,
    "claimed_by": "YourName",
    "claimed_at": 1703499900
}
```

### HitClaim
```json
{
    "target_id": 1234567,
    "target_name": "TargetPlayer",
    "claimed_by": "Attacker",
    "claimed_by_id": 7654321,
    "claimed_at": 1703499900,
    "expires_at": 1703500020
}
```

## Known Limitations

- **Not truly real-time**: Torn API is pull-based, ~2 second delay minimum
- **Online detection is heuristic**: Based on last action timestamp
- **Med detection has false positives**: Early hospital exit could be attack-related
- **Single instance state**: Claims are in-memory (Redis upgrade possible)

## License

MIT - Use at your own risk. Not affiliated with Torn.
