"""Open lobbies. A lobby holds a code and up to eight named players."""

import secrets
from dataclasses import dataclass

MAX_PLAYERS = 8
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


@dataclass
class Lobby:
    code: str
    players: list[Player]


class LobbyBook:
    def __init__(self) -> None:
        self._lobbies: dict[str, Lobby] = {}
        self._membership: dict[str, str] = {}

    def create(self, name: str) -> tuple[str, str]:
        cleaned = clean_name(name)
        code = self._new_code()
        player_id = secrets.token_hex(8)
        self._lobbies[code] = Lobby(code, [Player(player_id, cleaned)])
        self._membership[player_id] = code
        return player_id, code

    def join(self, code: str, name: str) -> tuple[str, str]:
        cleaned_name = clean_name(name)
        cleaned_code = clean_code(code)
        lobby = self._lobbies.get(cleaned_code)
        if lobby is None:
            raise LobbyError("No lobby with that code.")
        if len(lobby.players) >= MAX_PLAYERS:
            raise LobbyError("This lobby is full.")
        if any(player.name.casefold() == cleaned_name.casefold() for player in lobby.players):
            raise LobbyError("That name is already in this lobby.")
        player_id = secrets.token_hex(8)
        lobby.players.append(Player(player_id, cleaned_name))
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
        return code

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
            "players": [
                {"name": player.name, "you": player.player_id == viewer_id}
                for player in lobby.players
            ],
        }

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._lobbies:
                return code


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
