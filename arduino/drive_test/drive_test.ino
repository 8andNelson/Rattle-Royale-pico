// Drive test for two 28BYJ-48 steppers, each on its own ULN2003.
// Motor 1: IN1 -> pin 4, IN2 -> pin 5, IN3 -> pin 6, IN4 -> pin 7.
// Motor 2: IN1 -> pin A0, IN2 -> pin A1, IN3 -> pin A2, IN4 -> pin A3.
// Both drivers share Arduino GND. Prefer an external 5V supply for the
// driver VCC pins, since both motors draw current at the same time.
//
// Both motors step forward together and keep going, so the car should roll.
// If it spins in place, the motors are mirrored: change one direction below
// from 1 to -1. About 4096 half-steps is one wheel revolution, about 12 seconds.

const int kStepDelayMs = 3;
const long kStepsPerMove = 512;

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

void applyStep(Motor& motor) {
  const int phase = (motor.stepIndex % 8 + 8) % 8;
  for (int pin = 0; pin < 4; pin++) {
    digitalWrite(motor.pins[pin], kSequence[phase][pin]);
  }
}

void stepMotor(Motor& motor, int direction) {
  motor.stepIndex = (motor.stepIndex + direction + 8) % 8;
  applyStep(motor);
}

void setupMotor(Motor& motor) {
  for (int pin = 0; pin < 4; pin++) {
    pinMode(motor.pins[pin], OUTPUT);
  }
}

// Steps both motors before the shared wait, so the shafts turn together.
void moveSteps(long count, int direction1, int direction2) {
  for (long n = 0; n < count; n++) {
    stepMotor(motor1, direction1);
    stepMotor(motor2, direction2);
    delay(kStepDelayMs);
  }
}

void setup() {
  setupMotor(motor1);
  setupMotor(motor2);
}

void loop() {
  moveSteps(kStepsPerMove, -1, -1);
}
