# Self-Hosting Torn RW Tracker on Orange Pi Zero 3

Complete guide to self-host the Torn RW Tracker on Orange Pi Zero 3 (Ubuntu Noble) using Cloudflare Tunnel.

## Prerequisites

- Orange Pi Zero 3 with Ubuntu 24.04 (Noble) installed
- Domain name (e.g., `deadfragment.com`) with Cloudflare DNS
- SSH access to Orange Pi
- Basic terminal knowledge

## Overview

The tracker will be accessible at: `https://deadfragment.com/rw`

**Two Setup Options:**

### Option 1: Docker (Recommended - Simplest)
- ✅ Single command to start everything
- ✅ Easy updates and rollbacks
- ✅ Isolated environment
- ✅ Auto-restart on failure
- **Architecture:** Docker Compose (FastAPI + Redis) + Cloudflare Tunnel

### Option 2: Native (Manual Control)
- ✅ Direct control over services
- ✅ No Docker overhead
- ✅ Lighter resource usage
- **Architecture:** FastAPI (Uvicorn) + Redis + Systemd + Cloudflare Tunnel

**Choose your preferred option below.**

---

# 🐳 OPTION 1: Docker Setup (Recommended)

## Step 1: Install Docker

SSH into your Orange Pi and install Docker:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install -y docker-compose

# Reboot to apply group changes
sudo reboot
```

After reboot, verify installation:
```bash
docker --version
docker-compose --version
```

---

## Step 2: Upload Application Files

From your Windows machine:

```powershell
# Run in your project directory (c:\Users\dafer\code\python\torn_rw)
scp -r * your-username@orangepi-ip:/home/your-username/torn_rw/
```

Or create the directory and upload manually via WinSCP/FileZilla.

---

## Step 3: Create Docker Configuration

SSH back into Orange Pi:

```bash
cd ~/torn_rw
```

Create `Dockerfile`:

```bash
nano Dockerfile
```

Add:
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `docker-compose.yml`:

```bash
nano docker-compose.yml
```

Add:
```yaml
version: '3.8'

services:
  app:
    build: .
    container_name: torn-rw-app
    restart: unless-stopped
    ports:
      - "8000:8000"
    environment:
      - ENEMY_FACTION_IDS=${ENEMY_FACTION_IDS}
      - FACTION_ID=${FACTION_ID}
      - CLAIM_EXPIRY=${CLAIM_EXPIRY:-120}
      - MAX_CLAIMS_PER_USER=${MAX_CLAIMS_PER_USER:-3}
      - KV_REST_API_URL=redis://redis:6379
      - KV_REST_API_TOKEN=not-needed
    depends_on:
      - redis
    networks:
      - torn-network

  redis:
    image: redis:7-alpine
    container_name: torn-rw-redis
    restart: unless-stopped
    volumes:
      - redis-data:/data
    networks:
      - torn-network
    command: redis-server --appendonly yes

volumes:
  redis-data:

networks:
  torn-network:
    driver: bridge
```

---

## Step 4: Configure Environment Variables

Create `.env` file:

```bash
nano .env
```

Add your configuration:
```bash
# Enemy Faction IDs (comma-separated)
ENEMY_FACTION_IDS=12345,67890

# Your Faction ID (restricts access to your faction)
FACTION_ID=11111

