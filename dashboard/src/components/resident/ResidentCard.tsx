import { ALERT_COLORS } from '../../types';
import type { Resident, Alert, HistoryBuffer } from '../../types';
import { VitalSparkline } from './VitalSparkline';
import { NightBlock } from './NightBlock';

interface Props {
  resident: Resident;
  alert?: Alert;
  history?: HistoryBuffer;
  onClick: () => void;
}

function vitalColor(type: string, val: number): string {
  const ranges: Record<string, { ok: [number, number]; warn: [number, number] }> = {
    heart_rate: { ok: [50, 100], warn: [40, 130] },
    spo2: { ok: [95, 100], warn: [90, 94] },
    blood_pressure_sys: { ok: [90, 159], warn: [80, 179] },
    temperature: { ok: [36, 37.9], warn: [37.9, 39.5] },
  };
  const r = ranges[type];
  if (!r) return 'var(--text)';
  if (val >= r.ok[0] && val <= r.ok[1]) return 'var(--green)';
  if (val >= r.warn[0] && val <= r.warn[1]) return 'var(--yellow)';
  return 'var(--red)';
}

export function ResidentCard({ resident: r, alert, history, onClick }: Props) {
  const level = alert && !alert.resolved ? alert.level : 0;
  const v = r.vitals ?? {};
  const mlRisk = r.ml_risk ?? 0;
  const isN5 = level === 5;

  const cardStyle: React.CSSProperties = {
    background: isN5 ? '#000' : level >= 4 ? '#1a0a0a' : level >= 3 ? '#1a140a' : level >= 2 ? '#1a1900' : level >= 1 ? '#0a1220' : 'var(--bg2)',
    border: `1px solid ${isN5 ? '#ff0000' : level > 0 ? ALERT_COLORS[level] : 'var(--border)'}`,
    borderRadius: 10,
    padding: 8,
    cursor: 'pointer',
    transition: 'transform .15s, box-shadow .15s',
    color: isN5 ? '#ff3333' : 'var(--text)',
    boxShadow: level >= 4 ? `0 0 16px ${ALERT_COLORS[level]}44` : undefined,
    position: 'relative',
  };

  const alertColor = ALERT_COLORS[level] ?? 'transparent';

  return (
    <div style={cardStyle} onClick={onClick}>
      {level > 0 && (
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0,
          height: 3, borderRadius: '10px 10px 0 0',
          background: isN5 ? '#ff0000' : alertColor,
        }} />
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13, color: isN5 ? '#ff3333' : 'var(--text)' }}>
            {r.name}
          </div>
          <div style={{ fontSize: 10, color: isN5 ? '#ff5555' : 'var(--text3)' }}>
            Ch. {r.room} · {r.current_zone || 'zone ?'}
          </div>
        </div>
        {level > 0 && (
          <span style={{
            fontSize: 10, fontWeight: 700,
            padding: '2px 7px', borderRadius: 999,
            background: isN5 ? '#000' : `${alertColor}22`,
            color: isN5 ? '#ff3333' : alertColor,
            border: `1px solid ${isN5 ? '#ff0000' : alertColor}`,
          }}>
            N{level}
          </span>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 8px', fontSize: 11 }}>
        {v.heart_rate != null && (
          <div style={{ color: vitalColor('heart_rate', v.heart_rate) }}>
            ♥ {v.heart_rate} bpm
          </div>
        )}
        {v.spo2 != null && (
          <div style={{ color: vitalColor('spo2', v.spo2) }}>
            SpO2 {v.spo2}%
          </div>
        )}
        {v.blood_pressure_sys != null && (
          <div style={{ color: vitalColor('blood_pressure_sys', v.blood_pressure_sys) }}>
            PA {v.blood_pressure_sys}
          </div>
        )}
        {v.temperature != null && (
          <div style={{ color: vitalColor('temperature', v.temperature) }}>
            T° {v.temperature?.toFixed(1)}
          </div>
        )}
      </div>

      {history && (
        <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
          <VitalSparkline data={history.hr} color="#ef4444" width={55} height={22} />
          <VitalSparkline data={history.spo2} color="#3b82f6" width={55} height={22} />
        </div>
      )}

      {mlRisk > 0.25 && (
        <div style={{ fontSize: 10, color: mlRisk > 0.75 ? 'var(--red)' : mlRisk > 0.5 ? 'var(--orange)' : 'var(--yellow)', marginTop: 3 }}>
          Risque ML {Math.round(mlRisk * 100)}%
        </div>
      )}

      {alert && !alert.resolved && (
        <div style={{ fontSize: 10, color: isN5 ? '#ff5555' : alertColor, marginTop: 4, lineHeight: 1.35 }}>
          {alert.reason}
        </div>
      )}

      <NightBlock r={r} />
    </div>
  );
}
