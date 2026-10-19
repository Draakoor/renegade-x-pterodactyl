# Third-party components and references

The MIT license in this repository covers the original packaging scripts,
Dockerfile, workflow and documentation. It does not relicense third-party software.

- **Pterodactyl Yolks / Wine:** [upstream repository](https://github.com/Ptero-Eggs/yolks).
  The exact Linux/amd64 image digest is recorded in `sources.lock.json` and the Dockerfile.
  Wine, Winetricks, Debian packages and their dependencies retain their upstream licenses.
  Their installed license notices remain in the base image.
- **TA patcher:** the official binary is fetched from Totem Arts during explicit game installation.
  Its SHA256 is recorded in `sources.lock.json`; no modification is made to it.
  [Official server installation recipe](https://github.com/TotemArts/amp-repo-test/blob/main/renegade-xupdates.json).
- **xdelta3:** the official Totem Arts-hosted helper is likewise fetched and checksum verified during installation.
  [xdelta source and licensing](https://github.com/jmacd/xdelta). The helper identifies itself
  by its upstream filename as version 3.0.11. Neither helper binary is redistributed
  in the Git source tree or the runtime image; installation downloads them directly
  from their publisher into the operator's persistent volume.
- **Microsoft redistributables:** downloaded by the pinned base image's Winetricks script
  only when the operator runs installation. These remain subject to Microsoft's terms.
  They are not preinstalled or bundled as a Wine prefix in this image.
- **Renegade X / UDK:** game binaries and assets are not stored in Git or in the image.
  The installer obtains the game through Totem Arts' patcher. Game and engine rights remain
  with their respective owners. This is an unofficial hosting integration.

Implementation references:

- [Renegade X download](https://forums.totemarts.games/files/file/148-renegade-x/)
- [Dedicated server setup](https://wiki.totemarts.games/wiki/Server)
- [Linux runtime prerequisites](https://wiki.totemarts.games/wiki/Linux_Guide)
- [Renegade X command line](https://wiki.totemarts.games/wiki/Command_Line)
- [Native RCON protocol](https://github.com/TotemArts/Renegade-X/blob/master/Development/Src/RenX_Game/Classes/RconProtocol.uci)
- [Native RCON connection and escaping](https://github.com/TotemArts/Renegade-X/blob/master/Development/Src/RenX_Game/Classes/Rx_RconConnection.uc)
- [UE3 configuration inheritance and array operations](https://docs.unrealengine.com/udk/Three/ConfigurationFiles.html)

These references informed the implementation. They are not evidence that this image
has passed a game-server runtime test.
