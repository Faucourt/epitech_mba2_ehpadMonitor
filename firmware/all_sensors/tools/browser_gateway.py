"""Forward live browser UART frames only; never retain or queue disconnected data."""
import json
import sys
import paho.mqtt.client as mqtt

client = mqtt.Client(client_id='ehpad-browser-gateway')
client.reconnect_delay_set(1, 10)
client.connect('127.0.0.1', 1887, 30)
client.loop_start()
try:
    for line in sys.stdin:
        row = json.loads(line)
        if client.is_connected() and row.get('source') == 'wokwi':
            client.publish('ehpad/lab/lebretyves-all/v1/' + row['device_id'] + '/telemetry',
                           line.strip(), qos=0, retain=False)
finally:
    client.disconnect()
    client.loop_stop()
