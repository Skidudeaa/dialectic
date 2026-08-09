import { useEffect } from 'react'
import './HelpDialog.css'

interface HelpDialogProps {
  onClose: () => void
}

export function HelpDialog({ onClose }: HelpDialogProps) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="help-overlay" onClick={onClose}>
      <div className="help-dialog" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true" aria-label="Help">
        <div className="help-dialog-header">
          <div>
            <h2>What can this room do?</h2>
            <p>You, the others, and Claude — a participant, not a chatbot.</p>
          </div>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close help">&times;</button>
        </div>

        <div className="help-body">
          <section className="help-section">
            <h3>The room</h3>
            <ul>
              <li><strong>@Claude</strong> gets an instant streamed reply. Without it, Claude jumps in on its own judgment.</li>
              <li>Room Settings → <strong>auto-interjection</strong> toggle makes Claude speak only when summoned.</li>
              <li>Mark a message <strong>Claim</strong>, <strong>Question</strong>, or <strong>Definition</strong> so its role matters.</li>
              <li><strong>Fork</strong> any message to branch — the fork inherits everything above it.</li>
              <li><strong>Memory</strong> is the shared brain. Restate a fact and it updates, keeping the old version's history.</li>
              <li><strong>Stakes</strong> tracks predictions: confidence updates, deadlines, calibration.</li>
              <li><strong>Protocols</strong> (Steelman, Socratic, Devil's Advocate, Synthesis) — Claude facilitates phases and writes conclusions to memory.</li>
              <li>The "new since you were here" line plus Claude's annotations catch you up.</li>
            </ul>
          </section>

          <section className="help-section">
            <h3>Claude's hands and eyes</h3>
            <ul>
              <li>Ask it to check reality — "what's oil at?", "any news on the thesis?", "run the what-if". It pulls live quotes, Polymarket, thesis state, headlines.</li>
              <li>Watch the "Claude is checking…" label while it works; expand the "used N tools" footer to audit every fetch.</li>
              <li>Paste or drag-drop a chart and ask about it — Claude sees images (not video).</li>
              <li>Ask and walk away: after 10 quiet minutes Claude follows up once (max 3/day, quiet 11pm–7am, off when the interjection toggle is off).</li>
              <li>Claude may draft a prediction — the <strong>Accept</strong> card is yours. Claude never writes to the desk itself.</li>
            </ul>
          </section>

          <section className="help-section">
            <h3>Trading rooms</h3>
            <ul>
              <li>Five live theses (Iran/Hormuz, Trump Tariffs, AI Capex, China Property, Japan Rates) fed into Claude's context within minutes.</li>
              <li>A <strong>critical</strong> node flip buzzes your pocket; warnings stay in-room.</li>
              <li><strong>Open Full Dashboard</strong> → td.somacura.org, no second login.</li>
            </ul>
          </section>

          <section className="help-section">
            <h3>The daily rhythm</h3>
            <ul>
              <li>7am CT <strong>Morning Brief</strong> in rooms that had activity: missed threads, unanswered questions, commitments due within 72h, thesis staleness — pushed to your phone.</li>
              <li>Tap the 🔔 chip once per device to enable notifications.</li>
            </ul>
          </section>

          <section className="help-section">
            <h3>Honest limits</h3>
            <ul>
              <li>Recalled facts can be stale — if a number matters, make Claude fetch it live.</li>
              <li>The fallback model can't see images or use tools, and says so.</li>
              <li>Claude takes no external actions. Your tap is the only write.</li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  )
}
