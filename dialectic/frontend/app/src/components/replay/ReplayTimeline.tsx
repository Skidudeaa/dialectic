import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../../lib/api';
import './ReplayTimeline.css';

interface TimelineBucket {
  start: string;
  end: string;
  count: number;
}

interface TimelineData {
  buckets: TimelineBucket[];
  total_events: number;
  start_time: string;
  end_time: string;
}

interface ReplayTimelineProps {
  roomId: string;
  onSeek?: (timestamp: string) => void;
}

const SPEEDS = [1, 2, 4, 8];

export function ReplayTimeline({ roomId, onSeek }: ReplayTimelineProps) {
  const [timeline, setTimeline] = useState<TimelineData | null>(null);
  const [loading, setLoading] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [position, setPosition] = useState(0); // 0-1
  const trackRef = useRef<HTMLDivElement>(null);
  const playTimerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    setLoading(true);
    api.getTimeline(roomId)
      .then((data) => setTimeline(data as TimelineData))
      .catch(() => setTimeline(null))
      .finally(() => setLoading(false));
  }, [roomId]);

  // Playback
  useEffect(() => {
    if (playing && timeline) {
      playTimerRef.current = setInterval(() => {
        setPosition((prev) => {
          const next = prev + (0.002 * speed);
          if (next >= 1) {
            setPlaying(false);
            return 1;
          }
          return next;
        });
      }, 50);
    } else {
      clearInterval(playTimerRef.current);
    }
    return () => clearInterval(playTimerRef.current);
  }, [playing, speed, timeline]);

  // Notify parent on position change
  useEffect(() => {
    if (!timeline || !onSeek) return;
    const start = new Date(timeline.start_time).getTime();
    const end = new Date(timeline.end_time).getTime();
    const ts = new Date(start + (end - start) * position).toISOString();
    onSeek(ts);
  }, [position, timeline, onSeek]);

  const handleTrackClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    setPosition(x);
  }, []);

  if (loading) {
    return <div className="replay-timeline"><div className="replay-loading">Loading timeline...</div></div>;
  }

  if (!timeline || !timeline.buckets?.length) {
    return <div className="replay-timeline"><div className="replay-loading">No replay data available.</div></div>;
  }

  const maxCount = Math.max(...timeline.buckets.map((b) => b.count), 1);
  const currentTs = (() => {
    const start = new Date(timeline.start_time).getTime();
    const end = new Date(timeline.end_time).getTime();
    return new Date(start + (end - start) * position);
  })();

  return (
    <div className="replay-timeline">
      <div className="replay-controls">
        <button className="play-btn" onClick={() => setPlaying(!playing)}>
          {playing ? '\u275A\u275A' : '\u25B6'}
        </button>
        <span className="replay-timestamp">{currentTs.toLocaleString()}</span>
        <div className="speed-selector">
          {SPEEDS.map((s) => (
            <button key={s} className={speed === s ? 'active' : ''} onClick={() => setSpeed(s)}>
              {s}x
            </button>
          ))}
        </div>
      </div>

      <div className="replay-track-container" ref={trackRef} onClick={handleTrackClick}>
        <div className="replay-heatmap">
          {timeline.buckets.map((bucket, i) => {
            const intensity = bucket.count / maxCount;
            // Gradient from blue (sparse) to red (dense)
            const r = Math.round(59 + intensity * 180);
            const g = Math.round(130 - intensity * 100);
            const b = Math.round(246 - intensity * 175);
            return (
              <div
                key={i}
                className="heatmap-bar"
                style={{
                  background: `rgb(${r}, ${g}, ${b})`,
                  opacity: 0.3 + intensity * 0.7,
                }}
              />
            );
          })}
        </div>
        <div className="replay-thumb" style={{ left: `${position * 100}%` }} />
      </div>
    </div>
  );
}
