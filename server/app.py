"""Phone connection, lobbies, and a 20-second shake game.

A phone can create or join a lobby of up to eight players. Each player gets a
seat and a floor mark. The creator starts the game. Shakes add to that
player's score until the timer ends, and fading pull shows who the robot
would chase.

A phone that joins gets a private seat token. If its connection drops, the
player is marked away and keeps the seat for RECONNECT_GRACE_SECONDS. A phone
that sends that token back in time resumes the seat. A second tab with the
same token takes the seat over and the first tab is told it was replaced.

A big screen at /screen watches one lobby without playing in it.
"""

import asyncio
import json
import logging
import time

from aiohttp import ClientConnectionError, WSMsgType, web

from server.arduino_bridge import Bridge
from server.lobby import PULL_TICK_SECONDS, LobbyBook, LobbyError
from server.pages import ARENA_JS, PAGE, SCREEN
from server.pico_link import PicoLink

HOST = "0.0.0.0"
PORT = 8080
RECONNECT_GRACE_SECONDS = 15.0

log = logging.getLogger(__name__)


def create_app(
    robot_token: str | None = None,
    chase_countdown: float | None = None,
    reconnect_grace: float = RECONNECT_GRACE_SECONDS,
) -> web.Application:
    app = web.Application()
    app["book"] = LobbyBook() if chase_countdown is None else LobbyBook(chase_countdown=chase_countdown)
    app["sockets"] = {}
    app["watchers"] = {}
    app["drop_tasks"] = {}
    app["reconnect_grace"] = reconnect_grace
    app["bridge"] = Bridge()
    app["robot"] = PicoLink(robot_token)
    app.on_startup.append(start_watch)
    app.on_cleanup.append(stop_watch)
    app.on_cleanup.append(close_bridge)
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/screen", screen)
    app.router.add_get("/arena.js", arena_js)
    app.router.add_post("/api/robot", robot_poll)
    app.router.add_get("/api/robot/status", robot_status)
    app.router.add_post("/api/robot/test", robot_test)
    return app


async def close_bridge(app: web.Application) -> None:
    app["bridge"].close()


async def index(_request: web.Request) -> web.Response:
    return web.Response(text=PAGE, content_type="text/html", charset="utf-8")


async def screen(_request: web.Request) -> web.Response:
    return web.Response(text=SCREEN, content_type="text/html", charset="utf-8")


async def arena_js(_request: web.Request) -> web.Response:
    return web.Response(text=ARENA_JS, content_type="application/javascript", charset="utf-8")


async def websocket(request: web.Request) -> web.WebSocketResponse:
    socket = web.WebSocketResponse(heartbeat=20)
    await socket.prepare(request)
    peer = request.remote or "unknown"
    player_id: str | None = None
    log.info("phone connected from %s", peer)
    try:
        await socket.send_str(json.dumps({"type": "hello"}))
        async for message in socket:
            if message.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
            if message.type != WSMsgType.TEXT:
                continue
            player_id = await handle_text(request.app, socket, player_id, message.data)
    finally:
        unwatch(request.app, socket)
        if player_id is not None and request.app["sockets"].get(player_id) is socket:
            await mark_away(request.app, player_id)
        log.info("phone disconnected from %s", peer)
    return socket


