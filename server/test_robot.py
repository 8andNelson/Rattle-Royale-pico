"""Orders for the wireless robot."""

import unittest

from aiohttp.test_utils import AioHTTPTestCase

from server.app import create_app
from server.lobby import LobbyBook
from server.robot import RobotLink, mark_position


class OrderTests(unittest.TestCase):
    def test_no_round_sends_the_robot_home(self) -> None:
        self.assertEqual(RobotLink("t").order(LobbyBook()), {"mode": "home", "reset": None})

    def test_an_open_round_with_no_pull_holds(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada, chase=True)
        self.assertEqual(RobotLink("t").order(book), {"mode": "hold", "round": code, "reset": None})

    def test_the_chased_seat_becomes_a_point_on_the_circle(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.join(code, "Cy")
        book.join(code, "Di")
        book.start(ada, chase=True)
        book.record_shakes(bea, 4)
        order = RobotLink("t", mark_radius=200).order(book)
        self.assertEqual(order["mode"], "chase")
        self.assertEqual(order["seat"], 1)
        self.assertEqual(order["name"], "Bea")
        self.assertAlmostEqual(order["x"], 0)
        self.assertAlmostEqual(order["y"], 200)

    def test_a_test_point_is_used_only_without_a_round(self) -> None:
        book = LobbyBook()
        robot = RobotLink("t")
        robot.set_test_point({"x": 100, "y": -50})
        self.assertEqual(robot.order(book), {"mode": "test", "x": 100.0, "y": -50.0, "reset": None})
        ada, code = book.create("Ada")
        book.start(ada, chase=True)
        self.assertEqual(robot.order(book)["mode"], "hold")
        robot.set_test_point({"clear": True})
        self.assertIsNone(robot.test_point)

    def test_a_poll_keeps_the_pose_and_reports_each_arrival_once(self) -> None:
        robot = RobotLink("t")
        book = LobbyBook()
        report = {"x": 1, "y": 2, "heading": 90, "moving": True, "arrived": {"round": "ABCD", "seat": 2}}
        _, first = robot.poll(book, report, now=10)
        _, second = robot.poll(book, report, now=11)
        self.assertEqual(first, {"round": "ABCD", "seat": 2, "at": 10, "won": False})
        self.assertIsNone(second)
        self.assertEqual(robot.pose, {"x": 1.0, "y": 2.0, "heading": 90.0, "moving": True})
        self.assertTrue(robot.online(now=12))
        self.assertFalse(robot.online(now=20))

    def test_seat_zero_is_along_x(self) -> None:
        self.assertEqual(mark_position(0, 250), (250.0, 0.0))


class EndpointTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app("secret")

    async def test_a_wrong_token_is_refused(self) -> None:
        response = await self.client.post("/api/robot", json={}, headers={"Authorization": "Bearer nope"})
        self.assertEqual(response.status, 401)

    async def test_the_right_token_gets_an_order(self) -> None:
        response = await self.client.post("/api/robot", json={}, headers={"Authorization": "Bearer secret"})
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"mode": "home", "reset": None})

    async def test_a_bad_test_point_is_refused(self) -> None:
        response = await self.client.post("/api/robot/test", json={"x": "far"}, headers={"Authorization": "Bearer secret"})
        self.assertEqual(response.status, 400)


class DisabledTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app()

    async def test_no_token_turns_the_link_off(self) -> None:
        response = await self.client.post("/api/robot", json={}, headers={"Authorization": "Bearer "})
        self.assertEqual(response.status, 503)


if __name__ == "__main__":
    unittest.main()
