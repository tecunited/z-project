#!/bin/bash
set -e

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }
info() { echo -e "${BLUE}[→]${NC} $1"; }

# ── Banner ────────────────────────────────────────────────────────────────────
echo ""
echo "  ██████╗ ██████╗ ███╗   ██╗███████╗ █████╗ ██╗"
echo "  ██╔════╝██╔═══██╗████╗  ██║██╔════╝██╔══██╗██║"
echo "  ██║     ██║   ██║██╔██╗ ██║███████╗███████║██║"
echo "  ██║     ██║   ██║██║╚██╗██║╚════██║██╔══██║██║"
echo "  ╚██████╗╚██████╔╝██║ ╚████║███████║██║  ██║██║"
echo "   ╚═════╝ ╚═════╝ ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝╚═╝"
echo ""
echo "  Z-Project Provisioning Script"
echo "  ─────────────────────────────"
echo ""

# ── Arguments ─────────────────────────────────────────────────────────────────
UNIT_ID=""
CAMERA_TYPE="z-project"
API_KEY=""
API_BASE_URL="https://consai.app"
STORAGE_BACKEND="gcs"
OPENWEATHER_KEY=""
IPINFO_TOKEN=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --unit-id)         UNIT_ID="$2";         shift 2 ;;
        --camera-type)     CAMERA_TYPE="$2";     shift 2 ;;
        --api-key)         API_KEY="$2";         shift 2 ;;
        --api-base-url)    API_BASE_URL="$2";    shift 2 ;;
        --storage-backend) STORAGE_BACKEND="$2"; shift 2 ;;
        --openweather-key) OPENWEATHER_KEY="$2"; shift 2 ;;
        --ipinfo-token)    IPINFO_TOKEN="$2";    shift 2 ;;
        *) err "Unknown argument: $1" ;;
    esac
done

# ── Validate ──────────────────────────────────────────────────────────────────
if [ -z "$UNIT_ID" ]; then
    echo -n "  Enter Unit ID (e.g. 0051): "
    read UNIT_ID
fi

if [ -z "$API_KEY" ]; then
    echo -n "  Enter API Key: "
    read API_KEY
fi

if [ -z "$OPENWEATHER_KEY" ]; then
    echo -n "  Enter OpenWeather API Key: "
    read OPENWEATHER_KEY
fi

echo ""
info "Provisioning unit: $UNIT_ID"
info "Camera type:       $CAMERA_TYPE"
info "Storage backend:   $STORAGE_BACKEND"
echo ""

# ── Step 1: System update ─────────────────────────────────────────────────────
info "Step 1/9: Updating system..."
sudo apt update -qq && sudo apt upgrade -y -qq
log "System updated"

# ── Step 2: Install packages ──────────────────────────────────────────────────
info "Step 2/9: Installing packages..."
sudo apt install -y -qq \
    python3-pip \
    python3-libcamera \
    python3-picamera2 \
    python3-smbus \
    python3-flask \
    git \
    sqlite3 \
    i2c-tools \
    rpicam-apps \
    fbi \
    qrencode \
    hostapd \
    dnsmasq \
    exiftool \
    libcamera-tools

sudo pip3 install --break-system-packages -q \
    python-dotenv \
    luma.oled \
    RPi.GPIO \
    Pillow \
    requests \
    boto3

log "Packages installed"

# ── Step 3: Hardware config ───────────────────────────────────────────────────
info "Step 3/9: Configuring hardware..."

# Camera
sudo raspi-config nonint do_camera 0 2>/dev/null || true

# SPI for OLED
sudo raspi-config nonint do_spi 0

# I2C
sudo raspi-config nonint do_i2c 0

# Autologin
sudo raspi-config nonint do_boot_behaviour B2

# Add dtoverlay and GPIO config
CONFIG_FILE="/boot/firmware/config.txt"

if ! grep -q "dtoverlay=imx519" "$CONFIG_FILE"; then
    echo "dtoverlay=imx519" | sudo tee -a "$CONFIG_FILE" > /dev/null
    log "Camera overlay added"
fi

if ! grep -q "gpio=6,19,5,26,13,21,20,16=pu" "$CONFIG_FILE"; then
    echo "gpio=6,19,5,26,13,21,20,16=pu" | sudo tee -a "$CONFIG_FILE" > /dev/null
    log "GPIO pull-ups added"
