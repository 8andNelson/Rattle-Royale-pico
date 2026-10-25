"""Open lobbies. A lobby holds a code and up to eight named players.

Each player gets a seat on a circle. Seats pack until the round starts, then
lock, and each seat keeps the angle it had at the start. The creator can start
a 20-second shake game. The highest shake count wins.
"""

import secrets
import time
from dataclasses import dataclass

MAX_PLAYERS = 8
ROUND_SECONDS = 20
MAX_SHAKE_JUMP = 12
SCORE_GRACE_SECONDS = 0.5
CODE_LENGTH = 4
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class LobbyError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class Player:
    player_id: str
    name: str
    shakes: int = 0
    accepted_shakes: int = 0
    seat: int = 0
    angle: float | None = None


@dataclass
class Lobby:
    code: str
    creator_id: str
    players: list[Player]
    started: bool = False
    finished: bool = False
    ends_at: float | None = None


class LobbyBook:
    def __init__(self) -> None:
        self._lobbies: dict[str, Lobby] = {}
        self._membership: dict[str, str] = {}

    def create(self, name: str) -> tuple[str, str]:
        cleaned = clean_name(name)
        code = self._new_code()
        player_id = secrets.token_hex(8)
        self._lobbies[code] = Lobby(code, player_id, [Player(player_id, cleaned, seat=0)])
        self._membership[player_id] = code
        return player_id, code

    def join(self, code: str, name: str) -> tuple[str, str]:
        cleaned_name = clean_name(name)
        cleaned_code = clean_code(code)
        lobby = self._lobbies.get(cleaned_code)
        if lobby is None:
            raise LobbyError("No lobby with that code.")
        if lobby.started:
            raise LobbyError("This game has already started.")
        if len(lobby.players) >= MAX_PLAYERS:
            raise LobbyError("This lobby is full.")
        if any(player.name.casefold() == cleaned_name.casefold() for player in lobby.players):
            raise LobbyError("That name is already in this lobby.")
        player_id = secrets.token_hex(8)
        lobby.players.append(Player(player_id, cleaned_name, seat=len(lobby.players)))
        self._membership[player_id] = cleaned_code
        return player_id, cleaned_code

    def leave(self, player_id: str) -> str | None:
        """Remove a player. Returns the code when the lobby still has someone."""
        code = self._membership.pop(player_id, None)
        if code is None:
            return None
        lobby = self._lobbies[code]
        lobby.players = [player for player in lobby.players if player.player_id != player_id]
        if not lobby.players:
            del self._lobbies[code]
            return None
        if not lobby.started:
            for index, player in enumerate(lobby.players):
                player.seat = index
        if lobby.creator_id == player_id:
            lobby.creator_id = lobby.players[0].player_id
        return code

    def start(self, player_id: str) -> str:
        lobby = self._lobby_for(player_id)
        if player_id != lobby.creator_id:
            raise LobbyError("Only the creator can start.")
        if lobby.started:
            raise LobbyError("The game has already started.")
        count = len(lobby.players)
        for player in lobby.players:
            player.angle = 360 * player.seat / count
        lobby.started = True
        lobby.ends_at = time.time() + ROUND_SECONDS
        return lobby.code

    def record_shakes(self, player_id: str, total: object) -> tuple[str, bool]:
        """Apply a phone's running shake total. Score moves only during the game."""
        lobby = self._lobby_for(player_id)
        if not lobby.started or lobby.finished:
            return lobby.code, False
        if lobby.ends_at is not None and time.time() >= lobby.ends_at + SCORE_GRACE_SECONDS:
            lobby.finished = True
            return lobby.code, True
        if type(total) is not int or total < 0:
            raise LobbyError("That shake total could not be read.")
        player = next(player for player in lobby.players if player.player_id == player_id)
        if total <= player.accepted_shakes:
            return lobby.code, False
        increase = total - player.accepted_shakes
        if increase > MAX_SHAKE_JUMP:
            return lobby.code, False
        player.accepted_shakes = total
        player.shakes += increase
        return lobby.code, True

    def deadline(self, code: str) -> float | None:
        lobby = self._lobbies.get(code)
        if lobby is None or lobby.finished:
            return None
        return lobby.ends_at + SCORE_GRACE_SECONDS

    def finish_if_due(self, code: str) -> bool:
        lobby = self._lobbies.get(code)
        if lobby is None or not lobby.started or lobby.finished:
            return False
        if lobby.ends_at is None or time.time() < lobby.ends_at + SCORE_GRACE_SECONDS:
            return False
        lobby.finished = True
        return True

    def member_ids(self, code: str) -> list[str]:
        lobby = self._lobbies.get(code)
        if lobby is None:
            return []
        return [player.player_id for player in lobby.players]

    def snapshot(self, code: str, viewer_id: str) -> dict:
        lobby = self._lobbies[code]
        return {
            "type": "lobby",
            "code": lobby.code,
            "max": MAX_PLAYERS,
            "started": lobby.started,
            "finished": lobby.finished,
            "ends_at": None if lobby.ends_at is None else int(lobby.ends_at * 1000),
            "winners": winner_names(lobby) if lobby.finished else [],
            "creator": viewer_id == lobby.creator_id,
            "players": [
                player_snapshot(player, viewer_id, lobby.started) for player in lobby.players
            ],
        }

    def _lobby_for(self, player_id: str) -> Lobby:
        code = self._membership.get(player_id)
        if code is None:
            raise LobbyError("You are not in a lobby.")
        return self._lobbies[code]

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._lobbies:
                return code


def player_snapshot(player: Player, viewer_id: str, started: bool) -> dict:
    entry = {
        "name": player.name,
        "you": player.player_id == viewer_id,
        "shakes": player.shakes,
        "seat": player.seat,
    }
    if started:
        entry["angle"] = player.angle
    return entry


def winner_names(lobby: Lobby) -> list[str]:
    best = max(player.shakes for player in lobby.players)
    return [player.name for player in lobby.players if player.shakes == best]


def clean_name(name: object) -> str:
    if not isinstance(name, str):
        raise LobbyError("Enter a name.")
    cleaned = " ".join(name.split())
    if not cleaned:
        raise LobbyError("Enter a name.")
    if len(cleaned) > 20:
        raise LobbyError("Name is too long.")
    return cleaned


def clean_code(code: object) -> str:
    if not isinstance(code, str):
        raise LobbyError("Enter a lobby code.")
    cleaned = "".join(code.split()).upper()
    if not cleaned:
        raise LobbyError("Enter a lobby code.")
    return cleaned
