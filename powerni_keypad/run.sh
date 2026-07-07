#!/usr/bin/with-contenv bashio
# ---------------------------------------------------------------------------
# PowerNI keypad+ add-on entrypoint.
# Reads the add-on options + (optionally) the Mosquitto add-on's MQTT service,
# then runs the bundled keypad_meter.py bridge.
# ---------------------------------------------------------------------------
set -e

# --- meter / polling -------------------------------------------------------
export METER_MAC="$(bashio::config 'meter_mac')"
export METER_CH="$(bashio::config 'meter_channel')"
export POLL_SECS="$(bashio::config 'poll_seconds')"

if bashio::var.is_empty "${METER_MAC}"; then
    bashio::log.info "No meter_mac set — pick your meter with the Scan button in the 'Meter Pairing' panel."
fi

# --- MQTT: prefer an explicit host, else fall back to the Mosquitto add-on -
if bashio::config.has_value 'mqtt_host'; then
    export MQTT_HOST="$(bashio::config 'mqtt_host')"
    export MQTT_PORT="$(bashio::config 'mqtt_port')"
    export MQTT_USER="$(bashio::config 'mqtt_user')"
    export MQTT_PASS="$(bashio::config 'mqtt_pass')"
    bashio::log.info "Using MQTT broker from add-on config: ${MQTT_HOST}:${MQTT_PORT}"
elif bashio::services.available "mqtt"; then
    export MQTT_HOST="$(bashio::services mqtt 'host')"
    export MQTT_PORT="$(bashio::services mqtt 'port')"
    export MQTT_USER="$(bashio::services mqtt 'username')"
    export MQTT_PASS="$(bashio::services mqtt 'password')"
    bashio::log.info "Using MQTT broker from the Mosquitto add-on: ${MQTT_HOST}:${MQTT_PORT}"
else
    bashio::log.fatal "No MQTT broker configured. Install the Mosquitto broker add-on, or set mqtt_host in the Configuration tab."
    exit 1
fi

export INGRESS_PORT=8099
bashio::log.info "Meter ${METER_MAC} ch ${METER_CH}, poll ${POLL_SECS}s — open the 'Meter Pairing' panel to pair."
# pair_ui.py serves the ingress pairing page AND supervises keypad_meter.py
# (auto-starts the bridge once the meter is paired).
exec python3 /pair_ui.py
