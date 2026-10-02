'use strict';
const wokwiFeed = new WokwiFeed.Feed();
const wokwiColors = {info: '#10b981', warning: '#f59e0b', danger: '#ef4444'};
function wokwiStatus(r) {
  const w = r.wokwi;
  return !w.connected ? 'Broker déconnecté' : !w.online ? 'Appareil hors ligne' : !w.received ? 'En attente de mesures' : !w.fresh ? 'Mesure périmée' : 'Appareil en ligne';
}
function wokwiChart(points) {
  const recent = points.slice(-60);
  const coords = recent.map((p,i) => `${10 + i * 480 / Math.max(1,recent.length-1)},${125 - (p.v-30)/150*110}`).join(' ');
  return `<svg viewBox="0 0 500 150" role="img" aria-label="Fréquence cardiaque reçue de Wokwi" style="width:100%;background:var(--bg);border-radius:8px"><path d="M10 15H490 M10 70H490 M10 125H490" stroke="#334155" fill="none"/><polyline points="${coords}" stroke="#2dd4bf" stroke-width="3" fill="none"/><text x="10" y="145" fill="#94a3b8" font-size="11">60 dernières mesures reçues · 30–180 bpm</text></svg>`;
}
function renderWokwiCard(card, r) {
  const w = r.wokwi;
  card.className = 'resident-card';
  card.style.borderColor = w.fresh ? wokwiColors[w.level] : '#64748b';
  card.innerHTML = `<div class="card-name">P001 · Wokwi ESP32</div><div class="card-room">Patient fictif · TP M1</div><div style="margin:10px 0;color:${w.fresh ? wokwiColors[w.level] : '#94a3b8'}">${wokwiStatus(r)}</div><div style="font-size:32px;font-weight:700">${r.vitals.heart_rate ?? '—'} <small style="font-size:14px">bpm</small></div>${wokwiChart(w.points)}<div style="font-size:12px;margin-top:8px">${w.events.length} événement(s) · SOS / chute / FC</div><div style="font-size:11px;color:var(--text2);margin-top:8px">SpO₂, température, PA : non mesurées<br>Score médical : non évalué</div>`;
}
function renderWokwiDetail(r) {
  const w = r.wokwi;
  document.getElementById('detail-panel').classList.add('open');
  document.getElementById('dp-name').textContent = 'P001 · Wokwi ESP32';
  document.getElementById('dp-info').textContent = 'TP M1 · patient fictif · capteurs simulés';
  document.getElementById('dp-content').innerHTML = `<div class="section-sub">${wokwiStatus(r)}</div><div style="font-size:48px;font-weight:800;color:${w.fresh ? wokwiColors[w.level] : '#94a3b8'}">${r.vitals.heart_rate ?? '—'} <small style="font-size:20px">bpm</small></div><div style="margin-bottom:12px">${w.fresh ? {info:'Niveau normal',warning:'Vigilance',danger:'Alerte élevée'}[w.level] : 'Aucune mesure actuelle'}</div>${wokwiChart(w.points)}<div class="vital-row"><span>Dernière mesure</span><span>${w.timestamp ? new Date(w.timestamp).toLocaleTimeString('fr-FR') : 'Horloge non synchronisée'}</span></div><div class="vital-row"><span>Séquence / origine</span><span>${w.seq ?? '—'} / esp32-01</span></div><div class="vital-row"><span>Pic accélération (dernière mesure)</span><span>${w.peak === null ? '—' : w.peak.toFixed(2)} g</span></div><div class="vital-row"><span>MPU-6050 (dernier état)</span><span>${w.imu === null ? 'Inconnu' : w.imu ? 'Détecté' : 'Indisponible'}</span></div><div class="section-sub">Mesures absentes</div><p>SpO₂, température, pression artérielle et respiration : non mesurées. Score médical et prédiction IA : non évalués.</p><div class="section-sub">Événements du firmware (${w.events.length})</div><div id="wokwi-events">${w.events.map(e=>`<div style="padding:9px 0;border-bottom:1px solid var(--border)"><strong style="color:${wokwiColors[e.level]}">${e.name} · ${e.value}</strong><div style="font-size:12px;color:var(--text2)">${new Date(e.time).toLocaleTimeString('fr-FR')} · ${e.level}</div></div>`).join('') || 'Aucun événement reçu'}</div><p style="font-size:11px;color:var(--text2);margin-top:15px">Flux direct MQTT over WebSocket · données fictives. Historique de cette session navigateur. Les niveaux du TP ne constituent pas une évaluation clinique.</p>`;
}
function syncWokwiResident() {
  if (ACQUISITION_MODE) return;
  liveResidents.P001 = wokwiFeed.resident();
  if (replayOffsetMinutes > 0 || historyOffsetDays > 0) return;
  residents.P001 = cloneState(liveResidents.P001);
  updateResidentCard('P001'); updateStats();
  const badge = document.getElementById('wokwi-connection');
  if (badge) badge.textContent = `Wokwi · ${wokwiStatus(residents.P001)}`;
}
function focusWokwi() { showTab('grid'); applyLiveState(); openDetail('P001'); }
if (!ACQUISITION_MODE && typeof mqtt !== 'undefined') {
  const client = mqtt.connect('wss://broker.hivemq.com:8884/mqtt', {clientId: `digi4-wokwi-${Math.random().toString(16).slice(2)}`, reconnectPeriod: 3000, connectTimeout: 15000});
  client.on('connect', () => client.subscribe(Object.values(WokwiFeed.TOPICS), {qos: 1}, (err, grants) => {
    wokwiFeed.connected = !err && grants?.length === 3 && grants.every(g=>g.qos !== 128); syncWokwiResident();
  }));
  for (const event of ['offline','close','error']) client.on(event, () => {wokwiFeed.connected = false; syncWokwiResident();});
  client.on('message', (topic, payload) => {
    if (wokwiFeed.ingest(topic, payload)) { syncWokwiResident(); captureTimelineSnapshot(); }
  });
  const timer = setInterval(syncWokwiResident, 1000);
  window.addEventListener('beforeunload', () => {clearInterval(timer); client.end(true);});
}
syncWokwiResident();
