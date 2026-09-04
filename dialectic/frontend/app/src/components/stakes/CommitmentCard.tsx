import { useState } from 'react';
import { PARTICIPANT_NAME } from '../../lib/productIdentity.ts'
import type { Commitment } from '../../types';
import './CommitmentCard.css';

interface CommitmentCardProps {
  commitment: Commitment;
  onUpdateConfidence?: (commitmentId: string, confidence: number) => void;
  onResolve?: (commitmentId: string) => void;
}

type StampKind = 'hourglass' | 'check' | 'cross' | 'slash';

/** Rubber-stamp readout for a commitment's status: word + glyph + hue,
    never hue alone. */
const STATUS_STAMP: Record<Commitment['status'], { word: string; glyph: StampKind }> = {
  active:   { word: 'Pending', glyph: 'hourglass' },
  resolved: { word: 'Kept',    glyph: 'check' },
  expired:  { word: 'Missed',  glyph: 'cross' },
  voided:   { word: 'Void',    glyph: 'slash' },
};

export function StampGlyph({ kind, className }: { kind: StampKind; className?: string }) {
  const cls = className ?? 'stamp-glyph';
  if (kind === 'check') {
    return (
      <svg className={cls} viewBox="0 0 10 10" aria-hidden="true">
        <path d="M1.6 5.4 L4.1 7.9 L8.4 2.2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (kind === 'cross') {
    return (
      <svg className={cls} viewBox="0 0 10 10" aria-hidden="true">
        <path d="M2.2 2.2 L7.8 7.8 M7.8 2.2 L2.2 7.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === 'slash') {
    return (
      <svg className={cls} viewBox="0 0 10 10" aria-hidden="true">
        <circle cx="5" cy="5" r="3.3" fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d="M2.7 7.3 L7.3 2.7" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg className={cls} viewBox="0 0 10 10" aria-hidden="true">
      <path d="M2.6 1.4 H7.4 M2.6 8.6 H7.4 M3.2 1.4 C3.2 3.9 5 4.3 5 5 C5 5.7 3.2 6.1 3.2 8.6 M6.8 1.4 C6.8 3.9 5 4.3 5 5 C5 5.7 6.8 6.1 6.8 8.6" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}

function formatDeadline(deadline: string | null): { text: string; urgent: boolean } {
  if (!deadline) return { text: '', urgent: false };
  const deadlineDate = new Date(deadline);
  const now = new Date();
  const diff = deadlineDate.getTime() - now.getTime();
  const days = Math.ceil(diff / (1000 * 60 * 60 * 24));

  if (days < 0) return { text: `Expired ${Math.abs(days)}d ago`, urgent: true };
  if (days === 0) return { text: 'Due today', urgent: true };
  if (days === 1) return { text: 'Due tomorrow', urgent: true };
  if (days <= 3) return { text: `Due in ${days} days`, urgent: true };
  return { text: `Due ${deadlineDate.toLocaleDateString()}`, urgent: false };
}

export function CommitmentCard({ commitment, onUpdateConfidence, onResolve }: CommitmentCardProps) {
  const [sliderValue, setSliderValue] = useState(0.5);

  const deadline = formatDeadline(commitment.deadline);
  const isActive = commitment.status === 'active';
  const stamp = STATUS_STAMP[commitment.status];

  // Group latest confidence per user
  const latestConfidence = new Map<string, number>();
  for (const entry of commitment.confidence_history ?? []) {
    const key = entry.user_id ?? 'llm';
    latestConfidence.set(key, entry.confidence);
  }

  return (
    <div className="commitment-card" data-status={commitment.status}>
      <div className="commitment-card-header">
        <div className="commitment-claim">{commitment.claim}</div>
        <div className="commitment-badges">
          <span className={`status-badge ${commitment.status}`}>
            <StampGlyph kind={stamp.glyph} />
            <span className="stamp-word">{stamp.word}</span>
          </span>
          <span className="category-badge">{commitment.category}</span>
        </div>
      </div>

      {commitment.resolution_criteria && (
        <div className="commitment-criteria">{commitment.resolution_criteria}</div>
      )}

      {deadline.text && (
        <div className={`commitment-deadline${deadline.urgent ? ' urgent' : ''}`}>
          <svg className="due-glyph" viewBox="0 0 10 10" aria-hidden="true">
            <rect x="1.2" y="2" width="7.6" height="6.8" fill="none" stroke="currentColor" strokeWidth="1.1" />
            <path d="M1.2 4.3 H8.8 M3.3 1 V2.9 M6.7 1 V2.9" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
          </svg>
          {deadline.text}
        </div>
      )}

      {latestConfidence.size > 0 && (
        <div className="confidence-section">
          <h5>Confidence</h5>
          {Array.from(latestConfidence.entries()).map(([userId, conf]) => (
            <div className="confidence-bar-row" key={userId} data-owner={userId === 'llm' ? 'desk' : 'human'}>
              <span className="conf-label">{userId === 'llm' ? PARTICIPANT_NAME : userId.slice(0, 8)}</span>
              <div className="conf-track">
                <div className="conf-fill" style={{ width: `${conf * 100}%` }} />
              </div>
              <span className="conf-value">{(conf * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      )}

      {isActive && (
        <div className="commitment-actions">
          {onUpdateConfidence && (
            <div className="update-confidence">
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={sliderValue}
                onChange={(e) => setSliderValue(parseFloat(e.target.value))}
              />
              <span className="conf-display">{(sliderValue * 100).toFixed(0)}%</span>
              <button
                className="update-btn"
                onClick={() => onUpdateConfidence(commitment.id, sliderValue)}
              >
                Update
              </button>
            </div>
          )}
          {onResolve && (
            <button className="resolve-btn" onClick={() => onResolve(commitment.id)}>
              Resolve
            </button>
          )}
        </div>
      )}

      <span className="slip-serial" aria-hidden="true">№ {commitment.id.slice(0, 6).toUpperCase()}</span>
    </div>
  );
}
