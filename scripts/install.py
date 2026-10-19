"""Explicit install/update only. Never starts UDK.exe or imports a panel egg."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import sys
import tempfile
import urllib.request
import uuid

from common import (LOCK, atomic_write, component_stamp, contained, exclusive,
                    log, prefix_marker, prefix_ready, run_program, timestamp,
                    windows_path, wine_environment)


def download_helpers(root):
    cache = contained(root, root / ".installer")
    cache.mkdir(exist_ok=True)
    for filename, source in LOCK["downloads"].items():
        destination = contained(root, cache / filename)
        if destination.exists():
            with destination.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest == source["sha256"]:
                continue
            raise RuntimeError(f"Cached installer checksum mismatch: .installer/{filename}. Move it aside before retrying.")
        log(f"Downloading the pinned official helper {filename}.")
        fd, temporary = tempfile.mkstemp(prefix=".download-", dir=cache)
        try:
            with os.fdopen(fd, "wb") as stream:
                with urllib.request.urlopen(source["url"], timeout=60) as response:
                    shutil.copyfileobj(response, stream)
            with open(temporary, "rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != source["sha256"]:
                raise RuntimeError(f"Downloaded {filename} does not match sources.lock.json; it will not be executed.")
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return cache


def install(root):
    root.mkdir(parents=True, exist_ok=True)
    # Wings' installation container normally runs as root. Wine must not create a root prefix.
    if os.geteuid() == 0:
        user = pwd.getpwnam("container")
        os.chown(root, user.pw_uid, user.pw_gid)
        os.initgroups(user.pw_name, user.pw_gid)
        os.setgid(user.pw_gid)
        os.setuid(user.pw_uid)
    with exclusive(root):
        game = contained(root, root / "game")
        stage = contained(root, root / (".renx-staging-" + uuid.uuid4().hex))
        backup_dir = contained(root, root / "backups" / ("install-" + timestamp()))
        helpers = download_helpers(root)
        if game.exists():
            if any(path.is_symlink() for path in game.rglob("*")):
                raise RuntimeError("Remove symlinks from game/ before updating; no existing files were changed.")
            required = sum(path.stat().st_size for path in game.rglob("*") if path.is_file())
            if shutil.disk_usage(root).free < required + 10 * 1024**3:
                raise RuntimeError("Not enough free space for staging plus 10 GiB of update headroom.")
            log("Copying the current installation to a staging directory.")
            shutil.copytree(game, stage)
        else:
            stage.mkdir()
        prepare_prefix = not prefix_ready(root)
        if prepare_prefix and (root / ".wine").exists():
            log("Backing up the existing Wine prefix before changing runtime components.")
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(contained(root, root / ".wine"), backup_dir / ".wine", symlinks=True)
        # Restore user INIs from the untouched live tree after the patcher finishes.
        # Default*.ini files always come from the newly downloaded release.
        with wine_environment(root) as env:
            if prepare_prefix:
                log("Preparing Wine redistributables. This may take several minutes.")
                run_program(["wineboot", "--init"], env, root, 180)
                run_program(["wineserver", "-w"], env, root, 180)
                run_program(["winetricks", "-q", *LOCK["wine_components"]], env, root, 1800)
                atomic_write(prefix_marker(root), json.dumps(component_stamp(), indent=2).encode())
            log("Downloading/updating the official renegade_x channel in staging.")
            run_program(["wine", str(helpers / "tapatcher.exe"), "update", "renegade_x",
                         windows_path(stage), "-X", windows_path(helpers / "xdelta3.exe"),
                         "-L", windows_path(stage / "tapatcher.log"), "--progress-mode=plain"],
                        env, stage, 14400)
        required_files = ["Binaries/Win64/UDK.exe", "UDKGame/Config/DefaultEngine.ini",
                          "UDKGame/Config/DefaultGame.ini", "UDKGame/Config/DefaultRenegadeX.ini"]
        if any(not (stage / name).is_file() for name in required_files):
            raise RuntimeError("The patcher did not produce the expected Win64 game layout; staging was retained.")
        old_config = game / "UDKGame" / "Config"
        if old_config.exists():
            for original in old_config.rglob("*.ini"):
                if not original.name.casefold().startswith("default"):
                    target = stage / "UDKGame" / "Config" / original.relative_to(old_config)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, target)
        atomic_write(stage / ".renx-install.json", json.dumps({
            "installed_at": timestamp(), "image_version": os.environ.get("RENX_IMAGE_VERSION", "unknown"),
            "product": "renegade_x", "game_version_policy": "official patcher default channel",
        }, indent=2).encode())
        try:
            if game.exists():
                backup_dir.mkdir(parents=True, exist_ok=True)
                game.rename(backup_dir / "game")
            stage.rename(game)
        except BaseException:
            if (backup_dir / "game").exists() and not game.exists():
                (backup_dir / "game").rename(game)
            raise
        log("Installation complete. No game server has been started.")
        if backup_dir.exists():
            log(f"Previous game files: {backup_dir.relative_to(root)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/home/container"))
    args = parser.parse_args()
    os.umask(0o077)

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        install(args.root.resolve())
    except KeyboardInterrupt:
        log("Installation interrupted; previous game files and staging were retained.")
        sys.exit(130)
    except Exception as error:
        log(f"Installation failed: {error}")
        sys.exit(1)
