// Game sketch for two 28BYJ-48 steppers, each on its own ULN2003.
// Motor 1: IN1 -> pin 4, IN2 -> pin 5, IN3 -> pin 6, IN4 -> pin 7.
// Motor 2: IN1 -> pin A0, IN2 -> pin A1, IN3 -> pin A2, IN4 -> pin A3.
// Both drivers share Arduino GND. Prefer an external 5V supply for the
// driver VCC pins, since both motors draw current at the same time.
//
// One command per line at 115200 baud:
//   PING
//   STOP
//   SPIN <steps> <direction>
//   DRIVE <steps> <direction>
// <steps> is 1..16000 half-steps. <direction> is 1 or -1.
//
// DRIVE direction 1 rolls away from seat 0. DRIVE direction -1 rolls toward
// seat 0. SPIN direction 1 turns from seat 0 toward seat 1, which is positive
// heading. SPIN direction -1 turns toward lower seat numbers.
//
// About 4096 half-steps is one revolution of a 28BYJ-48.
// The laptop chooses each chunk. This sketch does not know seats or pull.

const unsigned long kBaud = 115200;
const int kStepDelayMs = 3;
const long kMaxSteps = 16000;
const size_t kLineLimit = 32;

// Half-step order for IN1, IN2, IN3, IN4.
const uint8_t kSequence[8][4] = {
    {1, 0, 0, 0},
    {1, 1, 0, 0},
    {0, 1, 0, 0},
    {0, 1, 1, 0},
    {0, 0, 1, 0},
    {0, 0, 1, 1},
    {0, 0, 0, 1},
    {1, 0, 0, 1},
};

const int kMotor1Pins[4] = {4, 5, 6, 7};
const int kMotor2Pins[4] = {A0, A1, A2, A3};

struct Motor {
  const int* pins;
  int stepIndex;
};

Motor motor1 = {kMotor1Pins, 0};
Motor motor2 = {kMotor2Pins, 0};

char lineBuf[kLineLimit];
size_t lineLen = 0;
bool lineOverflow = false;

enum Command {
  kCmdBad,
  kCmdPing,
  kCmdStop,
  kCmdSpin,
  kCmdDrive,
};

struct Motion {
  Command command;
  long steps;
  int direction;
};

enum PollResult {
  kPollNone,
  kPollLine,
  kPollOverflow,
};

void applyStep(Motor& motor) {
  const int phase = (motor.stepIndex % 8 + 8) % 8;
  for (int pin = 0; pin < 4; pin++) {
    digitalWrite(motor.pins[pin], kSequence[phase][pin]);
  }
}

void releaseCoils(Motor& motor) {
  for (int pin = 0; pin < 4; pin++) {
    digitalWrite(motor.pins[pin], LOW);
  }
}

void releaseBoth() {
  releaseCoils(motor1);
  releaseCoils(motor2);
}

void stepMotor(Motor& motor, int direction) {
  motor.stepIndex = (motor.stepIndex + direction + 8) % 8;
  applyStep(motor);
}

void setupMotor(Motor& motor) {
  for (int pin = 0; pin < 4; pin++) {
    pinMode(motor.pins[pin], OUTPUT);
  }
  releaseCoils(motor);
}

bool parseUnsigned(const char*& cursor, long& value) {
  if (*cursor < '0' || *cursor > '9') {
    return false;
  }
  value = 0;
  while (*cursor >= '0' && *cursor <= '9') {
    int digit = *cursor - '0';
    if (value > (kMaxSteps - digit) / 10) {
      return false;
    }
    value = value * 10 + digit;
    cursor++;
  }
  return true;
}

