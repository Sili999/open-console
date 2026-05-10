#!/usr/bin/env python3
import os
import json
import time
import sys

try:
    from pyfingerprint.pyfingerprint import PyFingerprint
except ImportError:
    print("pyfingerprint not installed. Please install with 'sudo pip3 install pyfingerprint'")
    sys.exit(1)


def _load_hw_settings():
    settings_path = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                 '..', 'config', 'settings.json')
    try:
        with open(settings_path) as f:
            s = json.load(f)
        hw = s.get('hardware', {})
        return hw.get('fingerprint_port', '/dev/ttyAMA0'), hw.get('fingerprint_baud', 57600)
    except Exception:
        return '/dev/ttyAMA0', 57600   # safe default

def set_aura_led(f, control, speed, color, count):
    """
    Attempts to control the R503 Aura LED.
    control: 1=breathing, 2=flashing, 3=always on, 4=off
    color: 1=red, 2=blue, 3=purple, 4=green, 5=yellow, 6=cyan, 7=white
    """
    try:
        if hasattr(f, 'setAuraLed'):
            f.setAuraLed(control, speed, color, count)
    except Exception:
        pass

def main():
    port, baud = _load_hw_settings()
    try:
        f = PyFingerprint(port, baud, 0xFFFFFFFF, 0x00000000)
        
        if not f.verifyPassword():
            raise ValueError('Fingerprint sensor password verification failed!')

    except Exception as e:
        print('Init Error: ' + str(e), file=sys.stderr)
        sys.exit(1)

    # Set Aura LED to Breathing White while waiting
    set_aura_led(f, 1, 0x55, 7, 0)
    
    timeout_duration = 5.0 # seconds
    start_time = time.time()
    
    finger_placed = False
    
    # Wait for finger or timeout
    while time.time() - start_time < timeout_duration:
        if f.readImage():
            finger_placed = True
            break
        time.sleep(0.1)
        
    if not finger_placed:
        # Timeout
        set_aura_led(f, 4, 0x00, 1, 0) # Off
        sys.exit(2)
        
    # Finger was placed
    f.convertImage(0x01)
    result = f.searchTemplate()
    
    positionNumber = result[0]
    
    if positionNumber == -1:
        # Unknown finger -> Flashing Red
        set_aura_led(f, 2, 0x55, 1, 3)
        time.sleep(1)
        set_aura_led(f, 4, 0x00, 1, 0) # Off
        sys.exit(3)
        
    else:
        # Recognized -> Solid Green
        set_aura_led(f, 3, 0x00, 4, 0)
        print(positionNumber)
        time.sleep(0.5)
        set_aura_led(f, 4, 0x00, 1, 0) # Off
        sys.exit(0)

if __name__ == '__main__':
    main()
