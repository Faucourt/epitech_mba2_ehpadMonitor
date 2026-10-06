// Each namespace reads its own component. No fan-out or resident data cloning.
#include "device_config.h"
#include <WiFi.h>
#include <PubSubClient.h>
#include "finite_float.h"
#include "endpoints.h"
WiFiClient network;
PubSubClient mqtt(network);
String bootId;
uint32_t lastConnect=0,lastWifi=0,lastPublish=0;
unsigned publishIndex=0;

void setup() {
  Serial.begin(115200);
  Wire.begin(21,22);Wire.setTimeOut(50);prepareGroupSPI();analogReadResolution(12);
  // Initialize every slave select before initializing any SPI reader.
  for(auto &endpoint:endpoints) endpoint.begin();
  WiFi.mode(WIFI_STA); // Enables the ESP32 RNG entropy source.
  bootId=String(uint32_t(esp_random()),HEX);
#if !COLLECTIVE_SERIAL_GATEWAY
  WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
  mqtt.setServer(MQTT_HOST,MQTT_PORT);mqtt.setBufferSize(4096);
  mqtt.setSocketTimeout(1);mqtt.setKeepAlive(15);
#endif
  Serial.printf("GROUP READY %s %u\n",ENTITY_ID,ENDPOINT_COUNT);
}

void loop() {
  for(auto &endpoint:endpoints)endpoint.tick();
  uint32_t now=millis();
#if !COLLECTIVE_SERIAL_GATEWAY
  if(WiFi.status()!=WL_CONNECTED&&now-lastWifi>15000){lastWifi=now;WiFi.reconnect();}
  if(WiFi.status()==WL_CONNECTED&&!mqtt.connected()&&now-lastConnect>5000){
    lastConnect=now;if(bootId.length()==0)bootId=String(uint32_t(esp_random()),HEX);
    String client=String("ehpad-")+ENTITY_ID+"-"+bootId;
    if(mqtt.connect(client.c_str(),MQTT_USER,MQTT_PASSWORD))Serial.println("GROUP MQTT CONNECTED");
  }
  mqtt.loop();
#endif
  // Spread publications across the two-second cycle to avoid a large burst.
  if(now-lastPublish>=2000/ENDPOINT_COUNT){
    lastPublish=now;
    auto &endpoint=endpoints[publishIndex];publishIndex=(publishIndex+1)%ENDPOINT_COUNT;
    JsonDocument doc;doc["schema"]=1;doc["device_id"]=endpoint.id;doc["entity_id"]=ENTITY_ID;
    doc["kind"]=endpoint.kind;doc["source"]=WOKWI_BUILD?"wokwi":"hardware";
    doc["boot"]=bootId;doc["seq"]=++endpoint.seq;doc["uptime_ms"]=now;
    bool valid=*endpoint.lastValid&&now-*endpoint.lastValid<10000;
    doc["available"]=valid;doc["sample_age_ms"]=*endpoint.lastValid?now-*endpoint.lastValid:uint32_t(0xffffffff);
    if(valid)doc["values"].set(endpoint.values->as<JsonObject>());else doc["values"].to<JsonObject>();
    String payload;serializeJson(doc,payload);
#if COLLECTIVE_SERIAL_GATEWAY
    Serial.print("SAMPLE ");Serial.println(payload);
#else
    String topic=String(MQTT_PREFIX)+"/"+endpoint.id+"/telemetry";
    bool sent=mqtt.connected()&&mqtt.publish(topic.c_str(),payload.c_str(),false);
    Serial.print(sent?"PUB ":"LOCAL ");Serial.println(payload);
#endif
  }
  delay(1);
}
