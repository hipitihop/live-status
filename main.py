import os
import re
import subprocess
import time
from paho.mqtt import client as mqtt_client
import platform
import json

# Every so many seconds, check the status of the uvcvideo device
# and whenever it changes, post the status change to MQTT

broker = "192.168.0.102"
port = 1883
client_id = "oceanus2"
topic = f"on-air/{client_id}/status"


def connect_mqtt():
    print(f"connecting to MQTT from host \"{platform.node()}\"...")

    def on_log(client, userdata, level, buf):
        print("mqtt: ", buf)

    def on_connect(client, userdata, flags, rc):
        if rc==0:
            print("Successfully connected to MQTT broker")
        else:
            print("Failed to connect, return code %d", rc)
    mqtt = mqtt_client.Client(platform.node())
    # client.on_log = on_log
    mqtt.on_connect = on_connect
    mqtt.connect(broker, port)
    mqtt.loop_start()
    return mqtt


mqtt = connect_mqtt()


def current_video_status():
    results = subprocess.run(args=["lsmod"], capture_output=True).stdout.decode().splitlines()
    status = 0
    for line in results:
        line_parts = line.split()
        if line_parts[0] == "uvcvideo":
            status = line_parts[2]
    return status


# filter for uvcvideo
def filter_regex(datalist, rexp):
    return [val for val in datalist
            if re.search(rexp, val.__str__())]


def main():
    resolution_in_seconds = 2
    prior_status = current_video_status()
    mqtt_topic = f"transmit_posture/{platform.node()}/status"
    mqtt.publish(topic=mqtt_topic, payload=json.dumps({"status": prior_status}))
    # when off, debounce sporadic noise which triggers on, by waiting for enough
    # resolution cycles to occur in the on position before we report it.
    on_debounce = 0
    notified_on = False
    while True:
        print("debounce value:", on_debounce)
        current_state = current_video_status()
        if current_state == "1":
            on_debounce += 1
        else:
            on_debounce = 0
            notified_on = False

        if current_state == "0" and current_state != prior_status:
            prior_status = current_state
            mqtt.publish(topic=mqtt_topic, payload=json.dumps({"status": current_state}))
            print("changed to:", current_state)
        elif on_debounce >= resolution_in_seconds and not notified_on:
            prior_status = current_state
            mqtt.publish(topic=mqtt_topic, payload=json.dumps({"status": current_state}))
            notified_on = True
            print("changed to:", current_state)

        time.sleep(resolution_in_seconds)


if __name__ == '__main__':
    main()