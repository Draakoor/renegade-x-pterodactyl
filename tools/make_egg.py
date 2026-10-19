"""Generate the distributable PTDL_v2 egg. This does not import it anywhere."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
version = (root / "VERSION").read_text(encoding="utf-8").strip()
image = f"ghcr.io/draakoor/renegade-x-pterodactyl:{version}"


def variable(name, key, default, description, rules):
    return {"name": name, "description": description, "env_variable": key,
            "default_value": str(default), "user_viewable": True, "user_editable": True,
            "rules": rules, "field_type": "text"}


egg = {
    "_comment": "Runtime untested. Build and publication only; no game server was started.",
    "meta": {"version": "PTDL_v2", "update_url": None},
    "exported_at": "2026-10-20T00:00:00+00:00",
    "name": "Renegade X",
    "author": "draakoor@users.noreply.github.com",
    "description": "Renegade X multiplayer under Wine (Linux/amd64). Explicit installation through the official TA patcher. No automatic updates on startup. Runtime, join, RCON and shutdown have not been tested. See the repository README before use.",
    "features": [],
    "docker_images": {f"Renegade X Wine runtime {version} (amd64)": image},
    "file_denylist": [],
    "startup": "/opt/renegade-x/entrypoint.sh start",
    "config": {"files": "{}", "startup": json.dumps({"done": "[Renegade X] Server ready."}),
               "logs": "{}", "stop": "quit"},
    "scripts": {"installation": {
        "script": "#!/bin/bash\nset -euo pipefail\nexec /opt/renegade-x/entrypoint.sh install /mnt/server\n",
        "container": image, "entrypoint": "/bin/bash"
    }},
    "variables": [
        variable("Server name", "SERVER_NAME", "Renegade X Server",
                 "Displayed server name. No control characters, double quotes or backslashes.", "required|string|max:96"),
        variable("Starting map", "START_MAP", "CNC-Field",
                 "Installed map name without extension. Map rotation remains in game/UDKGame/Config/UDKGame.ini.",
                 "required|string|max:96|regex:/^[A-Za-z0-9_-]+$/"),
        variable("Maximum players", "MAX_PLAYERS", 40,
                 "Player limit. Capacity and performance have not been measured.", "required|integer|min:1|max:64"),
        variable("Steam query port", "QUERY_PORT", 27015,
                 "Assign this UDP port as an additional allocation. Must differ from game and RCON ports.",
                 "required|integer|min:1024|max:65535"),
        variable("Internal RCON port", "RCON_PORT", 7779,
                 "TCP port used by the native console bridge. Do not assign a public allocation for it. Must differ from other ports.",
                 "required|integer|min:1024|max:65535"),
        variable("Administrator password", "ADMIN_PASSWORD", "",
                 "Required for native RCON and in-game administration. Use 12-128 characters: letters, numbers and _.@%+=:,!-. No default password.",
                 "required|string|min:12|max:128|regex:/^[A-Za-z0-9_.@%+=:,!-]+$/"),
        variable("Game password", "SERVER_PASSWORD", "",
                 "Optional join password. Empty allows joining without a password. Allowed: letters, numbers and _.@%+=:,!-.",
                 "nullable|string|max:64|regex:/^[A-Za-z0-9_.@%+=:,!-]+$/"),
    ]
}
(root / "egg-renegade-x.json").write_text(json.dumps(egg, indent=2) + "\n", encoding="utf-8")
