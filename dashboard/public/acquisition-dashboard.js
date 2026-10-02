/* Existing resident grid, fed by the same acquisition API as hardware.html. */
(() => {
  'use strict';
  if (!ACQUISITION_MODE) return;
  const $ = id => document.getElementById(id);
  const node = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const labels = {heart_rate:'FC',spo2:'SpO₂',blood_pressure_sys:'Pression systolique',blood_pressure_dia:'Pression diastolique',
    contact_temperature_c:'Température de contact',respiratory_rate:'Respiration',sos_pressed:'SOS',impact:'Impact',
    accel_g:'Accélération',gyro_dps:'Rotation',motion:'Mouvement',presence:'Présence',door_open:'Porte ouverte',
    ecg_mv:'Signal ECG',leads_off:'Électrodes déconnectées',load_kg:'Charge',load_raw:'Charge brute',
    respiration_mv:'Signal respiratoire',ir_raw:'Infrarouge brut',red_raw:'Rouge brut'};
  let inventory = null, snapshot = null, receivedAt = 0, requestStarted = 0, stopped = false, pollTimer, ageTimer, controller;
  let activeTab='grid';
  const signals=[],previousSignals=new Set();
  function valueText(value, unit = '') {
    if (value === undefined || value === null) return 'non mesuré';
    if (typeof value === 'boolean') return value ? 'Oui' : 'Non';
    const formatted = typeof value === 'number' ? value.toLocaleString('fr-FR', {maximumFractionDigits: 2}) : String(value);
    return formatted + (unit && unit !== 'bool' ? ` ${unit}` : '');
  }
  function state(r) { return r.acquisition.communicating ? `${r.acquisition.communicating} / ${r.acquisition.devices.length} capteurs qui publient` : 'Déconnecté · aucune mesure récente'; }
  function renderCard(card, r) {
    card.className = 'resident-card';
    card.style.borderColor = r.acquisition.alerts.length ? '#f59e0b' : r.acquisition.communicating ? '#3b82f6' : '#64748b';
    card.replaceChildren(node('div','card-name',r.name),node('div','card-room',`Chambre ${r.room} · ${r.id}`),
      node('p','acquisition-state',state(r)));
    const vitals = node('div','card-vitals');
    const entries = [['heart_rate','bpm'],['spo2','%'],['blood_pressure_sys','mmHg'],['blood_pressure_dia','mmHg'],
      ['contact_temperature_c','°C'],['respiratory_rate','resp./min']];
    for (const [field, unit] of entries) {
      const item=node('div','vital');
      item.append(node('span','vital-val',valueText(r.vitals[field],unit)),node('span','vital-label',labels[field]));
      vitals.append(item);
    }
    card.append(vitals,node('p','card-room',`Wokwi · ${r.acquisition.live} capteurs avec une mesure récente`));
    for (const alert of r.acquisition.alerts) card.append(node('p','',alert));
    card.append(node('p','card-room','Ouvrir pour voir les capteurs de ce résident'));
  }
  function renderDetail(r) {
    $('detail-panel').classList.add('open');
    $('dp-name').textContent = r.name;
    $('dp-info').textContent = `Chambre ${r.room} · ${r.id} · Simulation Wokwi`;
    const body=$('dp-content');
    body.replaceChildren(node('p','',state(r)),node('p','card-room','Seules les mesures récentes des capteurs affectés à ce résident sont affichées. Le risque clinique et la température corporelle ne sont pas déduits de ces signaux.'));
    for (const device of r.acquisition.devices) {
      const model=inventory.catalog[device.kind];
      body.append(node('h3','section-sub',model?.model || device.kind),node('p','card-room',device.id),
        node('p','',device.status==='live'?'Mesures reçues':device.communicating?'Connecté · en attente de mesure':'Déconnecté'));
      for (const [field,unit] of Object.entries(device.fields)) {
        const row=node('div','vital-row');
        row.append(node('span','',labels[field] || field),node('span','',valueText(device.values[field],unit)));
        body.append(row);
      }
      if (model?.limit) body.append(node('p','card-room',model.limit));
    }
  }
  function updateStats() {
    const all=Object.values(residents);
    $('stat-total').textContent=all.length;
    $('stat-alerts').textContent=all.filter(r=>r.acquisition.alerts.length).length;
    $('stat-ml').textContent='—';
    $('stat-ok').textContent=all.filter(r=>r.acquisition.communicating>0).length;
  }
  function allResidents(){return Object.values(residents);}
  function zones(){return inventory?ResidentAcquisition.project(inventory,snapshot,snapshot?(performance.now()-requestStarted)/1000:0,'zone'):[];}
  function panel(parent,id){let el=$(id);if(!el){el=node('section','report-panel');el.id=id;$(parent).append(el);}return el;}
  function renderEnvironment(parent){
    const box=panel(parent,`acquisition-environment-${parent}`);
    const opened=new Set([...box.querySelectorAll('details[open]')].map(el=>el.dataset.id));
    box.replaceChildren(node('h3','','Capteurs des 20 zones environnementales'));
    for(const zone of zones()){
      const details=node('details');
      details.dataset.id=zone.id;details.open=opened.has(zone.id);
      details.append(node('summary','',`${zone.name} · ${zone.acquisition.communicating}/${zone.acquisition.devices.length} capteurs qui publient`));
      for(const d of zone.acquisition.devices){
        const values=Object.entries(d.values).filter(([,v])=>!Array.isArray(v)).map(([key,value])=>`${labels[key]||key} : ${valueText(value,d.fields[key])}`).join(' · ');
        details.append(node('p','card-room',`${inventory.catalog[d.kind]?.model||d.kind} · ${d.id} · ${values||'non mesuré'}`));
      }
      box.append(details);
    }
  }
  function renderNight(){
    const all=allResidents();
    $('night-total').textContent=all.length;
    $('night-bed').textContent='—';$('night-up').textContent='—';
    $('night-door').textContent=all.filter(r=>r.vitals.door_open===true).length;
    $('night-risk').textContent=all.filter(r=>r.acquisition.alerts.length).length;
    $('night-period-label').textContent='Mesures Wokwi : ouverture, mouvement, présence et charge. Le sommeil et le lever ne sont pas déduits des signaux bruts.';
    const filtered=all.filter(r=>currentNightFilter==='all'||currentNightFilter==='door'&&r.vitals.door_open===true||currentNightFilter==='risk'&&r.acquisition.alerts.length);
    $('night-grid').replaceChildren(...filtered.map(r=>{
      const card=node('div','night-card');card.onclick=()=>openDetail(r.id);
      card.append(node('h3','night-name',r.name),node('p','night-room',`Chambre ${r.room} · ${state(r)}`));
      for(const d of r.acquisition.devices.filter(d=>d.role!=='wearable')){
        const values=Object.entries(d.values).map(([key,value])=>`${labels[key]||key} : ${valueText(value,d.fields[key])}`).join(' · ');
        card.append(node('p','',`${inventory.catalog[d.kind]?.model||d.kind} : ${values||'non mesuré'}`));
      }
      return card;
    }));
    if(!filtered.length)$('night-grid').append(node('p','no-alerts',['bed','up'].includes(currentNightFilter)?'État lit / lever non déterminé par les mesures disponibles.':'Aucun signal reçu correspondant à ce filtre.'));
  }
  function renderReports(){
    updateReportResidentSelect();
    const box=$('global-report');box.replaceChildren(node('p','','Transmission des mesures Wokwi actuellement disponibles. Les champs non mesurés ne sont pas complétés automatiquement.'));
    for(const r of allResidents())box.append(node('p','',`${r.name} · chambre ${r.room} · ${state(r)} · FC ${valueText(r.vitals.heart_rate,'bpm')} · SpO₂ ${valueText(r.vitals.spo2,'%')}`));
    const chosen=residents[$('report-resident-select').value]||allResidents()[0];
    $('resident-dpi').replaceChildren(node('h3','',chosen?.name||'Résident'),node('p','','Données d’acquisition de cette session ; aucune évaluation clinique automatique.'));
    if(chosen)for(const d of chosen.acquisition.devices)$('resident-dpi').append(node('p','',`${inventory.catalog[d.kind]?.model||d.kind} : ${Object.entries(d.values).map(([key,value])=>`${labels[key]||key} ${valueText(value,d.fields[key])}`).join(' · ')||'non mesuré'}`));
  }
  function renderHistory(){
    const box=$('history-list');
    box.replaceChildren(node('h3','','Signaux SOS / impact reçus pendant cette session'));
    for(const event of signals)box.append(node('p','',`${new Date(event.at).toLocaleTimeString('fr-FR')} · ${event.name} · ${event.label}`));
    if(!signals.length)box.append(node('p','','Aucun signal SOS / impact reçu dans cette session.'));
    $('simulated-history').replaceChildren(node('p','','Historique Wokwi limité aux messages effectivement reçus. Aucun historique de 12 mois n’est généré pour les capteurs.'));
  }
  function renderValidation(){
    const box=$('readiness-panel');
    if(!box)return;
    const all=[...allResidents(),...zones()],count=all.reduce((n,e)=>n+e.acquisition.communicating,0);
    box.replaceChildren(node('h3','','Réception effective des capteurs Wokwi'),node('p','',`${count} / ${inventory?.devices.length||437} capteurs qui publient actuellement.`),node('p','','La présence des schémas et la compilation ne prouvent pas une exécution simultanée. Les 3 premiers résidents et les 20 zones forment le groupe prioritaire de 214 points.'));
    for(const e of all)box.append(node('p','',`${e.name} : ${e.acquisition.communicating} / ${e.acquisition.devices.length} qui publient ; ${e.acquisition.live} avec mesure récente`));
  }
  function modelDetail(data,detail){
    if(data.type==='resident'){openDetail(data.resident_id);detail.textContent=`${residents[data.resident_id]?.name} · chambre attribuée, position non mesurée.`;return;}
    detail.replaceChildren(node('strong','',data.label||data.name||data.location||'Capteur'));
    detail.append(node('p','','Emplacement du capteur dans la maquette. Les valeurs reçues pour chaque zone sont listées sous la vue 3D.'));
    if(data.room){const r=allResidents().find(r=>String(r.room)===String(data.room));if(r)openDetail(r.id);}
  }
  function showTab(name){
    activeTab=name;
    if(name==='plan'){
      renderFloorPlan(currentFloor);
      const note=panel('tab-plan','acquisition-plan-note');note.textContent='Plan des chambres attribuées et des capteurs. La position des résidents reste inconnue tant qu’aucune localisation n’est mesurée.';
      renderEnvironment('tab-plan');
    }
    if(name==='model3d'){
      initEHPAD3D();
      const note=panel('tab-model3d','acquisition-model-note');note.textContent='Les avatars indiquent les chambres attribuées, pas une localisation mesurée. Bleu : capteurs qui publient ; gris : déconnectés.';
      renderEnvironment('tab-model3d');
    }
    if(name==='night')renderNight();
    if(name==='reports')renderReports();
    if(name==='staff')loadStaff();
    if(name==='validation')renderValidation();
    if(name==='history'){updateSimulatedHistorySelect();renderHistory();}
  }
  window.AcquisitionDashboard={renderCard,renderDetail,updateStats,showTab,renderNight,renderReports,renderHistory,renderValidation,modelDetail};
  function render() {
    if (!inventory) return;
    const elapsed=snapshot?(performance.now()-requestStarted)/1000:0;
    residents=Object.fromEntries(ResidentAcquisition.project(inventory,snapshot,elapsed).map(r=>[r.id,r]));
    liveResidents=cloneState(residents);
    renderGrid();updateStats();
    const current=new Set();
    for(const r of allResidents())for(const label of r.acquisition.alerts){
      const key=r.id+':'+label;current.add(key);
      if(!previousSignals.has(key))signals.unshift({at:receivedAt,name:r.name,label});
    }
    previousSignals.clear();current.forEach(key=>previousSignals.add(key));signals.splice(200);
    const list=$('quick-history-list');
    list.replaceChildren(...signals.slice(0,5).map(e=>node('p','card-room',`${new Date(e.at).toLocaleTimeString('fr-FR')} · ${e.name} · ${e.label}`)));
    if(!signals.length)list.append(node('p','card-room','Aucun signal SOS / impact reçu dans cette session Wokwi.'));
    const active=allResidents().filter(r=>r.acquisition.alerts.length);
    $('alert-toggle-count').textContent=active.length;
    $('alert-list').replaceChildren(...active.map(r=>{const el=node('p','',`${r.name} · ${r.acquisition.alerts.join(' · ')}`);el.onclick=()=>openDetail(r.id);return el;}));
    if(!active.length)$('alert-list').append(node('p','no-alerts','Aucun signal SOS / impact actuel.'));
    if(activeTab==='night')renderNight();
    if(activeTab==='validation')renderValidation();
    if(activeTab==='history')renderHistory();
    if(activeTab==='model3d')updateEHPAD3D();
    if(activeTab==='plan'){renderFloorPlan(currentFloor);renderEnvironment('tab-plan');}
    if(activeTab==='model3d')renderEnvironment('tab-model3d');
    if (currentDetailResident && $('detail-panel').classList.contains('open')) openDetail(currentDetailResident);
  }
  async function poll() {
    controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),7000);
    const started=performance.now();
    try {
      const response=await fetch('/api/hardware/snapshot?source=wokwi',{signal:controller.signal,cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data=await response.json();
      if (data.source!=='wokwi' || !Array.isArray(data.entities) || !Number.isFinite(data.received_at)) throw new Error('Réponse invalide');
      snapshot=data;receivedAt=Date.now();requestStarted=started;
      $('conn-status').textContent='Acquisition joignable';
      $('conn-dot').classList.add('connected');
      $('acquisition-note').textContent=`Simulation Wokwi · dernières données vérifiées à ${new Date(receivedAt).toLocaleTimeString('fr-FR')}. Les capteurs sans mesure récente restent déconnectés.`;
    } catch {
      snapshot=null;
      $('conn-status').textContent='Acquisition inaccessible';
      $('conn-dot').classList.remove('connected');
      $('acquisition-note').textContent='Acquisition inaccessible : aucune ancienne mesure ni valeur du simulateur ne remplace les données manquantes.';
    } finally {
      clearTimeout(timeout);render();
      if (!stopped) pollTimer=setTimeout(poll,2000);
    }
  }
  document.body.classList.add('acquisition-mode');
  $('acquisition-mode-label').textContent='Source : capteurs Wokwi des 25 résidents';
  $('wokwi-connection').hidden=true;
  $('sim-speed').disabled=true;
  $('sim-speed').parentElement.querySelector('span').textContent='Temps réel Wokwi';
  $('sim-speed').parentElement.querySelector('button').onclick=()=>location.reload();
  $('sim-speed-label').textContent='Wokwi';
  $('sim-speed').parentElement.querySelectorAll('div span').forEach(el=>el.textContent='Pilotage dans Wokwi');
  for (const id of ['stat-ml','stat-ok','stat-alerts']) {
    const stat=$(id).parentElement;
    stat.removeAttribute('onclick');stat.removeAttribute('title');
    stat.querySelector('.stat-label').textContent={ 'stat-ml':'Risque non évalué','stat-ok':'Résidents connectés','stat-alerts':'Résidents avec signal SOS / impact' }[id];
  }
  const style=node('style');
  style.textContent=`.acquisition-mode [hidden],.acquisition-mode .time-card:nth-child(n+3){display:none!important}.acquisition-mode .vital-val{font-size:14px}.acquisition-state{font-size:12px;color:var(--text2);margin:12px 0}.acquisition-mode #demo-banner{display:none!important}`;
  document.head.append(style);
  document.querySelector('.filter-bar button:nth-child(2)').textContent='Signaux SOS / impact';
  const risk=document.querySelector('.filter-bar button:nth-child(3)');risk.disabled=true;risk.title='Le score clinique n’est pas calculé à partir de ces signaux.';
  const demo=document.querySelector('.filter-bar button:nth-child(4)');demo.textContent='Démo historique';demo.onclick=()=>location.href='/?source=simulator';
  document.querySelector('.quick-history-head div div:nth-child(2)').textContent='Signaux effectivement reçus dans cette session Wokwi';
  document.querySelectorAll('.quick-history button').forEach(button=>button.onclick=()=>window.showTab('history'));
  document.querySelectorAll('#tab-history button').forEach(button=>{button.onclick=renderHistory;button.textContent='Signaux Wokwi reçus';});
  document.querySelector('#tab-history > div > span').textContent='Aucun historique simulé ajouté aux mesures Wokwi.';
  $('mini-dpi-llm-btn').disabled=true;$('mini-dpi-llm-btn').title='Le moteur clinique historique ne traite pas encore ce flux d’acquisition.';
  $('acquisition-note').textContent='Chargement des capteurs affectés aux résidents…';
  async function start() {
    try {
      const response=await fetch('/hardware-inventory.json',{cache:'no-store'});
      if (!response.ok) throw new Error('Catalogue inaccessible');
      inventory=await response.json();
      if (!Array.isArray(inventory.entities)||!Array.isArray(inventory.devices)) throw new Error('Catalogue invalide');
      render();ageTimer=setInterval(render,1000);poll();
    } catch {
      $('acquisition-note').textContent='Catalogue des capteurs inaccessible. Recharge la page lorsque le serveur est disponible.';
      $('conn-status').textContent='Catalogue inaccessible';
    }
  }
  window.addEventListener('pagehide',()=>{stopped=true;clearTimeout(pollTimer);clearInterval(ageTimer);controller?.abort();});
  start();
})();
