# AWS Deployment Guide — Cybernauts Integrated Platform

This document describes how to deploy the **Cybernauts Integrated Platform** (`Cybernauts_Integrated`) to an **AWS EC2 instance** using **Docker**, **Docker Compose**, **Amazon ECR**, and **GitHub Actions CI/CD**.

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
                                      |   1. Lint, Compile & Unit Tests             |
                                      |   2. Build Docker Image (Python 3.11-slim)   |
                                      |   3. Push to Private Amazon ECR             |
                                      |   4. Secure SSH to EC2 via .pem Key         |
                                      +---------------------+-----------------------+
                                                            |
                                      +---------------------+-----------------------+
                                      |                                             |
                                      v                                             v
                      +-------------------------------+             +-------------------------------+
                      |        Amazon ECR Repo        |             |        AWS EC2 Instance       |
                      | <account_id>.dkr.ecr.<region> |             |  IP: <ec2-public-ip>          |
                      |   Tag: <commit-sha> & latest  |             |  Dir: /opt/cybernauts         |
                      +---------------+---------------+             +---------------+---------------+
                                      |                                             |
                                      +------------------- Docker Pull -------------+
                                                            |
                                                            v
                                            +-------------------------------+
                                            |       Docker Compose App      |
                                            |  - Port 8000:8000             |
                                            |  - Non-root user: appuser     |
                                            |  - Health: /health (HTTP 200) |
                                            |  - Persistent: leads.db       |
                                            |  - Persistent: recordings/    |
                                            +-------------------------------+
```

---

## 2. Prerequisites

1. **AWS Account**:
   - Access to create an **EC2 instance** (e.g., `t3.medium` or `c6i.large` recommended for real-time WebRTC audio pipelines).
   - Access to create an **Amazon ECR** private repository.
   - An **IAM user** or **role** with permissions to push to ECR.
2. **SSH Key Pair**:
   - Existing key named `cybernautsServices.pem`.
3. **Domain / DNS / Carrier**:
   - Public IP or Domain for Plivo / Twilio webhooks, WebSockets, and LiveKit WebRTC.
4. **GitHub Repository**:
   - Admin access to configure **GitHub Actions Secrets and Variables**.

---

## 3. Required GitHub Repository Secrets & Variables

Navigate to **GitHub Repository** -> **Settings** -> **Secrets and variables** -> **Actions**.

### Secrets (Confidential)

| Secret Name | Description | Example / Format |
| :--- | :--- | :--- |
| `AWS_ACCESS_KEY_ID` | IAM User access key with ECR permissions | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | IAM User secret access key | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` |
| `AWS_REGION` | AWS Region where ECR and EC2 reside | `us-east-1` (or your chosen region) |
| `ECR_REPOSITORY_NAME` | Name of your Amazon ECR repository | `cybernauts-integrated` |
| `EC2_HOST` | Public IP address or Elastic IP of EC2 | `54.x.x.x` or `ec2-54-x-x-x.compute-1.amazonaws.com` |
| `EC2_USER` | SSH user for your EC2 AMI | `ubuntu` (for Ubuntu) or `ec2-user` |
| `EC2_SSH_KEY` | Full content of `cybernautsServices.pem` | `-----BEGIN RSA PRIVATE KEY----- ... -----END RSA PRIVATE KEY-----` |

> [!CAUTION]
> **Never commit `cybernautsServices.pem` or `.env` to Git.** Store `cybernautsServices.pem` strictly inside GitHub Secrets as `EC2_SSH_KEY` and on your local administrator workstation.

### Variables (Non-Sensitive)

| Variable Name | Description | Default |
| :--- | :--- | :--- |
| `APP_DIR` | Working directory path on EC2 | `/opt/cybernauts` |

---

## 4. AWS Infrastructure Setup

### Step 4.1: Create Amazon ECR Repository

Using AWS CLI or Console:
```bash
aws ecr create-repository \
  --repository-name cybernauts-integrated \
  --image-scanning-configuration scanOnPush=true \
  --region <aws-region>
```

### Step 4.2: Launch EC2 Instance

