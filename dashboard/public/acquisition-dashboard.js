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
  window.AcquisitionDashboard={renderCard,renderDetail,updateStats};
  function render() {
    if (!inventory) return;
    const elapsed=snapshot?(performance.now()-requestStarted)/1000:0;
    residents=Object.fromEntries(ResidentAcquisition.project(inventory,snapshot,elapsed).map(r=>[r.id,r]));
    liveResidents=cloneState(residents);
    renderGrid();updateStats();
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
  $('sim-speed').parentElement.hidden=true;
  for (const id of ['stat-ml','stat-ok','stat-alerts']) {
    const stat=$(id).parentElement;
    stat.removeAttribute('onclick');stat.removeAttribute('title');
    stat.querySelector('.stat-label').textContent={ 'stat-ml':'Risque non évalué','stat-ok':'Résidents connectés','stat-alerts':'Résidents avec signal SOS / impact' }[id];
  }
  const style=node('style');
  style.textContent=`.acquisition-mode [hidden],.acquisition-mode .quick-history,.acquisition-mode .tabs,.acquisition-mode #alert-toggle,.acquisition-mode #alert-sidebar,.acquisition-mode .time-card:nth-child(n+3),.acquisition-mode .filter-bar button:nth-child(n+3){display:none!important}.acquisition-mode .vital-val{font-size:14px}.acquisition-state{font-size:12px;color:var(--text2);margin:12px 0}.acquisition-mode #demo-banner{display:none!important}`;
  document.head.append(style);
  document.querySelector('.filter-bar button:nth-child(2)').textContent='Signaux SOS / impact';
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
