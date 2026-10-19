"""Wine supervisor and native Renegade X RCON bridge (not Source RCON)."""
import codecs
import os
from pathlib import Path
import queue
import re
import select
import signal
import socket
import subprocess
import sys
import threading
import time

from common import (atomic_write, backup, contained, exclusive, log, prefix_ready,
                    timestamp, windows_path, wine_environment)
from configuration import configure, settings


def wire_encode(text):
    """Rx_RconConnection expects ASCII with escaped UTF-16 code units."""
    result = []
    data = text.encode("utf-16-le")
    for offset in range(0, len(data), 2):
        unit = int.from_bytes(data[offset:offset + 2], "little")
        if unit == 92:
            result.append("\\\\")
        elif 32 <= unit < 127:
            result.append(chr(unit))
        else:
            result.append(f"\\u{unit:04X}")
    return "".join(result).encode("ascii")


def wire_decode(text):
    def expand(match):
        return "\\" if match[0] == "\\\\" else chr(int(match[0][2:], 16))
    return re.sub(r"\\\\|\\[uU][0-9A-Fa-f]{4}", expand, text).encode(
        "utf-16-le", "surrogatepass").decode("utf-16-le", "replace")


class Rcon:
    def __init__(self, port, password):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        self.buffer = b""
        try:
            greeting = self.receive(5)
            if not greeting.startswith("v004"):
                raise ValueError("Unsupported Renegade X RCON protocol; expected version 004.")
            self.send("a", password)
            answer = self.receive(5)
            if not answer.startswith("a"):
                raise ValueError("RCON authentication failed. Check the managed AdminPassword setting.")
        except BaseException:
            self.sock.close()
            raise

    def send(self, kind, text=""):
        self.sock.sendall(kind.encode("ascii") + wire_encode(text) + b"\n")

    def receive(self, timeout):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.sock], [], [], remaining)[0]:
                raise TimeoutError
            data = self.sock.recv(16384)
            if not data:
                raise ConnectionError("RCON disconnected.")
            self.buffer += data
            if len(self.buffer) > 1024 * 1024:
                raise ConnectionError("RCON line exceeded the size limit.")
        line, self.buffer = self.buffer.split(b"\n", 1)
        return wire_decode(line.rstrip(b"\r").decode("ascii", "replace"))

    def close(self):
        self.sock.close()