fi

log "Hardware configured"

# ── Step 4: Locale ────────────────────────────────────────────────────────────
info "Step 4/9: Setting locale and timezone..."
sudo locale-gen en_GB.UTF-8 pl_PL.UTF-8 > /dev/null 2>&1
sudo update-locale LANG=en_GB.UTF-8 LC_ALL=en_GB.UTF-8
sudo timedatectl set-timezone Europe/Warsaw
log "Locale and timezone set"

# ── Step 5: Clone code ────────────────────────────────────────────────────────
info "Step 5/9: Cloning Z-Project code..."

if [ -d "/home/z001/.git" ]; then
    warn "Repo already exists — pulling latest..."
    cd /home/z001 && git pull --ff-only
else
    git clone https://github.com/tecunited/z-project.git /tmp/z-project-clone
    cp -r /tmp/z-project-clone/. /home/z001/
    rm -rf /tmp/z-project-clone
fi

log "Code deployed"

# ── Step 6: Create directory structure ────────────────────────────────────────
info "Step 6/9: Creating directories..."
mkdir -p /home/z001/logs/archive
mkdir -p /home/z001/logs/active
mkdir -p /home/z001/photos
mkdir -p /home/z001/photos_backup
mkdir -p /home/z001/photos_archive
sudo mkdir -p /mnt/usb
log "Directories created"

# ── Step 7: Create .env ───────────────────────────────────────────────────────
info "Step 7/9: Creating configuration..."

cat > /home/z001/.env << EOF
# Unit identity
UNIT_ID=${UNIT_ID}
INSTALLATION_ID=0000
CAMERA_TYPE=${CAMERA_TYPE}

# consai.app
API_KEY=${API_KEY}
API_BASE_URL=${API_BASE_URL}

# Storage backend — gcs | r2 | s3
STORAGE_BACKEND=${STORAGE_BACKEND}
GCS_BUCKET=gconsai-${UNIT_ID}
GCS_CREDENTIALS_PATH=/home/z001/consai/credentials.json
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=
R2_ENDPOINT=

# External APIs
OPENWEATHER_API_KEY=${OPENWEATHER_KEY}
IPINFO_TOKEN=${IPINFO_TOKEN}

# Schedule
CAPTURE_FREQ=1
SYNC_FREQ=5
EOF

log ".env created"

# ── Step 8: Initialize camera settings and DB ─────────────────────────────────
info "Step 8/9: Initializing database and settings..."

export PYTHONPATH=/home/z001

# Add PYTHONPATH to .bashrc
if ! grep -q "PYTHONPATH=/home/z001" /home/z001/.bashrc; then
    echo "export PYTHONPATH=/home/z001" >> /home/z001/.bashrc
fi

# Initialize camera settings
python3 -c "
from consai.settings import save_settings, DEFAULTS
save_settings(DEFAULTS)
print('Camera settings initialized')
"

# Initialize DB
python3 -m consai.db

# Initialize unit config
python3 -c "
from consai.installation import init_unit_config
init_unit_config()
print('Unit config initialized')
"

log "Database and settings initialized"

# ── Step 9: Install systemd services ─────────────────────────────────────────
info "Step 9/9: Installing systemd services..."

sudo cp /home/z001/systemd/*.service /etc/systemd/system/
sudo cp /home/z001/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable capture.timer sync.timer watchdog.service oled-menu.service
sudo systemctl start capture.timer sync.timer watchdog.service oled-menu.service

log "Services installed and started"

# ── Sudoers ───────────────────────────────────────────────────────────────────
if [ ! -f /etc/sudoers.d/z001 ]; then
    echo "z001 ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/z001 > /dev/null
    sudo chmod 440 /etc/sudoers.d/z001
    log "Sudoers configured"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "  ─────────────────────────────────────────────"
echo -e "  ${GREEN}✅ Unit ${UNIT_ID} provisioned successfully!${NC}"
echo "  ─────────────────────────────────────────────"
echo ""
echo "  Next steps:"
echo "  1. Reboot: sudo reboot"
echo "  2. OLED should show home screen on boot"
echo "  3. Assign installation ID in consai.app"
echo "  4. Update INSTALLATION_ID in /home/z001/.env"
echo ""