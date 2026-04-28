import { useState, useEffect } from 'react';
import type { Resident, Alert, HistoryBuffer } from '../../types';
import { AlertBadge } from '../alerts/AlertBadge';
import { VitalSparkline } from './VitalSparkline';

const BACKEND_HTTP = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8001`;

interface Props {
  resident: Resident;
  alert?: Alert;
  history?: HistoryBuffer;
  onClose: () => void;
  onFullscreen: () => void;
}

interface LlmReport {
  niveau_risque?: string;
  synthese_clinique?: string;
  resume?: string;
  actions_prioritaires?: Array<{ delai: string; action: string } | string>;
  sources_kb?: string[];
}

interface LlmData {
  report?: LlmReport;
  model?: string;
  duration_ms?: number;
  ml_risk?: number;
  alerts_count_today?: number;
}

const llmCache: Record<string, string> = {};

export function DrillDownPanel({ resident: r, alert, history, onClose, onFullscreen }: Props) {
  const [llmHtml, setLlmHtml] = useState<string>(llmCache[r.id] ?? '');
  const [llmLoading, setLlmLoading] = useState(false);
  const level = alert && !alert.resolved ? alert.level : 0;
  const v = r.vitals ?? {};

  // Restore cache when resident changes
  useEffect(() => {
    setLlmHtml(llmCache[r.id] ?? '');
  }, [r.id]);

  async function loadLlm() {
    setLlmLoading(true);
    try {
      const res = await fetch(`${BACKEND_HTTP}/api/llm/report/${r.id}`);
      if (!res.ok) throw new Error(String(res.status));
      const data: LlmData = await res.json();
      const html = renderLlmReport(data);
      setLlmHtml(html);
      llmCache[r.id] = html;
    } catch (e) {
      setLlmHtml(`<div style="color:var(--red);font-size:12px">Erreur: ${e instanceof Error ? e.message : 'inconnue'} (Ollama disponible ?)</div>`);
    } finally {
      setLlmLoading(false);
    }
  }

  return (
    <aside style={{
      width: 440,
      flexShrink: 0,
      borderLeft: '1px solid var(--border)',
      overflowY: 'auto',
      background: 'var(--bg2)',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Header */}
      <div style={{
        padding: '10px 14px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        position: 'sticky', top: 0, background: 'var(--bg2)', zIndex: 10,
      }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 14 }}>{r.name}</div>
          <div style={{ fontSize: 11, color: 'var(--text2)' }}>Ch. {r.room} · {r.current_zone ?? 'zone ?'}</div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {level > 0 && <AlertBadge level={level} />}
          <button onClick={onFullscreen} style={{ fontSize: 11, padding: '4px 8px' }}>⤢ Plein écran</button>
          <button onClick={onClose} style={{ fontSize: 11, padding: '4px 8px', background: 'transparent', color: 'var(--text2)' }}>✕</button>
        </div>
      </div>

      {/* N5 SAMU banner */}
      {level === 5 && (
        <div style={{ background: '#000', padding: '10px 14px', borderBottom: '2px solid #ff0000' }}>
          <div style={{ color: '#ff3333', fontWeight: 700, fontSize: 13, marginBottom: 6 }}>
            ⚠ DANGER VITAL — Appel SAMU requis
          </div>
          <a href="tel:15" style={{
            display: 'inline-block', background: '#dc2626', color: '#fff',
            padding: '8px 20px', borderRadius: 8, fontWeight: 800, fontSize: 14,
          }}>
            📞 SAMU 15
          </a>
        </div>
      )}

      <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* Vitals */}
        <section>
          <SectionTitle>Constantes</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px', fontSize: 12 }}>
            <Vital label="FC" value={v.heart_rate != null ? `${v.heart_rate} bpm` : '—'} />
            <Vital label="SpO2" value={v.spo2 != null ? `${v.spo2}%` : '—'} />
            <Vital label="PA" value={v.blood_pressure_sys != null ? `${v.blood_pressure_sys}/${v.blood_pressure_dia ?? '?'} mmHg` : '—'} />
            <Vital label="T°" value={v.temperature != null ? `${v.temperature.toFixed(1)}°C` : '—'} />
            <Vital label="FR" value={v.respiratory_rate != null ? `${v.respiratory_rate}/min` : '—'} />
          </div>
        </section>

        {/* Sparklines 30 min */}
        {history && (
          <section>
            <SectionTitle>Tendances 30 min</SectionTitle>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <SparkCard label="FC" data={history.hr} color="#ef4444" />
              <SparkCard label="SpO2" data={history.spo2} color="#3b82f6" />
              <SparkCard label="PA sys" data={history.bp} color="#f59e0b" />
              <SparkCard label="T°" data={history.temp} color="#a78bfa" />
            </div>
          </section>
        )}

        {/* Alert detail */}
        {alert && !alert.resolved && (
          <section>
            <SectionTitle>Alerte en cours</SectionTitle>
            <div style={{
              background: `${level === 5 ? '#000' : 'var(--bg3)'}`,
              border: `1px solid ${level === 5 ? '#ff0000' : '#2d3748'}`,
              borderRadius: 8, padding: 10, fontSize: 12,
              color: level === 5 ? '#ff3333' : 'var(--text)',
            }}>
              <div style={{ marginBottom: 4 }}>{alert.reason}</div>
              <div style={{ fontSize: 11, color: level === 5 ? '#ff5555' : 'var(--text3)' }}>
                {alert.created_at ? new Date(alert.created_at).toLocaleString('fr-FR') : ''}
                {alert.location ? ` · ${alert.location}` : ''}
              </div>
              {alert.notified_staff && Object.keys(alert.notified_staff).length > 0 && (
                <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text2)' }}>
                  Notifiés: {Object.keys(alert.notified_staff).join(', ')}
                </div>
              )}
            </div>
          </section>
        )}

        {/* Risk & activity */}
        <section>
          <SectionTitle>Situation</SectionTitle>
          <div style={{ display: 'grid', gap: 4, fontSize: 12 }}>
            <InfoRow label="Activité" value={r.activity ?? '—'} />
            <InfoRow label="Zone" value={r.current_zone ?? '—'} />
            <InfoRow label="Routine" value={r.routine_label ?? '—'} />
            <InfoRow label="Risque ML" value={r.ml_risk != null ? `${Math.round(r.ml_risk * 100)}%` : '—'} />
            <InfoRow label="Soignant" value={r.assigned_caregiver ?? '—'} />
          </div>
        </section>

        {/* LLM report */}
        <section>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
            <SectionTitle>Rapport LLM (Meditron)</SectionTitle>
            <button
              onClick={loadLlm}
              disabled={llmLoading}
              style={{ fontSize: 11, padding: '3px 10px' }}
            >
              {llmLoading ? '…' : llmHtml ? 'Régénérer' : 'Générer'}
            </button>
          </div>
          {llmLoading && (
            <div style={{ fontSize: 12, color: 'var(--text2)', padding: '8px 0' }}>
              Génération en cours (10–30s)…
            </div>
          )}
          {llmHtml && !llmLoading && (
            <div dangerouslySetInnerHTML={{ __html: llmHtml }} />
          )}
        </section>
      </div>
    </aside>
  );
}

function renderLlmReport(data: LlmData): string {
  const r = data.report ?? {};
  const color = r.niveau_risque === 'eleve' ? 'var(--red)' : r.niveau_risque === 'modere' ? 'var(--yellow)' : 'var(--green)';
  const actions = (r.actions_prioritaires ?? []).slice(0, 4);
  const sources = (r.sources_kb ?? []).join(', ') || '—';

  return `
    <div style="background:var(--bg3);border-radius:6px;padding:10px;font-size:12px;line-height:1.55;border:1px solid var(--border)">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:6px">
        <span style="font-weight:800;color:${color};text-transform:uppercase">${r.niveau_risque ?? '—'}</span>
        <span style="color:var(--text2);font-size:11px">${data.model ?? ''} · ${data.duration_ms ? data.duration_ms + 'ms' : ''}</span>
      </div>
      <div style="margin-bottom:8px">${r.synthese_clinique ?? r.resume ?? '—'}</div>
      ${actions.length ? `<div style="font-weight:700;margin:6px 0 3px">Actions</div>
        <ul style="padding-left:16px;margin:0">${actions.map(a => {
          const isObj = typeof a === 'object' && a !== null;
          return `<li><b>${isObj ? a.delai : 'Action'}</b> — ${isObj ? a.action : String(a)}</li>`;
        }).join('')}</ul>` : ''}
      <div style="color:var(--text2);font-size:11px;margin-top:6px">KB: ${sources} · aide à la décision</div>
    </div>`;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 6 }}>
      {children}
    </div>
  );
}

function Vital({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span style={{ color: 'var(--text3)', marginRight: 4 }}>{label}</span>
      <span style={{ fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text2)' }}>
      <span>{label}</span>
      <span style={{ fontWeight: 600, color: 'var(--text)' }}>{value}</span>
    </div>
  );
}

function SparkCard({ label, data, color }: { label: string; data: HistoryBuffer['hr']; color: string }) {
  const last = data[data.length - 1]?.v;
  return (
    <div style={{ background: 'var(--bg3)', borderRadius: 6, padding: '6px 8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 2 }}>
        <span style={{ color: 'var(--text3)' }}>{label}</span>
        {last != null && <span style={{ color, fontWeight: 700 }}>{Math.round(last)}</span>}
      </div>
      <VitalSparkline data={data} color={color} width={160} height={36} />
    </div>
  );
}
