"""Seat assignment for a lobby."""

import unittest

from server.lobby import MAX_PLAYERS, LobbyBook, LobbyError


def seats(book: LobbyBook, code: str, viewer_id: str) -> dict[str, dict]:
    snapshot = book.snapshot(code, viewer_id)
    return {player["name"]: player for player in snapshot["players"]}


class SeatTests(unittest.TestCase):
    def test_creator_is_seat_zero_and_the_next_player_is_seat_one(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        book.join(code, "Bea")
        players = seats(book, code, ada)
        self.assertEqual(players["Ada"]["seat"], 0)
        self.assertEqual(players["Bea"]["seat"], 1)
        self.assertNotIn("angle", players["Ada"])

    def test_leave_before_start_packs_later_seats(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.join(code, "Cam")
        book.leave(bea)
        players = seats(book, code, ada)
        self.assertEqual(list(players), ["Ada", "Cam"])
        self.assertEqual(players["Ada"]["seat"], 0)
        self.assertEqual(players["Cam"]["seat"], 1)

    def test_start_stores_angles_and_a_later_leave_keeps_them(self) -> None:
        book = LobbyBook()
        ada, code = book.create("Ada")
        bea, _ = book.join(code, "Bea")
        book.start(ada)
        players = seats(book, code, bea)
        self.assertEqual(players["Ada"]["angle"], 0)
        self.assertEqual(players["Bea"]["angle"], 180)
        book.leave(ada)
        players = seats(book, code, bea)
        self.assertEqual(list(players), ["Bea"])
        self.assertEqual(players["Bea"]["seat"], 1)
        self.assertEqual(players["Bea"]["angle"], 180)

    def test_eighth_player_is_accepted_and_ninth_is_refused(self) -> None:
        book = LobbyBook()
        creator, code = book.create("P0")
        for number in range(1, MAX_PLAYERS):
            book.join(code, f"P{number}")
        players = seats(book, code, creator)
        self.assertEqual(len(players), MAX_PLAYERS)
        self.assertEqual(players["P7"]["seat"], 7)
        with self.assertRaises(LobbyError) as caught:
            book.join(code, "P8")
        self.assertEqual(caught.exception.message, "This lobby is full.")


if __name__ == "__main__":
    unittest.main()
