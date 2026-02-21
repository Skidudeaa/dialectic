import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { useAppStore } from '../../stores/appStore';
import type { Commitment } from '../../types';
import { CommitmentCard } from './CommitmentCard';
import './CommitmentDashboard.css';

type FilterTab = 'all' | 'active' | 'resolved' | 'expired';

interface CalibrationPoint {
  confidence: number;
  accuracy: number;
}

interface CommitmentDashboardProps {
  roomId: string;
  onCreateCommitment: (claim: string, criteria: string, category?: string) => void;
  onUpdateConfidence: (commitmentId: string, confidence: number) => void;
  onResolve?: (commitmentId: string) => void;
}

export function CommitmentDashboard({
  roomId,
  onCreateCommitment,
  onUpdateConfidence,
  onResolve,
}: CommitmentDashboardProps) {
  const [tab, setTab] = useState<FilterTab>('all');
  const [showCreate, setShowCreate] = useState(false);
  const [calibration, setCalibration] = useState<CalibrationPoint[]>([]);

  const commitments = useAppStore((s) => s.activeCommitments);

  // Form state
  const [claim, setClaim] = useState('');
  const [criteria, setCriteria] = useState('');
  const [category, setCategory] = useState<'prediction' | 'commitment' | 'bet'>('prediction');
  const [deadline, setDeadline] = useState('');
  const [initialConf, setInitialConf] = useState(0.5);

  useEffect(() => {
    api.getCommitments(roomId)
      .then((data) => useAppStore.getState().setActiveCommitments(data as Commitment[]))
      .catch(() => {});

    api.getCalibration(roomId)
      .then((data) => setCalibration((data as { points?: CalibrationPoint[] })?.points ?? []))
      .catch(() => {});
  }, [roomId]);

  const filtered = commitments.filter((c) => {
    if (tab === 'all') return true;
    if (tab === 'active') return c.status === 'active';
    if (tab === 'resolved') return c.status === 'resolved';
    if (tab === 'expired') return c.status === 'expired' || c.status === 'voided';
    return true;
  });

  const handleCreate = () => {
    if (!claim.trim()) return;
    onCreateCommitment(claim.trim(), criteria.trim(), category);
    setClaim('');
    setCriteria('');
    setCategory('prediction');
    setDeadline('');
    setInitialConf(0.5);
    setShowCreate(false);
  };

  return (
    <div className="commitment-dashboard">
      <h3>Predictions & Commitments</h3>

      <div className="commitment-tabs">
        {(['all', 'active', 'resolved', 'expired'] as FilterTab[]).map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {showCreate ? (
        <div className="commitment-create-form">
          <label>
            Claim
            <textarea value={claim} onChange={(e) => setClaim(e.target.value)} placeholder="What do you predict or commit to?" />
          </label>
          <label>
            Resolution criteria
            <textarea value={criteria} onChange={(e) => setCriteria(e.target.value)} placeholder="How will this be judged?" />
          </label>
          <div className="form-row">
            <label>
              Category
              <select value={category} onChange={(e) => setCategory(e.target.value as typeof category)}>
                <option value="prediction">Prediction</option>
                <option value="commitment">Commitment</option>
                <option value="bet">Bet</option>
              </select>
            </label>
            <label>
              Deadline
              <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
            </label>
          </div>
          <label>
            Initial confidence: {(initialConf * 100).toFixed(0)}%
            <input type="range" min={0} max={1} step={0.01} value={initialConf} onChange={(e) => setInitialConf(parseFloat(e.target.value))} />
          </label>
          <div className="form-actions">
            <button className="cancel-btn" onClick={() => setShowCreate(false)}>Cancel</button>
            <button className="submit-btn" disabled={!claim.trim()} onClick={handleCreate}>Create</button>
          </div>
        </div>
      ) : (
        <button className="new-commitment-btn" onClick={() => setShowCreate(true)}>
          + New Prediction
        </button>
      )}

      <div className="commitment-list">
        {filtered.length === 0 ? (
          <div className="commitment-empty">No {tab === 'all' ? '' : tab + ' '}commitments yet.</div>
        ) : (
          filtered.map((c) => (
            <CommitmentCard
              key={c.id}
              commitment={c}
              onUpdateConfidence={onUpdateConfidence}
              onResolve={onResolve}
            />
          ))
        )}
      </div>

      {calibration.length > 0 && (
        <div className="calibration-section">
          <h4>Calibration</h4>
          <CalibrationChart points={calibration} />
        </div>
      )}
    </div>
  );
}

function CalibrationChart({ points }: { points: CalibrationPoint[] }) {
  const w = 280;
  const h = 180;
  const pad = 28;
  const plotW = w - pad * 2;
  const plotH = h - pad * 2;

  const sorted = [...points].sort((a, b) => a.confidence - b.confidence);

  const toX = (v: number) => pad + v * plotW;
  const toY = (v: number) => pad + (1 - v) * plotH;

  const linePath = sorted.map((p, i) =>
    `${i === 0 ? 'M' : 'L'} ${toX(p.confidence)} ${toY(p.accuracy)}`
  ).join(' ');

  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      {/* Grid */}
      {[0, 0.25, 0.5, 0.75, 1].map((v) => (
        <line key={`h-${v}`} x1={pad} y1={toY(v)} x2={w - pad} y2={toY(v)} stroke="var(--border-subtle)" strokeWidth={0.5} />
      ))}
      {[0, 0.25, 0.5, 0.75, 1].map((v) => (
        <line key={`v-${v}`} x1={toX(v)} y1={pad} x2={toX(v)} y2={h - pad} stroke="var(--border-subtle)" strokeWidth={0.5} />
      ))}

      {/* Perfect calibration diagonal */}
      <line x1={toX(0)} y1={toY(0)} x2={toX(1)} y2={toY(1)} stroke="var(--text-ghost)" strokeWidth={1} strokeDasharray="4 3" />

      {/* Data line */}
      {sorted.length > 1 && (
        <path d={linePath} fill="none" stroke="var(--claude-primary)" strokeWidth={1.5} />
      )}

      {/* Data points */}
      {sorted.map((p, i) => (
        <circle key={i} cx={toX(p.confidence)} cy={toY(p.accuracy)} r={3} fill="var(--claude-primary)" />
      ))}

      {/* Axis labels */}
      <text x={w / 2} y={h - 4} textAnchor="middle" fontSize={9} fill="var(--text-tertiary)" fontFamily="Inter, sans-serif">Confidence</text>
      <text x={8} y={h / 2} textAnchor="middle" fontSize={9} fill="var(--text-tertiary)" fontFamily="Inter, sans-serif" transform={`rotate(-90 8 ${h / 2})`}>Accuracy</text>
    </svg>
  );
}
