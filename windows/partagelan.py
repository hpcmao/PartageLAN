#!/usr/bin/env python3
"""
partagelan.py — client Windows pour PartageLAN (app macOS de hpcmao).

Parle le meme protocole TCP que l'app Mac, sur le port 7365 :
    trame = [longueur UInt32 big-endian][JSON meta][octets bruts optionnels]
    (la longueur ne couvre QUE le JSON ; le corps d'un fichier suit juste apres)
Types : clip | file | ping/pong | ls/lsr | get | err

Aucune dependance externe : stdlib Python uniquement.
Le presse-papier passe par PowerShell (Get-Clipboard / Set-Clipboard), integre a Windows.

Exemples :
    python partagelan.py ping
    python partagelan.py scan
    python partagelan.py ls ~
    python partagelan.py push "C:\\chemin\\fichier.zip"
    python partagelan.py push "C:\\chemin\\fichier.zip" ~/Downloads
    python partagelan.py pull ~/Documents/note.txt
    python partagelan.py send-clip "bonjour le Mac"
    python partagelan.py send-clip            (envoie le presse-papier Windows)
    python partagelan.py listen               (recevoir du Mac : pair complet)
    python partagelan.py --ip 10.0.0.4 ping   (viser une autre IP)
"""
import argparse, socket, struct, json, os, sys, subprocess, platform, ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor

# Console en UTF-8 (accents + symboles) meme sur un terminal Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_IP = "10.0.0.4"   # vemao ; surchargeable avec --ip
MACHINE_NAME = "winjeux"  # nom affiche par le Mac (scan, pong, lsr)
PORT = 7365
MAXLEN = 50_000_000
CHUNK = 1 << 16           # 64 Kio, comme l'app Mac

# --------------------------------------------------------------------------- #
#  Framing bas niveau                                                          #
# --------------------------------------------------------------------------- #
def recvn(sock, n):
    """Lit exactement n octets ou leve EOFError."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError("connexion fermee prematurement")
        buf += chunk
    return bytes(buf)

def read_frame(sock):
    """Lit une trame [UInt32 longueur][JSON] et renvoie le dict meta."""
    (ln,) = struct.unpack(">I", recvn(sock, 4))
    if not (0 < ln < MAXLEN):
        raise ValueError(f"longueur de trame invalide : {ln}")
    return json.loads(recvn(sock, ln).decode("utf-8"))

def frame_bytes(meta):
    """Serialise un dict meta en trame [UInt32 longueur][JSON]."""
    data = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    return struct.pack(">I", len(data)) + data

def connect(ip, timeout=5.0):
    s = socket.create_connection((ip, PORT), timeout=timeout)
    s.settimeout(timeout)
    return s

# --------------------------------------------------------------------------- #
#  Presse-papier Windows via l'API Win32 (ctypes) : aucune fenetre, tres leger  #
#  (l'ancienne version lancait PowerShell, ce qui faisait clignoter une console #
#   a chaque sondage du presse-papier toutes les 0,6 s).                        #
# --------------------------------------------------------------------------- #
_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
_user32.OpenClipboard.argtypes = [ctypes.c_void_p]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.GetClipboardData.argtypes = [wintypes.UINT]
_user32.GetClipboardData.restype = ctypes.c_void_p
_user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
_user32.SetClipboardData.restype = ctypes.c_void_p
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

def clip_get():
    """Lit le presse-papier (texte Unicode) via l'API Win32 — aucune fenetre."""
    if not _user32.OpenClipboard(None):
        return ""
    try:
        h = _user32.GetClipboardData(_CF_UNICODETEXT)
        if not h:
            return ""
        p = _kernel32.GlobalLock(h)
        if not p:
            return ""
        try:
            return ctypes.c_wchar_p(p).value or ""
        finally:
            _kernel32.GlobalUnlock(h)
    finally:
        _user32.CloseClipboard()

