# File-Based Persistence Layer

Lightweight JSON file storage for self-hosted deployments.

## Overview

This module provides automatic file-based persistence when Redis/Vercel KV is not configured. It's designed for single-instance deployments like Orange Pi or other self-hosted environments.

## Features

- **Automatic detection**: Uses file storage when `KV_REST_API_URL` is not set
- **Thread-safe**: Safe for concurrent access from async/sync code
- **TTL support**: Automatic expiration of time-based data
- **Atomic writes**: Uses temp files + rename for crash safety
- **Low overhead**: Direct JSON file I/O, no network calls

## Storage Structure

```
data/
├── claims.json              # Active hit claims
├── yata_cache.json          # YATA battle stats estimates
├── faction_profiles.json    # Faction member profiles
└── leaderboards.json        # User statistics history
```

## How It Works

### Automatic Mode Selection

The application automatically chooses storage backend:

```python
from api.file_storage import is_self_hosted

if is_self_hosted():
    # Uses file storage in data/ directory
    # No Redis/KV configured
else:
    # Uses Vercel KV / Redis
    # KV_REST_API_URL is configured
```

### Data Persistence

- **Claims**: Stored with expiration time, auto-deleted when expired
- **YATA cache**: Permanent storage (no expiration)
- **Faction profiles**: Permanent storage, updated on each user action
- **Leaderboards**: Historical data, trimmed to last 365 days

### Example Usage

```python
from api.file_storage import get_file_storage

storage = get_file_storage()

# Store data
storage.set("namespace", "key", {"data": "value"})

# Store with expiration (5 minutes)
storage.set("namespace", "key", {"data": "value"}, ex=300)

# Retrieve data
data = storage.get("namespace", "key")

# Get all keys in namespace
keys = storage.keys("namespace")

# Get all data in namespace
all_data = storage.get_all("namespace")

# Delete key
storage.delete("namespace", "key")
```

## Configuration

No configuration needed! Just don't set these environment variables:

```env
# Leave these UNSET for self-hosted mode
# KV_REST_API_URL=
# KV_REST_API_TOKEN=
```

## Backup & Restore

### Backup
```bash
# Backup all persistent data
tar -czf data-backup-$(date +%Y%m%d).tar.gz data/

# Or use rsync for incremental backups
rsync -av data/ ~/backups/torn-tracker-data/
```

### Restore
```bash
# Stop service
sudo systemctl stop torn-rw-tracker

# Restore data
tar -xzf data-backup-YYYYMMDD.tar.gz

# Start service
sudo systemctl start torn-rw-tracker
```

## Performance

- **Read latency**: <1ms (direct file I/O)
- **Write latency**: <5ms (atomic write with fsync)
- **Memory usage**: Minimal (files loaded on-demand)
- **Disk usage**: ~1-5MB for typical faction data

## Thread Safety

All operations are thread-safe with per-namespace locking:
- Multiple reads can happen concurrently
- Writes are serialized per namespace
- No risk of corrupted data

## Maintenance

### Cleanup Expired Data

Expired entries are automatically removed during reads. To force cleanup:

```python
storage = get_file_storage()
# Reading keys triggers cleanup
storage.keys("namespace")
```

### Monitor Storage

```python
storage = get_file_storage()
stats = storage.stats()
# Returns: {'storage_dir': 'data/', 'namespaces': {...}}
```

## Migration from Redis

If you previously used Redis and want to migrate to file storage:

1. Export data from Redis (if needed)
2. Stop application
3. Remove `KV_REST_API_URL` and `KV_REST_API_TOKEN` from `.env`
4. Start application - it will use file storage automatically
5. Data will accumulate as users interact with the application

## Advantages Over Redis

For single-instance self-hosted deployments:

- ✅ No external dependencies
- ✅ No service to manage/monitor
- ✅ Lower memory usage
- ✅ Easier backups (just files)
- ✅ Faster access (no network)
- ✅ Simpler troubleshooting (human-readable JSON)

## When to Use Redis Instead

Consider Redis/Vercel KV if:

- Multiple application instances need shared state
- Deploying to serverless (Vercel, AWS Lambda)
- Need distributed caching
- Want managed backup/replication

## Troubleshooting

### Permission Errors
```bash
# Ensure data directory is writable
chmod 755 data/
chown dafer:dafer data/
```

### Corrupted Files
```bash
# Backup and remove corrupted file
mv data/corrupted.json data/corrupted.json.bak

# Service will recreate on next write
sudo systemctl restart torn-rw-tracker
```

### Large File Sizes
```bash
# Check file sizes
du -sh data/*

# If leaderboards.json is too large, trim history
# (automatically limited to 365 days)
```

## Implementation Details

- Uses `threading.Lock` for thread safety
- Atomic writes via temp file + rename
- JSON serialization with `ensure_ascii=False` for UTF-8
- Expiration metadata stored inline with data
- Lazy loading (files read on-demand)
