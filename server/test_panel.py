"""Robot health, reboot recovery, manual control, and the /robot panel."""

import unittest

from aiohttp.test_utils import AioHTTPTestCase

from server.app import create_app
from server.lobby import LobbyBook
from server.pages import ROBOT_PANEL
from server.pico_link import MARK_RADIUS_MM, RESTORE_SECONDS, PicoLink

HOME = {"x": 0, "y": 0, "heading": 0, "moving": False}
OUT = {"x": 80.0, "y": 20.0, "heading": 45.0, "moving": False}


class RestoreTests(unittest.TestCase):
    def test_a_quick_reboot_gets_the_last_pose_back_until_it_says_restored(self) -> None:
        robot = PicoLink("t")
        book = LobbyBook()
        robot.poll(book, dict(OUT, boot="a"), now=10)
        order, _ = robot.poll(book, dict(HOME, boot="b"), now=15)
        self.assertEqual(order["restore"], {"x": 80.0, "y": 20.0, "heading": 45.0})
        order, _ = robot.poll(book, dict(OUT, boot="b", restored=True), now=16)
        self.assertNotIn("restore", order)
        self.assertEqual(robot.boots, 2)

    def test_the_first_boot_and_a_long_gap_restore_nothing(self) -> None:
        robot = PicoLink("t")
        book = LobbyBook()
        order, _ = robot.poll(book, dict(HOME, boot="a"), now=10)
        self.assertNotIn("restore", order)
        robot.poll(book, dict(OUT, boot="a"), now=11)
        order, _ = robot.poll(book, dict(HOME, boot="b"), now=11 + RESTORE_SECONDS + 1)
        self.assertNotIn("restore", order)

    def test_marking_the_robot_home_cancels_a_restore(self) -> None:
        robot = PicoLink("t")
        book = LobbyBook()
        robot.poll(book, dict(OUT, boot="a"), now=10)
        robot.poll(book, dict(HOME, boot="b"), now=12)
        robot.request_reset()
        self.assertNotIn("restore", robot.order(book))


class HealthTests(unittest.TestCase):
    def test_health_keeps_known_numbers_only(self) -> None:
        robot = PicoLink("t")
        robot.poll(LobbyBook(), dict(HOME, health={"rssi": -61, "mem_free": 90000, "latency_ms": "slow", "extra": 1}))
        self.assertEqual(robot.health, {"uptime_s": None, "latency_ms": None, "rssi": -61, "mem_free": 90000})


class ManualTests(unittest.TestCase):
    def test_manual_control_holds_instead_of_driving_home(self) -> None:
        robot = PicoLink("t")
        book = LobbyBook()
        robot.set_manual(True)
        self.assertEqual(robot.order(book)["mode"], "hold")
        robot.go_home()
        self.assertEqual(robot.order(book)["mode"], "home")

    def test_a_jog_runs_until_the_robot_reports_it_done(self) -> None:
        robot = PicoLink("t")
        book = LobbyBook()
        robot.add_jog("spin", -90)
        order = robot.order(book)
        self.assertEqual((order["mode"], order["kind"], order["amount"]), ("jog", "spin", -90.0))
        self.assertTrue(robot.manual)
        robot.poll(book, dict(HOME, jog_done="not this one"))
        self.assertEqual(robot.order(book)["mode"], "jog")
        robot.poll(book, dict(HOME, jog_done=order["id"]))
        self.assertEqual(robot.order(book)["mode"], "hold")

    def test_jogs_out_of_range_are_refused(self) -> None:
        robot = PicoLink("t")
        for kind, amount in (("drive", 0), ("drive", 5000), ("spin", 1000), ("hop", 10), ("drive", "far")):
            with self.assertRaises(ValueError):
                robot.add_jog(kind, amount)

    def test_go_to_a_mark_uses_the_mark_circle(self) -> None:
        robot = PicoLink("t")
        robot.goto_seat(1, 4)
        order = robot.order(LobbyBook())
        self.assertEqual(order["mode"], "test")
        self.assertAlmostEqual(order["x"], 0, places=0)
        self.assertAlmostEqual(order["y"], MARK_RADIUS_MM, places=0)
        with self.assertRaises(ValueError):
            robot.goto_seat(4, 4)

    def test_a_halt_beats_a_jog(self) -> None:
        robot = PicoLink("t")
        robot.add_jog("drive", 50)
        robot.halt()
        self.assertEqual(robot.order(LobbyBook())["mode"], "stop")
        self.assertIsNone(robot.jog)


class PanelEndpointTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app("secret", chase_countdown=0)

    async def control(self, body: dict, token: str = "secret"):
        return await self.client.post("/api/robot/control", json=body, headers={"Authorization": "Bearer " + token})

    async def poll(self, report: dict) -> dict:
        response = await self.client.post("/api/robot", json=report, headers={"Authorization": "Bearer secret"})
        return await response.json()

    async def test_the_panel_page_is_served(self) -> None:
        response = await self.client.get("/robot")
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.text(), ROBOT_PANEL)

    async def test_control_needs_the_robot_token(self) -> None:
        response = await self.control({"action": "manual", "on": True}, token="wrong")
        self.assertEqual(response.status, 401)

    async def test_a_jog_from_the_panel_reaches_the_robot(self) -> None:
        response = await self.control({"action": "jog", "kind": "drive", "amount": 120})
        self.assertEqual(response.status, 200)
        status = await response.json()
        self.assertTrue(status["manual"])
        order = await self.poll(HOME)
        self.assertEqual((order["mode"], order["amount"]), ("jog", 120.0))

    async def test_bad_actions_say_why(self) -> None:
        response = await self.control({"action": "jog", "kind": "drive", "amount": 99999})
        self.assertEqual(response.status, 400)
        self.assertIn("1000", await response.text())
        response = await self.control({"action": "dance"})
        self.assertEqual(response.status, 400)

    async def test_a_chase_cannot_start_in_manual_and_the_panel_cannot_jog_a_chase(self) -> None:
        await self.poll(HOME)
        await self.control({"action": "manual", "on": True})
        socket = await self.client.ws_connect("/ws")
        await socket.receive_json()
        await socket.send_json({"type": "create", "name": "Ada", "shaking": True})
        await socket.send_json({"type": "start"})
        while True:
            message = await socket.receive_json()
            if message["type"] == "error":
                break
        self.assertIn("manual control", message["message"])

        await self.control({"action": "home"})
        await self.poll(HOME)
        await socket.send_json({"type": "start"})
        while True:
            message = await socket.receive_json()
            if message["type"] == "lobby" and message["started"]:
                break
        response = await self.control({"action": "jog", "kind": "spin", "amount": 90})
        self.assertEqual(response.status, 400)
        self.assertIn("chase is running", await response.text())

        response = await self.control({"action": "stop"})
        self.assertTrue((await response.json())["halted"])
        while True:
            message = await socket.receive_json()
            if message["type"] == "lobby" and message["finished"]:
                break
        self.assertEqual(message["reason"], "stopped")
        await socket.close()


if __name__ == "__main__":
    unittest.main()
