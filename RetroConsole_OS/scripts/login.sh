 #!/bin/bash

# Configuration
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
CONFIG_FILE="$SCRIPT_DIR/../config/user_map.json"

echo "Starting RetroConsole Login Loop..."

while true; do
    echo "Waiting for user login..."
    
    # 1. Set external WS2812B LEDs to white to indicate readiness
    sudo python3 "$SCRIPT_DIR/set_rgb.py" --mode solid --color white

    # 2. Start fingerprint scan (this will also turn on the Aura LED on R503)
    # The scan_finger script will block for up to 5 seconds
    OUTPUT=$(sudo python3 "$SCRIPT_DIR/scan_finger.py")
    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        # Success! Output is the Slot ID
        SLOT_ID=$OUTPUT
        echo "Fingerprint matched! Slot ID: $SLOT_ID"
        
        # Check if user exists in map
        USER_EXISTS=$(python3 -c "import json; import sys; data=json.load(open('$CONFIG_FILE')); sys.exit(0 if str($SLOT_ID) in data else 1)" 2>/dev/null)
        if [ $? -eq 0 ]; then
            # Parse User Info
            USER_NAME=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))[str($SLOT_ID)]['name'])")
            USER_COLOR=$(python3 -c "import json; print(','.join(map(str, json.load(open('$CONFIG_FILE'))[str($SLOT_ID)]['color'])))")
            USER_HOME=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))[str($SLOT_ID)]['home'])")
            
            echo "Logging in as: $USER_NAME"
            
            # Set WS2812B to user color
            sudo python3 "$SCRIPT_DIR/set_rgb.py" --mode solid --color "[$USER_COLOR]"
            
            # Start EmulationStation
            echo "Starting EmulationStation for $USER_NAME in $USER_HOME..."
            # emulationstation --home "$USER_HOME"
            # NOTE: For testing we just sleep here if emulationstation is not installed
            if command -v emulationstation &> /dev/null; then
                emulationstation --home "$USER_HOME"
            else
                echo "EmulationStation not found! Simulating game session for 5 seconds..."
                sleep 5
            fi
            
            echo "EmulationStation exited. Resetting..."
        else
            echo "Slot ID $SLOT_ID found in sensor, but not in user_map.json!"
            sudo python3 "$SCRIPT_DIR/set_rgb.py" --mode flash --color red
        fi

    elif [ $EXIT_CODE -eq 2 ]; then
        # Timeout
        # echo "Scan timeout. Checking fallback buttons..."
        # TODO: Implement fallback button logic here
        # Example:
        # if ./check_buttons.sh; then ... fallback logic ... fi
        continue

    elif [ $EXIT_CODE -eq 3 ]; then
        # Unknown finger
        echo "Fingerprint not recognized!"
        sudo python3 "$SCRIPT_DIR/set_rgb.py" --mode flash --color red
        
    else
        # Error / Sensor unplugged
        echo "Sensor Error or unplugged! Exit code: $EXIT_CODE"
        sudo python3 "$SCRIPT_DIR/set_rgb.py" --mode flash --color red
        sleep 2
    fi

    # Small delay before next loop iteration to prevent high CPU load
    sleep 0.5
done
