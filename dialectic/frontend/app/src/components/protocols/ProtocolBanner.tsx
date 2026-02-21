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
