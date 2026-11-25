/*
 * Rover RC con orugas + brazo robótico (6 movimientos / 7 servos)
 * ---------------------------------------------------------------
 * Placa: Arduino MEGA 2560 (Herramientas > Placa > Arduino Mega or Mega 2560).
 *
 * Los comandos se aceptan por dos puertos a la vez (115200 baud):
 *   - Serial  : USB al PC (útil para depurar con el Monitor Serial)
 *   - Serial1 : ESP32 (TX1 = pin 18, RX1 = pin 19) -> control por WiFi
 *     Cableado: Mega TX1(18) -> divisor 1k/2k -> ESP32 RX | ESP32 TX -> Mega RX1(19) | GND común
 *
 * Comandos (terminan en '\n'):
 *   s1<ang>  Base panorámica
 *   s2<ang>  Base principal (servoBaseIzq = ang, servoBaseDer = 180 - ang)
 *   s3<ang>  Codo
 *   s4<ang>  Muñeca Pitch
 *   s5<ang>  Muñeca Roll
 *   s6<ang>  Pinza
 *   R_FWD / R_BWD / R_LEFT / R_RIGHT / R_STOP   Tracción
 *
 * ALIMENTACIÓN: 7 servos pueden consumir varios amperios. Aliméntalos con una
 * fuente/BEC externo de 5-6 V y une su GND con el GND del Arduino y del L298N.
 */

#include <Servo.h>

// ------------------------- PINES DE LOS SERVOS -------------------------
// Nota (Mega 2560): con hasta 12 servos la librería Servo usa el Timer5 y
// desactiva analogWrite() solo en los pines 44, 45 y 46. No los uses como ENA/ENB.
const uint8_t PIN_SERVO_BASE_PAN = 12;  // Servo 1: Base panorámica
const uint8_t PIN_SERVO_BASE_IZQ = 11;  // Servo 2: Base principal (1 de 2)
const uint8_t PIN_SERVO_BASE_DER = 10;  // Servo 3: Base principal (2 de 2, espejeado)
const uint8_t PIN_SERVO_CODO     = 9;   // Servo 4: Brazo / codo
const uint8_t PIN_SERVO_PITCH    = 8;   // Servo 5: Muñeca pitch
const uint8_t PIN_SERVO_ROLL     = 7;   // Servo 6: Muñeca roll
const uint8_t PIN_SERVO_PINZA    = 6;   // Servo 7: Pinza

// ------------------------- PINES DEL L298N -------------------------
const uint8_t PIN_ENA = 4;    // PWM velocidad motor izquierdo
const uint8_t PIN_IN1 = 22;   // Motor izquierdo
const uint8_t PIN_IN2 = 24;
const uint8_t PIN_IN3 = 26;   // Motor derecho
const uint8_t PIN_IN4 = 28;
const uint8_t PIN_ENB = 5;    // PWM velocidad motor derecho (pin PWM libre)

const uint8_t VELOCIDAD_AVANCE = 200;  // 0-255 (ajusta según tus motores de 300 RPM)
const uint8_t VELOCIDAD_GIRO   = 180;  // Velocidad al girar sobre su eje

// ------------------------- OBJETOS SERVO -------------------------
Servo servoBasePan;
Servo servoBaseIzq;
Servo servoBaseDer;
Servo servoCodo;
Servo servoMunecaPitch;
Servo servoMunecaRoll;
Servo servoPinza;

// ------------------------- PROTOTIPOS -------------------------
void leerPuerto(Stream &puerto);
void procesarComando(String cmd);
void moverServo(int numero, int angulo);
void moverBasePrincipal(int angulo);
void motoresAdelante();
void motoresAtras();
void motoresIzquierda();
void motoresDerecha();
void motoresDetener();
void setMotorIzq(int dir, uint8_t vel);
void setMotorDer(int dir, uint8_t vel);

