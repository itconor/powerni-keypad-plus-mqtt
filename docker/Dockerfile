# Standalone Docker image — meter bridge + scan/pair web GUI, no Home Assistant needed.
# Build context is the repo root (see docker-compose.yml).
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bluez \
        dbus \
        python3 \
        python3-paho-mqtt \
        python3-flask \
        python3-pexpect \
    && rm -rf /var/lib/apt/lists/*

COPY keypad_meter.py            /keypad_meter.py
COPY powerni_keypad/pair_ui.py  /pair_ui.py

ENV INGRESS_PORT=8099
EXPOSE 8099

# pair_ui.py serves the web GUI (scan/select/pair) and supervises keypad_meter.py
CMD ["python3", "/pair_ui.py"]
