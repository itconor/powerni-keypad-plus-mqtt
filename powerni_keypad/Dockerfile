ARG BUILD_FROM
FROM ${BUILD_FROM}

# bluez = Bluetooth stack (RFCOMM), plus python + paho-mqtt
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bluez \
        python3 \
        python3-paho-mqtt \
    && rm -rf /var/lib/apt/lists/*

COPY keypad_meter.py /keypad_meter.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
