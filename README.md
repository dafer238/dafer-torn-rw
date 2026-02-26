# Torn Ranked War Tracker

Real-time situational awareness for Torn ranked wars. Track hospital timers, online status, and coordinate attacks with your faction.

## Features

- **Hospital Timers**: Real-time countdown timers with sub-second client-side updates
- **Online Detection**: Inferred online status from last action timestamps
- **Med Detection**: Alerts when targets leave hospital early (medding out)
- **Hit Claiming**: Coordinate attacks to prevent overlap
- **Smart Caching**: Aggressive polling while respecting Torn's rate limits
- **YATA Integration**: Battle stats estimates from YATA's ML models
- **TornStats Integration**: Faction spy database lookup
- **Faction Overview**: Leadership view of member status/cooldowns
- **Leaderboards**: Track xanax/overdose stats

## Architecture

- **Backend**: FastAPI (Python) with async HTTP client
- **Frontend**: Static HTML/CSS/JS with client-side timers
- **Storage**: Pure in-memory (no Redis, no file I/O in hot path)
- **Deployment**: systemd service + nginx reverse proxy on Hetzner VPS
- **Domain**: `df.neodafer.com` → nginx → `localhost:8005`

## Setup (Hetzner VPS)

### 1. Clone and install

```bash
cd /home/dafer/code/python/dafer-torn-rw
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
nano .env
```

Key settings:
- `ENEMY_FACTION_IDS` - comma-separated enemy faction IDs
- `FACTION_ID` - restrict access to your faction
- `FRONTEND_POLL_INTERVAL` - how often the browser fetches data (ms, default: 1000)
- `CACHE_TTL` - how long to cache Torn API responses (seconds, default: 1)

### 3. Install systemd service

```bash
sudo cp torn.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable torn
sudo systemctl start torn
```

Check status:
```bash
sudo systemctl status torn
sudo journalctl -u torn -f
```

### 4. Setup nginx

```bash
sudo cp nginx/df.neodafer.com.conf /etc/nginx/sites-available/df.neodafer.com
sudo ln -s /etc/nginx/sites-available/df.neodafer.com /etc/nginx/sites-enabled/
sudo certbot --nginx -d df.neodafer.com
sudo nginx -t && sudo systemctl reload nginx
```

### 5. DNS

Point `df.neodafer.com` A record to `46.225.116.100`.

## Configuration (.env)

| Variable                 | Default     | Description                            |
| ------------------------ | ----------- | -------------------------------------- |
| `HOST`                   | `127.0.0.1` | Bind address                           |
| `PORT`                   | `8005`      | Bind port                              |
| `FRONTEND_POLL_INTERVAL` | `1000`      | Browser poll interval (ms)             |
| `CACHE_TTL`              | `1`         | Torn API cache TTL (seconds)           |
| `ENEMY_FACTION_IDS`      |             | Enemy faction IDs (comma-separated)    |
| `FACTION_ID`             |             | Restrict to this faction               |
| `LEADERSHIP_WHITELIST`   |             | Player IDs for faction overview access |
| `CLAIM_EXPIRY`           | `300`       | Claim auto-expire time (seconds)       |
| `MAX_CLAIMS_PER_USER`    | `1`         | Max concurrent claims per user         |
| `DRUG_CD_MAX`            | `480`       | Max drug cooldown (minutes)            |
| `MED_CD_MAX`             | `540`       | Max medical cooldown (minutes)         |
| `BOOSTER_CD_MAX`         | `2880`      | Max booster cooldown (minutes)         |

## API Endpoints

| Endpoint                | Method | Description                          |
| ----------------------- | ------ | ------------------------------------ |
| `/api/status`           | GET    | All targets with hospital timers     |
| `/api/me`               | GET    | Current user's status/bars/cooldowns |
| `/api/claim`            | POST   | Claim a target                       |
| `/api/claim/{id}`       | DELETE | Release a claim                      |
| `/api/claims`           | GET    | List active claims                   |
| `/api/config`           | GET    | Server configuration                 |
| `/api/health`           | GET    | Health check                         |
| `/api/stats`            | GET    | Cache and rate limit stats           |
| `/api/leaderboards`     | GET    | Faction leaderboards                 |
| `/api/faction-overview` | GET    | Leadership member overview           |
| `/api/faction-config`   | GET    | Cooldown config                      |
| `/api/tornstats/{id}`   | GET    | TornStats spy data                   |

## User Authentication

Users provide their own Torn API keys via the frontend (`X-API-Key` header). The tracker validates faction membership and caches it for 5 minutes.

## License

MIT
