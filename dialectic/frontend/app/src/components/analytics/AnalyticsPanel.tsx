import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import './AnalyticsPanel.css';

interface ThreadAnalytics {
  thread_id: string;
  total_messages: number;
  argument_density: number;
  question_resolution_rate: number;
  fork_count: number;
  memory_crystallizations: number;
  provoker_interventions: number;
  speaker_counts: Record<string, number>;
}

interface AnalyticsPanelProps {
  threadId?: string;
  roomId?: string;
}

const SPEAKER_COLORS: Record<string, string> = {
  human: 'var(--human-1)',
  llm_primary: 'var(--claude-primary)',
  llm_provoker: 'var(--claude-provoker)',
  llm_annotator: 'var(--claude-annotator)',
  system: 'var(--text-ghost)',
};

const SPEAKER_LABELS: Record<string, string> = {
  human: 'Human',
  llm_primary: 'Claude',
  llm_provoker: 'Provoker',
  llm_annotator: 'Annotator',
  system: 'System',
};

export function AnalyticsPanel({ threadId, roomId }: AnalyticsPanelProps) {
  const [data, setData] = useState<ThreadAnalytics | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!threadId && !roomId) return;
    setLoading(true);

    const fetchData = threadId
      ? api.getThreadAnalytics(threadId)
      : Promise.resolve(null);

    fetchData
      .then((result) => setData(result as ThreadAnalytics | null))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [threadId, roomId]);

  if (loading) {
    return (
      <div className="analytics-panel">
        <h3>Analytics</h3>
        <div className="analytics-loading">Loading analytics...</div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="analytics-panel">
        <h3>Analytics</h3>
        <div className="analytics-empty">No analytics data available yet.</div>
      </div>
    );
  }

  const maxCount = Math.max(...Object.values(data.speaker_counts ?? {}), 1);

  return (
    <div className="analytics-panel">
      <h3>Analytics</h3>

      <div className="analytics-grid">
        <div className="stat-card">
          <div className="stat-value">{data.total_messages}</div>
          <div className="stat-label">Messages</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{(data.argument_density * 100).toFixed(0)}%</div>
          <div className="stat-label">Arg Density</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{(data.question_resolution_rate * 100).toFixed(0)}%</div>
          <div className="stat-label">Q Resolution</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.memory_crystallizations}</div>
          <div className="stat-label">Memories</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.fork_count}</div>
          <div className="stat-label">Forks</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{data.provoker_interventions}</div>
          <div className="stat-label">Provocations</div>
        </div>
      </div>

      {data.speaker_counts && Object.keys(data.speaker_counts).length > 0 && (
        <div className="turn-balance">
          <h4>Turn Balance</h4>
          {Object.entries(data.speaker_counts).map(([speaker, count]) => (
            <div className="turn-bar" key={speaker}>
              <span className="turn-label">{SPEAKER_LABELS[speaker] ?? speaker}</span>
              <div className="turn-track">
                <div
                  className="turn-fill"
                  style={{
                    width: `${(count / maxCount) * 100}%`,
                    background: SPEAKER_COLORS[speaker] ?? 'var(--text-tertiary)',
                  }}
                />
              </div>
              <span className="turn-count">{count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
