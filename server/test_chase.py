"""Chase rounds: the robot online at the start, arrival, the clock, and home."""

import unittest

from aiohttp.test_utils import AioHTTPTestCase

from server.app import create_app
from server.lobby import CHASE_ROUND_SECONDS, ROUND_SECONDS, LobbyBook
from server.pico_link import PicoLink

HOME = {"x": 0, "y": 0, "heading": 0, "moving": False}


def finish_by_clock(book: LobbyBook, code: str) -> dict:
    book._lobbies[code].ends_at = 0
    book.finish_if_due(code)
    return book.snapshot(code, book.member_ids(code)[0])


class ChaseRuleTests(unittest.TestCase):
    def test_a_chase_runs_longer_than_the_shake_contest(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        book.start(ada, chase=True)
        lobby = book._lobbies[code]
        self.assertAlmostEqual(lobby.ends_at - lobby.pull_at, CHASE_ROUND_SECONDS, places=1)
        self.assertNotEqual(CHASE_ROUND_SECONDS, ROUND_SECONDS)
        self.assertTrue(book.snapshot(code, ada)["chase"])

    def test_the_robot_ignores_a_plain_shake_contest(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, _ = book.create("Ada")
        book.start(ada)
        book.record_shakes(ada, 3)
        self.assertIsNone(book.robot_round())

    def test_arrival_wins_for_that_seat_even_without_the_lead(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada, chase=True)
        book.record_shakes(ada, 10)
        self.assertTrue(book.arrive(code, 1))
        snapshot = book.snapshot(code, ada)
        self.assertTrue(snapshot["finished"])
        self.assertEqual(snapshot["winners"], ["Bea"])
        self.assertEqual(snapshot["reason"], "arrival")
        self.assertFalse(book.arrive(code, 0))
        self.assertIsNone(book.robot_round())

    def test_arrival_does_nothing_outside_an_open_chase(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        self.assertFalse(book.arrive(code, 0))
        book.start(ada)
        self.assertFalse(book.arrive(code, 0))
        self.assertFalse(book.arrive("ZZZZ", 0))

    def test_the_clock_gives_the_win_to_the_player_being_chased(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada, chase=True)
        book.record_shakes(ada, 1)
        book.record_shakes(bea, 6)
        snapshot = finish_by_clock(book, code)
        self.assertEqual(snapshot["winners"], ["Bea"])
        self.assertEqual(snapshot["reason"], "clock")

    def test_nobody_chased_at_the_clock_is_a_draw(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        book.start(ada, chase=True)
        snapshot = finish_by_clock(book, code)
        self.assertEqual(snapshot["winners"], [])
        self.assertEqual(snapshot["reason"], "draw")

    def test_the_result_stays_after_the_winner_leaves(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada, chase=True)
        book.arrive(code, 1)
        book.leave(bea)
        snapshot = book.snapshot(code, ada)
        self.assertEqual(snapshot["winners"], ["Bea"])
        self.assertEqual(snapshot["reason"], "arrival")

    def test_the_shake_contest_still_names_the_most_shakes(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        book.record_shakes(bea, 2)
        snapshot = finish_by_clock(book, code)
        self.assertEqual(snapshot["winners"], ["Bea"])
        self.assertEqual(snapshot["reason"], "shakes")


class RobotPollTests(unittest.TestCase):
    def test_a_reported_arrival_ends_the_chase_and_sends_the_robot_home(self) -> None:
        book = LobbyBook(chase_countdown=0)
        robot = PicoLink("t")
        ada, code = book.create("Ada")
        book.start(ada, chase=True)
        book.record_shakes(ada, 4)
        self.assertEqual(robot.order(book)["mode"], "chase")
        _, arrival = robot.poll(book, dict(HOME, arrived={"round": code, "seat": 0}))
        self.assertTrue(arrival["won"])
        self.assertEqual(book.snapshot(code, ada)["reason"], "arrival")
        self.assertEqual(robot.order(book)["mode"], "home")

    def test_home_needs_a_still_robot_near_the_center_facing_seat_0(self) -> None:
        robot = PicoLink("t")
        book = LobbyBook(chase_countdown=0)
        self.assertFalse(robot.at_home())
        robot.poll(book, HOME)
        self.assertTrue(robot.at_home())
        robot.poll(book, dict(HOME, heading=-358))
        self.assertTrue(robot.at_home())
        robot.poll(book, dict(HOME, x=80))
        self.assertFalse(robot.at_home())
        robot.poll(book, dict(HOME, heading=45))
        self.assertFalse(robot.at_home())
        robot.poll(book, dict(HOME, moving=True))
        self.assertFalse(robot.at_home())

    def test_a_reset_changes_the_id_in_every_order(self) -> None:
        robot = PicoLink("t")
        book = LobbyBook(chase_countdown=0)
        robot.poll(book, dict(HOME, x=200))
        self.assertIsNone(robot.order(book)["reset"])
        robot.request_reset()
        first = robot.order(book)["reset"]
        self.assertIsNotNone(first)
        self.assertIsNone(robot.pose)
        robot.request_reset()
        self.assertNotEqual(robot.order(book)["reset"], first)


class StartTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app("secret", chase_countdown=0)

    async def poll(self, report: dict) -> dict:
        response = await self.client.post("/api/robot", json=report, headers={"Authorization": "Bearer secret"})
        return await response.json()

    async def next_lobby(self, socket) -> dict:
        while True:
            message = await socket.receive_json()
            if message["type"] in ("lobby", "error"):
                return message

    async def test_the_robot_must_be_home_before_a_chase_starts(self) -> None:
        socket = await self.client.ws_connect("/ws")
        await socket.receive_json()
        await socket.send_json({"type": "create", "name": "Ada", "shaking": True})
        lobby = await self.next_lobby(socket)
        self.assertFalse(lobby["robot"]["online"])

        await self.poll(dict(HOME, x=120))
        await socket.send_json({"type": "start"})
        refused = await self.next_lobby(socket)
        while refused["type"] != "error":
            refused = await self.next_lobby(socket)
        self.assertEqual(refused["message"], "The robot is not on the center mark yet.")

        await self.poll(HOME)
        await socket.send_json({"type": "start"})
        started = await self.next_lobby(socket)
        while not started.get("started"):
            started = await self.next_lobby(socket)
        self.assertTrue(started["chase"])
        await socket.close()

    async def test_the_creator_can_mark_the_robot_home(self) -> None:
        socket = await self.client.ws_connect("/ws")
        await socket.receive_json()
        await socket.send_json({"type": "create", "name": "Ada", "shaking": True})
        await self.next_lobby(socket)
        await self.poll(dict(HOME, x=120))
        await socket.send_json({"type": "robot_home"})
        order = await self.poll(dict(HOME, x=120))
        self.assertIsNotNone(order["reset"])
        await socket.close()


if __name__ == "__main__":
    unittest.main()
