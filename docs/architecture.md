# Rattle Royale architecture

Rattle Royale is a party game for phones, with a two-motor robot on the bench. The running game is a lobby and a 20-second shake contest. Players open a page from the laptop, enable shaking, and join a lobby of up to 8 people. Each player gets a seat and a floor mark. The creator starts the round. Everyone shakes. The highest shake count when the timer ends wins.

During that round the server also keeps a fading pull score and picks who the robot would chase. Every phone shows that name. The robot does not move during a round. `server/arduino_bridge.py` can open the Arduino port, and nothing in a round sends it a move yet.

The phones do not drive motors. The laptop runs the page, the lobby, the clock, the scores, and the chase line. Campus Wi-Fi often blocks a phone from opening the laptop’s own address, so phones use an ngrok HTTPS tunnel to that same server. iOS also requires HTTPS before it will share motion data.

```text
Phones (up to 8)                         Laptop
Enable shaking, then join  --WebSocket--  Game server
    shake total during the round              lobby, seats, 20s clock, scores
                                              fading pull, chase target, winner
```

The motion that would aim the robot is specified further down and is not in this server. Seats, marks, fading pull, and the chase line already are.

| Piece | Where it runs | Now |
|---|---|---|
| Phone client | Browser on each phone | Join a lobby, show the seat and mark, count shakes, show pull, the chase line, the timer, and the winner |
| Game server | Laptop, port 8080 | Rooms, names, seats, 20-second clock, shake scores, fading pull, chase target, winner |
| ngrok | Laptop, forwarding to port 8080 | Public HTTPS address for phones |
| Motion planner | Same laptop | Not built. Later: aim and creep toward the live target |
| Serial bridge | Same laptop, using pyserial | Opens `RATTLE_PORT` at startup, sends one command, and waits for the reply. A round does not send moves yet |
| Firmware | Arduino | `arduino/dual_motor` accepts `SPIN`, `DRIVE`, `STOP`, and `PING`. `drive_test` rolls the car. `spin_test` turns it in place |

## Wireless robot (Pico W)

The robot can run on a Raspberry Pi Pico W instead of the Arduino, with no cable to the laptop. The code is in `pico/` and runs under MicroPython. The Arduino path below still works and is untouched.

The split is different from the Arduino plan. The Pico W owns the pose, the planning, and the stepping. The laptop only says what to do.

```text
Pico W                                     Laptop
POST /api/robot  --HTTPS via ngrok-->      game server
  pose, moving, arrival                      reply: chase / hold / home / test / stop
```

- The Pico polls `POST /api/robot` about every 300 ms on one kept-alive HTTPS connection, through the same ngrok address the phones use. Any Wi-Fi with internet works, including a phone hotspot. eduroam's enterprise login does not.
- Every request needs `Authorization: Bearer <token>`. The token is `RATTLE_ROBOT_TOKEN` on the laptop and `ROBOT_TOKEN` in `pico/config.py`. With no token set, the robot endpoints answer 503.
- The reply is one of: `chase` with the chased seat's mark in millimeters, `hold` (a round is open and nobody has pull), `home` (no round is open), `test` with a point set through `POST /api/robot/test`, or `stop` while a host has the robot stopped. `GET /api/robot/status` shows the last pose and the current order.
- Marks sit on a circle of `MARK_RADIUS_MM` (152.4 mm, 6 in, in `server/pico_link.py`), the same circle the Arduino planner uses. Seat 0 is along +x, and higher seats go counterclockwise seen from above. Lay the floor marks out that way.
- The Pico starts its pose at the center, pointed at seat 0, so it must be placed there before power-on. In `home` it drives back to the center and faces seat 0 on its own.
- Every order carries a `reset` id. The lobby creator's **The robot is on the center mark** button changes it, and the robot then sets its pose back to the center facing seat 0. Use it after placing the robot by hand.
- Core 1 does nothing but step the motors, so a slow HTTPS request on core 0 never stalls them. A move can be cut short at any step. The pose counts only the steps the wheels took, so a new order stops the move in flight and replans at once.
- Without a good reply for 2 seconds, the robot holds still.
- `WIFI_NETWORKS` in `pico/config.py` lists networks in order, such as the venue Wi-Fi and then a phone hotspot. A network that drops or does not connect within 10 seconds hands over to the next one.
- The onboard LED shows the link: a fast blink while joining Wi-Fi, a slow blink while looking for the server, solid when online, and a double blink while a host has the robot stopped.
- Each move ramps from `START_STEP_US` (3000) to `STEP_US` (2000) over `RAMP_STEPS` (200), and slows the same way before it ends, so the motors cruise faster than they could start.

### Host stop

The lobby creator sees a red **Stop the robot** button whenever the robot is online. During a chase only that lobby's creator can press it.

- Stop ends a running chase at once. The result is "The robot was stopped. No winner".
- Every order is then `stop`. The robot cuts the move in flight and stays still, and its pose stays right, since it counts only the steps it took.
- A chase cannot start while the robot is stopped. **Resume the robot**, or **The robot is on the center mark** after placing it by hand, lets it move again.

`pico/brain.py` holds every decision: orders, arrival, home, reset, stop, Wi-Fi handover, the LED state, and a lost link. `pico/main.py` runs it with the real wheels and Wi-Fi. `pico/simulator.py` runs the same brain on the laptop with pretend wheels, so phones can play a whole chase before the robot exists:

