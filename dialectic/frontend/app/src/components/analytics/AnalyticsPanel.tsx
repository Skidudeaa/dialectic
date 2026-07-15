import { useEffect, useState } from 'react';
import { api } from '../../lib/api';
import type { ConversationDNA } from '../../types';
import { DNAGlyph } from './DNAGlyph';
import './AnalyticsPanel.css';

interface ThreadAnalytics {
  thread_id: string;
  total_messages: number;
  argument_density: number;
  question_resolution_rate: number;
  fork_count: number;
  memory_crystallizations: number;
  provoker_interventions: number;
  turn_balance: Record<string, number>;
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
  const [dna, setDna] = useState<ConversationDNA | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!threadId && !roomId) return;

    const analyticsRequest = threadId
      ? api.getThreadAnalytics(threadId)
      : Promise.resolve(null);
    const dnaRequest = threadId
      ? api.getThreadDNA(threadId)
      : roomId
        ? api.getRoomDNA(roomId)
        : Promise.resolve(null);

    Promise.all([analyticsRequest, dnaRequest])
      .then(([result, dnaResult]) => {
        setData(result as ThreadAnalytics | null);
        setDna(dnaResult as ConversationDNA | null);
      })
      .catch(() => {
        setData(null);
        setDna(null);
      })
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

  const speakerCounts = data.turn_balance ?? {};
  const maxCount = Math.max(...Object.values(speakerCounts), 1);

  return (
    <div className="analytics-panel">
      <h3>Analytics</h3>

      {dna && <DNAGlyph dna={dna} />}

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

      {Object.keys(speakerCounts).length > 0 && (
        <div className="turn-balance">
          <h4>Turn Balance</h4>
          {Object.entries(speakerCounts).map(([speaker, count]) => (
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
