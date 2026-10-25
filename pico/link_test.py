"""Join Wi-Fi and ask the game server for one order. Run in Thonny.

Start the laptop server with RATTLE_ROBOT_TOKEN set and ngrok running first.
Each network in config.WIFI_NETWORKS is tried in order.
"""

import config
from brain import wifi_networks
from wifi_link import Link, start_wifi, wait_for_wifi

address = None
for ssid, password in wifi_networks(config):
    print("Joining", ssid)
    try:
        address = wait_for_wifi(start_wifi(ssid, password))
        break
    except RuntimeError as error:
        print(" ", error)
if address is None:
    raise RuntimeError("No Wi-Fi network in config.py connected.")
print("Pico W address:", address)

link = Link(config.SERVER_URL, config.ROBOT_TOKEN)
print("Asking", config.SERVER_URL)
try:
    for _ in range(3):
        print("Order:", link.post("/api/robot", {"x": 0, "y": 0, "heading": 0, "moving": False, "arrived": None}))
finally:
    link.close()