```text
python pico/simulator.py --token <RATTLE_ROBOT_TOKEN> --speed 5
```

`pico/deploy.py` copies the robot onto a Pico W over USB with mpremote, then restarts it. `--bench` leaves `main.py` off, so the robot does not drive on boot while `motor_test.py`, `link_test.py`, and `calibrate.py` are run from Thonny:

```text
python pico/deploy.py --bench
python pico/deploy.py
```

`pico/config_example.py` starts from the measured Arduino car: 38 mm wheels and a 127 mm wheel base (34.31 steps per millimeter, 38.03 per degree of spin), and forward is coil direction -1 on both wheels.

### Chase round

A round started while the robot is online is a chase. Otherwise it is the 20-second shake contest, unchanged.

- Start is refused until the robot is online, still, within 30 mm of the center, and facing seat 0 within 10°. Only one chase runs at a time.
- The chase lasts `CHASE_ROUND_SECONDS` (60). Shakes and pull work the same as in the contest.
- The robot reaching a mark, inside 25 mm, ends the round at once, and that seat wins, even if it lost the lead on the same tick.
- At the clock, the player being chased wins. Nobody chased is a draw. A host stop has no winner.
- The result is frozen when the round ends, so it stays if the winner leaves.
- Phones show whether the robot is online and on the center, whether the round is a chase or a contest, and an arena: marks on the circle, the chased mark in red, the viewer's mark outlined, and the robot as a yellow triangle at its pose.
- After the round the robot drives home by itself.

Pico W wiring: left ULN2003 IN1–IN4 on GP2–GP5, right ULN2003 IN1–IN4 on GP6–GP9, and Pico GND tied to both driver grounds and the motor supply ground. Driver VCC comes from the motor supply, never from the Pico's 3.3 V pin.

At a 2 ms cruise and 38 mm wheels, the robot moves about 15 mm per second. Reaching a mark 152.4 mm out takes about 9 seconds of a 60-second chase. If the motors skip at 2 ms, raise `STEP_US` toward 3000, which is about 10 mm per second and about 13 seconds to a mark.

## What already exists

The phone game lives in `server/`. Start it from the project folder with `python -m server`. It serves the page at `/` and a WebSocket at `/ws`. `requirements.txt` includes `aiohttp` for that server and `pyserial` for the Arduino link. `server/arduino_bridge.py` is the only module that imports `pyserial`.

`server/lobby.py` assigns seats, locks each seat’s angle when the round starts, accepts shake totals, fades pull, and chooses the chase target. `server/test_lobby.py` and `server/test_pull.py` cover that. `server/test_arduino_bridge.py` covers the serial link with a fake port. The page in `server/app.py` shows the seat, the mark, the pull, and who would be chased. The winner is still the highest shake count.

`ngrok.yml` points a public HTTPS address at `http://127.0.0.1:8080`. The phone page follows whatever address it was opened on, so the WebSocket uses the ngrok host when the page was opened through the tunnel.

The robot hardware is two 28BYJ-48 steppers, each on its own ULN2003 driver. `arduino/dual_motor` accepts motion commands. The phone round does not send those commands yet. Set `RATTLE_PORT` to the board’s COM port before starting the server, and close the serial monitor first. The server keeps that port open. If the variable is unset, or the board does not answer, the server logs that the robot is offline and the lobby still runs.

- Motor 1 uses Arduino pins 4, 5, 6, and 7.
- Motor 2 uses Arduino pins A0, A1, A2, and A3.
- Both driver grounds share the Arduino ground. Driver VCC should come from an external 5V supply, because both motors draw current at the same time.
- About 4096 half-steps is one revolution of a 28BYJ-48. At 3 ms per step, one wheel revolution takes about 12 seconds.
- `arduino/motor_test` exercises one motor on pins A0–A3. `arduino/stepper_driver` exercises one motor on pins 8–11, which is an older single-motor wiring, not motor 1 on the car.
- `arduino/drive_test` steps both car motors the same way and keeps going. On the bench, that rolls the car.
- `arduino/spin_test` steps motor 1 forward and motor 2 backward, the opposite of the drive test, so the car turns in place.
- `arduino/dual_motor` is the game sketch. At 115200 baud it reads `PING`, `STOP`, `SPIN`, and `DRIVE`, steps both motors on the same tick, waits 3 ms once per step, and releases the coils when the chunk ends. A step count is 1 through 16000. `DRIVE` with both motors in the same direction is the roll. `SPIN` runs them in opposite directions. Which way positive `SPIN` points relative to seat 0 is not written down yet.

## How a round feels

1. The player opens the page and taps **Enable shaking**. The name and lobby controls stay hidden until that succeeds. A phone with no motion sensor never gets them.
2. They enter a name and either create a lobby or join with a 4-character code. The lobby lists every name and seat. The phone says which seat they are and which floor mark to stand on.
3. The creator taps **Start game**. A 20-second countdown runs from the server’s end time. Seat numbers lock, and each seat gets the angle it will keep for the round.
4. Shakes add to that player’s score only while the countdown is running. The same shakes add pull. Pull fades while the round is open, and the phone with the strongest pull is the one the robot would chase. The list on every phone shows the same scores and pull. The personal shake total is hidden on the join screen and appears once the round has started.
5. At zero, the highest shake count wins. If several players share that score, all of their names are shown. Pull is not the winner. The leave button is hidden during the 20 seconds and comes back with the result.
6. Leaving the lobby removes that player and sets their phone’s shake count back to 0. After the result, the creator can tap **Rematch**. Everyone moves to a fresh lobby under a new code, with scores at 0 and seats packed again, and new players can join that code before the next start.

