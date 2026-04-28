import { useEffect } from 'react';
import { ALERT_COLORS } from '../../types';

export interface ToastData {
  id: string;
  level: number;
  residentName: string;
  reason: string;
}

interface Props {
  toasts: ToastData[];
  onDismiss: (id: string) => void;
}

export function ToastContainer({ toasts, onDismiss }: Props) {
  return (
    <div style={{
      position: 'fixed',
      top: 16,
      right: 16,
      zIndex: 1000,
      display: 'flex',
      flexDirection: 'column',
      gap: 8,
      maxWidth: 320,
    }}>
      {toasts.map(t => (
        <Toast key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function Toast({ toast: t, onDismiss }: { toast: ToastData; onDismiss: (id: string) => void }) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(t.id), 8000);
    return () => clearTimeout(timer);
  }, [t.id, onDismiss]);

  const isN5 = t.level === 5;
  const color = ALERT_COLORS[t.level] ?? '#94a3b8';

  return (
    <div
      style={{
        background: isN5 ? '#000' : 'var(--bg2)',
        border: `1px solid ${isN5 ? '#ff0000' : color}`,
        borderLeft: `4px solid ${isN5 ? '#ff0000' : color}`,
        borderRadius: 8,
        padding: '10px 14px',
        color: isN5 ? '#ff3333' : 'var(--text)',
        animation: 'slideIn .3s ease',
        cursor: 'pointer',
        fontWeight: isN5 ? 700 : 400,
      }}
      onClick={() => onDismiss(t.id)}
    >
      <div style={{ fontSize: 11, fontWeight: 700, color: isN5 ? '#ff3333' : color, marginBottom: 3 }}>
        N{t.level} — {t.residentName}
      </div>
      <div style={{ fontSize: 12 }}>{t.reason}</div>
    </div>
  );
}
