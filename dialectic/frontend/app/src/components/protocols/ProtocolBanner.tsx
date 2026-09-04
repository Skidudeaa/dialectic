import { useState } from 'react';
import type { ProtocolState } from '../../types';
import './ProtocolBanner.css';

const PROTOCOL_NAMES: Record<string, string> = {
  steelman: 'Steelman',
  socratic: 'Socratic Descent',
  devil_advocate: "Devil's Advocate",
  synthesis: 'Synthesis',
};

const PHASE_NAMES: Record<string, string[]> = {
  steelman: ['Articulation', 'Strengthening', 'Stress Test', 'Verdict'],
  socratic: ['Opening Question', 'Deepening', 'Bedrock', 'Reflection'],
  devil_advocate: ['Claim Setup', 'Attack Vectors', 'Defense', 'Assessment'],
  synthesis: ['Position Mapping', 'Tension Points', 'Integration', 'Synthesis Statement'],
};

/* Mode glyphs — one 16px stroke figure per protocol, so the strip reads at a
   glance even before the name does (hue + icon + word, never hue alone). */
const PROTOCOL_GLYPHS: Record<string, React.ReactNode> = {
  steelman: (
    <path d="M8 1.6 L13.4 3.6 V7.8 C13.4 11.6 11 13.9 8 14.9 C5 13.9 2.6 11.6 2.6 7.8 V3.6 Z" />
  ),
  socratic: (
    <>
      <path d="M5.4 5.9 A2.6 2.6 0 1 1 9.3 8 C8.4 8.5 8 9.1 8 10.2" />
      <circle cx="8" cy="12.9" r="0.9" fill="currentColor" stroke="none" />
    </>
  ),
  devil_advocate: (
    <path d="M8 2.2 V13.8 M4 2.2 V5.6 A4 4 0 0 0 12 5.6 V2.2" />
  ),
  synthesis: (
    <>
      <path d="M2 3.4 L7 8 L2 12.6" />
      <path d="M7 8 H13.6 M11 5.4 L13.8 8 L11 10.6" />
    </>
  ),
};

interface ProtocolBannerProps {
  protocol: ProtocolState;
  onAdvance: (protocolId: string) => void;
  onAbort: (protocolId: string) => void;
}

export function ProtocolBanner({ protocol, onAdvance, onAbort }: ProtocolBannerProps) {
  const [concluded, setConcluded] = useState(false);

  if (protocol.status === 'concluded') {
    if (concluded) return null;
    return (
      <div className="protocol-concluded">
        <span>Protocol concluded — synthesis written to memory</span>
        <button className="dismiss-btn" onClick={() => setConcluded(true)}>Dismiss</button>
      </div>
    );
  }

  if (protocol.status === 'aborted') return null;

  const name = PROTOCOL_NAMES[protocol.protocol_type] ?? protocol.protocol_type;
  const phases = PHASE_NAMES[protocol.protocol_type] ?? [];
  const phaseName = phases[protocol.current_phase] ?? `Phase ${protocol.current_phase + 1}`;
  const progress = ((protocol.current_phase + 1) / protocol.total_phases) * 100;

  return (
    <div className="protocol-banner">
      <div className="protocol-banner-top">
        <div className="protocol-banner-info">
          <div className="protocol-icon" />
          <svg className="protocol-glyph" viewBox="0 0 16 16" aria-hidden="true">
            {PROTOCOL_GLYPHS[protocol.protocol_type] ?? null}
          </svg>
          <span className="protocol-name">{name}</span>
          <span className="protocol-phase">
            {phaseName} ({protocol.current_phase + 1}/{protocol.total_phases})
          </span>
        </div>
        <div className="protocol-banner-actions">
          {protocol.current_phase < protocol.total_phases - 1 && (
            <button className="advance-btn" onClick={() => onAdvance(protocol.id)}>
              Advance Phase
            </button>
          )}
          <button className="abort-btn" onClick={() => onAbort(protocol.id)}>Abort</button>
        </div>
      </div>
      <div className="protocol-progress">
        <div className="protocol-progress-fill" style={{ width: `${progress}%` }} />
      </div>
    </div>
  );
}
