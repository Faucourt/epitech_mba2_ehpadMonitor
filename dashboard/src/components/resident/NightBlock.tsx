import type { Resident } from '../../types';

interface Props { r: Resident; }

export function NightBlock({ r }: Props) {
  const isNight = ['nuit', 'coucher', 'sieste'].includes(r.time_of_day ?? '');
  const m = r.movement ?? {};
  if (!isNight && !m.is_sleeping) return null;

  const inactMin = Math.round((m.last_movement_ago_s ?? 0) / 60);
  const isFall = m.is_fall_detected;
  const isErrance = r.movement_scenario === 'errance_nuit' || r.current_zone === 'hors_ehpad';
  const inRoom = !r.current_zone || r.current_zone.startsWith('ch') || r.current_zone === 'chambre';

  let sleepLabel: string;
  let sleepColor: string;
  if (isFall)             { sleepLabel = '⚠ Chute';             sleepColor = '#ef4444'; }
  else if (isErrance)     { sleepLabel = '⚠ Errance';           sleepColor = '#f97316'; }
  else if (!inRoom)       { sleepLabel = 'Hors chambre';         sleepColor = '#f59e0b'; }
  else if (m.is_sleeping) { sleepLabel = 'Dort';                 sleepColor = '#818cf8'; }
  else if (inactMin > 90) { sleepLabel = `Immobile ${inactMin}min`; sleepColor = '#f59e0b'; }
  else                    { sleepLabel = 'Éveillé';              sleepColor = '#10b981'; }

  const pathologies = r.pathologies ?? r.profile?.pathologies ?? [];
  const spo2Thr = pathologies.includes('bpco') ? '89%' : '91%';
  const locationTxt = r.current_zone === 'hors_ehpad'
    ? '⚠ HORS EHPAD'
    : !inRoom ? `Zone: ${r.current_zone}` : 'En chambre';

  return (
    <div style={{
      marginTop: 7,
      padding: '6px 8px 5px',
      borderTop: '1px solid rgba(99,102,241,0.35)',
      background: 'rgba(30,27,75,0.45)',
      borderRadius: '0 0 6px 6px',
      marginLeft: -8,
      marginRight: -8,
      marginBottom: -8,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 3 }}>
        <span style={{ fontSize: 11 }}>🌙</span>
        <span style={{ fontSize: 10, fontWeight: 700, color: '#818cf8', letterSpacing: '.03em' }}>MODE NUIT</span>
        <span style={{ fontSize: 10, fontWeight: 600, color: sleepColor, marginLeft: 'auto' }}>{sleepLabel}</span>
      </div>
      <div style={{ fontSize: 10, color: 'var(--text2)' }}>
        Inactivité: {inactMin} min · {locationTxt}
      </div>
      <div style={{ fontSize: 10, color: '#6366f1', marginTop: 2 }}>
        Seuil SpO2 nuit: {spo2Thr} · SOS: {m.sos_pressed ? '⚠ ACTIF' : 'inactif'}
      </div>
      {isErrance && (
        <div style={{ fontSize: 10, color: '#f97316', fontWeight: 700, marginTop: 2 }}>
          ⚠ Errance nocturne détectée
        </div>
      )}
    </div>
  );
}
