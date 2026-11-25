"""
Rover + brazo: control con mando DualSense (sin cámara)
=======================================================
Amplía rover_control_wifi.py (debe estar en la misma carpeta) con control por
un mando DualSense (USB o Bluetooth) leído con pygame.

Dependencias:  pip install pyserial numpy pygame
Uso normal:    python rover_dualsense.py
Ver el mapa:   python rover_dualsense.py --mapa   (muestra qué número tiene cada botón/eje)

DISTRIBUCIÓN DEL MANDO
  Stick izquierdo ........ Tracción (arriba/abajo = adelante/atrás, izq/der = girar)
  Stick derecho X ........ s1 Base panorámica
  Stick derecho Y ........ s2 Base principal (elevación)
  D-pad arriba / abajo ... s3 Codo
  L1 / R1 ................ s4 Muñeca pitch (baja / sube)
  D-pad izq / der ........ s5 Muñeca roll
  L2 / R2 ................ s6 Pinza (abre / cierra, analógico)
  ✕ (Cruz) ............... Guardar posición
  △ (Triángulo) .......... Ejecutar trayectoria
  ○ (Círculo) ............ PARADA DE EMERGENCIA (frena el rover y detiene la trayectoria)
  □ (Cuadrado) ........... Volver suavemente a la posición inicial (90°)
  R3 (clic stick der.) ... Alterna velocidad normal / fina del brazo
"""

import os
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# Permite leer el mando aunque la ventana activa sea la de tkinter
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

import pygame

from rover_control_wifi import RoverApp, POSICION_INICIAL

# ----------------------------- CONFIGURACIÓN -----------------------------
# Numeración del DualSense en pygame 2 (Windows). Si algo no coincide en tu equipo,
# ejecuta con --mapa y corrige estos números.
EJE_LX, EJE_LY, EJE_RX, EJE_RY, EJE_L2, EJE_R2 = 0, 1, 2, 3, 4, 5
BTN_CRUZ, BTN_CIRCULO, BTN_CUADRADO, BTN_TRIANGULO = 0, 1, 2, 3
BTN_L3, BTN_R3 = 7, 8
BTN_L1, BTN_R1 = 9, 10
BTN_ARRIBA, BTN_ABAJO, BTN_IZQUIERDA, BTN_DERECHA = 11, 12, 13, 14

ZONA_MUERTA = 0.15          # Ignora el "ruido" del stick en reposo
UMBRAL_TRACCION = 0.5       # Cuánto hay que empujar el stick para mover el rover
VELOCIDAD_NORMAL = 80.0     # Grados por segundo con el stick a fondo
VELOCIDAD_FINA = 20.0       # Modo preciso (R3)
PERIODO_MANDO_MS = 25       # Frecuencia de lectura del mando (~40 Hz)

# Pon True en la articulación que se mueva al revés de lo esperado (orden: s1..s6)
INVERTIR = [False, False, False, False, False, False]


# ----------------------------- FUNCIONES AUXILIARES -----------------------------
def aplicar_zona_muerta(valor, zona=ZONA_MUERTA):
    """Devuelve 0 dentro de la zona muerta y reescala el resto a -1..1."""
    if abs(valor) < zona:
        return 0.0
    signo = 1.0 if valor > 0 else -1.0
    return signo * (abs(valor) - zona) / (1.0 - zona)


def comando_traccion(x, y):
    """Convierte la posición del stick izquierdo en un comando de tracción."""
    if abs(y) >= UMBRAL_TRACCION and abs(y) >= abs(x):
        return "R_FWD" if y < 0 else "R_BWD"      # En pygame, arriba es y negativo
    if abs(x) >= UMBRAL_TRACCION:
        return "R_RIGHT" if x > 0 else "R_LEFT"
    return "R_STOP"


