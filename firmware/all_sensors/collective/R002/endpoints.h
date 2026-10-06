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
HardwareSerial collectiveSerial1(1),collectiveSerial2(2);
namespace endpoint0 {
constexpr char SENSOR_KIND[]="mpu6050";
constexpr char DEVICE_ID[]="R002-wearable-mpu6050";
#if !WOKWI_BUILD
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

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  Serial2.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(27)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(26)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){Serial2.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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

  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
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

} // endpoint0
namespace endpoint1 {
constexpr char SENSOR_KIND[]="max30102";
constexpr char DEVICE_ID[]="R002-wearable-max30102";
#if !WOKWI_BUILD
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

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  Serial2.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(27)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(26)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){Serial2.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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

  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
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

} // endpoint1
namespace endpoint2 {
constexpr char SENSOR_KIND[]="tmp117";
constexpr char DEVICE_ID[]="R002-wearable-tmp117";
#if !WOKWI_BUILD
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

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  Serial2.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(27)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(26)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){Serial2.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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

  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
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

} // endpoint2
namespace endpoint3 {
constexpr char SENSOR_KIND[]="sos";
constexpr char DEVICE_ID[]="R002-wearable-sos";
#if !WOKWI_BUILD
#endif

JsonDocument values;
DHT dht(4,DHT22);
HX711 scale;
MAX30105 optical;
MFRC522 rfid(5,22);
TinyGPSPlus gps;
VOCGasIndexAlgorithm vocAlgorithm;
bool sensorReady=false;
uint32_t lastSensor=0, lastValid=0, lastOptical=0;
uint32_t redSamples[100], irSamples[100];
unsigned sampleCount=0;

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  Serial2.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(4)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(26)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){Serial2.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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
pinMode(4,INPUT_PULLUP);
  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
  } else if(kind("hx711")) {ok=scale.is_ready();if(ok){long raw=scale.read();values["load_raw"]=raw;if(LOAD_SCALE!=0)values["load_kg"]=(raw-LOAD_OFFSET)/float(LOAD_SCALE);else values["load_kg"]=nullptr;}
  } else if(kind("rfid")) {
    if(sensorReady && rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {char uid[21]={0}; for(byte i=0;i<rfid.uid.size && i<10;i++)sprintf(uid+2*i,"%02X",rfid.uid.uidByte[i]);values["tag_uid"]=uid;ok=true;rfid.PICC_HaltA();}
    if(ok)lastValid=now;if(now-lastValid>10000)values["tag_uid"]=nullptr;return;
  } else if(kind("sos") || kind("door")) {
    static bool stable=false,lastRaw=false;static uint32_t changed=0,pressed=0;
    bool raw=kind("sos") ? !digitalRead(4) : digitalRead(4);
    if(raw!=lastRaw){changed=now;lastRaw=raw;}if(now-changed>=40)stable=raw;
    if(kind("sos")){if(stable)pressed=now;values["sos_pressed"]=stable || (pressed && now-pressed<3000);} else values["door_open"]=stable;
    ok=true;
  } else if(kind("pir") || kind("radar")) {values[kind("pir")?"motion":"presence"]=bool(digitalRead(4));ok=true;
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

} // endpoint3
namespace endpoint4 {
constexpr char SENSOR_KIND[]="ecg";
constexpr char DEVICE_ID[]="R002-wearable-ecg";
#if !WOKWI_BUILD
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

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  Serial2.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(27)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(26)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){Serial2.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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
pinMode(13,INPUT_PULLDOWN);pinMode(14,INPUT_PULLDOWN);analogSetPinAttenuation(34,ADC_11db);
  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
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
  } else if(kind("ecg")) {bool off=digitalRead(13)||digitalRead(14);values["leads_off"]=off;if(off)values["ecg_mv"]=nullptr;else values["ecg_mv"]=adcMillivolts(34);ok=true;
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

} // endpoint4
namespace endpoint5 {
constexpr char SENSOR_KIND[]="respiration";
constexpr char DEVICE_ID[]="R002-wearable-respiration";
#if !WOKWI_BUILD
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

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  Serial2.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(27)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(26)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){Serial2.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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
analogSetPinAttenuation(35,ADC_11db);
  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
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
  } else if(kind("mq2")) {values["gas_adc"]=analogRead(35);ok=true;
  } else if(kind("sound")) {
    int mv=adcMillivolts(35);values["sound_mv"]=mv;ok=mv>=600 && mv<=2600;if(ok)values["sound_db"]=mv/20.f;
  } else if(kind("ecg")) {bool off=digitalRead(32)||digitalRead(33);values["leads_off"]=off;if(off)values["ecg_mv"]=nullptr;else values["ecg_mv"]=adcMillivolts(35);ok=true;
  } else if(kind("respiration")) {
    int mv=adcMillivolts(35);values["respiration_mv"]=mv;
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

} // endpoint5
namespace endpoint6 {
constexpr char SENSOR_KIND[]="nibp";
constexpr char DEVICE_ID[]="R002-wearable-nibp";
#if !WOKWI_BUILD
#endif

JsonDocument values;
DHT dht(18,DHT22);
HX711 scale;
MAX30105 optical;
MFRC522 rfid(5,22);
TinyGPSPlus gps;
VOCGasIndexAlgorithm vocAlgorithm;
bool sensorReady=false;
uint32_t lastSensor=0, lastValid=0, lastOptical=0;
uint32_t redSamples[100], irSamples[100];
unsigned sampleCount=0;

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  collectiveSerial1.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(collectiveSerial1.available()) {
    uint8_t b=collectiveSerial1.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(18)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(19)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){collectiveSerial1.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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
pinMode(18,INPUT_PULLUP);pinMode(19,INPUT_PULLUP);collectiveSerial1.begin(4800,SERIAL_8N1,16,17);
  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(19,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  while(collectiveSerial1.available()) {
    uint8_t b=collectiveSerial1.read();
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
  } else if(kind("hx711")) {ok=scale.is_ready();if(ok){long raw=scale.read();values["load_raw"]=raw;if(LOAD_SCALE!=0)values["load_kg"]=(raw-LOAD_OFFSET)/float(LOAD_SCALE);else values["load_kg"]=nullptr;}
  } else if(kind("rfid")) {
    if(sensorReady && rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {char uid[21]={0}; for(byte i=0;i<rfid.uid.size && i<10;i++)sprintf(uid+2*i,"%02X",rfid.uid.uidByte[i]);values["tag_uid"]=uid;ok=true;rfid.PICC_HaltA();}
    if(ok)lastValid=now;if(now-lastValid>10000)values["tag_uid"]=nullptr;return;
  } else if(kind("sos") || kind("door")) {
    static bool stable=false,lastRaw=false;static uint32_t changed=0,pressed=0;
    bool raw=kind("sos") ? !digitalRead(18) : digitalRead(18);
    if(raw!=lastRaw){changed=now;lastRaw=raw;}if(now-changed>=40)stable=raw;
    if(kind("sos")){if(stable)pressed=now;values["sos_pressed"]=stable || (pressed && now-pressed<3000);} else values["door_open"]=stable;
    ok=true;
  } else if(kind("pir") || kind("radar")) {values[kind("pir")?"motion":"presence"]=bool(digitalRead(18));ok=true;
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

} // endpoint6
namespace endpoint7 {
constexpr char SENSOR_KIND[]="radar";
constexpr char DEVICE_ID[]="R002-radar-radar";
#if !WOKWI_BUILD
#endif

JsonDocument values;
DHT dht(23,DHT22);
HX711 scale;
MAX30105 optical;
MFRC522 rfid(5,22);
TinyGPSPlus gps;
VOCGasIndexAlgorithm vocAlgorithm;
bool sensorReady=false;
uint32_t lastSensor=0, lastValid=0, lastOptical=0;
uint32_t redSamples[100], irSamples[100];
unsigned sampleCount=0;

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  Serial2.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(23)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(26)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){Serial2.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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
pinMode(23,INPUT_PULLDOWN);
  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
  } else if(kind("hx711")) {ok=scale.is_ready();if(ok){long raw=scale.read();values["load_raw"]=raw;if(LOAD_SCALE!=0)values["load_kg"]=(raw-LOAD_OFFSET)/float(LOAD_SCALE);else values["load_kg"]=nullptr;}
  } else if(kind("rfid")) {
    if(sensorReady && rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {char uid[21]={0}; for(byte i=0;i<rfid.uid.size && i<10;i++)sprintf(uid+2*i,"%02X",rfid.uid.uidByte[i]);values["tag_uid"]=uid;ok=true;rfid.PICC_HaltA();}
    if(ok)lastValid=now;if(now-lastValid>10000)values["tag_uid"]=nullptr;return;
  } else if(kind("sos") || kind("door")) {
    static bool stable=false,lastRaw=false;static uint32_t changed=0,pressed=0;
    bool raw=kind("sos") ? !digitalRead(23) : digitalRead(23);
    if(raw!=lastRaw){changed=now;lastRaw=raw;}if(now-changed>=40)stable=raw;
    if(kind("sos")){if(stable)pressed=now;values["sos_pressed"]=stable || (pressed && now-pressed<3000);} else values["door_open"]=stable;
    ok=true;
  } else if(kind("pir") || kind("radar")) {values[kind("pir")?"motion":"presence"]=bool(digitalRead(23));ok=true;
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

} // endpoint7
namespace endpoint8 {
constexpr char SENSOR_KIND[]="door";
constexpr char DEVICE_ID[]="R002-porte-door";
#if !WOKWI_BUILD
#endif

JsonDocument values;
DHT dht(25,DHT22);
HX711 scale;
MAX30105 optical;
MFRC522 rfid(5,22);
TinyGPSPlus gps;
VOCGasIndexAlgorithm vocAlgorithm;
bool sensorReady=false;
uint32_t lastSensor=0, lastValid=0, lastOptical=0;
uint32_t redSamples[100], irSamples[100];
unsigned sampleCount=0;

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  Serial2.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(25)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(26)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){Serial2.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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
pinMode(25,INPUT_PULLUP);
  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
  } else if(kind("hx711")) {ok=scale.is_ready();if(ok){long raw=scale.read();values["load_raw"]=raw;if(LOAD_SCALE!=0)values["load_kg"]=(raw-LOAD_OFFSET)/float(LOAD_SCALE);else values["load_kg"]=nullptr;}
  } else if(kind("rfid")) {
    if(sensorReady && rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {char uid[21]={0}; for(byte i=0;i<rfid.uid.size && i<10;i++)sprintf(uid+2*i,"%02X",rfid.uid.uidByte[i]);values["tag_uid"]=uid;ok=true;rfid.PICC_HaltA();}
    if(ok)lastValid=now;if(now-lastValid>10000)values["tag_uid"]=nullptr;return;
  } else if(kind("sos") || kind("door")) {
    static bool stable=false,lastRaw=false;static uint32_t changed=0,pressed=0;
    bool raw=kind("sos") ? !digitalRead(25) : digitalRead(25);
    if(raw!=lastRaw){changed=now;lastRaw=raw;}if(now-changed>=40)stable=raw;
    if(kind("sos")){if(stable)pressed=now;values["sos_pressed"]=stable || (pressed && now-pressed<3000);} else values["door_open"]=stable;
    ok=true;
  } else if(kind("pir") || kind("radar")) {values[kind("pir")?"motion":"presence"]=bool(digitalRead(25));ok=true;
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

} // endpoint8
namespace endpoint9 {
constexpr char SENSOR_KIND[]="pir";
constexpr char DEVICE_ID[]="R002-sdb_pir-pir";
#if !WOKWI_BUILD
#endif

JsonDocument values;
DHT dht(26,DHT22);
HX711 scale;
MAX30105 optical;
MFRC522 rfid(5,22);
TinyGPSPlus gps;
VOCGasIndexAlgorithm vocAlgorithm;
bool sensorReady=false;
uint32_t lastSensor=0, lastValid=0, lastOptical=0;
uint32_t redSamples[100], irSamples[100];
unsigned sampleCount=0;

// Acquisition only: the PAR module controls pneumatic measurement and safety.
// No automatic inflation at boot. GPIO27 starts one adult/manual cycle; GPIO26 aborts.
enum ParStep { PAR_IDLE, PAR_START, PAR_ADULT, PAR_MANUAL, PAR_MEASURING, PAR_REQUEST, PAR_REPLY };
ParStep parStep=PAR_IDLE;
uint32_t parCommandAt=0,parStarted=0,parButtonAt=0;
bool parReady=false,parButton=false;
void parCommand(unsigned code) {
  char body[5];snprintf(body,sizeof(body),"%02u;;",code);
  uint8_t sum=0;for(unsigned i=0;i<4;i++)sum+=body[i];
  char frame[9];snprintf(frame,sizeof(frame),"\x02%s%02X\x03",body,sum);
  Serial2.write((const uint8_t*)frame,8);parCommandAt=millis();
  Serial.printf("NIBP command %02u\n",code);
}
void readNibp() {
  uint32_t now=millis();
  static uint8_t buffer[80];static unsigned used=0;static uint32_t byteAt=0;
  while(Serial2.available()) {
    uint8_t b=Serial2.read();if(used&&now-byteAt>1000)used=0;byteAt=now;
    if(b==2){used=0;buffer[used++]=b;continue;}
    if(!used)continue;
    if(used>=sizeof(buffer)){used=0;continue;}buffer[used++]=b;
    if(b!=13)continue;
    if(used==6 && memcmp(buffer,"\x02" "999\x03\r",6)==0 && parStep==PAR_MEASURING)parStep=PAR_REQUEST;
    NibpStatus status;
    if(used>1 && nibpStatus(buffer,used-1,status)) {
      parReady=status.state==1 || status.state==5 || status.state==2;
      if(parStep==PAR_REPLY) {
        values.clear();lastValid=0;
        if(status.measurement){values["blood_pressure_sys"]=status.sys;values["blood_pressure_dia"]=status.dia;lastValid=now;}
        else Serial.printf("NIBP rejected status S%d M%02d\n",status.state,status.error);
        parStep=PAR_IDLE;
      }
    }
    used=0;
  }
  bool down=digitalRead(26)==LOW;
  if(down!=parButton){parButton=down;parButtonAt=now;}
  static bool armed=true;
  if(!down)armed=true;
  if(down&&armed&&now-parButtonAt>=40){armed=false;if(parStep==PAR_IDLE&&parReady){values.clear();lastValid=0;parStep=PAR_START;parStarted=now;}}
  if(digitalRead(26)==LOW || (parStep!=PAR_IDLE&&now-parStarted>120000)) {
    if(parStep!=PAR_IDLE){Serial2.write('X');parCommandAt=now;parStep=PAR_IDLE;values.clear();lastValid=0;Serial.println("NIBP cancelled");return;}
  }
  if(now-parCommandAt>1100) {
    if(parStep==PAR_START){parCommand(24);parStep=PAR_ADULT;}
    else if(parStep==PAR_ADULT){parCommand(3);parStep=PAR_MANUAL;}
    else if(parStep==PAR_MANUAL){parCommand(1);parStep=PAR_MEASURING;}
    else if(parStep==PAR_REQUEST){parCommand(18);parStep=PAR_REPLY;}
    else if(parStep==PAR_IDLE&&!parReady&&now>3000&&now-parCommandAt>5000)parCommand(18);
  }
  if(parStep==PAR_REPLY&&millis()-parCommandAt>3000){parStep=PAR_IDLE;values.clear();lastValid=0;}
  if(lastValid && now-lastValid>10000)values.clear();
}

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
pinMode(26,INPUT_PULLDOWN);
  if(kind("mpu6050")) sensorReady=regWrite(0x68,0x6b,0) && regWrite(0x68,0x1c,0) && regWrite(0x68,0x1b,0);
  else if(kind("max30102")) {sensorReady=optical.begin(Wire,I2C_SPEED_FAST); if(sensorReady) optical.setup(60,4,2,100,411,4096);}
  else if(kind("tmp117")) {uint8_t b[2]; sensorReady=regRead(0x48,0x0f,b,2) && b[0]==1 && b[1]==0x17;}
  else if(kind("scd41")) {command(0x62,0x3f86); delay(500); sensorReady=command(0x62,0x21b1);}
  else if(kind("sgp30")) sensorReady=command(0x58,0x2003);
  else if(kind("amg8833")) sensorReady=regWrite(0x69,0,0) && regWrite(0x69,1,0x3f);
  else if(kind("dht22")) { dht.begin(); sensorReady=true; }
  else if(kind("hx711")) {scale.begin(26,25); scale.power_down(); delayMicroseconds(80); scale.power_up(); sensorReady=true;}
  else if(kind("rfid")) {rfid.PCD_Init(); uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);sensorReady=v!=0 && v!=255;}
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
  } else if(kind("dht22")) {float t=dht.readTemperature(),h=dht.readHumidity();ok=finiteMeasurement(t)&&finiteMeasurement(h);if(ok){values["temperature_c"]=t;values["humidity_pct"]=h;}
  } else if(kind("hx711")) {ok=scale.is_ready();if(ok){long raw=scale.read();values["load_raw"]=raw;if(LOAD_SCALE!=0)values["load_kg"]=(raw-LOAD_OFFSET)/float(LOAD_SCALE);else values["load_kg"]=nullptr;}
  } else if(kind("rfid")) {
    if(sensorReady && rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {char uid[21]={0}; for(byte i=0;i<rfid.uid.size && i<10;i++)sprintf(uid+2*i,"%02X",rfid.uid.uidByte[i]);values["tag_uid"]=uid;ok=true;rfid.PICC_HaltA();}
    if(ok)lastValid=now;if(now-lastValid>10000)values["tag_uid"]=nullptr;return;
  } else if(kind("sos") || kind("door")) {
    static bool stable=false,lastRaw=false;static uint32_t changed=0,pressed=0;
    bool raw=kind("sos") ? !digitalRead(26) : digitalRead(26);
    if(raw!=lastRaw){changed=now;lastRaw=raw;}if(now-changed>=40)stable=raw;
    if(kind("sos")){if(stable)pressed=now;values["sos_pressed"]=stable || (pressed && now-pressed<3000);} else values["door_open"]=stable;
    ok=true;
  } else if(kind("pir") || kind("radar")) {values[kind("pir")?"motion":"presence"]=bool(digitalRead(26));ok=true;
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

} // endpoint9

struct Endpoint {const char *id;const char *kind;void (*begin)();void (*tick)();JsonDocument *values;uint32_t *lastValid;uint32_t seq;};
Endpoint endpoints[]={
{"R002-wearable-mpu6050","mpu6050",endpoint0::sensorBegin,endpoint0::sensorTick,&endpoint0::values,&endpoint0::lastValid,0},
{"R002-wearable-max30102","max30102",endpoint1::sensorBegin,endpoint1::sensorTick,&endpoint1::values,&endpoint1::lastValid,0},
{"R002-wearable-tmp117","tmp117",endpoint2::sensorBegin,endpoint2::sensorTick,&endpoint2::values,&endpoint2::lastValid,0},
{"R002-wearable-sos","sos",endpoint3::sensorBegin,endpoint3::sensorTick,&endpoint3::values,&endpoint3::lastValid,0},
{"R002-wearable-ecg","ecg",endpoint4::sensorBegin,endpoint4::sensorTick,&endpoint4::values,&endpoint4::lastValid,0},
{"R002-wearable-respiration","respiration",endpoint5::sensorBegin,endpoint5::sensorTick,&endpoint5::values,&endpoint5::lastValid,0},
{"R002-wearable-nibp","nibp",endpoint6::sensorBegin,endpoint6::sensorTick,&endpoint6::values,&endpoint6::lastValid,0},
{"R002-radar-radar","radar",endpoint7::sensorBegin,endpoint7::sensorTick,&endpoint7::values,&endpoint7::lastValid,0},
{"R002-porte-door","door",endpoint8::sensorBegin,endpoint8::sensorTick,&endpoint8::values,&endpoint8::lastValid,0},
{"R002-sdb_pir-pir","pir",endpoint9::sensorBegin,endpoint9::sensorTick,&endpoint9::values,&endpoint9::lastValid,0},
};
constexpr unsigned ENDPOINT_COUNT=sizeof(endpoints)/sizeof(endpoints[0]);
void prepareGroupSPI(){
}