One player is enough to start. The creator is the person who created the lobby. If they leave and someone is still in it, the next person in the list becomes the creator.

## Phone client

A mobile web page served by the laptop. Players join by opening the ngrok HTTPS link. A native app is unnecessary.

The page asks for motion permission, takes a name and a lobby code, shows the seat and floor mark, counts shakes during the round, and shows the scores, the pull, who the robot would chase, the countdown, and the winner.

### Enable shaking

Shake detection uses the phone’s accelerometer through browser motion events.

- iOS only exposes motion data on an HTTPS page, and only after a tap that calls the permission request. The ngrok address is that HTTPS page.
- Android can read motion without that extra permission. The same page still asks everyone to tap **Enable shaking**.
- Create and join stay unavailable until shaking is on. The server also refuses a create or join that does not say shaking is enabled.
- If the browser has no motion API, the page says this phone cannot shake, and the lobby controls stay hidden.
- Turning shaking on closes the keyboard. Name and code are recorded by the page rather than by the keyboard’s own typing history, so an iPhone is less likely to pop up “Undo Typing” when the phone is shaken.

### Join a room

After shaking is enabled, the page asks for a display name and, to join an existing lobby, a code.

- The code is 4 characters from an alphabet that skips look-alike letters, so it can be read aloud.
- The display name is what the lobby list shows. The server assigns the seat. The creator is seat 0. The next player is seat 1, and so on.
- Before the round starts, a player who leaves is removed and the later seats pack down. After the start, a seat number stays put when someone leaves.
- The page shows “You are seat 3” and “Stand on mark 3” in the lobby. It does not draw the circle.
- Empty names, names longer than 20 characters, duplicate names in the same lobby, a full lobby (8 players), an unknown code, and a join after the start get a clear message on the page.
- A refresh or a dropped connection removes the player. The page does not resume the same seat.
- The page shows connecting and reconnecting. After a disconnect it returns to the join screen.

### Shake detection

The phone counts shakes locally and sends its running total for this round to the server when the count increases. It sends the total, not a claim that it is winning.

The strength of a reading is the magnitude of acceleration including gravity, in meters per second squared. Rest is about one gravity. A reading at or above a threshold of 15 counts. While the phone stays that strong, another shake is added about every 150 milliseconds, so a continuous rattle keeps scoring. The phone stops adding when the countdown reaches zero.

The phone sends totals only while the round is open. Shakes before the start and after zero stay off the score. If the tab is hidden, counting pauses. The shake total on the phone is reset when the player leaves the lobby, and a new round starts that phone from zero.

The server is given a short grace, about half a second after zero, to accept the last total that was already sent. The number on the phone and the number used to pick the winner are the same total.

### Scoreboard

During the round the page shows every player’s name, seat, shake count, and pull, ordered by pull. The local player’s row is marked. The chased row is marked with the word “chased”. A line above the list says “The robot is chasing” that name, “The robot is coming for you” on that player’s own phone, or “The robot is holding still” when nobody has pull. A countdown shows the time left, using the server’s end timestamp.

When the round ends, the page shows the winner, or every tied name, and the final counts. That winner is the highest shake count. The chase line stays on the frozen pull from the end of the round. The leave button is hidden while the 20 seconds are running.

### Phone edge cases

- A phone that loses the connection shows “reconnecting” and returns to the join screen. It cannot upload shakes from the gap.
- Leaving, or closing the page, removes that player from the lobby immediately.

## Game server

The game server is the source of truth for lobbies, seats, the clock, shake scores, pull, the chase target, and the winner. It runs on the laptop and speaks to phones over a WebSocket. It can open the serial port. It does not store a robot pose, and a round does not move the motors.

### Room creation

Any player who has enabled shaking can create a lobby from their phone.

- The server generates a room code that is unique among lobbies that still have someone in them.
- The creator is the first player. The lobby stores the player list and whether the round has started.
- When the last player leaves, the lobby is deleted and the code can be used again.
- There is no idle-room timer and no separate host screen on the laptop.

### Joining

- A join requires a valid room code, a display name, and shaking enabled.
- The server accepts the join when the lobby has fewer than 8 players and the round has not started. A join after the start is rejected with “This game has already started.”
- Names are compared without regard to case. “Bea” and “bea” are the same name.
- There is no minimum other than the creator. The maximum is 8.
- Every join and leave is broadcast so every phone’s list matches.

### Start and the clock

The creator starts the round. Other players do not start it.

Start broadcasts the lobby with the round end timestamp, 20 seconds out. Phones display that timestamp. The server is the clock that ends the round. There is no separate countdown before the shakes begin. Shakes before this start do not score.

Start also locks the seat list. Seat `i` of `N` players receives the angle `i × 360° / N`. People can still leave during the lobby, so the count is the number of players present at start. The page shows the seat number. The angle is stored for the later robot and is not drawn.

### Shake score

The score is the number of shakes accepted during the round. It does not fade.

