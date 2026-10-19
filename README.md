# Renegade X for Pterodactyl

Docker build files and a Pterodactyl `PTDL_v2` egg for a standard Renegade X
multiplayer server running under Wine on **Linux/amd64**.

**Status: runtime untested.** Only the image build and publication are performed for
this release. No game installation, server startup, player join, RCON console or
graceful-shutdown tests have been run. No panel has been accessed or modified.
There are no test jobs or game-server startup steps in the publishing workflow.

## Downloads

- [Egg JSON](egg-renegade-x.json) — use GitHub's **Download raw file** button.
- [Releases](https://github.com/draakoor/renegade-x-pterodactyl/releases)
- [Container package](https://github.com/draakoor/renegade-x-pterodactyl/pkgs/container/renegade-x-pterodactyl)

```text
ghcr.io/draakoor/renegade-x-pterodactyl:0.1.0
```

Tags: `0.1.0`, `latest`, and `sha-<short-commit>`. The egg uses the versioned tag.
The GitHub Actions build summary also records the immutable image digest.

**Image version and game version are separate.** Image `0.1.0` versions this
packaging and runtime. The official download page listed game **1.2.1109** on
October 20, 2026. The TA patcher installs its current official `renegade_x` channel
when installation is explicitly requested; game content is not locked to that
reference version. The image contains neither the full game nor a graphical launcher.

## Requirements

- A Linux x86-64 Pterodactyl Wings node capable of running Docker containers.
- Pterodactyl 1.x with `PTDL_v2` egg support.
- Outbound HTTPS/DNS access for the game patcher and Wine redistributables during installation.
- Start with 4 GiB RAM, two CPU cores with good single-thread performance, and
  **60 GiB disk**. These are provisional sizing suggestions, not measured capacity.
  Updates need a complete staging copy, download space, and space for retained backups.

This package does not install a management bot, campaign mod or BRenBot. It does
not configure host services, nginx, firewalls or a game proxy.

## Pterodactyl setup

The following are instructions for the operator; none were performed for this release.

1. Import `egg-renegade-x.json` into a nest of your choice.
2. Create a server using the included versioned Docker image.
3. Set the primary allocation to the desired **UDP game port** (default `7777`).
   `SERVER_PORT` is supplied by Wings from that allocation.
4. Add a second allocation matching **`QUERY_PORT`**, default `27015/UDP`.
5. Set a unique **`ADMIN_PASSWORD`** before starting. It has no default value.
6. Allow the installation to finish. It prepares Wine and downloads the game;
   the installation script does not launch `UDK.exe`.
7. Start the server when you choose to perform your own runtime validation.

The internal RCON listener defaults to `7779/TCP`. **Do not allocate or publish that
port** for ordinary operation; the console bridge connects from inside the same
container. The game may bind that listener on all container interfaces, so it is
not a loopback-only security boundary. All three configured port numbers must differ.
Game/query allocations must map the same internal and external port numbers.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `SERVER_NAME` | `Renegade X Server` | Browser name; up to 96 characters, no quotes, backslashes or control characters |
| `START_MAP` | `CNC-Field` | Installed map name without extension or path |
| `MAX_PLAYERS` | `40` | Player limit, 1–64 |
| `SERVER_PORT` | `7777` outside Wings | Main UDP port; primary allocation under Pterodactyl |
| `QUERY_PORT` | `27015` | Steam query UDP port; additional allocation required |
| `RCON_PORT` | `7779` | Internal native Renegade X RCON TCP port |
| `ADMIN_PASSWORD` | Required, no default | In-game administrator and RCON authentication, 12–128 characters |
| `SERVER_PASSWORD` | Empty | Optional join password, up to 64 characters |

Passwords accept letters, numbers and `_.@%+=:,!-`. Use a generated random password.
Managed passwords are not placed on the UDK command line. The log-file bridge
redacts their literal values when forwarding logs to the console.

At startup, environment settings update only their corresponding properties in
`game/UDKGame/Config/UDKGame.ini`, `UDKEngine.ini`, and `UDKRenegadeX.ini`.
Changes to existing files are backed up first. Environment values take precedence
for those managed properties; other settings, including map rotations, remain editable.
Do not modify shipped `Default*.ini` files.

Missing generated INIs are materialized from the shipped default/Base hierarchy
without a preliminary game launch. The generator handles UE3 `BasedOn` inheritance
and `+`, `-`, `.`, `!` array operations. UDK is started with `-nohomedir` and
`-noautoiniupdate`. This initial-configuration path is **not runtime verified**.

## Console and stopping

The supervisor starts `Binaries/Win64/UDK.exe server` with the selected map, player
limit and primary port. Xvfb supplies a private virtual display without an X11 TCP
listener. The game log is forwarded to stdout, supporting UTF-8 and UTF-16 logs.

Console input uses Renegade X's native version-004 line protocol, **not Source RCON**.
Commands are unavailable while authentication or a map-change reconnection is in
progress; disconnected commands are not replayed. The ready marker requires both
a map-loaded log event and authenticated RCON. Startup times out after ten minutes
if that combination is not observed.

The egg's Stop action sends `quit`. `quit`, `exit`, `stop`, SIGTERM and SIGINT all
request an RCON `quit`, wait up to 20 seconds, then terminate the server's own Wine
prefix/process group if necessary. Allow at least 30 seconds for container shutdown.
This behavior is implemented but has not been tested against a running game.

## Installation, updates and backups

There are **no automatic game updates on startup**. Stop the server before using
Pterodactyl's Reinstall action to update to the patcher's current official channel.
For plain Docker, run the explicit installer below while the runtime is stopped.

The installer and runtime share an exclusive filesystem lock. Wine is initialized
as UID/GID 1000, including `vcrun2008`, `vcrun2010`, `d3dx9`, `xact` and Windows 10
compatibility. Components are prepared only during explicit installation, not startup.

An update copies the current game to a staging directory and patches that copy.
Existing non-Default INIs are restored into the staged tree, then the previous game
directory is moved into a timestamped backup before replacement. A failed download
does not replace the current game. Failed staging directories are retained for
diagnosis and consume disk space. No automatic backup pruning occurs.
An existing Wine prefix is also copied into the installation backup before its
component stamp is changed. Prefix preparation can change `.wine/` even if a later
game download fails; that copy can be used to undo the component change while stopped.

Persistent volume layout:

```text
/home/container/
  game/                      Installed game, config and logs
  .wine/                     Private persistent Wine prefix
  .installer/                Checksum-verified official patcher helpers
  .renx.lock                 Persistent lock inode; do not delete while running
  backups/install-<UTC>/game/ Previous installation
  backups/config-<UTC>/      Changed user INIs before startup
  backups/log-<UTC>/         Previous console log
  .renx-staging-<id>/        Incomplete/failed installation, if any
```

Backups contain passwords; keep them private. For a full rollback, stop the server
and restore a volume snapshot including `game/` and `.wine/`. To roll back only game
files, move the current `game/` aside and move a chosen `backups/install-.../game/`
back to `game/`, preserving ownership. New image versions may require an explicit
reinstall if their pinned Wine base or required component set changes.

The installer runs as `container` even when Wings starts its installation container
as root. For a manually mounted host directory, give UID/GID 1000 ownership before
installing. Installation uses `/mnt/server`; the runtime uses `/home/container`.
Only mount one server's data into either location.

## Build and use outside Pterodactyl

Build locally without starting the game:

```sh
docker build --platform linux/amd64 \
  --build-arg IMAGE_VERSION=0.1.0 \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  -t ghcr.io/draakoor/renegade-x-pterodactyl:0.1.0 .
```

The following commands install/start the game **only when you run them**:

```sh
mkdir -p data
sudo chown 1000:1000 data
cp .env.example .env
# Edit .env and set ADMIN_PASSWORD before starting.

docker run --rm \
  -v "$PWD/data:/home/container" \
  ghcr.io/draakoor/renegade-x-pterodactyl:0.1.0 install

docker run --name renegade-x -it --stop-timeout 30 \
  --env-file .env \
  -v "$PWD/data:/home/container" \
  -p 7777:7777/udp -p 27015:27015/udp \
  ghcr.io/draakoor/renegade-x-pterodactyl:0.1.0
```

Stop the runtime before repeating the installer command. Do not expose RCON merely
to make the Pterodactyl console work; its connection stays inside the container.

## Publishing and maintaining the package

GitHub Actions builds and pushes on a `vX.Y.Z` tag or a manual workflow dispatch.
`VERSION` must match the requested version. The job uses `GITHUB_TOKEN` with
`packages: write`; no registry secret needs to be committed. It does not install or
start the game, run Winetricks, execute tests, or access a panel.

For a new packaging release, update `VERSION`, the Dockerfile version default,
workflow default and README examples, then regenerate the egg:

```sh
python3 tools/make_egg.py
git tag v0.1.0
git push origin v0.1.0
```

Use the new version in place of `0.1.0`. Runtime and installation images in the egg
must point to the same release. Publish the new image before distributing that egg.
The first GHCR package publication may default to private; package settings must be
set to public for anonymous Wings pulls. The OCI source label associates the image
with this repository.

Source digests, installer hashes and the distinction between pinned runtime inputs
and the patcher's moving game channel are recorded in [sources.lock.json](sources.lock.json).
Changing a downloaded helper requires updating its lock entry and releasing a new image.
See [THIRD_PARTY.md](THIRD_PARTY.md) for upstream documentation and notices.

No claim is made that server listing, client compatibility, multiplayer performance,
console commands, config persistence or graceful shutdown have passed runtime validation.
