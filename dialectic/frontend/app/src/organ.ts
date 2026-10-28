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
// The Long Way opens a journey room on its Chart: the first thing a friend sees is the thing they cannot get
// anywhere else (moonshot-house, The Hard Part). The Record is one tap away.
export const SCENES: readonly ImplementedWorkspaceScene[] = ORGAN === 'longway'
  ? ['bench', 'record', 'library', 'field', 'ledger']
  : ['surface', 'record', 'bench', 'field', 'atlas', 'library', 'ledger']
export const benchLabel = ORGAN === 'longway' ? 'Chart' : 'Bench'
