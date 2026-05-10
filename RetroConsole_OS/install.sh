#!/usr/bin/env bash
# RetroConsole OS — one-shot dependency installer
# Run once on a fresh Raspberry Pi:
#   sudo bash install.sh

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }
step() { echo -e "\n${YELLOW}▶ $*${NC}"; }

NEED_REBOOT=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Root check ────────────────────────────────────────────────────────────────
[[ "$EUID" -eq 0 ]] || fail "Run as root: sudo bash install.sh"

# ── Python 3 check ────────────────────────────────────────────────────────────
step "Checking Python version"
python3 --version &>/dev/null || fail "python3 not found — install Raspberry Pi OS first"
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
[[ "${PY_VER%%.*}" -ge 3 && "${PY_VER##*.}" -ge 9 ]] \
    || warn "Python $PY_VER detected — 3.9+ recommended"
ok "Python $PY_VER"

# ── System packages (apt) ─────────────────────────────────────────────────────
step "Installing system packages"
apt-get update -qq
apt-get install -y --no-install-recommends \
    python3-pip          \
    libsdl2-dev          \
    libsdl2-image-dev    \
    libsdl2-mixer-dev    \
    libsdl2-ttf-dev      \
    libopenjp2-7         \
    git
ok "System packages installed"

# ── Python packages (pip) ─────────────────────────────────────────────────────
step "Installing Python packages"

PIP="python3 -m pip install --break-system-packages -q --upgrade"

PYTHON_PACKAGES=(
    "pygame"
    "RPi.GPIO"
    "adafruit-blinka"
    "adafruit-circuitpython-neopixel-spi"
    "pyfingerprint"
)

FAILED_PKGS=()
for pkg in "${PYTHON_PACKAGES[@]}"; do
    echo -n "  $pkg ... "
    if $PIP "$pkg" 2>/tmp/pip_err; then
        ok "$pkg"
    else
        echo ""
        warn "$pkg failed: $(cat /tmp/pip_err | tail -1)"
        FAILED_PKGS+=("$pkg")
    fi
done

if [[ ${#FAILED_PKGS[@]} -gt 0 ]]; then
    warn "The following packages failed to install: ${FAILED_PKGS[*]}"
    warn "The system will fall back to demo mode for missing hardware."
else
    ok "All Python packages installed"
fi

# ── Hardware interfaces (/boot/firmware/config.txt) ───────────────────────────
step "Enabling hardware interfaces"

CONFIG_TXT="/boot/firmware/config.txt"
[[ -f "$CONFIG_TXT" ]] || CONFIG_TXT="/boot/config.txt"   # older Pi OS path
[[ -f "$CONFIG_TXT" ]] || fail "Cannot find config.txt — is this a Raspberry Pi?"

# SPI — required for WS2812B LEDs via GPIO 10 (MOSI)
if grep -qE "^dtparam=spi=on" "$CONFIG_TXT"; then
    ok "SPI already enabled"
else
    echo "dtparam=spi=on" >> "$CONFIG_TXT"
    ok "SPI enabled"
    NEED_REBOOT=1
fi

# Disable Bluetooth to free UART0 for the R503 fingerprint sensor
if grep -qE "^dtoverlay=disable-bt" "$CONFIG_TXT"; then
    ok "UART0 (disable-bt) already set"
else
    echo "dtoverlay=disable-bt" >> "$CONFIG_TXT"
    ok "Bluetooth disabled — UART0 freed for fingerprint sensor"
    NEED_REBOOT=1
fi

# Serial port — enable hardware UART, disable console on serial
if grep -qE "^enable_uart=1" "$CONFIG_TXT"; then
    ok "Hardware UART already enabled"
else
    echo "enable_uart=1" >> "$CONFIG_TXT"
    ok "Hardware UART enabled"
    NEED_REBOOT=1
fi

# Remove the Linux serial console from UART0 — it blocks fingerprint sensor comms
CMDLINE_TXT="/boot/firmware/cmdline.txt"
[[ -f "$CMDLINE_TXT" ]] || CMDLINE_TXT="/boot/cmdline.txt"
if [[ -f "$CMDLINE_TXT" ]] && grep -qE "console=(serial0|ttyAMA0),[0-9]+" "$CMDLINE_TXT"; then
    sed -i 's/console=serial0,[0-9]\+ \?//g; s/console=ttyAMA0,[0-9]\+ \?//g' "$CMDLINE_TXT"
    ok "Serial console removed from UART0 (fingerprint sensor now has exclusive access)"
    NEED_REBOOT=1
else
    ok "Serial console already clear of UART0"
fi

# ── User permissions ──────────────────────────────────────────────────────────
step "Configuring user permissions"
TARGET_USER="${SUDO_USER:-pi}"

for group in gpio spi i2c dialout video; do
    if getent group "$group" &>/dev/null; then
        usermod -aG "$group" "$TARGET_USER"
        ok "Added '$TARGET_USER' to group '$group'"
    else
        warn "Group '$group' not found — skipped"
    fi
done

# ── Config files ──────────────────────────────────────────────────────────────
step "Checking config files"
mkdir -p "$SCRIPT_DIR/config"

USER_MAP="$SCRIPT_DIR/config/user_map.json"
if [[ ! -f "$USER_MAP" ]]; then
    echo "{}" > "$USER_MAP"
    ok "Created empty config/user_map.json"
else
    ok "config/user_map.json already exists"
fi

# ── Import verification ───────────────────────────────────────────────────────
step "Verifying Python imports"

python3 - <<'PYEOF'
import sys, importlib

CHECKS = [
    ("pygame",                      "pygame"),
    ("RPi.GPIO",                    "RPi.GPIO"),
    ("board",                       "adafruit-blinka"),
    ("busio",                       "adafruit-blinka"),
    ("neopixel_spi",                "adafruit-circuitpython-neopixel-spi"),
    ("pyfingerprint.pyfingerprint", "pyfingerprint"),
]

G = '\033[0;32m'; Y = '\033[1;33m'; N = '\033[0m'
all_ok = True
for mod, pkg in CHECKS:
    try:
        importlib.import_module(mod)
        print(f"  {G}[OK]{N}    {mod}")
    except ImportError as exc:
        print(f"  {Y}[SKIP]{N}  {mod}  (pip: {pkg}) — {exc}")
        all_ok = False

sys.exit(0 if all_ok else 2)
PYEOF

IMPORT_RC=$?
if [[ $IMPORT_RC -eq 0 ]]; then
    ok "All imports verified"
elif [[ $IMPORT_RC -eq 2 ]]; then
    warn "Some imports failed — hardware features for those modules will be disabled"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   RetroConsole OS — install complete!    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "  Start (full):        python3 $SCRIPT_DIR/start.py"
echo "  Start (no sensor):   python3 $SCRIPT_DIR/start.py --no-sensor"
echo "  Enroll new user:     python3 $SCRIPT_DIR/scripts/enroll.py"
echo "  Run tests:           python3 $SCRIPT_DIR/tests/test_integration_sim.py"
echo ""
if [[ $NEED_REBOOT -eq 1 ]]; then
    echo -e "${YELLOW}  ⚠  Hardware config changed — reboot required:${NC}"
    echo "     sudo reboot"
    echo ""
fi