# ----------------------------- APLICACIÓN CON MANDO -----------------------------
class RoverAppMando(RoverApp):
    def __init__(self, root):
        super().__init__(root)

        # Etiqueta de estado del mando al final de la ventana principal
        self.texto_mando = "Mando: no detectado"
        self.lbl_mando = ttk.Label(self.root, text=self.texto_mando)
        self.lbl_mando.pack(fill="x", padx=10, pady=(0, 8))

        pygame.display.init()
        pygame.joystick.init()
        self.mando = None
        self.modo_fino = False
        self.cmd_rover = "R_STOP"
        self.angulos_f = [float(a) for a in self.angulos_actuales()]
        self.gatillo_listo = {EJE_L2: False, EJE_R2: False}
        self.t_ultimo = time.time()

        self._buscar_mando()
        self.root.after(PERIODO_MANDO_MS, self.tick_mando)

    # --- Mensajes del mando ---
    def fijar_texto_mando(self, texto):
        self.texto_mando = texto
        self.lbl_mando.config(text=texto)

    def avisar(self, texto):
        """Muestra un aviso breve (sin ventanas modales que detendrían la lectura del mando)."""
        self.lbl_mando.config(text=texto)
        self.root.after(2500, lambda: self.lbl_mando.config(text=self.texto_mando))

    # --- Detección del mando ---
    def _buscar_mando(self):
        if self.mando is None and pygame.joystick.get_count() > 0:
            self._usar_mando(0)

    def _usar_mando(self, indice):
        self.mando = pygame.joystick.Joystick(indice)
        self.gatillo_listo = {EJE_L2: False, EJE_R2: False}
        self.fijar_texto_mando(f"Mando: {self.mando.get_name()}")

    # --- Bucle principal del mando ---
    def tick_mando(self):
        ahora = time.time()
        dt = min(ahora - self.t_ultimo, 0.1)
        self.t_ultimo = ahora
        try:
            self._procesar_eventos()
            if self.mando is not None:
                self._mover_traccion()
                self._mover_brazo(dt)
        except pygame.error:
            self._mando_perdido()
        self.root.after(PERIODO_MANDO_MS, self.tick_mando)

    def _procesar_eventos(self):
        for ev in pygame.event.get():
            if ev.type == pygame.JOYDEVICEADDED and self.mando is None:
                self._usar_mando(ev.device_index)
            elif ev.type == pygame.JOYDEVICEREMOVED:
                if self.mando is not None and ev.instance_id == self.mando.get_instance_id():
                    self._mando_perdido()
            elif ev.type == pygame.JOYBUTTONDOWN and self.mando is not None:
                self.al_boton(ev.button)

    def _mando_perdido(self):
        """Si el mando se desconecta, el rover se detiene por seguridad."""
        self.mando = None
        self.parada_emergencia()
        self.fijar_texto_mando("Mando: desconectado (rover detenido)")

    # --- Lectura de controles ---
    def _boton(self, indice):
        return indice < self.mando.get_numbuttons() and bool(self.mando.get_button(indice))

    def _dpad(self):
        x = y = 0
        if self.mando.get_numhats() > 0:
            x, y = self.mando.get_hat(0)
        if self._boton(BTN_ARRIBA):
            y = 1
        if self._boton(BTN_ABAJO):
            y = -1
        if self._boton(BTN_DERECHA):
            x = 1
        if self._boton(BTN_IZQUIERDA):
            x = -1
        return x, y

    def _gatillo(self, eje):
        """Devuelve 0..1. Se ignora hasta ver el gatillo en reposo (-1) para evitar lecturas falsas."""
        valor = self.mando.get_axis(eje)
        if valor <= -0.9:
            self.gatillo_listo[eje] = True
        if not self.gatillo_listo[eje]:
            return 0.0
        return aplicar_zona_muerta((valor + 1.0) / 2.0, 0.05)

    # --- Tracción ---
    def _mover_traccion(self):
        cmd = comando_traccion(self.mando.get_axis(EJE_LX), self.mando.get_axis(EJE_LY))
        if cmd != self.cmd_rover:                    # Solo se envía cuando cambia
            self.cmd_rover = cmd
            self.enviar(cmd)

    # --- Brazo ---
    def _mover_brazo(self, dt):
        if self.hilo_trayectoria and self.hilo_trayectoria.is_alive():
            return                                   # Durante una trayectoria el mando no mueve el brazo
        dx, dy = self._dpad()
        rx = aplicar_zona_muerta(self.mando.get_axis(EJE_RX))
        ry = aplicar_zona_muerta(self.mando.get_axis(EJE_RY))
        velocidades = [
            rx,                                                        # s1 Base panorámica
            -ry,                                                       # s2 Elevación (stick arriba = sube)
            float(dy),                                                 # s3 Codo
            float(self._boton(BTN_R1)) - float(self._boton(BTN_L1)),   # s4 Muñeca pitch
            float(dx),                                                 # s5 Muñeca roll
            self._gatillo(EJE_R2) - self._gatillo(EJE_L2),             # s6 Pinza
        ]
        vmax = VELOCIDAD_FINA if self.modo_fino else VELOCIDAD_NORMAL

        for i, v in enumerate(velocidades):
            slider = self.sliders[i]
            if v == 0.0:
                self.angulos_f[i] = float(slider.get())   # Sigue al slider si se movió con el ratón
                continue
            if INVERTIR[i]:
                v = -v
            nuevo = max(0.0, min(180.0, self.angulos_f[i] + v * vmax * dt))
            self.angulos_f[i] = nuevo
            if int(round(nuevo)) != int(slider.get()):
                slider.set(int(round(nuevo)))            # Mover el slider envía el comando s<n><ángulo>

    # --- Botones ---
    def al_boton(self, boton):
        if boton == BTN_CRUZ:
            self.guardar_posicion()
            self.avisar(f"Posición P{len(self.posiciones)} guardada")
        elif boton == BTN_TRIANGULO:
            if len(self.posiciones) < 2:
                self.avisar("Guarda al menos 2 posiciones (✕)")
            elif not self.esta_conectado():
                self.avisar("Conéctate al rover primero")
            else:
                self.ejecutar_trayectoria()
        elif boton == BTN_CIRCULO:
            self.parada_emergencia()
            self.avisar("PARADA DE EMERGENCIA")
        elif boton == BTN_CUADRADO:
            self.ir_a_inicio()
        elif boton == BTN_R3:
            self.modo_fino = not self.modo_fino
            self.avisar("Velocidad fina" if self.modo_fino else "Velocidad normal")

    def parada_emergencia(self):
        self.parar_trayectoria()
        self.cmd_rover = "R_STOP"
        self.enviar("R_STOP")

    def ir_a_inicio(self):
        """Lleva el brazo a 90° de forma suave usando la misma interpolación de las trayectorias."""
        if not self.esta_conectado():
            self.avisar("Conéctate al rover primero")
            return
        if self.hilo_trayectoria and self.hilo_trayectoria.is_alive():
            return
        puntos = [self.angulos_actuales(), [POSICION_INICIAL] * 6]
        self.detener_trayectoria.clear()
        self.hilo_trayectoria = threading.Thread(
            target=self._hilo_trayectoria, args=(puntos, 60, 0.03), daemon=True)
        self.hilo_trayectoria.start()

    # --- Cierre ---
    def al_cerrar(self):
        try:
            pygame.quit()
        except pygame.error:
            pass
        super().al_cerrar()


