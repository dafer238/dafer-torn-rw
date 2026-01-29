# Orange Pi Deployment Guide

Complete guide to deploy Torn Ranked War Tracker to your Orange Pi with Cloudflare Tunnel.

## Table of Contents
- [Overview](#overview)
- [Stack Recommendations](#stack-recommendations)
- [Prerequisites](#prerequisites)
- [Installation Steps](#installation-steps)
- [Cloudflare Tunnel Setup](#cloudflare-tunnel-setup)
- [Service Management](#service-management)
- [Monitoring & Maintenance](#monitoring--maintenance)

---

## Overview

This application is a FastAPI-based web service that tracks Torn game ranked wars. It currently uses:
- **FastAPI** - Modern Python web framework
- **In-memory caching** - Lightweight, no external dependencies
- **Docker Compose** (optional) - For containerized deployment

**Target Domain:** `deadfragment.neodafer.com`

---

## Stack Recommendations

### Current Stack: ✅ **KEEP IT SIMPLE**

For Orange Pi self-hosting, the **current in-memory cache approach is BETTER** than Redis:

#### Why In-Memory Cache is Ideal:
- ✅ **Lower resource usage** - Orange Pi has limited RAM/CPU
- ✅ **No additional services** - One less thing to manage
- ✅ **Faster access** - No network/serialization overhead
- ✅ **Simpler deployment** - No Redis maintenance
- ✅ **Perfect for single instance** - No need for distributed cache

#### When You WOULD Need Redis:
- ❌ Multiple application instances (not your case)
- ❌ Cache persistence across restarts (war data is ephemeral)
- ❌ Shared cache between services (single service here)

### Recommended Deployment Method

**Native Python (systemd)** - Best for Orange Pi:
- Lower memory footprint (~50-100MB vs ~200-300MB with Docker)
- Faster startup
- Direct access to system resources
- Easier debugging

**Docker Compose** - Alternative:
- Better isolation
- Easier updates
- Slightly higher resource usage

---

## Prerequisites

### System Requirements
- Orange Pi running Ubuntu/Debian/Armbian
- Python 3.10+ installed
- Cloudflare Tunnel (cloudflared) already installed ✅
- Domain: `deadfragment.neodafer.com` pointed to Cloudflare

### Check Your Setup
```bash
# Check Python version
python3 --version

# Check if cloudflared is installed
cloudflared --version

# Check available memory
free -h
```

---

## Installation Steps

### Option 1: Native Python Deployment (Recommended)

#### 1. Clone Repository
```bash
# Create code directory if it doesn't exist
mkdir -p ~/code
cd ~/code

# Clone repository
git clone <your-repo-url> dafer-torn-rw
# OR transfer files via scp/sftp to ~/code/dafer-torn-rw

cd dafer-torn-rw
```

#### 2. Install Dependencies with uv
```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv directory structure
mkdir -p ~/code/python/venvs

# Create virtual environment with uv
uv venv ~/code/python/venvs/torn --python python3.10

# Activate virtual environment
source ~/code/python/venvs/torn/bin/activate

# Install dependencies with uv
cd ~/code/dafer-torn-rw
uv pip install -r requirements.txt
```

#### 3. Configure Environment
```bash
# Create .env file
nvim .env
```

Add the following (adjust values):
```env
# Torn API Configuration
ENEMY_FACTION_IDS=12345,67890
FACTION_ID=YOUR_FACTION_ID

# Leadership API Keys (comma-separated)
LEADERSHIP_WHITELIST=key1,key2,key3

# Cooldown Settings (in seconds)
DRUG_CD_MAX=480
MED_CD_MAX=360
BOOSTER_CD_MAX=2880

# Claim Settings
CLAIM_EXPIRY=300
MAX_CLAIMS_PER_USER=1

# These are not needed with in-memory cache
# KV_REST_API_URL=not-used
# KV_REST_API_TOKEN=not-used
```

#### 4. Test Run
```bash
# Activate venv if not already
source ~/code/python/venvs/torn/bin/activate

# Start application
cd ~/code/dafer-torn-rw
uvicorn main:app --host 0.0.0.0 --port 8003

# Test in another terminal
curl http://localhost:8003/api/health
```

#### 5. Create systemd Service
```bash
sudo nvim /etc/systemd/system/torn-rw-tracker.service
```

Add:
```ini
[Unit]
Description=Torn Ranked War Tracker
After=network.target

[Service]
Type=simple
User=dafer
WorkingDirectory=/home/dafer/code/dafer-torn-rw
Environment="PATH=/home/dafer/code/python/venvs/torn/bin"
EnvironmentFile=/home/dafer/code/dafer-torn-rw/.env
ExecStart=/home/dafer/code/python/venvs/torn/bin/uvicorn main:app --host 0.0.0.0 --port 8003
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service (start on boot)
sudo systemctl enable torn-rw-tracker

# Start service
sudo systemctl start torn-rw-tracker

# Check status
sudo systemctl status torn-rw-tracker
```

## Cloudflare Tunnel Setup

### Configure Tunnel for Your Domain

#### 1. Login to Cloudflare Tunnel
```bash
cloudflared tunnel login
```

#### 2. Create Tunnel (if not exists)
```bash
cloudflared tunnel create torn-tracker
```

#### 3. Configure Tunnel
```bash
nano ~/.cloudflared/config.yml
```

Add/update:
```yaml
tunnel: YOUR_TUNNEL_ID
credentials-file: /home/dafer/.cloudflared/YOUR_TUNNEL_ID.json

ingress:
  - hostname: deadfragment.neodafer.com
    service: http://localhost:8003
  - service: http_status:404
```

#### 4. Route DNS
```bash
cloudflared tunnel route dns torn-tracker deadfragment.neodafer.com
```

#### 5. Run Tunnel as Service
```bash
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
sudo systemctl status cloudflared
```

#### 6. Test
Visit `https://deadfragment.neodafer.com` - should show your application!

---

## Service Management

### Systemd Commands (Native Python)
```bash
# Start
sudo systemctl start torn-rw-tracker

# Stop
sudo systemctl stop torn-rw-tracker

# Restart
sudo systemctl restart torn-rw-tracker

# View logs
sudo journalctl -u torn-rw-tracker -f

# View recent logs
sudo journalctl -u torn-rw-tracker -n 100
```

### Docker Commands
```bash
# Start
docker-compose up -d

# Stop
docker-compose down

# Restart
docker-compose restart

# Logs
docker-compose logs -f

# Update (after code changes)
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

### Cloudflare Tunnel
```bash
# Restart tunnel
sudo systemctl restart cloudflared

# Check tunnel status
sudo systemctl status cloudflared

# View tunnel logs
sudo journalctl -u cloudflared -f
```

---

## Monitoring & Maintenance

### Health Check
```bash
# Local check
curl http://localhost:8003/api/health

# External check
curl https://deadfragment.neodafer.com/api/health
```

### Resource Monitoring
```bash
# CPU and Memory usage
htop

# Application process (native)
ps aux | grep uvicorn

# Docker stats
docker stats torn-rw-app
```

### Log Rotation

For native deployment, configure logrotate:
```bash
sudo nano /etc/logrotate.d/torn-rw-tracker
```

Add:
```
/var/log/torn-rw-tracker/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### Backup
```bash
# Backup configuration
tar -czf torn-rw-backup-$(date +%Y%m%d).tar.gz \
  ~/code/dafer-torn-rw/.env \
  ~/.cloudflared/config.yml

# Move to safe location
mv torn-rw-backup-*.tar.gz ~/backups/
```

---

## Troubleshooting

### Application Won't Start
```bash
# Check if port 8003 is in use
sudo lsof -i :8003

# Check service logs
sudo journalctl -u torn-rw-tracker -n 50 --no-pager
```

### Can't Access via Domain
```bash
# Check if cloudflared is running
sudo systemctl status cloudflared

# Check tunnel connection
cloudflared tunnel info torn-tracker

# Test local access first
curl http://localhost:8003/api/health
```

### High Memory Usage
```bash
# Check memory
free -h

# If needed, restart service
sudo systemctl restart torn-rw-tracker

# Consider adding swap if Orange Pi has <1GB RAM
```

### Update Application
```bash
# Native Python
cd ~/code/dafer-torn-rw
git pull
source ~/code/python/venvs/torn/bin/activate
uv pip install -r requirements.txt --upgrade
sudo systemctl restart torn-rw-tracker

# Docker
cd ~/code/dafer-torn-rw
git pull
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

---

## Performance Optimization Tips

1. **Enable HTTP/2** - Cloudflare handles this automatically
2. **Monitor cache hit rates** - Check application logs
3. **Adjust worker count** if needed:
   ```bash
   # Add to systemd ExecStart or use gunicorn
   uvicorn main:app --host 0.0.0.0 --port 8003 --workers 2
   ```
4. **Set up fail2ban** to protect SSH access
5. **Regular updates**:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

---

## Summary

✅ **Recommended Setup:**
- Native Python with systemd
- In-memory cache (current implementation)
- Cloudflare Tunnel for secure external access
- No Redis needed

This gives you the best performance and lowest resource usage on Orange Pi while maintaining simplicity and reliability.

**Your application will be accessible at:**
- Externally: `https://deadfragment.neodafer.com`
- Locally: `http://localhost:8003`

Good luck with your deployment! 🎉