class Supervisor:
    def __init__(self, root, config):
        self.root, self.config = root, config
        self.stop = threading.Event()
        self.finished = threading.Event()
        self.connected = threading.Event()
        self.map_loaded = threading.Event()
        self.commands = queue.Queue(maxsize=64)
        self.failure = None
        self.secrets = [config["ADMIN_PASSWORD"], config["SERVER_PASSWORD"]]
        self.proc = None

    def output(self, line):
        for secret in self.secrets:
            if secret:
                line = line.replace(secret, "[REDACTED]")
        print(line, flush=True)

    def request_stop(self, *_):
        self.stop.set()

    def console(self):
        for line in sys.stdin:
            command = line.strip()
            if not command:
                continue
            if command.casefold() in ("quit", "exit", "stop"):
                self.request_stop()
                return
            if not self.connected.is_set():
                log("Console unavailable while RCON connects; command was not queued.")
                continue
            if len(command) > 4096 or any(ord(c) < 32 for c in command):
                log("Rejected console command: use one line of at most 4096 characters.")
                continue
            try:
                self.commands.put_nowait(command)
            except queue.Full:
                log("Console queue is full; command was not queued.")

    def rcon(self):
        while not self.finished.is_set():
            client = None
            try:
                client = Rcon(self.config["RCON_PORT"], self.config["ADMIN_PASSWORD"])
                self.connected.set()
                log("Native RCON console connected.")
                while not self.finished.is_set():
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        command = None
                    if command is not None:
                        client.send("c", command)
                    try:
                        response = client.receive(0.2)
                        if response.startswith(("r", "e")):
                            self.output("[RCON] " + response[1:])
                    except TimeoutError:
                        pass
            except ValueError as error:
                self.failure = str(error)
                self.stop.set()
                return
            except (OSError, ConnectionError):
                pass
            finally:
                self.connected.clear()
                if client:
                    client.close()
                # Commands from a lost session must never replay after a map change.
                while True:
                    try:
                        self.commands.get_nowait()
                    except queue.Empty:
                        break
            self.finished.wait(2)

    def tail_log(self, path):
        position = 0
        decoder = None
        pending = ""
        while not self.finished.wait(0.15):
            if not path.exists():
                continue
            if path.stat().st_size < position:
                position, decoder, pending = 0, None, ""
            with path.open("rb") as stream:
                stream.seek(position)
                chunk = stream.read(65536)
            if not chunk:
                continue
            if decoder is None:
                if len(chunk) < 2:
                    continue
                encoding = "utf-16" if chunk.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
                decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
            position += len(chunk)
            pending += decoder.decode(chunk)
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                self.output(line.rstrip("\r"))
                if re.search(r"\bMAP[\x02\s]+Loaded;", line):
                    self.map_loaded.set()
            if len(pending) > 1024 * 1024:
                self.output(pending)
                pending = ""

    def shutdown(self, env):
        if self.proc is None or self.proc.poll() is not None:
            return
        log("Stopping: requesting quit through native RCON.")
        sent = False
        deadline = time.monotonic() + 20
        while self.proc.poll() is None and time.monotonic() < deadline:
            if self.connected.is_set() and not sent:
                try:
                    self.commands.put_nowait("quit")
                    sent = True
                except queue.Full:
                    pass
            time.sleep(0.1)
        if self.proc.poll() is None:
            log("Graceful shutdown timed out; terminating this server's Wine processes.")
            subprocess.run(["wineserver", "-k"], env=env, timeout=3, check=False)
            if self.proc.poll() is None:
                os.killpg(self.proc.pid, signal.SIGTERM)
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                    self.proc.wait(timeout=2)

    def run(self, env):
        game = contained(self.root, self.root / "game")
        logfile = contained(self.root, game / "UDKGame" / "Logs" / "Pterodactyl.log")
        backup(self.root, logfile, self.root / "backups" / ("log-" + timestamp()))
        atomic_write(logfile, b"")
        command = ["wine", str(game / "Binaries" / "Win64" / "UDK.exe"), "server",
                   f'{self.config["START_MAP"]}?maxplayers={self.config["MAX_PLAYERS"]}',
                   f'-port={self.config["SERVER_PORT"]}', "-multihome=0.0.0.0",
                   "-unattended", "-nohomedir", "-noautoiniupdate", "-nosound", "-nosplash",
                   "-forcelogflush", "ABSLOG=" + windows_path(logfile)]
        log("Starting the installed game. Automatic updates are disabled.")
        self.proc = subprocess.Popen(command, cwd=game / "Binaries" / "Win64", env=env,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
        workers = [threading.Thread(target=self.console, daemon=True),
                   threading.Thread(target=self.rcon, daemon=True),
                   threading.Thread(target=self.tail_log, args=(logfile,), daemon=True)]
        for worker in workers:
            worker.start()
        ready = False
        deadline = time.monotonic() + 600
        try:
            while self.proc.poll() is None and not self.stop.wait(0.1):
                if not ready and self.map_loaded.is_set() and self.connected.is_set():
                    log("Server ready.")
                    ready = True
                elif not ready and time.monotonic() > deadline:
                    self.failure = "Startup timed out: no loaded map with an authenticated RCON connection."
                    self.stop.set()
            if self.stop.is_set():
                self.shutdown(env)
            if self.failure:
                log(self.failure)
                return 1
            return 0 if self.stop.is_set() else (self.proc.returncode or 1)
        finally:
            self.finished.set()
            for worker in workers[1:]:
                worker.join(timeout=1)


def main():
    os.umask(0o077)
    if os.geteuid() == 0:
        raise RuntimeError("Start the runtime as the container user (UID 1000), not root.")
    root = Path("/home/container").resolve()
    config = settings()
    with exclusive(root):
        binary = contained(root, root / "game" / "Binaries" / "Win64" / "UDK.exe")
        if not binary.is_file() or not prefix_ready(root):
            raise RuntimeError("Installation is missing or Wine components changed. Stop and run the explicit installer.")
        configure(root, config)
        supervisor = Supervisor(root, config)
        signal.signal(signal.SIGTERM, supervisor.request_stop)
        signal.signal(signal.SIGINT, supervisor.request_stop)
        with wine_environment(root) as env:
            if supervisor.stop.is_set():
                return 0
            return supervisor.run(env)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        log(f"Startup/runtime failed: {error}")
        sys.exit(1)
