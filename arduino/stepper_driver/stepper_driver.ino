// Test sketch for a 28BYJ-48 (or similar) on a ULN2003 board.
// Wiring: IN1 -> pin 8, IN2 -> pin 9, IN3 -> pin 10, IN4 -> pin 11,
//         driver VCC -> Arduino 5V, driver GND -> Arduino GND.
//
// On power-up the motor takes a short move one way, pauses, then
// returns. About 4096 half-steps is one revolution of a 28BYJ-48.

const int kPins[4] = {8, 9, 10, 11};
const int kStepDelayMs = 3;
const long kStepsPerMove = 512;
const int kPauseMs = 1000;

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

int stepIndex = 0;

void applyStep(int index) {
  const int phase = (index % 8 + 8) % 8;
  for (int pin = 0; pin < 4; pin++) {
    digitalWrite(kPins[pin], kSequence[phase][pin]);
  }
}

void releaseCoils() {
  for (int pin = 0; pin < 4; pin++) {
    digitalWrite(kPins[pin], LOW);
  }
}

void moveSteps(long count, int direction) {
  for (long n = 0; n < count; n++) {
    stepIndex = (stepIndex + direction + 8) % 8;
    applyStep(stepIndex);
    delay(kStepDelayMs);
  }
  releaseCoils();
}

void setup() {
  for (int pin = 0; pin < 4; pin++) {
    pinMode(kPins[pin], OUTPUT);
  }
  releaseCoils();
}

void loop() {
  moveSteps(kStepsPerMove, 1);
  delay(kPauseMs);
  moveSteps(kStepsPerMove, -1);
  delay(kPauseMs);
}
