#pragma once
#define ENTITY_ID "pharmacie_admin"
#define WOKWI_BUILD 1
// CLI receives actual virtual UART samples and forwards them to local MQTT.
// Physical firmware retains direct WiFi/MQTT transport.
#define COLLECTIVE_SERIAL_GATEWAY WOKWI_BUILD
#if WOKWI_BUILD
#define WIFI_SSID "Wokwi-GUEST"
#define WIFI_PASSWORD ""
#define MQTT_HOST "test.mosquitto.org"
#define MQTT_PREFIX "ehpad/lab/lebretyves-all/v1"
#define LOAD_SCALE 420
#else
#define WIFI_SSID "CHANGE_ME"
#define WIFI_PASSWORD ""
#define MQTT_HOST "192.168.1.10"
#define MQTT_PREFIX "ehpad/hardware/v1"
#define LOAD_SCALE 0
#endif
#define MQTT_PORT 1883
#define MQTT_USER ""
#define MQTT_PASSWORD ""
#define LOAD_OFFSET 0
