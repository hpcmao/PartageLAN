#!/usr/bin/env python3
"""
partagelan_tray.py — application PartageLAN pour Windows (winjeux).

Equivalent de l'app macOS : tourne en arriere-plan avec une icone dans la zone de
notification, ecoute en permanence (le Mac peut pousser fichiers/presse-papier), se
lance au demarrage, et ouvre une fenetre a deux panneaux facon Transmit (machine
locale a gauche, machine distante a droite), presse-papier partage, copie ->/<-,
scan reseau, themes et journal horodate.

Reutilise le protocole de partagelan.py. Dependances : pystray, Pillow (UI en tkinter).

Lancement normal (fenetre + tray)   : python  partagelan_tray.py
Lancement silencieux (sans console) : pythonw partagelan_tray.py   <- au demarrage
"""
import os
import sys
import json
import time
import socket
import threading
import subprocess
import winreg
import ctypes
from ctypes import wintypes
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import pystray
from pystray._util import win32 as _w32
from PIL import Image, ImageDraw, ImageTk

try:
    import tkinterdnd2
    from tkinterdnd2 import DND_FILES
except Exception:
    tkinterdnd2 = None
    DND_FILES = None

import partagelan as pl   # coeur du protocole (framing, ls/get/push/clip, utilitaires)

APP_NAME = "PartageLAN"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "PartageLAN")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
SCRIPT_PATH = os.path.abspath(__file__)

CLIP_LABELS = ["Les 2 sens", "Envoi seul", "Réception seule", "Coupé"]
CLIP_LABEL_TO_MODE = {"Les 2 sens": "both", "Envoi seul": "send",
                      "Réception seule": "receive", "Coupé": "off"}
CLIP_MODE_TO_LABEL = {v: k for k, v in CLIP_LABEL_TO_MODE.items()}

THEME_LABELS = ["Système", "Clair", "Sombre", "Océan", "Sépia", "Nord",
                "Dracula", "Solarisé clair", "Contraste élevé"]
THEME_LABEL_TO_KEY = {"Système": "systeme", "Clair": "clair", "Sombre": "sombre",
                      "Océan": "ocean", "Sépia": "sepia", "Nord": "nord",
                      "Dracula": "dracula", "Solarisé clair": "solarise",
                      "Contraste élevé": "contraste"}
THEME_KEY_TO_LABEL = {v: k for k, v in THEME_LABEL_TO_KEY.items()}

DEFAULTS = {
    "peer_ip": pl.DEFAULT_IP,
    "recv_dir": pl.downloads_dir(),
    "listen": True,
    "clip_mode": "both",
    "theme": "Clair",
    "local_path": os.path.expanduser("~"),
    "remote_path": "~",
    "geometry": "1140x760",
}

# --------------------------------------------------------------------------- #
#  Palettes de themes                                                          #
# --------------------------------------------------------------------------- #
PALETTES = {
    "clair":     dict(bg="#ECECEC", fg="#1A1A1A", muted="#6B7280", err="#C0392B",
                      list_bg="#FFFFFF", list_fg="#1A1A1A", sel_bg="#3B82F6", sel_fg="#FFFFFF",
                      btn="#E4E4E4", btn_active="#D2D2D2", log_bg="#FFFFFF", log_fg="#111111"),
    "sombre":    dict(bg="#2B2B2E", fg="#E8E8E8", muted="#9AA0A6", err="#FF6B6B",
                      list_bg="#1E1E20", list_fg="#E8E8E8", sel_bg="#2563EB", sel_fg="#FFFFFF",
                      btn="#3A3A3E", btn_active="#4A4A4F", log_bg="#141416", log_fg="#DDDDDD"),
    "ocean":     dict(bg="#0F2A3F", fg="#E6F1FF", muted="#7FA8C9", err="#FF8080",
                      list_bg="#10344F", list_fg="#E6F1FF", sel_bg="#2E86C1", sel_fg="#FFFFFF",
                      btn="#164060", btn_active="#1E5580", log_bg="#0B2136", log_fg="#CFE6FF"),
    "sepia":     dict(bg="#F4ECD8", fg="#4B3B2A", muted="#8A7A5C", err="#B23A2A",
                      list_bg="#FBF5E6", list_fg="#4B3B2A", sel_bg="#B08D57", sel_fg="#FFFFFF",
                      btn="#E9DFC6", btn_active="#DCCFA8", log_bg="#FBF5E6", log_fg="#4B3B2A"),
    "nord":      dict(bg="#2E3440", fg="#ECEFF4", muted="#A0AAB8", err="#BF616A",
                      list_bg="#3B4252", list_fg="#ECEFF4", sel_bg="#88C0D0", sel_fg="#2E3440",
                      btn="#434C5E", btn_active="#4C566A", log_bg="#292E39", log_fg="#E5E9F0"),
    "dracula":   dict(bg="#282A36", fg="#F8F8F2", muted="#9CA0B0", err="#FF5555",
                      list_bg="#21222C", list_fg="#F8F8F2", sel_bg="#BD93F9", sel_fg="#282A36",
                      btn="#343746", btn_active="#44475A", log_bg="#1E1F29", log_fg="#F8F8F2"),
    "solarise":  dict(bg="#FDF6E3", fg="#586E75", muted="#93A1A1", err="#DC322F",
                      list_bg="#FDF6E3", list_fg="#586E75", sel_bg="#268BD2", sel_fg="#FFFFFF",
                      btn="#EEE8D5", btn_active="#DDD6C1", log_bg="#FDF6E3", log_fg="#586E75"),
    "contraste": dict(bg="#000000", fg="#FFFFFF", muted="#CCCCCC", err="#FF5555",
                      list_bg="#000000", list_fg="#FFFFFF", sel_bg="#FFB000", sel_fg="#000000",
                      btn="#1A1A1A", btn_active="#333333", log_bg="#000000", log_fg="#FFFFFF"),
}

def windows_is_dark():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return v == 0
    except Exception:
        return False

def resolve_theme_key(key):
    if key == "systeme":
        return "sombre" if windows_is_dark() else "clair"
    return key if key in PALETTES else "clair"

# --------------------------------------------------------------------------- #
#  Config                                                                      #
# --------------------------------------------------------------------------- #
def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)

