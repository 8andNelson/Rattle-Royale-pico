"""A host stopping and resuming the robot."""

import unittest

from aiohttp.test_utils import AioHTTPTestCase

from server.app import create_app
from server.lobby import LobbyBook
from server.pico_link import PicoLink

HOME = {"x": 0, "y": 0, "heading": 0, "moving": False}


class StopRuleTests(unittest.TestCase):
    def test_stopping_a_chase_ends_it_with_no_winner(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        book.start(ada, chase=True)
        book.record_shakes(ada, 5)
        self.assertTrue(book.stop_chase(code))
        snapshot = book.snapshot(code, ada)
        self.assertTrue(snapshot["finished"])
        self.assertEqual(snapshot["winners"], [])
        self.assertEqual(snapshot["reason"], "stopped")
        self.assertFalse(book.stop_chase(code))

    def test_a_shake_contest_cannot_be_stopped_as_a_chase(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        book.start(ada)
        self.assertFalse(book.stop_chase(code))

    def test_a_halted_robot_gets_stop_until_resumed_or_reset(self) -> None:
        robot = PicoLink("t")
        book = LobbyBook(chase_countdown=0)
        robot.halt()
        self.assertEqual(robot.order(book)["mode"], "stop")
        self.assertTrue(robot.summary()["halted"])
        robot.resume()
        self.assertEqual(robot.order(book)["mode"], "home")
        robot.halt()
        robot.request_reset()
        self.assertEqual(robot.order(book)["mode"], "home")


class StopEndpointTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app("secret", chase_countdown=0)

    async def poll(self, report: dict) -> dict:
        response = await self.client.post("/api/robot", json=report, headers={"Authorization": "Bearer secret"})
        return await response.json()

    async def join(self, kind: str, name: str, code: str | None = None):
        socket = await self.client.ws_connect("/ws")
        await socket.receive_json()
        message = {"type": kind, "name": name, "shaking": True}
        if code:
            message["code"] = code
        await socket.send_json(message)
        return socket, await self.wait(socket, lambda m: m["type"] == "lobby")

    async def wait(self, socket, check) -> dict:
        while True:
            message = await socket.receive_json()
            if check(message):
                return message

    async def test_the_creator_stops_a_running_chase_and_resumes_after(self) -> None:
        await self.poll(HOME)
        ada, lobby = await self.join("create", "Ada")
        bea, _ = await self.join("join", "Bea", lobby["code"])

        await ada.send_json({"type": "start"})
        await self.wait(ada, lambda m: m.get("started"))
        await ada.send_json({"type": "shakes", "total": 3})
        self.assertEqual((await self.poll(HOME))["mode"], "chase")

        await bea.send_json({"type": "stop_robot"})
        refused = await self.wait(bea, lambda m: m["type"] == "error")
        self.assertEqual(refused["message"], "Only a lobby creator can stop the robot.")

        await ada.send_json({"type": "stop_robot"})
        stopped = await self.wait(ada, lambda m: m.get("finished"))
        self.assertEqual(stopped["reason"], "stopped")
        self.assertTrue(stopped["robot"]["halted"])
        self.assertEqual((await self.poll(HOME))["mode"], "stop")

        await ada.send_json({"type": "rematch"})
        await self.wait(ada, lambda m: m["type"] == "lobby" and not m["started"])
        await ada.send_json({"type": "start"})
        blocked = await self.wait(ada, lambda m: m["type"] == "error")
        self.assertEqual(blocked["message"], "The robot is stopped. Resume it first.")

        await ada.send_json({"type": "resume_robot"})
        resumed = await self.wait(ada, lambda m: m["type"] == "lobby" and not m["robot"]["halted"])
        self.assertFalse(resumed["robot"]["halted"])
        self.assertEqual((await self.poll(HOME))["mode"], "home")
        await ada.close()
        await bea.close()


if __name__ == "__main__":
    unittest.main()
