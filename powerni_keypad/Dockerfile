ARG BUILD_FROM
FROM ${BUILD_FROM}

# bluez = Bluetooth stack (RFCOMM) + bluetoothctl (pairing);
# python + paho-mqtt (bridge), flask + pexpect (in-HA pairing UI)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bluez \
        python3 \
        python3-paho-mqtt \
        python3-flask \
        python3-pexpect \
    && rm -rf /var/lib/apt/lists/*

COPY keypad_meter.py /keypad_meter.py
COPY pair_ui.py /pair_ui.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
