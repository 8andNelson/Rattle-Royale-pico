"""A whole chase: real server, simulated robot, one phone over the WebSocket.

Runs on the laptop: python -m unittest discover -s pico
"""

import asyncio
import sys
import threading
import unittest
from pathlib import Path

from aiohttp import ClientSession, web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config_example  # noqa: E402
from brain import Brain  # noqa: E402
from server.app import create_app  # noqa: E402
from server.pico_link import MARK_RADIUS_MM  # noqa: E402
from simulator import HttpLink, SimWheels, SimWlan, settings  # noqa: E402

TOKEN = "game-test"


class RobotThread(threading.Thread):
    def __init__(self, url: str, speed: float = 50) -> None:
        super().__init__(daemon=True)
        config = settings(TOKEN, url)
        self.wheels = SimWheels(config.STEP_US, speed=speed)
        self.brain = Brain(config, self.wheels, HttpLink(url, TOKEN), SimWlan(), log=lambda *_: None)
        self.running = True

    def run(self) -> None:
        while self.running:
            self.brain.tick()
            threading.Event().wait(0.01)

    def stop(self) -> None:
        self.running = False
        self.join(timeout=2)
        self.wheels.shutdown()


class GameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runner = web.AppRunner(create_app(TOKEN, chase_countdown=0))
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        self.url = "http://127.0.0.1:" + str(port)
        self.robot = RobotThread(self.url)
        self.robot.start()
        self.session = ClientSession()

    async def asyncTearDown(self) -> None:
        self.robot.stop()
        await self.session.close()
        await self.runner.cleanup()

    async def lobby_until(self, socket, check, seconds: float) -> dict:
        async def wait() -> dict:
            while True:
                message = await socket.receive_json()
                if message.get("type") == "lobby" and check(message):
                    return message

        return await asyncio.wait_for(wait(), seconds)

    async def test_the_robot_drives_to_the_shaker_and_wins_it_for_them(self) -> None:
        socket = await self.session.ws_connect(self.url + "/ws")
        await socket.receive_json()
        await socket.send_json({"type": "create", "name": "Ada", "shaking": True})
        await self.lobby_until(socket, lambda m: m["robot"]["online"] and m["robot"]["home"], 5)

        await socket.send_json({"type": "start"})
        started = await self.lobby_until(socket, lambda m: m["started"], 5)
        self.assertTrue(started["chase"])

        await socket.send_json({"type": "shakes", "total": 10})
        done = await self.lobby_until(socket, lambda m: m["finished"], 20)
        self.assertTrue(done["players"][0]["chased"])
        self.assertEqual(done["reason"], "arrival")
        self.assertEqual(done["winners"], ["Ada"])
        pose = done["robot"]["pose"]
        self.assertGreater(pose["x"], MARK_RADIUS_MM - config_example.ARRIVAL_RADIUS_MM - 5)

        await self.lobby_until(socket, lambda m: m["robot"]["home"], 20)
        await socket.close()

    async def test_a_lead_change_mid_drive_turns_the_robot_to_the_new_leader(self) -> None:
        self.robot.wheels._tick_seconds *= 5
        ada_socket = await self.session.ws_connect(self.url + "/ws")
        await ada_socket.receive_json()
        await ada_socket.send_json({"type": "create", "name": "Ada", "shaking": True})
        lobby = await self.lobby_until(ada_socket, lambda m: m["robot"]["home"], 5)
        bea_socket = await self.session.ws_connect(self.url + "/ws")
        await bea_socket.receive_json()
        await bea_socket.send_json({"type": "join", "name": "Bea", "code": lobby["code"], "shaking": True})
        await self.lobby_until(ada_socket, lambda m: len(m["players"]) == 2, 5)

        await ada_socket.send_json({"type": "start"})
        await self.lobby_until(ada_socket, lambda m: m["started"], 5)
        await ada_socket.send_json({"type": "shakes", "total": 6})
        toward_ada = await self.lobby_until(ada_socket, lambda m: m["robot"]["pose"]["x"] > 30, 10)
        self.assertFalse(toward_ada["finished"])

        for total in (12, 24, 36):
            await bea_socket.send_json({"type": "shakes", "total": total})
        await self.lobby_until(ada_socket, lambda m: any(p["chased"] and p["name"] == "Bea" for p in m["players"]), 5)
        done = await self.lobby_until(ada_socket, lambda m: m["finished"], 30)
        self.assertEqual(done["winners"], ["Bea"])
        self.assertEqual(done["reason"], "arrival")
        self.assertLess(done["robot"]["pose"]["x"], -MARK_RADIUS_MM + config_example.ARRIVAL_RADIUS_MM + 5)
        await ada_socket.close()
        await bea_socket.close()

    async def test_a_panel_jog_drives_and_a_reboot_gets_the_pose_back(self) -> None:
        headers = {"Authorization": "Bearer " + TOKEN}
        await asyncio.sleep(0.5)
        response = await self.session.post(
            self.url + "/api/robot/control", json={"action": "jog", "kind": "drive", "amount": 100}, headers=headers
        )
        self.assertEqual(response.status, 200)
        brain = self.robot.brain
        for _ in range(100):
            if brain.jog_done is not None:
                break
            await asyncio.sleep(0.05)
        self.assertAlmostEqual(brain.pose.x, 100, delta=1)
        await asyncio.sleep(0.5)

        rebooted = Brain(brain.config, self.robot.wheels, HttpLink(self.url, TOKEN), SimWlan(), log=lambda *_: None)
        self.assertNotEqual(rebooted.boot, brain.boot)
        self.robot.brain = rebooted
        for _ in range(60):
            if rebooted.restored:
                break
            await asyncio.sleep(0.05)
        self.assertTrue(rebooted.restored)
        self.assertAlmostEqual(rebooted.pose.x, 100, delta=1)
        for _ in range(40):
            status = await (await self.session.get(self.url + "/api/robot/status", headers=headers)).json()
            if not status["restoring"]:
                break
            await asyncio.sleep(0.05)
        self.assertEqual(status["boots"], 2)
        self.assertFalse(status["restoring"])

    async def test_a_reset_puts_the_robot_back_on_the_center(self) -> None:
        robot = self.robot.brain
        await asyncio.sleep(0.5)
        robot.pose.x = 140.0
        socket = await self.session.ws_connect(self.url + "/ws")
        await socket.receive_json()
        await socket.send_json({"type": "create", "name": "Ada", "shaking": True})
        await self.lobby_until(socket, lambda m: m["robot"]["online"], 5)
        self.robot.wheels.stop()
        robot.order = {"mode": "hold"}
        await socket.send_json({"type": "robot_home"})
        for _ in range(50):
            if robot.pose.x == 0 and not self.robot.wheels.busy():
                break
            await asyncio.sleep(0.1)
        self.assertEqual((robot.pose.x, robot.pose.y), (0, 0))
        await socket.close()


if __name__ == "__main__":
    unittest.main()
