"""Phone connection only.

A phone opens the page and holds a WebSocket. Rooms, seats, and names are
not part of this step.
"""

import json
import logging

from aiohttp import WSMsgType, web

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
      text-align: center;
    }
    main { padding: 1.5rem; }
    #status { font-size: 2.5rem; margin: 0 0 0.75rem; }
    #detail { margin: 0; color: #aaa; font-size: 1rem; }
  </style>
</head>
<body>
  <main>
    <p id="status">Connecting</p>
    <p id="detail"></p>
  </main>
  <script>
    const statusEl = document.getElementById("status");
    const detailEl = document.getElementById("detail");
    detailEl.textContent = location.host;

    let retryTimer = null;

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
      const socket = new WebSocket(protocol + "//" + location.host + "/ws");

      socket.addEventListener("message", (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch (error) {
          return;
        }
        if (message.type === "hello") {
          statusEl.textContent = "Connected";
        }
      });

      socket.addEventListener("close", scheduleReconnect);
      socket.addEventListener("error", () => {
        statusEl.textContent = "Reconnecting";
      });
    }

    connect();
  </script>
</body>
</html>
"""


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", websocket)
    return app


async def index(_request: web.Request) -> web.Response:
    return web.Response(text=PAGE, content_type="text/html", charset="utf-8")


async def websocket(request: web.Request) -> web.WebSocketResponse:
    socket = web.WebSocketResponse(heartbeat=20)
    await socket.prepare(request)
    peer = request.remote or "unknown"
    log.info("phone connected from %s", peer)
    try:
        await socket.send_str(json.dumps({"type": "hello"}))
        async for message in socket:
            if message.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
    finally:
        log.info("phone disconnected from %s", peer)
    return socket
