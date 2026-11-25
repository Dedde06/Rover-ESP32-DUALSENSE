"""
Control de Rover con orugas + brazo robótico por WiFi (o USB)
=============================================================
La PC se conecta por TCP al ESP32 (misma red WiFi); el ESP32 reenvía cada
comando por serial al Arduino Mega. También se puede usar USB directo.

Protocolo (cada comando termina en '\n'):
    s1<angulo> ... s6<angulo>   -> Articulaciones del brazo
    R_FWD / R_BWD / R_LEFT / R_RIGHT / R_STOP -> Tracción
    HB                          -> Latido (solo WiFi; lo consume el ESP32)

Dependencias:  pip install pyserial numpy
"""

import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import serial
import serial.tools.list_ports

# ----------------------------- CONFIGURACIÓN -----------------------------
BAUDRATE_USB = 115200
HOST_POR_DEFECTO = "192.168.4.1"      # IP fija del ESP32 de control (su propia red WiFi)
PUERTO_TCP_POR_DEFECTO = 8080
INTERVALO_LATIDO = 0.5             # Segundos entre latidos (el ESP32 corta a los 2 s)
POSICION_INICIAL = 90

NOMBRES_ARTICULACIONES = [
    "1. Base panorámica",
    "2. Base principal (elevación)",
    "3. Brazo / Codo",
    "4. Muñeca Pitch",
    "5. Muñeca Roll",
    "6. Pinza",
]


class RoverApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Control Rover RC + Brazo Robótico (WiFi / USB)")
        self.root.protocol("WM_DELETE_WINDOW", self.al_cerrar)

        self.ser = None                          # Conexión USB
        self.sock = None                         # Conexión TCP (WiFi)
        self.lock_envio = threading.Lock()       # Evita escrituras simultáneas
        self.parar_hilos = threading.Event()     # Detiene lector y latido
        self.ultimo_enviado = [None] * 6         # Evita reenviar el mismo ángulo
        self.posiciones = []                     # Arreglo de posiciones guardadas
        self.cola_ui = queue.Queue()             # Mensajes de hilos hacia la GUI
        self.suprimir_envio = False              # True cuando se mueven sliders por código
        self.detener_trayectoria = threading.Event()
        self.hilo_trayectoria = None

        self.construir_interfaz()
        self.actualizar_puertos()
        self.root.after(30, self.procesar_cola_ui)

    # ------------------------------------------------------------------
    # Interfaz
    # ------------------------------------------------------------------
    def construir_interfaz(self):
        # --- Conexión ---
        marco_con = ttk.LabelFrame(self.root, text="Conexión")
        marco_con.pack(fill="x", padx=10, pady=5)

        self.var_modo = tk.StringVar(value="wifi")

        fila_wifi = ttk.Frame(marco_con)
        fila_wifi.pack(fill="x", pady=2)
        ttk.Radiobutton(fila_wifi, text="WiFi", variable=self.var_modo, value="wifi", width=8).pack(side="left", padx=4)
        ttk.Label(fila_wifi, text="IP / host:").pack(side="left")
        self.var_host = tk.StringVar(value=HOST_POR_DEFECTO)
        ttk.Entry(fila_wifi, textvariable=self.var_host, width=18).pack(side="left", padx=4)
        ttk.Label(fila_wifi, text="Puerto:").pack(side="left")
        self.var_puerto_tcp = tk.StringVar(value=str(PUERTO_TCP_POR_DEFECTO))
        ttk.Entry(fila_wifi, textvariable=self.var_puerto_tcp, width=6).pack(side="left", padx=4)

        fila_usb = ttk.Frame(marco_con)
        fila_usb.pack(fill="x", pady=2)
        ttk.Radiobutton(fila_usb, text="USB", variable=self.var_modo, value="usb", width=8).pack(side="left", padx=4)
        self.combo_puerto = ttk.Combobox(fila_usb, width=16, state="readonly")
        self.combo_puerto.pack(side="left", padx=4)
        ttk.Button(fila_usb, text="Refrescar", command=self.actualizar_puertos).pack(side="left")

        fila_est = ttk.Frame(marco_con)
        fila_est.pack(fill="x", pady=3)
        self.btn_conectar = ttk.Button(fila_est, text="Conectar", command=self.alternar_conexion)
        self.btn_conectar.pack(side="left", padx=5)
        self.lbl_estado = ttk.Label(fila_est, text="Desconectado", foreground="red")
        self.lbl_estado.pack(side="left", padx=10)

        # --- Sliders del brazo ---
        marco_brazo = ttk.LabelFrame(self.root, text="Brazo robótico (0° - 180°)")
        marco_brazo.pack(fill="x", padx=10, pady=5)

        self.sliders = []
        for i, nombre in enumerate(NOMBRES_ARTICULACIONES):
            ttk.Label(marco_brazo, text=nombre, width=28).grid(row=i, column=0, sticky="w", padx=5)
            slider = tk.Scale(
                marco_brazo, from_=0, to=180, orient="horizontal", length=350,
                command=lambda valor, idx=i: self.al_mover_slider(idx, valor),
            )
            slider.set(POSICION_INICIAL)
            slider.grid(row=i, column=1, padx=5, pady=2)
            self.sliders.append(slider)

        # --- Trayectorias ---
        marco_tray = ttk.LabelFrame(self.root, text="Posiciones y trayectoria")
        marco_tray.pack(fill="x", padx=10, pady=5)

        fila_btn = ttk.Frame(marco_tray)
        fila_btn.pack(fill="x", pady=3)
        ttk.Button(fila_btn, text="Guardar Posición", command=self.guardar_posicion).pack(side="left", padx=4)
        ttk.Button(fila_btn, text="Ejecutar Trayectoria", command=self.ejecutar_trayectoria).pack(side="left", padx=4)
        ttk.Button(fila_btn, text="Parar Trayectoria", command=self.parar_trayectoria).pack(side="left", padx=4)
        ttk.Button(fila_btn, text="Borrar Todo", command=self.borrar_posiciones).pack(side="left", padx=4)

        fila_par = ttk.Frame(marco_tray)
        fila_par.pack(fill="x", pady=3)
        ttk.Label(fila_par, text="Pasos entre puntos:").pack(side="left", padx=4)
        self.var_pasos = tk.IntVar(value=50)
        ttk.Spinbox(fila_par, from_=2, to=500, textvariable=self.var_pasos, width=6).pack(side="left")
        ttk.Label(fila_par, text="Retardo por paso (s):").pack(side="left", padx=(12, 4))
        self.var_retardo = tk.DoubleVar(value=0.03)
        ttk.Spinbox(fila_par, from_=0.005, to=1.0, increment=0.005,
                    textvariable=self.var_retardo, width=7).pack(side="left")

        self.lista_pos = tk.Listbox(marco_tray, height=5)
        self.lista_pos.pack(fill="x", padx=4, pady=3)

        # --- Tracción ---
        marco_rover = ttk.LabelFrame(self.root, text="Tracción del Rover (mantén pulsado para moverte)")
        marco_rover.pack(fill="x", padx=10, pady=5)

        grilla = ttk.Frame(marco_rover)
        grilla.pack(pady=5)
        self.crear_boton_traccion(grilla, "▲ Adelante", "R_FWD", 0, 1)
        self.crear_boton_traccion(grilla, "◄ Izquierda", "R_LEFT", 1, 0)
        ttk.Button(grilla, text="■ Detener", command=lambda: self.enviar("R_STOP")).grid(
            row=1, column=1, padx=3, pady=3, ipadx=8, ipady=6)
        self.crear_boton_traccion(grilla, "Derecha ►", "R_RIGHT", 1, 2)
        self.crear_boton_traccion(grilla, "▼ Atrás", "R_BWD", 2, 1)

    def crear_boton_traccion(self, padre, texto, comando, fila, columna):
        """Envía el comando al presionar y R_STOP al soltar."""
        boton = ttk.Button(padre, text=texto)
        boton.grid(row=fila, column=columna, padx=3, pady=3, ipadx=8, ipady=6)
        boton.bind("<ButtonPress-1>", lambda e: self.enviar(comando))
        boton.bind("<ButtonRelease-1>", lambda e: self.enviar("R_STOP"))

    # ------------------------------------------------------------------
    # Conexión (WiFi / USB)
    # ------------------------------------------------------------------
    def actualizar_puertos(self):
        puertos = [p.device for p in serial.tools.list_ports.comports()]
        self.combo_puerto["values"] = puertos
        if puertos and not self.combo_puerto.get():
            self.combo_puerto.set(puertos[0])

    def esta_conectado(self) -> bool:
        return self.sock is not None or (self.ser is not None and self.ser.is_open)

    def alternar_conexion(self):
        if self.esta_conectado():
            self.desconectar()
        else:
            self.conectar()

    def conectar(self):
        self.parar_hilos.clear()
        if self.var_modo.get() == "wifi":
            self.conectar_wifi()
        else:
            self.conectar_usb()

    def conectar_wifi(self):
        host = self.var_host.get().strip()
        try:
            puerto = int(self.var_puerto_tcp.get())
            sock = socket.create_connection((host, puerto), timeout=4)
        except (ValueError, OSError) as e:
            messagebox.showerror(
                "WiFi",
                f"No se pudo conectar a {host}:{self.var_puerto_tcp.get()}\n{e}\n\n"
                "Revisa que PC y ESP32 estén en la misma red y prueba con la IP "
                "que muestra el Monitor Serial del ESP32.")
            return
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(1.0)
        self.sock = sock
        self.ultimo_enviado = [None] * 6
        # Hilos: lector de respuestas del Mega y latido de seguridad
        threading.Thread(target=self._hilo_lector, args=(sock,), daemon=True).start()
        threading.Thread(target=self._hilo_latido, args=(sock,), daemon=True).start()
        self.marcar_conectado(f"Conectado por WiFi a {host}:{puerto}")

    def conectar_usb(self):
        puerto = self.combo_puerto.get()
        if not puerto:
            messagebox.showwarning("USB", "Selecciona un puerto serial.")
            return
        try:
            self.ser = serial.Serial(puerto, BAUDRATE_USB, timeout=0.1)
            time.sleep(2)  # El Arduino se reinicia al abrir el puerto
        except serial.SerialException as e:
            messagebox.showerror("USB", f"No se pudo abrir el puerto:\n{e}")
            self.ser = None
            return
        self.ultimo_enviado = [None] * 6
        self.marcar_conectado(f"Conectado por USB a {puerto}")

    def marcar_conectado(self, texto):
        self.lbl_estado.config(text=texto, foreground="green")
        self.btn_conectar.config(text="Desconectar")

    def desconectar(self, aviso=None):
        self.parar_trayectoria()
        self.enviar("R_STOP")          # Frena el rover antes de cerrar
        self.parar_hilos.set()
        with self.lock_envio:
            if self.sock:
                try:
                    self.sock.close()
                except OSError:
                    pass
                self.sock = None
            if self.ser:
                try:
                    self.ser.close()
                except serial.SerialException:
                    pass
                self.ser = None
        self.ultimo_enviado = [None] * 6
        self.lbl_estado.config(text=aviso or "Desconectado", foreground="red")
        self.btn_conectar.config(text="Conectar")

    # ------------------------------------------------------------------
    # Envío y recepción
    # ------------------------------------------------------------------
    def enviar(self, texto: str):
        """Envía una cadena terminada en '\\n' por WiFi o USB."""
        datos = (texto + "\n").encode("ascii")
        with self.lock_envio:
            try:
                if self.sock:
                    self.sock.sendall(datos)
                elif self.ser and self.ser.is_open:
                    self.ser.write(datos)
            except (OSError, serial.SerialException) as e:
                # Se avisa a la GUI (este método puede correr en un hilo)
                self.cola_ui.put(("perdida", f"Conexión perdida: {e}"))

    def enviar_servo(self, indice: int, angulo: int):
        """Envía 's<n><angulo>' solo si el ángulo cambió."""
        angulo = max(0, min(180, int(angulo)))
        if self.ultimo_enviado[indice] != angulo:
            self.ultimo_enviado[indice] = angulo
            self.enviar(f"s{indice + 1}{angulo}")

    def _hilo_lector(self, sock):
        """Lee y muestra en consola lo que responde el Mega a través del ESP32."""
        while not self.parar_hilos.is_set():
            try:
                datos = sock.recv(1024)
                if not datos:
                    raise OSError("el ESP32 cerró la conexión")
                print("[Mega]", datos.decode(errors="ignore").strip())
            except socket.timeout:
                continue
            except OSError as e:
                if not self.parar_hilos.is_set():
                    self.cola_ui.put(("perdida", f"Conexión perdida: {e}"))
                return

    def _hilo_latido(self, sock):
        """Envía 'HB' periódicamente: si se corta, el ESP32 frena el rover."""
        while not self.parar_hilos.wait(INTERVALO_LATIDO):
            if self.sock is not sock:
                return
            self.enviar("HB")

    # ------------------------------------------------------------------
    # Sliders
    # ------------------------------------------------------------------
    def al_mover_slider(self, indice: int, valor: str):
        if self.suprimir_envio:
            return
        self.enviar_servo(indice, round(float(valor)))

    def angulos_actuales(self):
        return [int(s.get()) for s in self.sliders]

    # ------------------------------------------------------------------
    # Guardar y ejecutar trayectorias
    # ------------------------------------------------------------------
    def guardar_posicion(self):
        pos = self.angulos_actuales()
        self.posiciones.append(pos)
        self.lista_pos.insert("end", f"P{len(self.posiciones)}: {pos}")

    def borrar_posiciones(self):
        self.posiciones.clear()
        self.lista_pos.delete(0, "end")

    def ejecutar_trayectoria(self):
        if len(self.posiciones) < 2:
            messagebox.showinfo("Trayectoria", "Guarda al menos 2 posiciones.")
            return
        if not self.esta_conectado():
            messagebox.showwarning("Conexión", "Conéctate al rover primero.")
            return
        if self.hilo_trayectoria and self.hilo_trayectoria.is_alive():
            return

        self.detener_trayectoria.clear()
        pasos = max(2, int(self.var_pasos.get()))
        retardo = max(0.001, float(self.var_retardo.get()))
        puntos = [list(p) for p in self.posiciones]

        self.hilo_trayectoria = threading.Thread(
            target=self._hilo_trayectoria, args=(puntos, pasos, retardo), daemon=True)
        self.hilo_trayectoria.start()

    def _hilo_trayectoria(self, puntos, pasos, retardo):
        """Interpola con numpy.linspace entre cada par de puntos y envía paso a paso."""
        for k in range(len(puntos) - 1):
            segmento = np.linspace(np.array(puntos[k]), np.array(puntos[k + 1]), pasos)
            if k > 0:
                segmento = segmento[1:]  # Evita repetir el punto de unión
            for fila in segmento:
                if self.detener_trayectoria.is_set():
                    return
                angulos = [int(round(a)) for a in fila]
                for i, ang in enumerate(angulos):
                    self.enviar_servo(i, ang)
                self.cola_ui.put(("sliders", angulos))
                time.sleep(retardo)

    def parar_trayectoria(self):
        self.detener_trayectoria.set()

    # ------------------------------------------------------------------
    # Mensajes de los hilos hacia la GUI (siempre en el hilo principal)
    # ------------------------------------------------------------------
    def procesar_cola_ui(self):
        try:
            while True:
                tipo, dato = self.cola_ui.get_nowait()
                if tipo == "sliders":
                    self.suprimir_envio = True   # No reenviar lo que ya se envió
                    for slider, ang in zip(self.sliders, dato):
                        slider.set(ang)
                    self.suprimir_envio = False
                elif tipo == "perdida" and self.esta_conectado():
                    self.desconectar(aviso=dato)
        except queue.Empty:
            pass
        self.root.after(30, self.procesar_cola_ui)

    # ------------------------------------------------------------------
    def al_cerrar(self):
        self.detener_trayectoria.set()
        try:
            self.desconectar()
        finally:
            self.root.destroy()


if __name__ == "__main__":
    ventana = tk.Tk()
    RoverApp(ventana)
    ventana.mainloop()