async def handle_text(app: web.Application, socket: web.WebSocketResponse, player_id: str | None, raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        await send_error(socket, "That message could not be read.")
        return player_id
    if not isinstance(payload, dict):
        await send_error(socket, "That message could not be read.")
        return player_id

    kind = payload.get("type")
    book: LobbyBook = app["book"]
    try:
        if kind in ("create", "join"):
            if payload.get("shaking") is not True:
                raise LobbyError("Enable shaking before joining a lobby.")
            if kind == "create":
                new_id, code = book.create(payload.get("name"))
            else:
                new_id, code = book.join(payload.get("code"), payload.get("name"))
            app["sockets"][new_id] = socket
            previous = player_id
            player_id = new_id
            if previous is not None:
                await drop_player(app, previous)
            log.info("player %s entered lobby %s", player_id, code)
            await socket.send_str(json.dumps({"type": "joined", "player": player_id}))
            await broadcast(app, code)
        elif kind == "resume":
            resumed = payload.get("player")
            if not isinstance(resumed, str) or book.code_of(resumed) is None:
                await socket.send_str(json.dumps({"type": "expired"}))
                return player_id
            if player_id is not None and player_id != resumed:
                await drop_player(app, player_id)
            code = book.resume(resumed, payload.get("total"))
            cancel_drop(app, resumed)
            older = app["sockets"].get(resumed)
            app["sockets"][resumed] = socket
            if older is not None and older is not socket and not older.closed:
                await older.send_str(json.dumps({"type": "replaced"}))
                await older.close()
            player_id = resumed
            log.info("player %s resumed in lobby %s", player_id, code)
            await broadcast(app, code)
        elif kind == "watch":
            watched = payload.get("code")
            watched = watched.strip().upper() if isinstance(watched, str) else ""
            if watched not in book.codes():
                raise LobbyError("No lobby with that code.")
            watch(app, socket, watched)
            await broadcast(app, watched)
        elif kind == "start":
            if player_id is None:
                raise LobbyError("You are not in a lobby.")
            book.check_start(player_id)
            robot: PicoLink = app["robot"]
            chase = robot.online()
            if chase and book.robot_round() is not None:
                raise LobbyError("The robot is busy with another lobby's chase.")
            if chase and robot.halted:
                raise LobbyError("The robot is stopped. Resume it first.")
            if chase and not robot.at_home():
                raise LobbyError("The robot is not on the center mark yet.")
            code = book.start(player_id, chase=chase)
            log.info("lobby %s started%s", code, " as a chase" if chase else "")
            await broadcast(app, code)
            app.setdefault("round_tasks", {})[code] = asyncio.create_task(finish_when_due(app, code))
            app.setdefault("pull_tasks", {})[code] = asyncio.create_task(fade_pull(app, code))
        elif kind == "rematch":
            if player_id is None:
                raise LobbyError("You are not in a lobby.")
            old_code = book.code_of(player_id)
            code = book.rematch(player_id)
            log.info("rematch opened as lobby %s", code)
            if old_code in app["watchers"]:
                app["watchers"][code] = app["watchers"].pop(old_code)
            await broadcast(app, code)
        elif kind == "shakes":
            if player_id is None:
                raise LobbyError("You are not in a lobby.")
            code, changed = book.record_shakes(player_id, payload.get("total"))
            if changed:
                await broadcast(app, code)
        elif kind == "robot_home":
            if player_id is None:
                raise LobbyError("You are not in a lobby.")
            book.check_start(player_id)
            if book.robot_round() is not None:
                raise LobbyError("The robot is in a chase right now.")
            app["robot"].request_reset()
            log.info("robot pose reset to the center")
            await broadcast_all(app)
        elif kind == "stop_robot":
            if player_id is None or not book.is_creator(player_id):
                raise LobbyError("Only a lobby creator can stop the robot.")
            current = book.robot_round()
            if current is not None and current["code"] != book.code_of(player_id):
                raise LobbyError("Only the creator of the running chase can stop it.")
            app["robot"].halt()
            log.info("robot stopped by a host")
            if current is not None and book.stop_chase(current["code"]):
                log.info("lobby %s finished because the robot was stopped", current["code"])
            await broadcast_all(app)
        elif kind == "resume_robot":
            if player_id is None or not book.is_creator(player_id):
                raise LobbyError("Only a lobby creator can resume the robot.")
            app["robot"].resume()
            log.info("robot resumed")
            await broadcast_all(app)
        elif kind == "leave":
            if player_id is not None:
                cancel_drop(app, player_id)
                await drop_player(app, player_id)
                player_id = None
            await socket.send_str(json.dumps({"type": "left"}))
        else:
            await send_error(socket, "That request was not recognized.")
    except LobbyError as error:
        await send_error(socket, error.message)
    return player_id


def robot_link(request: web.Request) -> PicoLink:
    robot: PicoLink = request.app["robot"]
    if not robot.enabled:
        raise web.HTTPServiceUnavailable(text="The robot link is off. Set RATTLE_ROBOT_TOKEN.")
    if not robot.authorized(request.headers.get("Authorization")):
        raise web.HTTPUnauthorized(text="Wrong robot token.")
    return robot


async def read_json(request: web.Request) -> object:
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text="That body could not be read.")


async def robot_poll(request: web.Request) -> web.Response:
    robot = robot_link(request)
    app = request.app
    book: LobbyBook = app["book"]
    order, arrival = robot.poll(book, await read_json(request))
    if arrival is not None:
        log.info("robot reached seat %s in lobby %s", arrival["seat"], arrival["round"])
        if arrival["won"]:
            log.info("lobby %s finished by arrival", arrival["round"])
            order = robot.order(book)
            await broadcast(app, arrival["round"])
    await robot_changed(app)
    return web.json_response(order)


async def robot_changed(app: web.Application) -> None:
    """Every lobby hears when the robot comes, goes, or gets home. The open
    chase also hears every new pose."""
    robot: PicoLink = app["robot"]
    book: LobbyBook = app["book"]
    state = (robot.online(), robot.at_home())
    if state != app.get("robot_state"):
        if state[0] != (app.get("robot_state") or (False,))[0]:
            log.info("robot %s", "online" if state[0] else "offline")
        app["robot_state"] = state
        await broadcast_all(app)
        return
    current = book.robot_round()
    if current is not None and robot.pose != app.get("robot_pose"):
        app["robot_pose"] = robot.pose
        await broadcast(app, current["code"])


