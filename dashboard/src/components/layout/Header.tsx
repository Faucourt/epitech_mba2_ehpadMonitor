interface Props {
  connected: boolean;
  residentCount: number;
  alertCount: number;
  criticalCount: number;
}

export function Header({ connected, residentCount, alertCount, criticalCount }: Props) {
  return (
    <header style={{
      background: 'var(--bg2)',
      borderBottom: '1px solid var(--border)',
      padding: '12px 20px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      zIndex: 100,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 18, fontWeight: 800, color: 'var(--blue)' }}>
        <BalloonLogo />
        <div>
          <span>EPicare Palace</span>
          <div style={{ fontSize: 10, fontWeight: 500, color: 'var(--text2)', marginTop: -2, letterSpacing: '.04em' }}>
            EHPAD · Monitoring temps réel
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
        <Stat label="Résidents" value={residentCount} color="var(--blue)" />
        <Stat label="Alertes" value={alertCount} color={alertCount > 0 ? 'var(--orange)' : 'var(--green)'} />
        <Stat label="Critiques" value={criticalCount} color={criticalCount > 0 ? 'var(--red)' : 'var(--green)'} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text2)' }}>
          <span style={{
            width: 10, height: 10, borderRadius: '50%',
            background: connected ? 'var(--green)' : 'var(--red)',
            display: 'inline-block',
            animation: connected ? 'pulse 2s infinite' : undefined,
          }} />
          {connected ? 'Connecté' : 'Déconnecté'}
        </div>
      </div>
    </header>
  );
}

function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--text2)' }}>{label}</div>
    </div>
  );
}

function BalloonLogo() {
  return (
    <div style={{ width: 36, height: 36, animation: 'balloon-float 3s ease-in-out infinite', flexShrink: 0 }}>
      <svg viewBox="0 0 36 50" fill="none">
        <ellipse cx="18" cy="16" rx="13" ry="15" fill="#3b82f6" opacity=".9" />
        <ellipse cx="18" cy="16" rx="7" ry="9" fill="white" opacity=".18" />
        <path d="M18 31 L16 34 L18 33 L20 34 Z" fill="#3b82f6" />
        <path d="M18 34 Q14 40 16 46" stroke="#64748b" strokeWidth="1.2" fill="none" />
      </svg>
    </div>
  );
}
