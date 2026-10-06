'use strict';
const test=require('node:test');const assert=require('node:assert/strict');const fs=require('node:fs');const path=require('node:path');
const base=path.resolve(__dirname,'../simulation');
async function model(name) {
 const module=await WebAssembly.compile(fs.readFileSync(path.join(base,name+'.chip.wasm')));
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
  uartInit:p=>{state.uart.push({ud:mem().getUint32(p,true),baud:mem().getUint32(p+12,true),rx:mem().getUint32(p+16,true)});return state.uart.length;},
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
 state.receive=data=>{for(const b of data)call(state.uart[0].rx,state.uart[0].ud,b);};
 state.newInstance=()=>instance.exports.chipInit();return state;
}
test('MAX30102 identity, FIFO progression, sample data, reset and finger absent',async()=>{
 const m=await model('max30102');m.write([255]);assert.deepEqual(m.read(1),[21]);m.write([9,3]);m.tick(40);m.write([4]);assert.deepEqual(m.read(1),[1]);m.write([7]);const b=m.read(6);assert.ok((b[0]<<16|b[1]<<8|b[2])>5000);m.write([6]);assert.deepEqual(m.read(1),[1]);m.write([9,0x40]);m.write([4]);assert.deepEqual(m.read(1),[0]);m.set('finger',0);m.write([9,3]);m.tick(40);m.write([7]);assert.deepEqual(m.read(6),[0,0,0,0,0,0]);
});

test('MAX30102 has 32 FIFO slots, saturates overflow and preserves unread data',async()=>{
 const m=await model('max30102');m.write([9,3]);
 const reg=r=>{m.write([r]);return m.read(1)[0];};
 for(let i=0;i<32;i++)m.tick(40);
 assert.equal(reg(4),0);assert.equal(reg(5),0);assert.equal(reg(6),0);
 assert.equal(reg(0)&0x80,0x80);
 m.set('finger',0);for(let i=0;i<70;i++)m.tick(40);
 assert.equal(reg(5),31);assert.equal(reg(4),0);
 m.write([7]);const b=m.read(6);assert.ok((b[0]<<16|b[1]<<8|b[2])>5000);
 assert.equal(reg(5),0);assert.equal(reg(6),1);
 m.write([7]);assert.equal(m.read(31*6).length,186);
 assert.equal(reg(6),0);m.write([7]);assert.deepEqual(m.read(6),[0,0,0,0,0,0]);
 assert.equal(reg(6),0);
});

test('MAX30102 partial FIFO read stays coherent while producer rolls over',async()=>{
 const m=await model('max30102');m.write([8,0x10]);m.write([9,3]);m.tick(40);
 m.write([7]);const expected=m.read(6);
 // Rewind the read pointer as documented for a failed transaction.
 m.write([6,0]);m.write([7]);const first=m.read(1);
 m.write([6]);assert.equal(m.read(1)[0],1); // advance on first byte
 m.set('finger',0);for(let i=0;i<40;i++)m.tick(40);
 m.write([7]);assert.deepEqual([...first,...m.read(5)],expected);
 m.write([7]);assert.deepEqual(m.read(6),[0,0,0,0,0,0]);
 m.write([9,0x40]);m.write([4]);assert.deepEqual(m.read(3),[0,0,0]);
});
