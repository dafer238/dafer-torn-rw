# WSL Local Testing Guide

Complete guide to test the Torn RW Tracker locally in WSL (Windows Subsystem for Linux) before deploying to Hetzner.

This guide replicates the production setup on your local machine so you can verify everything works correctly.

---

## Prerequisites

- Windows 10/11 with WSL2 installed
- Basic terminal knowledge

---

## Part 1: WSL Setup

### Step 1: Install/Update WSL

Open PowerShell as Administrator:

```powershell
# Install WSL2 with Ubuntu (if not already installed)
wsl --install -d Ubuntu-24.04

# Or update existing WSL
wsl --update

# Set WSL2 as default
wsl --set-default-version 2
```

### Step 2: Start Ubuntu

```powershell
# Launch Ubuntu
wsl
```

You're now in the Ubuntu terminal!

### Step 3: Update System

```bash
sudo apt update && sudo apt upgrade -y
```

---

## Part 2: Choose Your Testing Method

You have two options - choose one:

### Option A: Docker (Recommended - Faster Setup)

Pros:
- ✅ Matches production closely
- ✅ Easier to clean up
- ✅ Isolated environment

### Option B: Native (Closer to Manual Hetzner Setup)

Pros:
- ✅ Tests actual systemd service
- ✅ Matches native Hetzner setup exactly
- ✅ Better for troubleshooting

**For first-time testing, use Docker (Option A).**

---

## Part 3A: Docker Setup

### Install Docker

```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install -y docker-compose

# Apply group changes (or restart WSL)
newgrp docker

# Verify installation
docker --version
docker-compose --version
```

### Copy Application Files to WSL

From PowerShell (Windows side):

```powershell
# Copy entire project to WSL
wsl -e mkdir -p /home/$env:USERNAME/torn_rw
Copy-Item -Path "C:\Users\dafer\code\python\torn_rw\*" -Destination "\\wsl$\Ubuntu-24.04\home\$env:USERNAME\torn_rw\" -Recurse
```

Or from within WSL:

```bash
# Create directory
mkdir -p ~/torn_rw

# Copy from Windows to WSL
cp -r /mnt/c/Users/dafer/code/python/torn_rw/* ~/torn_rw/
```

### Configure Environment

```bash
cd ~/torn_rw
nano .env
```

Add your test configuration:

```bash
# Required: Enemy Faction IDs (use real IDs for testing)
ENEMY_FACTION_IDS=12345,67890

# Optional: Your Faction ID
FACTION_ID=11111

# Leadership Whitelist
LEADERSHIP_WHITELIST=123456,789012

# Faction CD times (adjust to your faction)
DRUG_CD_MAX=480
MED_CD_MAX=360
BOOSTER_CD_MAX=2880

# Claim settings
CLAIM_EXPIRY=120
MAX_CLAIMS_PER_USER=3

# Redis (Docker internal)
KV_REST_API_URL=redis://redis:6379
KV_REST_API_TOKEN=not-needed
```

### Update main.py for /rw Path

Make sure `main.py` has `root_path="/rw"`:

```bash
nano ~/torn_rw/main.py
```

Find the FastAPI initialization and ensure:

```python
app = FastAPI(
    title="Torn Ranked War Tracker",
    description="Real-time situational awareness for Torn ranked wars",
    version="1.0.0",
    lifespan=lifespan,
    root_path="/rw",  # Important for subdirectory
)
```

### Start Docker Containers

```bash
cd ~/torn_rw

# Build and start
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f
```

### Test Application Directly

```bash
# Test on localhost:8000
curl http://localhost:8000/

# Should return HTML content
```

---

## Part 3B: Native Setup (Alternative)

### Install Dependencies

```bash
# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip

# Install Redis
sudo apt install -y redis-server

# Start Redis
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Verify Redis
redis-cli ping  # Should return "PONG"
```

### Setup Application

```bash
# Copy files (if not already done)
mkdir -p ~/torn_rw
cp -r /mnt/c/Users/dafer/code/python/torn_rw/* ~/torn_rw/

cd ~/torn_rw

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configure Environment

```bash
nano ~/torn_rw/.env
```

```bash
# Same as Docker setup above, but:
KV_REST_API_URL=redis://localhost:6379
KV_REST_API_TOKEN=not-needed
```

### Update main.py

Ensure `root_path="/rw"` as shown in Docker section.

### Create Test Service (Optional)

```bash
sudo nano /etc/systemd/system/torn-rw.service
```

```ini
[Unit]
Description=Torn RW Tracker
After=network.target redis-server.service

[Service]
Type=simple
User=$USER
WorkingDirectory=/home/$USER/torn_rw
Environment="PATH=/home/$USER/torn_rw/venv/bin"
EnvironmentFile=/home/$USER/torn_rw/.env
ExecStart=/home/$USER/torn_rw/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Replace `$USER` with your actual username.

