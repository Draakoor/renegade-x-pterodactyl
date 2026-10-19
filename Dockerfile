# syntax=docker/dockerfile:1.7
FROM ghcr.io/ptero-eggs/yolks@sha256:db48c30fc50104a43d951200174d33e2b9200f80b03b3ded9c106586450dbcf8

ARG IMAGE_VERSION=0.1.0
ARG VCS_REF=unknown
LABEL org.opencontainers.image.title="Renegade X for Pterodactyl" \
      org.opencontainers.image.description="Wine runtime and explicit installer for Renegade X. Runtime not tested." \
      org.opencontainers.image.source="https://github.com/draakoor/renegade-x-pterodactyl" \
      org.opencontainers.image.url="https://github.com/draakoor/renegade-x-pterodactyl" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.authors="Draakoor" \
      org.opencontainers.image.licenses="MIT"

USER root
RUN groupadd --gid 1000 container \
    && useradd --uid 1000 --gid 1000 --home-dir /home/container --shell /bin/bash container \
    && mkdir -p /home/container /opt/renegade-x \
    && chown container:container /home/container

# The explicit installer obtains checksum-pinned helpers and game content later.
COPY scripts/ /opt/renegade-x/
COPY sources.lock.json LICENSE THIRD_PARTY.md /opt/renegade-x/
RUN chmod 755 /opt/renegade-x/entrypoint.sh \
    && chmod 644 /opt/renegade-x/*.py

ENV HOME=/home/container USER=container WINEARCH=win64 \
    WINEPREFIX=/home/container/.wine WINEDEBUG=-all \
    WINEDLLOVERRIDES="mscoree,mshtml=" AUTO_UPDATE=0 \
    LANG=en_US.UTF-8 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    RENX_IMAGE_VERSION=${IMAGE_VERSION}
USER container
WORKDIR /home/container
EXPOSE 7777/udp 27015/udp
STOPSIGNAL SIGTERM
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/renegade-x/entrypoint.sh"]
CMD ["start"]
