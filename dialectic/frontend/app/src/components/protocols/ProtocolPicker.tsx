import { useState } from 'react';
import './ProtocolPicker.css';

interface ProtocolDef {
  type: 'steelman' | 'socratic' | 'devil_advocate' | 'synthesis';
  name: string;
  description: string;
  phases: string[];
  needsClaim: boolean;
}

const PROTOCOLS: ProtocolDef[] = [
  {
    type: 'steelman',
    name: 'Steelman',
    description: 'Strengthen an argument by finding its best possible formulation before critiquing.',
    phases: ['Articulation', 'Strengthening', 'Stress Test', 'Verdict'],
    needsClaim: true,
  },
  {
    type: 'socratic',
    name: 'Socratic Descent',
    description: 'Drill into assumptions with layered questioning until foundational beliefs surface.',
    phases: ['Opening Question', 'Deepening', 'Bedrock', 'Reflection'],
    needsClaim: false,
  },
  {
    type: 'devil_advocate',
    name: "Devil's Advocate",
    description: 'Systematically attack a claim from every angle to expose weaknesses.',
    phases: ['Claim Setup', 'Attack Vectors', 'Defense', 'Assessment'],
    needsClaim: true,
  },
  {
    type: 'synthesis',
    name: 'Synthesis',
    description: 'Merge divergent positions into a higher-order understanding.',
    phases: ['Position Mapping', 'Tension Points', 'Integration', 'Synthesis Statement'],
    needsClaim: false,
  },
];

interface ProtocolPickerProps {
  onInvoke: (type: string, config: Record<string, unknown>) => void;
  onClose: () => void;
}

export function ProtocolPicker({ onInvoke, onClose }: ProtocolPickerProps) {
  const [selected, setSelected] = useState<ProtocolDef | null>(null);
  const [claim, setClaim] = useState('');

  const canInvoke = selected && (!selected.needsClaim || claim.trim().length > 0);

  const handleInvoke = () => {
    if (!selected || !canInvoke) return;
    const config: Record<string, unknown> = {};
    if (selected.needsClaim) {
      config.target_claim = claim.trim();
    }
    onInvoke(selected.type, config);
    onClose();
  };

  return (
    <div className="protocol-picker-overlay" onClick={onClose}>
      <div className="protocol-picker" onClick={(e) => e.stopPropagation()}>
        <h2>Invoke Thinking Protocol</h2>
        <p className="picker-subtitle">Choose a structured reasoning protocol for the conversation.</p>

        <div className="protocol-grid">
          {PROTOCOLS.map((p) => (
            <div
              key={p.type}
              className={`protocol-card${selected?.type === p.type ? ' selected' : ''}`}
              onClick={() => { setSelected(p); setClaim(''); }}
            >
              <h3>{p.name}</h3>
              <p className="card-desc">{p.description}</p>
              <div className="card-phases">
                {p.phases.map((phase, i) => (
                  <span key={i} className="phase-tag">{phase}</span>
                ))}
              </div>
            </div>
          ))}
        </div>

        {selected?.needsClaim && (
          <div className="protocol-config">
            <label>Target claim to examine</label>
            <textarea
              value={claim}
              onChange={(e) => setClaim(e.target.value)}
              placeholder="Enter the claim or argument to analyze..."
            />
          </div>
        )}

        <div className="protocol-actions">
          <button className="cancel-btn" onClick={onClose}>Cancel</button>
          <button className="invoke-btn" disabled={!canInvoke} onClick={handleInvoke}>
            Invoke {selected?.name ?? 'Protocol'}
          </button>
        </div>
      </div>
    </div>
  );
}
