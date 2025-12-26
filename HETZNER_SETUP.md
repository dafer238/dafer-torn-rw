# Hetzner Ubuntu Server Setup Guide

Complete guide to deploy the Torn RW Tracker on Hetzner Cloud using Nginx at `https://deadfragment.com/rw/`

## Prerequisites

- Hetzner Cloud account
- Domain `deadfragment.com` registered on Cloudflare
- SSH access to server
- Basic Linux/terminal knowledge

---

## Part 1: Hetzner Server Setup

### Step 1: Create Hetzner Server

1. Log into [Hetzner Cloud Console](https://console.hetzner.cloud/)
2. Create new project (e.g., "Torn Tracker")
3. Add new server:
   - **Location**: Choose closest to you (e.g., Nuremberg, Helsinki)
   - **Image**: Ubuntu 24.04 LTS
   - **Type**: CPX11 (2 vCPU, 2GB RAM) - ~€4.51/month
   - **SSH Key**: Add your SSH public key
   - **Firewall**: Create firewall (see below)
   - **Volume**: Not needed
   - **Network**: Default is fine

### Step 2: Configure Firewall

In Hetzner Console, create firewall with these rules:

**Inbound Rules:**
- SSH: Port 22, Source: Your IP (or 0.0.0.0/0 if dynamic IP)
- HTTP: Port 80, Source: 0.0.0.0/0
- HTTPS: Port 443, Source: 0.0.0.0/0

**Outbound Rules:**
- Allow all

Apply this firewall to your server.

### Step 3: Initial Server Setup

SSH into your server:
```bash
ssh root@YOUR_SERVER_IP
```

Update system:
```bash
apt update && apt upgrade -y
```

Create non-root user (optional but recommended):
```bash
adduser tornrw
usermod -aG sudo tornrw
```

---

## Part 2: Cloudflare DNS Configuration

### Step 1: Point Domain to Hetzner Server

1. Log into [Cloudflare Dashboard](https://dash.cloudflare.com/)
2. Select your domain `deadfragment.com`
3. Go to **DNS** > **Records**
4. Add/Update A record:
   - **Type**: A
   - **Name**: @ (or deadfragment.com)
   - **IPv4 address**: YOUR_HETZNER_SERVER_IP
   - **Proxy status**: ⚠️ **DNS only (gray cloud)** - Important for Let's Encrypt
   - **TTL**: Auto

5. Wait 5-10 minutes for DNS propagation

Verify DNS:
```bash
# From your local machine
nslookup deadfragment.com
# Should return your Hetzner server IP
```

---

## Part 3: Install Required Software

### Option A: Docker Setup (Recommended)

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt install -y docker-compose

# Add your user to docker group
sudo usermod -aG docker $USER

# Apply group changes
newgrp docker

# Verify installation
docker --version
docker-compose --version
```

### Option B: Native Setup

```bash
# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip

# Install Redis
sudo apt install -y redis-server

# Install Nginx
sudo apt install -y nginx

# Install Certbot for SSL
sudo apt install -y certbot python3-certbot-nginx
```

---

## Part 4: Deploy Application

### Create Application Directory

```bash
sudo mkdir -p /opt/torn_rw
sudo chown $USER:$USER /opt/torn_rw
cd /opt/torn_rw
```

### Upload Application Files

From your Windows machine, upload files via SCP:

```powershell
# Run in PowerShell from your project directory
scp -r * root@YOUR_SERVER_IP:/opt/torn_rw/
```

Or use WinSCP/FileZilla for GUI transfer.

### Configure Environment Variables

Create `.env` file:

```bash
cd /opt/torn_rw
nano .env
```

Add the following configuration:

```bash
# Required: Enemy Faction IDs to track (comma-separated)
ENEMY_FACTION_IDS=12345,67890

# Optional: Restrict access to your faction only
FACTION_ID=11111

# Leadership Whitelist (comma-separated player IDs who can access faction overview)
# Leave blank to disable faction overview feature
LEADERSHIP_WHITELIST=123456,789012

# Faction Overview - Max Cooldown Times (in minutes)
# Adjust based on your faction perks
DRUG_CD_MAX=480      # 8 hours (xanax default)
MED_CD_MAX=360       # 6 hours (medical cooldown)
BOOSTER_CD_MAX=2880  # 48 hours (booster cooldown)

# Claim Configuration
CLAIM_EXPIRY=120          # Claim expires after 2 minutes
MAX_CLAIMS_PER_USER=3     # Max simultaneous claims per user

# Redis Configuration
KV_REST_API_URL=redis://localhost:6379
KV_REST_API_TOKEN=not-needed-for-local-redis

# Optional: Upstash Redis (if you prefer cloud Redis)
# KV_REST_API_URL=https://your-upstash-url.upstash.io
# KV_REST_API_TOKEN=your-upstash-token
```

**Important:** Replace the faction IDs with your actual values!

Set proper permissions:
```bash
chmod 600 .env
```

---

## Part 5: Configure Application for /rw Path

### Update main.py

Edit `main.py` to support subdirectory deployment:

```bash
nano /opt/torn_rw/main.py
```

Find the `FastAPI` initialization (around line 60-70) and ensure it has `root_path="/rw"`:

```python
app = FastAPI(
    title="Torn Ranked War Tracker",
    description="Real-time situational awareness for Torn ranked wars",
    version="1.0.0",
    lifespan=lifespan,
    root_path="/rw",  # Important: serves app at /rw path
)
```

---

## Part 6A: Docker Deployment

### Update docker-compose.yml

Ensure `docker-compose.yml` has correct port mapping:

```yaml
version: "3.8"

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
      - LEADERSHIP_WHITELIST=${LEADERSHIP_WHITELIST}
      - DRUG_CD_MAX=${DRUG_CD_MAX:-480}
      - MED_CD_MAX=${MED_CD_MAX:-360}
      - BOOSTER_CD_MAX=${BOOSTER_CD_MAX:-2880}
      - CLAIM_EXPIRY=${CLAIM_EXPIRY:-300}
      - MAX_CLAIMS_PER_USER=${MAX_CLAIMS_PER_USER:-1}
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

### Build and Start Containers

```bash
cd /opt/torn_rw

# Build and start
docker-compose up -d

# Check logs
docker-compose logs -f

# Verify it's running
curl http://localhost:8000/
```

You should see HTML output!

---

## Part 6B: Native Deployment (Alternative)

If you prefer not to use Docker:

### Install Python Dependencies

```bash
cd /opt/torn_rw
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure Redis

```bash
sudo systemctl enable redis-server
sudo systemctl start redis-server
redis-cli ping  # Should return "PONG"
```

### Create Systemd Service

```bash
sudo nano /etc/systemd/system/torn-rw.service
```

Add:

```ini
[Unit]
Description=Torn RW Tracker
After=network.target redis-server.service
Requires=redis-server.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/torn_rw
Environment="PATH=/opt/torn_rw/venv/bin"
EnvironmentFile=/opt/torn_rw/.env
ExecStart=/opt/torn_rw/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Start service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable torn-rw
sudo systemctl start torn-rw
sudo systemctl status torn-rw
```

---

## Part 7: Nginx Configuration

### Create Nginx Config

```bash
sudo nano /etc/nginx/sites-available/deadfragment.com
```

Add the following configuration:

```nginx
# HTTP - Redirect to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name deadfragment.com www.deadfragment.com;
    
    # Allow Certbot for SSL certificate validation
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    # Redirect all other traffic to HTTPS
    location / {
        return 301 https://$server_name$request_uri;
    }
}

# HTTPS - Main Configuration
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name deadfragment.com www.deadfragment.com;
    
    # SSL certificates (will be added by Certbot)
    # ssl_certificate /etc/letsencrypt/live/deadfragment.com/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/deadfragment.com/privkey.pem;
    
    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    
    # Root site (you can serve other content here)
    location / {
        root /var/www/html;
        index index.html index.htm;
        try_files $uri $uri/ =404;
    }
    
    # Torn RW Tracker at /rw
    location /rw/ {
        # Remove /rw prefix when forwarding to app
        rewrite ^/rw/(.*) /$1 break;
        
        # Proxy to FastAPI application
        proxy_pass http://localhost:8000/;
        proxy_http_version 1.1;
        
        # Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        
        # WebSocket support (if needed in future)
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts for long-polling requests
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # Static files served directly by Nginx (better performance)
    location /rw/static/ {
        alias /opt/torn_rw/static/;
        expires 1d;
        add_header Cache-Control "public, immutable";
    }
}
```

### Enable Site

```bash
# Create symbolic link to enable site
sudo ln -s /etc/nginx/sites-available/deadfragment.com /etc/nginx/sites-enabled/

# Remove default site if exists
sudo rm /etc/nginx/sites-enabled/default

# Test Nginx configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

---

## Part 8: SSL Certificate (HTTPS)

### Install Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
```

### Obtain SSL Certificate

**Important:** Make sure Cloudflare DNS is set to **DNS only (gray cloud)** not proxied!

```bash
sudo certbot --nginx -d deadfragment.com -d www.deadfragment.com
```

Follow the prompts:
1. Enter your email address
2. Agree to terms of service
3. Choose whether to redirect HTTP to HTTPS (recommended: Yes)

Certbot will automatically:
- Obtain certificate from Let's Encrypt
- Update your Nginx config with SSL settings
- Set up auto-renewal

### Verify Auto-Renewal

```bash
# Test renewal (dry run)
sudo certbot renew --dry-run

# Check renewal timer
sudo systemctl status certbot.timer
```

Certificates auto-renew every 60 days.

---

## Part 9: Optional - Enable Cloudflare Proxy

After SSL is working, you can optionally enable Cloudflare's proxy for:
- DDoS protection
- CDN caching
- Analytics

**Steps:**
1. Go to Cloudflare Dashboard > DNS
2. Click on the orange cloud icon next to your A record
3. It should turn from gray (DNS only) to orange (Proxied)

**Note:** If you enable proxy, Cloudflare handles SSL, so you may need to adjust Nginx SSL settings.

---

## Part 10: Verification & Testing

### Test the Application

1. **Check app is running:**
   ```bash
   # Docker
   docker-compose ps
   docker-compose logs -f app
   
   # Native
   sudo systemctl status torn-rw
   journalctl -u torn-rw -f
   ```

2. **Test locally:**
   ```bash
   curl http://localhost:8000/
   ```

3. **Test via Nginx:**
   ```bash
   curl http://localhost/rw/
   ```

4. **Test from browser:**
   - Open `https://deadfragment.com/rw/`
   - Should load the Torn RW Tracker interface

5. **Test API endpoints:**
   ```bash
   # Health check
   curl https://deadfragment.com/rw/api/health
   
   # Should return: {"status":"ok"}
   ```

### Check Logs

```bash
# Nginx access logs
sudo tail -f /var/log/nginx/access.log

# Nginx error logs
sudo tail -f /var/log/nginx/error.log

# Docker logs
docker-compose logs -f

# Native service logs
journalctl -u torn-rw -f
```

---

## Part 11: Maintenance & Updates

### Update Application

**Docker:**
```bash
cd /opt/torn_rw
git pull  # or upload new files
docker-compose down
docker-compose build
docker-compose up -d
```

**Native:**
```bash
cd /opt/torn_rw
git pull  # or upload new files
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart torn-rw
```

### Backup

**Backup Script:**
```bash
sudo nano /opt/backup-torn-rw.sh
```

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/torn-rw"
DATE=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Backup Redis data
if command -v docker &> /dev/null; then
    # Docker
    docker exec torn-rw-redis redis-cli BGSAVE
    sleep 5
    docker cp torn-rw-redis:/data/dump.rdb $BACKUP_DIR/redis_$DATE.rdb
else
    # Native
    redis-cli BGSAVE
    sleep 5
    cp /var/lib/redis/dump.rdb $BACKUP_DIR/redis_$DATE.rdb
fi

# Backup env file
cp /opt/torn_rw/.env $BACKUP_DIR/env_$DATE

# Keep only last 7 days
find $BACKUP_DIR -name "*.rdb" -mtime +7 -delete
find $BACKUP_DIR -name "env_*" -mtime +7 -delete

echo "Backup completed: $DATE"
```

Make executable and schedule:
```bash
sudo chmod +x /opt/backup-torn-rw.sh

# Add to crontab (daily at 3 AM)
sudo crontab -e

# Add line:
0 3 * * * /opt/backup-torn-rw.sh >> /var/log/torn-rw-backup.log 2>&1
```

### Monitor Resources

```bash
# Check CPU/RAM usage
htop

# Check disk space
df -h

# Check Docker resources
docker stats

# Check open connections
sudo netstat -tlnp | grep :8000
```

---

## Part 12: Troubleshooting

### Application Not Starting

```bash
# Check logs
docker-compose logs -f  # Docker
journalctl -u torn-rw -xe  # Native

# Check if port is in use
sudo netstat -tlnp | grep 8000

# Verify .env file
cat /opt/torn_rw/.env
```

### Nginx 502 Bad Gateway

```bash
# Check if app is running
curl http://localhost:8000/

# Check Nginx error logs
sudo tail -f /var/log/nginx/error.log

# Restart services
docker-compose restart  # Docker
sudo systemctl restart torn-rw  # Native
sudo systemctl restart nginx
```

### SSL Certificate Issues

```bash
# Check certificate status
sudo certbot certificates

# Renew manually
sudo certbot renew --force-renewal

# Check Nginx SSL config
sudo nginx -t
```

### Can't Access from Internet

```bash
# Check firewall
sudo ufw status
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Check Nginx is running
sudo systemctl status nginx

# Check DNS
nslookup deadfragment.com

# Check if port is listening
sudo netstat -tlnp | grep :443
```

### High Memory Usage

```bash
# Limit Docker memory (docker-compose.yml)
services:
  app:
    mem_limit: 512m
    
# Or reduce workers
command: uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

---

## Part 13: Security Recommendations

### 1. Enable UFW Firewall

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

### 2. Configure Fail2ban

```bash
sudo apt install -y fail2ban

sudo nano /etc/fail2ban/jail.local
```

```ini
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
bantime = 3600

[nginx-http-auth]
enabled = true
filter = nginx-http-auth
port = http,https
logpath = /var/log/nginx/error.log
```

```bash
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 3. Regular Updates

```bash
# Enable automatic security updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

### 4. Restrict Redis

```bash
# Edit Redis config
sudo nano /etc/redis/redis.conf

# Ensure these settings:
bind 127.0.0.1 ::1
protected-mode yes
```

---

## Part 14: Cost Breakdown

### Hetzner Server Costs

- **CPX11** (2 vCPU, 2GB RAM, 40GB SSD): €4.51/month
- **Traffic**: 20TB included (way more than needed)
- **Backups**: +20% if enabled (€0.90/month)

### Domain & DNS

- **Cloudflare**: Free (DNS, SSL, basic DDoS protection)
- **Domain**: ~€12/year (varies by registrar)

### Total Monthly Cost

- **Server**: €4.51
- **Domain**: ~€1.00 (€12/year)
- **Total**: ~€5.51/month (~$6 USD)

**vs Vercel Pro:** $20/month  
**Savings:** ~$14/month = $168/year

---

## Part 15: Quick Reference Commands

```bash
# Docker Commands
docker-compose up -d              # Start
docker-compose down              # Stop
docker-compose restart           # Restart
docker-compose logs -f app       # View logs
docker-compose ps                # Status

# Native Commands
sudo systemctl start torn-rw     # Start
sudo systemctl stop torn-rw      # Stop
sudo systemctl restart torn-rw   # Restart
sudo systemctl status torn-rw    # Status
journalctl -u torn-rw -f         # View logs

# Nginx Commands
sudo systemctl reload nginx      # Reload config
sudo systemctl restart nginx     # Restart
sudo nginx -t                    # Test config
sudo tail -f /var/log/nginx/error.log  # Error logs

# SSL Commands
sudo certbot certificates        # List certificates
sudo certbot renew              # Renew certificates
sudo certbot renew --dry-run    # Test renewal

# Firewall Commands
sudo ufw status                 # Check status
sudo ufw allow 80/tcp           # Allow HTTP
sudo ufw allow 443/tcp          # Allow HTTPS
```

---

## Success! 🎉

Your Torn RW Tracker should now be running at:
**https://deadfragment.com/rw/**

- ✅ Full control over server
- ✅ No usage limits
- ✅ Professional setup with SSL
- ✅ Auto-restart on failure
- ✅ Cost-effective (~€5.51/month)
- ✅ Scalable (upgrade server size anytime)

Share the URL with your faction and enjoy unlimited tracking!

---

## Appendix: Environment Variables Reference

| Variable               | Required | Default | Description                              |
| ---------------------- | -------- | ------- | ---------------------------------------- |
| `ENEMY_FACTION_IDS`    | ✅ Yes    | -       | Comma-separated faction IDs to track     |
| `FACTION_ID`           | ❌ No     | None    | Restrict access to specific faction      |
| `LEADERSHIP_WHITELIST` | ❌ No     | None    | Player IDs who can view faction overview |
| `DRUG_CD_MAX`          | ❌ No     | 480     | Max drug cooldown in minutes             |
| `MED_CD_MAX`           | ❌ No     | 360     | Max medical cooldown in minutes          |
| `BOOSTER_CD_MAX`       | ❌ No     | 2880    | Max booster cooldown in minutes          |
| `CLAIM_EXPIRY`         | ❌ No     | 120     | Claim expiry time in seconds             |
| `MAX_CLAIMS_PER_USER`  | ❌ No     | 3       | Max simultaneous claims per user         |
| `KV_REST_API_URL`      | ✅ Yes    | -       | Redis connection URL                     |
| `KV_REST_API_TOKEN`    | ❌ No     | -       | Redis token (not needed for local)       |

---

## Support

For issues or questions:
1. Check troubleshooting section above
2. Review logs for error messages
3. Verify all configurations match this guide
4. Check Hetzner/Cloudflare status pages