```bash
sudo systemctl daemon-reload
sudo systemctl enable torn-rw
sudo systemctl start torn-rw
sudo systemctl status torn-rw
```

Or run manually for testing:

```bash
cd ~/torn_rw
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## Part 4: Install and Configure Nginx

### Install Nginx

```bash
sudo apt install -y nginx
```

### Create Nginx Configuration

```bash
sudo nano /etc/nginx/sites-available/torn-rw-test
```

Add this configuration:

```nginx
# Test configuration for local development
server {
    listen 80;
    server_name localhost;
    
    # Root path - can serve test page
    location / {
        return 200 "Nginx is working! Go to /rw for the tracker.";
        add_header Content-Type text/plain;
    }
    
    # Torn RW Tracker at /rw (matches production)
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
        
        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
    
    # Static files (optional - Nginx can serve directly)
    location /rw/static/ {
        alias /home/$USER/torn_rw/static/;
        expires 1d;
        add_header Cache-Control "public";
    }
}
```

**Important:** Replace `$USER` with your actual username (e.g., `dafer`).

### Enable Configuration

```bash
# Create symbolic link
sudo ln -s /etc/nginx/sites-available/torn-rw-test /etc/nginx/sites-enabled/

# Remove default site
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# If test is OK, reload Nginx
sudo systemctl reload nginx

# Check Nginx status
sudo systemctl status nginx
```

---

## Part 5: Testing

### Get Your WSL IP Address

```bash
# Get WSL IP
ip addr show eth0 | grep "inet\b" | awk '{print $2}' | cut -d/ -f1

# Example output: 172.18.240.50
```

### Test from WSL Terminal

```bash
# Test Nginx is working
curl http://localhost/

# Test direct app access
curl http://localhost:8000/

# Test app through Nginx (production-like)
curl http://localhost/rw/

# Test API health endpoint
curl http://localhost/rw/api/health
```

All should return content!

### Test from Windows Browser

Open your browser and go to:

**Option 1: Using localhost (easiest)**
```
http://localhost/rw/
```

**Option 2: Using WSL IP (if localhost doesn't work)**
```
http://172.18.240.50/rw/
```
(Replace with your actual WSL IP)

**Direct app access (bypassing Nginx):**
```
http://localhost:8000/
```

### What You Should See

1. **http://localhost/rw/** - The Torn RW Tracker interface
2. **http://localhost/rw/api/health** - `{"status":"ok"}`
3. **http://localhost/** - "Nginx is working!" message

---

## Part 6: Test All Features

### 1. Basic Functionality

- Enter your Torn API key
- Enter your player ID and name
- Click "Save Configuration"
- Check that targets load

### 2. Test Claiming

- Click "Claim" on a target
- Verify it shows as claimed
- Test unclaiming

### 3. Test Faction Overview (if whitelisted)

- Toggle to "Faction" view
- Check that faction members appear
- Test table sorting
- Verify cooldown bars display

### 4. Test on Mobile View

In browser:
- Press F12 (Developer Tools)
- Click device toggle icon (or Ctrl+Shift+M)
- Select phone view (iPhone, Android)
- Verify responsive layout works

---

## Part 7: View Logs

### Docker Logs

```bash
# All logs
docker-compose logs -f

# App only
docker-compose logs -f app

# Redis only
docker-compose logs -f redis

# Last 50 lines
docker-compose logs --tail=50
```

### Native Logs

```bash
# If using systemd service
journalctl -u torn-rw -f

# Or check console output if running manually
```

### Nginx Logs

```bash
# Access log (requests)
sudo tail -f /var/log/nginx/access.log

# Error log
sudo tail -f /var/log/nginx/error.log
```

---

## Part 8: Testing Checklist

- [ ] Docker/Native setup completed
- [ ] Nginx installed and configured
- [ ] App accessible at http://localhost:8000/
- [ ] App accessible at http://localhost/rw/ (through Nginx)
- [ ] Static files loading correctly
- [ ] API key validation works
- [ ] Targets loading from Torn API
- [ ] Claim/unclaim functionality works
- [ ] Faction overview displays (if whitelisted)
- [ ] Mobile responsive layout looks good
- [ ] No errors in browser console (F12)
- [ ] No errors in application logs
- [ ] No errors in Nginx logs

---

## Part 9: Troubleshooting

### Can't Access from Windows Browser

**Issue:** "This site can't be reached"

**Solutions:**

```bash
# 1. Check if ports are accessible from Windows
# In WSL:
ip addr show eth0 | grep "inet\b"

# 2. Try using the WSL IP directly in browser
# http://172.x.x.x/rw/

# 3. Check Windows Firewall isn't blocking
# In PowerShell (Admin):
New-NetFirewallRule -DisplayName "WSL Nginx" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow

