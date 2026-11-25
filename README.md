# Rover RC con orugas y brazo robótico

Rover de tracción por orugas con un brazo robótico de 6 movimientos (7 servomotores), controlado desde una PC por WiFi, con una interfaz gráfica en Python o con un mando **DualSense** (PS5).

## Características

- **Brazo de 6 movimientos con 7 servos:** la base principal usa dos servos enfrentados (espejeados) para duplicar el torque.
- **Interfaz gráfica** en `tkinter`, con 6 sliders de 0° a 180° que envían los ángulos en tiempo real.
- **Posiciones y trayectorias:** se guardan posiciones del brazo y se reproducen con movimiento suave, interpolando con `numpy.linspace`.
- **Tracción por orugas** con puente H L298N y motores DC de 300 RPM.
- **Comunicación inalámbrica sin router:** el ESP32 crea su propia red WiFi y la laptop se conecta a ella.
- **Control con mando DualSense** por USB o Bluetooth, con parada de emergencia.
- **Seguridad:** el rover se detiene solo si se pierde la conexión, si el mando se desconecta o si se suelta un botón de tracción.

## Arquitectura

```
[Laptop: Python + mando DualSense]
            │  WiFi (TCP, 192.168.4.1:8080)
            ▼
[ESP32 de 38 pines: punto de acceso + puente]
            │  Serial UART (115200 baud)
            ▼
[Arduino Mega 2560]
   ├── 7 servos del brazo
   └── Módulo L298N ── 2 motores DC de 300 RPM
```

## Materiales

| Componente | Cantidad | Función |
|---|---|---|
| Arduino Mega 2560 | 1 | Controla servos y motores |
| ESP32 (placa de 38 pines) | 1 | Crea la red WiFi y reenvía las órdenes al Mega |
| Servomotores | 7 | Movimientos del brazo |
| Módulo L298N | 1 | Puente H para los motores de tracción |
| Motores DC de 300 RPM | 2 | Tracción por orugas |
| Resistencias 1 kΩ y 2 kΩ | 1 de cada | Divisor de voltaje (5 V → 3,3 V) |
| Mando DualSense | 1 | Control manual |
| Fuente de 5–6 V para servos | 1 | Alimentación independiente de los servos |
| Fuente de 7–8 V | 1 | Alimentación del Mega por Vin |
| Batería para los motores | 1 | Alimentación del L298N |

## Estructura del repositorio

```
.
├── README.md
├── rover_control_wifi.py     # Interfaz gráfica: sliders, posiciones, trayectorias, tracción
├── rover_dualsense.py        # Control con mando DualSense (usa rover_control_wifi.py)
├── rover_arduino/
│   └── rover_arduino.ino     # Código del Arduino Mega 2560
└── rover_esp32/
    └── rover_esp32.ino       # Código del ESP32 (punto de acceso + puente)
```

> Cada `.ino` debe estar dentro de una carpeta con su mismo nombre para que el Arduino IDE lo abra.

## Conexiones

### Servos (Arduino Mega)

| Servo | Función | Comando | Pin |
|---|---|---|---|
| 1 | Base panorámica | `s1` | 12 |
| 2 | Base principal (izquierdo) | `s2` | 11 |
| 3 | Base principal (derecho, espejeado) | `s2` | 10 |
| 4 | Brazo / codo | `s3` | 9 |
| 5 | Muñeca pitch | `s4` | 8 |
| 6 | Muñeca roll | `s5` | 7 |
| 7 | Pinza | `s6` | 6 |

El comando `s2` mueve el servo izquierdo al ángulo recibido y el derecho a `180 - ángulo`, para que trabajen en sincronía.

### Módulo L298N (Arduino Mega)

| Señal | Pin |
|---|---|
| ENA (velocidad motor izquierdo, PWM) | 4 |
| IN1 | 22 |
| IN2 | 24 |
| IN3 | 26 |
| IN4 | 28 |
| ENB (velocidad motor derecho, PWM) | 5 |

### Enlace Mega ↔ ESP32

El ESP32 trabaja a 3,3 V y el Mega a 5 V, por lo que la línea del Mega al ESP32 necesita un divisor de voltaje.

| Desde | Hacia |
|---|---|
| Mega **TX1 (pin 18)** | Resistencia de 1 kΩ → punto de unión → ESP32 **GPIO16** (RX2) |
| Punto de unión | Resistencia de 2 kΩ → GND |
| ESP32 **GPIO17** (TX2) | Mega **RX1 (pin 19)** (directo) |
| ESP32 **GND** | Mega **GND** |

