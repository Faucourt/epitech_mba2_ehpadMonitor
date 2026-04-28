import { ALERT_COLORS, ALERT_LABELS } from '../../types';
import type { Alert } from '../../types';

const BACKEND_HTTP = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8001`;

interface Props {
  alerts: Alert[];
  onSelectResident: (id: string) => void;
}

export function AlertsSidebar({ alerts, onSelectResident }: Props) {
  const sorted = [...alerts].sort((a, b) => b.level - a.level || new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  async function ack(alertId: string, e: React.MouseEvent) {
    e.stopPropagation();
    try {
      await fetch(`${BACKEND_HTTP}/api/alerts/${alertId}/ack`, { method: 'POST' });
    } catch { /* ignore */ }
  }

  if (sorted.length === 0) {
    return (
      <div style={{ padding: '16px 12px', color: 'var(--text3)', fontSize: 12, textAlign: 'center' }}>
        ✓ Aucune alerte active
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 8 }}>
      {sorted.map(alert => {
        const color = ALERT_COLORS[alert.level] ?? '#94a3b8';
        const isN5 = alert.level === 5;
        const since = alert.time_since_s != null
          ? alert.time_since_s < 60 ? `${alert.time_since_s}s` : `${Math.round(alert.time_since_s / 60)}min`
          : '';

        return (
          <div
            key={alert.id}
            onClick={() => onSelectResident(alert.resident_id)}
            style={{
              background: isN5 ? '#000' : `${color}18`,
              border: `1px solid ${isN5 ? '#ff0000' : color}`,
              borderRadius: 8,
              padding: '8px 10px',
              cursor: 'pointer',
              color: isN5 ? '#ff3333' : 'var(--text)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 3 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: isN5 ? '#ff3333' : color }}>
                N{alert.level} {ALERT_LABELS[alert.level]}
              </span>
              <span style={{ fontSize: 10, color: isN5 ? '#ff5555' : 'var(--text3)' }}>{since}</span>
            </div>
            <div style={{ fontSize: 12, fontWeight: 700 }}>{alert.resident_name}</div>
            <div style={{ fontSize: 11, color: isN5 ? '#ff5555' : 'var(--text2)', lineHeight: 1.35, marginTop: 2 }}>{alert.reason}</div>
            {isN5 && (
              <div style={{ marginTop: 6 }}>
                <a href="tel:15" style={{ background: '#dc2626', color: '#fff', padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 700 }}>
                  📞 SAMU 15
                </a>
              </div>
            )}
            {!alert.acknowledged && (
              <button
                onClick={e => ack(alert.id, e)}
                style={{ marginTop: 6, fontSize: 10, padding: '3px 8px', background: 'var(--bg3)', color: 'var(--text2)' }}
              >
                Acquitter
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
