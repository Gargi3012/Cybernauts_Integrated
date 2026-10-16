# AWS Deployment Guide — Cybernauts Integrated Platform

This document describes how to deploy the **Cybernauts Integrated Platform** (`Cybernauts_Integrated`) directly to an existing **AWS EC2 instance** using **GitHub Actions CI/CD over SSH/SCP** and **Linux systemd**, **WITHOUT requiring AWS IAM Access Keys, AWS Secret Access Keys, Amazon ECR, or Docker image builds in GitHub Actions**.

---

## 1. Architecture & Deployment Overview

```
                                  +---------------------------------------------+
                                  |             GitHub Repository               |
                                  |   - Push to `main` or `workflow_dispatch`   |
                                  +---------------------+-----------------------+
                                                        |
                                                        v
                                  +---------------------------------------------+
                                  |             GitHub Actions CI/CD            |
                                  |   1. Lint, Compile & Unit Tests (Python 3.11)|
                                  |   2. Package clean bundle (excludes secrets,|
                                  |      local DB, 10MB logs, and temp caches)  |
                                  |   3. Pinned Host-Key Verification (Strict)  |
                                  |   4. Secure SCP tarball + Pre-extraction    |
                                  |   5. Isolated systemd script execution      |
                                  |   6. Automatic cleanup of temporary key     |
                                  +---------------------+-----------------------+
                                                        |
                                                        v  (SSH / SCP)
                                  +---------------------------------------------+
                                  |             AWS EC2 Instance                |
                                  | Host: ec2-43-204-8-94.ap-south-1...         |
                                  | User: ec2-user                              |
                                  | Root Dir: /home/ec2-user/apps/              |
                                  |           cybernauts-integrated/            |
                                  +---------------------+-----------------------+
                                                        |
                        +-------------------------------+-------------------------------+
                        |                               |                               |
                        v                               v                               v
         +-----------------------------+ +-----------------------------+ +-----------------------------+
         |   [EXISTING] Voice-Pipeline | |     [EXISTING] Flowiz       | |  [NEW] Cybernauts-Integrated|
         | - Docker container          | | - /var/www/flowiz           | | - /home/ec2-user/apps/      |
         | - Port 8000                 | | - flowiz.service            | |   cybernauts-integrated     |
         | - Apache /voice proxy       | | - Port 8008                 | | - cybernauts-integrated.    |
         | - (UNTOUCHED & PRESERVED)   | | - (UNTOUCHED & PRESERVED)   | |   service                   |
         +-----------------------------+ +-----------------------------+ | - Dedicated venv            |
                                                                         | - Port 8010                 |
                                                                         | - Health: /health (HTTP 200)|
                                                                         | - Persistent: leads.db      |
                                                                         +-----------------------------+
```

---

## 2. Why Direct SSH/systemd Deployment?

- **No AWS API Credentials Needed**: The deployment uses standard SSH authentication with your existing key (`cybernautsServices.pem`). You do **not** need `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, or IAM console access.
- **No Amazon ECR or Docker Overhead**: GitHub Actions does not build or push heavy Docker images, saving bandwidth, runner time, and repository costs.
- **Zero Impact on Existing Applications**:
  - The `voice-pipeline` container on port **8000** is completely isolated and never touched.
  - The `flowiz.service` on port **8008** is completely isolated and never touched.
  - Existing Apache websites and MariaDB databases are untouched.
- **Isolated Target Directory**: All files, dedicated virtual environment, logs, and databases reside in `/home/ec2-user/apps/cybernauts-integrated`.

---

## 3. Required GitHub Repository Secrets

Configure the following secrets in **GitHub Repository** -> **Settings** -> **Secrets and variables** -> **Actions**:

| Secret Name | Required? | Description | Example / Notes |
| :--- | :--- | :--- | :--- |
| `EC2_HOST` | **Yes** | Hostname or Public IP of the EC2 instance | `ec2-43-204-8-94.ap-south-1.compute.amazonaws.com` |
| `EC2_SSH_KEY` | **Yes** | Full contents of your private key file (`cybernautsServices.pem`) | Include both `-----BEGIN RSA PRIVATE KEY-----` and `-----END RSA PRIVATE KEY-----` |
| `EC2_HOST_KEY` | **Yes** | Independently verified public host key | See Section 3.1 below |
| `EC2_USERNAME` | No (Optional) | SSH user for the EC2 instance | `ec2-user` (Defaults to `ec2-user` if omitted) |

> [!CAUTION]
> **Never commit your private key (`cybernautsServices.pem`) to Git or share it in chats.** It is stored exclusively in GitHub Secrets as `EC2_SSH_KEY`.

### 3.1 Independently Verified Host Key (`EC2_HOST_KEY`)

To strictly protect against Man-In-The-Middle (MITM) attacks, the CI/CD pipeline does **not** rely on dynamic or unverified network scans. You must obtain the server's public key from a trusted, authenticated channel:

**Trusted Channel Option A — Via Authenticated Shell on the EC2 Server**:
Log in via Windows CMD using your existing key and read the local server public key:
```bash
cat /etc/ssh/ssh_host_ed25519_key.pub
```
This outputs: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBnZCTiCtDI0DcRpBU++KUvF1fZv08RcUEbIt5GttwDX`.
Format the secret value as:
```
ec2-43-204-8-94.ap-south-1.compute.amazonaws.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBnZCTiCtDI0DcRpBU++KUvF1fZv08RcUEbIt5GttwDX
```