Motion parseCommand(const char* line) {
  Motion motion = {kCmdBad, 0, 0};
  if (strcmp(line, "PING") == 0) {
    motion.command = kCmdPing;
    return motion;
  }
  if (strcmp(line, "STOP") == 0) {
    motion.command = kCmdStop;
    return motion;
  }

  const char* cursor = NULL;
  if (strncmp(line, "SPIN ", 5) == 0) {
    motion.command = kCmdSpin;
    cursor = line + 5;
  } else if (strncmp(line, "DRIVE ", 6) == 0) {
    motion.command = kCmdDrive;
    cursor = line + 6;
  } else {
    return motion;
  }

  if (!parseUnsigned(cursor, motion.steps) || motion.steps < 1 || *cursor != ' ') {
    motion.command = kCmdBad;
    return motion;
  }
  cursor++;
  if (cursor[0] == '1' && cursor[1] == '\0') {
    motion.direction = 1;
  } else if (cursor[0] == '-' && cursor[1] == '1' && cursor[2] == '\0') {
    motion.direction = -1;
  } else {
    motion.command = kCmdBad;
  }
  return motion;
}

// Reads bytes already received. A finished line is left in lineBuf.
PollResult pollLine() {
  while (Serial.available() > 0) {
    int raw = Serial.read();
    if (raw < 0) {
      break;
    }
    char c = (char)raw;
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      lineBuf[lineLen] = '\0';
      bool overflow = lineOverflow;
      lineLen = 0;
      lineOverflow = false;
      return overflow ? kPollOverflow : kPollLine;
    }
    if (lineOverflow || lineLen + 1 >= kLineLimit) {
      lineOverflow = true;
      continue;
    }
    lineBuf[lineLen++] = c;
  }
  return kPollNone;
}

// Drains complete lines during a move. STOP wins. A queued PING is answered
// only after the move's DONE line, so one reply stays unambiguous.
bool serviceWhileMoving(bool& pingWaiting) {
  bool stop = false;
  while (true) {
    PollResult result = pollLine();
    if (result == kPollNone) {
      return stop;
    }
    if (result == kPollOverflow) {
      Serial.println("ERR BAD");
      continue;
    }
    Motion motion = parseCommand(lineBuf);
    if (motion.command == kCmdStop) {
      stop = true;
    } else if (motion.command == kCmdPing) {
      pingWaiting = true;
    } else if (motion.command == kCmdSpin || motion.command == kCmdDrive) {
      Serial.println("ERR BUSY");
    } else {
      Serial.println("ERR BAD");
    }
  }
}

bool waitStep(bool& pingWaiting) {
  unsigned long start = millis();
  while ((unsigned long)(millis() - start) < (unsigned long)kStepDelayMs) {
    if (serviceWhileMoving(pingWaiting)) {
      return false;
    }
  }
  return true;
}

void replyDone(const Motion& motion) {
  Serial.print(motion.command == kCmdSpin ? "DONE SPIN " : "DONE DRIVE ");
  Serial.print(motion.steps);
  Serial.print(' ');
  Serial.println(motion.direction);
}

void runMove(const Motion& motion) {
  bool pingWaiting = false;
  int direction2 = motion.command == kCmdSpin ? -motion.direction : motion.direction;
  bool stopped = false;
  for (long n = 0; n < motion.steps; n++) {
    if (serviceWhileMoving(pingWaiting)) {
      stopped = true;
      break;
    }
    stepMotor(motor1, motion.direction);
    stepMotor(motor2, direction2);
    if (!waitStep(pingWaiting)) {
      stopped = true;
      break;
    }
  }
  releaseBoth();
  if (stopped) {
    Serial.println("DONE STOP");
  } else {
    replyDone(motion);
  }
  if (pingWaiting) {
    Serial.println("PONG");
  }
}

void handleIdleLine() {
  Motion motion = parseCommand(lineBuf);
  if (motion.command == kCmdPing) {
    Serial.println("PONG");
    return;
  }
  if (motion.command == kCmdStop) {
    releaseBoth();
    Serial.println("DONE STOP");
    return;
  }
  if (motion.command == kCmdSpin || motion.command == kCmdDrive) {
    runMove(motion);
    return;
  }
  releaseBoth();
  Serial.println("ERR BAD");
}

void setup() {
  setupMotor(motor1);
  setupMotor(motor2);
  Serial.begin(kBaud);
  Serial.println("READY");
}

void loop() {
  PollResult result = pollLine();
  if (result == kPollOverflow) {
    releaseBoth();
    Serial.println("ERR BAD");
    return;
  }
  if (result == kPollLine) {
    handleIdleLine();
  }
}
