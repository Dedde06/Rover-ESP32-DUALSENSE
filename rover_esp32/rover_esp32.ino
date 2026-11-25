/*
 * ESP32: punto de acceso WiFi + puente TCP -> Serial -> Arduino Mega
 * -------------------------------------------------------------------
 * El ESP32 CREA su propia red WiFi (no necesita router). La laptop se conecta
 * a esa red y abre una conexión TCP a 192.168.4.1:8080. Cada línea que llega
 * (s1..s6, R_FWD, ...) se reenvía tal cual al Mega por UART. Las líneas que
 * responde el Mega se devuelven a la laptop.
 *
 * SEGURIDAD: si el cliente se desconecta o no llegan datos durante
 * TIMEOUT_CLIENTE_MS, el ESP32 envía R_STOP al Mega para frenar el rover.
 * La interfaz de Python manda un "HB" (latido) cada 0.5 s para evitar ese corte.
 *
 * CABLEADO (ESP32 trabaja a 3.3 V, el Mega a 5 V):
 *   Mega TX1 (pin 18) -> divisor 1k/2k -> ESP32 PIN_RX_MEGA
 *   ESP32 PIN_TX_MEGA -> Mega RX1 (pin 19)  (directo, sin divisor)
 *   GND del ESP32 unido al GND del Mega
 *
 * Placa en el IDE: "ESP32 Dev Module".
 */

#include <WiFi.h>

// ------------------------- CONFIGURACIÓN -------------------------
const char*    AP_SSID         = "Rover-Meca";  // Nombre de la red que crea el ESP32
const char*    AP_PASS         = "YAKCHE123";     // Clave: mínimo 8 caracteres (cámbiala)
const uint8_t  AP_CANAL        = 6;                // Canal WiFi 1-13 (prueba 1, 6 u 11)
const uint8_t  AP_MAX_CLIENTES = 4;                // Laptop + ESP32-CAM + algún extra
const uint16_t TCP_PORT        = 8080;             // IP fija del ESP32 en su red: 192.168.4.1

const int  PIN_RX_MEGA = 16;                       // ESP32 RX2  <- TX1 del Mega (con divisor)
const int  PIN_TX_MEGA = 17;                       // ESP32 TX2  -> RX1 del Mega
const long BAUD_MEGA   = 115200;

const unsigned long TIMEOUT_CLIENTE_MS = 2000;     // Sin datos por este tiempo = enlace perdido

// ------------------------- VARIABLES -------------------------
WiFiServer servidor(TCP_PORT);
WiFiClient cliente;
bool hayCliente = false;
String bufferCliente = "";       // Línea en construcción que viene de la laptop
String bufferMega = "";          // Línea en construcción que viene del Mega
unsigned long ultimoRx = 0;      // Última vez que llegó algo de la laptop

// ------------------------- FUNCIONES -------------------------
void detenerRover() {
  Serial2.print("R_STOP\n");     // Orden de frenado de seguridad al Mega
}

void cerrarCliente(const char* motivo) {
  if (hayCliente) {
    cliente.stop();
    hayCliente = false;
    detenerRover();
    Serial.printf("Cliente desconectado (%s). Rover detenido.\n", motivo);
  }
}

void crearRedWifi() {
  WiFi.mode(WIFI_AP);
  // Parámetros: nombre, clave, canal, red oculta (0 = visible), máximo de clientes
  bool ok = WiFi.softAP(AP_SSID, AP_PASS, AP_CANAL, 0, AP_MAX_CLIENTES);
  WiFi.setSleep(false);          // Menor latencia
  if (ok) {
    Serial.printf("Red WiFi creada: %s\n", AP_SSID);
    Serial.print("IP del ESP32: ");
    Serial.println(WiFi.softAPIP());   // Normalmente 192.168.4.1
  } else {
    Serial.println("ERROR al crear la red WiFi (revisa que la clave tenga 8+ caracteres)");
  }
}

// =====================================================================
void setup() {
  Serial.begin(115200);                                            // Depuración (USB)
  Serial2.begin(BAUD_MEGA, SERIAL_8N1, PIN_RX_MEGA, PIN_TX_MEGA);  // Enlace con el Mega

  crearRedWifi();

  servidor.begin();
  servidor.setNoDelay(true);
  Serial.printf("Servidor TCP en el puerto %u\n", TCP_PORT);
}

void loop() {
  // --- 1) Aceptar un cliente nuevo (solo uno a la vez) ---
  WiFiClient nuevo = servidor.available();
  if (nuevo) {
    if (hayCliente) {
      cliente.stop();            // Reemplaza al cliente anterior
    }
    cliente = nuevo;
    cliente.setNoDelay(true);
    hayCliente = true;
    bufferCliente = "";
    ultimoRx = millis();
    detenerRover();              // Arranca siempre con el rover detenido
    Serial.println("Cliente conectado.");
  }

  // --- 2) Laptop -> Mega ---
  if (hayCliente) {
    if (!cliente.connected()) {
      cerrarCliente("cerrado por la laptop");
    } else {
      while (cliente.available()) {
        char c = cliente.read();
        ultimoRx = millis();
        if (c == '\n') {
          bufferCliente.trim();
          // "HB" es solo el latido: no se reenvía al Mega
          if (bufferCliente.length() > 0 && bufferCliente != "HB") {
            Serial2.print(bufferCliente);
            Serial2.print('\n');
          }
          bufferCliente = "";
        } else if (c != '\r' && bufferCliente.length() < 64) {
          bufferCliente += c;
        }
      }
      if (millis() - ultimoRx > TIMEOUT_CLIENTE_MS) {
        cerrarCliente("sin latido");
      }
    }
  }

  // --- 3) Mega -> Laptop (líneas completas) ---
  while (Serial2.available()) {
    char c = Serial2.read();
    if (c == '\n') {
      bufferMega.trim();
      if (hayCliente && bufferMega.length() > 0) {
        cliente.print(bufferMega);
        cliente.print('\n');
      }
      bufferMega = "";
    } else if (c != '\r' && bufferMega.length() < 64) {
      bufferMega += c;
    }
  }
}
