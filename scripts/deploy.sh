#!/usr/bin/env bash
# ==============================================================================
# scripts/deploy.sh — Production Deployment & Rollback Automation
# Executed on AWS EC2 instance by GitHub Actions CI/CD or standalone operator
# ==============================================================================

set -euo pipefail

# Color output helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

APP_DIR="${APP_DIR:-/opt/cybernauts}"
TARGET_IMAGE="${1:-${DOCKER_IMAGE:-cybernauts-app:latest}}"
HEALTH_CHECK_URL="http://127.0.0.1:8000/health"
MAX_HEALTH_ATTEMPTS=20
HEALTH_INTERVAL_SECONDS=3

echo -e "${BLUE}======================================================================${NC}"
echo -e "${BLUE}  Cybernauts Integrated Platform — EC2 Deployment Script              ${NC}"
echo -e "${BLUE}======================================================================${NC}"
echo -e "Target Directory : ${APP_DIR}"
echo -e "Target Image     : ${TARGET_IMAGE}"
echo -e "Timestamp        : $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo ""

# 1. Navigate to deployment directory
if [ -d "${APP_DIR}" ]; then
  cd "${APP_DIR}"
else
  echo -e "${YELLOW}[NOTICE] ${APP_DIR} does not exist. Using current working directory: $(pwd)${NC}"
fi

# 2. Validate essential deployment prerequisites
if [ ! -f "docker-compose.yml" ]; then
  echo -e "${RED}[ERROR] docker-compose.yml not found in $(pwd)!${NC}"
  exit 1
fi

if [ ! -f ".env" ]; then
  echo -e "${RED}[ERROR] .env file not found in $(pwd)!${NC}"
  echo -e "${YELLOW}Please create a server-side .env file with production credentials before deploying.${NC}"
  exit 1
fi

# 3. Ensure persistent directories and database files exist with proper permissions
echo -e "${BLUE}[STEP 1/5] Preparing persistent directories and permissions...${NC}"
mkdir -p static/recordings logs
touch leads.db
# Ensure non-root container user (UID 1000) can read/write to database and storage
chmod 666 leads.db
chmod -R 777 static/recordings logs

# 4. Record currently running container image for instant rollback on failure
PREVIOUS_IMAGE=$(docker compose images -q app 2>/dev/null || true)
if [ -n "${PREVIOUS_IMAGE}" ]; then
  echo -e "Previous active image ID: ${PREVIOUS_IMAGE}"
else
  echo -e "No existing container image found. Clean initial deployment."
fi

# 5. Pull latest image from registry (if remote image URI is provided)
echo -e "${BLUE}[STEP 2/5] Pulling target image: ${TARGET_IMAGE}...${NC}"
if [[ "${TARGET_IMAGE}" == *"/"* ]]; then
  if ! docker pull "${TARGET_IMAGE}"; then
    echo -e "${RED}[ERROR] Failed to pull image ${TARGET_IMAGE} from registry!${NC}"
    exit 1
  fi
else
  echo -e "${YELLOW}[INFO] Local image tag specified. Skipping docker pull.${NC}"
fi

# 6. Recreate and start the application container
echo -e "${BLUE}[STEP 3/5] Starting application via Docker Compose...${NC}"
export DOCKER_IMAGE="${TARGET_IMAGE}"

# Use 'docker compose' or fallback to 'docker-compose'
if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD="docker compose"
else
  COMPOSE_CMD="docker-compose"
fi

${COMPOSE_CMD} up -d --remove-orphans

# 7. Health Check Verification Loop
echo -e "${BLUE}[STEP 4/5] Verifying application health check (${HEALTH_CHECK_URL})...${NC}"
ATTEMPT=1
IS_HEALTHY=false

while [ ${ATTEMPT} -le ${MAX_HEALTH_ATTEMPTS} ]; do
  HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_CHECK_URL}" || echo "000")
  if [ "${HTTP_STATUS}" = "200" ]; then
    echo -e "${GREEN}✓ Application is healthy! HTTP 200 received on attempt ${ATTEMPT}.${NC}"
    IS_HEALTHY=true
    break
  else
    echo -e "  Attempt ${ATTEMPT}/${MAX_HEALTH_ATTEMPTS}: HTTP status=${HTTP_STATUS}. Waiting ${HEALTH_INTERVAL_SECONDS}s..."
    sleep ${HEALTH_INTERVAL_SECONDS}
    ATTEMPT=$((ATTEMPT + 1))
  fi
done

# 8. Handling healthcheck success or triggering rollback
if [ "${IS_HEALTHY}" = true ]; then
  echo -e "${BLUE}[STEP 5/5] Post-deployment cleanup...${NC}"
  docker image prune -f >/dev/null 2>&1 || true
  echo -e "${GREEN}======================================================================${NC}"
  echo -e "${GREEN}  DEPLOYMENT SUCCESSFUL! Version: ${TARGET_IMAGE}                     ${NC}"
  echo -e "${GREEN}======================================================================${NC}"
  exit 0
else
  echo -e "${RED}======================================================================${NC}"
  echo -e "${RED}  HEALTH CHECK FAILED! Target image did not respond within timeout.   ${NC}"
  echo -e "${RED}======================================================================${NC}"
  echo -e "${YELLOW}Dumping recent container logs:${NC}"
  ${COMPOSE_CMD} logs --tail 60 app

  # Automatic Rollback if previous known-good image exists
  if [ -n "${PREVIOUS_IMAGE}" ]; then
    echo ""
    echo -e "${YELLOW}[ROLLBACK] Initiating rollback to previous known-good image: ${PREVIOUS_IMAGE}...${NC}"
    export DOCKER_IMAGE="${PREVIOUS_IMAGE}"
    ${COMPOSE_CMD} up -d --remove-orphans

    # Brief rollback health check
    sleep 5
    ROLLBACK_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_CHECK_URL}" || echo "000")
    if [ "${ROLLBACK_STATUS}" = "200" ]; then
      echo -e "${GREEN}✓ Rollback successful. Service restored on previous image.${NC}"
    else
      echo -e "${RED}✗ Rollback container also failed health check. Manual intervention required.${NC}"
    fi
  else
    echo -e "${RED}[NO ROLLBACK] No previous image exists to rollback to.${NC}"
  fi

  exit 1
fi