**Trusted Channel Option B — AWS Console System Log**:
In AWS EC2 Console -> Select Instance -> Actions -> Monitor and Troubleshoot -> Get System Log. Search for the SSH host key fingerprints generated during initial cloud-init provisioning.

---

## 4. EC2 Storage & Dependency Footprint

### Root Filesystem Accounting
- Total Disk: ~10 GB
- Used: ~8.8 GB
- Free: ~1.3 GB (~88% utilization)

### Deployment Footprint Breakdown
1. **Archive Upload & Extraction**: ~3.5 MB tarball, extracts to ~10.5 MB. Tarball is deleted immediately after extraction.
2. **Virtual Environment Base**: ~20 MB.
3. **Pip Wheel Downloads & Installation**:
   - `pip install --no-cache-dir` is strictly used to prevent keeping ~400 MB of wheel archives.
   - Transient wheel downloads reside in an isolated temporary directory (`${APP_DIR}/tmp`), avoiding `/tmp` partition exhaustion.
   - Peak temporary space during extraction: ~120–160 MB.
   - Installed `site-packages`: ~450–550 MB.
   - Total peak installation requirement: ~700 MB.
4. **Safety Buffer**: ~300 MB reserved for Flowiz logs, systemd journals, and MariaDB.
5. **Initial Free Space Threshold**: The deployment script enforces `MIN_INITIAL_FREE_MB=1000` (1.0 GB). If free space is below 1,000 MB, the deployment **aborts immediately before making any changes**, guaranteeing existing applications remain unaffected.
6. **No Dangerous Cleanup Commands**: Never run `docker system prune`, `rsync --delete`, or broad `rm -rf` on EC2.

---

## 5. Port Allocation & Health Check Verification

| Port | Allocation | Status |
| :--- | :--- | :--- |
| **8000** | Voice-pipeline (Docker) | **Reserved — DO NOT USE** |
| **8008** | Flowiz (systemd / Uvicorn) | **Reserved — DO NOT USE** |
| **8010** | **Cybernauts Integrated Platform** | **Dedicated Production Port** |

### Health Check Behavior (`/health`)
- Local URL on EC2: `http://127.0.0.1:8010/health`
- **Lifespan State Tracking**:
  - Returns **HTTP 503** while the server is booting or if mandatory SQLite databases fail to initialize.
  - Returns **HTTP 200** once core services are initialized:
    ```json
    {
      "status": "ok",
      "app": "cybernauts-integrated",
      "version": "2.0.0",
      "ready": true,
      "team_a_db": true,
      "recordings_db": true,
      "team_b_db": false,
      "team_b_db_required": false
    }
    ```
- **Team B PostgreSQL Policy (`team_b_db`)**:
  - By default, Team B PostgreSQL operates in **graceful degradation** mode (`REQUIRE_TEAM_B_DB=false`) because core lead discovery, browser testing, and SQLite recordings function without it.
  - If a dedicated PostgreSQL cluster is configured and required, set `REQUIRE_TEAM_B_DB=true` in `.env`. The `/health` endpoint will then return **HTTP 503** until PostgreSQL connectivity is established.

---

## 6. Manual EC2 Setup (One-Time Only)

Before running the GitHub Actions workflow, perform this one-time step:

### Step 6.1: Connect via SSH from Windows CMD
```cmd
ssh -i "C:\Users\hp\Downloads\cybernautsServices.pem" ec2-user@ec2-43-204-8-94.ap-south-1.compute.amazonaws.com
```

### Step 6.2: Create Application Directory & Production `.env`
```bash
mkdir -p /home/ec2-user/apps/cybernauts-integrated
cd /home/ec2-user/apps/cybernauts-integrated
```

Create `/home/ec2-user/apps/cybernauts-integrated/.env`:
```bash
cat << 'EOF' > .env
PORT=8010
HOST=0.0.0.0
ENVIRONMENT=production
PUBLIC_BASE_URL=https://your-domain-or-proxy.com
SERVER_BASE_URL=https://your-domain-or-proxy.com
TRANSPORT_MODE=plivo
PLIVO_AUTH_ID=your_real_plivo_auth_id
PLIVO_AUTH_TOKEN=your_real_plivo_auth_token
PLIVO_PHONE_NUMBER=your_real_plivo_number
DEEPGRAM_API_KEY=your_real_deepgram_key
OPENAI_API_KEY=your_real_openai_key
CARTESIA_API_KEY=your_real_cartesia_key
JWT_SECRET_KEY=generate_a_secure_random_32_character_key_here
REQUIRE_TEAM_B_DB=false
EOF
chmod 600 .env
```

---

## 7. Operating & Monitoring the Service

The application runs as a standard Linux systemd service: `cybernauts-integrated.service`.

- **Check Status**: `sudo systemctl status cybernauts-integrated.service`
- **Tail Live Logs**: `sudo journalctl -u cybernauts-integrated.service -f`
- **Recent 50 Lines**: `sudo journalctl -u cybernauts-integrated.service -n 50 --no-pager`
- **Restart Service**: `sudo systemctl restart cybernauts-integrated.service`
- **Verify Health**: `curl -i http://127.0.0.1:8010/health`

---

## 8. Local Development (Docker & Compose)

The repository retains `Dockerfile` and `docker-compose.yml` for local development.

To run locally with Docker:
```bash
docker compose up --build
```
This runs the container locally on `http://localhost:8000` without impacting remote EC2 deployment.
