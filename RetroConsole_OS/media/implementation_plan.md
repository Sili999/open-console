# Integration of R503 Fingerprint Login System

Based on the `retro_console_projektplan.html` and the user's specific request to consider the R503's built-in RGB ring display, this plan outlines the implementation of the Phase C login system.

## Background Context
The system uses a Raspberry Pi 5. The R503 fingerprint sensor is connected via UART (`/dev/ttyAMA0`), and there's also an external WS2812B RGB strip via SPI (GPIO 10). The user explicitly reminded us about the R503's internal RGB Ring.
We will use the `pyfingerprint` library to interface with the R503 (which supports the Aura LED ring) and `rpi_ws281x` for the WS2812B strip.

## User Review Required

> [!IMPORTANT]
> The R503 has its own RGB ring (Aura LED), and the project plan also mentions an external WS2812B LED strip. I will implement the login script to control *both* the R503's RGB ring and the WS2812B strip. Please let me know if you only want to use the R503's RGB ring or both.

## Proposed Changes

### Configuration
#### [MODIFY] [user_map.json](file:///c:/Users/User/Documents/GitHub/open-console/RetroConsole_OS/config/user_map.json)
- Set up an initial empty JSON structure `{}` to store user data.

---

### Python Scripts (Hardware Interface)
#### [MODIFY] [set_rgb.py](file:///c:/Users/User/Documents/GitHub/open-console/RetroConsole_OS/scripts/set_rgb.py)
- Implement a script using `rpi_ws281x` to control the external LED strip via SPI (GPIO 10).
- Support arguments like `--mode` (flash, solid, off) and `--color` (red, green, user-specific RGB).

#### [MODIFY] [enroll.py](file:///c:/Users/User/Documents/GitHub/open-console/RetroConsole_OS/scripts/enroll.py)
- Implement enrollment logic using `pyfingerprint`.
- Control the R503 Aura LED during enrollment (e.g., breathing blue while waiting, flashing green on success).
- After successful enrollment, ask for user details (name, color) and update `user_map.json`.
- Create the user's `.emulationstation` directory.

#### [MODIFY] [scan_finger.py](file:///c:/Users/User/Documents/GitHub/open-console/RetroConsole_OS/scripts/scan_finger.py)
- Wait for a finger to be placed (with a 5-second timeout).
- Control the R503 Aura LED (e.g., breathing white while waiting).
- Output the matched slot ID to stdout.
- Return exit code 0 on success, 2 on timeout, 3 on unknown finger.

---

### Bash Orchestration
#### [MODIFY] [login.sh](file:///c:/Users/User/Documents/GitHub/open-console/RetroConsole_OS/scripts/login.sh)
- The main orchestration loop.
- Pulses LEDs white (both R503 and WS2812B).
- Calls `scan_finger.py`.
- If successful (exit 0), reads the user's color from `user_map.json`, sets LEDs to that color, and launches `emulationstation --home /home/pi/users/<id>`.
- Implements the fallback login (reading GPIO inputs) if `scan_finger.py` times out (exit 2).

## Verification Plan

### Automated Tests
- We will provide mock implementations or test mode flags if running on a non-Pi environment, but primarily this code is for the actual Raspberry Pi hardware.
- We will lint and statically check the Python and bash scripts for syntax errors.

### Manual Verification
- You will need to run `python3 enroll.py` on the Pi to test sensor connection and enrollment.
- You will need to run `bash login.sh` to test the full flow.
