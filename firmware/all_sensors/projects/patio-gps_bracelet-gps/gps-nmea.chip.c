#define MODEL 10
#define ADDRESS 0
#define ATTR_A "latitude"
#define DEFAULT_A 48.8566f
#define ATTR_B "longitude"
#define DEFAULT_B 2.3522f
#define ATTR_C "fix"
#define DEFAULT_C 1.0f
#define ATTR_D "unused3"
#define DEFAULT_D 0.0f
// Wokwi educational peripheral models. Implements the subset used by sensors.h.
// Not an electrical, RF, optical or clinical validation of the selected hardware.
#include "wokwi-api.h"
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>
#include <math.h>
#include <string.h>
typedef struct {
  uint8_t regs[256], fifo[32][6], reg, pos, wp, rp, bytepos;
  uint8_t response[192], tx[256]; unsigned response_len, readpos, writes;
  uint16_t command; bool running; double measurement_at;
  uint32_t a,b,c,d,connected,corrupt; pin_t out,lop,lom;uart_dev_t uart;
} model_t;
static uint8_t crc8(const uint8_t *p,unsigned n) {uint8_t crc=255;while(n--){crc^=*p++;for(int i=0;i<8;i++)crc=crc&128?(crc<<1)^0x31:crc<<1;}return crc;}
static void word(model_t *m,unsigned i,uint16_t v) {m->response[i]=v>>8;m->response[i+1]=v;m->response[i+2]=crc8(m->response+i,2) ^ (attr_read(m->corrupt)?1:0);}
static bool connect_i2c(void *u,uint32_t address,bool read) {
  model_t *m=u;if(!attr_read(m->connected))return false;
  if(!read){m->writes=0;m->pos=0;} else {
    m->readpos=0;
#if MODEL == 2
    uint16_t temp=(int16_t)roundf(attr_read_float(m->a)*128);m->response[0]=temp>>8;m->response[1]=temp;
    if(m->reg==15){m->response[0]=1;m->response[1]=0x17;}
#elif MODEL == 3
    bool ready=m->running && get_sim_nanos_d()-m->measurement_at>=5e9;
    if(m->command==0xe4b8) {word(m,0,ready?1:0);m->response_len=3;}
    else if(m->command==0xec05 && ready){word(m,0,attr_read_float(m->a));word(m,3,(attr_read_float(m->b)+45)*65535/175);word(m,6,attr_read_float(m->c)*65535/100);m->response_len=9;m->measurement_at=get_sim_nanos_d();}
    else m->response_len=0;
#elif MODEL == 4
    if(m->command==0x2008 && m->running){word(m,0,attr_read_float(m->b));word(m,3,attr_read_float(m->a));m->response_len=6;}else m->response_len=0;
#elif MODEL == 12
    if(m->command==0x260f && m->writes==8 && crc8(m->tx+2,2)==m->tx[4] && crc8(m->tx+5,2)==m->tx[7]) {word(m,0,attr_read_float(m->a));m->response_len=3;}else m->response_len=0;
#elif MODEL == 5
    for(int i=0;i<64;i++){float v=attr_read_float(i==(int)attr_read_float(m->c)?m->b:m->a);uint16_t raw=roundf(fabsf(v)*4);if(v<0)raw|=0x800;m->regs[128+2*i]=raw;m->regs[129+2*i]=raw>>8;}
#elif MODEL == 6
    uint8_t mac[6]={0x02,0,0,0,0,1};memcpy(m->regs,mac,6);m->regs[6]=(int8_t)attr_read_float(m->a);
#endif
  }return true;
}
static bool write_i2c(void *u,uint8_t b) {
  model_t *m=u;
#if MODEL == 3 || MODEL == 4 || MODEL == 12
  if(m->writes<sizeof(m->tx))m->tx[m->writes]=b;
  if(m->writes==0)m->command=(uint16_t)b<<8;else if(m->writes==1){m->command|=b;
    if(m->command==0x21b1 || m->command==0x2003){m->running=true;m->measurement_at=get_sim_nanos_d();}
    if(m->command==0x3f86)m->running=false;
  }
#else
  if(m->writes==0)m->reg=b;else {
    m->regs[m->reg]=b;
#if MODEL == 1
    if(m->reg==4)m->wp=b&31;if(m->reg==6){m->rp=b&31;m->bytepos=0;}
    if(m->reg==9 && (b&0x40)){memset(m->regs,0,256);m->wp=m->rp=m->bytepos=0;}
#endif
    m->reg++;
  }
#endif
  m->writes++;return true;
}
static uint8_t read_i2c(void *u) {
  model_t *m=u;
#if MODEL == 1
  if(m->reg==7){uint8_t v=m->fifo[m->rp][m->bytepos++];if(m->bytepos==6){m->bytepos=0;m->rp=(m->rp+1)&31;}return v;}
  uint8_t r=m->reg++;if(r==4)return m->wp;if(r==6)return m->rp;if(r==255)return 0x15;if(r==254)return 3;return m->regs[r];
#elif MODEL == 2
  return m->response[(m->readpos++)&1];
#elif MODEL == 3 || MODEL == 4 || MODEL == 12
  return m->readpos<m->response_len?m->response[m->readpos++]:0xff;
#else
  return m->regs[m->reg++];
#endif
}
static void tick(void *u) {
  model_t *m=u;if(!attr_read(m->connected))return;
  double seconds=get_sim_nanos_d()/1e9;
#if MODEL == 1
  if((m->regs[9]&7)!=3 || (m->regs[9]&0x80))return;
  // 100 Hz ADC / averaging 4 = 25 FIFO samples/s, as configured by firmware.
  if(get_sim_nanos_d()-m->measurement_at<4e7)return;m->measurement_at=get_sim_nanos_d();
  float pulse=sinf(seconds*6.283185307*attr_read_float(m->a)/60);
  uint32_t ir=attr_read_float(m->d)>0 ? 60000+3500*pulse : 0;
  uint32_t red=attr_read_float(m->d)>0 ? 55000+attr_read_float(m->b)*3500*pulse : 0;
  uint8_t *p=m->fifo[m->wp];p[0]=red>>16;p[1]=red>>8;p[2]=red;p[3]=ir>>16;p[4]=ir>>8;p[5]=ir;
  uint8_t next=(m->wp+1)&31;if(next==m->rp){m->regs[5]=(m->regs[5]+1)&31;if(m->regs[8]&0x10)m->rp=(m->rp+1)&31;else return;}m->wp=next;
#elif MODEL == 7
  pin_write(m->out,attr_read_float(m->a)>=.5);
#elif MODEL == 8
  float voltage=attr_read_float(m->b)+attr_read_float(m->a)*sinf(seconds*6.283185307*attr_read_float(m->c));
  pin_dac_write(m->out,fmaxf(0,fminf(3.3,voltage)));pin_write(m->lop,attr_read_float(m->d)>=.5);pin_write(m->lom,attr_read_float(m->d)>=.5);
#elif MODEL == 9
  uint16_t ppm=roundf(attr_read_float(m->a)*10);uint8_t frame[9]={255,4,3,1,ppm>>8,ppm&255,0x13,0x88,0};uint8_t sum=0;for(int i=1;i<8;i++)sum+=frame[i];frame[8]=(uint8_t)(0-sum)^(attr_read(m->corrupt)?1:0);memcpy(m->tx,frame,9);uart_write(m->uart,m->tx,9);
#elif MODEL == 10
  double lat=attr_read_float(m->a),lon=attr_read_float(m->b);double la=fabs(lat),lo=fabs(lon);
  char body[180];snprintf(body,sizeof(body),"GPRMC,120000.00,%c,%09.4f,%c,%010.4f,%c,0.0,0.0,021026,,,A",attr_read_float(m->c)>.5?'A':'V',floor(la)*100+(la-floor(la))*60,lat<0?'S':'N',floor(lo)*100+(lo-floor(lo))*60,lon<0?'W':'E');
  uint8_t crc=0;for(unsigned i=0;body[i];i++)crc^=body[i];if(attr_read(m->corrupt))crc^=1;
  int n=snprintf((char*)m->tx,sizeof(m->tx),"$%s*%02X\r\n",body,crc);uart_write(m->uart,m->tx,n);
#elif MODEL == 11
  uint16_t sys=attr_read_float(m->a),dia=attr_read_float(m->b);uint8_t frame[8]={0xa5,0x5a,1,sys>>8,sys&255,dia>>8,dia&255,0};frame[7]=crc8(frame,7)^(attr_read(m->corrupt)?1:0);memcpy(m->tx,frame,8);uart_write(m->uart,m->tx,8);
#elif MODEL == 13
  pin_dac_write(m->out,attr_read_float(m->a)/50.f);
#endif
}
void chip_init(void) {
  model_t *m=calloc(1,sizeof(model_t));m->connected=attr_init("connected",1);m->corrupt=attr_init("corrupt",0);
  m->a=attr_init_float(ATTR_A,DEFAULT_A);m->b=attr_init_float(ATTR_B,DEFAULT_B);m->c=attr_init_float(ATTR_C,DEFAULT_C);m->d=attr_init_float(ATTR_D,DEFAULT_D);
#if MODEL <= 6 || MODEL == 12
  i2c_config_t cfg={.address=ADDRESS,.scl=pin_init("SCL",INPUT_PULLUP),.sda=pin_init("SDA",INPUT_PULLUP),.connect=connect_i2c,.read=read_i2c,.write=write_i2c,.user_data=m};i2c_init(&cfg);
#elif MODEL == 7
  m->out=pin_init("OUT",OUTPUT_LOW);
#elif MODEL == 8
  m->out=pin_init("OUT",ANALOG);m->lop=pin_init("LOP",OUTPUT_LOW);m->lom=pin_init("LOM",OUTPUT_LOW);
#elif MODEL == 13
  m->out=pin_init("OUT",ANALOG);
#else
  uart_config_t uart={.rx=pin_init("RX",INPUT),.tx=pin_init("TX",OUTPUT_HIGH),.baud_rate=9600,.user_data=m};m->uart=uart_init(&uart);
#endif
  timer_config_t timer={.callback=tick,.user_data=m};timer_t t=timer_init(&timer);timer_start(t,MODEL>=9?1000000:10000,true);
}
