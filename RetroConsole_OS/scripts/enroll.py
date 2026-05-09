#!/usr/bin/env python3
import time
import json
import os
import sys

try:
    from pyfingerprint.pyfingerprint import PyFingerprint
except ImportError:
    print("pyfingerprint not installed. Please install with 'sudo pip3 install pyfingerprint'")
    sys.exit(1)

CONFIG_FILE = '../config/user_map.json'


def _wait_for_finger(f, timeout=30):
    """Poll readImage() until a finger is placed or timeout expires."""
    import time as _time
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        if f.readImage():
            return True
        _time.sleep(0.1)
    return False


def set_aura_led(f, control, speed, color, count):
    """
    Attempts to control the R503 Aura LED.
    control: 1=breathing, 2=flashing, 3=always on, 4=off
    color: 1=red, 2=blue, 3=purple, 4=green, 5=yellow, 6=cyan, 7=white
    """
    try:
        # Check if setAuraLed method exists (might depend on library version)
        if hasattr(f, 'setAuraLed'):
            f.setAuraLed(control, speed, color, count)
    except Exception as e:
        print(f"Warning: Failed to set Aura LED ({e})")

def enroll_finger():
    try:
        f = PyFingerprint('/dev/ttyAMA0', 57600, 0xFFFFFFFF, 0x00000000)
        
        if not f.verifyPassword():
            raise ValueError('Fingerprint sensor password verification failed!')

        print('Currently used templates: {}/{}'.format(f.getTemplateCount(), f.getStorageCapacity()))
        
        # Set Aura LED to Breathing Blue
        set_aura_led(f, 1, 0x55, 2, 0)

        print('Waiting for finger...')

        ## Read finger 1 (with 30 s timeout)
        if not _wait_for_finger(f, timeout=30):
            raise TimeoutError('No finger detected after 30 s (scan 1)')

        f.convertImage(0x01)

        print('Finger recognized! Waiting for removal...')
        set_aura_led(f, 2, 0x55, 2, 0)

        removal_deadline = time.time() + 15
        while time.time() < removal_deadline:
            if not f.readImage():
                break
            time.sleep(0.05)
        else:
            raise TimeoutError('Finger not removed after 15 s')

        print('Place same finger again...')
        # Set Aura LED to Breathing Blue again
        set_aura_led(f, 1, 0x55, 2, 0)

        ## Read finger 2 (with 30 s timeout)
        if not _wait_for_finger(f, timeout=30):
            raise TimeoutError('No finger detected after 30 s (scan 2)')

        f.convertImage(0x02)
        
        print('Creating template...')
        if f.compareCharacteristics() == 0:
            raise Exception('Fingers do not match')

        f.createTemplate()
        
        positionNumber = f.storeTemplate()
        print('Finger enrolled successfully!')
        print('New template position #{}'.format(positionNumber))
        
        # Flash Green for success
        set_aura_led(f, 2, 0x55, 4, 3)
        time.sleep(1)
        # Turn off LED
        set_aura_led(f, 4, 0x00, 1, 0)
        
        return positionNumber

    except Exception as e:
        print('Operation failed!')
        print('Exception message: ' + str(e))
        sys.exit(1)

def main():
    script_dir = os.path.dirname(os.path.realpath(__file__))
    config_path = os.path.join(script_dir, CONFIG_FILE)
    
    # 1. Enroll finger
    slot_id = enroll_finger()
    
    # 2. Get user info
    name = input("Enter user name: ")
    color_input = input("Enter RGB color for user (e.g., 255,100,50): ")
    
    try:
        color = [int(c.strip()) for c in color_input.split(',')]
        if len(color) != 3:
            raise ValueError
    except:
        print("Invalid color format. Defaulting to [255, 255, 255] (white).")
        color = [255, 255, 255]
    
    home_dir = f"/home/pi/users/{slot_id}"
    
    # 3. Update user_map.json
    try:
        with open(config_path, 'r') as file:
            user_map = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        user_map = {}
        
    user_map[str(slot_id)] = {
        "name": name,
        "color": color,
        "home": home_dir
    }
    
    with open(config_path, 'w') as file:
        json.dump(user_map, file, indent=4)
    print(f"Updated {config_path}")
    
    # 4. Create .emulationstation directory
    es_dir = os.path.join(home_dir, ".emulationstation")
    os.makedirs(es_dir, exist_ok=True)
    
    # Try to set ownership to 'pi' if running as root
    try:
        import pwd
        pi_uid = pwd.getpwnam('pi').pw_uid
        pi_gid = pwd.getpwnam('pi').pw_gid
        os.chown(home_dir, pi_uid, pi_gid)
        os.chown(es_dir, pi_uid, pi_gid)
    except BaseException as e:
        print(f"Warning: Could not set owner to 'pi' ({e}). You may need to chown manually.")
        
    print(f"Created home directory for user: {home_dir}")
    print("Enrollment complete!")

if __name__ == '__main__':
    main()
