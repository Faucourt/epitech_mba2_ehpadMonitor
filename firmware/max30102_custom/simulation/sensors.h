#pragma once
#include <Wire.h>
#include <SPI.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <HX711.h>
#include <MAX30105.h>
#include <spo2_algorithm.h>
#include <MFRC522.h>
#include <TinyGPS++.h>
#include <VOCGasIndexAlgorithm.h>
#include "protocols.h"
#if !WOKWI_BUILD
#include <BLEDevice.h>
#endif

JsonDocument values;
DHT dht(27,DHT22);
HX711 scale;
MAX30105 optical;
MFRC522 rfid(5,22);
TinyGPSPlus gps;
VOCGasIndexAlgorithm vocAlgorithm;
bool sensorReady=false;
uint32_t lastSensor=0, lastValid=0, lastOptical=0;
uint32_t redSamples[100], irSamples[100];
unsigned sampleCount=0;
#include "nibp.h"
bool kind(const char *s) { return strcmp(SENSOR_KIND,s)==0; }
uint32_t adcMillivolts(uint8_t pin) {
#if WOKWI_BUILD
  // Wokwi Analog API uses a 5 V reference for every virtual ADC.
  // https://docs.wokwi.com/chips-api/analog
  return (uint32_t(analogRead(pin))*5000u+2047u)/4095u;
#else
  return analogReadMilliVolts(pin); // Real ESP32 factory calibration.
#endif
}
bool regRead(uint8_t addr,uint8_t reg,uint8_t *out,uint8_t n) {
  Wire.beginTransmission(addr); Wire.write(reg);
  if(Wire.endTransmission(false)!=0) return false;
  if(Wire.requestFrom(addr,n)!=n) { while(Wire.available()) Wire.read(); return false; }
  for(int i=0;i<n;i++) out[i]=Wire.read(); return true;
}
bool regWrite(uint8_t addr,uint8_t reg,uint8_t val) {
  Wire.beginTransmission(addr); Wire.write(reg); Wire.write(val); return Wire.endTransmission()==0;
}
bool command(uint8_t addr,uint16_t cmd) {
  Wire.beginTransmission(addr); Wire.write(cmd>>8); Wire.write(cmd&255); return Wire.endTransmission()==0;
}
bool words(uint8_t addr,uint16_t cmd,uint16_t *out,uint8_t n,uint16_t waitMs) {
  if(!command(addr,cmd)) return false;
  delay(waitMs);
  if(Wire.requestFrom(addr,uint8_t(n*3))!=n*3) {while(Wire.available()) Wire.read(); return false;}
  for(int i=0;i<n;i++) {uint8_t b[3]; for(int j=0;j<3;j++) b[j]=Wire.read(); if(sensirionCrc(b,2)!=b[2]) return false; out[i]=(b[0]<<8)|b[1];}
  return true;
}
void sensorBegin() {
  Wire.begin(21,22); Wire.setTimeOut(50);
  pinMode(27,INPUT_PULLUP); pinMode(32,INPUT_PULLDOWN); pinMode(33,INPUT_PULLDOWN);
  if(kind("pir") || kind("radar"))pinMode(27,INPUT_PULLDOWN);
  analogReadResolution(12); analogSetPinAttenuation(34,ADC_11db);
  Serial2.begin(kind("nibp")?4800:9600,SERIAL_8N1,16,17);
  if(kind("nibp"))pinMode(26,INPUT_PULLUP);
  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); sensorReady=true;}
  else if(kind("rfid")) {Wire.end(); SPI.begin(); rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
  else sensorReady=true;
#if !WOKWI_BUILD
  if(kind("ble")) {BLEDevice::init(DEVICE_ID); BLEDevice::getScan()->setActiveScan(false);}
#endif
}
void readOptical() {
  if(!sensorReady) return;
  // SparkFun configures the real device; acquire complete RED/IR pairs directly
  // to check I2C byte counts and avoid its four-slot software FIFO losing data.
  // Same registers and acquisition path on hardware and in Wokwi (100Hz / 4).
  uint8_t pointers[3];
  bool ok=regRead(0x57,0x04,pointers,3);
  unsigned queued=ok ? ((pointers[0]-pointers[2])&31) : 0;
  // 32 samples can make WR_PTR == RD_PTR. Also discard after a polling gap
  // long enough to fill the FIFO, even if a counter/read masks that situation.
  if(!ok || pointers[1] || (lastOptical && millis()-lastOptical>=1200)) {
    values.clear();sampleCount=0;lastValid=lastOptical=0;
    if(!ok) {sensorReady=false;return;}
    bool reset=regWrite(0x57,0x04,0);
    reset=regWrite(0x57,0x05,0) && reset;
    reset=regWrite(0x57,0x06,0) && reset;
    if(!reset)sensorReady=false;
    return;
  }
  for(unsigned sample=0;sample<queued;sample++) {
    uint8_t pair[6];
    if(!regRead(0x57,0x07,pair,6)) {
      // A partial transfer can leave FIFO_DATA mid-sample. Reinitialization
      // on the existing retry path resets both pointers before reacquisition.
      values.clear();sampleCount=0;lastValid=lastOptical=0;sensorReady=false;return;
    }
    uint32_t r=((uint32_t(pair[0])<<16)|(uint32_t(pair[1])<<8)|pair[2])&0x3ffff;
    uint32_t ir=((uint32_t(pair[3])<<16)|(uint32_t(pair[4])<<8)|pair[5])&0x3ffff;
    values["red_raw"]=r; values["ir_raw"]=ir; lastValid=millis(); lastOptical=millis();
    if(ir<5000) {sampleCount=0; values["heart_rate"]=nullptr; values["spo2"]=nullptr; continue;}
    redSamples[sampleCount]=r; irSamples[sampleCount++]=ir;
    if(sampleCount==100) {
      int32_t spo2,hr; int8_t validSpo2,validHr;
      maxim_heart_rate_and_oxygen_saturation(irSamples,100,redSamples,&spo2,&validSpo2,&hr,&validHr);
      if(validHr && hr>=30 && hr<=240) values["heart_rate"]=hr; else values["heart_rate"]=nullptr;
      if(validSpo2 && spo2>=50 && spo2<=100) values["spo2"]=spo2; else values["spo2"]=nullptr;
      memmove(irSamples,irSamples+25,75*sizeof(uint32_t)); memmove(redSamples,redSamples+25,75*sizeof(uint32_t)); sampleCount=75;
    }
  }
  if(millis()-lastOptical>3000) {values.clear();sampleCount=0;lastValid=0;}
}
void readSerialSensor() {
  static uint8_t frame[9]; static unsigned count=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();
    if(kind("gps")) {gps.encode(b); continue;}
    uint8_t start=kind("ze07co")?0xff:0xa5;
    if(count==0 && b!=start) continue;
    frame[count++]=b; unsigned length=kind("ze07co")?9:8;
    if(count==length) {
      float a,c;
      if(kind("ze07co") && ze07Frame(frame,a)) {values["co_ppm"]=a;lastValid=millis();}
      // Resume scanning the next frame; never publish an invalid checksum.
      count=0;
    }
  }
  if(kind("gps")) {
    bool fix=gps.location.isValid() && gps.location.age()<5000;
    values["gps_fix"]=fix;
    if(fix) {values["latitude"]=gps.location.lat();values["longitude"]=gps.location.lng();lastValid=millis();}
    else {values["latitude"]=nullptr;values["longitude"]=nullptr;}
  }
  if(millis()-lastValid>10000 && !kind("gps")) values.clear();
}
void sensorTick() {
  uint32_t now=millis();
  static uint32_t retried=0;
  if(kind("nibp")){readNibp();return;}
  if(now-lastValid>10000 && now-retried>15000){retried=now;sensorBegin();}
  if(kind("max30102")) {readOptical();return;}
  if(kind("gps") || kind("ze07co") || kind("nibp")) {readSerialSensor();return;}
  uint32_t interval=(kind("ecg")||kind("respiration"))?10:(kind("mpu6050")||kind("sos"))?20:kind("dht22")?2200:(kind("sgp30")||kind("sgp40"))?1000:500;
  if(now-lastSensor<interval) return; lastSensor=now;
  bool ok=false;
  if(kind("mpu6050")) {
    uint8_t b[14]; ok=regRead(0x68,0x3b,b,14);
    if(ok) {float a=0,g=0;for(int i=0;i<3;i++){float v=int16_t((b[2*i]<<8)|b[2*i+1])/16384.f;a+=v*v;v=int16_t((b[8+2*i]<<8)|b[9+2*i])/131.f;g+=v*v;}
      values["accel_g"]=sqrtf(a);values["gyro_dps"]=sqrtf(g);
      static uint32_t impactAt=0; if(sqrtf(a)>2.5f) impactAt=now;
      values["impact"]=impactAt!=0 && now-impactAt<3000;}
  } else if(kind("tmp117")) {uint8_t b[2];ok=regRead(0x48,0,b,2);if(ok)values["contact_temperature_c"]=int16_t((b[0]<<8)|b[1])/128.f;
  } else if(kind("scd41")) {
    uint16_t ready,w[3];ok=words(0x62,0xe4b8,&ready,1,1);
    if(ok && (ready&0x7ff) && words(0x62,0xec05,w,3,1) && w[0]>0) {
      values["co2_ppm"]=w[0];values["temperature_c"]=-45+175.f*w[1]/65535;values["humidity_pct"]=100.f*w[2]/65535;lastValid=now;
    } return;
  } else if(kind("sgp30")) {uint16_t w[2];ok=words(0x58,0x2008,w,2,15);if(ok && now>15000){values["eco2_ppm"]=w[0];values["tvoc_ppb"]=w[1];}else ok=false;
  } else if(kind("sgp40")) {
    uint8_t cmd[8]={0x26,0x0f,0x80,0x00,0,0x66,0x66,0};cmd[4]=sensirionCrc(cmd+2,2);cmd[7]=sensirionCrc(cmd+5,2);
    Wire.beginTransmission(0x59);Wire.write(cmd,8);ok=Wire.endTransmission()==0;delay(30);
    if(ok && Wire.requestFrom(uint8_t(0x59),uint8_t(3))==3){uint8_t b[3];for(int i=0;i<3;i++)b[i]=Wire.read();ok=sensirionCrc(b,2)==b[2];if(ok){uint16_t raw=(b[0]<<8)|b[1];values["voc_raw"]=raw;int32_t index=vocAlgorithm.process(raw);if(index>0)values["voc_index"]=index;else values["voc_index"]=nullptr;}}else ok=false;
  } else if(kind("amg8833")) {
    uint8_t b[128];ok=true;for(int i=0;i<4;i++)if(!regRead(0x69,0x80+i*32,b+i*32,32))ok=false;
    if(ok){JsonArray arr=values["thermal_pixels_c"].to<JsonArray>();float peak=-100;for(int i=0;i<64;i++){float v=amgPixel(b[i*2],b[i*2+1]);arr.add(v);peak=max(peak,v);}values["thermal_max_c"]=peak;}
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=isfinite(t)&&isfinite(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
  } else if(kind("hx711")) {ok=scale.is_ready();if(ok){long raw=scale.read();values["load_raw"]=raw;if(LOAD_SCALE!=0)values["load_kg"]=(raw-LOAD_OFFSET)/float(LOAD_SCALE);else values["load_kg"]=nullptr;}
  } else if(kind("rfid")) {
    if(sensorReady && rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {char uid[21]={0}; for(byte i=0;i<rfid.uid.size && i<10;i++)sprintf(uid+2*i,"%02X",rfid.uid.uidByte[i]);values["tag_uid"]=uid;ok=true;rfid.PICC_HaltA();}
    if(ok)lastValid=now;if(now-lastValid>10000)values["tag_uid"]=nullptr;return;
  } else if(kind("sos") || kind("door")) {
    static bool stable=false,lastRaw=false;static uint32_t changed=0,pressed=0;
    bool raw=kind("sos") ? !digitalRead(27) : digitalRead(27);
    if(raw!=lastRaw){changed=now;lastRaw=raw;}if(now-changed>=40)stable=raw;
    if(kind("sos")){if(stable)pressed=now;values["sos_pressed"]=stable || (pressed && now-pressed<3000);} else values["door_open"]=stable;
    ok=true;
  } else if(kind("pir") || kind("radar")) {values[kind("pir")?"motion":"presence"]=bool(digitalRead(27));ok=true;
  } else if(kind("mq2")) {values["gas_adc"]=analogRead(34);ok=true;
  } else if(kind("sound")) {
    int mv=adcMillivolts(34);values["sound_mv"]=mv;ok=mv>=600 && mv<=2600;if(ok)values["sound_db"]=mv/20.f;
  } else if(kind("ecg")) {bool off=digitalRead(32)||digitalRead(33);values["leads_off"]=off;if(off)values["ecg_mv"]=nullptr;else values["ecg_mv"]=adcMillivolts(34);ok=true;
  } else if(kind("respiration")) {
    int mv=adcMillivolts(34);values["respiration_mv"]=mv;
    static bool high=false;static uint32_t peak=0;
    if(!high && mv>1800){high=true;uint32_t period=now-peak;if(peak && period>=1000 && period<=15000)values["respiratory_rate"]=60000.f/period;peak=now;}
    if(mv<1500)high=false;if(!peak || now-peak>15000)values["respiratory_rate"]=nullptr;ok=true;
  } else if(kind("ble")) {
#if WOKWI_BUILD
    uint8_t b[7];ok=regRead(0x30,0,b,7);if(ok){char mac[18];snprintf(mac,sizeof(mac),"%02X:%02X:%02X:%02X:%02X:%02X",b[0],b[1],b[2],b[3],b[4],b[5]);values["ble_address"]=mac;values["ble_rssi_dbm"]=int8_t(b[6]);}
#else
    static uint32_t scanAt=0;if(now-scanAt<10000)return;scanAt=now;
    BLEScan *scan=BLEDevice::getScan();BLEScanResults results=scan->start(1,false);
    int strongest=-200;String address;
    for(int i=0;i<results.getCount();i++){auto d=results.getDevice(i);if(d.getRSSI()>strongest){strongest=d.getRSSI();address=d.getAddress().toString().c_str();}}
    ok=strongest>-200;if(ok){values["ble_address"]=address;values["ble_rssi_dbm"]=strongest;}scan->clearResults();
#endif
  }
  if(ok)lastValid=now;else if(now-lastValid>10000)values.clear();
}