- The phone sends a running total. The server adds the increase since the last total it accepted from that player.
- An increase is stored only while the round is open, the total went up, and the jump is at most 12. A larger jump is dropped.
- Totals that arrive up to about half a second after the end timestamp still count, so the last shake sent before zero is included. After that grace, the round is finished and further totals do not score.
- The scoreboard is broadcast with each accepted change.
- The winner is the player with the highest shake count. Everyone who shares that score is listed as a tie, including a round where the high score is zero. Pull does not pick the winner.

### Pull and the chase target

Pull is a decaying score on top of the shake count. It is who the robot would follow. The robot is not connected, so the target is only a line on the phone.

- Each accepted shake adds that same increase to the player’s pull. A dropped jump adds nothing.
- About four times a second the server fades every player’s pull. The half-life is 2.5 seconds. Pull below 0.05 becomes zero.
- The chase target is the player with the highest pull, as long as that pull is above zero. If two players have the same pull, the lower seat wins the comparison.
- The target switches only when a challenger leads by at least 1 pull, or by 15% of the current target’s pull, whichever is larger. A tie, or a lead inside that margin, keeps the current target.
- If every pull is zero, there is no target. The phone says the robot is holding still.
- If the chased player leaves and someone else still has pull, the next leader becomes the target. Their seat number does not change.
- Pull fades only while the round is open, including the half-second grace. When the round finishes, pull freezes at the value it had at the end of that grace.
- The scoreboard is broadcast when pull changes the list, including a change of target.

### Disconnects

A WebSocket close removes the player immediately. There is no reconnect grace and no reserved seat. If the creator leaves and the lobby is not empty, the next player becomes the creator. If they leave during a finished round, the result remains for whoever is still there.

### Server state

Each lobby moves through this sequence:

1. **Lobby** — players join and leave. Shakes do not score.
2. **Playing** — the 20-second window is open, shakes score, pull fades, the chase line is visible, and the leave button is hidden.
3. **Result** — the shake-count winner is fixed, shakes no longer score, pull stays where it froze, and players can leave.
4. The lobby ends when the last player leaves. The creator's **Rematch** opens the next round as a new lobby with the same players and a new code. The new code keeps the robot from mixing an arrival up between two rounds.

## Later: robot motion

Seats, floor marks, fading pull, and the chase line are already in the running server. The sections below are the motion that is not built. The laptop would turn the chase target into short spins and drives, track the robot’s pose, and be able to end a round because the robot arrived.

The running round does not do that. It lasts 20 seconds, the winner is the highest shake count, and a disconnect removes the player immediately. A later chase round would last longer, keep a seat through a short reconnect, and name a winner by arrival or by who the robot was chasing when the clock ended. Those rules are written below and are not in the server.

## Physical model the software depends on

The robot cannot see the phones. Indoor GPS and phone compass headings are too coarse to aim a small robot at a person. Each player claims a numbered mark on the floor, and that mark is their location for the whole game.

Marks sit on a circle around the robot’s home point, evenly spaced. The robot starts each round at the center, pointed at seat 0. Seat `i` of `N` players is the angle `i × 360° / N`. The mark coordinates are:

```text
mark(i) = (R cos θ, R sin θ)
θ = i × 360° / N
```

`R` is the measured radius from the center to the marks. Heading 0 points along +x, toward seat 0. Positive heading turns toward higher seat numbers. That sign is matched once to a positive `SPIN` direction and written down next to the pin map.

The laptop tracks the robot’s pose: `x`, `y`, and heading. The center is `(0, 0)`. Every finished spin updates the heading. Every finished drive updates `x` and `y` along the heading it had when the drive started. The pose is only trustworthy if the round begins on the home pose and every chunk runs to completion.

Players stand on their marks and stay there. The arrival radius is smaller than the distance from the mark to the player’s feet, so the robot can “reach” someone and stop short of them.

Three constants are measured once on the real chassis and then left alone:

- Steps per degree of a spin in place (motors in opposite directions).
- Steps per millimeter of straight travel (motors in the same direction).
- Radius `R` from the center to the marks, in millimeters.

Open-loop steppers drift if the robot is bumped or a move is cut off. Between games the host sets the robot back on the home pose by hand, or runs a return-to-home and then checks it. A host action resets the stored pose to `(0, 0)` at heading 0°.

## How a chase round feels

This is the later robot round, not the 20-second contest above.

1. Players join, get a seat, and stand on that mark. The robot sits at the center, pointed at seat 0.
2. The host starts. A short countdown plays. Shakes during the countdown do not count.
3. The shake window opens and the robot starts moving. Each phone’s shakes add pull. Pull fades if that person stops, so the robot follows current effort.
4. The planner picks the player with the strongest pull and sends a short spin or a short drive toward that player’s mark. When the chunk finishes, it looks at the scores again and sends the next chunk.
5. If someone overtakes the leader, the next chunk aims at the new leader. The robot visibly changes direction in the middle of the round.
6. The round ends in one of two ways. The robot’s pose comes within the arrival radius of a mark, and that player wins. Or the clock runs out, and the player the robot is chasing wins.
7. The result stays on screen. The next round starts from the center again.

While nobody has any pull, the robot holds still. The first shakes are what get it moving.

## Chase phone client

A mobile web page, served by the laptop, for the robot game. The running page already shows the seat, the mark, the pull, and who would be chased. It does not draw an arena or the robot’s pose, and a refresh does not resume the same seat.

