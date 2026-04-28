import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import type { Alert } from '../types';
import { AlertBadge } from '../components/alerts/AlertBadge';

const BACKEND_HTTP = `${window.location.protocol}//${window.location.hostname}:8001`;

interface DpiReport {
  resident_id: string; resident_name: string; room: string;
  profile?: { age?: number; mobility?: string };
  current?: { vitals?: Record<string, number>; location?: string };
  risk?: { ml_risk?: number; alert_level_name?: string; trend_30d?: string };
  alerts_today?: unknown[];
  history_30d?: { avg_vitals?: Record<string, number>; alerts_count?: number };
  watch_points?: string[];
  next_actions?: string[];
  transmission_summary?: string;
}

export function ResidentDetail() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const staffToken = searchParams.get('token') ?? '';
  void searchParams.get('staff'); // URL param kept for future use
  const [dpi, setDpi] = useState<DpiReport | null>(null);
  const [alert, setAlert] = useState<Alert | null>(null);
  const [llmHtml, setLlmHtml] = useState('');
  const [llmLoading, setLlmLoading] = useState(false);
  const [loading, setLoading] = useState(true);

  const headers: Record<string, string> = staffToken ? { Authorization: `Bearer ${staffToken}` } : {};

  useEffect(() => {
    if (!id) return;
    Promise.all([
      fetch(`${BACKEND_HTTP}/api/residents/${id}/dpi`, { headers }).then(r => r.ok ? r.json() : null),
      fetch(`${BACKEND_HTTP}/api/alerts?resident_id=${id}`, { headers }).then(r => r.ok ? r.json() : null),
    ]).then(([dpiData, aData]) => {
      if (dpiData) setDpi(dpiData);
      if (aData?.active?.length) setAlert(aData.active[0]);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [id]);

  async function loadLlm() {
    setLlmLoading(true);
    try {
      const res = await fetch(`${BACKEND_HTTP}/api/llm/report/${id}`, { headers });
      if (!res.ok) throw new Error(String(res.status));
      const data = await res.json();
      const r = data.report ?? {};
      const color = r.niveau_risque === 'eleve' ? '#ef4444' : r.niveau_risque === 'modere' ? '#f59e0b' : '#10b981';
      setLlmHtml(`
        <div style="background:#242840;border-radius:8px;padding:12px;font-size:13px;line-height:1.55;border:1px solid #2d3748">
          <div style="font-weight:800;color:${color};text-transform:uppercase;margin-bottom:6px">${r.niveau_risque ?? '—'}</div>
          <div style="margin-bottom:8px">${r.synthese_clinique ?? r.resume ?? '—'}</div>
          <div style="color:#94a3b8;font-size:11px">KB: ${(r.sources_kb ?? []).join(', ') || '—'} · aide à la décision</div>
        </div>`);
    } catch (e) {
      setLlmHtml(`<div style="color:#ef4444">Erreur: ${e instanceof Error ? e.message : 'inconnue'}</div>`);
    } finally {
      setLlmLoading(false);
    }
  }

  if (loading) return <div style={loadingStyle}>Chargement du DPI…</div>;
  if (!dpi) return <div style={loadingStyle}>DPI introuvable.</div>;

  const v = dpi.current?.vitals ?? {};
  const avg = dpi.history_30d?.avg_vitals ?? {};
  const level = alert && !alert.resolved ? alert.level : 0;

  return (
    <div style={{ minHeight: '100vh', background: '#0f1117', color: '#e2e8f0', fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ background: '#1a1d2e', borderBottom: '1px solid #2d3748', padding: '12px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', position: 'sticky', top: 0, zIndex: 10 }}>
        <div>
          <div style={{ fontWeight: 800, fontSize: 18 }}>{dpi.resident_name}</div>
          <div style={{ fontSize: 12, color: '#94a3b8' }}>Chambre {dpi.room} · {dpi.profile?.age ? `${dpi.profile.age} ans` : ''} · {dpi.profile?.mobility ?? ''}</div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {level > 0 && <AlertBadge level={level} />}
          <button onClick={() => history.back()} style={{ background: '#242840', color: '#94a3b8', border: '1px solid #2d3748', borderRadius: 8, padding: '7px 12px', cursor: 'pointer', fontSize: 12 }}>← Retour</button>
        </div>
      </header>

      <div style={{ maxWidth: 900, margin: '0 auto', padding: 20, display: 'grid', gap: 16 }}>
        {/* Alert */}
        {alert && !alert.resolved && (
          <section style={{ background: level === 5 ? '#000' : '#1a1d2e', border: `2px solid ${level === 5 ? '#ff0000' : '#ef4444'}`, borderRadius: 12, padding: 16, color: level === 5 ? '#ff3333' : '#e2e8f0' }}>
            <div style={{ fontWeight: 700, marginBottom: 6 }}>Alerte N{level} en cours</div>
            <div style={{ fontSize: 13, lineHeight: 1.45 }}>{alert.reason}</div>
            {level === 5 && (
              <a href="tel:15" style={{ display: 'inline-block', marginTop: 12, background: '#dc2626', color: '#fff', padding: '8px 20px', borderRadius: 8, fontWeight: 800, textDecoration: 'none' }}>
                📞 SAMU 15
              </a>
            )}
          </section>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          {/* Current vitals */}
          <Card title="Constantes actuelles">
            {[
              ['FC', v.heart_rate != null ? `${v.heart_rate} bpm` : '—'],
              ['SpO2', v.spo2 != null ? `${v.spo2}%` : '—'],
              ['PA', v.blood_pressure_sys != null ? `${v.blood_pressure_sys} mmHg` : '—'],
              ['T°', v.temperature != null ? `${Number(v.temperature).toFixed(1)}°C` : '—'],
              ['FR', v.respiratory_rate != null ? `${v.respiratory_rate}/min` : '—'],
            ].map(([k, val]) => <DpiRow key={k} label={k} value={val} />)}
          </Card>

          {/* Risk */}
          <Card title="Risque et situation">
            <DpiRow label="Position" value={dpi.current?.location ?? '—'} />
            <DpiRow label="Risque ML" value={dpi.risk?.ml_risk != null ? `${Math.round(dpi.risk.ml_risk * 100)}%` : '—'} />
            <DpiRow label="Tendance" value={dpi.risk?.alert_level_name ?? '—'} />
            <DpiRow label="Tendance 30j" value={dpi.risk?.trend_30d ?? 'stable'} />
            <DpiRow label="Alertes / jour" value={String(dpi.alerts_today?.length ?? 0)} />
            <DpiRow label="Événements 30j" value={String(dpi.history_30d?.alerts_count ?? 0)} />
          </Card>

          {/* 30d avg */}
          <Card title="Moyennes 30 jours">
            {[
              ['FC moy.', avg.heart_rate != null ? `${Math.round(avg.heart_rate)} bpm` : '—'],
              ['SpO2 moy.', avg.spo2 != null ? `${Math.round(avg.spo2)}%` : '—'],
              ['PA moy.', avg.blood_pressure_sys != null ? `${Math.round(avg.blood_pressure_sys)} mmHg` : '—'],
            ].map(([k, val]) => <DpiRow key={k} label={k} value={val} />)}
          </Card>

          {/* Actions */}
          <Card title="Actions soignantes">
            {(dpi.next_actions ?? ['Surveillance standard.']).map((a, i) => (
              <div key={i} style={{ fontSize: 12, color: '#94a3b8', padding: '4px 0', borderBottom: '1px solid #2d3748' }}>{a}</div>
            ))}
          </Card>
        </div>

        {/* Transmission */}
        {dpi.transmission_summary && (
          <Card title="Transmission">
            <div style={{ fontSize: 13, lineHeight: 1.45, color: '#94a3b8' }}>{dpi.transmission_summary}</div>
          </Card>
        )}

        {/* Watch points */}
        {(dpi.watch_points ?? []).length > 0 && (
          <Card title="Points de vigilance">
            {dpi.watch_points!.map((p, i) => (
              <div key={i} style={{ fontSize: 12, color: '#94a3b8', padding: '4px 0', borderBottom: '1px solid #2d3748' }}>{p}</div>
            ))}
          </Card>
        )}

        {/* LLM */}
        <Card title="Rapport LLM (Meditron)">
          <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
            <button onClick={loadLlm} disabled={llmLoading} style={{ background: '#3b82f6', color: '#fff', border: 0, borderRadius: 8, padding: '7px 14px', fontWeight: 700, cursor: 'pointer', fontSize: 12 }}>
              {llmLoading ? '…' : llmHtml ? 'Régénérer' : 'Générer le rapport'}
            </button>
          </div>
          {llmHtml && <div dangerouslySetInnerHTML={{ __html: llmHtml }} />}
        </Card>
      </div>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section style={{ background: '#1a1d2e', border: '1px solid #2d3748', borderRadius: 12, padding: 16 }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 10 }}>{title}</div>
      {children}
    </section>
  );
}

function DpiRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid #2d3748', fontSize: 13 }}>
      <span style={{ color: '#94a3b8' }}>{label}</span>
      <span style={{ fontWeight: 600 }}>{value}</span>
    </div>
  );
}

const loadingStyle: React.CSSProperties = { minHeight: '100vh', background: '#0f1117', display: 'grid', placeItems: 'center', color: '#64748b' };
