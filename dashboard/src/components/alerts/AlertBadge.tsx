import { ALERT_COLORS, ALERT_LABELS } from '../../types';

interface Props {
  level: number;
  size?: 'sm' | 'md';
}

export function AlertBadge({ level, size = 'md' }: Props) {
  if (level === 0) return null;
  const color = ALERT_COLORS[level] ?? '#94a3b8';
  const label = ALERT_LABELS[level] ?? `N${level}`;
  const isN5 = level === 5;

  const style: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: size === 'sm' ? '2px 7px' : '3px 10px',
    borderRadius: 999,
    fontSize: size === 'sm' ? 10 : 12,
    fontWeight: 700,
    background: isN5 ? '#000' : `${color}22`,
    color: isN5 ? '#ff3333' : color,
    border: `1px solid ${isN5 ? '#ff0000' : color}`,
    letterSpacing: '.03em',
  };

  return (
    <span style={style}>
      N{level} {label}
    </span>
  );
}
