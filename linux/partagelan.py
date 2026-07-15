#!/usr/bin/env python3
"""
partagelan.py — client Linux pour PartageLAN (app macOS de hpcmao).

Parle le même protocole TCP que l'app Mac, sur le port 7365 :
    trame = [longueur UInt32 big-endian][JSON méta][octets bruts optionnels]
    (la longueur ne couvre QUE le JSON ; le corps d'un fichier suit juste après)
Types : clip | file | ping/pong | ls/lsr | get | err

Dépendances : stdlib Python uniquement. Le presse-papier passe par le premier
outil trouvé : wl-copy/wl-paste (Wayland), xclip ou xsel (X11), sinon GTK
(python3-gi, lecture fiable / écriture au mieux). Recommandé : `apt install xclip`.

Exemples :
    python3 partagelan.py ping
    python3 partagelan.py scan
    python3 partagelan.py ls ~
    python3 partagelan.py push ~/chemin/fichier.zip
    python3 partagelan.py push ~/chemin/fichier.zip ~/Downloads
    python3 partagelan.py pull ~/Documents/note.txt
    python3 partagelan.py send-clip "bonjour le Mac"
    python3 partagelan.py send-clip            (envoie le presse-papier Linux)
    python3 partagelan.py listen               (recevoir du Mac : pair complet)
    python3 partagelan.py --ip 10.0.0.4 ping   (viser une autre IP)
"""
import argparse, socket, struct, json, os, re, sys, subprocess, platform, shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# Sortie en UTF-8 (accents + symboles) même si la locale du terminal est exotique.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_IP = "10.0.0.4"      # vemao ; surchargeable avec --ip
MACHINE_NAME = "haikubuntu"  # nom affiché par le Mac (scan, pong, lsr)
PORT = 7365
MAXLEN = 50_000_000
CHUNK = 1 << 16              # 64 Kio, comme l'app Mac

# --------------------------------------------------------------------------- #
#  Framing bas niveau                                                          #
# --------------------------------------------------------------------------- #
def recvn(sock, n):
    """Lit exactement n octets ou lève EOFError."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("connexion fermée prématurément")
        buf += chunk
    return bytes(buf)

def read_frame(sock):
    """Lit une trame [UInt32 longueur][JSON] et renvoie le dict méta."""
    (ln,) = struct.unpack(">I", recvn(sock, 4))
    if not (0 < ln < MAXLEN):
        raise ValueError(f"longueur de trame invalide : {ln}")
    return json.loads(recvn(sock, ln).decode("utf-8"))

def frame_bytes(meta):
    """Sérialise un dict méta en trame [UInt32 longueur][JSON]."""
    data = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    return struct.pack(">I", len(data)) + data

def connect(ip, timeout=5.0):
    s = socket.create_connection((ip, PORT), timeout=timeout)
    s.settimeout(timeout)
    return s

# --------------------------------------------------------------------------- #
#  Presse-papier Linux : wl-clipboard (Wayland), xclip/xsel (X11), sinon GTK.  #
#  xclip et xsel « forkent » pour rester propriétaires de la sélection X11 :   #
#  le texte collé survit donc à la fin du processus appelant.                  #
# --------------------------------------------------------------------------- #
_CLIP_BACKEND = "?"   # mémoïsé au premier appel

def clip_backend():
    """Renvoie l'outil presse-papier utilisé : wl-clipboard | xclip | xsel | gtk | None."""
    global _CLIP_BACKEND
    if _CLIP_BACKEND == "?":
        if os.environ.get("WAYLAND_DISPLAY") and shutil.which("wl-paste"):
            _CLIP_BACKEND = "wl-clipboard"
        elif shutil.which("xclip"):
            _CLIP_BACKEND = "xclip"
        elif shutil.which("xsel"):
            _CLIP_BACKEND = "xsel"
        else:
            try:
                import gi
                gi.require_version("Gtk", "3.0")
                _CLIP_BACKEND = "gtk"
            except Exception:
                _CLIP_BACKEND = None
    return _CLIP_BACKEND

def _gtk_clipboard():
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk
    return Gtk, Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

def _run_clip(cmd, data=None):
    r = subprocess.run(cmd, input=data, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, timeout=5)
    return r.stdout

def clip_get():
    """Lit le presse-papier (texte). Renvoie '' si vide ou sans outil."""
    b = clip_backend()
    try:
        if b == "wl-clipboard":
            return _run_clip(["wl-paste", "-n"]).decode("utf-8", "replace")
        if b == "xclip":
            return _run_clip(["xclip", "-selection", "clipboard", "-o"]).decode("utf-8", "replace")
        if b == "xsel":
            return _run_clip(["xsel", "-ob"]).decode("utf-8", "replace")
        if b == "gtk":
            _, cb = _gtk_clipboard()
            return cb.wait_for_text() or ""
    except Exception:
        pass
    return ""

