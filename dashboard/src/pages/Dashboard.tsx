import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useWS } from '../context/WebSocketContext';
import { Header } from '../components/layout/Header';
import { TimeRibbon } from '../components/layout/TimeRibbon';
import { ResidentCard } from '../components/resident/ResidentCard';
import { AlertsSidebar } from '../components/alerts/AlertsSidebar';
import { ToastContainer } from '../components/alerts/Toast';
import { DrillDownPanel } from '../components/resident/DrillDownPanel';
import type { Alert, HistoryBuffer } from '../types';
import type { ToastData } from '../components/alerts/Toast';

type Filter = 'all' | 'alert' | 'risk' | 'demo';
const BACKEND_HTTP = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8001`;

export function Dashboard() {
  const { residents, activeAlerts, connected } = useWS();
  const [filter, setFilter] = useState<Filter>('all');
  const [selectedResident, setSelectedResident] = useState<string | null>(null);
  const [historyBuffers, setHistoryBuffers] = useState<Record<string, HistoryBuffer>>({});
  const [toasts, setToasts] = useState<ToastData[]>([]);
  const [simulatorSpeed, setSimulatorSpeed] = useState(1);
  const prevAlerts = useRef<Record<string, Alert>>({});

  // Toast on new alerts
  useEffect(() => {
    Object.values(activeAlerts).forEach(alert => {
      const prev = prevAlerts.current[alert.resident_id];
      if (!prev || prev.id !== alert.id) {
        setToasts(t => [...t.slice(-4), {
          id: `${alert.id}-${Date.now()}`,
          level: alert.level,
          residentName: alert.resident_name ?? alert.resident_id,
          reason: alert.reason,
        }]);
      }
    });
    prevAlerts.current = { ...activeAlerts };
  }, [activeAlerts]);

  // Update history buffers from incoming vitals
  useEffect(() => {
    Object.values(residents).forEach(r => {
      if (!r.vitals) return;
      const v = r.vitals;
      const ts = Date.now();
      const cutoff = ts - 30 * 60 * 1000;
      setHistoryBuffers(prev => {
        const buf = prev[r.id] ?? { hr: [], spo2: [], bp: [], temp: [] };
        const push = (arr: HistoryBuffer['hr'], val?: number) => {
          if (val == null || !isFinite(val)) return arr;
          const next = [...arr.filter(p => p.t >= cutoff), { t: ts, v: val }];
          return next.slice(-200);
        };
        return {
          ...prev,
          [r.id]: {
            hr: push(buf.hr, v.heart_rate),
            spo2: push(buf.spo2, v.spo2),
            bp: push(buf.bp, v.blood_pressure_sys),
            temp: push(buf.temp, v.temperature),
          },
        };
      });
    });
  }, [residents]);

  const filtered = useMemo(() => {
    const all = Object.values(residents);
    if (filter === 'alert') return all.filter(r => activeAlerts[r.id] && !activeAlerts[r.id].resolved);
    if (filter === 'risk') return all.filter(r => (r.ml_risk ?? 0) > 0.5);
    if (filter === 'demo') return all.filter(r => r.id === 'R005');
    return all;
  }, [residents, activeAlerts, filter]);

  const alertList = useMemo(
    () => Object.values(activeAlerts).filter(a => !a.resolved),
    [activeAlerts]
  );

  const criticalCount = alertList.filter(a => a.level >= 4).length;

  const dismissToast = useCallback((id: string) => {
    setToasts(t => t.filter(x => x.id !== id));
  }, []);

  async function changeSpeed(speed: number) {
    setSimulatorSpeed(speed);
    try {
      await fetch(`${BACKEND_HTTP}/api/simulator/speed?speed=${speed}`, { method: 'POST' });
    } catch { /* ignore */ }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <Header
        connected={connected}
        residentCount={Object.keys(residents).length}
        alertCount={alertList.length}
        criticalCount={criticalCount}
      />
      <TimeRibbon residents={residents} simulatorSpeed={simulatorSpeed} />

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        {/* Left sidebar — alerts */}
        <aside style={{
          width: 240,
          flexShrink: 0,
          borderRight: '1px solid var(--border)',
          overflowY: 'auto',
          background: 'var(--bg2)',
        }}>
          <div style={{ padding: '8px 12px', borderBottom: '1px solid var(--border)', fontSize: 12, fontWeight: 700, color: 'var(--text2)' }}>
            Alertes actives ({alertList.length})
          </div>
          <AlertsSidebar alerts={alertList} onSelectResident={setSelectedResident} />
        </aside>

        {/* Main content */}
        <main style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
          {/* Filter bar */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
            {(['all', 'alert', 'risk', 'demo'] as Filter[]).map(f => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  fontSize: 12, padding: '5px 12px',
                  background: filter === f ? 'var(--blue)' : 'var(--bg3)',
                  color: filter === f ? '#fff' : 'var(--text2)',
                }}
              >
                {f === 'all' ? 'Tous' : f === 'alert' ? 'En alerte' : f === 'risk' ? 'Risque ML' : 'Démo'}
              </button>
            ))}
            <span style={{ fontSize: 12, color: 'var(--text3)', marginLeft: 8 }}>
              {filtered.length} résidents
            </span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 12, color: 'var(--text3)' }}>Vitesse:</span>
              {[1, 5, 10, 30].map(s => (
                <button
                  key={s}
                  onClick={() => changeSpeed(s)}
                  style={{
                    fontSize: 11, padding: '4px 8px',
                    background: simulatorSpeed === s ? 'var(--purple)' : 'var(--bg3)',
                    color: simulatorSpeed === s ? '#fff' : 'var(--text2)',
                  }}
                >
                  x{s}
                </button>
              ))}
            </div>
          </div>

          {/* Nav links */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <NavLink href="/soignant">👤 Soignant</NavLink>
            <NavLink href="/famille">👨‍👩‍👧 Famille</NavLink>
            <NavLink href="/album-activites">📷 Album</NavLink>
            <NavLink href="/simulateur/config">⚙ Simulateur</NavLink>
          </div>

          {/* Resident grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
            gap: 10,
          }}>
            {filtered.map(r => (
              <ResidentCard
                key={r.id}
                resident={r}
                alert={activeAlerts[r.id]}
                history={historyBuffers[r.id]}
                onClick={() => setSelectedResident(r.id)}
              />
            ))}
          </div>
        </main>

        {/* Drill-down panel */}
        {selectedResident && residents[selectedResident] && (
          <DrillDownPanel
            resident={residents[selectedResident]}
            alert={activeAlerts[selectedResident]}
            history={historyBuffers[selectedResident]}
            onClose={() => setSelectedResident(null)}
            onFullscreen={() => window.open(`/resident/${selectedResident}`, '_blank')}
          />
        )}
      </div>

      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      style={{
        fontSize: 12, padding: '5px 12px',
        background: 'var(--bg3)', color: 'var(--text2)',
        borderRadius: 8, border: '1px solid var(--border)',
        textDecoration: 'none',
      }}
    >
      {children}
    </a>
  );
}
