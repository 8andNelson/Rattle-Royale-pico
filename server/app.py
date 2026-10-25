"""Phone connection and lobbies.

A phone opens the page, holds a WebSocket, and can create or join a lobby
of up to eight players. Seats, scoring, and the round are not part of this step.
"""

import json
import logging

from aiohttp import WSMsgType, web

from server.lobby import LobbyBook, LobbyError

HOST = "0.0.0.0"
PORT = 8080

log = logging.getLogger(__name__)

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rattle Royale</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      min-height: 100dvh;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #111;
      color: #f4f4f4;
      font-family: sans-serif;
    }
    main { width: min(24rem, 100%); padding: 1.5rem; box-sizing: border-box; }
    #status { font-size: 1.1rem; margin: 0 0 1.25rem; color: #aaa; text-align: center; }
    label { display: block; color: #ccc; }
    input, button { font: inherit; font-size: 1.1rem; }
    input {
      width: 100%;
      box-sizing: border-box;
      margin: 0.35rem 0 0.9rem;
      padding: 0.75rem;
    }
    button {
      width: 100%;
      margin: 0 0 0.9rem;
      padding: 0.85rem;
    }
    #error { min-height: 1.2rem; margin: 0; color: #ffb4b4; }
    #lobby { text-align: center; }
    #lobby-code {
      font-size: 3rem;
      letter-spacing: 0.18rem;
      margin: 0 0 0.25rem;
    }
    #lobby-count { margin: 0 0 1rem; color: #aaa; }
    #players { list-style: none; padding: 0; margin: 0 0 1.25rem; font-size: 1.35rem; }
    #players li { padding: 0.35rem 0; }
  </style>
</head>
<body>
  <main>
    <p id="status">Connecting</p>
    <section id="join">
      <label for="name">Name</label>
      <input id="name" maxlength="20" autocomplete="nickname" enterkeyhint="done">
      <button id="create" type="button">Create lobby</button>
      <label for="code">Lobby code</label>
      <input id="code" maxlength="4" autocapitalize="characters" autocomplete="off" enterkeyhint="go">
      <button id="join-lobby" type="button">Join lobby</button>
      <p id="error"></p>
    </section>
    <section id="lobby" hidden>
      <p id="lobby-code"></p>
      <p id="lobby-count"></p>
      <ul id="players"></ul>
      <button id="leave" type="button">Leave lobby</button>
    </section>
  </main>
  <script>
    const statusEl = document.getElementById("status");
    const joinEl = document.getElementById("join");
    const lobbyEl = document.getElementById("lobby");
    const errorEl = document.getElementById("error");
    const nameEl = document.getElementById("name");
    const codeEl = document.getElementById("code");

    let socket = null;
    let inLobby = false;
    let retryTimer = null;

    function showJoin() {
      lobbyEl.hidden = true;
      joinEl.hidden = false;
    }

    function showLobby(message) {
      inLobby = true;
      errorEl.textContent = "";
      joinEl.hidden = true;
      lobbyEl.hidden = false;
      document.getElementById("lobby-code").textContent = message.code;
      document.getElementById("lobby-count").textContent =
        message.players.length + " of " + message.max;
      const list = document.getElementById("players");
      list.replaceChildren();
      message.players.forEach((player) => {
        const item = document.createElement("li");
        item.textContent = player.you ? player.name + " (you)" : player.name;
        list.append(item);
      });
    }

    function send(message) {
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        errorEl.textContent = "Still connecting.";
        return;
      }
      errorEl.textContent = "";
      socket.send(JSON.stringify(message));
    }

    document.getElementById("create").addEventListener("click", () => {
      send({ type: "create", name: nameEl.value });
    });
    document.getElementById("join-lobby").addEventListener("click", () => {
      send({ type: "join", name: nameEl.value, code: codeEl.value });
    });
    document.getElementById("leave").addEventListener("click", () => {
      send({ type: "leave" });
    });
    nameEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        send({ type: "create", name: nameEl.value });
      }
    });
    codeEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        send({ type: "join", name: nameEl.value, code: codeEl.value });
      }
    });

    function scheduleReconnect() {
      statusEl.textContent = "Reconnecting";
      if (retryTimer !== null) {
        return;
      }
      retryTimer = setTimeout(() => {
        retryTimer = null;
        connect();
      }, 1000);
    }

    function connect() {
      statusEl.textContent = "Connecting";
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const next = new WebSocket(protocol + "//" + location.host + "/ws");
      socket = next;

      next.addEventListener("message", (event) => {
        if (next !== socket) {
          return;
        }
        let message;
        try {
          message = JSON.parse(event.data);
        } catch (error) {
          return;
        }
        if (message.type === "hello") {
          statusEl.textContent = "Connected";
        } else if (message.type === "lobby") {
          showLobby(message);
        } else if (message.type === "left") {
          inLobby = false;
          showJoin();
        } else if (message.type === "error") {
          errorEl.textContent = message.message || "Something went wrong.";
        }
      });

      next.addEventListener("close", () => {
        if (next !== socket) {
          return;
        }
        if (inLobby) {
          inLobby = false;
          showJoin();
          errorEl.textContent = "Connection lost. Join the lobby again.";
        }
        scheduleReconnect();
      });

      next.addEventListener("error", () => {
        if (next === socket) {
          statusEl.textContent = "Reconnecting";
        }
      });
    }

    connect();
  </script>
</body>
</html>
"""


def create_app() -> web.Application:
    app = web.Application()
    app["book"] = LobbyBook()
    app["sockets"] = {}
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    return app


async def index(_request: web.Request) -> web.Response:
    return web.Response(text=PAGE, content_type="text/html", charset="utf-8")


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
        if player_id is not None:
            await drop_player(request.app, player_id)
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
            await broadcast(app, code)
        elif kind == "leave":
            if player_id is not None:
                await drop_player(app, player_id)
                player_id = None
            await socket.send_str(json.dumps({"type": "left"}))
        else:
            await send_error(socket, "That request was not recognized.")
    except LobbyError as error:
        await send_error(socket, error.message)
    return player_id


async def drop_player(app: web.Application, player_id: str) -> None:
    app["sockets"].pop(player_id, None)
    code = app["book"].leave(player_id)
    if code is not None:
        await broadcast(app, code)


async def broadcast(app: web.Application, code: str) -> None:
    book: LobbyBook = app["book"]
    sockets: dict[str, web.WebSocketResponse] = app["sockets"]
    for player_id in book.member_ids(code):
        destination = sockets.get(player_id)
        if destination is None or destination.closed:
            continue
        await destination.send_str(json.dumps(book.snapshot(code, player_id)))


async def send_error(socket: web.WebSocketResponse, message: str) -> None:
    if not socket.closed:
        await socket.send_str(json.dumps({"type": "error", "message": message}))
