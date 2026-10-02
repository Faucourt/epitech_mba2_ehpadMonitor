'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const base = 'digi5/lebretyves-ehpad-m1';
  const topics = {vitals: `${base}/patient/P001/vitals`, alerts: `${base}/patient/P001/alerts`, status: `${base}/device/esp32-01/status`};
  const levels = ['info', 'warning', 'danger'];
  const names = {sos: 'Appel SOS', fall_suspected: 'Chute suspectée', hr_out_of_range: 'Fréquence hors plage'};
  const points = [];
  let last = 0, eventCount = 0, invalid = 0, recorder, stream;
  function badge(id, value, state = '') { $(id).textContent = value; $(id).className = `badge ${state}`; }
  function validTime(v) { return typeof v === 'string' && (v === '' || (v.length <= 40 && Number.isFinite(Date.parse(v)))); }
  function time(v) { return v ? new Date(v).toLocaleTimeString('fr-FR', {hour12: false}) : 'Horloge non synchronisée'; }
  function fresh() {
    const age = last ? (Date.now() - last) / 1000 : Infinity;
    document.querySelector('.heart').classList.toggle('stale', age > 7);
    badge('fresh', !last ? 'En attente' : age > 7 ? 'Mesure périmée' : 'Mesure récente', !last ? '' : age > 7 ? 'warning' : 'ok');
    $('age').textContent = last ? `Reçue il y a ${Math.floor(age)} s` : 'Aucune donnée';
    if (age > 7) $('hr').textContent = '—';
  }
  function renderVitals(p) {
    last = Date.now();
    $('hr').textContent = p.heart_rate;
    $('level').textContent = {info: 'Niveau normal', warning: 'Vigilance', danger: 'Alerte élevée'}[p.alert_level];
    $('timestamp').textContent = time(p.timestamp); $('seq').textContent = p.seq; $('source').textContent = p.source;
    $('accel').textContent = `${p.accel_peak_g.toFixed(2)} g`; $('imu').textContent = p.imu_ok ? 'Opérationnel' : 'Indisponible';
    points.push(p.heart_rate); if (points.length > 60) points.shift();
    $('line').setAttribute('points', points.map((v, i) => `${i * 720 / 59},${115 - (Math.min(220, Math.max(30, v)) - 30) / 190 * 100}`).join(' '));
    $('chartEmpty').hidden = true;
    $('normalized').textContent = JSON.stringify({resident_id: 'P001', device_id: 'esp32-01', vitals: {heart_rate: p.heart_rate, spo2: null, temperature: null, blood_pressure_sys: null, blood_pressure_dia: null, respiratory_rate: null}, alert_level: p.alert_level, timestamp: p.timestamp, accel_peak_g: p.accel_peak_g, imu_ok: p.imu_ok, source: p.source, seq: p.seq}, null, 2);
    fresh();
  }
  function addEvent(p) {
    if (!eventCount) $('events').replaceChildren();
    eventCount++; $('count').textContent = `${eventCount} événement${eventCount > 1 ? 's' : ''}`;
    const row = document.createElement('li'), severity = document.createElement('span'), label = document.createElement('span'), date = document.createElement('time');
    severity.className = `badge ${p.level === 'info' ? 'ok' : p.level}`; severity.textContent = {info: 'Info', warning: 'Vigilance', danger: 'Alerte'}[p.level];
    label.className = 'event-label'; label.textContent = names[p.type] + (typeof p.value === 'number' ? ` · ${p.value}` : ''); date.textContent = time(p.timestamp);
    row.append(severity, label, date); $('events').prepend(row); while ($('events').children.length > 30) $('events').lastChild.remove();
  }
  if (typeof mqtt === 'undefined') badge('broker', 'Bibliothèque MQTT indisponible', 'danger');
  else {
    const client = mqtt.connect('wss://broker.hivemq.com:8884/mqtt', {clientId: `epicare-m1-${Math.random().toString(16).slice(2)}`, clean: true, reconnectPeriod: 3000, connectTimeout: 15000});
    client.on('connect', () => { client.subscribe(Object.values(topics), {qos: 1}, (err, grants) => badge('broker', err || !grants || grants.some(g => g.qos === 128) ? 'Abonnement refusé' : 'MQTT connecté', err || !grants || grants.some(g => g.qos === 128) ? 'danger' : 'ok')); });
    client.on('reconnect', () => badge('broker', 'Reconnexion MQTT…', 'warning'));
    client.on('offline', () => badge('broker', 'MQTT déconnecté', 'warning'));
    client.on('error', () => badge('broker', 'Erreur de connexion MQTT', 'danger'));
    client.on('message', (topic, data) => {
      try {
        if (data.length > 16384) throw Error('size');
        const p = JSON.parse(data.toString()); if (!p || Array.isArray(p) || typeof p !== 'object') throw Error('object');
        if ((topic === topics.vitals || topic === topics.alerts) && (p.patient_id !== 'P001' || p.device_id !== 'esp32-01')) throw Error('identity');
        if (topic === topics.vitals) {
          if (!Number.isFinite(p.heart_rate) || p.heart_rate < 0 || p.heart_rate > 300 || !levels.includes(p.alert_level) || !validTime(p.timestamp) || !Number.isFinite(p.accel_peak_g) || p.accel_peak_g < 0 || typeof p.imu_ok !== 'boolean' || p.source !== 'esp32' || !Number.isSafeInteger(p.seq) || p.seq < 0) throw Error('vitals');
          renderVitals(p);
        } else if (topic === topics.alerts) {
          if (!Object.hasOwn(names, p.type) || !levels.includes(p.level) || !validTime(p.timestamp) || !(p.value === null || typeof p.value === 'boolean' || Number.isFinite(p.value) || (typeof p.value === 'string' && p.value.length <= 200))) throw Error('alert');
          addEvent(p);
        } else if (topic === topics.status) {
          if (!['online','offline'].includes(p.state)) throw Error('status');
          badge('device', p.state === 'online' ? 'Appareil en ligne' : 'Appareil hors ligne', p.state === 'online' ? 'ok' : 'warning');
        } else return;
        $('topic').textContent = topic; $('raw').textContent = JSON.stringify(p, null, 2);
      } catch { invalid++; $('invalid').textContent = `${invalid} message${invalid > 1 ? 's' : ''} invalide${invalid > 1 ? 's' : ''} ignoré${invalid > 1 ? 's' : ''}`; }
    });
    window.addEventListener('beforeunload', () => client.end(true));
  }
  setInterval(fresh, 1000); fresh();
  let downloadUrl;
  $('record').addEventListener('click', async () => {
    if (recorder && recorder.state === 'recording') { $('record').disabled = true; recorder.stop(); return; }
    $('record').disabled = true;
    try {
      if (!navigator.mediaDevices?.getDisplayMedia || typeof MediaRecorder === 'undefined') throw Error('unsupported');
      stream = await navigator.mediaDevices.getDisplayMedia({video: {frameRate: 30}, audio: false});
      const mimeType = ['video/webm;codecs=vp9','video/webm;codecs=vp8','video/webm'].find(type => MediaRecorder.isTypeSupported(type));
      if (!mimeType) throw Error('unsupported');
      recorder = new MediaRecorder(stream, {mimeType});
      const chunks = [];
      recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = () => {
        stream.getTracks().forEach(t => t.stop());
        if (downloadUrl) URL.revokeObjectURL(downloadUrl);
        downloadUrl = URL.createObjectURL(new Blob(chunks, {type: recorder.mimeType}));
        $('download').href = downloadUrl; $('download').download = `epicare-m1-${new Date().toISOString().replace(/[:.]/g, '-')}.webm`; $('download').hidden = false;
        $('record').disabled = false; $('record').textContent = '● Enregistrer l’écran'; $('recordStatus').textContent = 'Vidéo prête. Téléchargez-la pour conserver votre démonstration.';
      };
      stream.getVideoTracks()[0].addEventListener('ended', () => { if (recorder.state === 'recording') { $('record').disabled = true; recorder.stop(); } });
      recorder.start(1000); $('download').hidden = true; $('record').textContent = '■ Arrêter la vidéo'; $('recordStatus').textContent = 'Enregistrement en cours…';
    } catch (err) {
      stream?.getTracks().forEach(t => t.stop());
      $('recordStatus').textContent = err.name === 'NotAllowedError' ? 'Partage annulé ou refusé. Cliquez pour réessayer.' : 'Capture indisponible. Utilisez Chrome ou Edge sur localhost ou HTTPS.';
    } finally { $('record').disabled = false; }
  });
})();
