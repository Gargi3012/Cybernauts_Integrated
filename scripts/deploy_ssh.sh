#!/usr/bin/env bash
# ==============================================================================
# scripts/deploy_ssh.sh — Direct SSH Deployment for Cybernauts Integrated Platform
# Executed remotely on AWS EC2 by GitHub Actions or an authorized operator.
# ==============================================================================
set -euo pipefail

# Output styling
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

APP_DIR="${APP_DIR:-/home/ec2-user/apps/cybernauts-integrated}"
APP_PORT="${APP_PORT:-8010}"
SERVICE_NAME="cybernauts-integrated.service"
HEALTH_CHECK_URL="http://127.0.0.1:${APP_PORT}/health"
# Minimum required initial free disk space: 1,000 MB (1.0 GB)
# Accounting for: ~10 MB code extraction, ~20 MB base venv, ~450-550 MB site-packages,
# ~120-160 MB peak wheel downloads in isolated TMPDIR, plus a 300 MB safety buffer for existing apps.
MIN_INITIAL_FREE_MB=1000
MIN_POST_INSTALL_FREE_MB=300

# Cleanup trap for isolated temp directory
cleanup() {
  if [ -d "${APP_DIR}/tmp" ]; then
    rm -rf "${APP_DIR}/tmp"
  fi
}
trap cleanup EXIT

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}  Cybernauts Integrated — Direct SSH/systemd Production Deployment   ${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo -e "Application Directory : ${APP_DIR}"
echo -e "Target Port           : ${APP_PORT}"
echo -e "Service Unit          : ${SERVICE_NAME}"
echo -e "Timestamp             : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# ── 1. Navigate to isolated deployment directory ─────────────────────────────
mkdir -p "${APP_DIR}"
cd "${APP_DIR}"

# ── 2. Disk Space & Safety Pre-flight Check ──────────────────────────────────
echo -e "${BLUE}[STEP 1/6] Running multi-stage disk space & safety pre-flight checks...${NC}"
AVAILABLE_MB=$(df -m / | awk 'NR==2 {print $4}')
echo -e "Root partition available disk space: ${AVAILABLE_MB} MB"

if [ "${AVAILABLE_MB}" -lt "${MIN_INITIAL_FREE_MB}" ]; then
  echo -e "${RED}[FATAL ERROR] Insufficient disk space on EC2 to perform safe deployment!${NC}"
  echo -e "${RED}Available: ${AVAILABLE_MB} MB, Required initial minimum: ${MIN_INITIAL_FREE_MB} MB.${NC}"
  echo -e "${YELLOW}Aborting deployment immediately before any changes. No files or existing services have been touched.${NC}"
  exit 1
fi

# Ensure reserved ports (8000 for voice-pipeline, 8008 for flowiz) are strictly avoided
if [ "${APP_PORT}" = "8000" ] || [ "${APP_PORT}" = "8008" ]; then
  echo -e "${RED}[FATAL ERROR] Target port ${APP_PORT} conflicts with existing critical production services!${NC}"
  echo -e "${YELLOW}Port 8000 belongs to voice-pipeline; Port 8008 belongs to Flowiz.${NC}"
  exit 1
fi

# ── 3. Unpack deployment tarball (if bundle is present) ──────────────────────
if [ -f "deploy_bundle.tar.gz" ]; then
  echo -e "${BLUE}[STEP 2/6] Extracting deployment bundle...${NC}"
  tar -xzf deploy_bundle.tar.gz
  rm -f deploy_bundle.tar.gz
  echo -e "${GREEN}✓ Application code extracted successfully.${NC}"
else
  echo -e "${GREEN}✓ Deployment bundle already extracted.${NC}"
fi

# ── 4. Prepare persistent directories, database, and configuration ───────────
echo -e "${BLUE}[STEP 3/6] Setting up runtime storage and configuration...${NC}"
mkdir -p logs data output cookies static/recordings

# Preserve existing SQLite database — never overwrite or truncate if it exists
if [ ! -f "leads.db" ]; then
  touch leads.db
  echo -e "Initialized new empty leads.db SQLite file."
else
  echo -e "${GREEN}✓ Preserved existing production leads.db SQLite database.${NC}"
fi

# Set restrictive file permissions — strictly avoid chmod 777
chmod 640 leads.db 2>/dev/null || true
chmod 750 logs data output cookies static/recordings 2>/dev/null || true

# Check for production .env file — never overwrite, create placeholders, or copy defaults into production
if [ ! -f ".env" ]; then
  echo -e "${RED}[FATAL ERROR] Production environment file (.env) was not found in ${APP_DIR}!${NC}"
  echo -e "${YELLOW}A server-side .env file with real production secrets (including a 32+ character JWT_SECRET) is required.${NC}"
  echo -e "${YELLOW}Deployment will not copy placeholder credentials or create insecure default configuration in production.${NC}"
  exit 1
fi

# Ensure PORT is configured to our target port in .env without overwriting other variables
if grep -q "^PORT=" .env; then
  sed -i "s/^PORT=.*/PORT=${APP_PORT}/" .env
else
  echo "PORT=${APP_PORT}" >> .env
fi
chmod 600 .env
echo -e "${GREEN}✓ Preserved existing server-side .env configuration (PORT=${APP_PORT}).${NC}"

# Validate server-side JWT_SECRET configuration without ever exposing or printing the secret
echo -e "Validating server-side JWT_SECRET configuration in .env..."
ENV_JWT_SECRET=$(grep -E '^[[:space:]]*JWT_SECRET=' .env 2>/dev/null | tail -n 1 | cut -d '=' -f2- | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^["'"'"']//' -e 's/["'"'"']$//' || true)

if [ -z "${ENV_JWT_SECRET}" ]; then
  echo -e "${RED}[FATAL ERROR] 'JWT_SECRET' is missing or empty in ${APP_DIR}/.env!${NC}"
  echo -e "${YELLOW}A secure secret of at least 32 characters is required before starting or restarting the service.${NC}"
  exit 1
fi

if [ "${ENV_JWT_SECRET}" = "change-this-to-a-secure-random-32-byte-secret-in-production" ] || \
   [ "${ENV_JWT_SECRET}" = "your_jwt_secret_here" ] || \
   [ "${ENV_JWT_SECRET}" = "super-secret-key" ] || \
   [ "${ENV_JWT_SECRET}" = "supersecretflowizkey2026" ] || \
   [ "${ENV_JWT_SECRET}" = "dev-insecure-jwt-secret-key-32bytes-min!!" ]; then
  echo -e "${RED}[FATAL ERROR] 'JWT_SECRET' in ${APP_DIR}/.env is set to an insecure placeholder value!${NC}"
  echo -e "${YELLOW}Replace placeholder credentials with a cryptographically secure random 32+ character secret.${NC}"
  exit 1
fi

JWT_SECRET_LEN=${#ENV_JWT_SECRET}
if [ "${JWT_SECRET_LEN}" -lt 32 ]; then
  echo -e "${RED}[FATAL ERROR] 'JWT_SECRET' in ${APP_DIR}/.env is too short (${JWT_SECRET_LEN} chars; minimum is 32)!${NC}"
  echo -e "${YELLOW}HMAC-SHA256 (RFC 7518 Section 3.2) requires at least 256 bits (32 characters).${NC}"
  exit 1
fi

unset ENV_JWT_SECRET
echo -e "${GREEN}✓ Verified strong JWT_SECRET (${JWT_SECRET_LEN} characters) in server-side .env.${NC}"

# ── 5. Setup Python Virtual Environment & Install Dependencies ───────────────
echo -e "${BLUE}[STEP 4/6] Managing dedicated Python virtual environment...${NC}"

# Detect Python interpreter (prefer python3.11, fallback to python3)
PYTHON_BIN=""
if command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
else
  echo -e "${RED}[ERROR] No python3 executable found on system!${NC}"
  exit 1
fi
echo -e "Using Python interpreter: $($PYTHON_BIN --version)"

VENV_DIR="${APP_DIR}/venv"
if [ ! -d "${VENV_DIR}" ]; then
  echo -e "Creating dedicated Python virtual environment at ${VENV_DIR}..."
  $PYTHON_BIN -m venv "${VENV_DIR}"
fi

# Use an isolated temporary directory within the app directory to prevent filling /tmp
mkdir -p "${APP_DIR}/tmp"
export TMPDIR="${APP_DIR}/tmp"

echo -e "Installing / updating dependencies with --no-cache-dir to conserve disk space..."
"${VENV_DIR}/bin/pip" install --no-cache-dir --upgrade pip setuptools wheel
PROD_REQ_FILE="${APP_DIR}/requirements-prod.txt"
if [ ! -f "${PROD_REQ_FILE}" ]; then
  PROD_REQ_FILE="${APP_DIR}/requirements.txt"
fi
echo -e "Using production requirements: ${PROD_REQ_FILE}"
"${VENV_DIR}/bin/pip" install --no-cache-dir -r "${PROD_REQ_FILE}"

# Clean up isolated pip temporary directory
rm -rf "${APP_DIR}/tmp"

# Post-install disk verification
POST_INSTALL_MB=$(df -m / | awk 'NR==2 {print $4}')
echo -e "Available disk space after dependency installation: ${POST_INSTALL_MB} MB"
if [ "${POST_INSTALL_MB}" -lt "${MIN_POST_INSTALL_FREE_MB}" ]; then
  echo -e "${RED}[FATAL ERROR] Post-installation free disk space dropped below safety buffer (${MIN_POST_INSTALL_FREE_MB} MB)!${NC}"
  echo -e "${YELLOW}Aborting before service activation to avoid destabilizing the server.${NC}"
  exit 1
fi

# Verify compilation of application files
"${VENV_DIR}/bin/python" -m compileall -q server.py recording_manager.py routers

# ── 6. Configure & Restart systemd Service ─────────────────────────────────────
echo -e "${BLUE}[STEP 5/6] Updating and restarting systemd service (${SERVICE_NAME})...${NC}"

SYSTEMD_UNIT_SOURCE="${APP_DIR}/scripts/cybernauts-integrated.service"
SYSTEMD_UNIT_TARGET="/etc/systemd/system/${SERVICE_NAME}"

if [ -f "${SYSTEMD_UNIT_SOURCE}" ]; then
  echo -e "Installing systemd unit file to ${SYSTEMD_UNIT_TARGET}..."
  sudo cp "${SYSTEMD_UNIT_SOURCE}" "${SYSTEMD_UNIT_TARGET}"
  sudo chmod 644 "${SYSTEMD_UNIT_TARGET}"
  sudo systemctl daemon-reload
fi

sudo systemctl enable "${SERVICE_NAME}"
echo -e "Restarting ${SERVICE_NAME}..."
sudo systemctl restart "${SERVICE_NAME}"

# ── 7. Health Check Verification Loop ─────────────────────────────────────────
echo -e "${BLUE}[STEP 6/6] Verifying application readiness & health (${HEALTH_CHECK_URL})...${NC}"
MAX_ATTEMPTS=15
INTERVAL=2
ATTEMPT=1
IS_HEALTHY=false

while [ ${ATTEMPT} -le ${MAX_ATTEMPTS} ]; do
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_CHECK_URL}" || echo "000")
  if [ "${HTTP_STATUS}" = "200" ]; then
    echo -e "${GREEN}✓ Application is healthy! HTTP 200 received on attempt ${ATTEMPT}.${NC}"
    IS_HEALTHY=true
    break
  else
    echo -e "  Attempt ${ATTEMPT}/${MAX_ATTEMPTS}: HTTP status=${HTTP_STATUS}. Waiting ${INTERVAL}s..."
    sleep ${INTERVAL}
    ATTEMPT=$((ATTEMPT + 1))
  fi
done

if [ "${IS_HEALTHY}" = true ]; then
  echo -e "${GREEN}======================================================================${NC}"
  echo -e "${GREEN}  DEPLOYMENT SUCCESSFUL! Service '${SERVICE_NAME}' is active.        ${NC}"
  echo -e "${GREEN}  Listening on http://127.0.0.1:${APP_PORT}                           ${NC}"
  echo -e "${GREEN}======================================================================${NC}"
  exit 0
else
  echo -e "${RED}======================================================================${NC}"
  echo -e "${RED}  HEALTH CHECK FAILED! Target service did not respond with HTTP 200.  ${NC}"
  echo -e "${RED}======================================================================${NC}"
  echo -e "${YELLOW}Dumping recent journalctl logs for ${SERVICE_NAME}:${NC}"
  sudo journalctl -u "${SERVICE_NAME}" -n 40 --no-pager || true
  exit 1
fi
