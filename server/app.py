"""Phone connection, lobbies, and a 20-second shake game.

A phone can create or join a lobby of up to eight players. Each player gets a
seat and a floor mark. The creator starts the game. Shakes add to that
player's score until the timer ends, and fading pull shows who the robot
would chase.
"""

import asyncio
import json
import logging
import time

from aiohttp import ClientConnectionError, WSMsgType, web

from server.arduino_bridge import Bridge
from server.lobby import PULL_TICK_SECONDS, LobbyBook, LobbyError
from server.pico_link import PicoLink

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
      touch-action: manipulation;
    }
    #clock { font-size: 2.5rem; margin: 0 0 0.5rem; }
    #result { font-size: 2rem; margin: 0 0 1rem; }
    #error { min-height: 1.2rem; margin: 0; color: #ffb4b4; text-align: center; }
    #waiting { margin: 0 0 0.9rem; color: #aaa; }
    #lobby { text-align: center; }
    #lobby-code {
      font-size: 3rem;
      letter-spacing: 0.18rem;
      margin: 0 0 0.25rem;
    }
    #lobby-count { margin: 0 0 1rem; color: #aaa; }
    #your-seat { font-size: 2rem; margin: 0 0 0.25rem; }
    #your-mark { margin: 0 0 0.35rem; color: #aaa; }
    #chase { font-size: 1.25rem; margin: 0 0 1rem; }
    #round-kind, #robot-status { margin: 0 0 0.75rem; color: #aaa; }
    #arena { display: block; width: 100%; max-width: 18rem; margin: 0 auto 1rem; }
    #arena[hidden] { display: none; }
    #players { list-style: none; padding: 0; margin: 0 0 1.25rem; font-size: 1.35rem; }
    #players li { padding: 0.35rem 0; }
    #shakes { font-size: 1.6rem; margin: 0 0 0.4rem; text-align: center; }
    #shake-note { margin: 0 0 0.9rem; color: #aaa; font-size: 0.95rem; text-align: center; }
  </style>