def clip_set(text):
    """Ecrit du texte dans le presse-papier via l'API Win32 — aucune fenetre."""
    text = text or ""
    if not _user32.OpenClipboard(None):
        return
    try:
        _user32.EmptyClipboard()
        buf = ctypes.create_unicode_buffer(text)   # inclut le terminateur nul
        size = ctypes.sizeof(buf)
        h = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, size)
        if not h:
            return
        p = _kernel32.GlobalLock(h)
        if not p:
            return
        ctypes.memmove(p, buf, size)
        _kernel32.GlobalUnlock(h)
        _user32.SetClipboardData(_CF_UNICODETEXT, h)  # l'OS possede desormais la memoire
    finally:
        _user32.CloseClipboard()

# --------------------------------------------------------------------------- #
#  Commandes client : Windows -> Mac                                          #
# --------------------------------------------------------------------------- #
def cmd_ping(ip):
    with connect(ip) as s:
        s.sendall(frame_bytes({"type": "ping"}))
        r = read_frame(s)
    if r.get("type") == "pong":
        print(f"✓ {ip} repond : {r.get('name')} — {r.get('text')}")
    else:
        print(f"? reponse inattendue : {r}")
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
        if e.get("isDir"):
            print(f"  [dossier] {e['name']}")
        else:
            print(f"            {e['name']}  ({human(e.get('size') or 0)})")

def cmd_push(ip, filepath, destdir=None):
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
    print(f"✓ Envoye : {name} ({human(size)}) -> {ip}:{destdir or '(dossier de reception du Mac)'}")

def cmd_pull(ip, remotepath, localdir=None):
    localdir = localdir or downloads_dir()
    os.makedirs(localdir, exist_ok=True)
    with connect(ip) as s:
        s.sendall(frame_bytes({"type": "get", "path": remotepath}))
        r = read_frame(s)
        if r.get("type") == "err":
            print(f"✗ {r.get('text')}")
            return
        if r.get("type") != "file":
            print(f"✗ reponse inattendue : {r.get('type')}")
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
    print(f"✓ Recu : {name} ({human(size)}) -> {dest}")

def cmd_send_clip(ip, text=None):
    if not text:
        text = clip_get()
    if not text:
        print("✗ Presse-papier vide (rien a envoyer)")
        return
    with connect(ip) as s:
        s.sendall(frame_bytes({"type": "clip", "text": text}))
    print(f"✓ Presse-papier envoye a {ip} ({len(text)} caracteres)")

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
        print("  (aucune machine PartageLAN detectee)")
    return found

# --------------------------------------------------------------------------- #
#  Mode ecoute : Mac -> Windows (pair complet)                                #
# --------------------------------------------------------------------------- #
def os_desc():
    rel = platform.release()
    return f"Windows {rel}"

def handle_conn(conn, addr):
    try:
        meta = read_frame(conn)
        t = meta.get("type")
        if t == "ping":
            conn.sendall(frame_bytes({"type": "pong", "name": MACHINE_NAME, "text": os_desc()}))
        elif t == "clip":
            clip_set(meta.get("text") or "")
            print(f"[recu] presse-papier de {addr[0]} ({len(meta.get('text') or '')} car.)")
        elif t == "file":
            name = os.path.basename(meta.get("name") or "fichier_recu")
            size = int(meta.get("size") or 0)
            dest = unique_path(downloads_dir(), name)
            with open(dest, "wb") as f:
                remaining = size
                while remaining > 0:
                    chunk = conn.recv(min(remaining, CHUNK))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
            print(f"[recu] {name} ({human(size)}) -> {dest}")
        elif t == "ls":
            p = dir_for_ls(meta.get("path"))
            if p is None:
                conn.sendall(frame_bytes({"type": "err",
                                          "text": f"Dossier introuvable : {meta.get('path')}"}))
            else:
                conn.sendall(frame_bytes({"type": "lsr", "name": MACHINE_NAME,
                                          "text": os_desc(), "path": p, "entries": list_dir(p)}))
        elif t == "get":
            p = expand_win(meta.get("path"))
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
    print(f"A l'ecoute sur 0.0.0.0:{PORT} — {MACHINE_NAME} ({os_desc()})")
    print("Le Mac peut maintenant te pousser fichiers/presse-papier et te detecter au scan.")
    print("Ctrl+C pour arreter.")
    try:
        while True:
            conn, addr = srv.accept()
            conn.settimeout(30.0)
            handle_conn(conn, addr)   # sequentiel : un transfert a la fois (simple et sur)
    except KeyboardInterrupt:
        print("\nArret.")
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
    return os.path.join(os.path.expanduser("~"), "Downloads")

