#!/usr/bin/env python3
"""
partagelan_tray.py — application PartageLAN pour Linux (haikubuntu).

Équivalent de l'app macOS : tourne en arrière-plan avec une icône dans la zone de
notification, écoute en permanence (le Mac peut pousser fichiers/presse-papier), se
lance au démarrage (fichier .desktop dans ~/.config/autostart), et ouvre une fenêtre
à deux panneaux façon Transmit (machine locale à gauche, machine distante à droite),
presse-papier partagé, copie ->/<-, scan réseau, thèmes et journal horodaté.

Réutilise le protocole de partagelan.py. Dépendances : pystray, Pillow (UI en tkinter,
glisser-déposer via tkinterdnd2 si présent). Icône : zone de notification XEmbed
(backend gtk forcé sous X11) — clic gauche = ouvrir la fenêtre ET afficher le menu,
clic droit = menu. Relancer l'app quand elle tourne déjà fait apparaître sa fenêtre.
Les fichiers reçus arrivent dans le dossier affiché dans le panneau de gauche ;
chemins des panneaux et géométrie de fenêtre mémorisés en continu (robuste au crash).

Lancement : ./PartageLAN.sh   (ou : .venv/bin/python3 partagelan_tray.py)
"""
import os
import re
import sys
import json
import time
import shlex
import shutil
import socket
import pathlib
import threading
import subprocess
import urllib.parse
from datetime import datetime

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox, scrolledtext

# Icône : sous X11, la « Zone de notification » classique (XEmbed, backend gtk) est
# plus fiable que AppIndicator — icône parfois invisible dans le panneau MATE — et
# rend le clic gauche direct (ouvre la fenêtre). Surchargeable via PYSTRAY_BACKEND.
if not os.environ.get("PYSTRAY_BACKEND") and os.environ.get("DISPLAY") \
        and not os.environ.get("WAYLAND_DISPLAY"):
    os.environ["PYSTRAY_BACKEND"] = "gtk"
import pystray
from PIL import Image, ImageDraw, ImageTk

try:
    import tkinterdnd2
    from tkinterdnd2 import DND_FILES
except Exception:
    tkinterdnd2 = None
    DND_FILES = None

import partagelan as pl   # cœur du protocole (framing, ls/get/push/clip, utilitaires)

APP_NAME = "PartageLAN"
CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME",
                                         os.path.expanduser("~/.config")), "PartageLAN")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
AUTOSTART_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME",
                                            os.path.expanduser("~/.config")), "autostart")
AUTOSTART_PATH = os.path.join(AUTOSTART_DIR, "PartageLAN.desktop")
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
    "listen": True,
    "clip_mode": "both",
    "theme": "Système",
    "local_path": os.path.expanduser("~"),
    "remote_path": "~",
    "geometry": "1140x760",
}

# --------------------------------------------------------------------------- #
#  Palettes de thèmes                                                          #
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

def system_is_dark():
    """Détecte un thème sombre via gsettings (MATE puis GNOME)."""
    probes = [["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
              ["gsettings", "get", "org.mate.interface", "gtk-theme"],
              ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"]]
    for cmd in probes:
        try:
            out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=3, text=True).stdout.strip().lower()
            if "prefer-dark" in out or "dark" in out:
                return True
        except Exception:
            continue
    return False

def resolve_theme_key(key):
    if key == "systeme":
        return "sombre" if system_is_dark() else "clair"
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
#  Lancement au démarrage (~/.config/autostart/PartageLAN.desktop)             #
# --------------------------------------------------------------------------- #
def launch_command():
    return f"{sys.executable} {SCRIPT_PATH}"

def is_autostart_enabled():
    return os.path.isfile(AUTOSTART_PATH)

def set_autostart(enabled):
    if enabled:
        os.makedirs(AUTOSTART_DIR, exist_ok=True)
        icon_png = os.path.join(os.path.dirname(SCRIPT_PATH), "icon.png")
        icon_line = icon_png if os.path.isfile(icon_png) else "network-workgroup"
        with open(AUTOSTART_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join([
                "[Desktop Entry]",
                "Type=Application",
                "Name=PartageLAN",
                "Comment=Presse-papier partagé + copie de fichiers (LAN)",
                f"Exec={launch_command()}",
                f"Icon={icon_line}",
                "Terminal=false",
                "X-GNOME-Autostart-enabled=true",
                "X-MATE-Autostart-Delay=3",
            ]) + "\n")
    else:
        try:
            os.remove(AUTOSTART_PATH)
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

def xdg_open(path):
    subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)

