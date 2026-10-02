/* Map only fresh Wokwi readings to the residents in the acquisition inventory. */
(function(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ResidentAcquisition = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function() {
  'use strict';
  function project(inventory, snapshot, elapsedSeconds = 0) {
    const incoming = new Map();
    if (snapshot?.source === 'wokwi' && Number.isFinite(snapshot.received_at)) {
      for (const entity of snapshot.entities || []) {
        for (const device of entity.devices || []) {
          if (device.entity_id === entity.id && !incoming.has(device.id)) incoming.set(device.id, device);
        }
      }
    }
    return inventory.entities.filter(e => e.type === 'resident').map(entity => {
      const readings = {};
      const devices = inventory.devices.filter(d => d.entity_id === entity.id).map(expected => {
        const received = incoming.get(expected.id);
        const age = received && Number.isFinite(received.received_at)
          ? Math.max(0, snapshot.received_at - received.received_at) + Math.max(0, elapsedSeconds) : Infinity;
        const matches = received?.entity_id === entity.id && received?.kind === expected.kind;
        const communicating = matches && age <= 15 && ['live', 'unavailable'].includes(received.status);
        const live = communicating && received.status === 'live';
        const values = {};
        if (live) for (const field of Object.keys(expected.fields)) {
          const value = received.values?.[field];
          if (value !== null && value !== undefined) values[field] = value;
        }
        Object.assign(readings, values);
        return {...expected, values, communicating, status: live ? 'live' : communicating ? 'unavailable' : 'offline'};
      });
      const alerts = [];
      if (readings.sos_pressed === true) alerts.push('Bouton SOS activé');
      if (readings.impact === true) alerts.push('Impact détecté — à vérifier');
      return {...entity, source: 'wokwi-collective', vitals: readings, ml_risk: null,
        acquisition: {devices, alerts, communicating: devices.filter(d => d.communicating).length,
          live: devices.filter(d => d.status === 'live').length}};
    });
  }
  return {project};
});