# Claim Configuration
CLAIM_EXPIRY=120
MAX_CLAIMS_PER_USER=3
```

**Replace with your actual faction IDs!**

---

## Step 5: Update FastAPI for Subdirectory

Edit `main.py` to support `/rw` path:

```bash
nano main.py
```

Find the line:
```python
app = FastAPI(
```

And ensure it includes:
```python
app = FastAPI(
    title="Torn Ranked War Tracker",
    description="Real-time situational awareness for Torn ranked wars",
    version="1.0.0",
    lifespan=lifespan,
    root_path="/rw",  # Add this line
)
```

---

## Step 6: Start Application

Build and start containers:

```bash
# Build and start in background
docker-compose up -d

# View logs
docker-compose logs -f

# Check status
docker-compose ps
```

Test locally:
```bash
curl http://localhost:8000/
```

You should see HTML content!

---

## Step 7: Install Cloudflare Tunnel

```bash
cd ~
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared-linux-arm64.deb
```

---

## Step 8: Authenticate Cloudflare

```bash
cloudflared tunnel login
```

Open the provided URL in a browser and authorize.

---

## Step 9: Create Tunnel

```bash
cloudflared tunnel create torn-rw
```

Save the tunnel ID from the output!

---

## Step 10: Configure Tunnel

```bash
sudo mkdir -p /etc/cloudflared
sudo nano /etc/cloudflared/config.yml
```

Add (replace `<TUNNEL-ID>` with your actual ID):

```yaml
tunnel: <TUNNEL-ID>
credentials-file: /root/.cloudflared/<TUNNEL-ID>.json

ingress:
  - hostname: deadfragment.com
    service: http://localhost:8000
  - service: http_status:404
```

---

## Step 11: Route DNS

```bash
cloudflared tunnel route dns torn-rw deadfragment.com
```

---

## Step 12: Start Tunnel Service

```bash
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
sudo systemctl status cloudflared
```

---

## Step 13: Test!

Wait 1-2 minutes for DNS propagation, then visit:

**https://deadfragment.com/rw/**

✅ Done! Your tracker is live.

---

## Docker Management

```bash
# View logs
docker-compose logs -f app

# Restart application
docker-compose restart app

# Stop everything
docker-compose down

# Update application (after code changes)
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# View resource usage
docker stats

# Clean up old images
docker system prune -a
```

---

# 🔧 OPTION 2: Native Setup (No Docker)

## Step 1: Initial Setup

SSH into your Orange Pi and update the system:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git redis-server curl
```

---

## Step 2: Create Application User

```bash
sudo useradd -r -m -s /bin/bash tornrw
sudo mkdir -p /opt/torn_rw
sudo chown tornrw:tornrw /opt/torn_rw
```

---

## Step 3: Install Application

Upload files from Windows:

```powershell
# From Windows (run in your project directory)
scp -r * your-username@orangepi-ip:/tmp/torn_rw/
```

Then on Orange Pi:
```bash
sudo mv /tmp/torn_rw/* /opt/torn_rw/
sudo chown -R tornrw:tornrw /opt/torn_rw

# Switch to application user
sudo su - tornrw
cd /opt/torn_rw

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

exit  # Exit tornrw user
```

---

## Step 4: Configure Environment Variables

Create the `.env` file:

```bash
sudo nano /opt/torn_rw/.env
```

Add the following (same as Vercel):

```bash
# Enemy Faction IDs (comma-separated)
ENEMY_FACTION_IDS=12345,67890

# Your Faction ID (optional, restricts access to your faction only)
FACTION_ID=11111

# Claim Configuration
CLAIM_EXPIRY=120
MAX_CLAIMS_PER_USER=3

# Redis Configuration (local Redis)
KV_REST_API_URL=redis://localhost:6379
KV_REST_API_TOKEN=not-needed-for-local-redis

# Optional: If you want to use Upstash Redis instead
# KV_REST_API_URL=https://your-upstash-url.upstash.io
# KV_REST_API_TOKEN=your-upstash-token
```

**Important:** Replace the faction IDs with your actual values.

Set proper permissions:

```bash
sudo chmod 600 /opt/torn_rw/.env
sudo chown tornrw:tornrw /opt/torn_rw/.env
```

---

## Step 5: Configure Redis

Start and enable Redis:

```bash
sudo systemctl enable redis-server
sudo systemctl start redis-server
sudo systemctl status redis-server
```

---

## Step 6: Update FastAPI for Subdirectory

Edit `/opt/torn_rw/main.py`:

```bash
sudo nano /opt/torn_rw/main.py
```

Find this line and ensure it includes `root_path`:
```python
app = FastAPI(
    title="Torn Ranked War Tracker",
    description="Real-time situational awareness for Torn ranked wars",
    version="1.0.0",
    lifespan=lifespan,
    root_path="/rw",  # Add this line for subdirectory support
)
```

---

## Step 7: Create Systemd Service

Create the service file:

```bash
sudo nano /etc/systemd/system/torn-rw.service
```

Add this configuration:

```ini
[Unit]
Description=Torn RW Tracker
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=tornrw
Group=tornrw
WorkingDirectory=/opt/torn_rw
Environment="PATH=/opt/torn_rw/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/opt/torn_rw/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable torn-rw
sudo systemctl start torn-rw
sudo systemctl status torn-rw
```

Check logs:
```bash
sudo journalctl -u torn-rw -f
```

You should see: "Uvicorn running on http://0.0.0.0:8000"

Test locally:
```bash
curl http://localhost:8000/
```

---

## Step 8: Install Cloudflare Tunnel

```bash
cd ~
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared-linux-arm64.deb
```

---

## Step 9: Authenticate Cloudflare

```bash
cloudflared tunnel login
```

Open the provided URL in a browser and authorize.

---

## Step 10: Create Tunnel

```bash
cloudflared tunnel create torn-rw
```

Save the tunnel ID from the output!

---

## Step 11: Configure Tunnel

```bash
sudo mkdir -p /etc/cloudflared
sudo nano /etc/cloudflared/config.yml
```

Add (replace `<TUNNEL-ID>` with your actual ID):

```yaml
tunnel: <TUNNEL-ID>
credentials-file: /root/.cloudflared/<TUNNEL-ID>.json

ingress:
  - hostname: deadfragment.com
    service: http://localhost:8000
  - service: http_status:404
```

---

## Step 12: Route DNS

```bash
cloudflared tunnel route dns torn-rw deadfragment.com
```

---

## Step 13: Start Tunnel Service

```bash
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
sudo systemctl status cloudflared
```

---

## Step 14: Test!

Wait 1-2 minutes for DNS propagation, then visit:

**https://deadfragment.com/rw/**

✅ Done! Your tracker is live.

---

## Monitoring & Maintenance (Native Setup)

### Check Service Status
```bash
sudo systemctl status torn-rw
sudo systemctl status redis-server
sudo systemctl status cloudflared
```

### View Logs
```bash
# Application logs
sudo journalctl -u torn-rw -f

# Cloudflare Tunnel logs
sudo journalctl -u cloudflared -f
```

### Restart Services
```bash
sudo systemctl restart torn-rw
sudo systemctl restart cloudflared
```

### Update Application
```bash
cd /opt/torn_rw
sudo su - tornrw
source venv/bin/activate
# Upload new files or git pull
pip install -r requirements.txt
exit
sudo systemctl restart torn-rw
```

---

## Resource Usage

Expected usage on Orange Pi Zero 3:
- **RAM:** ~150-200 MB
- **CPU:** 5-10% average, spikes to 20% during polling
- **Disk:** ~100 MB
- **Network:** Minimal (~1-2 MB/hour)
- **Power:** ~2-3W

---

## Troubleshooting

### Docker: App won't start
```bash
# Check logs
docker-compose logs app

# Check container status
docker-compose ps

# Test manually
docker-compose exec app python -c "import main"
```

### Native: App won't start
```bash
# Check logs
sudo journalctl -u torn-rw -n 50

# Test manually
sudo su - tornrw
cd /opt/torn_rw
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

### Can't connect via Cloudflare
```bash
# Check tunnel status
sudo cloudflared tunnel info torn-rw

# Check DNS
nslookup deadfragment.com

# Restart tunnel
sudo systemctl restart cloudflared

# Check tunnel logs
sudo journalctl -u cloudflared -n 50
```

### Redis connection issues (Docker)
```bash
# Check Redis container
docker-compose logs redis

# Test connection
docker-compose exec redis redis-cli ping  # Should return "PONG"
```

### Redis connection issues (Native)
```bash
# Check Redis
sudo systemctl status redis-server
redis-cli ping  # Should return "PONG"
```

### Port already in use
```bash
# Check what's using port 8000
sudo netstat -tlnp | grep 8000

# Kill the process or change port in docker-compose.yml
```

---

## Security Notes

1. **Firewall:** No need to open ports (Cloudflare Tunnel handles everything)
2. **HTTPS:** Automatically provided by Cloudflare
3. **API Keys:** Users provide their own, never stored on server
4. **Faction Restriction:** Set `FACTION_ID` in `.env` to restrict access
5. **Updates:** Keep Ubuntu and packages updated:
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

---

## Performance Tuning (Optional)

### Docker: Increase Workers
Edit `docker-compose.yml`:
```yaml
    command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

Then:
```bash
docker-compose down
docker-compose up -d
```

### Native: Increase Workers
Edit `/etc/systemd/system/torn-rw.service`:
```ini
ExecStart=/opt/torn_rw/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl restart torn-rw
```

### Add Swap (both setups)
```bash
sudo fallocate -l 1G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## Backup

### Docker Backup

```bash
sudo nano /opt/backup-torn-rw-docker.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/torn-rw"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup Redis data from Docker volume
docker-compose exec -T redis redis-cli BGSAVE
sleep 5
docker cp torn-rw-redis:/data/dump.rdb $BACKUP_DIR/redis_$DATE.rdb

# Backup env file
cp ~/torn_rw/.env $BACKUP_DIR/env_$DATE

# Keep only last 7 backups
find $BACKUP_DIR -name "*.rdb" -mtime +7 -delete
find $BACKUP_DIR -name "env_*" -mtime +7 -delete
```

### Native Backup

```bash
sudo nano /opt/backup-torn-rw.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/torn-rw"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup Redis data
redis-cli BGSAVE
sleep 5
cp /var/lib/redis/dump.rdb $BACKUP_DIR/redis_$DATE.rdb

# Backup env file
cp /opt/torn_rw/.env $BACKUP_DIR/env_$DATE

# Keep only last 7 backups
find $BACKUP_DIR -name "*.rdb" -mtime +7 -delete
find $BACKUP_DIR -name "env_*" -mtime +7 -delete
```

Make executable and schedule:
```bash
sudo chmod +x /opt/backup-torn-rw*.sh

# Add to crontab (daily backup at 3 AM)
sudo crontab -e

# Add line:
0 3 * * * /opt/backup-torn-rw-docker.sh  # or backup-torn-rw.sh for native
```

---

## Cost Breakdown

- **Orange Pi Zero 3:** ~$30 one-time
- **Power (24/7):** ~$0.20/month
- **Domain:** ~$12/year (if new)
- **Cloudflare:** $0 (free plan)
- **Total monthly:** ~$0.20 (after hardware purchase)

**vs Vercel Pro:** $20/month

**Savings:** ~$240/year

---

## Success!

Your Torn RW Tracker is now running at:
**https://deadfragment.com/rw/**

- ✅ No free tier limits
- ✅ Automatic HTTPS
- ✅ Auto-starts on boot
- ✅ Persistent Redis storage
- ✅ Professional setup

Share the URL with your faction members and enjoy unlimited usage! 🎉
