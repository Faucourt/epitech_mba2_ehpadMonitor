const {test} = require('node:test');
const assert = require('node:assert/strict');
const {Feed, TOPICS} = require('../dashboard/public/wokwi-feed.js');
const sample = {patient_id:'P001',device_id:'esp32-01',source:'esp32',seq:1,timestamp:'2026-10-02T14:00:00Z',heart_rate:72,accel_peak_g:1,imu_ok:true,alert_level:'info'};
test('normalizes only measured fields, then masks stale/offline/disconnected values', () => {
  const f=new Feed(); f.connected=true;
  assert.equal(f.ingest(TOPICS.vitals,JSON.stringify(sample),1000),true);
  assert.equal(f.resident(1100).vitals.heart_rate,72);
  for(const key of ['spo2','temperature','blood_pressure_sys','respiratory_rate']) assert.equal(f.resident(1100).vitals[key],null);
  assert.equal(f.resident(17000).vitals.heart_rate,null);
  f.ingest(TOPICS.status,'{"state":"offline"}',1200);
  assert.equal(f.resident(1200).vitals.heart_rate,null);
  assert.equal(f.points.length,1);
  f.ingest(TOPICS.status,'{"state":"online"}',1300); f.connected=false;
  assert.equal(f.resident(1300).vitals.heart_rate,null);
});
test('rejects wrong identities, unknown topics, malformed data and null heart rate', () => {
  const f=new Feed();
  for(const patch of [{patient_id:'R001'},{device_id:'other'},{heart_rate:null},{heart_rate:999},{timestamp:'bad'},{seq:-1},{alert_level:'<script>'}]) assert.equal(f.ingest(TOPICS.vitals,JSON.stringify({...sample,...patch})),false);
  assert.equal(f.ingest('other/topic',JSON.stringify(sample)),false);
  assert.equal(f.ingest(TOPICS.vitals,'not json'),false);
  assert.equal(f.last,null);
});
test('retained online alone is not a measurement; new boot may restart sequence', () => {
  const f=new Feed(); f.connected=true; f.ingest(TOPICS.status,'{"state":"online"}');
  assert.equal(f.resident().wokwi.fresh,false);
  f.ingest(TOPICS.vitals,JSON.stringify(sample),1000);
  f.ingest(TOPICS.vitals,JSON.stringify({...sample,seq:0,heart_rate:80}),2000);
  assert.equal(f.resident(2000).vitals.heart_rate,80);
});
test('keeps bounded SOS/fall/HR history without fabricating clinical scores', () => {
  const f=new Feed();
  for(let i=0;i<40;i++) assert.equal(f.ingest(TOPICS.alerts,JSON.stringify({patient_id:'P001',device_id:'esp32-01',type:'sos',level:'danger',value:1,timestamp:''}),i+1),true);
  assert.equal(f.events.length,30); assert.equal(f.resident().ml_risk,null);
  assert.equal(f.ingest(TOPICS.alerts,JSON.stringify({patient_id:'P001',device_id:'esp32-01',type:'constructor',level:'danger',value:1,timestamp:''})),false);
});
