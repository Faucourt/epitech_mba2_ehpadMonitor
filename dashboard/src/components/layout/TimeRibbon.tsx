import { useEffect, useState } from 'react';
import type { Resident } from '../../types';

interface Props {
  residents: Record<string, Resident>;
  simulatorSpeed: number;
}

export function TimeRibbon({ residents, simulatorSpeed }: Props) {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const ref = Object.values(residents).find(r => r.time_label) ?? Object.values(residents)[0];

  const hour = now.getHours();
  const shift = hour >= 7 && hour < 15 ? 'Matin 7h–15h'
    : hour >= 15 && hour < 22 ? 'Après-midi 15h–22h'
    : 'Nuit 22h–7h';

  const period = hour >= 6 && hour < 9 ? 'lever'
    : hour >= 9 && hour < 11 ? 'matin'
    : hour >= 11 && hour < 13 ? 'repas_midi'
    : hour >= 13 && hour < 15 ? 'sieste'
    : hour >= 15 && hour < 18 ? 'apres_midi'
    : hour >= 18 && hour < 20 ? 'repas_soir'
    : hour >= 20 && hour < 22 ? 'soiree'
    : 'nuit';

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
      gap: 10,
      padding: '10px 16px',
      borderBottom: '1px solid var(--border)',
      background: '#121826',
    }}>
      <TimeCard label="Heure réelle" value={now.toLocaleTimeString('fr-FR')} accent />
      <TimeCard label="Heure simulée" value={ref?.time_label ?? '--:--'} />
      <TimeCard label="Période" value={`${period} · x${simulatorSpeed}`} />
      <TimeCard label="Garde" value={shift} />
    </div>
  );
}

function TimeCard({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div style={{
      background: 'var(--bg2)',
      border: '1px solid var(--border)',
      borderRadius: 8,
      padding: '8px 10px',
    }}>
      <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.05em' }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: accent ? '#60a5fa' : 'var(--text)', marginTop: 2 }}>{value}</div>
    </div>
  );
}