async def watch_robot(app: web.Application) -> None:
    """Catch the robot going quiet, which no poll will report."""
    while True:
        await asyncio.sleep(1)
        await robot_changed(app)


async def start_watch(app: web.Application) -> None:
    app["robot_watch"] = asyncio.create_task(watch_robot(app))


async def stop_watch(app: web.Application) -> None:
    app["robot_watch"].cancel()
    try:
        await app["robot_watch"]
    except asyncio.CancelledError:
        pass


async def robot_status(request: web.Request) -> web.Response:
    robot = robot_link(request)
    return web.json_response(robot.status(request.app["book"]))


async def robot_test(request: web.Request) -> web.Response:
    """Send the robot to a point when no round is open, or clear that point."""
    robot = robot_link(request)
    try:
        robot.set_test_point(await read_json(request))
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error))
    return web.json_response(robot.status(request.app["book"]))


async def finish_when_due(app: web.Application, code: str) -> None:
    book: LobbyBook = app["book"]
    while True:
        deadline = book.deadline(code)
        if deadline is None:
            return
        delay = deadline - time.time()
        if delay <= 0:
            break
        await asyncio.sleep(delay)
    if book.finish_if_due(code):
        log.info("lobby %s finished", code)
        await broadcast(app, code)
    app.setdefault("round_tasks", {}).pop(code, None)


async def fade_pull(app: web.Application, code: str) -> None:
    book: LobbyBook = app["book"]
    try:
        while True:
            await asyncio.sleep(PULL_TICK_SECONDS)
            if not book.pull_round_open(code):
                return
            if book.decay_pull(code):
                await broadcast(app, code)
    finally:
        app.setdefault("pull_tasks", {}).pop(code, None)


async def drop_player(app: web.Application, player_id: str) -> None:
    app["sockets"].pop(player_id, None)
    code = app["book"].code_of(player_id)
    still_open = app["book"].leave(player_id)
    if still_open is not None:
        await broadcast(app, still_open)
    elif code is not None:
        await send_watchers(app, code, None)
        app["watchers"].pop(code, None)


async def mark_away(app: web.Application, player_id: str) -> None:
    """The phone's socket closed. Hold the seat for the grace, then drop it."""
    app["sockets"].pop(player_id, None)
    code = app["book"].set_away(player_id, True)
    if code is None:
        return
    log.info("player %s is away from lobby %s", player_id, code)
    cancel_drop(app, player_id)
    app["drop_tasks"][player_id] = asyncio.create_task(drop_when_gone(app, player_id))
    await broadcast(app, code)


async def drop_when_gone(app: web.Application, player_id: str) -> None:
    await asyncio.sleep(app["reconnect_grace"])
    app["drop_tasks"].pop(player_id, None)
    if player_id not in app["sockets"] and app["book"].is_away(player_id):
        log.info("player %s did not come back", player_id)
        await drop_player(app, player_id)


def cancel_drop(app: web.Application, player_id: str) -> None:
    task = app["drop_tasks"].pop(player_id, None)
    if task is not None:
        task.cancel()


def watch(app: web.Application, socket: web.WebSocketResponse, code: str) -> None:
    unwatch(app, socket)
    app["watchers"].setdefault(code, set()).add(socket)


def unwatch(app: web.Application, socket: web.WebSocketResponse) -> None:
    for code in list(app["watchers"]):
        app["watchers"][code].discard(socket)
        if not app["watchers"][code]:
            del app["watchers"][code]


async def send_watchers(app: web.Application, code: str, snapshot: dict | None) -> None:
    """Big screens see the lobby as nobody in particular. None means it closed."""
    message = json.dumps(snapshot if snapshot is not None else {"type": "closed", "code": code})
    for watcher in list(app["watchers"].get(code, ())):
        if watcher.closed:
            continue
        try:
            await watcher.send_str(message)
        except ClientConnectionError:
            continue


async def broadcast(app: web.Application, code: str) -> None:
    book: LobbyBook = app["book"]
    sockets: dict[str, web.WebSocketResponse] = app["sockets"]
    robot = app["robot"].summary()
    for player_id in book.member_ids(code):
        destination = sockets.get(player_id)
        if destination is None or destination.closed:
            continue
        snapshot = book.snapshot(code, player_id)
        snapshot["robot"] = robot
        try:
            await destination.send_str(json.dumps(snapshot))
        except ClientConnectionError:
            continue
    if app["watchers"].get(code) and code in book.codes():
        snapshot = book.snapshot(code, None)
        snapshot["robot"] = robot
        await send_watchers(app, code, snapshot)


async def broadcast_all(app: web.Application) -> None:
    for code in app["book"].codes():
        await broadcast(app, code)


async def send_error(socket: web.WebSocketResponse, message: str) -> None:
    if not socket.closed:
        await socket.send_str(json.dumps({"type": "error", "message": message}))
