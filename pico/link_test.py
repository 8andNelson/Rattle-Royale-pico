"""Join Wi-Fi and ask the game server for one order. Run in Thonny.

Start the laptop server with RATTLE_ROBOT_TOKEN set and ngrok running first.
"""

import config
from link import Link, start_wifi, wait_for_wifi

print("Joining", config.WIFI_SSID)
address = wait_for_wifi(start_wifi(config.WIFI_SSID, config.WIFI_PASSWORD))
print("Pico W address:", address)

link = Link(config.SERVER_URL, config.ROBOT_TOKEN)
print("Asking", config.SERVER_URL)
try:
    for _ in range(3):
        print("Order:", link.post("/api/robot", {"x": 0, "y": 0, "heading": 0, "moving": False, "arrived": None}))
finally:
    link.close()
