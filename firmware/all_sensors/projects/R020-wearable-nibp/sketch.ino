// Shared source: generated device_config.h selects one physical sensor endpoint.
#include "device_config.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include "sensors.h"
WiFiClient network;
PubSubClient mqtt(network);
String baseTopic=String(MQTT_PREFIX)+"/"+DEVICE_ID;
String bootId;
uint32_t seq=0,lastPublish=0,lastConnect=0,lastWifi=0;
void setup() {
  Serial.begin(115200);delay(100);
  sensorBegin();
  WiFi.mode(WIFI_STA);WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
  mqtt.setServer(MQTT_HOST,MQTT_PORT);mqtt.setBufferSize(4096);mqtt.setSocketTimeout(1);mqtt.setKeepAlive(15);
  Serial.printf("READY %s %s\n",DEVICE_ID,SENSOR_KIND);
}
void loop() {
  sensorTick();uint32_t now=millis();
  if(WiFi.status()!=WL_CONNECTED && now-lastWifi>15000){lastWifi=now;WiFi.reconnect();}
  if(WiFi.status()==WL_CONNECTED && !mqtt.connected() && now-lastConnect>3000) {
    // WiFi enables the ESP32 hardware RNG entropy source before session creation.
    if(bootId.length()==0)bootId=String(uint32_t(esp_random()),HEX);
    lastConnect=now;String client=String(DEVICE_ID)+"-"+bootId;
    String will=String("{\"online\":false,\"boot\":\"")+bootId+"\"}";
    if(mqtt.connect(client.c_str(),MQTT_USER,MQTT_PASSWORD,(baseTopic+"/status").c_str(),1,true,will.c_str())) {
      String status=String("{\"online\":true,\"boot\":\"")+bootId+"\"}";
      mqtt.publish((baseTopic+"/status").c_str(),status.c_str(),true);
    }
  }
  mqtt.loop();
  if(now-lastPublish>=2000) {
    lastPublish=now;
    JsonDocument doc;doc["schema"]=1;doc["device_id"]=DEVICE_ID;doc["entity_id"]=ENTITY_ID;doc["kind"]=SENSOR_KIND;
    doc["source"]=WOKWI_BUILD?"wokwi":"hardware";doc["boot"]=bootId;doc["seq"]=++seq;doc["uptime_ms"]=now;
    bool valid=lastValid!=0 && now-lastValid<10000;
    doc["available"]=valid;doc["sample_age_ms"]=lastValid ? now-lastValid : uint32_t(0xffffffff);
    if(valid)doc["values"].set(values.as<JsonObject>());else doc["values"].to<JsonObject>();
    String payload;serializeJson(doc,payload);
    bool sent=mqtt.connected() && mqtt.publish((baseTopic+"/telemetry").c_str(),payload.c_str(),false);
    Serial.print(sent?"PUB ":"LOCAL ");Serial.println(payload);
  }
  delay(1);
}
