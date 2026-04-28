import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';

const BACKEND_HTTP = `${window.location.protocol}//${window.location.hostname}:8001`;

const DEMO_STAFF = [
  { id: 'soignant_A', pwd: 'EHPAD2024!' },
  { id: 'soignant_B', pwd: 'EHPAD2024!' },
  { id: 'soignant_C', pwd: 'EHPAD2024!' },
  { id: 'chef_garde', pwd: 'EHPAD2024!' },
  { id: 'direction', pwd: 'EHPAD2024!' },
];

interface Notification {
  notification_key?: string; alert_id?: string; resident_id?: string; resident_name?: string;
  level?: number; reason?: string; event?: string; location?: string; zone?: string; time?: string;
  samu_required?: boolean;
}

interface ResidentEntry {
  resident_id: string; name: string; room: string; alert_level?: number; ml_risk?: number;
  current_zone?: string; time_label?: string;
}

export function Soignant() {
  const { id: pathId } = useParams<{ id?: string }>();
  const [staffId, setStaffId] = useState(pathId ?? '');
  const [password, setPassword] = useState('');
  const [token, setToken] = useState(() => localStorage.getItem('ehpad_staff_token') ?? '');
  const [tokenStaffId] = useState(() => localStorage.getItem('ehpad_staff_id') ?? '');
  const [loggedIn, setLoggedIn] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [staffName, setStaffName] = useState('Identification requise');
  const [staffRole, setStaffRole] = useState('Espace personnel tracé');
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [residents, setResidents] = useState<ResidentEntry[]>([]);
  const [clock, setClock] = useState('--:--');
  const [topNotif, setTopNotif] = useState<Notification | null>(null);
  const [localStatus, setLocalStatus] = useState<Record<string, { status: string; at: string; by: string }>>(() =>
    JSON.parse(localStorage.getItem('ehpad_staff_notif_status') ?? '{}')
  );

  useEffect(() => {
    const t = setInterval(() => setClock(new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })), 1000);
    return () => clearInterval(t);
  }, []);

  function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
    return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
  }

  function saveLocalStatus(next: typeof localStatus) {
    setLocalStatus(next);
    localStorage.setItem('ehpad_staff_notif_status', JSON.stringify(next));
  }

  function notifKey(n: Notification): string {
    return n.notification_key ?? n.alert_id ?? `${n.resident_id}-${n.level}-${n.time ?? ''}-${n.reason ?? n.event ?? ''}`;
  }

  async function login() {
    setLoginError('');
    try {
      const res = await fetch(`${BACKEND_HTTP}/api/staff/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ staff_id: staffId, password }),
      });
      if (!res.ok) throw new Error('Identifiants incorrects');
      const data = await res.json();
      const t = data.token ?? '';
      setToken(t);
      localStorage.setItem('ehpad_staff_token', t);
      localStorage.setItem('ehpad_staff_id', staffId);
      setLoggedIn(true);
      loadStaff(t);
    } catch (e) {
      setLoginError(e instanceof Error ? e.message : 'Erreur');
    }
  }

  const loadStaff = useCallback(async (tk = token) => {
    if (!tk) return;
    try {
      const res = await fetch(`${BACKEND_HTTP}/api/staff/my-notifications`, {
        headers: { Authorization: `Bearer ${tk}` },
      });
      if (!res.ok) { setLoggedIn(false); return; }
      const data = await res.json();
      setLoggedIn(true);
      setStaffName(data.staff?.name ?? staffId);
      setStaffRole(`${data.staff?.role ?? 'soignant'} · ${data.staff?.sector ?? ''} · ${data.staff?.shift ?? ''}`);
      setNotifications(data.notifications ?? []);
      setResidents(data.assigned_residents ?? []);
      const top = (data.notifications ?? []).find((n: Notification) => (n.level ?? 0) >= 2);
      setTopNotif(top ?? null);
    } catch { /* ignore */ }
  }, [token, staffId]);

  useEffect(() => {
    if (token && tokenStaffId) loadStaff();
    const interval = setInterval(() => { if (loggedIn) loadStaff(); }, 15000);
    return () => clearInterval(interval);
  }, [loggedIn, loadStaff, token, tokenStaffId]);

  async function traceAction(key: string, action: string, n: Notification = {}) {
    const next = { ...localStatus, [key]: { status: action, at: new Date().toISOString(), by: staffId } };
    saveLocalStatus(next);
    try {
      await fetch(`${BACKEND_HTTP}/api/notifications/action`, {
        method: 'POST',
        headers: authHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ caregiver_id: staffId, action, notification_key: key, alert_id: n.alert_id, resident_id: n.resident_id, level: n.level, reason: n.reason ?? n.event, location: n.location ?? n.zone }),
      });
    } catch { /* ignore */ }
    loadStaff();
  }

  function logout() {
    setToken('');
    localStorage.removeItem('ehpad_staff_token');
    localStorage.removeItem('ehpad_staff_id');
    setLoggedIn(false);
  }

  const levelColors: Record<number, string> = { 2: 'rgba(245,158,11,0.14)', 3: 'rgba(249,115,22,0.16)', 4: 'rgba(239,68,68,0.20)', 5: 'rgba(239,68,68,0.20)' };

  // Login gate
  if (!loggedIn) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#101522', padding: 18 }}>
        <div style={{ width: 'min(420px, 100%)', background: '#151c2d', border: '1px solid #26334c', borderRadius: 14, padding: 22, boxShadow: '0 20px 70px rgba(0,0,0,.42)', color: '#e5edf8' }}>
          <h1 style={{ margin: '0 0 8px', fontSize: 20 }}>Identification personnel</h1>
          <p style={{ color: '#aab7ca', marginBottom: 14, lineHeight: 1.45 }}>Actions tracées sous cette identité.</p>
          <input value={staffId} onChange={e => setStaffId(e.target.value)} placeholder="ex: soignant_C" list="staff-list"
            style={{ width: '100%', background: '#0f172a', color: '#e5edf8', border: '1px solid #334155', borderRadius: 10, padding: 10, marginBottom: 8, font: 'inherit' }} />
          <datalist id="staff-list">
            {DEMO_STAFF.map(s => <option key={s.id} value={s.id} />)}
          </datalist>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="Mot de passe"
            style={{ width: '100%', background: '#0f172a', color: '#e5edf8', border: '1px solid #334155', borderRadius: 10, padding: 10, marginBottom: 8, font: 'inherit' }} />

          <div style={{ border: '1px solid #334155', background: '#0f172a', borderRadius: 12, padding: 12, marginBottom: 12, fontSize: 12 }}>
            <b style={{ color: '#e5edf8', display: 'block', marginBottom: 8 }}>Comptes démo</b>
            {DEMO_STAFF.map(s => (
              <div key={s.id} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 6, marginBottom: 4, alignItems: 'center' }}>
                <code style={{ background: '#111827', border: '1px solid #26334c', color: '#bfdbfe', borderRadius: 8, padding: '7px 8px', fontFamily: 'Consolas, monospace' }}>{s.id}</code>
                <code style={{ background: '#111827', border: '1px solid #26334c', color: '#bfdbfe', borderRadius: 8, padding: '7px 8px', fontFamily: 'Consolas, monospace' }}>{s.pwd}</code>
                <button onClick={() => { setStaffId(s.id); setPassword(s.pwd); }} style={{ background: '#26334c', color: '#dbeafe', border: '1px solid #334155', borderRadius: 8, padding: '7px 9px', fontWeight: 700, fontSize: 12, cursor: 'pointer', whiteSpace: 'nowrap' }}>Remplir</button>
              </div>
            ))}
          </div>
          <button onClick={login} style={{ width: '100%', background: '#2563eb', color: '#fff', border: 0, borderRadius: 10, padding: '9px 10px', fontWeight: 700, cursor: 'pointer', fontSize: 14 }}>Ouvrir mon accès</button>
          {loginError && <p style={{ color: '#fca5a5', marginTop: 8, textAlign: 'center' }}>{loginError}</p>}
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', fontFamily: 'Segoe UI, sans-serif', background: '#101522', color: '#e5edf8', display: 'grid', placeItems: 'start center', padding: 16 }}>
      <div style={{ width: 'min(390px, 100%)', border: '10px solid #05070c', borderRadius: 34, background: '#0b1020', boxShadow: '0 24px 70px rgba(0,0,0,.45)', overflow: 'hidden', height: 'min(820px, calc(100vh - 32px))', position: 'relative' }}>
        <div style={{ position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)', width: 112, height: 24, background: '#05070c', borderRadius: '0 0 16px 16px', zIndex: 2 }} />
        <div style={{ padding: '38px 16px 18px', height: '100%', overflowY: 'auto', background: 'linear-gradient(180deg, #111827 0%, #0f172a 100%)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, color: '#9fb0c7', marginBottom: 16, position: 'sticky', top: 0, zIndex: 2, paddingBottom: 8, background: 'linear-gradient(180deg, #111827 60%, rgba(17,24,39,0))' }}>
            <span>{clock}</span><span>● Connecté</span>
          </div>

          <div style={{ background: '#151c2d', border: '1px solid #26334c', borderRadius: 14, padding: 12, marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'flex-start' }}>
              <div>
                <strong style={{ display: 'block', fontSize: 18 }}>{staffName}</strong>
                <span style={{ color: '#9fb0c7', fontSize: 12 }}>{staffRole}</span>
              </div>
              <button onClick={logout} style={{ background: '#26334c', color: '#dbeafe', padding: '7px 9px', border: 0, borderRadius: 10, fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' }}>Déconnexion</button>
            </div>
          </div>

          {/* Top notification */}
          <div style={{ background: topNotif ? (levelColors[(topNotif.level ?? 1)] ?? 'rgba(59,130,246,0.18)') : 'rgba(59,130,246,0.18)', border: topNotif ? `1px solid rgba(239,68,68,.62)` : '1px solid rgba(59,130,246,.35)', borderRadius: 16, padding: 12, marginBottom: 12 }}>
            {topNotif ? (
              <>
                <h2 style={{ margin: '0 0 6px', fontSize: 15 }}>N{topNotif.level} — {topNotif.resident_name}</h2>
                <p style={{ margin: '3px 0', fontSize: 12, color: '#cbd5e1', lineHeight: 1.35 }}>{topNotif.reason ?? topNotif.event}</p>
                <p style={{ margin: '3px 0', fontSize: 12, color: '#cbd5e1' }}>{topNotif.location ?? topNotif.zone}</p>
                {topNotif.samu_required && (
                  <div style={{ marginTop: 10, border: '1px solid rgba(248,113,113,.55)', background: 'rgba(127,29,29,.32)', borderRadius: 12, padding: 10 }}>
                    <b style={{ color: '#fecaca' }}>⚠ SAMU 15 requis</b>
                    <a href="tel:15" style={{ display: 'block', marginTop: 6, background: '#dc2626', color: '#fff', padding: '6px 12px', borderRadius: 8, textAlign: 'center', fontWeight: 700, textDecoration: 'none' }}>📞 Appeler SAMU 15</a>
                  </div>
                )}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 10 }}>
                  <button onClick={() => traceAction(notifKey(topNotif), 'seen', topNotif)} style={{ background: '#26334c', color: '#dbeafe', border: 0, borderRadius: 10, padding: '9px 10px', fontWeight: 700, cursor: 'pointer', fontSize: 12 }}>Vu</button>
                  <button onClick={() => traceAction(notifKey(topNotif), 'acknowledged', topNotif)} style={{ background: '#059669', color: '#fff', border: 0, borderRadius: 10, padding: '9px 10px', fontWeight: 700, cursor: 'pointer', fontSize: 12 }}>Acquitter</button>
                </div>
              </>
            ) : (
              <>
                <h2 style={{ margin: '0 0 6px', fontSize: 15 }}>Aucune alerte prioritaire</h2>
                <p style={{ margin: 0, fontSize: 12, color: '#cbd5e1' }}>Les notifications apparaissent ici en direct.</p>
              </>
            )}
          </div>

          {/* Notifications list */}
          <div style={{ fontSize: 11, fontWeight: 800, color: '#9fb0c7', textTransform: 'uppercase', letterSpacing: '.08em', margin: '16px 0 8px' }}>Notifications</div>
          <div style={{ display: 'grid', gap: 8 }}>
            {notifications.length === 0 && <div style={{ color: '#8da0bb', fontSize: 13, textAlign: 'center', padding: 16, border: '1px dashed #334155', borderRadius: 12 }}>Aucune notification</div>}
            {notifications.map((n, i) => (
              <div key={i} style={{ background: '#151c2d', border: '1px solid #26334c', borderRadius: 12, padding: 10, fontSize: 12 }}>
                <b>{n.resident_name} · N{n.level}</b>
                <p style={{ margin: '3px 0', color: '#cbd5e1' }}>{n.reason ?? n.event}</p>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 }}>
                  <button onClick={() => traceAction(notifKey(n), 'seen', n)} style={{ background: '#26334c', color: '#dbeafe', border: 0, borderRadius: 8, padding: '7px 8px', fontWeight: 700, cursor: 'pointer', fontSize: 11 }}>Vu</button>
                  <a href={`/mobile/resident/${n.resident_id}?staff=${staffId}&token=${token}`} style={{ background: '#26334c', color: '#dbeafe', border: '1px solid #334155', borderRadius: 8, padding: '7px 8px', fontWeight: 700, fontSize: 11, textAlign: 'center', textDecoration: 'none' }}>Patient</a>
                </div>
              </div>
            ))}
          </div>

          {/* Assigned residents */}
          <div style={{ fontSize: 11, fontWeight: 800, color: '#9fb0c7', textTransform: 'uppercase', letterSpacing: '.08em', margin: '16px 0 8px' }}>Mes résidents</div>
          <div style={{ display: 'grid', gap: 8 }}>
            {residents.length === 0 && <div style={{ color: '#8da0bb', fontSize: 13, textAlign: 'center', padding: 16, border: '1px dashed #334155', borderRadius: 12 }}>Aucun résident assigné</div>}
            {residents.map(r => (
              <div key={r.resident_id} style={{ background: '#151c2d', border: '1px solid #26334c', borderRadius: 12, padding: 10, fontSize: 12 }}>
                <b>{r.name}</b>
                <span style={{ color: '#9fb0c7', marginLeft: 8 }}>Ch. {r.room} · {r.current_zone ?? 'zone ?'}</span>
                {(r.alert_level ?? 0) > 0 && <span style={{ marginLeft: 8, fontWeight: 700, color: '#ef4444' }}>N{r.alert_level}</span>}
                <a href={`/mobile/resident/${r.resident_id}?staff=${staffId}&token=${token}`} style={{ display: 'block', marginTop: 8, background: '#26334c', color: '#dbeafe', border: '1px solid #334155', borderRadius: 8, padding: '7px 8px', fontWeight: 700, fontSize: 11, textAlign: 'center', textDecoration: 'none' }}>
                  Ouvrir fiche
                </a>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
