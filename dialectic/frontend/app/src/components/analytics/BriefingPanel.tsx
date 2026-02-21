import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import './BriefingPanel.css';

interface BriefingData {
  summary: string;
  messages_missed: number;
  memories_created: number;
  threads_forked: number;
  highlights: { content: string; speaker_type: string }[];
}

interface BriefingPanelProps {
  roomId: string;
  userId: string;
  onDismiss: () => void;
}

export function BriefingPanel({ roomId, userId, onDismiss }: BriefingPanelProps) {
  const [briefing, setBriefing] = useState<BriefingData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getBriefing(roomId, userId)
      .then((data) => setBriefing(data as BriefingData))
      .catch(() => setBriefing(null))
      .finally(() => setLoading(false));
  }, [roomId, userId]);

  if (loading) {
    return (
      <div className="briefing-panel">
        <div className="briefing-loading">Preparing your briefing...</div>
      </div>
    );
  }

  if (!briefing) return null;

  return (
    <div className="briefing-panel">
      <div className="briefing-header">
        <h3>Welcome Back</h3>
        <button className="dismiss-btn" onClick={onDismiss}>&times;</button>
      </div>

      <div className="briefing-summary">{briefing.summary}</div>

      <div className="briefing-stats">
        <div className="briefing-stat">
          <div className="stat-value">{briefing.messages_missed}</div>
          <div className="stat-label">Messages</div>
        </div>
        <div className="briefing-stat">
          <div className="stat-value">{briefing.memories_created}</div>
          <div className="stat-label">Memories</div>
        </div>
        <div className="briefing-stat">
          <div className="stat-value">{briefing.threads_forked}</div>
          <div className="stat-label">Forks</div>
        </div>
      </div>

      {briefing.highlights?.length > 0 && (
        <div className="briefing-highlights">
          <h4>Key moments</h4>
          {briefing.highlights.map((h, i) => (
            <div className="highlight-card" key={i}>{h.content}</div>
          ))}
        </div>
      )}
    </div>
  );
}
