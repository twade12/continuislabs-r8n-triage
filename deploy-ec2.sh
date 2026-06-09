#!/usr/bin/env bash
# deploy-ec2.sh — one-shot setup for a fresh EC2 instance (Ubuntu 22.04 / 24.04)
# Run once after SSH-ing into a new instance:
#   curl -fsSL https://raw.githubusercontent.com/continuislabs/r8n-triage/main/deploy-ec2.sh | bash
# or:
#   bash deploy-ec2.sh
set -euo pipefail

REPO_URL="https://github.com/twade12/continuislabs-r8n-triage.git"
APP_DIR="$HOME/r8n-triage"

echo ""
echo "========================================="
echo " r8n-triage — EC2 deploy"
echo "========================================="
echo ""

# ---- 1. Docker -----------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    echo "[1/4] Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "      Docker installed. Adding $USER to docker group."
    echo "      NOTE: You may need to log out and back in for group to take effect."
    echo "      Re-run this script after re-logging if docker commands fail."
else
    echo "[1/4] Docker already installed ($(docker --version))"
fi

# ---- 2. Docker Compose plugin --------------------------------------------------
if ! docker compose version &>/dev/null 2>&1; then
    echo "[2/4] Installing Docker Compose plugin..."
    sudo apt-get update -qq
    sudo apt-get install -y docker-compose-plugin
else
    echo "[2/4] Docker Compose already installed ($(docker compose version --short))"
fi

# ---- 3. Clone repo -------------------------------------------------------------
echo "[3/4] Cloning repo to $APP_DIR..."
if [[ -d "$APP_DIR/.git" ]]; then
    echo "      Repo exists — pulling latest..."
    git -C "$APP_DIR" pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi

# ---- 4. .env -------------------------------------------------------------------
echo "[4/4] Checking .env..."
if [[ ! -f "$APP_DIR/.env" ]]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo ""
    echo "  *** .env created from .env.example ***"
    echo "  IMPORTANT: Edit $APP_DIR/.env and set a real ADMIN_PASS before continuing."
    echo ""
    echo "  Run:  nano $APP_DIR/.env"
    echo "  Then: cd $APP_DIR && docker compose up -d --build"
    echo ""
else
    echo "      .env already exists — skipping."
fi

echo ""
echo "========================================="
echo " Setup complete. Next steps:"
echo ""
echo "  cd $APP_DIR"
echo ""
echo "  # If you haven't already, set your admin password:"
echo "  nano .env"
echo ""
echo "  # Build image and start the stack:"
echo "  docker compose up -d --build"
echo ""
echo "  # Watch logs:"
echo "  docker compose logs -f"
echo ""
echo "  # Verify (HTTP — Caddy will get the cert on first request):"
echo "  curl -I http://r8n.continuislabs.cloud"
echo ""
echo "  # Once Caddy has the cert:"
echo "  curl https://r8n.continuislabs.cloud/health"
echo "========================================="
