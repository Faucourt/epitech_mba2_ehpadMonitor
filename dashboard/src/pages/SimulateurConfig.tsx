import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';

const API = `${window.location.protocol}//${window.location.hostname}:8001`;
const PATHOLOGIES = ['hypertension', 'diabete', 'alzheimer', 'insuffisance_cardiaque', 'parkinson', 'bpco', 'insuffisance_renale'];

interface Profile {
  resident_id: string;
  effective?: {
    name?: string; room?: string; age?: number; mobility?: string; risk_factor?: number;
    caregiver?: string; meal_mode?: string; care_level?: string;
    pathologies?: string[]; assigned_scenarios?: string[]; assigned_movement_scenario?: string;
    notes?: string; avatar?: string;
  };
  history?: { status?: string; daily_days?: number; generated_at?: string };
}

interface Config {
  profiles: Profile[];
  scenarios: string[];
  storage_policy: Record<string, string>;
}

export function SimulateurConfig() {
  const [config, setConfig] = useState<Config | null>(null);
  const [selectedId, setSelectedId] = useState<string>('');
  const [status, setStatus] = useState('Chargement...');

  async function loadConfig() {
    const res = await fetch(`${API}/api/simulator/config`);
    const data: Config = await res.json();
    setConfig(data);
    if (!selectedId && data.profiles?.[0]) setSelectedId(data.profiles[0].resident_id);
  }

  useEffect(() => { loadConfig().catch(e => setStatus(`Erreur: ${e.message}`)); }, []);

  const profile = config?.profiles.find(p => p.resident_id === selectedId);
  const e = profile?.effective ?? {};
  const h = profile?.history ?? {};

  async function saveProfile(form: HTMLFormElement) {
    const fd = new FormData(form);
    const body = {
      age: Number(fd.get('age')),
      mobility: fd.get('mobility'),
      risk_factor: Number(fd.get('risk_factor')),
      caregiver: fd.get('caregiver'),
      meal_mode: fd.get('meal_mode'),
      care_level: fd.get('care_level'),
      pathologies: fd.getAll('pathology'),
      assigned_scenarios: fd.getAll('scenario'),
      notes: fd.get('notes'),
    };
    const res = await fetch(`${API}/api/simulator/config/residents/${selectedId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    setStatus('Profil appliqué au live.');
    await loadConfig();
  }

  async function generateHistory(longMode: boolean) {
    setStatus('Génération en cours...');
    const body = { resident_id: selectedId, months: longMode ? 12 : 1, detailed_days: 30, step_hours: 6, overwrite: true };
    const res = await fetch(`${API}/api/simulator/config/history/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    setStatus(JSON.stringify(data.histories?.[0] ?? data, null, 2));
    await loadConfig();
  }

  return (
    <div style={{ minHeight: '100vh', background: '#0f1422', color: '#e6edf8', fontFamily: 'Segoe UI, sans-serif' }}>
      <header style={{ position: 'sticky', top: 0, zIndex: 3, display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 18px', background: 'rgba(15,20,34,.96)', borderBottom: '1px solid #26334c' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20 }}>Config simulateur</h1>
          <p style={{ margin: 0, color: '#9fb0c7', fontSize: 12 }}>Profils persistants, scénarios assignés, historique patient</p>
        </div>
        <Link to="/" style={{ background: '#2563eb', color: '#fff', padding: '9px 12px', borderRadius: 8, textDecoration: 'none', fontWeight: 800 }}>Dashboard</Link>
      </header>

      <div style={{ padding: 16, display: 'grid', gridTemplateColumns: '320px minmax(0, 1fr)', gap: 14 }}>
        {/* Resident list */}
        <div style={{ background: '#151c2d', border: '1px solid #26334c', borderRadius: 10, padding: 14 }}>
          <h2 style={{ fontSize: 13, color: '#9fb0c7', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 10 }}>Résidents</h2>
          <div style={{ display: 'grid', gap: 8, maxHeight: 'calc(100vh - 130px)', overflowY: 'auto' }}>
            {config?.profiles.map(p => {
              const name = p.effective?.name ?? p.resident_id;
              const room = p.effective?.room ?? '—';
              const hist = p.history?.status === 'ready' ? `${p.history.daily_days}j hist.` : 'historique absent';
              return (
                <div
                  key={p.resident_id}
                  onClick={() => setSelectedId(p.resident_id)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10,
                    border: `1px solid ${p.resident_id === selectedId ? '#60a5fa' : '#26334c'}`,
                    background: p.resident_id === selectedId ? '#13213a' : '#101827',
                    borderRadius: 8, padding: 9, cursor: 'pointer',
                  }}
                >
                  <div style={{ width: 42, height: 42, borderRadius: 10, background: '#26334c', display: 'grid', placeItems: 'center', fontWeight: 900, flexShrink: 0 }}>
                    {name.split(' ').map((x: string) => x[0]).join('').slice(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <div style={{ fontWeight: 700 }}>{name}</div>
                    <div style={{ color: '#9fb0c7', fontSize: 12 }}>{p.resident_id} · Ch. {room} · {hist}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Editor */}
        <div style={{ background: '#151c2d', border: '1px solid #26334c', borderRadius: 10, padding: 14 }}>
          <h2 style={{ fontSize: 13, color: '#9fb0c7', textTransform: 'uppercase', letterSpacing: '.08em', marginBottom: 10 }}>Profil et historique</h2>
          {profile ? (
            <form onSubmit={ev => { ev.preventDefault(); saveProfile(ev.currentTarget).catch(err => setStatus(`Erreur: ${err.message}`)); }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 12 }}>
                {[
                  { id: 'age', label: 'Âge', type: 'number', value: e.age ?? 80, min: 50, max: 110 },
                  { id: 'risk_factor', label: 'Risque global', type: 'number', value: e.risk_factor ?? 0.3, min: 0, max: 1, step: 0.01 },
                ].map(f => (
                  <label key={f.id} style={{ display: 'grid', gap: 6, color: '#cbd5e1', fontSize: 12, fontWeight: 700 }}>
                    {f.label}
                    <input name={f.id} type={f.type} defaultValue={f.value as number} min={f.min} max={f.max} step={(f as { step?: number }).step}
                      style={{ border: '1px solid #334155', borderRadius: 8, background: '#0f172a', color: '#e5edf8', padding: '9px 10px' }} />
                  </label>
                ))}
                {[
                  { name: 'mobility', label: 'Mobilité', opts: ['bonne', 'moyenne', 'faible', 'tres_faible'], val: e.mobility },
                  { name: 'meal_mode', label: 'Repas', opts: ['salle', 'accompagne', 'chambre'], val: e.meal_mode },
                  { name: 'caregiver', label: 'Soignant référent', opts: ['soignant_A', 'soignant_B', 'soignant_C', 'chef_garde'], val: e.caregiver },
                  { name: 'care_level', label: 'Autonomie', opts: ['autonome', 'accompagne', 'chambre'], val: e.care_level },
                ].map(f => (
                  <label key={f.name} style={{ display: 'grid', gap: 6, color: '#cbd5e1', fontSize: 12, fontWeight: 700 }}>
                    {f.label}
                    <select name={f.name} defaultValue={f.val ?? f.opts[0]}
                      style={{ border: '1px solid #334155', borderRadius: 8, background: '#0f172a', color: '#e5edf8', padding: '9px 10px' }}>
                      {f.opts.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  </label>
                ))}
              </div>

              <h2 style={{ fontSize: 13, color: '#9fb0c7', textTransform: 'uppercase', margin: '16px 0 10px' }}>Pathologies</h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8 }}>
                {PATHOLOGIES.map(x => (
                  <label key={x} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 8, border: '1px solid #26334c', borderRadius: 8, background: '#101827', fontWeight: 600, cursor: 'pointer' }}>
                    <input type="checkbox" name="pathology" value={x} defaultChecked={(e.pathologies ?? []).includes(x)} style={{ width: 'auto' }} />
                    {x}
                  </label>
                ))}
              </div>

              <h2 style={{ fontSize: 13, color: '#9fb0c7', textTransform: 'uppercase', margin: '16px 0 10px' }}>Scénarios</h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8 }}>
                {(config?.scenarios ?? []).map(x => {
                  const activeScenarios = new Set([...(e.assigned_scenarios ?? []), e.assigned_movement_scenario].filter(Boolean));
                  return (
                    <label key={x} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: 8, border: '1px solid #26334c', borderRadius: 8, background: '#101827', fontWeight: 600, cursor: 'pointer' }}>
                      <input type="checkbox" name="scenario" value={x} defaultChecked={activeScenarios.has(x)} style={{ width: 'auto' }} />
                      {x}
                    </label>
                  );
                })}
              </div>

              <label style={{ display: 'grid', gap: 6, color: '#cbd5e1', fontSize: 12, fontWeight: 700, marginTop: 12 }}>
                Notes profil
                <textarea name="notes" defaultValue={e.notes ?? ''}
                  style={{ border: '1px solid #334155', borderRadius: 8, background: '#0f172a', color: '#e5edf8', padding: '9px 10px', minHeight: 74, resize: 'vertical', font: 'inherit' }} />
              </label>

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 12 }}>
                <button type="submit" style={{ background: '#059669', color: '#fff', padding: '9px 12px', borderRadius: 8, fontWeight: 800 }}>Appliquer au live</button>
                <button type="button" onClick={() => generateHistory(true)} style={{ background: '#d97706', color: '#fff', padding: '9px 12px', borderRadius: 8, fontWeight: 800 }}>Générer 12 mois</button>
                <button type="button" onClick={() => generateHistory(false)} style={{ background: '#334155', color: '#fff', padding: '9px 12px', borderRadius: 8, fontWeight: 800 }}>Générer 30 jours</button>
                <Link to={`/resident/${selectedId}`} style={{ background: '#334155', color: '#fff', padding: '9px 12px', borderRadius: 8, textDecoration: 'none', fontWeight: 800 }}>Mini-DPI</Link>
              </div>

              <pre style={{ marginTop: 10, padding: 10, borderRadius: 8, background: '#101827', border: '1px solid #26334c', color: '#cbd5e1', whiteSpace: 'pre-wrap', fontSize: 12 }}>
                {`Historique: ${h.status === 'ready' ? `${h.daily_days} jours, généré le ${h.generated_at}` : 'non généré'}\n${status}`}
              </pre>

              {config?.storage_policy && (
                <>
                  <h2 style={{ fontSize: 13, color: '#9fb0c7', textTransform: 'uppercase', margin: '16px 0 10px' }}>Politique stockage</h2>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <tbody>
                      {Object.entries(config.storage_policy).map(([k, v]) => (
                        <tr key={k} style={{ borderBottom: '1px solid #26334c' }}>
                          <th style={{ textAlign: 'left', padding: 7, color: '#9fb0c7' }}>{k}</th>
                          <td style={{ padding: 7 }}>{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </form>
          ) : (
            <div style={{ color: '#9fb0c7' }}>{status}</div>
          )}
        </div>
      </div>
    </div>
  );
}
