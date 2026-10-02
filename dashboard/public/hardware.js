/* Acquisition only: no generated measurements, clinical defaults or risk scores. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const labels = {live:'En direct',waiting:'En attente',stale:'Périmé',offline:'Hors ligne',unavailable:'Indisponible'};
  const roles = {wearable:'Capteurs du résident',pir:'Présence dans la chambre',radar:'Radar de présence',porte:'Ouverture de porte',sdb_pir:'Présence · salle de bain',matelas:'Matelas',ambient:'Environnement',co2:'Qualité de l’air · CO₂',son:'Ambiance sonore',temperature:'Température',fumee:'Gaz et fumée',co:'Monoxyde de carbone',camera_thermique:'Image thermique',ble_beacon:'Balise BLE',sol_intelligent:'Sol',sol_capteur:'Sol',gps_bracelet:'Localisation GNSS'};
  const fields = {heart_rate:'Fréquence cardiaque',spo2:'Saturation SpO₂',accel_g:'Accélération résultante',gyro_dps:'Rotation résultante',impact:'Impact',sos_pressed:'Bouton SOS',motion:'Mouvement',presence:'Présence',door_open:'Porte ouverte',contact_temperature_c:'Température de contact',temperature_c:'Température ambiante',humidity_pct:'Humidité',co2_ppm:'CO₂ mesuré',eco2_ppm:'eCO₂ estimé',co_ppm:'Monoxyde de carbone',tvoc_ppb:'Composés organiques volatils',sound_peak_to_peak_mv:'Amplitude sonore électrique',blood_pressure_sys:'Pression systolique',blood_pressure_dia:'Pression diastolique',respiratory_rate:'Fréquence respiratoire',respiration_mv:'Signal respiratoire',ecg_mv:'Signal ECG',leads_off:'Électrodes déconnectées',load_kg:'Charge',load_raw:'Charge brute',gas_adc:'Signal gaz brut',latitude:'Latitude',longitude:'Longitude',gps_fix:'Position GNSS valide',tag_uid:'Identifiant du badge',ble_address:'Adresse BLE',ble_rssi_dbm:'Puissance BLE reçue',thermal_max_c:'Température maximale',thermal_pixels_c:'Image thermique · 8 × 8',ir_raw:'Infrarouge brut',red_raw:'Rouge brut'};
  Object.assign(fields,{sound_db:'Niveau sonore',sound_mv:'Tension du capteur sonore',voc_index:'Indice COV',voc_raw:'Signal COV brut'});
  const units = {bool:'',count:'points',hex:'',MAC:'',deg:'°','deg/s':'°/s','breaths/min':'resp./min'};
  let source='wokwi',type='resident',snapshot=null,inventory=null,failed=false,version=0,timer=null,controller=null,lastSuccess=null;
  const opened=new Set();
  const make=(tag,className,text)=>{const n=document.createElement(tag);if(className)n.className=className;if(text!==undefined)n.textContent=text;return n;};
  function currentStatus(device){return failed&&device.status==='live'?'stale':device.status||'waiting';}
  function effectiveEntities(){
    if(snapshot)return snapshot.entities;
    if(!inventory)return [];
    return inventory.entities.map(e=>({...e,alerts:[],devices:inventory.devices.filter(d=>d.entity_id===e.id).map(d=>({...d,status:'waiting',values:{}}))}));
  }
  function ageText(timestamp){
    if(!timestamp)return 'aucune réception';
    const seconds=Math.max(0,Math.floor(Date.now()/1000-timestamp));
    return seconds<60?`reçu il y a ${seconds} s`:`reçu il y a ${Math.floor(seconds/60)} min`;
  }
  function sourceName(){return source==='wokwi'?'Simulation Wokwi':'Matériel réel';}
  function renderDevice(d){
    const model=inventory?.catalog?.[d.kind]||{};
    const status=currentStatus(d),live=status==='live'&&!failed;
    const article=make('article','device');
    const heading=make('div','device-heading');
    const identity=make('div');identity.append(make('h3','',model.model||d.kind),make('p','device-id',d.id));
    heading.append(identity,make('span',`status ${status}`,labels[status]||'État inconnu'));
    article.append(heading,make('p','provenance',`${sourceName()} · ${model.bus||'Interface non renseignée'} · ${ageText(d.received_at)}`));
    const measures=make('dl','measurements');
    for(const [field,unit] of Object.entries(d.fields||{})){
      const pair=make('div');pair.append(make('dt','',fields[field]||field));
      const value=live?d.values?.[field]:null;
      const dd=make('dd');
      if(value===null||value===undefined){dd.className='unmeasured';dd.textContent='non mesuré';}
      else if(field==='thermal_pixels_c'&&Array.isArray(value)&&value.length===64&&value.every(Number.isFinite)){
        const min=Math.min(...value),max=Math.max(...value),grid=make('div','thermal-grid');
        grid.setAttribute('role','img');grid.setAttribute('aria-label',`Image thermique de 64 points, minimum ${min} °C, maximum ${max} °C`);
        value.forEach((v,i)=>{const cell=make('span','thermal-cell');const t=(v-min)/Math.max(max-min,1);cell.style.backgroundColor=`hsl(${240-t*240} 78% ${32+t*23}%)`;cell.title=`Ligne ${Math.floor(i/8)+1}, colonne ${i%8+1} : ${v} °C`;grid.append(cell);});
        dd.append(grid,make('p','thermal-scale',`${min.toLocaleString('fr-FR')} → ${max.toLocaleString('fr-FR')} °C · échelle relative`));
      }else if(typeof value==='boolean'){
        dd.textContent=value?'Oui':'Non';if(value&&['sos_pressed','impact','leads_off'].includes(field))dd.className='signal';
      }else{
        const display=typeof value==='number'?value.toLocaleString('fr-FR',{maximumFractionDigits:field==='latitude'||field==='longitude'?6:2}):String(value);
        const suffix=Object.hasOwn(units,unit)?units[unit]:unit;
        dd.textContent=`${display}${suffix?' '+suffix:''}`;
      }
      pair.append(dd);measures.append(pair);
    }
    article.append(measures);
    if(model.limit)article.append(make('p','limit',model.limit));
    return article;
  }
  function renderEntity(entity){
    const devices=entity.devices||[],live=devices.filter(d=>currentStatus(d)==='live').length;
    const alerts=failed?[]:entity.alerts||[];
    const details=make('details',`entity${alerts.length?' has-alert':''}`);details.dataset.entityId=entity.id;details.open=opened.has(entity.id);
    const summary=make('summary');summary.id=`entity-${entity.id}`;
    const identity=make('span');identity.append(make('span','entity-name',entity.name||entity.id),make('span','entity-id',entity.id));
    const place=entity.type==='resident'?`Chambre ${entity.room||'non attribuée'} · ${entity.floor===0?'RDC':'Étage '+entity.floor}`:entity.floor===0?'Rez-de-chaussée':`Étage ${entity.floor??'non renseigné'}`;
    const coverage=make('span','entity-coverage');coverage.append(make('strong','',`${live} / ${devices.length}`),document.createTextNode(' en direct'));
    const stateSummary=live?'Mesures reçues':devices.some(d=>currentStatus(d)==='stale')?'Mesures périmées':devices.some(d=>currentStatus(d)==='offline')?'Capteurs hors ligne':devices.some(d=>currentStatus(d)==='unavailable')?'Capteurs indisponibles':'En attente de mesures';
    summary.append(identity,make('span','place',place),make('span',alerts.length?'entity-alert':'entity-clear',alerts.length?`${alerts.length} signal${alerts.length>1?'s':''} à vérifier`:stateSummary),coverage);
    details.append(summary);
    function populate(){
      if(details.querySelector('.entity-body'))return;
      const body=make('div','entity-body');
      if(alerts.length){const list=make('ul','alert-list');for(const alert of alerts)list.append(make('li','',typeof alert==='string'?alert:alert.label||alert.field||'Signal à vérifier'));body.append(list);}
      const groups=new Map();for(const d of devices){if(!groups.has(d.role))groups.set(d.role,[]);groups.get(d.role).push(d);}
      for(const [role,group] of groups){body.append(make('h2','role-heading',roles[role]||role.replaceAll('_',' ')));for(const d of group)body.append(renderDevice(d));}
      if(!devices.length)body.append(make('p','provenance','Aucun capteur physique attendu pour cette fonction.'));
      details.append(body);
    }
    if(details.open)populate();
    details.addEventListener('toggle',()=>{if(details.open){opened.add(entity.id);populate();}else opened.delete(entity.id);});
    return details;
  }
  function render(){
    const entities=effectiveEntities();
    const count=t=>entities.filter(e=>e.type===t).length;
    const allDevices=entities.flatMap(e=>e.devices||[]),live=allDevices.filter(d=>currentStatus(d)==='live').length;
    const expected=snapshot?.expected_devices??inventory?.devices?.length;
    $('live-count').textContent=entities.length?live:'—';$('expected-count').textContent=` / ${expected??'—'}`;
    $('missing-count').textContent=expected===undefined?'—':Math.max(0,expected-live);
    $('coverage-progress').max=expected||1;$('coverage-progress').value=live;
    for(const t of ['resident','zone']){$(`${t}-count`).textContent=entities.length?count(t):'—';$(`${t}-tab-count`).textContent=entities.length?count(t):'';}
    const query=$('search').value.trim().toLocaleLowerCase('fr'),filter=$('filter').value;
    const filtered=entities.filter(e=>{
      if(e.type!==type)return false;
      const devices=e.devices||[],liveCount=devices.filter(d=>currentStatus(d)==='live').length;
      if(filter==='live'&&!liveCount||filter==='missing'&&liveCount===devices.length||filter==='alert'&&(failed||!e.alerts?.length))return false;
      const haystack=[e.id,e.name,e.room,...devices.flatMap(d=>[d.id,d.kind,d.role,inventory?.catalog?.[d.kind]?.model])].join(' ').toLocaleLowerCase('fr');
      return !query||haystack.includes(query);
    });
    const focusId=document.activeElement?.tagName==='SUMMARY'?document.activeElement.id:null;
    $('entities').replaceChildren(...filtered.map(renderEntity));
    if(focusId)document.getElementById(focusId)?.focus({preventScroll:true});
    $('results-count').textContent=`${filtered.length} / ${count(type)} ${type==='resident'?'résidents':'zones'}`;
    $('empty').hidden=filtered.length>0||(!inventory&&!snapshot);
    $('last-update').textContent=lastSuccess?`Dernière réponse : ${new Date(lastSuccess).toLocaleTimeString('fr-FR')}`:'';
  }
  async function poll(){
    const requestVersion=version,requestedSource=source;
    const active=new AbortController();controller=active;
    const timeout=setTimeout(()=>active.abort(),7000);
    try{
      const headers={};
      if(requestedSource==='hardware'){
        const token=localStorage.getItem('ehpad_staff_token');if(token)headers.Authorization=`Bearer ${token}`;
      }
      const response=await fetch(`/api/hardware/snapshot?source=${requestedSource}`,{headers,signal:active.signal,cache:'no-store'});
      if(!response.ok){const error=new Error(response.status===401?'Connexion soignant requise pour les mesures matérielles.':`Acquisition inaccessible (HTTP ${response.status}).`);error.status=response.status;throw error;}
      const data=await response.json();
      if(requestVersion!==version)return;
      if(data.source!==requestedSource||!Array.isArray(data.entities)||!Number.isFinite(data.expected_devices))throw new Error('Réponse d’acquisition invalide.');
      snapshot=data;failed=false;lastSuccess=Date.now();
      $('connection-text').textContent=`${sourceName()} · acquisition joignable`;$('connection-light').className='light live';$('signin').hidden=true;
    }catch(error){
      if(requestVersion!==version)return;
      failed=true;$('connection-light').className='light error';$('signin').hidden=error.status!==401;
      $('connection-text').textContent=error.name==='AbortError'?'Délai de connexion dépassé. Les mesures précédentes sont périmées.':`${error.message} Les mesures précédentes sont périmées.`;
    }finally{
      clearTimeout(timeout);
      if(requestVersion===version){controller=null;render();timer=setTimeout(poll,2000);}
    }
  }
  $('source').addEventListener('change',()=>{
    version++;clearTimeout(timer);controller?.abort();source=$('source').value;snapshot=null;failed=false;lastSuccess=null;opened.clear();
    $('connection-light').className='light';$('connection-text').textContent=`Connexion · ${sourceName()}…`;$('signin').hidden=true;
    $('source-note').textContent=source==='wokwi'?'Simulation Wokwi : valeurs produites par les composants simulés. Les champs absents restent « non mesuré ».':'Matériel réel : seules les mesures reçues des appareils sont affichées. Les champs absents restent « non mesuré ».';
    render();poll();
  });
  function selectTab(button){
    type=button.dataset.type;
    document.querySelectorAll('[role=tab]').forEach(tab=>{const active=tab===button;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;});
    $('entities').setAttribute('aria-labelledby',button.id);render();
  }
  document.querySelectorAll('[role=tab]').forEach(button=>{
    button.addEventListener('click',()=>selectTab(button));
    button.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const target=$((event.key==='Home'?'tab-resident':event.key==='End'?'tab-zone':type==='resident'?'tab-zone':'tab-resident'));selectTab(target);target.focus();}});
  });
  $('search').addEventListener('input',render);$('filter').addEventListener('change',render);
  window.addEventListener('pagehide',()=>{version++;clearTimeout(timer);controller?.abort();});
  async function loadInventory(){
    const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),7000);
    try{const r=await fetch('/hardware-inventory.json',{signal:abort.signal});if(!r.ok)throw new Error('Catalogue indisponible');const data=await r.json();if(!Array.isArray(data.entities)||!Array.isArray(data.devices))throw new Error('Catalogue invalide');inventory=data;$('catalog-error').hidden=true;render();}
    catch{$('catalog-error').hidden=false;}
    finally{clearTimeout(timeout);}
  }
  loadInventory();poll();
})();