The page has four jobs: join a room, show which floor mark to stand on, count shakes, and show the live chase.

### Join a room

The landing screen asks for a room code and a display name.

- The room code is short enough to read aloud.
- The display name is what the scoreboard shows. The server assigns the seat number. Players choose a name.
- Empty names, duplicate names in the same room, and a full room (8 players) get a clear message on the page.
- After a successful join, the page stores the player id for the tab session so a refresh can try to resume the same seat. Closing the tab drops the player after the server’s disconnect timeout.
- The page shows the connection state: connecting, in the lobby, in a round, reconnecting, and removed.

### Seat assignment

The server assigns the next free seat when the player joins. The page shows that seat in large type (“You are seat 3”) and tells the player to stand on the matching floor mark. The lobby list shows every joined name and seat so people can sort out who is standing where before the host starts.

Seats stay fixed for the life of the room. A player who drops and rejoins with the same session can reclaim the same seat while it is still reserved. A brand-new join gets a new free seat.

### Motion permission

Shake detection uses the phone’s accelerometer through the browser motion events.

- iOS only exposes motion data on an HTTPS page, and only after a tap that calls the permission request. The laptop must serve the page with a certificate, including on a local address.
- Android is more permissive. The same page still asks everyone to tap an “Enable shaking” button so both platforms share one flow.
- Until permission is granted, the player can sit in the lobby and cannot add pull. The host sees that player as not ready to score.
- If the browser has no motion API, the page says this phone cannot play, and the server does not count that player toward the minimum.

### Shake detection

The phone counts shakes locally and sends the running total for this round to the server a few times a second. It sends a total, not a claim that it is winning.

A shake counts when the acceleration magnitude crosses a fixed threshold and then falls back below it. One continuous rattle is one count. The threshold and the settle time are constants tuned on real phones. The page shows the player’s own shake count so they can feel the phone registering hits.

The phone sends counts only while the server says the round is open. Shakes before the start and after the round ends stay on the phone and are discarded. If the tab is hidden or the page is backgrounded, counting pauses and the last total stays in place.

### Live chase

During the round the page shows every player’s name, seat, and current pull, ordered by pull. Pull is the number the robot is listening to. The local player’s row is marked. The row of the player being chased is marked separately, with a line such as “The robot is coming for you” on that player’s own phone.

A countdown shows the time left, using the server’s end timestamp so phones with drifting clocks still agree. The page also shows a simple arena: marks around a circle and the robot’s latest pose, so people who cannot see the table still understand why it turned.

When the server ends the round, the page switches to the result: winner name and seat, whether they won by arrival or by the clock, and the final pull values. The next round returns the page to the lobby or to a “get ready” state, depending on what the server broadcasts.

### Phone edge cases

- A phone that loses Wi-Fi shows “reconnecting” and keeps the last chase on screen. On reconnect it resumes the same player id if the server still holds that seat.
- A phone that was disconnected cannot upload a burst of shakes from while it was offline. Pull only moves when the server accepts a new total.
- Two tabs with the same player id follow the server’s rule: the latest connection owns the seat, and the older tab is told it was replaced.

## Chase game server

The running server is already the source of truth for rooms, seats, the 20-second clock, shake scores, pull, and the chase target. The winner it broadcasts is still the highest shake count. It can open the serial port, and it does not keep a planner supplied. The chase server described here would add pose, arrival, and the motion chunks, on the same WebSocket.

### Room creation

A host creates a room from the laptop, or from a phone that then becomes the host.

- The server generates a room code that is unique among rooms that are still open.
- The room records a host id, the player list, the round state, and the robot pose. A new game sets the pose to home: `(0, 0)`, heading 0°.
- One room is the expected case for a party. The server can still keep rooms separate so a second code cannot collide with the first.
- Closing the host does not have to delete the room immediately. An idle room expires after a timeout so codes get reused.

### Joining and seats

- A join requires a valid room code and a display name.
- The server accepts the join when the room has fewer than 8 players and the room is still in the lobby. A join during a round is rejected with “round in progress.”
- Seats are integers from 0 to N−1 in join order. The angle for seat `i` is `i × 360° / N` using the number of players present when the host starts the round. People can still leave during the lobby, so angles are computed at start, not at join. The circle then matches the people actually playing.
- The minimum to start is 2 players. The maximum is 8.
- Every join, leave, and rename is broadcast to the room so every phone’s lobby list matches.

### Ready and start

The host starts the round. Other players do not start it.

Before the start is accepted:

- At least 2 players are connected.
- The stored pose is home. If the robot is still out on the floor from the last round, the host runs return-to-home or places it on the center mark and confirms home before starting.
- The robot is idle and the serial port is connected.
- The lobby shows who has not enabled shaking. Those players can still be in the round and will sit at zero pull until they enable it.

Start locks the seat list, computes mark positions, broadcasts a countdown, then a round-open message with the round end timestamp. Phones display that timestamp. The server is the clock that ends the round.

The round length is a server constant on the order of 45–60 seconds. The motors need several seconds to turn and cross the circle, and the fun of the demo is a lead change while the robot is already moving. Arrival can end the round sooner.

### Pull

Pull is a decaying score, not a lifetime shake count. A lifetime total would let an early leader own the robot for the rest of the round. Decay means the robot follows whoever is shaking now.