def open_uri_in_file_manager(uri):
    """Ouvre une URI distante (smb://…) dans l'explorateur de fichiers. Contrairement
    à xdg-open/gio open — qui échouent si l'emplacement n'est pas déjà monté — Caja
    monte le partage lui-même (boîte d'authentification graphique au besoin)."""
    for fm in ("caja", "nautilus", "nemo", "thunar", "pcmanfm"):
        if shutil.which(fm):
            subprocess.Popen([fm, uri], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return
    xdg_open(uri)   # dernier recours

def firewall_allow_port():
    """Ouvre le port 7365 dans ufw via pkexec (boîte de dialogue d'authentification).
    Renvoie un message pour le journal."""
    try:
        r = subprocess.run(["systemctl", "is-active", "--quiet", "ufw"])
        if r.returncode != 0:
            return "Pare-feu ufw inactif — rien à ouvrir."
    except Exception:
        pass
    if not shutil.which("pkexec"):
        return ("pkexec introuvable — lance :  sudo ufw allow 7365/tcp comment 'PartageLAN'  "
                "(profil « Admin » dans SudoManager)")
    r = subprocess.run(["pkexec", "sh", "-c", "ufw allow 7365/tcp comment 'PartageLAN'"],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode == 0:
        return "Pare-feu : port 7365 ouvert ✓"
    return (f"Pare-feu : échec ({(r.stdout or '').strip() or 'annulé'}) — lance :  "
            "sudo ufw allow 7365/tcp comment 'PartageLAN'")

# --------------------------------------------------------------------------- #
#  Icône tray : clic GAUCHE = ouvrir la fenêtre ET afficher le menu           #
# --------------------------------------------------------------------------- #
class TrayIcon(pystray.Icon):
    """Surcharge du backend GTK de pystray : clic gauche déclenche l'action par
    défaut (ouvrir la fenêtre) PUIS affiche le menu, comme la version Windows ;
    clic droit affiche le menu seul."""

    def _on_status_icon_activate(self, status_icon):
        self()   # élément par défaut du menu : « Ouvrir PartageLAN »
        try:
            self._on_status_icon_popup_menu(status_icon, 1, 0)
        except Exception:
            pass


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

        # écoute
        self.listen_stop = threading.Event()
        self.listener_thread = None
        self._srv = None

        # presse-papier (anti-écho) — wl-clipboard/xclip/xsel si présents, sinon
        # le presse-papier de Tk (fiable tant que l'app tourne). Tous les accès
        # se font dans le thread Tk (boucle .after), jamais dans un thread.
        self._clip_last_seen = ""
        self._clip_last_applied = ""
        self._clip_tool = pl.clip_backend() in ("wl-clipboard", "xclip", "xsel")

        # UI (créée à la demande)
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
        self._geom_job = None   # débounce de la mémorisation de géométrie
        self._vars = {}     # StringVars de la fenêtre

        if tkinterdnd2 is not None:
            try:
                self.root = tkinterdnd2.TkinterDnD.Tk()
                self._dnd_ok = True
            except Exception:
                self.root = tk.Tk()
                self._dnd_ok = False
        else:
            self.root = tk.Tk()
            self._dnd_ok = False
        self.root.withdraw()
        self._drag_anchor = ""
        try:
            self.icon = TrayIcon(APP_NAME, make_icon_image(False), APP_NAME,
                                 menu=self._menu())
        except Exception:
            self.icon = None   # pas de zone de notification : fenêtre ouverte direct

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
        if shutil.which("notify-send"):
            try:
                subprocess.Popen(["notify-send", "-a", APP_NAME, title, message])
                return
            except Exception:
                pass
        try:
            if self.icon:
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
            Item("Ouvrir le port 7365 (pare-feu)…", self.on_firewall),
            Sep,
            Item("Quitter", self.on_quit),
        )

    # ---- cycle de vie ------------------------------------------------------
    def run(self):
        if self.cfg.get("listen", True):
            self.start_listener()
        threading.Thread(target=self.poll_peer, daemon=True).start()
        if _SINGLETON is not None:
            threading.Thread(target=self._singleton_server, daemon=True).start()
        started = False
        if self.icon is not None:
            try:
                # icon.run() dans un thread dédié : pystray y fait tourner SA boucle
                # GLib. (run_detached() suppose une boucle GLib côté application —
                # or la nôtre est une boucle Tk : rien ne s'afficherait.)
                threading.Thread(target=self.icon.run, daemon=True).start()
                started = True
            except Exception:
                self.icon = None
        if started:
            self.ui(lambda: self.notify("PartageLAN est actif dans la zone de notification.",
                                        APP_NAME))
        else:
            self.ui(self._show_window)   # pas d'icône possible : fenêtre directe
        self.ui(self._clip_start)
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
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
        self.ui(self.root.quit)

    def _singleton_server(self):
        """Toute connexion sur la socket anti-doublon (= relance de l'app) fait
        apparaître la fenêtre."""
        while not self.quitting:
            try:
                conn, _ = _SINGLETON.accept()
            except OSError:
                return
            try:
                conn.close()
            except Exception:
                pass
            self.ui(self._show_window)

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
                    if self.icon:
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

    # ---- écoute (serveur) --------------------------------------------------
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
                    def apply(txt=txt):
                        self._clip_set_ui(txt)
                        self._clip_last_applied = txt
                        self._clip_last_seen = txt
                    self.ui(apply)
                    self.log(f"Presse-papier reçu de {addr[0]} ({len(txt)} car.)")
                    self.notify("Presse-papier reçu du Mac", APP_NAME)
            elif t == "file":
                name = os.path.basename(meta.get("name") or "fichier_recu")
                size = int(meta.get("size") or 0)
                # réception dans le dossier affiché à gauche (sauf destination
                # explicite demandée par l'expéditeur)
                dirpath, warn = pl.recv_file_dir(meta, self._local_path)
                if warn:
                    self.log(warn)
                os.makedirs(dirpath, exist_ok=True)
                dest = pl.unique_path(dirpath, name)
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
                self.ui(self._local_refresh_safe)
            elif t == "ls":
                p = pl.dir_for_ls(meta.get("path"))
                if p is None:
                    conn.sendall(pl.frame_bytes(
                        {"type": "err", "text": f"Dossier introuvable : {meta.get('path')}"}))
                else:
                    conn.sendall(pl.frame_bytes(
                        {"type": "lsr", "name": pl.MACHINE_NAME, "text": pl.os_desc(),
                         "path": p, "entries": pl.list_dir(p)}))
            elif t == "get":
                p = pl.expand_path(meta.get("path"))
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

    # ---- presse-papier partagé (boucle dans le thread Tk) -------------------
    def _clip_get_ui(self):
        if self._clip_tool:
            return pl.clip_get()
        try:
            return self.root.clipboard_get(type="UTF8_STRING")
        except Exception:
            try:
                return self.root.clipboard_get()
            except Exception:
                return ""

    def _clip_set_ui(self, text):
        if self._clip_tool:
            pl.clip_set(text)
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text or "")
        except Exception:
            pass

    def _clip_start(self):
        try:
            self._clip_last_seen = self._clip_get_ui() or ""
        except Exception:
            self._clip_last_seen = ""
        self._clip_tick()

    def _clip_tick(self):
        if self.quitting:
            return
        if self.cfg.get("clip_mode", "both") in ("both", "send"):
            cur = self._clip_get_ui() or ""
            if cur and cur != self._clip_last_seen and cur != self._clip_last_applied:
                self._clip_last_seen = cur
                self.run_bg(lambda cur=cur: self._clip_send(cur))
            else:
                self._clip_last_seen = cur
        self.root.after(600, self._clip_tick)

    def _clip_send(self, text):
        try:
            with pl.connect(self.cfg["peer_ip"], timeout=2.0) as s:
                s.sendall(pl.frame_bytes({"type": "clip", "text": text}))
            self.log(f"Presse-papier envoyé au Mac ({len(text)} car.)")
        except Exception:
            pass

    # ---- actions du menu ---------------------------------------------------
    def on_open(self, icon=None, item=None):
        self.ui(self._show_window)

    def on_open_recv(self, icon=None, item=None):
        xdg_open(self._local_path)   # réception = dossier affiché à gauche

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
        def work():
            text = self._clip_get_ui()
            if not text:
                self.notify("Presse-papier vide.", APP_NAME)
                return
            self.run_bg(lambda: self._send_clip_text(text))
        self.ui(work)   # lecture du presse-papier dans le thread Tk

    def _send_clip_text(self, text):
        try:
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
            if self.icon:
                self.icon.update_menu()
        except Exception:
            pass

    def on_toggle_autostart(self, icon=None, item=None):
        try:
            set_autostart(not is_autostart_enabled())
        except Exception as e:
            self.log(f"Autostart : {e}")
        try:
            if self.icon:
                self.icon.update_menu()
        except Exception:
            pass

    def on_firewall(self, icon=None, item=None):
        self.notify("Confirme la boîte de dialogue d'authentification pour ouvrir le port 7365.",
                    APP_NAME)
        self.run_bg(lambda: self.log(firewall_allow_port()))

    # ======================================================================= #
    #  FENÊTRE PRINCIPALE — deux panneaux façon Transmit                      #
    # ======================================================================= #
    def _ensure_icons(self):
        # icônes 24 px (affichage des panneaux agrandi ×1,5)
        if self.ic_folder is not None:
            return
        fol = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        d = ImageDraw.Draw(fol)
        d.polygon([(2, 8), (9, 8), (11, 5), (2, 5)], fill=(84, 150, 230, 255))
        d.rounded_rectangle([2, 6, 21, 20], radius=3, fill=(84, 150, 230, 255))
        self.ic_folder = ImageTk.PhotoImage(fol)
        doc = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        d = ImageDraw.Draw(doc)
        d.rectangle([5, 2, 18, 21], fill=(225, 225, 230, 255), outline=(150, 150, 155, 255))
        d.line([8, 8, 15, 8], fill=(150, 150, 155, 255))
        d.line([8, 12, 15, 12], fill=(150, 150, 155, 255))
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
                     font=("Sans", 17, "bold"))
        st.configure("TButton", background=p["btn"], foreground=p["fg"], borderwidth=1)
        st.map("TButton", background=[("active", p["btn_active"])])
        st.configure("TMenubutton", background=p["btn"], foreground=p["fg"])
        st.configure("TEntry", fieldbackground=p["list_bg"], foreground=p["fg"],
                     insertcolor=p["fg"])
        st.configure("TCombobox", fieldbackground=p["list_bg"], foreground=p["fg"],
                     background=p["btn"], arrowcolor=p["fg"])
        st.configure("Treeview", background=p["list_bg"], fieldbackground=p["list_bg"],
                     foreground=p["list_fg"], rowheight=33, font=("Sans", 15))
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
        w.title(f"Partage LAN — {pl.MACHINE_NAME}")
        try:
            w.geometry(self.cfg.get("geometry", "1140x760"))
        except Exception:
            w.geometry("1140x760")
        w.minsize(900, 560)
        w.protocol("WM_DELETE_WINDOW", self._hide_window)
        w.bind("<Configure>", self._on_win_configure)
        self._style = ttk.Style(w)

        # Textes ×1,5 (défaut Tk ≈ 10 pt) : les polices nommées couvrent labels,
        # boutons, champs, listes et menus d'un coup.
        for fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(fname).configure(size=15)
            except Exception:
                pass

        # ---- barre haute : presse-papier / thème ----
        top = ttk.Frame(w); top.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(top, text="Presse-papier :").pack(side="left")
        clip_var = tk.StringVar(value=CLIP_MODE_TO_LABEL.get(self.cfg.get("clip_mode", "both")))
        self._vars["clip"] = clip_var
        cb_clip = ttk.Combobox(top, textvariable=clip_var, values=CLIP_LABELS,
                               state="readonly", width=16)
        cb_clip.pack(side="left", padx=6)
        cb_clip.bind("<<ComboboxSelected>>", lambda e: self._on_clip_mode(clip_var.get()))

        theme_var = tk.StringVar(value=self.cfg.get("theme", "Système"))
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
        ttk.Label(lhead, text=f"Machine locale — {pl.MACHINE_NAME}", style="Head.TLabel").pack(side="left")
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

        # ---- bas : réception + statut ----
        bottom = ttk.Frame(w); bottom.pack(fill="x", padx=12, pady=(2, 2))
        ttk.Label(bottom,
                  text="Réception : les fichiers reçus arrivent dans le dossier affiché à gauche").pack(side="left")
        ttk.Button(bottom, text="Ouvrir", command=self.on_open_recv).pack(side="left", padx=6)
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
                                                     font=("Monospace", 14), wrap="none",
                                                     relief="solid", borderwidth=1)
        self.log_widget.pack(side="left", fill="both", expand=True)
        ttk.Button(logrow, text="⧉", width=3, command=self._copy_log).pack(side="left", padx=(4, 0))
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", "\n".join(self.log_lines[-200:]) + ("\n" if self.log_lines else ""))
        self.log_widget.configure(state="disabled")
        self.log_widget.see("end")

        self._apply_theme(THEME_LABEL_TO_KEY.get(self.cfg.get("theme", "Système"), "systeme"))
        self._refresh_status()
        self._local_go(self._local_path)
        self._remote_go(self._remote_path)

    def _make_tree(self, parent):
        wrap = ttk.Frame(parent); wrap.pack(fill="both", expand=True)
        tv = ttk.Treeview(wrap, columns=("size", "mtime"), selectmode="extended",
                          show="tree headings")
        tv.heading("#0", text="Nom")
        tv.heading("size", text="Taille")
        tv.heading("mtime", text="Modifié")
        tv.column("#0", width=380, anchor="w")
        tv.column("size", width=120, anchor="e", stretch=False)
        tv.column("mtime", width=200, anchor="e", stretch=False)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return tv

    # ---- interactions souris : clic-droit, glisser-sélection, glisser-déposer
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
            if row and self._local_entries[int(row)].get("isDir"):
                m.add_command(label="Ouvrir dans l'explorateur de fichiers",
                              command=lambda: self._open_local_dir(row))
            m.add_command(label="Afficher dans le dossier parent",
                          command=lambda: self._reveal_local(row))
            m.add_separator()
            m.add_command(label="Actualiser", command=self._local_refresh)
        else:
            m.add_command(label="Récupérer  ←", command=self._copy_to_local)
            m.add_command(label="Ouvrir le dossier", command=lambda: self._enter_remote(row))
            if row and self._remote_entries[int(row)].get("isDir"):
                m.add_command(label="Ouvrir dans l'explorateur de fichiers (SMB)",
                              command=lambda: self._open_remote_smb(row))
            m.add_command(label="Terminal SSH ici", command=lambda: self._ssh_here(row))
            m.add_separator()
            m.add_command(label="Actualiser", command=self._remote_refresh)
        # Sous X11, tk_popup ne bloque pas : ne PAS relâcher le grab juste après
        # (recette Windows), c'est lui qui ferme le menu quand on clique ailleurs.
        try:
            m.tk_popup(event.x_root, event.y_root)
        except Exception:
            m.grab_release()

    def _open_local_dir(self, row):
        """Ouvre le dossier cliqué dans l'explorateur de fichiers (Caja…)."""
        try:
            full = os.path.join(self._local_path, self._local_entries[int(row)]["name"])
            if os.path.isdir(full):
                xdg_open(full)
        except Exception:
            pass

    def _reveal_local(self, row):
        try:
            if not row:
                xdg_open(self._local_path)
                return
            full = os.path.join(self._local_path, self._local_entries[int(row)]["name"])
            uri = pathlib.Path(full).as_uri()
            r = subprocess.run(
                ["gdbus", "call", "--session",
                 "--dest", "org.freedesktop.FileManager1",
                 "--object-path", "/org/freedesktop/FileManager1",
                 "--method", "org.freedesktop.FileManager1.ShowItems",
                 f'["{uri}"]', ""],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            if r.returncode != 0:
                xdg_open(self._local_path)
        except Exception:
            try:
                xdg_open(self._local_path)
            except Exception:
                pass

    def _open_remote_smb(self, row):
        """Ouvre le dossier distant cliqué dans l'explorateur de fichiers Linux via
        SMB (Partage de fichiers macOS). Le dossier personnel du Mac est exposé comme
        partage au nom du compte : /Users/vemao/… → smb://10.0.0.4/vemao/…
        Hors de /Users, on ouvre la liste des partages du Mac."""
        try:
            e = self._remote_entries[int(row)]
            path = f"{self._remote_path.rstrip('/')}/{e['name']}"
            ip = self.cfg["peer_ip"]
            match = re.match(r"^/Users/([^/]+)(/.*)?$", path)
            if match:
                share, rest = match.group(1), match.group(2) or ""
                uri = f"smb://{ip}/{urllib.parse.quote(share)}{urllib.parse.quote(rest)}"
            else:
                uri = f"smb://{ip}/"
                self.log(f"Chemin hors /Users ({path}) → liste des partages")
            open_uri_in_file_manager(uri)
            self.log(f"Explorateur SMB → {uri}")
        except Exception as ex:
            self.log(f"Échec ouverture SMB : {ex}")

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
            import shutil as _sh
            def work():
                for p in files:
                    try:
                        dst = pl.unique_path(self._local_path, os.path.basename(p))
                        _sh.copy2(p, dst)
                        self.log(f"Copié dans {self._local_path} : {os.path.basename(p)}")
                    except Exception as ex:
                        self.log(f"Échec copie {os.path.basename(p)} : {ex}")
                self.ui(self._local_refresh)
            self.run_bg(work)

    def _default_ssh_host(self):
        return self._vars["ssh_host"].get().strip() or f"{self.peer_name}@{self.cfg['peer_ip']}"

    def _launch_terminal(self, host, remote, fname, title):
        """Écrit un petit .sh et l'ouvre dans un terminal (évite l'enfer des guillemets)."""
        try:
            ensure_config_dir()
            path = os.path.join(CONFIG_DIR, fname)
            # remote est quoté pour que $PATH/$SHELL s'expansent sur la machine
            # DISTANTE (pas dans le bash local qui lance ssh)
            sshline = (f"ssh -t {shlex.quote(host)} {shlex.quote(remote)}"
                       if remote else f"ssh {shlex.quote(host)}")
            content = "\n".join(["#!/bin/bash",
                                 f'echo "Connexion à {host} ..."', sshline,
                                 "echo",
                                 'read -rp "Session terminée — Entrée pour fermer." _'])
            with open(path, "w", encoding="utf-8") as f:
                f.write(content + "\n")
            os.chmod(path, 0o755)
            qpath = shlex.quote(path)
            candidates = [
                ("mate-terminal", ["mate-terminal", "--title", title, "-e", f"bash {qpath}"]),
                ("gnome-terminal", ["gnome-terminal", "--title", title, "--", "bash", path]),
                ("konsole", ["konsole", "-e", "bash", path]),
                ("xfce4-terminal", ["xfce4-terminal", "-T", title, "-e", f"bash {qpath}"]),
                ("x-terminal-emulator", ["x-terminal-emulator", "-e", f"bash {qpath}"]),
                ("xterm", ["xterm", "-T", title, "-e", "bash", path]),
            ]
            for name, cmd in candidates:
                if shutil.which(name):
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.log(f"{title} → {host}")
                    return
            self.log("Aucun terminal graphique trouvé (mate-terminal, gnome-terminal…)")
        except Exception as e:
            self.log(f"Échec {title} : {e}")

    def _open_shared_terminal(self):
        host = self._default_ssh_host()
        self._vars["ssh_host"].set(host)
        self.cfg["ssh_host"] = host
        save_config(self.cfg)
        # Même nom de session que l'app Mac ("partagelan") => terminal réellement partagé.
        # PATH ajouté pour trouver tmux (Homebrew/MacPorts) dans un shell SSH non-interactif.
        remote = ("export PATH=/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:$PATH; "
                  "command -v tmux >/dev/null 2>&1 || { echo tmux introuvable sur le Mac; exec $SHELL -l; }; "
                  "tmux new-session -A -s partagelan")
        self._launch_terminal(host, remote, "_term_partage.sh", "PartageLAN - Terminal partagé")

    def _on_win_configure(self, event):
        """Mémorisation immédiate (débouncée) de la taille et de la position."""
        if event.widget is not self.win:
            return
        if self._geom_job is not None:
            try:
                self.root.after_cancel(self._geom_job)
            except Exception:
                pass
        self._geom_job = self.root.after(500, self._save_geometry)

    def _save_geometry(self):
        self._geom_job = None
        try:
            if self.win is not None and self.win.winfo_exists() \
                    and self.win.state() == "normal":
                self.cfg["geometry"] = self.win.geometry()
                save_config(self.cfg)
        except Exception:
            pass

    def _hide_window(self):
        try:
            self.cfg["geometry"] = self.win.geometry()
            save_config(self.cfg)
        except Exception:
            pass
        self.win.withdraw()

    # ---- panneau local (Linux) ---------------------------------------------
    def _local_go(self, path):
        path = os.path.expanduser(path.strip()) if path else self._local_path
        if not os.path.isdir(path):
            self._vars["local_count"].set(f"Dossier introuvable : {path}")
            return
        self._local_path = os.path.abspath(path)
        self.cfg["local_path"] = self._local_path
        save_config(self.cfg)   # écriture immédiate : conservé même si l'app est tuée
        self._vars["local_path"].set(self._local_path)
        self._local_entries = pl.list_dir(self._local_path)
        self._fill_tree(self.local_tv, self._local_entries)
        self._update_counts()

    def _local_up(self):
        parent = os.path.dirname(self._local_path.rstrip("/"))
        if parent and os.path.isdir(parent):
            self._local_go(parent)

    def _local_refresh(self):
        self._local_go(self._local_path)

    def _local_refresh_safe(self):
        """Rafraîchit le panneau local seulement si la fenêtre existe (les fichiers
        peuvent arriver fenêtre fermée)."""
        if self.win is not None and self.win.winfo_exists():
            self._local_refresh()

    def _on_local_double(self, event):
        iid = self.local_tv.identify_row(event.y)
        if not iid:
            return
        e = self._local_entries[int(iid)]
        if e["isDir"]:
            self._local_go(os.path.join(self._local_path, e["name"]))

    # ---- panneau distant (Mac, via protocole) ------------------------------
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
                save_config(self.cfg)   # écriture immédiate, comme le panneau local
                ents = r.get("entries") or []
                # tri par date quand le pair fournit mtime (l'app Mac ne l'envoie pas :
                # dans ce cas on garde son ordre)
                if any(e.get("mtime") for e in ents):
                    ents = sorted(ents, key=lambda e: e.get("mtime") or 0, reverse=True)
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

    # ---- copie ->  et  <- ---------------------------------------------------
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
        into = into or self._local_path   # réception = dossier affiché à gauche
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
            self.ui(self._local_refresh_safe)
        except Exception as e:
            self.log(f"Échec réception {name} : {e}")

    # ---- remplissage d'un Treeview -----------------------------------------
    @staticmethod
    def _fmt_date(ts):
        try:
            return datetime.fromtimestamp(ts).strftime("%d/%m/%Y %H:%M") if ts else ""
        except Exception:
            return ""

    def _fill_tree(self, tv, entries):
        tv.delete(*tv.get_children())
        for i, e in enumerate(entries):
            img = self.ic_folder if e.get("isDir") else self.ic_file
            size = "" if e.get("isDir") else pl.human(e.get("size") or 0)
            tv.insert("", "end", iid=str(i), text="  " + e["name"], image=img,
                      values=(size, self._fmt_date(e.get("mtime"))))

    def _update_counts(self):
        if self.local_tv is not None and self.local_tv.winfo_exists():
            n = len(self._local_entries); k = len(self.local_tv.selection())
            self._vars["local_count"].set(f"{n} éléments — {k} sélectionné(s)")
        if self.remote_tv is not None and self.remote_tv.winfo_exists():
            n = len(self._remote_entries); k = len(self.remote_tv.selection())
            self._vars["remote_count"].set(f"{n} éléments — {k} sélectionné(s)")

    # ---- scan / test --------------------------------------------------------
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

    # ---- SSH / thème / presse-papier ----------------------------------------
    def _open_ssh(self):
        host = self._default_ssh_host()
        self._vars["ssh_host"].set(host)
        rdir = self._vars["ssh_dir"].get().strip()
        self.cfg["ssh_host"] = host
        self.cfg["ssh_dir"] = rdir
        save_config(self.cfg)
        remote = f"cd '{rdir}'; exec $SHELL -l" if rdir else ""
        self._launch_terminal(host, remote, "_term_ssh.sh", "PartageLAN - Terminal SSH")

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


_SINGLETON = None

def already_running():
    """Anti-doublon via une socket Unix abstraite (libérée automatiquement à la mort
    du processus, même en cas de crash). Si une instance tourne déjà, on lui demande
    d'ouvrir sa fenêtre avant de s'effacer."""
    global _SINGLETON
    addr = f"\0PartageLAN_{pl.MACHINE_NAME}_singleton"
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(addr)
        s.listen(2)
        _SINGLETON = s
        return False
    except OSError:
        try:
            c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            c.settimeout(2.0)
            c.connect(addr)
            c.close()
        except Exception:
            pass
        return True
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
