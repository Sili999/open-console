#!/usr/bin/env python3
import argparse
import time
import sys

try:
    from rpi_ws281x import PixelStrip, Color
except ImportError:
    print("rpi_ws281x not installed. Please install with 'sudo pip3 install rpi_ws281x'")
    sys.exit(1)

# LED strip configuration:
LED_COUNT = 16        # Number of LED pixels. Adjust based on your actual strip length.
LED_PIN = 10          # GPIO pin connected to the pixels (10 uses SPI /dev/spidev0.0).
LED_FREQ_HZ = 800000  # LED signal frequency in hertz (usually 800khz)
LED_DMA = 10          # DMA channel to use for generating signal (try 10)
LED_BRIGHTNESS = 255  # Set to 0 for darkest and 255 for brightest
LED_INVERT = False    # True to invert the signal (when using NPN transistor level shift)
LED_CHANNEL = 0       # set to '1' for GPIOs 13, 19, 41, 45 or 53

COLORS = {
    "red": Color(255, 0, 0),
    "green": Color(0, 255, 0),
    "blue": Color(0, 0, 255),
    "white": Color(255, 255, 255),
    "off": Color(0, 0, 0)
}

def parse_color(color_str):
    if color_str.lower() in COLORS:
        return COLORS[color_str.lower()]
    
    # Try parsing format like "[255, 120, 0]" or "255,120,0"
    try:
        color_str = color_str.strip('[] ')
        r, g, b = map(int, color_str.split(','))
        return Color(r, g, b) # rpi_ws281x Color takes GRB usually or RGB depending on strip, but typically Color(r,g,b) works if strip is RGB. Wait, rpi_ws281x Color is Color(r,g,b).
    except:
        pass
    
    # Default to white
    return COLORS["white"]

def set_all(strip, color):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
    strip.show()

def flash(strip, color, times=3, wait_ms=200):
    for _ in range(times):
        set_all(strip, color)
        time.sleep(wait_ms / 1000.0)
        set_all(strip, COLORS["off"])
        time.sleep(wait_ms / 1000.0)

def pulse(strip, color, wait_ms=20):
    """Pulsing effect (breathing)"""
    # extract rgb
    r = (color >> 16) & 0xFF
    g = (color >> 8) & 0xFF
    b = color & 0xFF
    
    # fade in
    for j in range(0, 256, 5):
        c = Color(int(r * j / 255.0), int(g * j / 255.0), int(b * j / 255.0))
        set_all(strip, c)
        time.sleep(wait_ms / 1000.0)
    # fade out
    for j in range(255, -1, -5):
        c = Color(int(r * j / 255.0), int(g * j / 255.0), int(b * j / 255.0))
        set_all(strip, c)
        time.sleep(wait_ms / 1000.0)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', type=str, choices=['solid', 'flash', 'pulse', 'off'], default='solid')
    parser.add_argument('--color', type=str, default='white')
    args = parser.parse_args()

    strip = PixelStrip(LED_COUNT, LED_PIN, LED_FREQ_HZ, LED_DMA, LED_INVERT, LED_BRIGHTNESS, LED_CHANNEL)
    strip.begin()

    target_color = parse_color(args.color)

    if args.mode == 'off':
        set_all(strip, COLORS["off"])
    elif args.mode == 'solid':
        set_all(strip, target_color)
    elif args.mode == 'flash':
        flash(strip, target_color)
    elif args.mode == 'pulse':
        pulse(strip, target_color)