# ----------------------------- MODO DIAGNÓSTICO -----------------------------
def modo_mapa():
    """Imprime qué eje/botón se mueve, para ajustar la numeración si fuera distinta."""
    pygame.display.init()
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("No se detecta ningún mando. Conéctalo por USB o Bluetooth y vuelve a intentar.")
        return
    mando = pygame.joystick.Joystick(0)
    print(f"Mando: {mando.get_name()} | ejes: {mando.get_numaxes()} | "
          f"botones: {mando.get_numbuttons()} | hats: {mando.get_numhats()}")
    print("Mueve sticks, gatillos y pulsa botones. Ctrl+C para salir.\n")
    previo = [0.0] * mando.get_numaxes()
    try:
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.JOYBUTTONDOWN:
                    print(f"Botón {ev.button}")
                elif ev.type == pygame.JOYHATMOTION:
                    print(f"Hat {ev.hat}: {ev.value}")
            for i in range(mando.get_numaxes()):
                v = mando.get_axis(i)
                if abs(v - previo[i]) > 0.4:
                    print(f"Eje {i}: {v:+.2f}")
                    previo[i] = v
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    if "--mapa" in sys.argv:
        modo_mapa()
    else:
        ventana = tk.Tk()
        RoverAppMando(ventana)
        ventana.mainloop()
