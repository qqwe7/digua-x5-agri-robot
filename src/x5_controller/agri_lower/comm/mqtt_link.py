import json
import time

import paho.mqtt.client as mqtt


class MqttLink:
    """MQTT link between the RDK_X5 Pi and the upper-control app."""

    def __init__(self, broker, port, prefix, client_id):
        self.broker = broker
        self.port = port
        self.prefix = prefix.strip("/")
        self.client_id = client_id
        self.client = mqtt.Client(client_id=client_id)
        self.command_handler = None
        self.connected = False

    def start(self):
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def set_command_handler(self, handler):
        self.command_handler = handler

    def publish(self, suffix, payload):
        topic = f"{self.prefix}/{suffix.strip('/')}"
        data = dict(payload)
        data.setdefault("timestamp", time.time())
        self.client.publish(topic, json.dumps(data, ensure_ascii=False), qos=0)

    def publish_status(self, payload):
        self.publish("status", payload)

    def publish_telemetry(self, payload):
        self.publish("telemetry", payload)

    def publish_media(self, payload):
        self.publish("media", payload)

    def publish_plan(self, payload):
        self.publish("plan/report", payload)

    def publish_result(self, payload):
        self.publish("command/result", payload)

    def _on_connect(self, client, userdata, flags, rc):
        self.connected = rc == 0
        print("mqtt connected rc=", rc)
        client.subscribe(f"{self.prefix}/command/down")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        print("mqtt disconnected rc=", rc)

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as exc:
            print("bad mqtt payload:", exc)
            return
        if self.command_handler:
            self.command_handler(payload)
