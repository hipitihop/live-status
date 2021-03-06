import logging
import json
import platform
import re
import subprocess
import time
from datetime import datetime
from paho.mqtt import client as mqtt_client

"""
Periodically checks the status of both video device and microphones.
Whenever the combined status changes, post the status change to MQTT.

- Video device usage is detected via "lsmod" based on "uvcvideo" device. See: current_video_status()
- Microphone usage is detected via "pactl" and detects anything listed as an "alsa_input.".
  See: current_mic_status()
  NOTE: This detects if an application like Google Meet has grabbed the microphone, but does not
        detect if the microphone is muted or not. If the host has more then one device then all are considered. 
"""
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(asctime)s - %(message)s')
broker = "localhost"
port = 1883
alsa_input_regex = r"^alsa_input\."
resolution_in_seconds = 2

__mqtt_client = None
__mqtt_connected = False


def current_video_status():
    results = subprocess.run(args=["lsmod"], capture_output=True).stdout.decode().splitlines()
    status = 0
    for line in results:
        line_parts = line.split()
        if line_parts[0] == "uvcvideo":
            status = line_parts[2]
    return status


def current_mic_status():
    results = subprocess.run(args=["pactl", "list", "sources", "short"], capture_output=True).stdout.decode().splitlines()
    status = "SUSPENDED"
    for line in results:
        line_parts = line.split()
        if re.match(alsa_input_regex, line_parts[1]) and line_parts[6] == "RUNNING":
            return "RUNNING"
    return status


def monitor():
    while not __mqtt_connected:
        time.sleep(1)

    # Our status is considered to be a combination of either the microphone or the video being used/grabbed
    # by any application like Google Meet, Zoom etc. We detect the microphone and the video device state separately,
    # but we don't detect what app is using them.
    # So for example, if you start Cheese which only uses only video, something else could be using the microphone.
    # In the case of the video/webcam, we can detected if the video is live via uvcvideo such that
    # if Google Meet is open, but the video off button is enabled, we detect it as on.
    # Conversely, if the video is turned on via the button, we detect the change. However, with the Microphone we
    # only see if it is being used by the app and this considers the Mic being live,
    # but we don't detect if it is muted or not.
    # Either way, if either of them are considered on then our posture is considered as on (transmitting).
    logging.info(f"Starting monitoring loop. Checking every {resolution_in_seconds} sec.")
    ts = datetime.utcnow().isoformat()[:-3]+'Z'
    prior_vid_state = current_video_status()
    prior_mic_state = current_mic_status()
    prior_posture = '1' if prior_vid_state == '1' or prior_mic_state == 'RUNNING' '1' else '0'
    mqtt_topic = f"transmit_posture/{platform.node()}/status"
    __mqtt_client.publish(topic=mqtt_topic, payload=json.dumps({"status": prior_posture, "ts": ts}))
    logging.info(f"current posture: {prior_posture}")
    # when off, debounce sporadic noise which triggers on, by waiting for enough
    # resolution cycles to occur in the on position before we report it.
    on_debounce = 0
    notified_on = False
    while True:
        ts = datetime.utcnow().isoformat()[:-3]+'Z'
        current_vid_state = current_video_status()
        current_mic_state = current_mic_status()
        current_posture = '0'
        if current_vid_state == '1' or current_mic_state == 'RUNNING':
            current_posture = '1'
        logging.debug(f"state vid: {current_vid_state} mic: {current_mic_state} posture: {current_posture} ts: {ts}")
        if current_vid_state == "1" or current_mic_state == 'RUNNING':
            on_debounce += 1
        else:
            on_debounce = 0
            notified_on = False

        if current_posture == "0" and current_posture != prior_posture:
            prior_vid_state = current_vid_state
            prior_mic_state = current_mic_state
            prior_posture = current_posture
            __mqtt_client.publish(topic=mqtt_topic, payload=json.dumps({"status": current_posture, "ts": ts}))
            logging.info(f"posture changed to: {current_posture}")
        elif on_debounce >= resolution_in_seconds and not notified_on:
            prior_vid_state = current_vid_state
            prior_mic_state = current_mic_state
            prior_posture = current_posture
            __mqtt_client.publish(topic=mqtt_topic, payload=json.dumps({"status": current_posture, "ts": ts}))
            notified_on = True
            logging.info(f"posture changed to: {current_posture}")

        time.sleep(resolution_in_seconds)


def connect_mqtt():
    global __mqtt_client
    logging.info(f"connecting to MQTT broker {broker}:{port} from host \"{platform.node()}\"...")

    def on_connect(client, userdata, flags, rc):
        global __mqtt_connected
        if rc == 0:
            __mqtt_connected = True
            logging.info(f"Successfully connected to MQTT broker.")
        else:
            logging.warning(f"Failed to connect to MQTT broker, return code {rc}")
    __mqtt_client = mqtt_client.Client(platform.node())
    # client.on_log = on_log
    __mqtt_client.on_connect = on_connect
    __mqtt_client.connect(broker, port)
    __mqtt_client.loop_start()


def main():
    connect_mqtt()
    monitor()


if __name__ == '__main__':
    main()