### Alimentación

- **Mega:** 7–8 V por el pin **Vin** (no alimentar los 5 V externos por Vin).
- **Servos:** fuente externa de 5–6 V; nunca desde el Arduino.
- **Motores:** batería conectada al L298N.
- **ESP32:** 5 V por su pin VIN/5V, desde una fuente estable.
- **Todos los GND deben estar unidos** (Mega, ESP32, servos y L298N).

## Software necesario

**Arduino IDE** (2.x) con el soporte para placas ESP32 de Espressif instalado desde el Gestor de tarjetas. No se necesitan librerías adicionales (`Servo` y `WiFi` vienen incluidas).

**Python 3** con las librerías:

```bash
pip install pyserial numpy pygame
```

## Puesta en marcha

1. **Sube el código al Mega:** abre `rover_arduino/rover_arduino.ino`, elige la placa *Arduino Mega or Mega 2560* y pulsa Subir.
2. **Sube el código al ESP32:** abre `rover_esp32/rover_esp32.ino`, revisa el nombre y la clave de la red (`AP_SSID` y `AP_PASS`, mínimo 8 caracteres), elige la placa *ESP32 Dev Module* y pulsa Subir.
3. **Realiza las conexiones** y enciende el Mega y el ESP32. Espera unos 5 segundos a que el ESP32 cree su red.
4. **Conecta la laptop** a la red WiFi del ESP32 (por defecto `Rover-Control`).
5. **Conecta el mando DualSense** por USB o Bluetooth.
6. **Ejecuta la interfaz** desde la carpeta del proyecto:

   ```bash
   python rover_dualsense.py
   ```

   Para usar solo la interfaz con ratón, sin mando: `python rover_control_wifi.py`.
7. Comprueba que el host sea `192.168.4.1` y pulsa **Conectar**.
8. Haz las primeras pruebas con el rover levantado y con movimientos pequeños.

## Controles del DualSense

| Control | Acción |
|---|---|
| Stick izquierdo | Tracción: adelante, atrás y giro |
| Stick derecho X | Base panorámica (s1) |
| Stick derecho Y | Base principal / elevación (s2) |
| D-pad ↑ ↓ | Codo (s3) |
| L1 / R1 | Muñeca pitch (s4) |
| D-pad ← → | Muñeca roll (s5) |
| L2 / R2 | Pinza: abrir / cerrar (s6) |
| ✕ | Guardar posición |
| △ | Ejecutar trayectoria |
| ○ | **Parada de emergencia** |
| □ | Volver suavemente a la posición inicial (90°) |
| R3 | Alterna velocidad normal / fina del brazo |

Si algún botón no coincide en tu equipo, ejecuta `python rover_dualsense.py --mapa`, pulsa cada control y ajusta los números al inicio del archivo. Si una articulación se mueve al revés, cambia a `True` su posición en la lista `INVERTIR`.

## Protocolo de comandos

Cada comando es texto que termina en salto de línea (`\n`).

| Comando | Acción |
|---|---|
| `s1<ángulo>` … `s6<ángulo>` | Mueve la articulación indicada (0–180) |
| `R_FWD` | Rover adelante |
| `R_BWD` | Rover atrás |
| `R_LEFT` | Giro a la izquierda |
| `R_RIGHT` | Giro a la derecha |
| `R_STOP` | Detiene el rover |
| `HB` | Latido de seguridad (lo consume el ESP32; no llega al Mega) |

## Solución de problemas

- **`No such file or directory` al ejecutar Python:** abre la terminal dentro de la carpeta donde están los archivos `.py`.
- **`No module named ...`:** falta instalar una librería con `pip install pyserial numpy pygame`.
- **No conecta con el ESP32:** verifica que la laptop esté en la red del ESP32 y que el host sea `192.168.4.1`.
- **El rover frena solo:** el ESP32 detiene el rover si no recibe datos durante 2 segundos; revisa la conexión WiFi.
- **Un servo se mueve al revés o con tirones:** revisa la polaridad, la fuente externa de los servos y que los GND estén unidos.
- **El mando no responde:** ciérralo en otros programas (por ejemplo Steam) y usa el modo `--mapa`.

## Mejoras posibles

- Velocidad proporcional de la tracción con el stick.
- Guardar y cargar trayectorias en un archivo.
- Agregar una cámara para ver el entorno desde la interfaz.

## Autor y licencia

Proyecto desarrollado por **Gian Carlos N.** ( 26/11/2026 ).

Licencia: define aquí la licencia que prefieras (por ejemplo, MIT).
