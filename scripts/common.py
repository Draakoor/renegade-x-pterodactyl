"""Shared filesystem locking and Wine lifecycle; no import-time actions."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from datetime import datetime, timezone

APP = Path(__file__).resolve().parent
LOCK = json.loads((APP / "sources.lock.json").read_text(encoding="utf-8"))


def log(message):
    print(f"[Renegade X] {message}", flush=True)


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def contained(root, path):
    path = path.resolve()
    if not path.is_relative_to(root.resolve()):
        raise RuntimeError(f"Path escapes the server directory: {path.name}")
    return path


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".renx-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextlib.contextmanager
def exclusive(root):
    root.mkdir(parents=True, exist_ok=True)
    path = contained(root, root / ".renx.lock")
    # Keep the inode permanently: unlinking a flock file would break mutual exclusion.
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("The server or installer is already running. Stop it first.") from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def backup(root, path, destination):
    if path.exists():
        source = contained(root, path)
        target = contained(root, destination / source.relative_to(root))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        target.chmod(0o600)


def prefix_marker(root):
    return contained(root, root / ".wine" / ".renx-components.json")


def component_stamp():
    return {"base": LOCK["base_image"], "components": LOCK["wine_components"]}


def prefix_ready(root):
    marker = prefix_marker(root)
    return (marker.exists() and json.loads(marker.read_text()) == component_stamp()
            and (root / ".wine" / "system.reg").exists())


@contextlib.contextmanager
def wine_environment(root):
    env = os.environ.copy()
    env.update(HOME=str(root), WINEPREFIX=str(contained(root, root / ".wine")),
               WINEARCH="win64", WINEDEBUG="-all", WINEDLLOVERRIDES="mscoree,mshtml=")
    # Xvfb chooses a free display and reports it through this pipe. No TCP listener.
    read_fd, write_fd = os.pipe()
    xvfb = subprocess.Popen(["Xvfb", "-displayfd", str(write_fd), "-screen", "0",
                             "1024x768x24", "-nolisten", "tcp"],
                            pass_fds=(write_fd,), start_new_session=True)
    os.close(write_fd)
    try:
        import select
        if not select.select([read_fd], [], [], 15)[0]:
            raise RuntimeError("Xvfb did not become ready within 15 seconds.")
        display = os.read(read_fd, 32).decode("ascii").strip()
        if not display.isdigit():
            raise RuntimeError("Xvfb failed to allocate a display.")
        env["DISPLAY"] = ":" + display
        yield env
    finally:
        os.close(read_fd)
        # This prefix belongs only to this server and the exclusive lock is held.
        try:
            subprocess.run(["wineserver", "-k"], env=env, timeout=5, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            pass
        xvfb.terminate()
        try:
            xvfb.wait(timeout=3)
        except subprocess.TimeoutExpired:
            xvfb.kill()
            xvfb.wait()


def run_program(argv, env, cwd, timeout):
    """Run an installer with a deadline and clean up its process group on errors."""
    proc = subprocess.Popen(argv, env=env, cwd=cwd, start_new_session=True)
    try:
        code = proc.wait(timeout=timeout)
        if code:
            raise RuntimeError(f"{Path(argv[0]).name} failed with exit code {code}.")
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


def windows_path(path):
    return "Z:" + str(path.resolve()).replace("/", "\\")