- Each accepted shake adds 1 pull to that player.
- On a fixed server tick, every player’s pull is multiplied by a decay factor. A half-life of about 2–3 seconds is the starting point: stop shaking and, a few seconds later, someone who is still going takes the robot.
- The phone still sends a monotonic shake total for the round. The server treats the increase since the last accepted total as the new shakes. The phone does not compute decay.
- An increase is stored only while the round is open, the total went up, and the jump fits under a physical rate limit. A jump larger than that limit is dropped.
- Pull is broadcast with the scoreboard so every phone shows the same race.
- The chase target is the player with the highest pull, as long as that pull is above zero.
- The target switches only when a challenger leads by a set margin (a fraction of the current pull, or a small absolute lead). A tie, or a lead inside the margin, keeps the current target. That stops the robot from twitching when two people are nearly even.
- If every pull is zero, there is no target and the planner sends nothing.

The rate limit exists so a modified client cannot jump from 0 to a huge pull in one message. Honest phones send small increases several times a second, so the limit sits just above a fast human shake rate.

### Winner

The server ends the round on the first of these:

- **Arrival.** After a chunk, the planner reports that the pose is inside a player’s arrival radius. That player wins, even if they lost the pull lead on the same tick. The robot already got there.
- **Clock.** The end timestamp passes. The current chase target wins. If there is no target because nobody shook, the round is a draw and the robot has not moved.
- **Host stop.** The host aborts. The round is a draw, the bridge is told to stop, and the pose is treated as unknown until the host confirms home.

The result message includes the winner id and seat, the reason (arrival, clock, or draw), and the final pull values. The room leaves Playing only after the current chunk has finished or the firmware has acknowledged `STOP`. A new round cannot start until the pose is home again.

### Disconnects

- A WebSocket close starts a short grace period. During the grace period the seat stays reserved and pull keeps decaying, because the person is not adding shakes.
- If the phone reconnects with the same player id inside the grace period, the seat continues and new shakes add pull again.
- If the grace period expires during the lobby, the seat is freed and the remaining seats are what the start-of-round angle math uses.
- If the grace period expires during a round, the player stays on the scoreboard. Their pull decays to nothing. They still occupy their mark for aiming, because the floor mark does not disappear when the phone does.
- If the host disconnects, the room stays up for the grace period. If the host does not return, the server stops the robot, ends the round as a draw, and returns the room to the lobby after the pose is marked unknown.

### Server state

Each room moves through a single sequence:

1. **Lobby** — players join and leave. The robot is idle at home.
2. **Countdown** — seats are locked, no more joins, shakes are not counted yet. The robot stays still.
3. **Playing** — pull is accepted, the planner sends chunks, phones show the chase. This state owns both the scoreboard and the motors.
4. **Result** — the robot is idle, the winner is fixed, and the pose is wherever the robot stopped. Return-to-home may run here.
5. **Lobby** — only after the host has confirmed the robot is back at the center. Heading and position are home again.

There is no separate “drive after the scores freeze” phase. Motion is part of Playing.

## Motion planner

The planner runs for the whole Playing state. Each time the serial bridge reports that a chunk finished, the planner reads the latest target and pose, updates the pose from the chunk that just finished, checks for arrival, and either stops the round or sends the next short move.

It does not wait for a final winner, and it does not interrupt a chunk that is already on the motors. A lead change shows up on the next chunk. Chunks stay short so that delay is a fraction of a second rather than a full drive across the table.

### Pose update

When `DONE SPIN` arrives for `steps` at `direction`:

```text
heading = wrap(heading + direction × steps / steps_per_degree)
```

When `DONE DRIVE` arrives for `steps` at `direction`:

```text
distance = direction × steps / steps_per_mm
x = x + cos(heading) × distance
y = y + sin(heading) × distance
```

Heading is in degrees in the game rules and in radians inside the trig. The wrap keeps heading in a single 360° range. Spin updates heading only. Drive uses the heading from before that drive, because a straight chunk does not turn.

### Next chunk

Let the target mark be `(tx, ty)`, and let the bearing from the robot to that mark be `bearing`. The heading error is the shortest signed angle from the current heading to `bearing`.

- If there is no target, send nothing and leave the coils released.
- If the distance to the target is inside the arrival radius, tell the server that player has won. Send nothing else.
- If the absolute heading error is above an align threshold (about 15°), send `SPIN` for the smaller of the error and a max spin chunk, in the direction of the error.
- Otherwise send `DRIVE` for the smaller of the remaining distance and a max drive chunk, forward.

Starting chunk sizes, to be tuned on the chassis:

- Max spin chunk: a few degrees, small enough that a new leader gets a visible correction within one or two chunks.
- Max drive chunk: a few centimeters, small enough that the robot can give up a straight line quickly when the target changes.

At 3 ms per step, a chunk of a few dozen steps is on the order of a tenth of a second of motion, plus one serial round trip. That is the responsiveness of the chase.

### Arrival and the clock

After every pose update the planner measures distance to every mark, not only the target. Entering any player’s arrival radius ends the round with that player as the winner. Checking every mark covers the case where the robot was committed to a short drive that carries it into a mark just as the lead changes.

If the server says the clock has expired, the planner finishes the chunk already in flight, then stops. It does not start another move. The server names the current target as the clock winner.

### Return to home

