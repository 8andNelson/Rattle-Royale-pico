"""The HTML the game server serves: the phone page, the big screen, the robot
panel, and the arena all three draw."""

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
    #stop-robot { background: #b22; color: #fff; border: none; }
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
      <button id="stop-robot" type="button" hidden>Stop the robot</button>
      <button id="resume-robot" type="button" hidden>Resume the robot</button>
      <button id="rematch" type="button" hidden>Rematch</button>
      <p id="waiting" hidden>Waiting for the creator to start</p>
      <button id="leave" type="button">Leave lobby</button>
    </section>
    <p id="error"></p>
  </main>
  <script src="/arena.js"></script>
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
    let roundOpensAt = null;
    let countdownTimer = null;
    let replaced = false;
    let justResumed = false;
    let shakeBase = 0;
    let wasChasedYou = false;
    let buzzedResult = false;
    const SEAT_KEY = "rattle-seat";

    function savedSeat() {
      try {
        return sessionStorage.getItem(SEAT_KEY);
      } catch (error) {
        return null;
      }
    }

    function saveSeat(player) {
      try {
        if (player) {
          sessionStorage.setItem(SEAT_KEY, player);
        } else {
          sessionStorage.removeItem(SEAT_KEY);
        }
      } catch (error) {
        // Without storage a reload starts a new seat. A dropped socket still resumes.
      }
    }

    let seatInMemory = savedSeat();

    function rememberSeat(player) {
      seatInMemory = player;
      saveSeat(player);
    }

    function buzz(pattern) {
      if (navigator.vibrate) {
        navigator.vibrate(pattern);
      }
    }

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
      roundOpensAt = null;
      resetShakes();
      shakesEl.hidden = true;
      lobbyEl.hidden = true;
      joinEl.hidden = !shaking;
    }

    function runCountdown(endsAt, opensAt) {
      stopCountdown();
      const clock = document.getElementById("clock");
      function tick() {
        const now = Date.now();
        if (opensAt && now < opensAt) {
          clock.textContent = "Get ready " + Math.ceil((opensAt - now) / 1000);
          return;
        }
        const left = Math.max(0, Math.ceil((endsAt - now) / 1000));
        clock.textContent = left + "s";
        if (left <= 0) {
          stopCountdown();
        }
      }
      tick();
      countdownTimer = setInterval(tick, 200);
    }

    function robotStatusText(message) {
      const robot = message.robot;
      if (!robot || !robot.online) {
        return message.started ? "Robot offline" : "Robot offline. This will be a 20-second shake contest.";
      }
      if (robot.halted) {
        return "Robot stopped by a host";
      }
      if (robot.manual && !message.started) {
        return "Robot in manual control from the robot panel";
      }
      if (message.started) {
        return "Robot online";
      }
      return robot.home ? "Robot ready on the center mark" : "Robot online, not on the center mark yet";
    }

    function showLobby(message) {
      inLobby = true;
      const nowPlaying = message.started && !message.finished;
      if (nowPlaying && !playing) {
        resetShakes();
      }
      const previousEnd = roundEndsAt;
      const previousOpen = roundOpensAt;
      playing = nowPlaying;
      roundEndsAt = message.started ? message.ends_at : null;
      roundOpensAt = message.started ? message.opens_at : null;
      shakesEl.hidden = !message.started;
      errorEl.textContent = "";
      joinEl.hidden = true;
      lobbyEl.hidden = false;
      if (!shaking) {
        // A reload resumes the seat, but the browser asks for motion again.
        shakeNoteEl.textContent = "Tap Enable shaking so your shakes count.";
      }
      document.getElementById("lobby-code").textContent = message.code;
      document.getElementById("lobby-count").textContent =
        message.players.length + " of " + message.max;
      document.getElementById("start").hidden = !(message.creator && !message.started);
      const robotOnline = Boolean(message.robot && message.robot.online);
      const robotHalted = Boolean(message.robot && message.robot.halted);
      const chaseRunning = message.chase && message.started && !message.finished;
      document.getElementById("stop-robot").hidden =
        !(message.creator && robotOnline && !robotHalted && (chaseRunning || !message.started || message.finished));
      document.getElementById("resume-robot").hidden = !(message.creator && robotHalted && !chaseRunning);
      document.getElementById("robot-home").hidden = !(message.creator && !message.started && robotOnline);
      document.getElementById("robot-status").textContent = robotStatusText(message);
      const roundKind = document.getElementById("round-kind");
      roundKind.hidden = !message.started;
      roundKind.textContent = message.chase
        ? "Chase round. Get the robot to reach you."
        : "Shake contest. Most shakes wins.";
      drawArena(document.getElementById("arena"), message);
      document.getElementById("rematch").hidden = !(message.creator && message.finished);
      const waiting = document.getElementById("waiting");
      waiting.hidden = message.creator || (message.started && !message.finished);
      waiting.textContent = message.finished
        ? "Waiting for the creator to start a rematch"
        : "Waiting for the creator to start";
      document.getElementById("leave").hidden = playing;
      const mine = message.players.find((player) => player.you);
      if (justResumed && mine) {
        justResumed = false;
        if (message.started && !message.finished) {
          shakeBase = mine.shakes - shakeCount;
          showShakeCount();
        }
      }
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
          if (message.chase && !message.finished && !wasChasedYou) {
            buzz(200);
          }
        } else {
          chase.textContent = "The robot is chasing " + chased.name;
        }
      } else {
        chase.hidden = true;
        chase.textContent = "";
      }
      wasChasedYou = Boolean(message.players.find((player) => player.chased && player.you));
      const clock = document.getElementById("clock");
      const result = document.getElementById("result");
      if (playing) {
        clock.hidden = false;
        result.hidden = true;
        result.textContent = "";
        if (countdownTimer === null || previousEnd !== message.ends_at || previousOpen !== message.opens_at) {
          runCountdown(message.ends_at, message.opens_at);
        }
      } else if (message.finished) {
        if (mine) {
          shakeCount = mine.shakes;
          shakeBase = 0;
          showShakeCount();
          if (!buzzedResult && message.winners.includes(mine.name)) {
            buzz([100, 60, 100, 60, 300]);
          }
        }
        buzzedResult = true;
        stopCountdown();
        clock.hidden = true;
        result.hidden = false;
        result.textContent = resultText(message.winners, message.reason);
      } else {
        stopCountdown();
        clock.hidden = true;
        result.hidden = true;
        result.textContent = "";
      }
      if (!message.finished) {
        buzzedResult = false;
      }
      const list = document.getElementById("players");
      list.replaceChildren();
      message.players.forEach((player) => {
        const item = document.createElement("li");
        const marker = player.you ? " (you)" : "";
        let text = player.name + " — seat " + player.seat + marker;
        if (player.away) {
          text += " — reconnecting";
        }
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
    document.getElementById("stop-robot").addEventListener("click", () => {
      send({ type: "stop_robot" });
    });
    document.getElementById("resume-robot").addEventListener("click", () => {
      send({ type: "resume_robot" });
    });
    document.getElementById("leave").addEventListener("click", () => {
      rememberSeat(null);
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
      shakeBase = 0;
      lastShakeAt = 0;
      showShakeCount();
    }

    function showShakeCount() {
      shakesEl.textContent = "Shakes: " + (shakeBase + shakeCount);
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
      if (roundOpensAt !== null && Date.now() < roundOpensAt) {
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
      if (retryTimer !== null || replaced) {
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
          if (seatInMemory) {
            justResumed = true;
            next.send(JSON.stringify({ type: "resume", player: seatInMemory, total: shakeCount }));
          }
        } else if (message.type === "joined") {
          rememberSeat(message.player);
        } else if (message.type === "lobby") {
          showLobby(message);
        } else if (message.type === "expired") {
          rememberSeat(null);
          justResumed = false;
          if (inLobby) {
            inLobby = false;
            showJoin();
            errorEl.textContent = "Your seat was given up. Join again.";
          }
        } else if (message.type === "replaced") {
          replaced = true;
          inLobby = false;
          showJoin();
          joinEl.hidden = true;
          statusEl.textContent = "This seat moved to another tab.";
        } else if (message.type === "left") {
          rememberSeat(null);
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
        if (replaced) {
          return;
        }
        if (inLobby) {
          errorEl.textContent = "Connection lost. Getting your seat back.";
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


ARENA_JS = """\
// Shared by the phone page and the big screen.
const SVG = "http://www.w3.org/2000/svg";

function svgEl(name, attributes) {
  const element = document.createElementNS(SVG, name);
  Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
  return element;
}

// Marks on a circle, seat 0 to the right, higher seats counterclockwise.
// The robot is a triangle at its pose, pointing along its heading. The phone
// shows the arena only for a chase, or while the robot waits in the lobby.
function drawArena(arena, message, always) {
  const robot = message.robot;
  const show = always || message.chase || (robot && robot.online && !message.started);
  arena.hidden = !show;
  if (!show) {
    return;
  }
  arena.replaceChildren();
  const scale = 100 / ((robot && robot.radius) || 152.4);
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
      opacity: player.away ? 0.45 : 1,
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
      fill: robot.halted ? "#888" : "#ffd24a",
      transform: "translate(" + x + " " + y + ") rotate(" + (-robot.pose.heading) + ")",
    }));
  }
}

function resultText(winners, reason) {
  if (reason === "arrival" && winners.length === 1) {
    return "The robot reached " + winners[0] + ". " + winners[0] + " wins";
  }
  if (reason === "clock" && winners.length === 1) {
    return "Time. The robot was chasing " + winners[0] + ". " + winners[0] + " wins";
  }
  if (reason === "draw") {
    return "Nobody shook. Draw";
  }
  if (reason === "stopped") {
    return "The robot was stopped. No winner";
  }
  if (!winners || winners.length === 0) {
    return "No winner";
  }
  if (winners.length === 1) {
    return winners[0] + " wins";
  }
  return "Tie: " + winners.join(", ");
}
"""


SCREEN = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Rattle Royale Screen</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      background: #111;
      color: #f4f4f4;
      font-family: sans-serif;
    }
    main {
      display: grid;
      grid-template-columns: minmax(0, 3fr) minmax(16rem, 2fr);
      gap: 2rem;
      padding: 2rem;
      box-sizing: border-box;
      min-height: 100vh;
      align-items: center;
    }
    @media (max-width: 50rem) {
      main { grid-template-columns: 1fr; padding: 1rem; gap: 1rem; }
    }
    #arena { display: block; width: 100%; max-height: 85vh; }
    #arena[hidden] { display: none; }
    #code { font-size: 4rem; letter-spacing: 0.3rem; margin: 0; }
    #join-hint { color: #aaa; margin: 0 0 1.5rem; font-size: 1.1rem; overflow-wrap: anywhere; }
    #kind, #robot { color: #aaa; margin: 0 0 0.5rem; font-size: 1.2rem; }
    #clock { font-size: 4rem; margin: 0.5rem 0; }
    #chase { font-size: 1.6rem; margin: 0 0 1rem; }
    #result { font-size: 2.4rem; margin: 0.5rem 0 1rem; color: #ffd24a; }
    #players { list-style: none; padding: 0; margin: 0; font-size: 1.4rem; }
    #players li { display: grid; grid-template-columns: 1fr auto; gap: 0.25rem 1rem; padding: 0.4rem 0; }
    .bar { grid-column: 1 / -1; height: 0.4rem; background: #2a2a2a; border-radius: 0.2rem; overflow: hidden; }
    .bar span { display: block; height: 100%; background: #c33; }
    .away { opacity: 0.5; }
    form { display: flex; gap: 0.5rem; margin: 0 0 1rem; }
    form[hidden] { display: none; }
    input, button { font: inherit; font-size: 1.2rem; padding: 0.6rem; }
    input { width: 8rem; text-transform: uppercase; }
    #error { color: #ffb4b4; min-height: 1.2rem; }
  </style>
</head>
<body>
  <main>
    <svg id="arena" viewBox="-130 -130 260 260"></svg>
    <section>
      <form id="pick">
        <input id="pick-code" maxlength="4" placeholder="CODE" autocomplete="off" aria-label="Lobby code">
        <button type="submit">Watch</button>
      </form>
      <p id="code"></p>
      <p id="join-hint"></p>
      <p id="kind"></p>
      <p id="robot"></p>
      <p id="clock" hidden></p>
      <p id="chase"></p>
      <p id="result" hidden></p>
      <ul id="players"></ul>
      <p id="error"></p>
    </section>
  </main>
  <script src="/arena.js"></script>
  <script>
    const params = new URLSearchParams(location.search);
    let watching = (params.get("code") || "").trim().toUpperCase();
    let socket = null;
    let clockTimer = null;
    let last = null;
    const errorEl = document.getElementById("error");

    function tickClock() {
      const clock = document.getElementById("clock");
      if (!last || !last.started || last.finished) {
        clock.hidden = true;
        return;
      }
      clock.hidden = false;
      const now = Date.now();
      if (last.opens_at && now < last.opens_at) {
        clock.textContent = "Get ready " + Math.ceil((last.opens_at - now) / 1000);
      } else {
        clock.textContent = Math.max(0, Math.ceil((last.ends_at - now) / 1000)) + "s";
      }
    }

    function robotLine(robot) {
      if (!robot || !robot.online) {
        return "Robot offline";
      }
      if (robot.halted) {
        return "Robot stopped by a host";
      }
      return robot.home ? "Robot on the center mark" : "Robot online";
    }

    function show(message) {
      last = message;
      watching = message.code;
      errorEl.textContent = "";
      history.replaceState(null, "", "?code=" + message.code);
      document.getElementById("pick").hidden = true;
      document.getElementById("code").textContent = message.code;
      document.getElementById("join-hint").textContent = message.started
        ? ""
        : "Join at " + location.host + " with code " + message.code;
      document.getElementById("kind").textContent = !message.started
        ? message.players.length + " of " + message.max + " in the lobby"
        : message.chase ? "Chase round" : "Shake contest";
      document.getElementById("robot").textContent = robotLine(message.robot);
      drawArena(document.getElementById("arena"), message, true);
      const chased = message.players.find((player) => player.chased);
      document.getElementById("chase").textContent = !message.started
        ? ""
        : chased ? "The robot is chasing " + chased.name : "The robot is holding still";
      const result = document.getElementById("result");
      result.hidden = !message.finished;
      result.textContent = message.finished ? resultText(message.winners, message.reason) : "";
      const top = Math.max(1, ...message.players.map((player) => player.pull || 0));
      const list = document.getElementById("players");
      list.replaceChildren();
      message.players.forEach((player) => {
        const item = document.createElement("li");
        if (player.away) {
          item.className = "away";
        }
        const name = document.createElement("span");
        name.textContent = player.seat + ". " + player.name + (player.away ? " (reconnecting)" : "");
        const score = document.createElement("span");
        score.textContent = message.started ? player.shakes + " shakes" : "";
        item.append(name, score);
        if (message.started) {
          const bar = document.createElement("div");
          bar.className = "bar";
          const fill = document.createElement("span");
          fill.style.width = Math.round((100 * (player.pull || 0)) / top) + "%";
          bar.append(fill);
          item.append(bar);
        }
        list.append(item);
      });
      tickClock();
    }

    function watch(code) {
      if (code && socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "watch", code: code }));
      }
    }

    document.getElementById("pick").addEventListener("submit", (event) => {
      event.preventDefault();
      watching = document.getElementById("pick-code").value.trim().toUpperCase();
      watch(watching);
    });

    function connect() {
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      socket = new WebSocket(protocol + "//" + location.host + "/ws");
      socket.addEventListener("message", (event) => {
        let message;
        try {
          message = JSON.parse(event.data);
        } catch (error) {
          return;
        }
        if (message.type === "hello") {
          watch(watching);
        } else if (message.type === "lobby") {
          show(message);
        } else if (message.type === "closed") {
          errorEl.textContent = "Lobby " + message.code + " closed. Enter another code.";
          document.getElementById("pick").hidden = false;
        } else if (message.type === "error") {
          errorEl.textContent = message.message || "Something went wrong.";
          document.getElementById("pick").hidden = false;
        }
      });
      socket.addEventListener("close", () => {
        setTimeout(connect, 1000);
      });
    }

    clockTimer = setInterval(tickClock, 200);
    document.getElementById("pick").hidden = Boolean(watching);
    connect();
  </script>
</body>
</html>
"""


ROBOT_PANEL = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Robot Panel</title>
  <style>
    body { margin: 0; background: #111; color: #f4f4f4; font-family: sans-serif; }
    main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(18rem, 1fr);
      gap: 1.5rem;
      padding: 1.5rem;
      box-sizing: border-box;
      max-width: 70rem;
      margin: 0 auto;
    }
    @media (max-width: 46rem) {
      main { grid-template-columns: 1fr; padding: 1rem; }
    }
    h1 { font-size: 1.4rem; margin: 0 0 0.75rem; }
    h2 { font-size: 1rem; color: #aaa; margin: 1.25rem 0 0.5rem; font-weight: normal; }
    #arena { display: block; width: 100%; max-width: 28rem; margin: 0 auto; }
    dl { display: grid; grid-template-columns: auto 1fr; gap: 0.3rem 1rem; margin: 0; }
    dt { color: #aaa; }
    dd { margin: 0; font-variant-numeric: tabular-nums; }
    .row { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
    button, input, select { font: inherit; padding: 0.55rem 0.75rem; }
    input[type=number] { width: 6rem; }
    #token-form input { flex: 1; min-width: 10rem; }
    #token-form[hidden] { display: none; }
    #stop { background: #b22; color: #fff; border: none; }
    #message { min-height: 1.3rem; color: #ffd24a; margin: 0.75rem 0 0; }
    #message.bad { color: #ffb4b4; }
    .on { color: #8f8; }
    .off { color: #f88; }
  </style>
</head>
<body>
  <main>
    <section>
      <h1>Robot panel</h1>
      <svg id="arena" viewBox="-130 -130 260 260"></svg>
      <div class="row">
        <label for="seats">Marks on the floor</label>
        <select id="seats"></select>
      </div>
    </section>
    <section>
      <form id="token-form" class="row">
        <input id="token" type="password" autocomplete="off" placeholder="Robot token (RATTLE_ROBOT_TOKEN)" aria-label="Robot token">
        <button type="submit">Use token</button>
      </form>
      <dl>
        <dt>Link</dt><dd id="link">Waiting for the token</dd>
        <dt>Order</dt><dd id="order">-</dd>
        <dt>Pose</dt><dd id="pose">-</dd>
        <dt>Control</dt><dd id="control">-</dd>
        <dt>Wi-Fi signal</dt><dd id="rssi">-</dd>
        <dt>Poll time</dt><dd id="latency">-</dd>
        <dt>Free memory</dt><dd id="memory">-</dd>
        <dt>Up for</dt><dd id="uptime">-</dd>
        <dt>Boots seen</dt><dd id="boots">-</dd>
      </dl>

      <h2>Safety</h2>
      <div class="row">
        <button id="stop" type="button">Stop the robot</button>
        <button type="button" data-action="resume">Resume</button>
        <button type="button" data-action="reset">It is on the center mark</button>
      </div>

      <h2>Manual control</h2>
      <div class="row">
        <button type="button" data-action="manual" data-on="true">Take control</button>
        <button type="button" data-action="home">Hand back and drive home</button>
      </div>

      <h2>Jog</h2>
      <div class="row">
        <button type="button" data-jog="drive" data-amount="100">Forward 100 mm</button>
        <button type="button" data-jog="drive" data-amount="-100">Back 100 mm</button>
      </div>
      <div class="row" style="margin-top: 0.5rem">
        <button type="button" data-jog="spin" data-amount="90">Left 90°</button>
        <button type="button" data-jog="spin" data-amount="-90">Right 90°</button>
        <button type="button" data-jog="spin" data-amount="360">Full turn</button>
      </div>
      <form id="custom" class="row" style="margin-top: 0.5rem">
        <select id="custom-kind" aria-label="Jog kind">
          <option value="drive">Drive mm</option>
          <option value="spin">Spin degrees</option>
        </select>
        <input id="custom-amount" type="number" step="any" value="200" aria-label="Jog amount">
        <button type="submit">Jog</button>
      </form>

      <h2>Go to a mark</h2>
      <div class="row" id="marks"></div>
      <p id="message"></p>
    </section>
  </main>
  <script src="/arena.js"></script>
  <script>
    const TOKEN_KEY = "rattle-robot-token";
    const SEATS_KEY = "rattle-robot-seats";
    let token = "";
    let seats = 4;
    let last = null;
    const messageEl = document.getElementById("message");

    try {
      token = localStorage.getItem(TOKEN_KEY) || "";
      seats = Number(localStorage.getItem(SEATS_KEY)) || 4;
    } catch (error) {
      // Without storage the token is asked for on every visit.
    }

    function say(text, bad) {
      messageEl.textContent = text;
      messageEl.className = bad ? "bad" : "";
    }

    function headers() {
      return { "Authorization": "Bearer " + token, "Content-Type": "application/json" };
    }

    async function call(body) {
      if (!token) {
        say("Enter the robot token first.", true);
        return;
      }
      const response = await fetch("/api/robot/control", { method: "POST", headers: headers(), body: JSON.stringify(body) });
      const text = await response.text();
      if (!response.ok) {
        say(text || "That did not work.", true);
        return;
      }
      say("Sent: " + body.action + (body.kind ? " " + body.kind + " " + body.amount : ""), false);
      show(JSON.parse(text));
    }

    function drawMarks() {
      const select = document.getElementById("seats");
      select.replaceChildren();
      for (let count = 1; count <= 8; count++) {
        const option = document.createElement("option");
        option.value = count;
        option.textContent = count;
        option.selected = count === seats;
        select.append(option);
      }
      const marks = document.getElementById("marks");
      marks.replaceChildren();
      for (let seat = 0; seat < seats; seat++) {
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = "Mark " + seat;
        button.addEventListener("click", () => call({ action: "goto_seat", seat: seat, count: seats }));
        marks.append(button);
      }
    }

    function show(status) {
      last = status;
      const link = document.getElementById("link");
      link.textContent = status.online ? "Online" : status.seen_seconds_ago == null ? "Never seen" : "Offline, last seen " + status.seen_seconds_ago + " s ago";
      link.className = status.online ? "on" : "off";
      const order = status.order || {};
      document.getElementById("order").textContent = order.mode + (order.name ? " " + order.name : "") + (order.kind ? " " + order.kind + " " + order.amount : "");
      const pose = status.pose;
      document.getElementById("pose").textContent = pose
        ? "x " + pose.x.toFixed(0) + " mm, y " + pose.y.toFixed(0) + " mm, heading " + pose.heading.toFixed(0) + "°" + (pose.moving ? ", moving" : "") + (status.home ? ", home" : "")
        : "unknown";
      document.getElementById("control").textContent = status.halted ? "Stopped" : status.manual ? "Manual" : "Game";
      const health = status.health || {};
      document.getElementById("rssi").textContent = health.rssi == null ? "-" : health.rssi + " dBm";
      document.getElementById("latency").textContent = health.latency_ms == null ? "-" : health.latency_ms + " ms";
      document.getElementById("memory").textContent = health.mem_free == null ? "-" : Math.round(health.mem_free / 1024) + " KB";
      document.getElementById("uptime").textContent = health.uptime_s == null ? "-" : Math.floor(health.uptime_s / 60) + " min " + (health.uptime_s % 60) + " s";
      document.getElementById("boots").textContent = status.boots + (status.restoring ? " (restoring the last pose)" : "");
      const players = [];
      for (let seat = 0; seat < seats; seat++) {
        players.push({ seat: seat, angle: (360 * seat) / seats, chased: order.mode === "chase" && order.seat === seat });
      }
      drawArena(document.getElementById("arena"), {
        players: players,
        robot: { online: status.online, pose: status.pose, radius: status.radius, halted: status.halted },
      }, true);
    }

    async function refresh() {
      if (!token) {
        return;
      }
      try {
        const response = await fetch("/api/robot/status", { headers: headers() });
        if (response.status === 401 || response.status === 503) {
          document.getElementById("token-form").hidden = false;
          say(await response.text(), true);
          return;
        }
        document.getElementById("token-form").hidden = true;
        show(await response.json());
      } catch (error) {
        document.getElementById("link").textContent = "The server is not answering";
      }
    }

    document.getElementById("token-form").addEventListener("submit", (event) => {
      event.preventDefault();
      token = document.getElementById("token").value.trim();
      try {
        localStorage.setItem(TOKEN_KEY, token);
      } catch (error) {
        // Kept for this visit only.
      }
      say("", false);
      refresh();
    });
    document.getElementById("seats").addEventListener("change", (event) => {
      seats = Number(event.target.value);
      try {
        localStorage.setItem(SEATS_KEY, String(seats));
      } catch (error) {
        // Kept for this visit only.
      }
      drawMarks();
      if (last) {
        show(last);
      }
    });
    document.getElementById("stop").addEventListener("click", () => call({ action: "stop" }));
    document.querySelectorAll("[data-action]").forEach((button) => {
      button.addEventListener("click", () => {
        const body = { action: button.dataset.action };
        if (button.dataset.on) {
          body.on = button.dataset.on === "true";
        }
        call(body);
      });
    });
    document.querySelectorAll("[data-jog]").forEach((button) => {
      button.addEventListener("click", () => call({ action: "jog", kind: button.dataset.jog, amount: Number(button.dataset.amount) }));
    });
    document.getElementById("custom").addEventListener("submit", (event) => {
      event.preventDefault();
      call({ action: "jog", kind: document.getElementById("custom-kind").value, amount: Number(document.getElementById("custom-amount").value) });
    });

    document.getElementById("token-form").hidden = Boolean(token);
    drawMarks();
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
"""
