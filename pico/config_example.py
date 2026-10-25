"""Copy this file to config.py on the Pico W and fill it in.

config.py holds the Wi-Fi password and the robot token, so git ignores it.
"""

# Wi-Fi the Pico W joins. eduroam's enterprise login will not work here. Use a
# phone hotspot or another WPA2 network with a plain password, 2.4 GHz.
WIFI_SSID = "YOUR_WIFI_NAME"
WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"

# The same https address the phones open. Any network with internet works.
SERVER_URL = "https://petroleum-guy-whenever.ngrok-free.dev"
# Must match RATTLE_ROBOT_TOKEN on the laptop.
ROBOT_TOKEN = "CHANGE_ME"

# Pico GPIO to ULN2003 IN1..IN4.
LEFT_PINS = (2, 3, 4, 5)
RIGHT_PINS = (6, 7, 8, 9)

# 1 or -1. Run motor_test.py and flip a wheel that turns backward.
LEFT_FORWARD = 1
RIGHT_FORWARD = 1

# Microseconds per half-step. 3000 matches the old Arduino sketch. Lower is
# faster until the motor starts to buzz and skip. Try 2000 once things work.
STEP_US = 3000

# Geometry. Measure, then tune with calibrate.py.
STEPS_PER_REV = 4096
WHEEL_DIAMETER_MM = 38.0
WHEEL_BASE_MM = 100.0

# Driving rules, in millimeters and degrees.
ARRIVAL_RADIUS_MM = 75.0
HOME_RADIUS_MM = 20.0
HOME_HEADING_DEGREES = 5.0
ALIGN_DEGREES = 15.0
MAX_SPIN_DEGREES = 30.0
MAX_DRIVE_MM = 40.0

# Ask the server for orders this often. Hold still after this long without one.
POLL_MS = 300
LINK_LOST_MS = 2000
