"""Own the web server and collector independently of browser sessions."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
STATE = DATA / "service.json"


def request(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
        return response.read()


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def running(state):
    if not state:
        return False
    try:
        return json.loads(request(state["control_port"], "/identity"))["token"] == state["token"]
    except Exception:
        return False


def serve():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from coach import capture
    stop = threading.Event()
    token = uuid.uuid4().hex
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/identity":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({"token": token}).encode())
            elif self.path == f"/stop/{token}":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"stopping")
                stop.set()
            else:
                self.send_error(404)
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [sys.executable, "-m", "streamlit", "run", str(ROOT/"app.py"), "--server.headless=true", "--server.address=127.0.0.1", f"--server.port={port}"]
    with (DATA/"web.log").open("a", encoding="utf-8") as log:
        child = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        state = {"pid": os.getpid(), "web_pid": child.pid, "port": port, "control_port": http.server_port, "token": token}
        STATE.write_text(json.dumps(state), encoding="utf-8")
        worker = threading.Thread(target=capture.serve, args=(stop,), daemon=True)
        worker.start()
        try:
            while not stop.wait(1) and child.poll() is None:
                pass
        finally:
            stop.set()
            child.terminate()
            child.wait(timeout=15)
            worker.join(timeout=45)
            http.shutdown()
            if load_state() == state:
                STATE.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "serve"])
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    DATA.mkdir(exist_ok=True)
    if args.action == "serve":
        serve()
        return
    # Serialize double-clicks without killing or attaching to unrelated Python processes.
    import msvcrt
    lock = (DATA/"launch.lock").open("a+b")
    if lock.tell() == 0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    for _ in range(100):
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            break
        except OSError:
            time.sleep(.2)
    else:
        raise RuntimeError("另一个启动/停止操作仍在进行，请稍后重试")
    state = load_state()
    if args.action == "stop":
        if running(state):
            request(state["control_port"], f"/stop/{state['token']}")
            for _ in range(60):
                if not running(state):
                    break
                time.sleep(.5)
        return
    if not running(state):
        with (DATA/"service.log").open("a", encoding="utf-8") as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "serve"], cwd=ROOT, stdout=log, stderr=log,
                             creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
        for _ in range(100):
            time.sleep(.2)
            state = load_state()
            if running(state):
                break
        else:
            raise RuntimeError("后台服务启动失败，请查看 data/service.log")
    for _ in range(120):
        try:
            if request(state["port"], "/_stcore/health") == b"ok":
                if not args.no_browser:
                    webbrowser.open(f"http://127.0.0.1:{state['port']}")
                return
        except Exception:
            pass
        time.sleep(.25)
    raise RuntimeError("网页服务未就绪，请查看 data/web.log")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(0, str(exc), "ADS 实验陪练", 16)
        raise
