"""Reconnect grace, the chase countdown, and the big screen."""

import asyncio
import time
import unittest

from aiohttp.test_utils import AioHTTPTestCase

from server.app import create_app
from server.lobby import CHASE_COUNTDOWN_SECONDS, LobbyBook, LobbyError
from server.pages import ARENA_JS, SCREEN

HOME = {"x": 0, "y": 0, "heading": 0, "moving": False}


class AwayRuleTests(unittest.TestCase):
    def test_an_away_player_keeps_their_seat_score_and_pull(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada, chase=True)
        book.record_shakes(bea, 6)
        self.assertEqual(book.set_away(bea, True), code)
        row = {player["name"]: player for player in book.snapshot(code, ada)["players"]}["Bea"]
        self.assertTrue(row["away"])
        self.assertEqual((row["seat"], row["shakes"]), (1, 6))
        self.assertTrue(row["chased"])

    def test_resume_counts_on_from_the_phone_total_it_comes_back_with(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        book.start(ada, chase=True)
        book.record_shakes(ada, 5)
        book.set_away(ada, True)
        book.resume(ada, 0)
        book.record_shakes(ada, 3)
        players = book.snapshot(code, ada)["players"]
        self.assertEqual(players[0]["shakes"], 8)
        self.assertFalse(players[0]["away"])

    def test_shakes_from_the_gap_do_not_count(self) -> None:
        book = LobbyBook(chase_countdown=0)
        ada, code = book.create("Ada")
        book.start(ada, chase=True)
        book.record_shakes(ada, 5)
        book.resume(ada, 11)
        book.record_shakes(ada, 12)
        self.assertEqual(book.snapshot(code, ada)["players"][0]["shakes"], 6)

    def test_a_gone_seat_cannot_be_resumed(self) -> None:
        book = LobbyBook()
        ada, _ = book.create("Ada")
        book.leave(ada)
        with self.assertRaises(LobbyError):
            book.resume(ada, 0)

    def test_a_rematch_keeps_who_is_away(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        book._lobbies[code].ends_at = 0
        book.finish_if_due(code)
        book.set_away(bea, True)
        new_code = book.rematch(ada)
        self.assertTrue(book.is_away(bea))
        self.assertEqual(book.code_of(bea), new_code)


class CountdownTests(unittest.TestCase):
    def test_a_chase_opens_after_the_countdown_and_ignores_early_shakes(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada, chase=True)
        lobby = book._lobbies[code]
        self.assertAlmostEqual(lobby.opens_at - time.time(), CHASE_COUNTDOWN_SECONDS, places=1)
        book.record_shakes(ada, 4)
        self.assertEqual(book.snapshot(code, ada)["players"][0]["shakes"], 0)
        self.assertIsNone(book.robot_round()["target"])
        lobby.opens_at = time.time() - 0.1
        lobby.pull_at = lobby.opens_at
        book.record_shakes(ada, 4)
        self.assertEqual(book.snapshot(code, ada)["players"][0]["shakes"], 4)

    def test_the_shake_contest_has_no_countdown(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.start(ada)
        snapshot = book.snapshot(code, ada)
        self.assertLessEqual(snapshot["opens_at"], int(time.time() * 1000) + 1)
        book.record_shakes(ada, 2)
        self.assertEqual(book.snapshot(code, ada)["players"][0]["shakes"], 2)


class PhoneSession:
    def __init__(self, socket) -> None:
        self.socket = socket

    async def until(self, check, seconds: float = 3) -> dict:
        async def wait() -> dict:
            while True:
                message = await self.socket.receive_json()
                if check(message):
                    return message

        return await asyncio.wait_for(wait(), seconds)


class ReconnectEndpointTests(AioHTTPTestCase):
    async def get_application(self):
        return create_app("secret", chase_countdown=0, reconnect_grace=0.5)

    async def phone(self) -> PhoneSession:
        session = PhoneSession(await self.client.ws_connect("/ws"))
        await session.until(lambda m: m["type"] == "hello")
        return session

    async def create(self, name: str) -> tuple[PhoneSession, str, dict]:
        phone = await self.phone()
        await phone.socket.send_json({"type": "create", "name": name, "shaking": True})
        joined = await phone.until(lambda m: m["type"] == "joined")
        lobby = await phone.until(lambda m: m["type"] == "lobby")
        return phone, joined["player"], lobby

    async def test_a_dropped_phone_resumes_its_seat_inside_the_grace(self) -> None:
        ada, ada_seat, lobby = await self.create("Ada")
        bea = await self.phone()
        await bea.socket.send_json({"type": "join", "name": "Bea", "code": lobby["code"], "shaking": True})
        bea_seat = (await bea.until(lambda m: m["type"] == "joined"))["player"]
        await bea.socket.close()
        away = await ada.until(lambda m: m["type"] == "lobby" and any(p["away"] for p in m["players"]))
        self.assertEqual([p["name"] for p in away["players"] if p["away"]], ["Bea"])

        back = await self.phone()
        await back.socket.send_json({"type": "resume", "player": bea_seat, "total": 0})
        mine = await back.until(lambda m: m["type"] == "lobby")
        row = next(p for p in mine["players"] if p["you"])
        self.assertEqual((row["name"], row["seat"], row["away"]), ("Bea", 1, False))
        await asyncio.sleep(0.7)
        await ada.socket.send_json({"type": "start"})
        started = await ada.until(lambda m: m["type"] == "lobby" and m["started"])
        self.assertEqual(len(started["players"]), 2)
        self.assertNotEqual(ada_seat, bea_seat)
        await ada.socket.close()
        await back.socket.close()

    async def test_a_phone_that_stays_gone_is_dropped_after_the_grace(self) -> None:
        ada, _, lobby = await self.create("Ada")
        bea = await self.phone()
        await bea.socket.send_json({"type": "join", "name": "Bea", "code": lobby["code"], "shaking": True})
        bea_seat = (await bea.until(lambda m: m["type"] == "joined"))["player"]
        await bea.socket.close()
        alone = await ada.until(lambda m: m["type"] == "lobby" and len(m["players"]) == 1)
        self.assertEqual(alone["players"][0]["name"], "Ada")
        late = await self.phone()
        await late.socket.send_json({"type": "resume", "player": bea_seat, "total": 0})
        await late.until(lambda m: m["type"] == "expired")
        await ada.socket.close()
        await late.socket.close()

    async def test_a_second_tab_takes_the_seat_and_the_first_is_told(self) -> None:
        first, seat, _ = await self.create("Ada")
        second = await self.phone()
        await second.socket.send_json({"type": "resume", "player": seat, "total": 0})
        await first.until(lambda m: m["type"] == "replaced")
        mine = await second.until(lambda m: m["type"] == "lobby")
        self.assertTrue(mine["creator"])
        self.assertFalse(mine["players"][0]["away"])
        await second.socket.close()

    async def test_leaving_drops_the_seat_at_once(self) -> None:
        ada, _, lobby = await self.create("Ada")
        bea = await self.phone()
        await bea.socket.send_json({"type": "join", "name": "Bea", "code": lobby["code"], "shaking": True})
        await bea.until(lambda m: m["type"] == "joined")
        await bea.socket.send_json({"type": "leave"})
        alone = await ada.until(lambda m: m["type"] == "lobby" and len(m["players"]) == 1)
        self.assertFalse(alone["players"][0]["away"])
        await ada.socket.close()
        await bea.socket.close()

    async def test_a_big_screen_watches_without_playing(self) -> None:
        ada, _, lobby = await self.create("Ada")
        screen = await self.phone()
        await screen.socket.send_json({"type": "watch", "code": lobby["code"].lower()})
        seen = await screen.until(lambda m: m["type"] == "lobby")
        self.assertEqual(len(seen["players"]), 1)
        self.assertFalse(seen["creator"])
        self.assertFalse(seen["players"][0]["you"])
        await ada.socket.send_json({"type": "start"})
        started = await screen.until(lambda m: m["type"] == "lobby" and m["started"])
        self.assertFalse(started["chase"])

        ada_lobby = await ada.until(lambda m: m["type"] == "lobby" and m["started"])
        self.assertEqual(ada_lobby["code"], lobby["code"])
        await ada.socket.send_json({"type": "leave"})
        await screen.until(lambda m: m["type"] == "closed")
        await ada.socket.close()
        await screen.socket.close()

    async def test_a_big_screen_follows_the_rematch(self) -> None:
        ada, _, lobby = await self.create("Ada")
        screen = await self.phone()
        await screen.socket.send_json({"type": "watch", "code": lobby["code"]})
        await screen.until(lambda m: m["type"] == "lobby")
        await ada.socket.send_json({"type": "start"})
        await ada.until(lambda m: m["type"] == "lobby" and m["started"])
        self.app["book"]._lobbies[lobby["code"]].ends_at = 0
        self.app["book"].finish_if_due(lobby["code"])
        await ada.socket.send_json({"type": "rematch"})
        rematch = await screen.until(lambda m: m["type"] == "lobby" and m["code"] != lobby["code"])
        self.assertFalse(rematch["started"])
        await ada.socket.close()
        await screen.socket.close()

    async def test_an_unknown_code_is_refused_to_a_screen(self) -> None:
        screen = await self.phone()
        await screen.socket.send_json({"type": "watch", "code": "ZZZZ"})
        refused = await screen.until(lambda m: m["type"] == "error")
        self.assertEqual(refused["message"], "No lobby with that code.")
        await screen.socket.close()

    async def test_the_screen_and_arena_script_are_served(self) -> None:
        page = await self.client.get("/screen")
        self.assertEqual(page.status, 200)
        self.assertEqual(await page.text(), SCREEN)
        script = await self.client.get("/arena.js")
        self.assertEqual(script.status, 200)
        self.assertEqual(script.content_type, "application/javascript")
        self.assertEqual(await script.text(), ARENA_JS)


if __name__ == "__main__":
    unittest.main()
