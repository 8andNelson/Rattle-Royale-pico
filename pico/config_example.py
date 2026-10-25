"""Copy this file to config.py on the Pico W and fill it in.

config.py holds the Wi-Fi password and the robot token, so git ignores it.
"""

# Wi-Fi the Pico W can join, tried in this order until one connects.
# eduroam's enterprise login will not work here. Use a phone hotspot or
# another WPA2 network with a plain password, on 2.4 GHz.
WIFI_NETWORKS = [
    ("YOUR_WIFI_NAME", "YOUR_WIFI_PASSWORD"),
    # ("YOUR_PHONE_HOTSPOT", "HOTSPOT_PASSWORD"),
]

# The same https address the phones open. Any network with internet works.
SERVER_URL = "https://petroleum-guy-whenever.ngrok-free.dev"
# Must match RATTLE_ROBOT_TOKEN on the laptop.
ROBOT_TOKEN = "CHANGE_ME"

# Pico GPIO to ULN2003 IN1..IN4. Left is motor 1 on the old Arduino car,
# right is motor 2.
LEFT_PINS = (2, 3, 4, 5)
RIGHT_PINS = (6, 7, 8, 9)

# 1 or -1: the coil direction that rolls each wheel forward. On the Arduino
# car, DRIVE -1 rolled toward seat 0, so forward is -1 for both. Run
# motor_test.py and flip a wheel that turns backward.
LEFT_FORWARD = -1
RIGHT_FORWARD = -1

# Microseconds per half-step. Each move starts at START_STEP_US and speeds up
# to STEP_US over RAMP_STEPS, then slows down the same way before it ends.
# The ramp lets the motors cruise faster than they can start. If a motor buzzes
# or the robot comes up short, raise STEP_US. The old Arduino sketch ran a flat
# 3000 with no ramp.
STEP_US = 2000
START_STEP_US = 3000
RAMP_STEPS = 200

# Geometry. These match the measured Arduino car: 34.31 steps per millimeter
# and 38.03 steps per degree of spin. Re-check with calibrate.py.
STEPS_PER_REV = 4096
WHEEL_DIAMETER_MM = 38.0
WHEEL_BASE_MM = 127.0

# Driving rules, in millimeters and degrees. Marks are 152.4 mm (6 in) out.
ARRIVAL_RADIUS_MM = 25.0
HOME_RADIUS_MM = 20.0
HOME_HEADING_DEGREES = 5.0
ALIGN_DEGREES = 15.0
MAX_SPIN_DEGREES = 30.0
MAX_DRIVE_MM = 40.0

# Ask the server for orders this often. Hold still after this long without one.
POLL_MS = 300
LINK_LOST_MS = 2000
