"""Open lobbies. A lobby holds a code and up to eight named players.

Each player gets a seat on a circle. Seats pack until the round starts, then
lock, and each seat keeps the angle it had at the start. The creator can start
a 20-second shake game. The highest shake count wins. During the round, each
accepted shake also adds pull that fades, and the chase target is the player
the robot would follow.

When the robot is online at the start, the round is a chase instead: it runs
longer, the robot reaching a mark wins for that seat, and at the clock the
player being chased wins. Nobody chased at the clock is a draw.
"""

import secrets
import time
from dataclasses import dataclass

MAX_PLAYERS = 8
ROUND_SECONDS = 20
CHASE_ROUND_SECONDS = 60
MAX_SHAKE_JUMP = 12
SCORE_GRACE_SECONDS = 0.5
PULL_HALF_LIFE_SECONDS = 2.5
PULL_TICK_SECONDS = 0.25
PULL_MARGIN_FRACTION = 0.15
PULL_MARGIN_ABSOLUTE = 1.0
PULL_FLOOR = 0.05
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
    pull: float = 0.0


@dataclass
class Lobby:
    code: str
    creator_id: str
    players: list[Player]
    started: bool = False
    finished: bool = False
    ends_at: float | None = None
    pull_at: float | None = None
    chase_id: str | None = None
    chase: bool = False
    arrived_id: str | None = None
    winners: list[str] | None = None
    reason: str | None = None


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
        if lobby.started:
            self._retarget(lobby)
        return code

    def check_start(self, player_id: str) -> Lobby:
        lobby = self._lobby_for(player_id)
        if player_id != lobby.creator_id:
            raise LobbyError("Only the creator can start.")
        if lobby.started:
            raise LobbyError("The game has already started.")
        return lobby

    def start(self, player_id: str, chase: bool = False) -> str:
        lobby = self.check_start(player_id)
        count = len(lobby.players)
        for player in lobby.players:
            player.angle = 360 * player.seat / count
        lobby.started = True
        lobby.chase = chase
        lobby.ends_at = time.time() + (CHASE_ROUND_SECONDS if chase else ROUND_SECONDS)
        lobby.pull_at = time.time()
        lobby.chase_id = None
        return lobby.code

    def record_shakes(self, player_id: str, total: object) -> tuple[str, bool]:
        """Apply a phone's running shake total. Score moves only during the game."""
        lobby = self._lobby_for(player_id)
        if not lobby.started or lobby.finished:
            return lobby.code, False
        now = time.time()
        if lobby.ends_at is not None and now >= lobby.ends_at + SCORE_GRACE_SECONDS:
            self._finish(lobby)
            return lobby.code, True
        if type(total) is not int or total < 0:
            raise LobbyError("That shake total could not be read.")
        changed = self._decay_to(lobby, now)
        player = next(player for player in lobby.players if player.player_id == player_id)
        if total > player.accepted_shakes:
            increase = total - player.accepted_shakes
            if increase <= MAX_SHAKE_JUMP:
                player.accepted_shakes = total
                player.shakes += increase
                player.pull += increase
                changed = True
        if self._retarget(lobby):
            changed = True
        return lobby.code, changed

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
        self._finish(lobby)
        return True

    def pull_round_open(self, code: str) -> bool:
        lobby = self._lobbies.get(code)
        return lobby is not None and lobby.started and not lobby.finished

    def decay_pull(self, code: str, now: float | None = None) -> bool:
        """Fade pull up to now. Returns whether the scoreboard changed."""
        lobby = self._lobbies.get(code)
        if lobby is None or not lobby.started or lobby.finished:
            return False
        moment = time.time() if now is None else now
        if lobby.ends_at is not None:
            moment = min(moment, lobby.ends_at + SCORE_GRACE_SECONDS)
        changed = self._decay_to(lobby, moment)
        if self._retarget(lobby):
            changed = True
        return changed

    def arrive(self, code: str, seat: int, now: float | None = None) -> bool:
        """The robot reached a seat's mark. Ends an open chase with that winner."""
        lobby = self._lobbies.get(code)
        if lobby is None or not lobby.chase or not lobby.started or lobby.finished:
            return False
        player = next((player for player in lobby.players if player.seat == seat), None)
        if player is None:
            return False
        lobby.arrived_id = player.player_id
        self._finish(lobby, time.time() if now is None else now)
        return True

    def codes(self) -> list[str]:
        return list(self._lobbies)

    def robot_round(self) -> dict | None:
        """The open chase the robot follows: the one that started last."""
        rounds = [
            lobby for lobby in self._lobbies.values() if lobby.chase and lobby.started and not lobby.finished
        ]
        if not rounds:
            return None
        lobby = max(rounds, key=lambda lobby: lobby.ends_at or 0)
        chased = next((player for player in lobby.players if player.player_id == lobby.chase_id), None)
        return {
            "code": lobby.code,
            "ends_at": lobby.ends_at,
            "target": None if chased is None else {"seat": chased.seat, "name": chased.name, "angle": chased.angle},
        }

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
            "chase": lobby.chase,
            "winners": lobby.winners or [],
            "reason": lobby.reason,
            "creator": viewer_id == lobby.creator_id,
            "players": [
                player_snapshot(player, viewer_id, lobby.started, lobby.chase_id)
                for player in snapshot_players(lobby)
            ],
        }

    def _lobby_for(self, player_id: str) -> Lobby:
        code = self._membership.get(player_id)
        if code is None:
            raise LobbyError("You are not in a lobby.")
        return self._lobbies[code]

    def _decay_to(self, lobby: Lobby, now: float) -> bool:
        if lobby.pull_at is None or now <= lobby.pull_at:
            return False
        factor = 0.5 ** ((now - lobby.pull_at) / PULL_HALF_LIFE_SECONDS)
        changed = False
        for player in lobby.players:
            if player.pull <= 0:
                continue
            updated = player.pull * factor
            if updated < PULL_FLOOR:
                updated = 0.0
            if updated != player.pull:
                changed = True
            player.pull = updated
        lobby.pull_at = now
        return changed

    def _retarget(self, lobby: Lobby) -> bool:
        previous = lobby.chase_id
        current = next(
            (
                player
                for player in lobby.players
                if player.player_id == previous and player.pull > 0
            ),
            None,
        )
        leader = max(lobby.players, key=lambda player: (player.pull, -player.seat))
        if leader.pull <= 0:
            lobby.chase_id = None
        elif current is None or leader.player_id == current.player_id:
            lobby.chase_id = leader.player_id
        else:
            margin = max(PULL_MARGIN_ABSOLUTE, current.pull * PULL_MARGIN_FRACTION)
            if leader.pull >= current.pull + margin:
                lobby.chase_id = leader.player_id
            else:
                lobby.chase_id = current.player_id
        return lobby.chase_id != previous

    def _finish(self, lobby: Lobby, now: float | None = None) -> None:
        if lobby.finished or lobby.ends_at is None:
            return
        last = lobby.ends_at + SCORE_GRACE_SECONDS
        self._decay_to(lobby, last if now is None else min(now, last))
        self._retarget(lobby)
        lobby.finished = True
        lobby.winners = winner_names(lobby)
        lobby.reason = result_reason(lobby)

    def _new_code(self) -> str:
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            if code not in self._lobbies:
                return code


def snapshot_players(lobby: Lobby) -> list[Player]:
    if not lobby.started:
        return lobby.players
    return sorted(lobby.players, key=lambda player: (-player.pull, player.seat))


def player_snapshot(player: Player, viewer_id: str, started: bool, chase_id: str | None) -> dict:
    entry = {
        "name": player.name,
        "you": player.player_id == viewer_id,
        "shakes": player.shakes,
        "seat": player.seat,
    }
    if started:
        entry["angle"] = player.angle
        entry["pull"] = round(player.pull, 2)
        entry["chased"] = player.player_id == chase_id
    return entry


def winner_names(lobby: Lobby) -> list[str]:
    if lobby.chase:
        winner_id = lobby.arrived_id or lobby.chase_id
        return [player.name for player in lobby.players if player.player_id == winner_id]
    best = max(player.shakes for player in lobby.players)
    return [player.name for player in lobby.players if player.shakes == best]


def result_reason(lobby: Lobby) -> str:
    """shakes for the plain contest. arrival, clock, or draw for a chase."""
    if not lobby.chase:
        return "shakes"
    if lobby.arrived_id is not None:
        return "arrival"
    if lobby.chase_id is not None:
        return "clock"
    return "draw"


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
