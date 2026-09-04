import { useAppStore } from '../../stores/appStore';
import type { Commitment } from '../../types';
import './CommitmentSurface.css';

interface CommitmentSurfaceProps {
  onViewCommitment?: (commitment: Commitment) => void;
}

type StampKind = 'hourglass' | 'check' | 'cross' | 'slash';

/** Compact stamp language, mirroring CommitmentCard's register stamps. */
const SURFACE_STAMP: Record<Commitment['status'], { word: string; glyph: StampKind }> = {
  active:   { word: 'Pending', glyph: 'hourglass' },
  resolved: { word: 'Kept',    glyph: 'check' },
  expired:  { word: 'Missed',  glyph: 'cross' },
  voided:   { word: 'Void',    glyph: 'slash' },
};

function SurfaceGlyph({ kind }: { kind: StampKind }) {
  if (kind === 'check') {
    return (
      <svg className="stamp-glyph" viewBox="0 0 10 10" aria-hidden="true">
        <path d="M1.6 5.4 L4.1 7.9 L8.4 2.2" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (kind === 'cross') {
    return (
      <svg className="stamp-glyph" viewBox="0 0 10 10" aria-hidden="true">
        <path d="M2.2 2.2 L7.8 7.8 M7.8 2.2 L2.2 7.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  if (kind === 'slash') {
    return (
      <svg className="stamp-glyph" viewBox="0 0 10 10" aria-hidden="true">
        <circle cx="5" cy="5" r="3.3" fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d="M2.7 7.3 L7.3 2.7" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg className="stamp-glyph" viewBox="0 0 10 10" aria-hidden="true">
      <path d="M2.6 1.4 H7.4 M2.6 8.6 H7.4 M3.2 1.4 C3.2 3.9 5 4.3 5 5 C5 5.7 3.2 6.1 3.2 8.6 M6.8 1.4 C6.8 3.9 5 4.3 5 5 C5 5.7 6.8 6.1 6.8 8.6" fill="none" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
    </svg>
  );
}

function surfaceDeadline(deadline: string | null): { text: string; urgent: boolean } {
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
        const stamp = SURFACE_STAMP[commitment.status];
        const due = surfaceDeadline(commitment.deadline);

        return (
          <div className="surfaced-card" key={commitment.id} data-status={commitment.status}>
            <div className="surfaced-top">
              <span className="surfaced-label">Related prediction</span>
              <span className={`surfaced-stamp ${commitment.status}`}>
                <SurfaceGlyph kind={stamp.glyph} />
                {stamp.word}
              </span>
            </div>
            <span className="surfaced-claim">{commitment.claim}</span>
            {latestConf && (
              <span className="surfaced-confidence">
                Confidence: {(latestConf.confidence * 100).toFixed(0)}%
              </span>
            )}
            {(commitment.resolution_criteria || due.text) && (
              <div className="surfaced-detail">
                {commitment.resolution_criteria && (
                  <span className="surfaced-criteria">{commitment.resolution_criteria}</span>
                )}
                {due.text && (
                  <span className={`surfaced-deadline${due.urgent ? ' urgent' : ''}`}>{due.text}</span>
                )}
              </div>
            )}
            <div className="surfaced-actions">
              <button className="dismiss-btn" onClick={() => dismiss(commitment.id)}>
                <svg className="btn-glyph" viewBox="0 0 10 10" aria-hidden="true">
                  <path d="M2.2 2.2 L7.8 7.8 M7.8 2.2 L2.2 7.8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                </svg>
                Dismiss
              </button>
              {onViewCommitment && (
                <button className="view-btn" onClick={() => onViewCommitment(commitment)}>
                  View
                  <svg className="btn-glyph" viewBox="0 0 10 10" aria-hidden="true">
                    <path d="M2 5 H8 M5.4 2.4 L8 5 L5.4 7.6" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