// =====================================================================
void setup() {
  Serial.begin(115200);    // USB (PC)
  Serial.setTimeout(20);
  Serial1.begin(115200);   // ESP32 (TX1 = 18, RX1 = 19)
  Serial1.setTimeout(20);

  // Configurar pines del puente H
  pinMode(PIN_ENA, OUTPUT);
  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);
  pinMode(PIN_IN3, OUTPUT);
  pinMode(PIN_IN4, OUTPUT);
  pinMode(PIN_ENB, OUTPUT);
  motoresDetener();

  // Asociar servos a sus pines
  servoBasePan.attach(PIN_SERVO_BASE_PAN);
  servoBaseIzq.attach(PIN_SERVO_BASE_IZQ);
  servoBaseDer.attach(PIN_SERVO_BASE_DER);
  servoCodo.attach(PIN_SERVO_CODO);
  servoMunecaPitch.attach(PIN_SERVO_PITCH);
  servoMunecaRoll.attach(PIN_SERVO_ROLL);
  servoPinza.attach(PIN_SERVO_PINZA);

  // Posición inicial (coincide con los sliders de la interfaz)
  servoBasePan.write(90);
  moverBasePrincipal(90);
  servoCodo.write(90);
  servoMunecaPitch.write(90);
  servoMunecaRoll.write(90);
  servoPinza.write(90);

  Serial.println("Rover listo");
}

void loop() {
  leerPuerto(Serial);    // Comandos por USB
  leerPuerto(Serial1);   // Comandos reenviados por el ESP32 (WiFi)
}

// Lee una línea completa del puerto indicado y la procesa
void leerPuerto(Stream &puerto) {
  if (puerto.available() > 0) {
    String comando = puerto.readStringUntil('\n');
    comando.trim();                 // Quita '\r', espacios, etc.
    if (comando.length() > 0) {
      procesarComando(comando);
    }
  }
}

// =====================================================================
// Interpretación de comandos
// =====================================================================
void procesarComando(String cmd) {
  // --- Comandos de servos: "s<1-6><angulo>" ---
  if (cmd.charAt(0) == 's' && cmd.length() >= 3) {
    int numero = cmd.charAt(1) - '0';
    int angulo = constrain(cmd.substring(2).toInt(), 0, 180);
    moverServo(numero, angulo);
    return;
  }

  // --- Comandos de tracción ---
  if      (cmd == "R_FWD")   motoresAdelante();
  else if (cmd == "R_BWD")   motoresAtras();
  else if (cmd == "R_LEFT")  motoresIzquierda();
  else if (cmd == "R_RIGHT") motoresDerecha();
  else if (cmd == "R_STOP")  motoresDetener();
}

void moverServo(int numero, int angulo) {
  switch (numero) {
    case 1: servoBasePan.write(angulo);      break;
    case 2: moverBasePrincipal(angulo);      break;  // Dos servos sincronizados
    case 3: servoCodo.write(angulo);         break;
    case 4: servoMunecaPitch.write(angulo);  break;
    case 5: servoMunecaRoll.write(angulo);   break;
    case 6: servoPinza.write(angulo);        break;
    default: break;  // Número de servo inválido: se ignora
  }
}

// Base principal: dos servos enfrentados. Uno gira al ángulo recibido y el
// otro al ángulo inverso, así ambos empujan en el mismo sentido sin pelearse.
void moverBasePrincipal(int angulo) {
  servoBaseIzq.write(angulo);
  servoBaseDer.write(180 - angulo);
}

// =====================================================================
// Control de tracción (L298N)
// =====================================================================
// dir:  1 = adelante, -1 = atrás, 0 = parado
void setMotorIzq(int dir, uint8_t vel) {
  digitalWrite(PIN_IN1, dir > 0 ? HIGH : LOW);
  digitalWrite(PIN_IN2, dir < 0 ? HIGH : LOW);
  analogWrite(PIN_ENA, dir == 0 ? 0 : vel);
}

void setMotorDer(int dir, uint8_t vel) {
  digitalWrite(PIN_IN3, dir > 0 ? HIGH : LOW);
  digitalWrite(PIN_IN4, dir < 0 ? HIGH : LOW);
  analogWrite(PIN_ENB, dir == 0 ? 0 : vel);
}

void motoresAdelante() {
  setMotorIzq(1, VELOCIDAD_AVANCE);
  setMotorDer(1, VELOCIDAD_AVANCE);
}

void motoresAtras() {
  setMotorIzq(-1, VELOCIDAD_AVANCE);
  setMotorDer(-1, VELOCIDAD_AVANCE);
}

// Giro sobre su eje (típico en orugas): una oruga avanza y la otra retrocede
void motoresIzquierda() {
  setMotorIzq(-1, VELOCIDAD_GIRO);
  setMotorDer(1, VELOCIDAD_GIRO);
}

void motoresDerecha() {
  setMotorIzq(1, VELOCIDAD_GIRO);
  setMotorDer(-1, VELOCIDAD_GIRO);
}

void motoresDetener() {
  setMotorIzq(0, 0);
  setMotorDer(0, 0);
}
