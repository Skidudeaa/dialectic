import { useAppStore } from '../../stores/appStore';
import type { Commitment } from '../../types';
import './CommitmentSurface.css';

interface CommitmentSurfaceProps {
  onViewCommitment?: (commitment: Commitment) => void;
}

export function CommitmentSurface({ onViewCommitment }: CommitmentSurfaceProps) {
  const surfaced = useAppStore((s) => s.surfacedCommitments);
  const setSurfaced = useAppStore((s) => s.setSurfacedCommitments);

  if (surfaced.length === 0) return null;

  const dismiss = (id: string) => {
    setSurfaced(surfaced.filter((c) => c.id !== id));
  };

  return (
    <div className="commitment-surface">
      {surfaced.map((commitment) => {
        const latestConf = commitment.confidence_history?.length
          ? commitment.confidence_history[commitment.confidence_history.length - 1]
          : null;

        return (
          <div className="surfaced-card" key={commitment.id}>
            <span className="surfaced-label">Related prediction</span>
            <span className="surfaced-claim">{commitment.claim}</span>
            {latestConf && (
              <span className="surfaced-confidence">
                Confidence: {(latestConf.confidence * 100).toFixed(0)}%
              </span>
            )}
            <div className="surfaced-actions">
              <button className="dismiss-btn" onClick={() => dismiss(commitment.id)}>Dismiss</button>
              {onViewCommitment && (
                <button className="view-btn" onClick={() => onViewCommitment(commitment)}>View</button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