</head>
<body>
  <main>
    <p id="status">Connecting</p>
    <p id="shakes" hidden>Shakes: 0</p>
    <button id="enable-shake" type="button">Enable shaking</button>
    <p id="shake-note">Enable shaking to create or join a lobby.</p>
    <section id="join" hidden>
      <label for="name">Name</label>
      <input id="name" maxlength="20" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" enterkeyhint="done">
      <button id="create" type="button">Create lobby</button>
      <label for="code">Lobby code</label>
      <input id="code" maxlength="4" autocomplete="off" autocorrect="off" autocapitalize="characters" spellcheck="false" enterkeyhint="go">
      <button id="join-lobby" type="button">Join lobby</button>
    </section>
    <section id="lobby" hidden>
      <p id="lobby-code"></p>
      <p id="lobby-count"></p>
      <p id="your-seat"></p>
      <p id="your-mark"></p>
      <p id="round-kind" hidden></p>
      <p id="robot-status"></p>
      <p id="chase" hidden></p>
      <svg id="arena" viewBox="-130 -130 260 260" hidden></svg>
      <ul id="players"></ul>
      <p id="clock" hidden></p>
      <p id="result" hidden></p>
      <button id="start" type="button" hidden>Start game</button>
      <button id="robot-home" type="button" hidden>The robot is on the center mark</button>
      <button id="rematch" type="button" hidden>Rematch</button>
      <p id="waiting" hidden>Waiting for the creator to start</p>
      <button id="leave" type="button">Leave lobby</button>
    </section>
    <p id="error"></p>
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
    let playing = false;
    let retryTimer = null;
    let roundEndsAt = null;
    let countdownTimer = null;

    function stopCountdown() {
      if (countdownTimer !== null) {
        clearInterval(countdownTimer);
        countdownTimer = null;
      }
    }

    function showJoin() {
      stopCountdown();
      playing = false;
      roundEndsAt = null;
      resetShakes();
      shakesEl.hidden = true;
      lobbyEl.hidden = true;
      joinEl.hidden = !shaking;
    }

    function winnerText(winners, reason) {
      if (reason === "arrival" && winners.length === 1) {
        return "The robot reached " + winners[0] + ". " + winners[0] + " wins";
      }
      if (reason === "clock" && winners.length === 1) {
        return "Time. The robot was chasing " + winners[0] + ". " + winners[0] + " wins";
      }
      if (reason === "draw") {
        return "Nobody shook. Draw";
      }
      if (!winners || winners.length === 0) {
        return "No winner";
      }
      if (winners.length === 1) {
        return winners[0] + " wins";
      }
      return "Tie: " + winners.join(", ");
    }

    function runCountdown(endsAt) {
      stopCountdown();
      const clock = document.getElementById("clock");
      function tick() {
        const left = Math.max(0, Math.ceil((endsAt - Date.now()) / 1000));
        clock.textContent = left + "s";
        if (left <= 0) {
          stopCountdown();
        }
      }
      tick();
      countdownTimer = setInterval(tick, 200);
    }

    const SVG = "http://www.w3.org/2000/svg";

    function svgEl(name, attributes) {
      const element = document.createElementNS(SVG, name);
      Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
      return element;
    }

    function robotStatusText(message) {
      const robot = message.robot;
      if (!robot || !robot.online) {
        return message.started ? "Robot offline" : "Robot offline. This will be a 20-second shake contest.";
      }
      if (message.started) {
        return "Robot online";
      }
      return robot.home ? "Robot ready on the center mark" : "Robot online, not on the center mark yet";
    }

    // Marks on a circle, seat 0 to the right, higher seats counterclockwise.
    // The robot is a triangle at its pose, pointing along its heading.
    function drawArena(message) {
      const arena = document.getElementById("arena");
      const robot = message.robot;
      const show = message.chase || (robot && robot.online && !message.started);
      arena.hidden = !show;
      if (!show) {
        return;
      }
      arena.replaceChildren();
      const scale = 100 / ((robot && robot.radius) || 250);
      arena.append(svgEl("circle", { cx: 0, cy: 0, r: 100, fill: "none", stroke: "#444", "stroke-width": 2 }));
      arena.append(svgEl("circle", { cx: 0, cy: 0, r: 5, fill: "#444" }));
      const count = message.players.length;
      message.players.forEach((player) => {
        const angle = player.angle != null ? player.angle : (360 * player.seat) / count;
        const theta = (angle * Math.PI) / 180;
        const x = 100 * Math.cos(theta);
        const y = -100 * Math.sin(theta);
        arena.append(svgEl("circle", {
          cx: x, cy: y, r: 14,
          fill: player.chased ? "#c33" : "#2a2a2a",
          stroke: player.you ? "#fff" : "#666",
          "stroke-width": player.you ? 3 : 1.5,
        }));
        const label = svgEl("text", {
          x: x, y: y + 5, "text-anchor": "middle", fill: "#f4f4f4", "font-size": 14,
        });
        label.textContent = player.seat;
        arena.append(label);
      });
      if (robot && robot.online && robot.pose) {
        const x = robot.pose.x * scale;
        const y = -robot.pose.y * scale;
        arena.append(svgEl("polygon", {
          points: "12,0 -8,-8 -8,8",
          fill: "#ffd24a",
          transform: "translate(" + x + " " + y + ") rotate(" + (-robot.pose.heading) + ")",
        }));
      }
    }

    function showLobby(message) {
      inLobby = true;
      const nowPlaying = message.started && !message.finished;
      if (nowPlaying && !playing) {
        resetShakes();
      }
      const previousEnd = roundEndsAt;
      playing = nowPlaying;
      roundEndsAt = message.started ? message.ends_at : null;
      shakesEl.hidden = !message.started;
      errorEl.textContent = "";
      joinEl.hidden = true;
      lobbyEl.hidden = false;
      document.getElementById("lobby-code").textContent = message.code;
      document.getElementById("lobby-count").textContent =
        message.players.length + " of " + message.max;
      document.getElementById("start").hidden = !(message.creator && !message.started);
      const robotOnline = Boolean(message.robot && message.robot.online);
      document.getElementById("robot-home").hidden = !(message.creator && !message.started && robotOnline);
      document.getElementById("robot-status").textContent = robotStatusText(message);
      const roundKind = document.getElementById("round-kind");
      roundKind.hidden = !message.started;
      roundKind.textContent = message.chase
        ? "Chase round. Get the robot to reach you."
        : "Shake contest. Most shakes wins.";
      drawArena(message);
      document.getElementById("rematch").hidden = !(message.creator && message.finished);
      const waiting = document.getElementById("waiting");
      waiting.hidden = message.creator || (message.started && !message.finished);
      waiting.textContent = message.finished
        ? "Waiting for the creator to start a rematch"
        : "Waiting for the creator to start";
      document.getElementById("leave").hidden = playing;
      const mine = message.players.find((player) => player.you);
      document.getElementById("your-seat").textContent = mine ? "You are seat " + mine.seat : "";
      document.getElementById("your-mark").textContent = mine ? "Stand on mark " + mine.seat : "";
      const chase = document.getElementById("chase");
      if (message.started) {
        const chased = message.players.find((player) => player.chased);
        chase.hidden = false;
        if (!chased) {
          chase.textContent = "The robot is holding still";
        } else if (chased.you) {
          chase.textContent = "The robot is coming for you";
        } else {
          chase.textContent = "The robot is chasing " + chased.name;
        }
      } else {
        chase.hidden = true;
        chase.textContent = "";
      }
      const clock = document.getElementById("clock");
      const result = document.getElementById("result");
      if (playing) {
        clock.hidden = false;
        result.hidden = true;
        result.textContent = "";
        if (countdownTimer === null || previousEnd !== message.ends_at) {
          runCountdown(message.ends_at);
        }
      } else if (message.finished) {
        if (mine) {
          shakeCount = mine.shakes;
          showShakeCount();
        }
        stopCountdown();
        clock.hidden = true;
        result.hidden = false;
        result.textContent = winnerText(message.winners, message.reason);
      } else {
        stopCountdown();
        clock.hidden = true;
        result.hidden = true;
        result.textContent = "";
      }
      const list = document.getElementById("players");
      list.replaceChildren();
      message.players.forEach((player) => {
        const item = document.createElement("li");
        const marker = player.you ? " (you)" : "";
        let text = player.name + " — seat " + player.seat + marker;
        if (message.started) {
          text += " — " + player.shakes + " — pull " + Number(player.pull).toFixed(2);
          if (player.chased) {
            text += " — chased";
          }
        }
        item.textContent = text;
        list.append(item);
      });
    }

    function send(message) {
      if ((message.type === "create" || message.type === "join") && !shaking) {
        errorEl.textContent = "Enable shaking before joining a lobby.";
        return;
      }
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        errorEl.textContent = "Still connecting.";
        return;
      }
      errorEl.textContent = "";
      socket.send(JSON.stringify(message));
    }

    document.getElementById("create").addEventListener("click", () => {
      send({ type: "create", name: nameEl.value, shaking: true });
    });
    document.getElementById("join-lobby").addEventListener("click", () => {
      send({ type: "join", name: nameEl.value, code: codeEl.value, shaking: true });
    });
    document.getElementById("start").addEventListener("click", () => {
      send({ type: "start" });
    });
    document.getElementById("rematch").addEventListener("click", () => {
      send({ type: "rematch" });
    });
    document.getElementById("robot-home").addEventListener("click", () => {
      send({ type: "robot_home" });
    });
    document.getElementById("leave").addEventListener("click", () => {
      send({ type: "leave" });
    });

    const SHAKE_THRESHOLD = 15;
    const SHAKE_GAP_MS = 150;
    const shakesEl = document.getElementById("shakes");
    const enableShakeEl = document.getElementById("enable-shake");
    const shakeNoteEl = document.getElementById("shake-note");
    let shakeCount = 0;
    let shaking = false;
    let lastShakeAt = 0;

    function resetShakes() {
      shakeCount = 0;
      lastShakeAt = 0;
      showShakeCount();
    }

    function showShakeCount() {
      shakesEl.textContent = "Shakes: " + shakeCount;
    }

    function dismissKeyboard() {
      nameEl.blur();
      codeEl.blur();
      const active = document.activeElement;
      if (active && active !== document.body && active.blur) {
        active.blur();
      }
    }

    function replaceRange(input, text) {
      const start = input.selectionStart == null ? input.value.length : input.selectionStart;
      const end = input.selectionEnd == null ? input.value.length : input.selectionEnd;
      const next = (input.value.slice(0, start) + text + input.value.slice(end)).slice(0, input.maxLength || undefined);
      input.value = next;
      const caret = Math.min(start + text.length, input.value.length);
      input.setSelectionRange(caret, caret);
    }

    function deleteRange(input, backward) {
      const start = input.selectionStart == null ? input.value.length : input.selectionStart;
      const end = input.selectionEnd == null ? input.value.length : input.selectionEnd;
      if (start !== end) {
        input.value = input.value.slice(0, start) + input.value.slice(end);
        input.setSelectionRange(start, start);
        return;
      }
      if (backward && start > 0) {
        input.value = input.value.slice(0, start - 1) + input.value.slice(end);
        input.setSelectionRange(start - 1, start - 1);
      } else if (!backward && end < input.value.length) {
        input.value = input.value.slice(0, start) + input.value.slice(end + 1);
        input.setSelectionRange(start, start);
      }
    }

    function watchTyping(input) {
      let handledByKey = false;
      input.addEventListener("pointerdown", () => {
        input.readOnly = false;
      });
      input.addEventListener("keydown", (event) => {
        if (event.metaKey || event.ctrlKey || event.altKey) {
          return;
        }
        if (event.key === "Enter") {
          event.preventDefault();
          return;
        }
        if (event.key === "Backspace" || event.key === "Delete") {
          event.preventDefault();
          handledByKey = true;
          deleteRange(input, event.key === "Backspace");
          return;
        }
        if (event.key.length === 1) {
          event.preventDefault();
          handledByKey = true;
          replaceRange(input, event.key);
        }
      });
      input.addEventListener("beforeinput", (event) => {
        if (event.inputType === "historyUndo" || event.inputType === "historyRedo" || event.inputType === "insertLineBreak") {
          event.preventDefault();
          handledByKey = false;
          return;
        }
        if (handledByKey) {
          event.preventDefault();
          handledByKey = false;
          return;
        }
        if (event.inputType === "insertText" || event.inputType === "insertFromPaste") {
          event.preventDefault();
          if (event.data) {
            replaceRange(input, event.data);
          }
          return;
        }
        if (event.inputType === "deleteContentBackward" || event.inputType === "deleteContentForward") {
          event.preventDefault();
          deleteRange(input, event.inputType === "deleteContentBackward");
        }
      });
    }

    watchTyping(nameEl);
    watchTyping(codeEl);

    function onMotion(event) {
      if (!shaking || !playing || document.visibilityState === "hidden") {
        return;
      }
      if (roundEndsAt !== null && Date.now() >= roundEndsAt) {
        return;
      }
      const reading = event.accelerationIncludingGravity;
      if (!reading || reading.x == null || reading.y == null || reading.z == null) {
        shakeNoteEl.textContent = "This phone cannot shake.";
        return;
      }
      const strength = Math.hypot(reading.x, reading.y, reading.z);
      if (strength < SHAKE_THRESHOLD) {
        return;
      }
      nameEl.readOnly = true;
      codeEl.readOnly = true;
      dismissKeyboard();
      const now = performance.now();
      if (now - lastShakeAt < SHAKE_GAP_MS) {
        return;
      }
      lastShakeAt = now;
      shakeCount += 1;
      showShakeCount();
      send({ type: "shakes", total: shakeCount });
    }

    async function enableShaking() {
      const motion = window.DeviceMotionEvent;
      if (!motion) {
        enableShakeEl.hidden = true;
        shakeNoteEl.textContent = "This phone cannot shake.";
        return;
      }
      if (typeof motion.requestPermission === "function" && !window.isSecureContext) {
        shakeNoteEl.textContent = "Open the https link to enable shaking.";
        return;
      }
      try {
        if (typeof motion.requestPermission === "function") {
          const result = await motion.requestPermission();
          if (result !== "granted") {
            shakeNoteEl.textContent = "Shaking is off.";
            return;
          }
        }
      } catch (error) {
        shakeNoteEl.textContent = "Shaking is off.";
        return;
      }
      if (shaking) {
        return;
      }
      window.addEventListener("devicemotion", onMotion);
      shaking = true;
      nameEl.readOnly = true;
      codeEl.readOnly = true;
      enableShakeEl.hidden = true;
      dismissKeyboard();
      shakeNoteEl.textContent = "Shaking is on.";
      if (!inLobby) {
        joinEl.hidden = false;
      }
    }

    document.getElementById("enable-shake").addEventListener("click", () => {
      enableShaking();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") {
        lastShakeAt = 0;
      }
    });
    nameEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        send({ type: "create", name: nameEl.value, shaking: true });
      }
    });
    codeEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        send({ type: "join", name: nameEl.value, code: codeEl.value, shaking: true });
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


