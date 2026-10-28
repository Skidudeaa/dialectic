import { Suspense, useState } from 'react'
import { createRoot } from 'react-dom/client'
import Chart, { JourneyStrip, LegCard, SeasonStrip } from '../index'
import { projection } from '../fixtures/projection'
import './preview.css'

export default function Preview() {
  const [selected, setSelected] = useState<string | null>(null)
  const [leg, setLeg] = useState(0)
  const [myth, setMyth] = useState(false)
  const [focus, setFocus] = useState<string | null>(null)
  const journey = projection.journeys.find(j => j.slug === selected)
  return <main>
    <h1>The Long Way</h1><p>Every leg is drawn only as firmly as its evidence.</p>
    <p>Offline chart fixture. No live positions.</p>
    <div className="controls">
      <label><input type="checkbox" checked={myth} onChange={e => setMyth(e.target.checked)} />Without the mythology</label>
      <label>Room focus <select value={focus ?? ''} onChange={e => setFocus(e.target.value || null)}><option value="">All journeys</option>{projection.journeys.map(j => <option key={j.slug} value={j.slug}>{j.title}</option>)}</select></label>
      <label>Journey <select value={selected ?? ''} onChange={e => { setSelected(e.target.value || null); setLeg(0) }}><option value="">All journeys</option>{projection.journeys.map(j => <option key={j.slug} value={j.slug}>{j.title}</option>)}</select></label>
    </div>
    <Suspense fallback={<p>Opening the globe…</p>}><Chart data={projection} focus={focus} selected={selected} myth={myth} onSelectJourney={slug => { setSelected(slug); setLeg(0) }} onSelectLeg={(_, i) => setLeg(i)} /></Suspense>
    {journey && <section><h2>{journey.title}</h2><JourneyStrip journey={journey} />
      <label>Leg <select value={leg} onChange={e => setLeg(Number(e.target.value))}>{journey.segments.map((s, i) => <option key={i} value={i}>{s.from} to {s.to}</option>)}</select></label>
      <LegCard journey={journey} index={leg} sources={projection.sources[journey.slug] ?? {}} />
      <SeasonStrip season={journey.season} sources={projection.sources[journey.slug] ?? {}} />
    </section>}
  </main>
}
createRoot(document.getElementById('root')!).render(<Preview />)
