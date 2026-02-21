import type { ConversationDNA } from '../../types';
import './DNAGlyph.css';

const ARCHETYPE_COLORS: Record<string, { fill: string; stroke: string; glow: string; text: string }> = {
  Crucible:   { fill: 'rgba(239,68,68,0.2)',   stroke: '#ef4444', glow: 'rgba(239,68,68,0.3)',   text: '#f87171' },
  'Deep Dive': { fill: 'rgba(59,130,246,0.2)', stroke: '#2563eb', glow: 'rgba(37,99,235,0.3)',   text: '#60a5fa' },
  Rhizome:    { fill: 'rgba(34,197,94,0.2)',    stroke: '#16a34a', glow: 'rgba(22,163,74,0.3)',   text: '#4ade80' },
  Symposium:  { fill: 'rgba(234,179,8,0.2)',    stroke: '#ca8a04', glow: 'rgba(202,138,4,0.3)',   text: '#facc15' },
  Forge:      { fill: 'rgba(245,158,11,0.2)',   stroke: '#f59e0b', glow: 'rgba(245,158,11,0.3)', text: '#fbbf24' },
  'Open Field': { fill: 'rgba(148,163,184,0.15)', stroke: '#64748b', glow: 'rgba(100,116,139,0.2)', text: '#94a3b8' },
};

const DEFAULT_COLORS = { fill: 'rgba(129,140,248,0.2)', stroke: '#818cf8', glow: 'rgba(99,102,241,0.3)', text: '#818cf8' };

const AXES: (keyof Pick<ConversationDNA, 'tension' | 'velocity' | 'asymmetry' | 'depth' | 'divergence' | 'memory_density'>)[] =
  ['tension', 'velocity', 'asymmetry', 'depth', 'divergence', 'memory_density'];

interface DNAGlyphProps {
  dna: ConversationDNA;
  size?: 'small' | 'large';
}

export function DNAGlyph({ dna, size = 'large' }: DNAGlyphProps) {
  const dim = size === 'small' ? 48 : 200;
  const cx = dim / 2;
  const cy = dim / 2;
  const radius = (dim / 2) * 0.78;

  const colors = ARCHETYPE_COLORS[dna.archetype] ?? DEFAULT_COLORS;

  const pointForAxis = (index: number, value: number) => {
    const angle = (Math.PI * 2 * index) / AXES.length - Math.PI / 2;
    const r = radius * Math.max(value, 0.05);
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  };

  const dataPoints = AXES.map((axis, i) => pointForAxis(i, dna[axis]));
  const dataPath = dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z';

  const gridLevels = [0.25, 0.5, 0.75, 1.0];

  return (
    <div className={`dna-glyph ${size}`} style={{ '--glyph-glow': colors.glow } as React.CSSProperties}>
      <svg width={dim} height={dim} viewBox={`0 0 ${dim} ${dim}`}>
        {/* Grid lines */}
        {gridLevels.map((level) => {
          const pts = AXES.map((_, i) => pointForAxis(i, level));
          const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ') + ' Z';
          return <path key={level} d={path} fill="none" stroke="var(--border-subtle)" strokeWidth={0.5} />;
        })}

        {/* Axis lines */}
        {AXES.map((_, i) => {
          const end = pointForAxis(i, 1);
          return <line key={i} x1={cx} y1={cy} x2={end.x} y2={end.y} stroke="var(--border-subtle)" strokeWidth={0.5} />;
        })}

        {/* Data polygon */}
        <path d={dataPath} fill={colors.fill} stroke={colors.stroke} strokeWidth={size === 'small' ? 1 : 1.5} />

        {/* Data points */}
        {size === 'large' && dataPoints.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={2.5} fill={colors.stroke} />
        ))}

        {/* Axis labels (large only) */}
        {size === 'large' && AXES.map((axis, i) => {
          const labelPos = pointForAxis(i, 1.18);
          return (
            <text
              key={axis}
              x={labelPos.x}
              y={labelPos.y}
              textAnchor="middle"
              dominantBaseline="middle"
              fill="var(--text-tertiary)"
              fontSize={9}
              fontFamily="Inter, sans-serif"
            >
              {axis.replace('_', ' ')}
            </text>
          );
        })}
      </svg>

      <span className="dna-fingerprint">{dna.fingerprint}</span>
      <span className="dna-archetype" style={{ color: colors.text }}>{dna.archetype}</span>
    </div>
  );
}
