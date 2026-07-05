import time

from agri_lower.comm.mqtt_link import MqttLink
from agri_lower.config import DEVICE_ID, MQTT_BROKER, MQTT_PORT, MQTT_PREFIX


def main():
    mqtt = MqttLink(MQTT_BROKER, MQTT_PORT, MQTT_PREFIX, "digua_x5-headless")
    mqtt.start()
    print("headless lower controller started")
    while True:
        payload = {
            "device_id": DEVICE_ID,
            "message": "headless heartbeat",
            "rdk_x5_online": True,
        }
        mqtt.publish_status(payload)
        mqtt.publish_telemetry(payload)
        print("published:", payload)
        time.sleep(3)


if __name__ == "__main__":
    main()