1. **AMI**: Ubuntu Server 22.04 LTS or 24.04 LTS (64-bit x86_64).
2. **Instance Type**: Minimum `t3.small` (2 vCPU, 2GB RAM); recommended `t3.medium` or `t3.large` for real-time speech synthesis + scraping.
3. **Key Pair**: Select `cybernautsServices`.
4. **Storage**: At least 30 GB gp3 SSD.
5. **Security Group Rules**:
   - **Port 22 (SSH)**: Source `My IP` or GitHub Actions IP range (or `0.0.0.0/0` if protected by key authentication).
   - **Port 8000 (HTTP/App)**: Source `0.0.0.0/0` (or restricted behind an Application Load Balancer / Nginx reverse proxy).
   - **Port 80 / 443**: Source `0.0.0.0/0` (if using Let's Encrypt / Nginx).

### Step 4.3: IAM Policy for GitHub Actions (Least-Privilege)

Attach the following policy to the IAM user used by GitHub Actions (`AWS_ACCESS_KEY_ID`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRAuth",
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*"
    },
    {
      "Sid": "ECRRepositoryAccess",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload"
      ],
      "Resource": "arn:aws:ecr:<aws-region>:<aws-account-id>:repository/cybernauts-integrated"
    }
  ]
}
```

---

## 5. Initial Server Setup (One-Time EC2 Configuration)

Connect to your EC2 instance via SSH:
```bash
chmod 400 cybernautsServices.pem
ssh -i cybernautsServices.pem ubuntu@<ec2-public-ip>
```

Run the following initialization commands on EC2:

```bash
# 1. Update OS packages
sudo apt-get update && sudo apt-get upgrade -y

# 2. Install Docker, Docker Compose, AWS CLI, and Git
sudo apt-get install -y ca-certificates curl gnupg lsb-release git awscli

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# 3. Add ubuntu user to docker group (run docker without sudo)
sudo usermod -aG docker $USER
newgrp docker

# 4. Create application directory with proper permissions
sudo mkdir -p /opt/cybernauts
sudo chown -R $USER:$USER /opt/cybernauts

# 5. Clone repository into /opt/cybernauts
cd /opt/cybernauts
git clone https://github.com/<your-org-or-user>/Cybernauts_Integrated.git .

# 6. Make deployment script executable
chmod +x scripts/deploy.sh
```

---

## 6. Configuring Server-Side Environment Variables

Create the production `.env` file directly on the EC2 server inside `/opt/cybernauts/.env`:

```bash
cd /opt/cybernauts
nano .env
```

Set permissions to restrict read access:
```bash
chmod 600 .env
```

Ensure the following production values are populated:

```ini
# ---------- Server Settings ----------
HOST=0.0.0.0
PORT=8000
ENVIRONMENT=production
LOG_LEVEL=INFO

# ---------- Telephony & Public Webhooks ----------
# Set to your EC2 public domain, ALB URL, or tunnel domain
PUBLIC_BASE_URL=https://<your-ec2-domain-or-alb>
SERVER_BASE_URL=https://<your-ec2-domain-or-alb>
TRANSPORT_MODE=livekit

# ---------- LiveKit Cloud WebRTC ----------
LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=<livekit-api-key>
LIVEKIT_API_SECRET=<livekit-api-secret>
LIVEKIT_ROOM_NAME=default-voice-room

# ---------- AI Voice & Speech Services ----------
SARVAM_API_KEY=<your-sarvam-key>
SARVAM_TTS_VOICE=shreya
SARVAM_TTS_MODEL=bulbul:v3

GROQ_API_KEY=<your-groq-key>
GROQ_WHISPER_MODEL=whisper-large-v3-turbo

DEEPGRAM_API_KEY=<your-deepgram-key>

OPENAI_API_KEY=<your-openai-key>
OPENAI_MODEL=gpt-4o-mini

# ---------- Telecom Carriers (Plivo / Twilio) ----------
PLIVO_AUTH_ID=<plivo-auth-id>
PLIVO_AUTH_TOKEN=<plivo-auth-token>
PLIVO_PHONE_NUMBER=<plivo-phone-number>

