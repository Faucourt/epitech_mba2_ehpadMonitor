const {test}=require('node:test');
const assert=require('node:assert/strict');
const {project}=require('../../dashboard/public/resident-acquisition.js');
const inventory=require('../../dashboard/public/hardware-inventory.json');
const device=inventory.devices.find(d=>d.entity_id==='R001' && 'heart_rate' in d.fields);
const snapshot=(override={})=>({source:'wokwi',received_at:1000,entities:[{id:'R001',devices:[{
  ...device,status:'live',received_at:999,values:{heart_rate:78,spo2:97},...override
}]}]});
test('all 25 original residents, no extra P001 and no default measurements',()=>{
  const models=project(inventory,null);
  assert.equal(models.length,25);
  assert.ok(!models.some(r=>r.id==='P001'));
  assert.ok(models.every(r=>Object.keys(r.vitals).length===0 && r.acquisition.communicating===0 && r.ml_risk===null));
});
test('environment views include all 20 zones without copying resident measurements',()=>{
  const models=project(inventory,snapshot(),0,'zone');
  assert.equal(models.length,20);
  assert.ok(models.every(e=>e.type==='zone' && Object.keys(e.vitals).length===0));
});
test('R001 measurements never populate R002 or another resident',()=>{
  const models=project(inventory,snapshot());
  assert.equal(models.find(r=>r.id==='R001').vitals.heart_rate,78);
  assert.ok(models.filter(r=>r.id!=='R001').every(r=>r.vitals.heart_rate===undefined));
});
test('expiry in the browser clears readings even without another API response',()=>{
  const resident=project(inventory,snapshot(),16).find(r=>r.id==='R001');
  assert.deepEqual(resident.vitals,{});
  assert.equal(resident.acquisition.communicating,0);
});
test('failed requests, offline and stale devices cannot retain readings',()=>{
  for (const data of [null,snapshot({status:'offline'}),snapshot({status:'stale'})]) {
    assert.deepEqual(project(inventory,data)[0].vitals,{});
  }
});
test('an unavailable sensor can communicate without a measurement',()=>{
  const resident=project(inventory,snapshot({status:'unavailable'}))[0];
  assert.equal(resident.acquisition.communicating,1);
  assert.equal(resident.acquisition.live,0);
  assert.deepEqual(resident.vitals,{});
});
test('reject a different source, resident assignment, or sensor kind',()=>{
  for (const data of [{...snapshot(),source:'hardware'},snapshot({entity_id:'R002'}),snapshot({kind:'other'})]) {
    assert.deepEqual(project(inventory,data)[0].vitals,{});
  }
});
test('fresh false and zero values are preserved; undeclared fields are ignored',()=>{
  const button=inventory.devices.find(d=>d.entity_id==='R001' && 'sos_pressed' in d.fields);
  const data={source:'wokwi',received_at:1000,entities:[{id:'R001',devices:[
    {...button,status:'live',received_at:1000,values:{sos_pressed:false,ml_risk:0.8}},
    {...device,status:'live',received_at:1000,values:{heart_rate:0}}
  ]}]};
  const resident=project(inventory,data)[0];
  assert.equal(resident.vitals.sos_pressed,false);
  assert.equal(resident.vitals.heart_rate,0);
  assert.equal(resident.vitals.ml_risk,undefined);
});