def clip_set(text):
    """Écrit du texte dans le presse-papier. Renvoie True si un outil a pris la main."""
    text = text or ""
    b = clip_backend()
    try:
        if b == "wl-clipboard":
            _run_clip(["wl-copy"], text.encode("utf-8"))
            return True
        if b == "xclip":
            _run_clip(["xclip", "-selection", "clipboard", "-i"], text.encode("utf-8"))
            return True
        if b == "xsel":
            _run_clip(["xsel", "-ib"], text.encode("utf-8"))
            return True
        if b == "gtk":
            # Au mieux : persiste si un gestionnaire de presse-papier tourne
            # (mate-settings-daemon en a un). Sinon, préférer xclip.
            Gtk, cb = _gtk_clipboard()
            cb.set_text(text, -1)
            cb.store()
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            return True
    except Exception:
        pass
    return False

# --------------------------------------------------------------------------- #
#  Commandes client : Linux -> Mac                                            #
# --------------------------------------------------------------------------- #
def cmd_ping(ip):
    with connect(ip) as s:
        s.sendall(frame_bytes({"type": "ping"}))
        r = read_frame(s)
    if r.get("type") == "pong":
        print(f"✓ {ip} répond : {r.get('name')} — {r.get('text')}")
    else:
        print(f"? réponse inattendue : {r}")
    return r

def cmd_ls(ip, path):
    with connect(ip) as s:
        s.sendall(frame_bytes({"type": "ls", "path": path}))
        r = read_frame(s)
    if r.get("type") == "err":
        print(f"✗ {r.get('text')}")
        return
    print(f"{r.get('name')}@{ip} : {r.get('path')}")
    for e in r.get("entries") or []:
        d = ""
        if e.get("mtime"):
            try:
                d = "  " + datetime.fromtimestamp(e["mtime"]).strftime("%d/%m/%Y %H:%M")
            except Exception:
                d = ""
        if e.get("isDir"):
            print(f"  [dossier] {e['name']}{d}")
        else:
            print(f"            {e['name']}  ({human(e.get('size') or 0)}){d}")

def cmd_push(ip, filepath, destdir=None):
    filepath = os.path.expanduser(filepath)
    if not os.path.isfile(filepath):
        print(f"✗ Fichier introuvable : {filepath}")
        return
    size = os.path.getsize(filepath)
    name = os.path.basename(filepath)
    meta = {"type": "file", "name": name, "size": size}
    if destdir:
        meta["path"] = destdir
    with connect(ip) as s:
        s.sendall(frame_bytes(meta))
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(CHUNK)
                if not chunk:
                    break
                s.sendall(chunk)
    print(f"✓ Envoyé : {name} ({human(size)}) -> {ip}:{destdir or '(dossier de réception du pair)'}")

def cmd_pull(ip, remotepath, localdir=None):
    localdir = os.path.expanduser(localdir) if localdir else downloads_dir()
    os.makedirs(localdir, exist_ok=True)
    with connect(ip) as s:
        s.sendall(frame_bytes({"type": "get", "path": remotepath}))
        r = read_frame(s)
        if r.get("type") == "err":
            print(f"✗ {r.get('text')}")
            return
        if r.get("type") != "file":
            print(f"✗ réponse inattendue : {r.get('type')}")
            return
        name = os.path.basename(r.get("name") or "fichier_recu")
        size = int(r.get("size") or 0)
        dest = unique_path(localdir, name)
        with open(dest, "wb") as f:
            remaining = size
            while remaining > 0:
                chunk = s.recv(min(remaining, CHUNK))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)
    print(f"✓ Reçu : {name} ({human(size)}) -> {dest}")

def cmd_send_clip(ip, text=None):
    if not text:
        text = clip_get()
    if not text:
        if clip_backend() is None:
            print("✗ Aucun outil presse-papier (installe xclip : sudo apt install xclip)")
        else:
            print("✗ Presse-papier vide (rien à envoyer)")
        return
    with connect(ip) as s:
        s.sendall(frame_bytes({"type": "clip", "text": text}))
    print(f"✓ Presse-papier envoyé à {ip} ({len(text)} caractères)")