# 4. Try port forwarding (if needed)
# In PowerShell (Admin):
netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=80 connectaddress=$(wsl hostname -I)
```

### Nginx 502 Bad Gateway

```bash
# Check if app is running
curl http://localhost:8000/

# If Docker:
docker-compose ps
docker-compose logs app

# If Native:
sudo systemctl status torn-rw
journalctl -u torn-rw -xe

# Check Nginx error logs
sudo tail -f /var/log/nginx/error.log
```

### Port Already in Use

```bash
# Check what's using port 8000
sudo netstat -tlnp | grep 8000

# Kill the process or change port
# In docker-compose.yml or uvicorn command
```

### Redis Connection Issues

```bash
# Test Redis
redis-cli ping

# Check if running
sudo systemctl status redis-server

# Docker: check container
docker-compose ps
docker-compose exec redis redis-cli ping
```

### Static Files Not Loading

```bash
# Check path in Nginx config
sudo nano /etc/nginx/sites-available/torn-rw-test

# Ensure path matches your username
# /home/YOUR_USERNAME/torn_rw/static/

# Reload Nginx
sudo systemctl reload nginx
```

### App Returns 404 for /rw

**Issue:** Going to http://localhost/rw/ returns 404

**Solution:** Ensure `main.py` has `root_path="/rw"`:

```python
app = FastAPI(
    root_path="/rw",  # This line is required!
    # ... other settings
)
```

Then restart:

```bash
# Docker
docker-compose restart

# Native
sudo systemctl restart torn-rw
```

---

## Part 10: Cleanup When Done Testing

### Stop Services

**Docker:**
```bash
cd ~/torn_rw
docker-compose down

# Remove all data (optional)
docker-compose down -v
```

**Native:**
```bash
# Stop service
sudo systemctl stop torn-rw

# Disable autostart
sudo systemctl disable torn-rw

# Or kill manual process: Ctrl+C
```

### Stop Nginx

```bash
sudo systemctl stop nginx

# Or disable
sudo systemctl disable nginx
```

### Remove Port Forwarding (if added)

In PowerShell (Admin):
```powershell
netsh interface portproxy delete v4tov4 listenport=80 listenaddress=0.0.0.0
```

---

## Part 11: Differences from Production

When you deploy to Hetzner, these will be different:

| Aspect | WSL Testing | Hetzner Production |
|--------|-------------|-------------------|
| Domain | localhost | deadfragment.com |
| SSL | No (HTTP) | Yes (HTTPS with Let's Encrypt) |
| Access | Local only | Internet accessible |
| Port | 80 (localhost) | 80→443 (redirect to HTTPS) |
| Firewall | Windows Firewall | UFW + Hetzner Firewall |
| DNS | None | Cloudflare A record |
| Auto-start | Manual | Systemd auto-start |
| Backups | None | Cron scheduled |

**Everything else is identical!** The Nginx config, app setup, and functionality are the same.

---

## Part 12: Next Steps

Once everything works in WSL:

1. ✅ You've verified the setup works
2. ✅ You've tested all features
3. ✅ You've confirmed Nginx proxying works
4. ✅ You've validated the /rw path configuration

**You're ready to deploy to Hetzner!**

Follow the **HETZNER_SETUP.md** guide, which will be almost identical to what you just did, but with:
- Real domain pointing to server
- SSL certificate setup
- Production security hardening
- Cloudflare integration

---

## Part 13: Quick Reference Commands

```bash
# Docker
docker-compose up -d              # Start
docker-compose down              # Stop
docker-compose restart           # Restart
docker-compose logs -f           # View logs
docker-compose ps                # Status

# Nginx
sudo systemctl start nginx       # Start
sudo systemctl stop nginx        # Stop
sudo systemctl restart nginx     # Restart
sudo systemctl reload nginx      # Reload config
sudo nginx -t                    # Test config

# Native Service
sudo systemctl start torn-rw     # Start
sudo systemctl stop torn-rw      # Stop
sudo systemctl restart torn-rw   # Restart
journalctl -u torn-rw -f         # View logs

# Redis
redis-cli ping                   # Test connection
sudo systemctl status redis-server  # Check status

# Get WSL IP
ip addr show eth0 | grep "inet\b" | awk '{print $2}' | cut -d/ -f1

# Check listening ports
sudo netstat -tlnp
```

---

## Success! 🎉

If everything works in WSL, you can be confident it will work on Hetzner!

You've now tested:
- ✅ Application running
- ✅ Nginx proxy at /rw path
- ✅ All API endpoints
- ✅ Frontend functionality
- ✅ Mobile responsive design
- ✅ Production-like configuration

**Ready to deploy to production!** Follow HETZNER_SETUP.md next.
