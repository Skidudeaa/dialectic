import { describe, expect, it } from 'vitest'
import { inkWithProposal, segments } from './mapStyle'
import type { Journey } from '../types'

const journey = (overrides: Partial<Journey['segments'][number]>[]): Journey => ({
  slug: 'banda-islands', kind: 'candidate', title: 'Banda', where: 'Banda Sea', status: 'researching', feasibility: 'unverified',
  judgment: null, season: null, days: null, pull: '', journey: '', questions: [],
  route: [[-3.7, 128.2, 'Ambon'], [-4.5, 129.9, 'Banda Neira'], [-4.5, 129.8, 'Ai']],
  segments: [
    { from: 'Ambon', to: 'Banda Neira', ink: 'pencil', basis: [], ...overrides[0] },
    { from: 'Banda Neira', to: 'Ai', ink: 'dashed', basis: ['S1'], ...overrides[1] },
  ],
})

describe('a pending proposal and the ink', () => {
  it('turns a pencil leg dotted and leaves ink alone', () => {
    expect(inkWithProposal({ ink: 'pencil', proposed: true })).toBe('dotted')
    expect(inkWithProposal({ ink: 'pencil' })).toBe('pencil')
    expect(inkWithProposal({ ink: 'dashed', proposed: true })).toBe('dashed')
    expect(inkWithProposal({ ink: 'contradicted', proposed: true })).toBe('contradicted')
  })

  it('carries the proposal into the segment features as ink, nothing else', () => {
    const features = segments([journey([{ proposed: true }, {}])]).features
    expect(features.map(f => f.properties)).toEqual([{ slug: 'banda-islands', i: 0, ink: 'dotted' }, { slug: 'banda-islands', i: 1, ink: 'dashed' }])
  })
})
