'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const base=path.resolve(__dirname,'../../firmware/all_sensors/chips');
async function model(name) {
 const module=await WebAssembly.compile(fs.readFileSync(path.join(base,name+'.wasm')));
 const state={attrs:new Map(),pins:new Map(),timers:[],i2cs:[],uart:[],now:0,tx:[],outputs:new Map()};let instance;
 const mem=()=>new DataView(instance.exports.memory.buffer);
 const bytes=()=>new Uint8Array(instance.exports.memory.buffer);
 const string=p=>{let end=p;while(bytes()[end])end++;return Buffer.from(bytes().slice(p,end)).toString();};
 const env={
  attrInit:(p,v)=>{const id=state.attrs.size+1;state.attrs.set(id,{name:string(p),value:v});return id;},
  attrInitFloat:(p,v)=>{const id=state.attrs.size+1;state.attrs.set(id,{name:string(p),value:v});return id;},
  attrRead:id=>state.attrs.get(id).value,attrReadFloat:id=>state.attrs.get(id).value,
  pinInit:(p,mode)=>{const id=state.pins.size+1;state.pins.set(id,{name:string(p),mode});return id;},
  pinWrite:(pin,v)=>state.outputs.set(state.pins.get(pin).name,v),pinDACWrite:(pin,v)=>{state.outputs.set(state.pins.get(pin).name,v);return v;},
  getSimNanos:()=>state.now,
  i2cInit:p=>{state.i2cs.push({ud:mem().getUint32(p,true),addr:mem().getUint32(p+4,true),connect:mem().getUint32(p+16,true),read:mem().getUint32(p+20,true),write:mem().getUint32(p+24,true)});return state.i2cs.length;},
  timerInit:p=>{state.timers.push({ud:mem().getUint32(p,true),fn:mem().getUint32(p+4,true)});return state.timers.length;},
  timerStart:(id,us,repeat)=>Object.assign(state.timers[id-1],{us,repeat}),
  uartInit:p=>{state.uart.push({baud:mem().getUint32(p+12,true)});return state.uart.length;},
  uartWrite:(id,p,n)=>{state.tx.push(Buffer.from(bytes().slice(p,p+n)));return 1;},
 };
 const wasi={fd_close:()=>0,fd_seek:()=>0,fd_write:()=>0,proc_exit:code=>{throw Error('WASM exit '+code);}};
 for(const i of WebAssembly.Module.imports(module))assert.ok((i.module==='env'?env:wasi)[i.name],`Unhandled ${i.module}.${i.name}`);
 instance=await WebAssembly.instantiate(module,{env,wasi_snapshot_preview1:wasi});instance.exports.chipInit();
 const call=(fn,...args)=>instance.exports.__indirect_function_table.get(fn)(...args);
 state.set=(name,value)=>{for(const attr of state.attrs.values())if(attr.name===name)attr.value=value;};
 state.write=(data,index=0)=>{const b=state.i2cs[index];if(!call(b.connect,b.ud,b.addr,0))return false;for(const v of data)assert.equal(call(b.write,b.ud,v),1);return true;};
 state.read=(n,index=0)=>{const b=state.i2cs[index];if(!call(b.connect,b.ud,b.addr,1))return null;return Array.from({length:n},()=>call(b.read,b.ud));};
 state.tick=(ms=1000)=>{state.now+=ms*1e6;for(const t of state.timers)call(t.fn,t.ud);};
 state.newInstance=()=>instance.exports.chipInit();return state;
}
const crc=p=>{let c=255;for(const b of p){c^=b;for(let i=0;i<8;i++)c=((c&128)?(c<<1)^0x31:c<<1)&255;}return c;};
test('TMP117 signed register, identity, disconnection and instance isolation',async()=>{
 const m=await model('tmp117');m.write([15]);assert.deepEqual(m.read(2),[1,23]);m.set('temperature',-10.5);m.write([0]);assert.deepEqual(m.read(2),[250,192]);
 m.newInstance();m.write([0],1);assert.deepEqual(m.read(2,1),[18,64]);m.set('connected',0);assert.equal(m.write([0]),false);
});
test('SCD41 start/readiness/5sec measurement, CRC and stop',async()=>{
 const m=await model('scd41');m.write([0xe4,0xb8]);assert.deepEqual(m.read(3),[0,0,129]);m.write([0x21,0xb1]);m.tick(5000);m.write([0xe4,0xb8]);assert.deepEqual(m.read(3),[0,1,176]);m.write([0xec,5]);const b=m.read(9);assert.equal((b[0]<<8)|b[1],600);for(let i=0;i<9;i+=3)assert.equal(crc(b.slice(i,i+2)),b[i+2]);
 m.set('corrupt',1);m.write([0xe4,0xb8]);const c=m.read(3);assert.notEqual(crc(c.slice(0,2)),c[2]);m.write([0x3f,0x86]);m.tick(6000);m.set('corrupt',0);m.write([0xe4,0xb8]);assert.deepEqual(m.read(3),[0,0,129]);
});
test('MAX30102 identity, FIFO progression, sample data, reset and finger absent',async()=>{
 const m=await model('max30102');m.write([255]);assert.deepEqual(m.read(1),[21]);m.write([9,3]);m.tick(40);m.write([4]);assert.deepEqual(m.read(1),[1]);m.write([7]);const b=m.read(6);assert.ok((b[0]<<16|b[1]<<8|b[2])>5000);m.write([6]);assert.deepEqual(m.read(1),[1]);m.write([9,0x40]);m.write([4]);assert.deepEqual(m.read(1),[0]);m.set('finger',0);m.write([9,3]);m.tick(40);m.write([7]);assert.deepEqual(m.read(6),[0,0,0,0,0,0]);
});
test('AMG8833 supplies64 pixels with signed magnitude temperatures',async()=>{
 const m=await model('amg8833');m.set('ambient',-4);m.write([128]);const data=m.read(128);assert.deepEqual(data.slice(0,2),[16,8]);assert.deepEqual(data.slice(54,56),[136,0]);
});
test('SGP40 requires compensation CRC and supplies raw VOC CRC',async()=>{
 const m=await model('sgp40');let cmd=[0x26,0x0f,0x80,0,0xa2,0x66,0x66,0x93];m.write(cmd);let b=m.read(3);assert.equal((b[0]<<8)|b[1],25000);assert.equal(crc(b.slice(0,2)),b[2]);cmd[4]=0;m.write(cmd);assert.deepEqual(m.read(3),[255,255,255]);
});
test('SGP30 initialization and independent VOC/eCO2 words',async()=>{
 const m=await model('sgp30');m.write([0x20,3]);m.write([0x20,8]);assert.deepEqual(m.read(6).filter((_,i)=>i%3!==2),[1,194,0,30]);
});
test('ZE07CO manufacturer frame, checksum and corruption',async()=>{
 const m=await model('ze07co');m.set('co',3.7);m.tick();let b=m.tx[0];assert.deepEqual([...b],[255,4,3,1,0,37,19,136,56]);m.set('corrupt',1);m.tick();assert.notEqual(m.tx[1][8],56);
});
test('NMEA fix, coordinates and checksum',async()=>{
 const m=await model('gps-nmea');m.tick();const line=m.tx[0].toString();assert.match(line,/GPRMC,120000.00,A,4851/);const [body,checksum]=line.slice(1).trim().split('*');let c=0;for(const b of Buffer.from(body))c^=b;assert.equal(c,parseInt(checksum,16));m.set('fix',0);m.tick();assert.match(m.tx[1].toString(),/120000.00,V,/);
});
test('project NIBP gateway frame (not a manufacturer cuff)',async()=>{
 const m=await model('nibp-fixture');m.tick();const b=m.tx[0];assert.deepEqual([...b.slice(0,7)],[165,90,1,0,120,0,75]);assert.equal(crc([...b.slice(0,7)]),b[7]);
});
test('analog, radar GPIO, sound-level transfer and BLE fixture',async()=>{
 const a=await model('analog-signal');a.set('amplitude',0);a.set('leadsOff',1);a.tick();assert.ok(Math.abs(a.outputs.get('OUT')-1.65)<.0001);assert.equal(a.outputs.get('LOP'),1);
 const r=await model('digital-presence');r.set('presence',1);r.tick();assert.equal(r.outputs.get('OUT'),1);
 const s=await model('sound-level');s.set('decibels',60);s.tick();assert.ok(Math.abs(s.outputs.get('OUT')-1.2)<.0001);
 const b=await model('ble-fixture');b.write([0]);assert.deepEqual(b.read(7),[2,0,0,0,0,1,201]);
});
