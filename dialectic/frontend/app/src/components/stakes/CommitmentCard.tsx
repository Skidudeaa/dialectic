import { useState } from 'react';
import type { Commitment } from '../../types';
import './CommitmentCard.css';

interface CommitmentCardProps {
  commitment: Commitment;
  onUpdateConfidence?: (commitmentId: string, confidence: number) => void;
  onResolve?: (commitmentId: string) => void;
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

  // Group latest confidence per user
  const latestConfidence = new Map<string, number>();
  for (const entry of commitment.confidence_history ?? []) {
    const key = entry.user_id ?? 'llm';
    latestConfidence.set(key, entry.confidence);
  }

  return (
    <div className="commitment-card">
      <div className="commitment-card-header">
        <div className="commitment-claim">{commitment.claim}</div>
        <div className="commitment-badges">
          <span className={`status-badge ${commitment.status}`}>{commitment.status}</span>
          <span className="category-badge">{commitment.category}</span>
        </div>
      </div>

      {commitment.resolution_criteria && (
        <div className="commitment-criteria">{commitment.resolution_criteria}</div>
      )}

      {deadline.text && (
        <div className={`commitment-deadline${deadline.urgent ? ' urgent' : ''}`}>
          {deadline.text}
        </div>
      )}

      {latestConfidence.size > 0 && (
        <div className="confidence-section">
          <h5>Confidence</h5>
          {Array.from(latestConfidence.entries()).map(([userId, conf]) => (
            <div className="confidence-bar-row" key={userId}>
              <span className="conf-label">{userId === 'llm' ? 'Claude' : userId.slice(0, 8)}</span>
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
    </div>
  );
}
