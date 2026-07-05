import json
import os
import time
from typing import Any

import paho.mqtt.client as mqtt


MQTT_BROKER = os.environ.get("UPPER_MQTT_BROKER", "127.0.0.1")
MQTT_PORT = int(os.environ.get("UPPER_MQTT_PORT", "1883"))
MQTT_PREFIX = os.environ.get("UPPER_MQTT_PREFIX", "agri/digua_x5")
MQTT_USERNAME = os.environ.get("UPPER_MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("UPPER_MQTT_PASSWORD", "")


class UpperMqttBridge:
    def __init__(self) -> None:
        self.client = mqtt.Client(client_id=f"upper-backend-{int(time.time())}")
        self.started = False
        self.media_handler = None
        self.result_handler = None
        self.status_handler = None

    def start(self) -> None:
        if self.started:
            return
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        if MQTT_USERNAME:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, 60)
        except OSError as exc:
            print("upper mqtt connect skipped:", exc)
            return
        self.client.loop_start()
        self.started = True

    def stop(self) -> None:
        if not self.started:
            return
        self.client.loop_stop()
        self.client.disconnect()
        self.started = False

    def publish_command(self, payload: dict[str, Any]) -> None:
        topic = f"{MQTT_PREFIX}/command/down"
        self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=0)

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            print("upper mqtt connect failed rc=", rc)
            return
        print("upper mqtt connected rc=", rc)
        client.subscribe(f"{MQTT_PREFIX}/media")
        client.subscribe(f"{MQTT_PREFIX}/command/result")
        client.subscribe(f"{MQTT_PREFIX}/status")
        client.subscribe(f"{MQTT_PREFIX}/telemetry")

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            print("upper mqtt bad payload:", exc)
            return

        topic = msg.topic
        if topic.endswith("/media") and self.media_handler:
            self.media_handler(payload)
            return
        if topic.endswith("/command/result") and self.result_handler:
            self.result_handler(payload)
            return
        if (topic.endswith("/status") or topic.endswith("/telemetry")) and self.status_handler:
            self.status_handler(payload)


bridge = UpperMqttBridge()
