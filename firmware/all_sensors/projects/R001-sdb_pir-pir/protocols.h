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
inline bool nibpFrame(const uint8_t *p, float &sys, float &dia) {
  // Project gateway protocol, not a manufacturer cuff protocol.
  if(p[0]!=0xa5 || p[1]!=0x5a || p[2]!=1 || sensirionCrc(p,7)!=p[7]) return false;
  sys=(uint16_t(p[3])<<8)|p[4]; dia=(uint16_t(p[5])<<8)|p[6];
  return sys>=40 && sys<=300 && dia>=20 && dia<=200 && sys>dia;
}
