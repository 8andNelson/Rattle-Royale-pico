// Dual-motor test for two 28BYJ-48 steppers, each on its own ULN2003.
// Motor 1: IN1 -> pin 8, IN2 -> pin 9, IN3 -> pin 10, IN4 -> pin 11.
// Motor 2: IN1 -> pin 4, IN2 -> pin 5, IN3 -> pin 6, IN4 -> pin 7.
// Both drivers share Arduino GND. Prefer an external 5V supply for the
// driver VCC pins, since both motors draw current at the same time.
//
// On power-up both motors take a short move one way, pause, then return
// together. About 4096 half-steps is one revolution of a 28BYJ-48.

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

const int kMotor1Pins[4] = {8, 9, 10, 11};
const int kMotor2Pins[4] = {4, 5, 6, 7};

struct Motor {
  const int* pins;
  int stepIndex;
};

Motor motor1 = {kMotor1Pins, 0};
Motor motor2 = {kMotor2Pins, 0};

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

void stepMotor(Motor& motor, int direction) {
  motor.stepIndex = (motor.stepIndex + direction + 8) % 8;
  applyStep(motor);
}

// Steps both motors before the shared wait, so the shafts turn together.
// Pass -1 for a direction to reverse that motor only.
void moveSteps(long count, int direction1, int direction2) {
  for (long n = 0; n < count; n++) {
    stepMotor(motor1, direction1);
    stepMotor(motor2, direction2);
    delay(kStepDelayMs);
  }
  releaseCoils(motor1);
  releaseCoils(motor2);
}

void setupMotor(Motor& motor) {
  for (int pin = 0; pin < 4; pin++) {
    pinMode(motor.pins[pin], OUTPUT);
  }
  releaseCoils(motor);
}

void setup() {
  setupMotor(motor1);
  setupMotor(motor2);
}

void loop() {
  moveSteps(kStepsPerMove, 1, 1);
  delay(kPauseMs);
  moveSteps(kStepsPerMove, -1, -1);
  delay(kPauseMs);
}
