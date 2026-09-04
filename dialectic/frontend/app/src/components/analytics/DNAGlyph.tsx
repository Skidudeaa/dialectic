import type { ConversationDNA } from '../../types';
import './DNAGlyph.css';

/* Archetype hues are read off the token set (styles/tokens.css) rather than a
   local hex ramp, so the glyph stays inside the Dark Roast band. The word is
   always printed under the glyph — hue is never the only signal. */
const ARCHETYPE_COLORS: Record<string, { fill: string; stroke: string; glow: string; text: string }> = {
  Crucible:   { fill: 'var(--scar-10)',   stroke: 'var(--color-error)',  glow: 'var(--scar-18)',  text: 'var(--color-error)' },
  'Deep Dive': { fill: 'var(--steel-12)', stroke: 'var(--color-steel)',  glow: 'var(--steel-30)', text: 'var(--color-steel)' },
  Rhizome:    { fill: 'var(--sage-12)',   stroke: 'var(--color-sage)',   glow: 'var(--sage-12)',  text: 'var(--color-sage)' },
  Symposium:  { fill: 'var(--gold-12)',   stroke: 'var(--color-gold)',   glow: 'var(--gold-12)',  text: 'var(--color-gold)' },
  Forge:      { fill: 'var(--amber-08)',  stroke: 'var(--color-amber)',  glow: 'var(--amber-18)', text: 'var(--color-amber)' },
  'Open Field': { fill: 'transparent',    stroke: 'var(--color-faint)',  glow: 'transparent',     text: 'var(--color-faint)' },
};

const DEFAULT_COLORS = { fill: 'var(--plum-12)', stroke: 'var(--color-plum)', glow: 'var(--plum-12)', text: 'var(--color-plum)' };

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
              fontFamily="var(--font-mono)"
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
