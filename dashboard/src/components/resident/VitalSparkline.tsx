import { LineChart, Line, ResponsiveContainer, YAxis } from 'recharts';
import type { HistoryPoint } from '../../types';

interface Props {
  data: HistoryPoint[];
  color?: string;
  width?: number;
  height?: number;
}

export function VitalSparkline({ data, color = '#3b82f6', width = 60, height = 28 }: Props) {
  if (!data || data.length < 2) {
    return <span style={{ display: 'inline-block', width, height, opacity: 0.2, fontSize: 10 }}>—</span>;
  }

  const chartData = data.map(p => ({ v: p.v }));
  const values = data.map(p => p.v);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const domain: [number, number] = [min * 0.97, max * 1.03];

  return (
    <ResponsiveContainer width={width} height={height}>
      <LineChart data={chartData}>
        <YAxis domain={domain} hide />
        <Line
          type="monotone"
          dataKey="v"
          stroke={color}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