def cmd_scan(subnet):
    print(f"Scan de {subnet}.1-254 sur le port {PORT} ...")
    found = []

    def probe(i):
        ip = f"{subnet}.{i}"
        try:
            s = socket.create_connection((ip, PORT), timeout=0.4)
            s.settimeout(1.0)
            s.sendall(frame_bytes({"type": "ping"}))
            r = read_frame(s)
            s.close()
            if r.get("type") == "pong":
                return (ip, r.get("name"), r.get("text"))
        except Exception:
            return None
        return None

    with ThreadPoolExecutor(max_workers=64) as ex:
        for res in ex.map(probe, range(1, 255)):
            if res:
                found.append(res)
                print(f"  ✓ {res[0]}  {res[1]} — {res[2]}")
    if not found:
        print("  (aucune machine PartageLAN détectée)")
    return found

# --------------------------------------------------------------------------- #
#  Mode écoute : Mac -> Linux (pair complet)                                  #
# --------------------------------------------------------------------------- #
def os_desc():
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return f"Linux {platform.release()}"

def recv_file_dir(meta, default_dir):
    """Dossier où enregistrer une trame 'file' : honore meta['path'] s'il est
    valide (comme l'app Mac), sinon repli sur le dossier de réception."""
    want = meta.get("path")
    if want:
        p = expand_path(want)
        if os.path.isdir(p):
            return p, None
        return default_dir, f"Dossier demandé invalide ({want}) → {default_dir}"
    return default_dir, None

def handle_conn(conn, addr):
    try:
        meta = read_frame(conn)
        t = meta.get("type")
        if t == "ping":
            conn.sendall(frame_bytes({"type": "pong", "name": MACHINE_NAME, "text": os_desc()}))
        elif t == "clip":
            ok = clip_set(meta.get("text") or "")
            extra = "" if ok else " (non appliqué : installe xclip)"
            print(f"[reçu] presse-papier de {addr[0]} ({len(meta.get('text') or '')} car.){extra}")
        elif t == "file":
            name = os.path.basename(meta.get("name") or "fichier_recu")
            size = int(meta.get("size") or 0)
            dirpath, warn = recv_file_dir(meta, downloads_dir())
            if warn:
                print(f"[écoute] {warn}")
            dest = unique_path(dirpath, name)
            with open(dest, "wb") as f:
                remaining = size
                while remaining > 0:
                    chunk = conn.recv(min(remaining, CHUNK))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            print(f"[reçu] {name} ({human(size)}) -> {dest}")
        elif t == "ls":
            p = dir_for_ls(meta.get("path"))
            if p is None:
                conn.sendall(frame_bytes({"type": "err",
                                          "text": f"Dossier introuvable : {meta.get('path')}"}))
            else:
                conn.sendall(frame_bytes({"type": "lsr", "name": MACHINE_NAME,
                                          "text": os_desc(), "path": p, "entries": list_dir(p)}))
        elif t == "get":
            p = expand_path(meta.get("path"))
            if not os.path.isfile(p):
                conn.sendall(frame_bytes({"type": "err", "text": f"Fichier introuvable : {p}"}))
            else:
                size = os.path.getsize(p)
                conn.sendall(frame_bytes({"type": "file", "name": os.path.basename(p), "size": size}))
                with open(p, "rb") as f:
                    while True:
                        chunk = f.read(CHUNK)
                        if not chunk:
                            break
                        conn.sendall(chunk)
    except Exception as e:
        print(f"[erreur] {addr[0]} : {e}")
    finally:
        conn.close()

def cmd_listen():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT))
    srv.listen(16)
    print(f"À l'écoute sur 0.0.0.0:{PORT} — {MACHINE_NAME} ({os_desc()})")
    print("Le Mac peut maintenant te pousser fichiers/presse-papier et te détecter au scan.")
    print("Ctrl+C pour arrêter.")
    try:
        while True:
            conn, addr = srv.accept()
            conn.settimeout(30.0)
            handle_conn(conn, addr)   # séquentiel : un transfert à la fois (simple et sûr)
    except KeyboardInterrupt:
        print("\nArrêt.")
    finally:
        srv.close()

# --------------------------------------------------------------------------- #
#  Utilitaires                                                                 #
# --------------------------------------------------------------------------- #
def human(n):
    n = float(n)
    for u in ["o", "Ko", "Mo", "Go"]:
        if n < 1024:
            return f"{n:.0f} {u}" if u == "o" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} To"

def downloads_dir():
    """Dossier de téléchargements XDG (~/Téléchargements sur un système français)."""
    home = os.path.expanduser("~")
    try:
        out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=3,
                             text=True).stdout.strip()
        if out and out != home and os.path.isdir(out):
            return out
    except Exception:
        pass
    for name in ("Téléchargements", "Downloads"):
        p = os.path.join(home, name)
        if os.path.isdir(p):
            return p
    return home

