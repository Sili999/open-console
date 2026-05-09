#!/usr/bin/env python3
import time
import sys

try:
    from pyfingerprint.pyfingerprint import PyFingerprint
except ImportError:
    print("pyfingerprint not installed. Please install with 'sudo pip3 install pyfingerprint'")
    sys.exit(1)

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
    try:
        f = PyFingerprint('/dev/ttyAMA0', 57600, 0xFFFFFFFF, 0x00000000)
        
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
