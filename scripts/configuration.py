"""Prepare generated UDK INIs without changing the shipped Default*.ini files."""
import os
from pathlib import Path
import re

from common import atomic_write, backup, contained, log, timestamp

SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
PASSWORD = re.compile(r"^[A-Za-z0-9_.@%+=:,!-]+$")


def read_text(path):
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8-sig"), "utf-8-sig" if data.startswith(b"\xef\xbb\xbf") else "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1252"), "cp1252"


def number(name, default, lower, upper):
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if not lower <= value <= upper:
        raise RuntimeError(f"{name} must be between {lower} and {upper}.")
    return value


def settings():
    name = os.environ.get("SERVER_NAME", "Renegade X Server")
    if not name.strip() or len(name) > 96 or any(ord(c) < 32 or c in '\\"' for c in name):
        raise RuntimeError("SERVER_NAME must be 1-96 characters, without control characters, quotes or backslashes.")
    initial_map = os.environ.get("START_MAP", "CNC-Field")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", initial_map):
        raise RuntimeError("START_MAP must be a map name without an extension or path.")
    admin = os.environ.get("ADMIN_PASSWORD", "")
    password = os.environ.get("SERVER_PASSWORD", "")
    if not 12 <= len(admin) <= 128 or not PASSWORD.fullmatch(admin):
        raise RuntimeError("Set ADMIN_PASSWORD (12-128 characters; letters, numbers and _.@%+=:,!-).")
    if password and (len(password) > 64 or not PASSWORD.fullmatch(password)):
        raise RuntimeError("SERVER_PASSWORD must be empty or 1-64 characters: letters, numbers and _.@%+=:,!-.")
    ports = {key: number(key, default, 1024, 65535) for key, default in
             (("SERVER_PORT", 7777), ("QUERY_PORT", 27015), ("RCON_PORT", 7779))}
    if len(set(ports.values())) != 3:
        raise RuntimeError("SERVER_PORT, QUERY_PORT and RCON_PORT must use distinct port numbers.")
    return {**ports, "SERVER_NAME": name, "START_MAP": initial_map,
            "MAX_PLAYERS": number("MAX_PLAYERS", 40, 1, 64),
            "ADMIN_PASSWORD": admin, "SERVER_PASSWORD": password}


def default_layers(game, source, stack=()):
    """Resolve UE3 BasedOn paths relative to the Engine directory."""
    source = contained(game, source)
    if source in stack:
        raise RuntimeError("A cycle was found in the default INI hierarchy.")
    text, _ = read_text(source)
    current = ""
    based_on = None
    for line in text.splitlines():
        match = SECTION.match(line)
        if match:
            current = match[1].casefold()
        elif current == "configuration" and "=" in line:
            key, value = line.split("=", 1)
            if key.strip().casefold() == "basedon":
                based_on = value.strip().strip('"')
    if based_on:
        yield from default_layers(game, game / "Engine" / based_on.replace("\\", "/"), (*stack, source))
    yield text


def materialize_defaults(game, filename):
    """Flatten UE3 scalar/array operations for the first generated configuration."""
    sections = {}
    names = {}
    for text in default_layers(game, game / "UDKGame" / "Config" / filename):
        section = None
        plain_seen = set()
        for line in text.splitlines():
            match = SECTION.match(line)
            if match:
                section = match[1].casefold()
                names[section] = match[1]
                sections.setdefault(section, [])
                continue
            if section is None or section in ("configuration", "iniversion"):
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith((";", "//", "#")) or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key, value = key.strip(), value.strip()
            operation = key[0] if key and key[0] in "+-.!" else "="
            if operation != "=":
                key = key[1:]
            entries = sections[section]
            same_key = lambda entry: entry[0].casefold() == key.casefold()
            if operation == "!":
                entries[:] = [entry for entry in entries if not same_key(entry)]
            elif operation == "-":
                entries[:] = [entry for entry in entries if not (same_key(entry) and entry[1] == value)]
            elif operation == "+":
                if not any(same_key(entry) and entry[1] == value for entry in entries):
                    entries.append((key, value))
            elif operation == ".":
                entries.append((key, value))
            else:
                identity = (section, key.casefold())
                if identity not in plain_seen:
                    entries[:] = [entry for entry in entries if not same_key(entry)]
                    plain_seen.add(identity)
                entries.append((key, value))
    return "\r\n".join(
        line for section, entries in sections.items()
        if section not in ("configuration", "iniversion")
        for line in [f"[{names[section]}]", *(f"{key}={value}" for key, value in entries), ""]
    )


def replace_values(text, section_name, replacements):
    """Preserve unrelated lines and repeated array properties in existing user INIs."""
    output = []
    inside = False
    found = False
    wanted = {key.casefold() for key in replacements}
    for line in text.splitlines():
        match = SECTION.match(line)
        if match:
            inside = match[1].casefold() == section_name.casefold()
            output.append(line)
            if inside and not found:
                output.extend(f"{key}={value}" for key, value in replacements.items())
                found = True
        elif inside and "=" in line and line.split("=", 1)[0].strip().lstrip("+-.!").casefold() in wanted:
            continue
        else:
            output.append(line)
    if not found:
        output.extend(["", f"[{section_name}]", *(f"{key}={value}" for key, value in replacements.items())])
    return "\r\n".join(output) + "\r\n"


def configure(root, config):
    game = contained(root, root / "game")
    updates = {
        "Game": {
            "Engine.GameReplicationInfo": {"ServerName": '"' + config["SERVER_NAME"] + '"'},
            "Engine.GameInfo": {"MaxPlayers": config["MAX_PLAYERS"]},
            "Engine.AccessControl": {"AdminPassword": config["ADMIN_PASSWORD"],
                                     "GamePassword": config["SERVER_PASSWORD"]},
        },
        "Engine": {"OnlineSubsystemSteamworks.OnlineSubsystemSteamworks": {"QueryPort": config["QUERY_PORT"]}},
        "RenegadeX": {"RenX_Game.Rx_Rcon": {"bEnableRcon": "True", "RconPort": config["RCON_PORT"]}},
    }
    backup_dir = contained(root, root / "backups" / ("config-" + timestamp()))
    for kind, sections in updates.items():
        path = contained(root, game / "UDKGame" / "Config" / f"UDK{kind}.ini")
        if path.exists():
            original = path.read_bytes()
            text, encoding = read_text(path)
        else:
            original = None
            text = materialize_defaults(game, f"Default{kind}.ini")
            encoding = "utf-16"
        for section, values in sections.items():
            text = replace_values(text, section, values)
        # Preserve existing encoding unless a newly supplied server name needs Unicode.
        try:
            data = text.encode(encoding)
        except UnicodeEncodeError:
            data = text.encode("utf-16")
        if data != original:
            backup(root, path, backup_dir)
            atomic_write(path, data)
    log("Server settings applied; existing changed INIs were backed up.")