def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    if not cfg.get("recv_dir"):
        cfg["recv_dir"] = pl.downloads_dir()
    if not os.path.isdir(cfg.get("local_path", "")):
        cfg["local_path"] = os.path.expanduser("~")
    return cfg

def save_config(cfg):
    ensure_config_dir()
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# --------------------------------------------------------------------------- #
#  Lancement au demarrage (cle Run du registre)                                #
# --------------------------------------------------------------------------- #
def pythonw_path():
    d = os.path.dirname(sys.executable)
    cand = os.path.join(d, "pythonw.exe")
    return cand if os.path.exists(cand) else sys.executable

def launch_command():
    return f'"{pythonw_path()}" "{SCRIPT_PATH}"'

def is_autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, APP_NAME)
            return bool(val)
    except OSError:
        return False

def set_autostart(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass

# --------------------------------------------------------------------------- #
#  Divers                                                                      #
# --------------------------------------------------------------------------- #
def make_icon_image(online=True):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (36, 105, 178, 255) if online else (110, 110, 116, 255)
    d.rounded_rectangle([2, 2, 61, 61], radius=14, fill=bg)
    w = (255, 255, 255, 255)
    d.line([15, 25, 43, 25], fill=w, width=5)
    d.polygon([(43, 17), (55, 25), (43, 33)], fill=w)
    d.line([21, 41, 49, 41], fill=w, width=5)
    d.polygon([(21, 33), (9, 41), (21, 49)], fill=w)
    return img

def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((pl.DEFAULT_IP, 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "?"

def add_firewall_rule():
    args = ('advfirewall firewall add rule name="PartageLAN 7365" '
            'dir=in action=allow protocol=TCP localport=7365')
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Start-Process netsh -ArgumentList '{args}' -Verb RunAs"],
        check=False)

# --------------------------------------------------------------------------- #
#  Icone tray : clic GAUCHE = ouvrir la fenetre ET afficher le menu           #
# --------------------------------------------------------------------------- #
class TrayIcon(pystray.Icon):
    """Surcharge du backend Win32 de pystray : clic gauche ouvre la fenetre PUIS
    affiche le menu ; clic droit affiche le menu."""

    def _popup_menu(self):
        if not getattr(self, "_menu_handle", None):
            return
        _w32.SetForegroundWindow(self._hwnd)
        point = wintypes.POINT()
        _w32.GetCursorPos(ctypes.byref(point))
        hmenu, descriptors = self._menu_handle
        index = _w32.TrackPopupMenuEx(
            hmenu,
            _w32.TPM_RIGHTALIGN | _w32.TPM_BOTTOMALIGN | _w32.TPM_RETURNCMD,
            point.x, point.y, self._menu_hwnd, None)
        if index > 0:
            descriptors[index - 1](self)

    def _on_notify(self, wparam, lparam):
        if lparam == _w32.WM_LBUTTONUP:
            try:
                self()
            except Exception:
                pass
            self._popup_menu()
        elif lparam == _w32.WM_RBUTTONUP:
            self._popup_menu()


# --------------------------------------------------------------------------- #
#  Application                                                                 #
# --------------------------------------------------------------------------- #
class App:
    def __init__(self):
        ensure_config_dir()
        self.cfg = load_config()
        self.quitting = False
        self.peer_online = False
        self.peer_name = "vemao"
        self.peer_os = "macOS"
        self.log_lines = []

        # ecoute
        self.listen_stop = threading.Event()
        self.listener_thread = None
        self._srv = None

        # presse-papier (anti-echo)
        self._clip_last_seen = ""
        self._clip_last_applied = ""

        # UI (cree a la demande)
        self.win = None
        self.log_widget = None
        self.status_var = None
        self.local_tv = None
        self.remote_tv = None
        self._local_entries = []
        self._remote_entries = []
        self._local_path = self.cfg.get("local_path") or os.path.expanduser("~")
        self._remote_path = self.cfg.get("remote_path") or "~"
        self._scan_hosts = []
        self.ic_folder = None
        self.ic_file = None
        self._style = None
        self._vars = {}     # StringVars de la fenetre

        self.root = tk.Tk()
        self.root.withdraw()
        self._dnd_ok = False
        if tkinterdnd2 is not None:
            try:
                tkinterdnd2.TkinterDnD._require(self.root)
                self._dnd_ok = True
            except Exception:
                self._dnd_ok = False
        self._drag_anchor = ""
        self.icon = TrayIcon(APP_NAME, make_icon_image(False), APP_NAME, menu=self._menu())

    # ---- helpers threads ---------------------------------------------------
    def ui(self, fn):
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def run_bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def log(self, msg):
        line = f"{datetime.now().strftime('%H:%M:%S')}  {msg}"
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-800:]
        def upd():
            if self.log_widget is not None and self.log_widget.winfo_exists():
                self.log_widget.configure(state="normal")
                self.log_widget.insert("end", line + "\n")
                self.log_widget.see("end")
                self.log_widget.configure(state="disabled")
        self.ui(upd)

    def notify(self, message, title=APP_NAME):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    # ---- menu tray ---------------------------------------------------------
    def _menu(self):
        Item = pystray.MenuItem
        Sep = pystray.Menu.SEPARATOR
        return pystray.Menu(
            Item("Ouvrir PartageLAN", self.on_open, default=True),
            Sep,
            Item(lambda i: f"Mac {self.peer_name} ({self.cfg['peer_ip']}) : "
                           f"{'en ligne' if self.peer_online else 'absent'}",
                 None, enabled=False),
            Sep,
            Item("Envoyer un fichier au Mac…", self.on_send_file),
            Item("Envoyer le presse-papier", self.on_send_clip),
            Item("Ouvrir le dossier de réception", self.on_open_recv),
            Sep,
            Item("Écoute active (recevoir du Mac)", self.on_toggle_listen,
                 checked=lambda i: self.listen_active()),
            Item("Lancer au démarrage", self.on_toggle_autostart,
                 checked=lambda i: is_autostart_enabled()),
            Item("Autoriser dans le pare-feu (admin)…", self.on_firewall),
            Sep,
            Item("Quitter", self.on_quit),
        )

    # ---- cycle de vie ------------------------------------------------------
    def run(self):
        if self.cfg.get("listen", True):
            self.start_listener()
        threading.Thread(target=self.poll_peer, daemon=True).start()
        threading.Thread(target=self._clip_poller, daemon=True).start()
        self.icon.run_detached()
        self.ui(lambda: self.notify("PartageLAN est actif dans la zone de notification.", APP_NAME))
        self.root.mainloop()

    def on_quit(self, icon=None, item=None):
        self.quitting = True
        if self.win is not None and self.win.winfo_exists():
            try:
                self.cfg["geometry"] = self.win.geometry()
            except Exception:
                pass
        save_config(self.cfg)
        self.stop_listener()
        try:
            self.icon.stop()
        except Exception:
            pass
        self.ui(self.root.quit)

    # ---- statut du pair ----------------------------------------------------
    def poll_peer(self):
        while not self.quitting:
            online, name, osd = False, self.peer_name, self.peer_os
            try:
                with pl.connect(self.cfg["peer_ip"], timeout=1.5) as s:
                    s.sendall(pl.frame_bytes({"type": "ping"}))
                    r = pl.read_frame(s)
                    if r.get("type") == "pong":
                        online = True
                        name = r.get("name") or name
                        osd = r.get("text") or osd
            except Exception:
                online = False
            changed = (online != self.peer_online) or (name != self.peer_name) or (osd != self.peer_os)
            self.peer_online, self.peer_name, self.peer_os = online, name, osd
            if changed:
                try:
                    self.icon.icon = make_icon_image(online)
                    self.icon.title = f"PartageLAN — {name} {'en ligne' if online else 'absent'}"
                    self.icon.update_menu()
                except Exception:
                    pass
                self._refresh_status()
            for _ in range(8):
                if self.quitting:
                    return
                time.sleep(1)

    def _refresh_status(self):
        def upd():
            if self.status_var is not None:
                if self.peer_online:
                    self.status_var.set(f"● Mac {self.peer_name} en ligne — {self.peer_os}")
                else:
                    self.status_var.set(f"○ Mac {self.peer_name} ({self.cfg['peer_ip']}) injoignable")
            v = self._vars.get("remote_sub")
            if v is not None:
                v.set(f"{self.cfg['peer_ip']} · {self.peer_os}")
            v = self._vars.get("remote_title")
            if v is not None:
                v.set(f"Machine distante — {self.peer_name}")
        self.ui(upd)

    # ---- ecoute (serveur) --------------------------------------------------
    def listen_active(self):
        return self.listener_thread is not None and self.listener_thread.is_alive()

    def start_listener(self):
        if self.listen_active():
            return
        self.listen_stop.clear()
        self.listener_thread = threading.Thread(target=self._serve, daemon=True)
        self.listener_thread.start()

    def stop_listener(self):
        self.listen_stop.set()
        try:
            if self._srv:
                self._srv.close()
        except Exception:
            pass

    def _serve(self):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("0.0.0.0", pl.PORT))
            srv.listen(16)
            srv.settimeout(1.0)
            self._srv = srv
            self.log(f"Écoute active sur le port {pl.PORT} (nom réseau : {pl.MACHINE_NAME})")
        except Exception as e:
            self.log(f"Écoute impossible : {e} — autorise le port {pl.PORT} au pare-feu.")
            return
        while not self.listen_stop.is_set():
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(conn, addr), daemon=True).start()
        try:
            srv.close()
        except Exception:
            pass
        self.log("Écoute arrêtée")

    @staticmethod
    def _dir_for_ls(path):
        """Resout un chemin recu pour un 'ls'. Un chemin macOS herite (/Users/...)
        qui n'existe pas sur Windows retombe sur l'accueil de winjeux, pour que le
        Mac affiche quand meme les dossiers de winjeux au lieu d'une erreur."""
        p = pl.expand_win(path)
        if os.path.isdir(p):
            return p
        if not path or path.startswith("/") or path.startswith("~"):
            return os.path.expanduser("~")
        return None   # vrai "introuvable" pour un chemin Windows explicite

    def _handle_conn(self, conn, addr):
        conn.settimeout(60.0)
        try:
            meta = pl.read_frame(conn)
            t = meta.get("type")
            if t == "ping":
                conn.sendall(pl.frame_bytes(
                    {"type": "pong", "name": pl.MACHINE_NAME, "text": pl.os_desc()}))
                self.log("Ping reçu de l'autre machine ✓")
            elif t == "clip":
                txt = meta.get("text") or ""
                if self.cfg.get("clip_mode", "both") in ("both", "receive"):
                    pl.clip_set(txt)
                    self._clip_last_applied = txt
                    self._clip_last_seen = txt
                    self.log(f"Presse-papier reçu de {addr[0]} ({len(txt)} car.)")
                    self.notify("Presse-papier reçu du Mac", APP_NAME)
            elif t == "file":
                name = os.path.basename(meta.get("name") or "fichier_recu")
                size = int(meta.get("size") or 0)
                dest = pl.unique_path(self.cfg["recv_dir"], name)
                with open(dest, "wb") as f:
                    remaining = size
                    while remaining > 0:
                        chunk = conn.recv(min(remaining, pl.CHUNK))
                        if not chunk:
                            break
                        f.write(chunk)
                        remaining -= len(chunk)
                self.log(f"Reçu : {name} ({pl.human(size)}) → {dest}")
                self.notify(f"Fichier reçu du Mac : {name}", APP_NAME)
            elif t == "ls":
                p = self._dir_for_ls(meta.get("path"))
                if p is None:
                    conn.sendall(pl.frame_bytes(
                        {"type": "err", "text": f"Dossier introuvable : {meta.get('path')}"}))
                else:
                    conn.sendall(pl.frame_bytes(
                        {"type": "lsr", "name": pl.MACHINE_NAME, "text": pl.os_desc(),
                         "path": p, "entries": pl.list_dir(p)}))
            elif t == "get":
                p = pl.expand_win(meta.get("path"))
                if not os.path.isfile(p):
                    conn.sendall(pl.frame_bytes({"type": "err", "text": f"Fichier introuvable : {p}"}))
                else:
                    size = os.path.getsize(p)
                    conn.sendall(pl.frame_bytes({"type": "file", "name": os.path.basename(p), "size": size}))
                    with open(p, "rb") as f:
                        while True:
                            chunk = f.read(pl.CHUNK)
                            if not chunk:
                                break
                            conn.sendall(chunk)
        except Exception as e:
            self.log(f"[écoute] erreur {addr[0]} : {e}")
        finally:
            conn.close()

    # ---- presse-papier partage --------------------------------------------
    def _clip_poller(self):
        try:
            self._clip_last_seen = pl.clip_get() or ""
        except Exception:
            self._clip_last_seen = ""
        while not self.quitting:
            if self.cfg.get("clip_mode", "both") in ("both", "send"):
                try:
                    cur = pl.clip_get() or ""
                except Exception:
                    cur = ""
                if cur and cur != self._clip_last_seen and cur != self._clip_last_applied:
                    self._clip_last_seen = cur
                    try:
                        with pl.connect(self.cfg["peer_ip"], timeout=2.0) as s:
                            s.sendall(pl.frame_bytes({"type": "clip", "text": cur}))
                        self.log(f"Presse-papier envoyé au Mac ({len(cur)} car.)")
                    except Exception:
                        pass
                else:
                    self._clip_last_seen = cur
            for _ in range(6):
                if self.quitting:
                    return
                time.sleep(0.1)

    # ---- actions du menu ---------------------------------------------------
    def on_open(self, icon=None, item=None):
        self.ui(self._show_window)

    def on_open_recv(self, icon=None, item=None):
        os.makedirs(self.cfg["recv_dir"], exist_ok=True)
        os.startfile(self.cfg["recv_dir"])

    def on_send_file(self, icon=None, item=None):
        self.ui(self._pick_and_send)

    def _pick_and_send(self):
        paths = filedialog.askopenfilenames(title="Fichier(s) à envoyer au Mac")
        for p in paths:
            self.run_bg(lambda p=p: self._push(p, self._remote_path))

    def _push(self, path, destdir=None):
        try:
            size = os.path.getsize(path)
            name = os.path.basename(path)
            meta = {"type": "file", "name": name, "size": size}
            if destdir:
                meta["path"] = destdir
            with pl.connect(self.cfg["peer_ip"]) as s:
                s.sendall(pl.frame_bytes(meta))
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(pl.CHUNK)
                        if not chunk:
                            break
                        s.sendall(chunk)
            self.log(f"Envoyé : {name} ({pl.human(size)}) → {self.cfg['peer_ip']}:{destdir or '(réception)'}")
            self.notify(f"Envoyé au Mac : {name}", APP_NAME)
        except Exception as e:
            self.log(f"Échec de l'envoi : {e}")

    def on_send_clip(self, icon=None, item=None):
        self.run_bg(self._send_clip)

    def _send_clip(self):
        try:
            text = pl.clip_get()
            if not text:
                self.notify("Presse-papier Windows vide.", APP_NAME)
                return
            with pl.connect(self.cfg["peer_ip"]) as s:
                s.sendall(pl.frame_bytes({"type": "clip", "text": text}))
            self.log(f"Presse-papier envoyé au Mac ({len(text)} car.)")
            self.notify("Presse-papier envoyé au Mac", APP_NAME)
        except Exception as e:
            self.log(f"Échec presse-papier : {e}")

    def on_toggle_listen(self, icon=None, item=None):
        if self.listen_active():
            self.stop_listener()
            self.cfg["listen"] = False
        else:
            self.cfg["listen"] = True
            self.start_listener()
        save_config(self.cfg)
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def on_toggle_autostart(self, icon=None, item=None):
        try:
            set_autostart(not is_autostart_enabled())
        except Exception as e:
            self.log(f"Autostart : {e}")
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def on_firewall(self, icon=None, item=None):
        self.run_bg(add_firewall_rule)
        self.notify("Confirme la fenêtre Windows (UAC) pour ouvrir le port 7365.", APP_NAME)

    # ======================================================================= #
    #  FENETRE PRINCIPALE — deux panneaux facon Transmit                      #
    # ======================================================================= #
    def _ensure_icons(self):
        if self.ic_folder is not None:
            return
        fol = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        d = ImageDraw.Draw(fol)
        d.polygon([(1, 5), (6, 5), (7, 3), (1, 3)], fill=(84, 150, 230, 255))
        d.rounded_rectangle([1, 4, 14, 13], radius=2, fill=(84, 150, 230, 255))
        self.ic_folder = ImageTk.PhotoImage(fol)
        doc = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        d = ImageDraw.Draw(doc)
        d.rectangle([3, 1, 12, 14], fill=(225, 225, 230, 255), outline=(150, 150, 155, 255))
        d.line([5, 5, 10, 5], fill=(150, 150, 155, 255))
        d.line([5, 8, 10, 8], fill=(150, 150, 155, 255))
        self.ic_file = ImageTk.PhotoImage(doc)

    def _apply_theme(self, key):
        p = PALETTES[resolve_theme_key(key)]
        st = self._style
        st.theme_use("clam")
        st.configure(".", background=p["bg"], foreground=p["fg"])
        st.configure("TFrame", background=p["bg"])
        st.configure("TLabel", background=p["bg"], foreground=p["fg"])
        st.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
        st.configure("Err.TLabel", background=p["bg"], foreground=p["err"])
        st.configure("Head.TLabel", background=p["bg"], foreground=p["fg"],
                     font=("Segoe UI", 11, "bold"))
        st.configure("TButton", background=p["btn"], foreground=p["fg"], borderwidth=1)
        st.map("TButton", background=[("active", p["btn_active"])])
        st.configure("TMenubutton", background=p["btn"], foreground=p["fg"])
        st.configure("TEntry", fieldbackground=p["list_bg"], foreground=p["fg"],
                     insertcolor=p["fg"])
        st.configure("TCombobox", fieldbackground=p["list_bg"], foreground=p["fg"],
                     background=p["btn"], arrowcolor=p["fg"])
        st.configure("Treeview", background=p["list_bg"], fieldbackground=p["list_bg"],
                     foreground=p["list_fg"], rowheight=22)
        st.map("Treeview", background=[("selected", p["sel_bg"])],
               foreground=[("selected", p["sel_fg"])])
        st.configure("TScrollbar", background=p["btn"], troughcolor=p["bg"])
        if self.win is not None:
            self.win.configure(bg=p["bg"])
        if self.log_widget is not None:
            self.log_widget.configure(bg=p["log_bg"], fg=p["log_fg"], insertbackground=p["fg"])

    def _show_window(self):
        if self.win is not None and self.win.winfo_exists():
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            self._local_refresh()
            self._remote_refresh()
            return

        self._ensure_icons()
        w = tk.Toplevel(self.root)
        self.win = w
        w.title("Partage LAN — winjeux")
        try:
            w.geometry(self.cfg.get("geometry", "1140x760"))
        except Exception:
            w.geometry("1140x760")
        w.minsize(900, 560)
        w.protocol("WM_DELETE_WINDOW", self._hide_window)
        self._style = ttk.Style(w)

        # ---- barre haute : presse-papier / theme ----
        top = ttk.Frame(w); top.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(top, text="Presse-papier :").pack(side="left")
        clip_var = tk.StringVar(value=CLIP_MODE_TO_LABEL.get(self.cfg.get("clip_mode", "both")))
        self._vars["clip"] = clip_var
        cb_clip = ttk.Combobox(top, textvariable=clip_var, values=CLIP_LABELS,
                               state="readonly", width=16)
        cb_clip.pack(side="left", padx=6)
        cb_clip.bind("<<ComboboxSelected>>", lambda e: self._on_clip_mode(clip_var.get()))

        theme_var = tk.StringVar(value=self.cfg.get("theme", "Clair"))
        self._vars["theme"] = theme_var
        cb_theme = ttk.Combobox(top, textvariable=theme_var, values=THEME_LABELS,
                                state="readonly", width=16)
        cb_theme.pack(side="right")
        ttk.Label(top, text="Thème :").pack(side="right", padx=(0, 6))
        cb_theme.bind("<<ComboboxSelected>>", lambda e: self._on_theme(theme_var.get()))

        self.status_var = tk.StringVar(value="…")

        # ---- zone des panneaux ----
        body = ttk.Frame(w); body.pack(fill="both", expand=True, padx=12, pady=4)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0)
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=1)

        # panneau local (gauche)
        left = ttk.Frame(body); left.grid(row=0, column=0, sticky="nsew")
        lhead = ttk.Frame(left); lhead.pack(fill="x")
        ttk.Label(lhead, text="Machine locale — winjeux", style="Head.TLabel").pack(side="left")
        ttk.Label(left, text=f"{local_ip()} · {pl.os_desc()}", style="Muted.TLabel").pack(anchor="w")
        lnav = ttk.Frame(left); lnav.pack(fill="x", pady=4)
        ttk.Button(lnav, text="↑", width=3, command=self._local_up).pack(side="left")
        lpath = tk.StringVar(value=self._local_path); self._vars["local_path"] = lpath
        e = ttk.Entry(lnav, textvariable=lpath); e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<Return>", lambda ev: self._local_go(lpath.get()))
        ttk.Button(lnav, text="⟳", width=3, command=self._local_refresh).pack(side="left")
        self.local_tv = self._make_tree(left)
        self.local_tv.bind("<Double-1>", self._on_local_double)
        self.local_tv.bind("<<TreeviewSelect>>", lambda e: self._update_counts())
        self._setup_tree_interactions(self.local_tv, "local")
        lcount = tk.StringVar(value=""); self._vars["local_count"] = lcount
        ttk.Label(left, textvariable=lcount, style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

        # colonne centrale : -> et <-
        mid = ttk.Frame(body); mid.grid(row=0, column=1, sticky="ns", padx=8)
        ttk.Frame(mid).pack(expand=True)
        ttk.Button(mid, text="→", width=4, command=self._copy_to_remote).pack(pady=6)
        ttk.Button(mid, text="←", width=4, command=self._copy_to_local).pack(pady=6)
        ttk.Frame(mid).pack(expand=True)

        # panneau distant (droite)
        right = ttk.Frame(body); right.grid(row=0, column=2, sticky="nsew")
        rhead = ttk.Frame(right); rhead.pack(fill="x")
        rtitle = tk.StringVar(value=f"Machine distante — {self.peer_name}")
        self._vars["remote_title"] = rtitle
        ttk.Label(rhead, textvariable=rtitle, style="Head.TLabel").pack(side="left")
        rtools = ttk.Frame(rhead); rtools.pack(side="right")
        ip_var = tk.StringVar(value=self.cfg["peer_ip"]); self._vars["ip"] = ip_var
        ttk.Entry(rtools, textvariable=ip_var, width=12).pack(side="left")
        ttk.Button(rtools, text="Tester", command=self._on_test).pack(side="left", padx=4)
        self._scan_btn = ttk.Menubutton(rtools, text="Scanner ▾")
        self._scan_menu = tk.Menu(self._scan_btn, tearoff=0)
        self._scan_btn["menu"] = self._scan_menu
        self._rebuild_scan_menu()
        self._scan_btn.pack(side="left")
        rsub = tk.StringVar(value=f"{self.cfg['peer_ip']} · {self.peer_os}")
        self._vars["remote_sub"] = rsub
        ttk.Label(right, textvariable=rsub, style="Muted.TLabel").pack(anchor="w")
        rnav = ttk.Frame(right); rnav.pack(fill="x", pady=4)
        ttk.Button(rnav, text="↑", width=3, command=self._remote_up).pack(side="left")
        rpath = tk.StringVar(value=self._remote_path); self._vars["remote_path"] = rpath
        e = ttk.Entry(rnav, textvariable=rpath); e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<Return>", lambda ev: self._remote_go(rpath.get()))
        ttk.Button(rnav, text="⟳", width=3, command=self._remote_refresh).pack(side="left")
        self.remote_tv = self._make_tree(right)
        self.remote_tv.bind("<Double-1>", self._on_remote_double)
        self.remote_tv.bind("<<TreeviewSelect>>", lambda e: self._update_counts())
        self._setup_tree_interactions(self.remote_tv, "remote")
        rcount = tk.StringVar(value=""); self._vars["remote_count"] = rcount
        ttk.Label(right, textvariable=rcount, style="Err.TLabel").pack(anchor="w", pady=(2, 0))

        # ---- bas : reception + statut ----
        bottom = ttk.Frame(w); bottom.pack(fill="x", padx=12, pady=(2, 2))
        ttk.Label(bottom, text="Fichiers poussés par l'autre machine reçus dans :").pack(side="left")
        recv = tk.StringVar(value=self._short(self.cfg["recv_dir"])); self._vars["recv"] = recv
        ttk.Label(bottom, textvariable=recv, style="Muted.TLabel").pack(side="left", padx=4)
        ttk.Button(bottom, text="Choisir…", command=self._choose_recvdir).pack(side="left")
        ttk.Button(bottom, text="Ouvrir", command=self.on_open_recv).pack(side="left", padx=4)
        ttk.Label(bottom,
                  text=f"Ici : {pl.MACHINE_NAME} ({local_ip()}) — à l'écoute sur le port {pl.PORT}",
                  style="Muted.TLabel").pack(side="right")

        # ---- ligne SSH ----
        sshrow = ttk.Frame(w); sshrow.pack(fill="x", padx=12, pady=(0, 2))
        ttk.Label(sshrow, text="SSH :").pack(side="left")
        ssh_host = tk.StringVar(value=self.cfg.get("ssh_host") or f"{self.peer_name}@{self.cfg['peer_ip']}")
        self._vars["ssh_host"] = ssh_host
        ttk.Entry(sshrow, textvariable=ssh_host, width=22).pack(side="left", padx=4)
        ssh_dir = tk.StringVar(value=self.cfg.get("ssh_dir", "")); self._vars["ssh_dir"] = ssh_dir
        ttk.Entry(sshrow, textvariable=ssh_dir, width=28).pack(side="left", padx=4)
        ttk.Button(sshrow, text="Terminal SSH", command=self._open_ssh).pack(side="left", padx=4)
        ttk.Button(sshrow, text="Terminal partagé", command=self._open_shared_terminal).pack(side="left")

        # ---- journal ----
        logrow = ttk.Frame(w); logrow.pack(fill="both", padx=12, pady=(0, 10))
        self.log_widget = scrolledtext.ScrolledText(logrow, height=7, state="disabled",
                                                     font=("Consolas", 9), wrap="none",
                                                     relief="solid", borderwidth=1)
        self.log_widget.pack(side="left", fill="both", expand=True)
        ttk.Button(logrow, text="⧉", width=3, command=self._copy_log).pack(side="left", padx=(4, 0))
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", "\n".join(self.log_lines[-200:]) + ("\n" if self.log_lines else ""))
        self.log_widget.configure(state="disabled")
        self.log_widget.see("end")

        self._apply_theme(THEME_LABEL_TO_KEY.get(self.cfg.get("theme", "Clair"), "clair"))
        self._refresh_status()
        self._local_go(self._local_path)
        self._remote_go(self._remote_path)

    def _make_tree(self, parent):
        wrap = ttk.Frame(parent); wrap.pack(fill="both", expand=True)
        tv = ttk.Treeview(wrap, columns=("size",), selectmode="extended", show="tree headings")
        tv.heading("#0", text="Nom")
        tv.heading("size", text="Taille")
        tv.column("#0", width=300, anchor="w")
        tv.column("size", width=90, anchor="e", stretch=False)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return tv

    # ---- interactions souris : clic-droit, glisser-selection, glisser-deposer
    def _setup_tree_interactions(self, tv, kind):
        tv.bind("<Button-3>", lambda e: self._popup_ctx(e, kind))
        tv.bind("<ButtonPress-1>", lambda e: self._drag_press(tv, e), add="+")
        tv.bind("<B1-Motion>", lambda e: self._drag_select(tv, e), add="+")
        if self._dnd_ok:
            try:
                tv.drop_target_register(DND_FILES)
                tv.dnd_bind("<<Drop>>", lambda e: self._on_drop(e, kind))
            except Exception:
                pass

    def _drag_press(self, tv, e):
        self._drag_anchor = tv.identify_row(e.y)

    def _drag_select(self, tv, e):
        cur = tv.identify_row(e.y)
        anchor = self._drag_anchor
        if not cur or not anchor:
            return
        try:
            a, b = int(anchor), int(cur)
        except ValueError:
            return
        lo, hi = (a, b) if a <= b else (b, a)
        tv.selection_set([str(i) for i in range(lo, hi + 1)])
        self._update_counts()

    def _popup_ctx(self, event, kind):
        tv = self.local_tv if kind == "local" else self.remote_tv
        row = tv.identify_row(event.y)
        if row and row not in tv.selection():
            tv.selection_set(row)
            self._update_counts()
        m = tk.Menu(tv, tearoff=0)
        if kind == "local":
            m.add_command(label="Envoyer au Mac  →", command=self._copy_to_remote)
            m.add_command(label="Ouvrir dans l'Explorateur", command=lambda: self._reveal_local(row))
            m.add_separator()
            m.add_command(label="Actualiser", command=self._local_refresh)
        else:
            m.add_command(label="Récupérer  ←", command=self._copy_to_local)
            m.add_command(label="Ouvrir le dossier", command=lambda: self._enter_remote(row))
            m.add_command(label="Terminal SSH ici", command=lambda: self._ssh_here(row))
            m.add_separator()
            m.add_command(label="Actualiser", command=self._remote_refresh)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _reveal_local(self, row):
        try:
            if not row:
                os.startfile(self._local_path)
                return
            full = os.path.join(self._local_path, self._local_entries[int(row)]["name"])
            subprocess.Popen(["explorer", "/select,", full])
        except Exception:
            pass

    def _enter_remote(self, row):
        if not row:
            return
        e = self._remote_entries[int(row)]
        if e["isDir"]:
            self._remote_go(f"{self._remote_path.rstrip('/')}/{e['name']}")

    def _ssh_here(self, row):
        path = self._remote_path
        if row:
            e = self._remote_entries[int(row)]
            if e["isDir"]:
                path = f"{self._remote_path.rstrip('/')}/{e['name']}"
        self._vars["ssh_dir"].set(path)
        self._open_ssh()

    def _on_drop(self, event, kind):
        try:
            paths = list(self.win.tk.splitlist(event.data))
        except Exception:
            paths = [event.data]
        files = [p for p in paths if os.path.isfile(p)]
        if not files:
            self.notify("Glisse des fichiers (les dossiers ne sont pas gérés).", APP_NAME)
            return
        if kind == "remote":
            dest = self._remote_path
            def work():
                for p in files:
                    self._push(p, dest)
                self.ui(self._remote_refresh)
            self.run_bg(work)
        else:
            import shutil
            def work():
                for p in files:
                    try:
                        dst = pl.unique_path(self._local_path, os.path.basename(p))
                        shutil.copy2(p, dst)
                        self.log(f"Copié dans {self._local_path} : {os.path.basename(p)}")
                    except Exception as ex:
                        self.log(f"Échec copie {os.path.basename(p)} : {ex}")
                self.ui(self._local_refresh)
            self.run_bg(work)

    def _default_ssh_host(self):
        return self._vars["ssh_host"].get().strip() or f"{self.peer_name}@{self.cfg['peer_ip']}"

    def _launch_terminal(self, host, remote, fname, title):
        """Ecrit un petit .cmd et l'ouvre dans une console (evite l'enfer des guillemets)."""
        try:
            ensure_config_dir()
            path = os.path.join(CONFIG_DIR, fname)
            sshline = f'ssh -t {host} "{remote}"' if remote else f"ssh {host}"
            content = "\r\n".join(["@echo off", f"title {title}",
                                   f"echo Connexion a {host} ...", sshline,
                                   "echo.", "echo Session terminee.", "pause"])
            with open(path, "w", encoding="ascii", errors="ignore") as f:
                f.write(content)
            subprocess.Popen(["cmd", "/c", "start", "", path])
            self.log(f"{title} -> {host}")
        except Exception as e:
            self.log(f"Echec {title} : {e}")

    def _open_shared_terminal(self):
        host = self._default_ssh_host()
        self._vars["ssh_host"].set(host)
        self.cfg["ssh_host"] = host
        save_config(self.cfg)
        # Meme nom de session que l'app Mac ("partagelan") => terminal reellement partage.
        # PATH ajoute pour trouver tmux (Homebrew/MacPorts) dans un shell SSH non-interactif.
        remote = ("export PATH=/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:$PATH; "
                  "command -v tmux >/dev/null 2>&1 || { echo tmux introuvable sur le Mac; exec $SHELL -l; }; "
                  "tmux new-session -A -s partagelan")
        self._launch_terminal(host, remote, "_term_partage.cmd", "PartageLAN - Terminal partage")

    def _hide_window(self):
        try:
            self.cfg["geometry"] = self.win.geometry()
            save_config(self.cfg)
        except Exception:
            pass
        self.win.withdraw()

    # ---- panneau local (Windows) ------------------------------------------
    def _local_go(self, path):
        path = os.path.expanduser(path.strip()) if path else self._local_path
        if not os.path.isdir(path):
            self._vars["local_count"].set(f"Dossier introuvable : {path}")
            return
        self._local_path = os.path.abspath(path)
        self.cfg["local_path"] = self._local_path
        self._vars["local_path"].set(self._local_path)
        self._local_entries = pl.list_dir(self._local_path)
        self._fill_tree(self.local_tv, self._local_entries)
        self._update_counts()

    def _local_up(self):
        parent = os.path.dirname(self._local_path.rstrip("\\/"))
        if parent and os.path.isdir(parent):
            self._local_go(parent)

    def _local_refresh(self):
        self._local_go(self._local_path)

    def _on_local_double(self, event):
        iid = self.local_tv.identify_row(event.y)
        if not iid:
            return
        e = self._local_entries[int(iid)]
        if e["isDir"]:
            self._local_go(os.path.join(self._local_path, e["name"]))

    # ---- panneau distant (Mac, via protocole) -----------------------------
    def _remote_go(self, path):
        path = path.strip() or "~"
        self._vars["remote_count"].set("Chargement…")
        def work():
            try:
                with pl.connect(self.cfg["peer_ip"]) as s:
                    s.sendall(pl.frame_bytes({"type": "ls", "path": path}))
                    r = pl.read_frame(s)
                if r.get("type") == "err":
                    self.ui(lambda: self._vars["remote_count"].set(r.get("text", "Erreur")))
                    return
                self._remote_path = r.get("path", path)
                self.cfg["remote_path"] = self._remote_path
                ents = r.get("entries") or []
                def apply():
                    self._remote_entries = ents
                    self._vars["remote_path"].set(self._remote_path)
                    self._fill_tree(self.remote_tv, ents)
                    self._update_counts()
                self.ui(apply)
            except Exception as ex:
                self.ui(lambda: self._vars["remote_count"].set(f"Erreur : {ex}"))
        self.run_bg(work)

    def _remote_up(self):
        base = self._remote_path.rstrip("/")
        parent = base.rsplit("/", 1)[0] or "/"
        self._remote_go(parent if base not in ("", "/", "~") else "~")

    def _remote_refresh(self):
        self._remote_go(self._remote_path)

    def _on_remote_double(self, event):
        iid = self.remote_tv.identify_row(event.y)
        if not iid:
            return
        e = self._remote_entries[int(iid)]
        base = self._remote_path.rstrip("/")
        target = f"{base}/{e['name']}"
        if e["isDir"]:
            self._remote_go(target)
        else:
            self.run_bg(lambda: self._pull(target, e["name"]))

    # ---- copie ->  et  <- --------------------------------------------------
    def _copy_to_remote(self):
        sel = self.local_tv.selection()
        files = [self._local_entries[int(i)] for i in sel if not self._local_entries[int(i)]["isDir"]]
        if not files:
            self.notify("Sélectionne un ou des fichiers à gauche.", APP_NAME)
            return
        dest = self._remote_path
        def work():
            for e in files:
                self._push(os.path.join(self._local_path, e["name"]), dest)
            self.ui(self._remote_refresh)
        self.run_bg(work)

    def _copy_to_local(self):
        sel = self.remote_tv.selection()
        files = [self._remote_entries[int(i)] for i in sel if not self._remote_entries[int(i)]["isDir"]]
        if not files:
            self.notify("Sélectionne un ou des fichiers à droite.", APP_NAME)
            return
        base = self._remote_path.rstrip("/")
        def work():
            for e in files:
                self._pull(f"{base}/{e['name']}", e["name"], into=self._local_path)
            self.ui(self._local_refresh)
        self.run_bg(work)

    def _pull(self, remote, name, into=None):
        into = into or self.cfg["recv_dir"]
        try:
            os.makedirs(into, exist_ok=True)
            dest = pl.unique_path(into, os.path.basename(name))
            with pl.connect(self.cfg["peer_ip"]) as s:
                s.sendall(pl.frame_bytes({"type": "get", "path": remote}))
                r = pl.read_frame(s)
                if r.get("type") != "file":
                    raise RuntimeError(r.get("text", "réponse inattendue"))
                size = int(r.get("size") or 0)
                with open(dest, "wb") as f:
                    remaining = size
                    while remaining > 0:
                        chunk = s.recv(min(remaining, pl.CHUNK))
                        if not chunk:
                            break
                        f.write(chunk)
                        remaining -= len(chunk)
            self.log(f"Reçu : {name} ({pl.human(size)}) → {dest}")
            self.notify(f"Reçu du Mac : {name}", APP_NAME)
        except Exception as e:
            self.log(f"Échec réception {name} : {e}")

    # ---- remplissage d'un Treeview ----------------------------------------
    def _fill_tree(self, tv, entries):
        tv.delete(*tv.get_children())
        for i, e in enumerate(entries):
            img = self.ic_folder if e.get("isDir") else self.ic_file
            size = "" if e.get("isDir") else pl.human(e.get("size") or 0)
            tv.insert("", "end", iid=str(i), text="  " + e["name"], image=img, values=(size,))

    def _update_counts(self):
        if self.local_tv is not None and self.local_tv.winfo_exists():
            n = len(self._local_entries); k = len(self.local_tv.selection())
            self._vars["local_count"].set(f"{n} éléments — {k} sélectionné(s)")
        if self.remote_tv is not None and self.remote_tv.winfo_exists():
            n = len(self._remote_entries); k = len(self.remote_tv.selection())
            self._vars["remote_count"].set(f"{n} éléments — {k} sélectionné(s)")

    # ---- scan / test ------------------------------------------------------
    def _rebuild_scan_menu(self):
        m = self._scan_menu
        m.delete(0, "end")
        m.add_command(label="Relancer le scan du réseau", command=self._on_scan)
        if self._scan_hosts:
            m.add_separator()
            for ip, user, osd in self._scan_hosts:
                m.add_command(label=f"{ip}  ·  {user} ({osd})",
                              command=lambda ip=ip: self._select_host(ip))

    def _select_host(self, ip):
        self.cfg["peer_ip"] = ip
        self._vars["ip"].set(ip)
        save_config(self.cfg)
        self._on_test()
        self._remote_go("~")

    def _on_scan(self):
        subnet = ".".join(self.cfg["peer_ip"].split(".")[:3]) or "10.0.0"
        self.log(f"Scan du réseau {subnet}.0/24 …")
        def work():
            hosts = []
            def probe(i):
                ip = f"{subnet}.{i}"
                try:
                    s = socket.create_connection((ip, pl.PORT), timeout=0.4)
                    s.settimeout(1.0)
                    s.sendall(pl.frame_bytes({"type": "ping"}))
                    r = pl.read_frame(s); s.close()
                    if r.get("type") == "pong":
                        return (ip, r.get("name"), r.get("text"))
                except Exception:
                    return None
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=64) as ex:
                for res in ex.map(probe, range(1, 255)):
                    if res:
                        hosts.append(res)
            self._scan_hosts = hosts
            self.log(f"Scan terminé — {len(hosts)} machine(s) PartageLAN trouvée(s)")
            def apply():
                self._rebuild_scan_menu()
                if len(hosts) == 1:
                    self._select_host(hosts[0][0])
            self.ui(apply)
        self.run_bg(work)

    def _on_test(self):
        ip = self._vars["ip"].get().strip() or pl.DEFAULT_IP
        self.cfg["peer_ip"] = ip
        save_config(self.cfg)
        self.log(f"Test de {ip} …")
        def work():
            try:
                with pl.connect(ip, timeout=2.0) as s:
                    s.sendall(pl.frame_bytes({"type": "ping"}))
                    r = pl.read_frame(s)
                if r.get("type") == "pong":
                    self.peer_online = True
                    self.peer_name = r.get("name") or self.peer_name
                    self.peer_os = r.get("text") or self.peer_os
                    self.log(f"✓ {ip} répond : {self.peer_name} — {self.peer_os}")
                    self._refresh_status()
                else:
                    self.log(f"Réponse inattendue de {ip}")
            except Exception as e:
                self.log(f"✗ {ip} injoignable : {e}")
        self.run_bg(work)

    # ---- reception / SSH / theme / presse-papier --------------------------
    def _choose_recvdir(self):
        d = filedialog.askdirectory(title="Dossier de réception", initialdir=self.cfg["recv_dir"])
        if d:
            self.cfg["recv_dir"] = d
            self._vars["recv"].set(self._short(d))
            save_config(self.cfg)

    def _open_ssh(self):
        host = self._default_ssh_host()
        self._vars["ssh_host"].set(host)
        rdir = self._vars["ssh_dir"].get().strip()
        self.cfg["ssh_host"] = host
        self.cfg["ssh_dir"] = rdir
        save_config(self.cfg)
        remote = f"cd '{rdir}'; exec $SHELL -l" if rdir else ""
        self._launch_terminal(host, remote, "_term_ssh.cmd", "PartageLAN - Terminal SSH")

    def _on_clip_mode(self, label):
        self.cfg["clip_mode"] = CLIP_LABEL_TO_MODE.get(label, "both")
        save_config(self.cfg)
        self.log(f"Presse-papier : {label}")

    def _on_theme(self, label):
        self.cfg["theme"] = label
        save_config(self.cfg)
        self._apply_theme(THEME_LABEL_TO_KEY.get(label, "clair"))

    def _copy_log(self):
        try:
            txt = "\n".join(self.log_lines)
            self.win.clipboard_clear()
            self.win.clipboard_append(txt)
            self.notify("Journal copié.", APP_NAME)
        except Exception:
            pass

    @staticmethod
    def _short(path, n=40):
        return path if len(path) <= n else "…" + path[-(n - 1):]


_MUTEX = None

def already_running():
    global _MUTEX
    try:
        kernel32 = ctypes.windll.kernel32
        _MUTEX = kernel32.CreateMutexW(None, False, "PartageLAN_winjeux_singleton")
        return kernel32.GetLastError() == 183   # ERROR_ALREADY_EXISTS
    except Exception:
        return False


def main():
    if already_running():
        return
    App().run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        ensure_config_dir()
        with open(os.path.join(CONFIG_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
        raise