def unique_path(dirpath, name):
    base, ext = os.path.splitext(name)
    dest = os.path.join(dirpath, name)
    i = 2
    while os.path.exists(dest):
        dest = os.path.join(dirpath, f"{base} ({i}){ext}")
        i += 1
    return dest

def expand_win(path):
    """Traduit un chemin recu du Mac vers un chemin Windows utilisable."""
    if not path:
        return os.path.expanduser("~")
    if path == "~" or path.startswith("~/") or path.startswith("~\\"):
        return os.path.expanduser("~") + path[1:]
    return path

def dir_for_ls(path):
    """Resout un chemin pour un 'ls'. Un chemin macOS herite (/Users/...) qui n'existe
    pas sur Windows retombe sur l'accueil, pour afficher les dossiers de la machine au
    lieu d'une erreur. Renvoie None seulement pour un chemin Windows explicite absent."""
    p = expand_win(path)
    if os.path.isdir(p):
        return p
    if not path or path.startswith("/") or path.startswith("~"):
        return os.path.expanduser("~")
    return None

def list_dir(p):
    out = []
    try:
        for name in sorted(os.listdir(p)):
            full = os.path.join(p, name)
            isdir = os.path.isdir(full)
            size = None
            if not isdir and os.path.isfile(full):
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = None
            out.append({"name": name, "isDir": isdir, "size": size})
    except Exception:
        pass
    return out

# --------------------------------------------------------------------------- #
#  CLI                                                                         #
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Client Windows pour PartageLAN (Mac <-> Windows sur le reseau local).")
    ap.add_argument("--ip", default=DEFAULT_IP, help=f"IP du Mac (defaut {DEFAULT_IP})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ping", help="tester la presence du Mac")

    p_scan = sub.add_parser("scan", help="scanner le reseau pour trouver les machines PartageLAN")
    p_scan.add_argument("--subnet", default="10.0.0", help="prefixe /24 (defaut 10.0.0)")

    p_ls = sub.add_parser("ls", help="lister un dossier distant")
    p_ls.add_argument("path", help="chemin sur le Mac (ex : ~  ou  ~/Downloads)")

    p_push = sub.add_parser("push", help="envoyer un fichier Windows -> Mac")
    p_push.add_argument("file", help="fichier local a envoyer")
    p_push.add_argument("dest", nargs="?", default=None,
                        help="dossier distant (defaut : dossier de reception du Mac)")

    p_pull = sub.add_parser("pull", help="recuperer un fichier Mac -> Windows")
    p_pull.add_argument("remote", help="chemin du fichier sur le Mac")
    p_pull.add_argument("localdir", nargs="?", default=None,
                        help="dossier local de destination (defaut : Telechargements)")

    p_clip = sub.add_parser("send-clip", help="envoyer du texte (ou le presse-papier Windows) au Mac")
    p_clip.add_argument("text", nargs="*", help="texte a envoyer (si absent : presse-papier Windows)")

    sub.add_parser("listen", help="ecouter : recevoir fichiers/presse-papier du Mac (pair complet)")

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
        print(f"✗ Connexion impossible a {args.ip}:{PORT} — {e}")
        print("  Verifie que PartageLAN.app tourne sur le Mac et que Little Snitch/pare-feu l'autorise.")
        sys.exit(1)

if __name__ == "__main__":
    main()
