# RetroConsole OS — Setup Guide
## Raspberry Pi 5 + RetroPie Integration

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [Hardware You Need](#2-hardware-you-need)
3. [Wiring the Hardware](#3-wiring-the-hardware)
4. [Installing RetroPie](#4-installing-retropie)
5. [Getting the Code onto the Pi](#5-getting-the-code-onto-the-pi)
6. [Running the Installer](#6-running-the-installer)
7. [Understanding the Configuration File](#7-understanding-the-configuration-file)
8. [Testing Without Hardware (Demo Mode)](#8-testing-without-hardware-demo-mode)
9. [Enrolling Your First User](#9-enrolling-your-first-user)
10. [Autostart on Boot](#10-autostart-on-boot)
11. [Adding More Users](#11-adding-more-users)
12. [How It All Works Together](#12-how-it-all-works-together)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What This System Does

RetroConsole OS is a fingerprint-based multi-user login system that sits in front of RetroPie. Instead of a PIN or password, each player presses their finger on a sensor. The system recognises who they are, lights up the LED strip in their personal colour, and launches EmulationStation with their own save-game folder. When they are done playing, the system returns to the login screen ready for the next player.

```
[Power on] → [Login screen] → [Player presses finger]
         → [Recognised] → [LEDs light up in player colour]
         → [EmulationStation launches with player's home folder]
         → [Player finishes] → [Back to login screen]
```

---

## 2. Hardware You Need

### Required

| Part | Specification | Notes |
|------|--------------|-------|
| Raspberry Pi 5 | Any RAM size | Pi 5 is required — see note below |
| MicroSD card | 32 GB+, Class 10 | 64 GB recommended if storing ROMs |
| R503 Fingerprint Sensor | UART, 3.3 V | The Aura LED ring is used for feedback |
| WS2812B LED Strip | 5 V, any length | 16 pixels configured by default |
| Display | 800 × 480, HDMI or DSI | Matches the configured resolution |
| 8 Momentary Push Buttons | Any, normally open | Used for menu navigation |
| 5 V Power Supply | 5 A minimum | Pi 5 draws more current than earlier models |
| Jumper wires | Female-to-female | For sensor and button connections |
| 220 Ω resistors | 8 pieces | One per button (short-circuit protection) |

> **Why Raspberry Pi 5 specifically?**
> The Pi 5 uses a new chip called RP1 for its GPIO. This chip does **not** support DMA-based LED control (the `rpi_ws281x` library). Instead, the code uses SPI-based LED control (`adafruit-circuitpython-neopixel-spi`), which works correctly on Pi 5. If you use a Pi 4 or earlier, both methods work, but the code is written for Pi 5.

### Optional but Recommended

- Solderless breadboard for prototyping
- Multimeter for checking wiring
- USB keyboard for initial setup

---

## 3. Wiring the Hardware

### 3.1 Raspberry Pi 5 GPIO Reference

The pin numbers below use BCM numbering (the number printed on the chip, not the physical position on the header).

```
 3V3 (Pin 1)  [ ][ ] 5V  (Pin 2)
 GPIO2        [ ][ ] 5V  (Pin 4)
 GPIO3        [ ][ ] GND (Pin 6)
 GPIO4        [ ][ ] GPIO14
 GND (Pin 9)  [ ][ ] GPIO15
 GPIO17 ← UP  [ ][ ] GPIO18
 GPIO27 ←DOWN [ ][ ] GND
 GPIO22 ←LEFT [ ][ ] GPIO23 ← RIGHT
 3V3          [ ][ ] GPIO24 ← CONFIRM
 GPIO10 ←MOSI [ ][ ] GND
 GPIO9  (MISO)[ ][ ] GPIO25 ← BACK
 GPIO11 (SCLK)[ ][ ] GPIO8
 GND          [ ][ ] GPIO7
 GPIO0        [ ][ ] GPIO1
 GPIO5  ←NEW  [ ][ ] GND
 GPIO6  ←QUIT [ ][ ] GPIO12
 GPIO13       [ ][ ] GND
 GPIO19       [ ][ ] GPIO16
 GPIO26       [ ][ ] GPIO20
 GND          [ ][ ] GPIO21
```

---

### 3.2 R503 Fingerprint Sensor

The R503 communicates over UART (serial). It has a built-in Aura LED ring that the code controls to show scan status — breathing white when idle, green on success, red/flashing on failure.

The R503 has a 6-wire connector. Wire it as follows:

| R503 Wire | Colour (typical) | Connects to |
|-----------|-----------------|-------------|
| VIN (power) | Red | Pi Pin 4 — 5V |
| GND | Black | Pi Pin 6 — GND |
| TXD (sensor transmits) | Yellow | Pi Pin 10 — GPIO15 (RXD0) |
| RXD (sensor receives) | Green | Pi Pin 8 — GPIO14 (TXD0) |
| WAKEUP | White | Not connected (leave free) |
| 3V3 (touch detect) | Blue | Pi Pin 1 — 3V3 (optional) |

> **Important:** The fingerprint sensor uses UART0 (`/dev/ttyAMA0`). On Raspberry Pi OS, UART0 is normally used by Bluetooth. The installer script disables Bluetooth and frees UART0 for the sensor automatically. You do not need to do this manually.

---

### 3.3 WS2812B LED Strip

The LED strip uses the SPI bus. The Pi sends data through GPIO 10 (MOSI — the data output pin of SPI0).

| LED Strip Wire | Colour (typical) | Connects to |
|---------------|-----------------|-------------|
| 5V | Red | External 5 V supply — **not** the Pi's 5V pin |
| GND | Black | Pi GND **and** external supply GND |
| DIN (data in) | Green / White | Pi Pin 19 — GPIO10 (MOSI) |

> **Power warning:** WS2812B LEDs can draw up to 60 mA per pixel at full white. 16 pixels × 60 mA = nearly 1 A. The Pi's 5V GPIO pins cannot supply this. Use a separate 5V power supply for the LED strip and connect the grounds together.

> **Logic level:** The Pi outputs 3.3V logic but WS2812B expects 5V. In practice this often works at short cable lengths. If LEDs flicker or show wrong colours, add a logic level shifter between GPIO10 and DIN.

---

### 3.4 Navigation Buttons

Eight buttons provide the interface for navigating the login and enrolment screens.

Each button is wired with one leg to a GPIO pin and the other leg to GND. The code activates the built-in pull-up resistors, so no external pull-up is needed. A 220 Ω resistor in series is recommended to protect against accidental short circuits.

```
GPIO pin → [220 Ω resistor] → [Button] → GND
```

| Button | BCM Pin | Physical Pin | Function |
|--------|---------|-------------|----------|
| UP | GPIO 17 | Pin 11 | Cycle to next character (name entry) |
| DOWN | GPIO 27 | Pin 13 | Cycle to previous character |
| LEFT | GPIO 22 | Pin 15 | Previous colour (colour picker) |
| RIGHT | GPIO 23 | Pin 16 | Next colour |
| CONFIRM | GPIO 24 | Pin 18 | Accept / advance |
| BACK | GPIO 25 | Pin 22 | Delete character / go back |
| NEW USER | GPIO 5 | Pin 29 | Start enrolment from the login screen |
| QUIT | GPIO 6 | Pin 31 | Exit the UI |

These pin assignments can be changed in `config/settings.json` without touching any code (see Section 7).

---

## 4. Installing RetroPie

If RetroPie is not yet installed, follow these steps. If it is already running, skip to Section 5.

1. Download **Raspberry Pi OS (64-bit, Lite)** from the Raspberry Pi website.
2. Flash it to your SD card using **Raspberry Pi Imager**. Enable SSH and set your username to `mainuser` in the imager's advanced options.
3. Insert the SD card, connect the display, keyboard, and power. Let it boot fully.
4. Run the RetroPie installer:

```bash
sudo apt update && sudo apt install -y git
git clone --depth=1 https://github.com/RetroPie/RetroPie-Setup.git
cd RetroPie-Setup
sudo bash retropie_setup.sh
```

5. In the menu choose **Basic Install**. This installs EmulationStation and the core emulators. It takes 20–60 minutes.
6. After it finishes, **do not reboot yet** — continue with Section 5 first.

---

## 5. Getting the Code onto the Pi

Open a terminal on the Pi (either directly or via SSH) and run:

```bash
cd ~
git clone https://github.com/Sili999/open-console.git
cd open-console/RetroConsole_OS
```

This puts all the code at:
```
/home/mainuser/open-console/RetroConsole_OS/
```

---

## 6. Running the Installer

The installer handles everything in one command: system packages, Python libraries, hardware interface settings, and user permissions.

```bash
sudo bash install.sh
```

It will work through these steps automatically:

| Step | What happens |
|------|-------------|
| System packages | Installs SDL2 (required by pygame), git, and pip via apt |
| Python packages | Installs pygame, RPi.GPIO, adafruit-blinka, adafruit-circuitpython-neopixel-spi, pyfingerprint |
| SPI | Adds `dtparam=spi=on` to `/boot/firmware/config.txt` so the LED strip works |
| UART | Adds `dtoverlay=disable-bt` to free UART0 for the fingerprint sensor |
| Permissions | Adds the `mainuser` user to groups: `gpio`, `spi`, `dialout`, `video` |
| Config | Creates `config/user_map.json` if it does not exist |
| Verification | Imports every library and reports success or failure |

At the end, it will tell you whether a reboot is needed. If so:

```bash
sudo reboot
```

Wait for the Pi to come back up before continuing.

### What the installer output looks like

```
▶ Checking Python version
[OK]    Python 3.11.2

▶ Installing system packages
[OK]    System packages installed

▶ Installing Python packages
  pygame ... [OK]    pygamehe 
  RPi.GPIO ... [OK]    RPi.GPIO
  adafruit-blinka ... [OK]    adafruit-blinka
  adafruit-circuitpython-neopixel-spi ... [OK]    adafruit-circuitpython-neopixel-spi
  pyfingerprint ... [OK]    pyfingerprint

▶ Enabling hardware interfaces
[OK]    SPI enabled
[OK]    Bluetooth disabled — UART0 freed for fingerprint sensor
[OK]    Hardware UART enabled

▶ Configuring user permissions
[OK]    Added 'mainuser' to group 'gpio'
...

▶ Verifying Python imports
  [OK]    pygame
  [OK]    RPi.GPIO
  [OK]    board
  [OK]    busio
  [OK]    neopixel_spi
  [OK]    pyfingerprint.pyfingerprint

╔══════════════════════════════════════════╗
║   RetroConsole OS — install complete!   ║
╚══════════════════════════════════════════╝

  ⚠  Hardware config changed — reboot required:
     sudo reboot
```

---

## 7. Understanding the Configuration File

All settings live in `config/settings.json`. You never need to touch the Python code to adjust pin numbers, resolution, or timing.

```json
{
  "hardware": {
    "fingerprint_port": "/dev/ttyAMA0",
    "fingerprint_baud": 57600,
    "ws2812b_pixel_count": 16,
    "buttons": {
      "up":       17,
      "down":     27,
      "left":     22,
      "right":    23,
      "confirm":  24,
      "back":     25,
      "new_user":  5,
      "quit":      6
    }
  },
  "ui": {
    "fullscreen": true,
    "resolution": [800, 480],
    "scan_timeout_sec": 5,
    "enroll_timeout_sec": 30
  },
  "keybindings": {
    "up":       "K_UP",
    "down":     "K_DOWN",
    "left":     "K_LEFT",
    "right":    "K_RIGHT",
    "confirm":  "K_RETURN",
    "back":     "K_BACKSPACE",
    "new_user": "K_n",
    "quit":     "K_ESCAPE"
  },
  "emulationstation": {
    "binary": "emulationstation",
    "users_base_dir": "/home/mainuser/users"
  }
}
```

### What each section means

**`hardware`**
- `fingerprint_port` — serial port the R503 is connected to. Always `/dev/ttyAMA0` on Pi 5 after running the installer.
- `fingerprint_baud` — communication speed. The R503 uses 57600 by default.
- `ws2812b_pixel_count` — how many LEDs are in your strip. Change this to match your strip length.
- `buttons` — BCM pin number for each physical button. Change these if you wire buttons to different pins.

**`ui`**
- `fullscreen` — set to `false` to run in a window (useful for testing on a desktop PC).
- `resolution` — width and height of the login screen in pixels. Must match your display.
- `scan_timeout_sec` — how many seconds the system waits for a fingerprint result before giving up.
- `enroll_timeout_sec` — how many seconds the system waits for a finger during enrolment.

**`keybindings`**
- Maps each button function to a Pygame key name. This means you can also use a keyboard during testing without wiring buttons.

**`emulationstation`**
- `binary` — the command used to launch EmulationStation. Leave as `emulationstation` for standard RetroPie installs.
- `users_base_dir` — where each user's home folder is created.

---

## 8. Testing Without Hardware (Demo Mode)

Before connecting any hardware, verify that the login UI works by running in demo mode. This works on the Pi and also on a regular Windows or Linux PC.

```bash
python3 start.py --no-sensor
```

In demo mode:
- The fingerprint sensor is skipped
- The LED strip does nothing (silently)
- GPIO buttons are not used — use your keyboard instead

**Demo walkthrough:**

1. The login screen appears showing an idle animation.
2. Press **N** (or the NEW USER button) to start enrolment.
3. The screen simulates the two fingerprint scans automatically (with a short delay each).
4. Use **Up/Down** to cycle through characters to type a name.
5. Press **Enter** to add each character. Press **Backspace** to delete.
6. Press **Enter** again when done to move to the colour picker.
7. Use **Left/Right** to browse colours.
8. Press **Enter** to confirm. The success screen appears.
9. After 2 seconds, a fake "EmulationStation" session runs for 5 seconds.
10. The login screen returns, ready for the next player.

Press **Escape** at any time to quit.

---

## 9. Enrolling Your First User

Make sure all hardware is connected and you have rebooted after running the installer.

Start the full login UI:

```bash
python3 start.py
```

The LED strip should glow dim cyan and the screen should show the idle animation with the sensor's Aura LED breathing white.

**Enrolment steps:**

1. Press the **NEW USER** button (or **N** on a keyboard).
2. The screen enters enrolment mode and the Aura LED pulses.
3. **Place your finger on the sensor** and hold it still. The screen shows step 1 of 2.
4. **Lift your finger** when prompted.
5. **Place the same finger again**. The screen shows step 2 of 2.
6. The sensor stores the fingerprint template internally (on its own flash memory chip — not on the Pi).
7. The screen moves to the **name entry** screen. Use UP/DOWN to cycle characters and CONFIRM to add each one. Use BACK to delete.
8. Press CONFIRM when the name is complete.
9. The **colour picker** appears. Use LEFT/RIGHT to browse and CONFIRM to select your personal LED colour.
10. Enrolment is complete. The system returns to the idle login screen.

### What gets saved where

| Data | Stored on |
|------|----------|
| Fingerprint template | R503 sensor chip (internal flash, up to 200 templates) |
| Name, LED colour, home folder path | `config/user_map.json` on the Pi |

The Pi never sees raw fingerprint data — only a slot number (e.g., `3`) is returned after a successful match. `user_map.json` then maps that number to a name and colour:

```json
{
  "1": {
    "name": "Alice",
    "color": [0, 200, 255],
    "home": "/home/mainuser/users/1"
  }
}
```

---

## 10. Autostart on Boot

To make RetroConsole OS launch automatically when the Pi powers on, create a systemd service.

```bash
sudo nano /etc/systemd/system/retroconsole.service
```

Paste the following (adjust the path if your clone is in a different location):

```ini
[Unit]
Description=RetroConsole OS Login UI
After=multi-user.target graphical.target

[Service]
Type=simple
User=mainuser
WorkingDirectory=/home/mainuser/open-console/RetroConsole_OS
ExecStart=/usr/bin/python3 /home/mainuser/open-console/RetroConsole_OS/start.py
Restart=on-failure
RestartSec=5
Environment=DISPLAY=:0
Environment=SDL_VIDEODRIVER=fbcon
Environment=SDL_FBDEV=/dev/fb0

[Install]
WantedBy=multi-user.target
```

Save the file (`Ctrl+O`, `Enter`, `Ctrl+X`), then enable the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable retroconsole.service
sudo systemctl start retroconsole.service
```

Check that it started without errors:

```bash
sudo systemctl status retroconsole.service
```

From now on, RetroConsole OS will start automatically every time the Pi boots, before any desktop environment appears.

### Disabling auto-login to the desktop

If Raspberry Pi OS is set to auto-login to a desktop, disable it so the login screen is not covered:

```bash
sudo raspi-config
```

Go to **System Options → Boot / Auto Login → Console** (not desktop, not auto-login).

---

## 11. Adding More Users

There is no limit on the number of enrolled users (the R503 sensor supports up to 200 fingerprint templates).

To enrol a new user:
1. Start the login UI (or wait until it is running if it auto-started).
2. Press the **NEW USER** button from the idle or fail screen.
3. Follow the same enrolment steps from Section 9.

Each new user automatically gets the next available slot number and their own home folder at `/home/mainuser/users/<slot_number>/.emulationstation/`.

To **remove a user**, delete their entry from `config/user_map.json`. Their fingerprint template remains on the sensor chip. To also remove the template from the sensor, re-run enrolment from scratch with the sensor management tools (this requires direct sensor access via `scripts/enroll.py`).

---

## 12. How It All Works Together

This section explains what happens under the hood, so you can understand the system if something goes wrong.

### The login loop

```
[start.py]
    │
    ├─ Creates LEDManager    → Controls WS2812B strip via SPI (GPIO 10)
    ├─ Creates FingerprintManager → Talks to R503 via UART (/dev/ttyAMA0)
    └─ Creates LoginUI
           │
           ├─ Background thread: polls sensor every second
           │      Finger detected → posts event to internal queue
           │      Match found    → posts slot ID to queue
           │      No match       → posts "unknown" to queue
           │
           ├─ Main loop (60 fps): reads queue, updates state machine
           │      IDLE → finger event → SCAN
           │      SCAN → match event  → SUCCESS (fires on_login_callback)
           │      SCAN → unknown event→ FAIL → back to IDLE after 3 s
           │
           └─ on_login_callback (daemon thread)
                  Lights LEDs in user colour
                  Launches: emulationstation --home /home/mainuser/users/<slot>
                  Waits for EmulationStation to exit
                  Turns LEDs off
                  Returns login screen to IDLE
```

### The fingerprint sensor (R503)

The R503 connects over serial UART at 57600 baud. When a finger is placed, the sensor:
1. Captures an image of the fingerprint.
2. Converts the image to a compact feature template internally.
3. Searches its own flash memory (up to 200 stored templates) for a match.
4. Returns the slot number of the match (or −1 if not recognised).

The Pi receives only a single number. No fingerprint image or raw data ever leaves the sensor.

The Aura LED ring on the sensor is controlled by sending a raw UART command (opcode `0x35`) directly to the sensor. The code handles this automatically to provide visual feedback:

| LED state | Meaning |
|-----------|---------|
| Breathing white | Waiting for a finger |
| Solid green | Fingerprint recognised |
| Flashing red | Fingerprint not recognised |
| Breathing blue | Enrolment in progress |

### The LED strip (WS2812B)

The WS2812B strip uses a single-wire protocol that is timing-critical. On Pi 5, DMA-based timing (used by the older `rpi_ws281x` library) is not available because the new RP1 GPIO chip does not support it. Instead, the code uses SPI to clock data out through GPIO 10 (MOSI), which the `adafruit-circuitpython-neopixel-spi` library handles correctly.

The strip lights up in each user's personal colour when they log in and turns off when they exit.

If the LED strip fails (broken wire, wrong voltage, SPI not enabled), it disables itself silently — the rest of the system continues to work normally.

### The buttons

Each button is a simple momentary switch wired to a GPIO pin and GND. The code uses the RPi.GPIO library's edge-detect feature to watch all eight pins in the background. When a button is pressed, it injects a Pygame keyboard event into the UI, so the UI code only ever deals with keyboard events regardless of whether a physical button or a key was pressed.

---

## 13. Troubleshooting

### The screen stays black after boot

- Check that `SDL_VIDEODRIVER=fbcon` is set in the systemd service file.
- Check that the display is connected and powered before the Pi boots.
- Try running `python3 start.py` manually from an SSH session to see error output.

### "SPI not enabled" in the logs

The installer should have added `dtparam=spi=on` to `/boot/firmware/config.txt`, but a reboot is required for it to take effect. Reboot and try again:

```bash
sudo reboot
```

To verify SPI is active after reboot:
```bash
ls /dev/spidev*
# Should show: /dev/spidev0.0  /dev/spidev0.1
```

### LEDs do not light up

1. Check that the strip's DIN (data in) is connected to GPIO 10 (Pin 19).
2. Check that GND is shared between the Pi, the LED strip, and the external 5V supply.
3. Check that the strip has a 5V power supply — the Pi's 5V pins cannot power more than a few LEDs.
4. Check that `ws2812b_pixel_count` in `settings.json` matches the actual number of LEDs in your strip.

### "Fingerprint sensor password verification failed" or sensor not found

1. Check that `dtoverlay=disable-bt` is in `/boot/firmware/config.txt` and you have rebooted.
2. Check wiring: TXD (sensor) → GPIO 15 (Pi RX), RXD (sensor) → GPIO 14 (Pi TX).
3. Check that the `mainuser` user is in the `dialout` group:
   ```bash
   groups mainuser
   # Should include: dialout
   ```
4. Verify the serial port is free:
   ```bash
   ls -la /dev/ttyAMA0
   ```

### Enrolment completes but the same finger is not recognised later

- The two scans during enrolment must be of the **same finger** from the **same angle**.
- If recognition is unreliable, delete the slot from `user_map.json` and re-enrol with slower, more deliberate placements.
- The R503 supports up to 200 stored templates before the flash is full.

### Buttons do not respond

1. Check that the `mainuser` user is in the `gpio` group:
   ```bash
   groups mainuser
   # Should include: gpio
   ```
2. Check that the button BCM pin numbers in `settings.json` match your physical wiring.
3. Test a button manually:
   ```bash
   python3 -c "import RPi.GPIO as GPIO; GPIO.setmode(GPIO.BCM); GPIO.setup(17, GPIO.IN, pull_up_down=GPIO.PUD_UP); print(GPIO.input(17))"
   # Should print 1 (unpressed) or 0 (pressed)
   ```

### EmulationStation does not start

1. Check that RetroPie is installed:
   ```bash
   which emulationstation
   # Should print: /usr/bin/emulationstation
   ```
2. Check that the `home` path in `user_map.json` exists:
   ```bash
   ls /home/mainuser/users/
   ```
3. Run EmulationStation manually to see its error output:
   ```bash
   emulationstation --home /home/mainuser/users/1
   ```

### Running the automated test suite

To verify that all software components are working correctly (without needing any hardware):

```bash
python3 tests/test_integration_sim.py
```

All 45 tests should pass. This suite simulates wiring faults, sensor errors, and state-machine edge cases so problems can be diagnosed before hardware is connected.