# ---------- Persistence Databases ----------
DATABASE_URL=postgresql+asyncpg://<user>:<password>@<host>/<database>?ssl=require
```

---

## 7. First Manual Deployment Walkthrough

To verify everything on EC2 before relying on CI/CD:

```bash
cd /opt/cybernauts

# 1. Log in to Amazon ECR (replace <aws-region> and <account-id>)
aws ecr get-login-password --region <aws-region> | docker login --username AWS --password-stdin <account-id>.dkr.ecr.<aws-region>.amazonaws.com

# 2. Or build locally on the instance for initial testing:
docker compose build

# 3. Execute the deployment script:
./scripts/deploy.sh cybernauts-app:latest

# 4. Verify the container is running and healthy:
docker compose ps
curl http://localhost:8000/health
# Expected Output: {"status":"ok"}
```

---

## 8. How Automated CI/CD Deployments Work

Once GitHub secrets are configured:

1. **Trigger**: Developer pushes code to `main` branch.
2. **Quality Stage**: GitHub Actions checks out code, runs Python bytecode compilation, and runs persona & context test suites.
3. **Build Stage**: Builds production Docker image using `Dockerfile`, tags with commit SHA + `latest`, and pushes to Amazon ECR.
4. **Deploy Stage**: Actions connects to EC2 via SSH using `cybernautsServices.pem` (from `EC2_SSH_KEY`).
5. **Execution**: EC2 executes `scripts/deploy.sh <ecr-image-uri>`:
   - Pulls the exact commit image.
   - Preserves previous container image ID for rollback.
   - Spins up new container via `docker compose`.
   - Polls `/health` endpoint for up to 60 seconds.
   - If healthy: completes successfully.
   - If failing: automatically rolls back to previous working container.

---

## 9. Monitoring, Logs & Troubleshooting

### Check Container Status
```bash
docker compose ps
```

### View Live Real-Time Logs
```bash
docker compose logs -f app
```

### Check Application Health
```bash
curl -i http://localhost:8000/health
# HTTP/1.1 200 OK
# {"status":"ok"}
```

### Common Issues & Resolutions

| Issue | Symptom | Resolution |
| :--- | :--- | :--- |
| **SSH Connection Timeout** | GitHub Actions fails on `ssh: connect to host ... port 22: Connection timed out` | Check EC2 Security Group inbound rule for port 22. Ensure Elastic IP / public IP is accessible. |
| **ECR Login Denied** | `no basic auth credentials` | Verify `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` have `ecr:GetAuthorizationToken` permission. |
| **Health Check Timeout** | `HEALTH CHECK FAILED! Target image did not respond within timeout` | Check `docker compose logs app`. Verify `.env` database and API keys are properly configured. |
| **Leads Database Permission Error** | `sqlite3.OperationalError: unable to open database file` | Ensure `chmod 666 leads.db` was run so non-root `appuser` (UID 1000) can write to SQLite. |
| **Missing Static Audio** | Greetings fail to play | Verify `static/audio/greetings/` files exist in repository. Do not add `static/audio` to `.dockerignore`. |

---

## 10. Manual Rollback Procedures

If an unexpected production bug occurs, roll back instantly:

```bash
cd /opt/cybernauts

# 1. View recent images
docker images

# 2. Run deploy script with previous specific image tag
./scripts/deploy.sh <account-id>.dkr.ecr.<aws-region>.amazonaws.com/cybernauts-integrated:<previous-commit-sha>
```

---

## 11. Security & Credential Rotation Guidelines

1. **If SSH Key is compromised**:
   - Generate a new key pair in AWS Console -> EC2 -> Key Pairs (`cybernautsServices-v2`).
   - Append public key to `~/.ssh/authorized_keys` on EC2, remove the old key.
   - Update `EC2_SSH_KEY` in GitHub Repository Secrets.
   - Delete the old key pair in AWS Console.
2. **If AWS Access Key is compromised**:
   - Create a new Access Key in IAM Console for the CI/CD user.
   - Update `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in GitHub Secrets.
   - Deactivate and delete the old Access Key in IAM.
3. **Database & API Keys**:
   - Keep all third-party API keys (Sarvam, Groq, Deepgram, Plivo) strictly inside server-side `/opt/cybernauts/.env`. Never commit them to Git.
