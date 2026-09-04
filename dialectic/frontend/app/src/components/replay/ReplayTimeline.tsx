import { useEffect, useState, useRef, useCallback } from 'react';
import { api } from '../../lib/api';
import './ReplayTimeline.css';

interface TimelineBucket {
  start_sequence: number;
  end_sequence: number;
  start_time: string;
  end_time: string;
  event_count: number;
  event_types: Record<string, number>;
}

interface ReplayTimelineProps {
  roomId: string;
  onSeek?: (timestamp: string) => void;
}

const SPEEDS = [1, 2, 4, 8];

export function ReplayTimeline({ roomId, onSeek }: ReplayTimelineProps) {
  const [timeline, setTimeline] = useState<TimelineBucket[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [position, setPosition] = useState(0); // 0-1
  const [hoverPos, setHoverPos] = useState<number | null>(null); // 0-1, cursor over the track
  const trackRef = useRef<HTMLDivElement>(null);
  const playTimerRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    api.getTimeline(roomId)
      .then((data) => setTimeline(data as TimelineBucket[]))
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
    if (timeline.length === 0) return;
    const start = new Date(timeline[0].start_time).getTime();
    const end = new Date(timeline[timeline.length - 1].end_time).getTime();
    const ts = new Date(start + (end - start) * position).toISOString();
    onSeek(ts);
  }, [position, timeline, onSeek]);

  const handleTrackClick = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    setPosition(x);
  }, []);

  const handleTrackHover = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!trackRef.current) return;
    const rect = trackRef.current.getBoundingClientRect();
    setHoverPos(Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)));
  }, []);

  if (loading) {
    return <div className="replay-timeline"><div className="replay-loading">Loading timeline...</div></div>;
  }

  if (!timeline?.length) {
    return <div className="replay-timeline"><div className="replay-loading">No replay data available.</div></div>;
  }

  const maxCount = Math.max(...timeline.map((b) => b.event_count), 1);
  const timeAt = (pos: number) => {
    const start = new Date(timeline[0].start_time).getTime();
    const end = new Date(timeline[timeline.length - 1].end_time).getTime();
    return new Date(start + (end - start) * pos);
  };
  const currentTs = timeAt(position);

  return (
    <div className="replay-timeline">
      <div className="replay-controls">
        <button
          className={`play-btn${playing ? ' is-playing' : ''}`}
          onClick={() => setPlaying(!playing)}
          aria-label={playing ? 'Pause replay' : 'Play replay'}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <span className="replay-timestamp">{currentTs.toLocaleString()}</span>
        <div className="speed-selector" role="group" aria-label="Replay speed">
          {SPEEDS.map((s) => (
            <button
              key={s}
              className={speed === s ? 'active' : ''}
              aria-pressed={speed === s}
              onClick={() => setSpeed(s)}
            >
              {s}x
            </button>
          ))}
        </div>
      </div>

      <div
        className="replay-track-container"
        ref={trackRef}
        onClick={handleTrackClick}
        onMouseMove={handleTrackHover}
        onMouseLeave={() => setHoverPos(null)}
      >
        <div className="replay-heatmap">
          {timeline.map((bucket, i) => {
            const intensity = bucket.event_count / maxCount;
            // Warm ramp: dark bean (sparse) climbing to lit amber (dense) —
            // density reads as heat on the chassis; hue is paired with the
            // opacity step, never carried by color alone.
            const r = Math.round(78 + intensity * 164);
            const g = Math.round(56 + intensity * 106);
            const b = Math.round(38 + intensity * 36);
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
        <div className="replay-thumb" style={{ left: `${position * 100}%` }} aria-hidden="true" />
        {hoverPos !== null && (
          <div className="replay-hover-tip" style={{ left: `${hoverPos * 100}%` }}>
            {timeAt(hoverPos).toLocaleTimeString()}
          </div>
        )}
      </div>
      <div className="replay-ticks" aria-hidden="true" />
    </div>
  );
}