def unique_path(dirpath, name):
    base, ext = os.path.splitext(name)
    dest = os.path.join(dirpath, name)
    i = 2
    while os.path.exists(dest):
        dest = os.path.join(dirpath, f"{base} ({i}){ext}")
        i += 1
    return dest

def expand_path(path):
    """Traduit un chemin reçu du pair vers un chemin Linux utilisable."""
    if not path:
        return os.path.expanduser("~")
    if path.startswith("~"):
        return os.path.expanduser(path)
    return path

def _looks_foreign(path):
    """Chemin hérité d'un autre OS de ce PC multiboot : macOS (/Users/...) ou
    Windows (C:\\...). Il n'existe pas sous Linux -> on retombera sur l'accueil."""
    return bool(re.match(r"^[A-Za-z]:[\\/]", path)) or "\\" in path or path.startswith("/Users/")

def dir_for_ls(path):
    """Résout un chemin pour un 'ls'. Un chemin macOS/Windows hérité qui n'existe
    pas sous Linux retombe sur l'accueil, pour afficher les dossiers de la machine
    au lieu d'une erreur. Renvoie None seulement pour un chemin Linux explicite absent."""
    p = expand_path(path)
    if os.path.isdir(p):
        return p
    if not path or path.startswith("~") or _looks_foreign(path):
        return os.path.expanduser("~")
    return None

def list_dir(p):
    out = []
    try:
        for name in os.listdir(p):
            full = os.path.join(p, name)
            isdir = os.path.isdir(full)
            size = None
            if not isdir and os.path.isfile(full):
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = None
            try:
                mtime = int(os.path.getmtime(full))
            except OSError:
                mtime = None
            out.append({"name": name, "isDir": isdir, "size": size, "mtime": mtime})
        # du plus récent au plus ancien (l'app Mac ignore le champ mtime, sans risque)
        out.sort(key=lambda e: e.get("mtime") or 0, reverse=True)
    except Exception:
        pass
    return out

# --------------------------------------------------------------------------- #
#  CLI                                                                         #
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Client Linux pour PartageLAN (Mac <-> Linux sur le réseau local).")
    ap.add_argument("--ip", default=DEFAULT_IP, help=f"IP du pair (défaut {DEFAULT_IP})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ping", help="tester la présence du pair")

    p_scan = sub.add_parser("scan", help="scanner le réseau pour trouver les machines PartageLAN")
    p_scan.add_argument("--subnet", default="10.0.0", help="préfixe /24 (défaut 10.0.0)")

    p_ls = sub.add_parser("ls", help="lister un dossier distant")
    p_ls.add_argument("path", help="chemin sur le pair (ex : ~  ou  ~/Downloads)")

    p_push = sub.add_parser("push", help="envoyer un fichier Linux -> pair")
    p_push.add_argument("file", help="fichier local à envoyer")
    p_push.add_argument("dest", nargs="?", default=None,
                        help="dossier distant (défaut : dossier de réception du pair)")

    p_pull = sub.add_parser("pull", help="récupérer un fichier pair -> Linux")
    p_pull.add_argument("remote", help="chemin du fichier sur le pair")
    p_pull.add_argument("localdir", nargs="?", default=None,
                        help="dossier local de destination (défaut : Téléchargements)")

    p_clip = sub.add_parser("send-clip", help="envoyer du texte (ou le presse-papier Linux) au pair")
    p_clip.add_argument("text", nargs="*", help="texte à envoyer (si absent : presse-papier Linux)")

    sub.add_parser("listen", help="écouter : recevoir fichiers/presse-papier du pair (pair complet)")

    args = ap.parse_args()
    try:
        if args.cmd == "ping":
            cmd_ping(args.ip)
        elif args.cmd == "scan":
            cmd_scan(args.subnet)
        elif args.cmd == "ls":
            cmd_ls(args.ip, args.path)
        elif args.cmd == "push":
            cmd_push(args.ip, args.file, args.dest)
        elif args.cmd == "pull":
            cmd_pull(args.ip, args.remote, args.localdir)
        elif args.cmd == "send-clip":
            cmd_send_clip(args.ip, " ".join(args.text) if args.text else None)
        elif args.cmd == "listen":
            cmd_listen()
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        print(f"✗ Connexion impossible à {args.ip}:{PORT} — {e}")
        print("  Vérifie que PartageLAN tourne sur le pair et que son pare-feu l'autorise.")
        sys.exit(1)

if __name__ == "__main__":
    main()