Return-to-home runs only in Result, after the robot is idle.

1. Spin the shortest way until the heading points from `(x, y)` back toward `(0, 0)`.
2. Drive the distance from the pose to the origin.
3. Spin to heading 0°.

The host looks at the robot. If it is on the center mark and pointed at seat 0, they confirm home and the server sets the pose to exactly `(0, 0)` at heading 0°. If it is off, they place it by hand and then confirm home. The stored pose follows the confirmation, not a hopeful guess.

### Planner outcomes

- **Chunk completed.** Pose updates. The planner either emits the next chunk, reports arrival, or idles because the clock expired or pull is zero.
- **No target.** The planner idles. Pose stays put.
- **Serial failure or timeout.** The server stops the round as a draw, tells the phones the drive failed, and marks the pose unknown until the host confirms home.
- **Host stop.** The bridge sends `STOP`. Pose becomes unknown until home is confirmed.

The planner never reads accelerometers and never computes pull. The server hands it a target, or no target.

## Serial bridge

`server/arduino_bridge.py` is the only code that opens the Arduino port. It uses pyserial. One thread reads and writes that port, so a wait cannot freeze the phone server. The planner is not calling it yet. When it does, it will hand the bridge one chunk at a time and wait for completion before the next, so a drive cannot start on top of a spin.

### Port

- The port name is the `RATTLE_PORT` environment variable, such as `COM5`. Auto-detect is optional later.
- The bridge opens that port when the game server starts and keeps it open. Opening the port usually resets the Arduino. The bridge waits up to 2 seconds for `READY`, then sends `PING`. `PONG` is what marks the link up.
- If `RATTLE_PORT` is unset, or the port is missing, or the board does not answer, the server logs that the robot is offline and the lobby still runs. Start is not rejected. The phone does not show a robot status yet. Rejecting start while the robot is offline belongs with the later chase round.
- A timeout, a dead cable, or a reply that does not match closes the port and leaves the bridge offline. It does not reconnect by itself, and it does not end the phone round. When the planner is running, that failure will end the round, tell the phones the drive failed, and mark the pose unknown until the host confirms home.

### Messages

Lines of text, one command or one reply per line. Human-readable text is enough at this baud rate and makes a serial monitor usable while tuning.

Commands the bridge sends:

| Command | Meaning |
|---|---|
| `SPIN <steps> <direction>` | Move `<steps>` half-steps with the motors in opposite directions. `<direction>` is `1` or `-1`. |
| `DRIVE <steps> <direction>` | Move `<steps>` half-steps with both motors in `<direction>`. |
| `STOP` | Release both coil sets immediately and cancel the current move. |
| `PING` | Ask the board to prove the link is up. |

Replies the firmware sends:

| Reply | Meaning |
|---|---|
| `READY` | Sent once from `setup` after the pins are safe. |
| `PONG` | Answer to `PING`. |
| `DONE SPIN <steps> <direction>` | The spin finished. The counts match the command so the planner can update heading. |
| `DONE DRIVE <steps> <direction>` | The drive finished. The counts match the command so the planner can update `x` and `y`. |
| `DONE STOP` | A stop finished with the coils released. Steps completed are not reported. Pose is unknown afterward. |
| `ERR BUSY` | A motion command arrived while a move was still running. |
| `ERR BAD` | The line could not be parsed. |

`<steps>` is an integer from 1 through 16000. `<direction>` is only `1` or `-1`. The bridge refuses to send anything else. A second spin or drive, while one is already on the port, is refused and is not written.

During Playing the bridge sends `STOP` only for a host abort or a serial recovery. Lead changes do not use `STOP`. The current chunk is allowed to finish so the pose math still matches the wheels.

### Waiting and timeouts

The bridge writes one command and reads until the matching `DONE` line, or until a timeout. A move may take the step count times 3 ms, plus 1 second. `PING` and `STOP` wait up to 1 second. `READY` and a stray `PONG` while a move is running are logged and skipped.

`ERR BUSY` and `ERR BAD` fail that motion. The bridge does not retry a motion on its own. A retry could repeat steps the wheels already took. The planner records the failure, the server ends the round, and the host recovers by homing.

`STOP` is the exception the host can send while a chunk is running. The firmware aborts the step loop, releases the coils, and replies `DONE STOP`.

### What the bridge does not do

The bridge does not compute angles, store pull, or choose motor pins. A spin of 40 steps at direction `-1` is opaque to it. That keeps serial failures independent of the chase.

## Firmware

`arduino/dual_motor` is the game sketch. `arduino/drive_test` and `arduino/spin_test` are the two-motor bench sketches: same direction rolls, opposite directions turn in place. `arduino/motor_test` and `arduino/stepper_driver` stay as single-motor tests. The game sketch keeps the existing motor model:

- The same 8-phase half-step sequence.
- Motor 1 on pins 4–7, motor 2 on pins A0–A3.
- Each motor keeps its own phase index so a spin does not corrupt the other motor’s phase.
- Each step writes both motors, then waits the step delay once.
- Coils are released when a chunk ends, so the motors do not sit powered between chunks. The next chunk starts immediately, so the release is brief. The phase index is kept across that release.

### Command executor

`setup` configures both motors, releases the coils, opens serial, and prints `READY`.

`loop` reads one line when no move is running. A parsed `SPIN` or `DRIVE` runs to completion, then prints `DONE` with the same step count and direction it executed. The step loop checks for a `STOP` line between steps so the host can abort a chunk.

