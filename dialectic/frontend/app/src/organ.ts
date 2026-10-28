import type { ImplementedWorkspaceScene } from './types/workspace'

export const ORGAN = import.meta.env.VITE_ORGAN === 'longway' ? 'longway' : 'trading'
export const IDENTITY = ORGAN === 'longway' ? {
  name: 'The Long Way', shortName: 'Long Way', participantName: 'Scout', signature: ')',
  lede: 'Go far enough to be surprised. Stay long enough to understand. Leave room to be changed.',
  originImprint: 'The Long Way',
} : {
  name: 'Dialectic', shortName: 'Dialectic', participantName: 'Dialectic', signature: ')',
  lede: null, originImprint: 'DwoodAmo',
}
export const SCENES: readonly ImplementedWorkspaceScene[] = ORGAN === 'longway'
  ? ['record', 'bench', 'library', 'field', 'ledger']
  : ['surface', 'record', 'bench', 'field', 'atlas', 'library', 'ledger']
export const benchLabel = ORGAN === 'longway' ? 'Chart' : 'Bench'
