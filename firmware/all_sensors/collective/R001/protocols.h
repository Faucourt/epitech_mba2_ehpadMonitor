#pragma once
#include <stdint.h>
#include <stddef.h>
#include <math.h>
inline uint8_t sensirionCrc(const uint8_t *p, size_t n) {
  uint8_t crc=0xff;
  while(n--) { crc ^= *p++; for(int i=0;i<8;i++) crc = (crc & 0x80) ? (crc<<1)^0x31 : crc<<1; }
  return crc;
}
inline bool ze07Frame(const uint8_t *p, float &ppm) {
  if(p[0]!=0xff || p[1]!=0x04 || p[2]!=0x03) return false;
  uint8_t sum=0; for(int i=1;i<8;i++) sum+=p[i];
  if(uint8_t(0-sum)!=p[8] || p[3]>3) return false;
  ppm=((uint16_t(p[4])<<8)|p[5])/powf(10,p[3]);
  return ppm>=0 && ppm<=500;
}
inline float amgPixel(uint8_t lo, uint8_t hi) {
  uint16_t raw=(uint16_t(hi)<<8)|lo;
  return (raw&0x800 ? -float(raw&0x7ff) : float(raw&0x7ff)) * .25f;
}
// PAR NIBP2010 / NIBP2020 UP, standard protocol without SpO2, revision 2.12.
// Frame includes STX and ETX; the following CR is handled by the stream reader.
struct NibpStatus {int state, error, sys, dia, mean; bool measurement;};
inline int parHex(uint8_t c) {return c>='0'&&c<='9'?c-'0':c>='A'&&c<='F'?c-'A'+10:-1;}
inline int parDigits(const uint8_t *p,unsigned n) {
  int v=0;while(n--){if(*p<'0'||*p>'9')return -1;v=v*10+*p++-'0';}return v;
}
inline bool nibpStatus(const uint8_t *p,size_t n,NibpStatus &s) {
  if(n!=41 || p[0]!=2 || p[40]!=3)return false;
  uint8_t sum=0;for(unsigned i=1;i<38;i++)sum+=p[i];
  int h=parHex(p[38]),l=parHex(p[39]);if(h<0||l<0||sum!=(h*16+l))return false;
  const uint8_t *b=p+1;
  if(b[0]!='S'||b[3]!='A'||b[6]!='C'||b[10]!='M'||b[14]!='P'||b[25]!='R'||b[30]!='T')return false;
  for(unsigned i: {2u,5u,9u,13u,24u,29u,35u,36u})if(b[i]!=';')return false;
  s.state=parDigits(b+1,1);s.error=parDigits(b+11,2);
  if(s.state<0||s.error<0||parDigits(b+4,1)<0||parDigits(b+7,2)<0)return false;
  s.sys=parDigits(b+15,3);s.dia=parDigits(b+18,3);s.mean=parDigits(b+21,3);
  s.measurement=s.state==1 && b[4]=='0' && (s.error==0||s.error==3)
    && s.sys>=40&&s.sys<=300&&s.dia>=20&&s.dia<=200&&s.sys>s.dia&&s.mean>=s.dia&&s.mean<=s.sys;
  return true;
}