def create_app(robot_token: str | None = None) -> web.Application:
    app = web.Application()
    app["book"] = LobbyBook()
    app["sockets"] = {}
    app["bridge"] = Bridge()
    app["robot"] = PicoLink(robot_token)
    app.on_startup.append(start_watch)
    app.on_cleanup.append(stop_watch)
    app.on_cleanup.append(close_bridge)
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    app.router.add_post("/api/robot", robot_poll)
    app.router.add_get("/api/robot/status", robot_status)
    app.router.add_post("/api/robot/test", robot_test)
    return app


async def close_bridge(app: web.Application) -> None:
    app["bridge"].close()


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
            await broadcast(app, code)
        elif kind == "start":
            if player_id is None:
                raise LobbyError("You are not in a lobby.")
            book.check_start(player_id)
            robot: PicoLink = app["robot"]
            chase = robot.online()
            if chase and book.robot_round() is not None:
                raise LobbyError("The robot is busy with another lobby's chase.")
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
            code = book.rematch(player_id)
            log.info("rematch opened as lobby %s", code)
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
    code = app["book"].leave(player_id)
    if code is not None:
        await broadcast(app, code)


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


async def broadcast_all(app: web.Application) -> None:
    for code in app["book"].codes():
        await broadcast(app, code)


async def send_error(socket: web.WebSocketResponse, message: str) -> None:
    if not socket.closed:
        await socket.send_str(json.dumps({"type": "error", "message": message}))
