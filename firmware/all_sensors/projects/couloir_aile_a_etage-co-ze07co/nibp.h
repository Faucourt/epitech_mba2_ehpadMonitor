#pragma once
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
