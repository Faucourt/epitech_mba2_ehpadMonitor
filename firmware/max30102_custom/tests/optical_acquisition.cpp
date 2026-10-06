// Compile against the actual readOptical() extracted by test_optical_acquisition.py.
#include <cassert>
#include <cstdint>
#include <cstring>
#include <deque>
#include <map>
#include <string>
#include <vector>
#include <iostream>
struct Value {
  int64_t number=0;bool null=true;
  Value &operator=(int64_t v){number=v;null=false;return *this;}
  Value &operator=(std::nullptr_t){null=true;return *this;}
};
struct Values:std::map<std::string,Value>{} values;
bool sensorReady=true;
uint32_t now=100,lastValid=0,lastOptical=0;
uint32_t redSamples[100],irSamples[100];unsigned sampleCount=0,algorithmCalls=0;
uint32_t millis(){return now;}
struct Read {uint8_t reg;std::vector<uint8_t> data;bool ok=true;};
std::deque<Read> reads;
std::vector<uint8_t> writes;
bool writesOk=true;
bool regRead(uint8_t addr,uint8_t reg,uint8_t *out,uint8_t n){
  assert(addr==0x57 && !reads.empty());auto r=reads.front();reads.pop_front();
  assert(r.reg==reg);if(!r.ok)return false;
  assert(r.data.size()==n);memcpy(out,r.data.data(),n);return true;
}
bool regWrite(uint8_t addr,uint8_t reg,uint8_t val){assert(addr==0x57 && val==0);writes.push_back(reg);return writesOk;}
void maxim_heart_rate_and_oxygen_saturation(uint32_t *ir,int n,uint32_t *red,int32_t *spo2,int8_t *vs,int32_t *hr,int8_t *vh){
  assert(n==100);for(int i=0;i<n;i++){assert(ir[i]==60000);assert(red[i]==55000);}
  algorithmCalls++;*hr=75;*spo2=98;*vh=*vs=1;
}
#include "read_optical_under_test.h"
void reset(){values.clear();reads.clear();writes.clear();sampleCount=algorithmCalls=0;lastValid=lastOptical=0;now=100;sensorReady=writesOk=true;}
void batch(unsigned count,bool finger=true){
  reads.push_back({4,{uint8_t(count),0,0}});
  for(unsigned i=0;i<count;i++)reads.push_back({7,finger?std::vector<uint8_t>{0,214,216,0,234,96}:std::vector<uint8_t>(6,0)});
  readOptical();assert(reads.empty());
}
int main(){
  reset();
  // 5 queued samples formerly overran the 4-slot SparkFun buffer. Preserve
  // every complete sample and compute only after a full contiguous window.
  for(int i=0;i<19;i++){batch(5);now+=200;assert(algorithmCalls==0);}
  batch(5);assert(algorithmCalls==1 && sampleCount==75);
  assert(values["heart_rate"].number==75 && lastValid==now);
  batch(1,false);assert(sampleCount==0 && values["heart_rate"].null && values["spo2"].null);
  std::cout<<"PASS contiguous backlog and finger removal\n";
  reset();sampleCount=99;values["heart_rate"]=75;lastValid=90;
  reads.push_back({4,{1,0,0}});reads.push_back({7,{0,214},false});readOptical();
  assert(!sensorReady && values.empty() && sampleCount==0 && lastValid==0 && algorithmCalls==0);
  std::cout<<"PASS short I2C transfer invalidates and requests reinitialization\n";
  reset();sampleCount=99;reads.push_back({4,{},false});readOptical();
  assert(!sensorReady && sampleCount==0 && values.empty());
  std::cout<<"PASS disconnected sensor\n";
  reset();sampleCount=99;values["heart_rate"]=75;reads.push_back({4,{0,31,0}});readOptical();
  assert(sampleCount==0 && sensorReady && values.empty());assert((writes==std::vector<uint8_t>{4,5,6}));
  batch(1);assert(sampleCount==1 && algorithmCalls==0);
  std::cout<<"PASS saturated FIFO flush and fresh acquisition\n";
  reset();lastOptical=100;lastValid=100;now=1300;sampleCount=99;
  reads.push_back({4,{4,0,0}});readOptical();assert(sampleCount==0 && writes.size()==3 && lastValid==0);
  std::cout<<"PASS polling gap discards previous window\n";
  reset();writesOk=false;reads.push_back({4,{0,1,0}});readOptical();assert(!sensorReady && writes.size()==3);
  std::cout<<"PASS failed FIFO recovery requests reinitialization\n";
}