Behavior of each command:

- **SPIN.** For each step, advance motor 1 by `direction` and motor 2 by the opposite direction, then wait the step delay. That pairing is what `arduino/spin_test` uses. Positive `direction` still has to be matched to the floor, toward higher seat numbers, and written into the sketch comment.
- **DRIVE.** For each step, advance both motors by `direction`, then wait the step delay. Both motors in direction `1` is what `arduino/drive_test` uses, and that rolls the car.
- **STOP.** Break out of the current step loop, release both coil sets, and print `DONE STOP`.
- **PING.** Print `PONG` when idle. During a move, a ping can wait. Stop takes priority over ping.

Malformed lines print `ERR BAD` and leave the motors released.

### Motion details that stay on the board

- Step delay stays a firmware constant. The laptop does not stream individual coil phases.
- Phase indices persist across commands so the next chunk continues from the electrical phase where the last chunk stopped. Releasing the coils does not reset the index. Resetting it would make the next step jump.
- Bounds: a step count outside 1 through 16000 is `ERR BAD`, so a bad serial line cannot spin forever. 16000 half-steps is a few wheel revolutions, enough for one return-to-home drive from the far side of a small circle.
- Baud rate is 115200, shared with the serial bridge.

### What stays off the board

The sketch does not know player names, seats, pull, or the round timer. It cannot decide who is being chased. Each command is one short spin or one short drive. The laptop is what strings those chunks into a chase.

## Shared rules

### Shakes and pull, as the game works now

- A shake is motion at or above a threshold of about 15 m/s², including gravity. While the phone stays that strong, another shake counts about every 150 ms.
- The phone sends its running total for the open round when the count increases.
- The server adds the increase only while the round is open, including a short grace after zero, and only when the jump is at most 12. That increase is added to both the shake count and the pull.
- Pull halves every 2.5 seconds and drops to zero below 0.05. The chase target switches only when a challenger leads by at least 1 pull or 15% of the current pull.
- Zero pull means the phone says the robot is holding still. The robot itself does not move.
- The highest shake count at the end wins. Ties list every name that shares that total. Pull freezes with the result and does not pick the winner.
- Shakes while the tab is hidden are not counted.
- Shakes before the start and after the countdown reaches zero are not sent.
- Leaving the lobby resets the phone’s count. A disconnect cannot fill in shakes from the gap.
- Shaking must be enabled before a player can create or join a lobby.

### Shakes and pull, for the later robot chase

- A shake for that chase is a threshold crossing followed by a settle, so one continuous rattle is one count.
- Pull decays on a server tick with a half-life of a few seconds, and the robot follows the pull leader.
- The chase target switches only when a challenger leads by a margin.
- Zero pull means the robot holds still.

### Pose and motion

These rules apply to the later robot chase.

- Home is `(0, 0)`, heading 0°, pointed at seat 0. Every round starts there. The host places the robot or confirms a return-to-home.
- Mark positions are computed from the player count at round start and do not change mid-round.
- The robot spins the short way toward the live target, then drives while it is aligned.
- Both motors step on the same tick. Opposite directions spin. Matching directions drive.
- Pose updates only from a `DONE` line for a chunk that finished every step.
- `STOP`, a serial timeout, or a disconnect marks the pose unknown until the host confirms home.
- Coils are off whenever the firmware is idle.
- The in-flight chunk finishes when the leader changes. The chunk after that aims at the new leader.

## Connection, hosting, and phone limits

- The laptop runs the web server and the WebSocket server on port 8080. ngrok forwards a public HTTPS address to that port. Phones open the ngrok address.
- Each player taps once to enable shaking before the lobby controls appear.
- A lobby holds up to 8 players. Join is refused above 8 and after the start. The creator can start alone.
- Set `RATTLE_PORT` to open the Arduino when the server starts. A round still does not send motor commands. Motor power comes from the external 5V supply, with grounds tied to the Arduino.

## Suggested build order

The phone game below is in place, including the chase line. The car rolls and can be told to turn in place from the bench sketches. A round still does not send those moves.

Done:

1. **Connection.** The laptop serves the page and a WebSocket. Phones reach it through ngrok.
2. **Lobby.** Create a room, join from other phones, refuse a ninth player, and require shaking first.
3. **Shake score.** Permission, counting on the phone, totals into the server, a 20-second clock, and a winner by shake count.
4. **Seats.** Assign a seat and a floor mark, pack seats until the start, then lock the angles.
5. **Fading pull.** Turn accepted shakes into a score that drops when someone stops, and show who the robot would chase.
6. **Firmware commands.** `arduino/dual_motor` runs `SPIN`, `DRIVE`, `STOP`, and `PING`, and the `DONE` reply echoes the step count and direction.
7. **Serial bridge.** `server/arduino_bridge.py` opens `RATTLE_PORT`, sends one command, and waits for `DONE` or a timeout. A round does not call it yet.

Still to build, so the robot actually follows that target:

8. **Pose and chase.** Measure steps per degree, steps per millimeter, and the mark radius. Aim short chunks at the live leader, then switch leaders and confirm the robot turns on the next chunk.
9. **Recovery.** Return-to-home, a dropped serial cable, a hidden phone tab, and a few seconds of lost Wi-Fi.
