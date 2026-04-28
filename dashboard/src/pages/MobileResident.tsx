import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import type { Resident, Alert } from '../types';

const BACKEND_HTTP = `${window.location.protocol}//${window.location.hostname}:8001`;

export function MobileResident() {
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const staffToken = searchParams.get('token') ?? '';
  const staffId = searchParams.get('staff') ?? '';
  const [resident, setResident] = useState<Resident | null>(null);
  const [alert, setAlert] = useState<Alert | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    const headers: Record<string, string> = staffToken ? { Authorization: `Bearer ${staffToken}` } : {};
    Promise.all([
      fetch(`${BACKEND_HTTP}/api/residents/${id}`, { headers }).then(r => (r.ok ? r.json() : null)),
      fetch(`${BACKEND_HTTP}/api/alerts?resident_id=${id}`, { headers }).then(r => (r.ok ? r.json() : null)),
    ]).then(([rData, aData]) => {
      if (rData) setResident(rData.resident ?? rData);
      if (aData?.active?.length) setAlert(aData.active[0]);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [id, staffToken]);

  if (loading) return <div style={{ minHeight: '100vh', background: '#0f172a', display: 'grid', placeItems: 'center', color: '#64748b' }}>Chargement…</div>;
  if (!resident) return <div style={{ minHeight: '100vh', background: '#0f172a', display: 'grid', placeItems: 'center', color: '#ef4444' }}>Résident introuvable</div>;

  const v = resident.vitals ?? {};
  const level = alert && !alert.resolved ? alert.level : 0;
  const alertColor = ['#10b981', '#3b82f6', '#f59e0b', '#f97316', '#ef4444', '#ff0000'][level] ?? '#10b981';

  return (
    <div style={{ minHeight: '100vh', background: '#0f172a', color: '#e5edf8', fontFamily: 'system-ui, sans-serif', padding: 16 }}>
      <div style={{ maxWidth: 400, margin: '0 auto' }}>
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <button onClick={() => history.back()} style={{ background: '#1e293b', color: '#94a3b8', border: 0, borderRadius: 8, padding: '8px 12px', cursor: 'pointer' }}>← Retour</button>
          {level > 0 && (
            <span style={{ background: level === 5 ? '#000' : `${alertColor}22`, color: level === 5 ? '#ff3333' : alertColor, border: `1px solid ${level === 5 ? '#ff0000' : alertColor}`, borderRadius: 999, padding: '4px 12px', fontWeight: 700, fontSize: 12 }}>
              N{level}
            </span>
          )}
        </div>

        {/* Identity */}
        <div style={{ background: '#1e293b', border: `1px solid ${level > 0 ? alertColor : '#334155'}`, borderRadius: 14, padding: 16, marginBottom: 12 }}>
          <div style={{ fontSize: 22, fontWeight: 800, marginBottom: 4 }}>{resident.name}</div>
          <div style={{ color: '#94a3b8', fontSize: 13 }}>Chambre {resident.room} · {resident.current_zone ?? 'zone ?'}</div>
          {resident.care_level && <div style={{ color: '#94a3b8', fontSize: 12, marginTop: 2 }}>Autonomie: {resident.care_level}</div>}
        </div>

        {/* Alert */}
        {alert && !alert.resolved && (
          <div style={{ background: level === 5 ? '#000' : '#1e293b', border: `2px solid ${level === 5 ? '#ff0000' : alertColor}`, borderRadius: 12, padding: 14, marginBottom: 12, color: level === 5 ? '#ff3333' : 'var(--text)' }}>
            <div style={{ fontWeight: 700, marginBottom: 6 }}>Alerte N{level}</div>
            <div style={{ fontSize: 13, lineHeight: 1.45 }}>{alert.reason}</div>
            {level === 5 && (
              <a href="tel:15" style={{ display: 'block', marginTop: 12, background: '#dc2626', color: '#fff', padding: '10px 16px', borderRadius: 10, textAlign: 'center', fontWeight: 800, fontSize: 16, textDecoration: 'none' }}>
                📞 SAMU 15
              </a>
            )}
          </div>
        )}

        {/* Vitals */}
        <div style={{ background: '#1e293b', borderRadius: 12, padding: 14, marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 10 }}>Constantes</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              { label: 'FC', value: v.heart_rate != null ? `${v.heart_rate} bpm` : '—' },
              { label: 'SpO2', value: v.spo2 != null ? `${v.spo2}%` : '—' },
              { label: 'PA', value: v.blood_pressure_sys != null ? `${v.blood_pressure_sys} mmHg` : '—' },
              { label: 'T°', value: v.temperature != null ? `${v.temperature.toFixed(1)}°C` : '—' },
              { label: 'FR', value: v.respiratory_rate != null ? `${v.respiratory_rate}/min` : '—' },
            ].map(item => (
              <div key={item.label} style={{ background: '#0f172a', borderRadius: 8, padding: '10px 12px' }}>
                <div style={{ fontSize: 11, color: '#64748b', marginBottom: 2 }}>{item.label}</div>
                <div style={{ fontSize: 18, fontWeight: 700 }}>{item.value}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Situation */}
        <div style={{ background: '#1e293b', borderRadius: 12, padding: 14, marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 10 }}>Situation</div>
          {[
            { label: 'Activité', value: resident.activity ?? '—' },
            { label: 'Zone', value: resident.current_zone ?? '—' },
            { label: 'Routine', value: resident.routine_label ?? '—' },
            { label: 'Risque ML', value: resident.ml_risk != null ? `${Math.round(resident.ml_risk * 100)}%` : '—' },
            { label: 'Soignant', value: (resident.assigned_caregiver ?? staffId) || '—' },
          ].map(item => (
            <div key={item.label} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: '1px solid #1e293b', fontSize: 13 }}>
              <span style={{ color: '#94a3b8' }}>{item.label}</span>
              <span style={{ fontWeight: 600 }}>{item.value}</span>
            </div>
          ))}
        </div>

        {/* Actions */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <button
            onClick={async () => { if (alert?.id) await fetch(`${BACKEND_HTTP}/api/alerts/${alert.id}/ack`, { method: 'POST', headers: staffToken ? { Authorization: `Bearer ${staffToken}` } : {} }); }}
            style={{ background: '#059669', color: '#fff', border: 0, borderRadius: 10, padding: '12px 16px', fontWeight: 700, cursor: 'pointer', fontSize: 14 }}
          >
            Acquitter alerte
          </button>
          <a
            href={`/resident/${id}${staffToken ? `?staff=${staffId}&token=${staffToken}` : ''}`}
            style={{ background: '#2563eb', color: '#fff', border: 0, borderRadius: 10, padding: '12px 16px', fontWeight: 700, fontSize: 14, textAlign: 'center', textDecoration: 'none', display: 'block' }}
          >
            DPI complet
          </a>
        </div>
      </div>
    </div>
  );
}
