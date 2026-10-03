'use strict';
(function(root) {
  const BASE = 'digi5/lebretyves-ehpad-m1';
  const TOPICS = {vitals: `${BASE}/patient/P001/vitals`, alerts: `${BASE}/patient/P001/alerts`, status: `${BASE}/device/esp32-01/status`};
  const LEVELS = ['info', 'warning', 'danger'];
  const NAMES = {sos: 'Appel SOS', fall_suspected: 'Chute suspectée', hr_out_of_range: 'Fréquence hors plage'};
  class Feed {
    constructor() { this.online = false; this.connected = false; this.last = null; this.received = 0; this.points = []; this.events = []; this.invalid = 0; }
    ingest(topic, raw, now = Date.now()) {
      try {
        if (raw.length > 16384) throw Error('size');
        const p = JSON.parse(raw.toString());
        if (!p || typeof p !== 'object' || Array.isArray(p)) throw Error('object');
        if (topic === TOPICS.status) {
          if (!['online', 'offline'].includes(p.state) || (p.device_id && p.device_id !== 'esp32-01')) throw Error('status');
          this.online = p.state === 'online'; return true;
        }
        if (topic !== TOPICS.vitals && topic !== TOPICS.alerts) return false;
        if (p.patient_id !== 'P001' || p.device_id !== 'esp32-01' || !LEVELS.includes(p.alert_level ?? p.level)) throw Error('identity');
        if (typeof p.timestamp !== 'string' || (p.timestamp && (p.timestamp.length > 40 || !Number.isFinite(Date.parse(p.timestamp))))) throw Error('time');
        if (topic === TOPICS.vitals) {
          if (p.source !== 'esp32' || !Number.isFinite(p.heart_rate) || p.heart_rate < 30 || p.heart_rate > 180 || !Number.isSafeInteger(p.seq) || p.seq < 0 || !Number.isFinite(p.accel_peak_g) || p.accel_peak_g < 0 || typeof p.imu_ok !== 'boolean' || !LEVELS.includes(p.alert_level)) throw Error('vitals');
          this.last = p; this.received = now; this.online = true;
          this.points.push({t: now, v: p.heart_rate}); this.points = this.points.filter(x => x.t >= now - 1800000).slice(-900);
        } else {
          if (!Object.hasOwn(NAMES, p.type) || !LEVELS.includes(p.level) || !Number.isFinite(p.value)) throw Error('alert');
          this.events.unshift({type: p.type, name: NAMES[p.type], level: p.level, value: p.value, time: p.timestamp || new Date(now).toISOString()});
          this.events = this.events.slice(0, 30);
        }
        return true;
      } catch { this.invalid++; return false; }
    }
    resident(now = Date.now()) {
      const fresh = Boolean(this.connected && this.online && this.last && now - this.received <= 15000);
      return {id: 'P001', resident_id: 'P001', name: 'P001 · Wokwi', room: 'TP', source: 'wokwi',
        vitals: {heart_rate: fresh ? this.last.heart_rate : null, spo2: null, temperature: null, blood_pressure_sys: null, blood_pressure_dia: null, respiratory_rate: null},
        ml_risk: null, movement: {}, wokwi: {fresh, connected: this.connected, online: this.online, received: this.received,
          level: this.last?.alert_level || 'info', peak: this.last?.accel_peak_g ?? null, imu: this.last?.imu_ok ?? null,
          seq: this.last?.seq ?? null, timestamp: this.last?.timestamp || '', points: this.points.slice(), events: this.events.slice(), invalid: this.invalid}};
    }
  }
  const api = {Feed, TOPICS};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.WokwiFeed = api;
})(globalThis);
