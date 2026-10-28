import { useLongwayResource } from '../organs/longway/useLongwayResource'
import { longwayPath } from '../organs/longway/api'
import type { ScoutedProposal } from '../organs/longway/types'

export function useLongwayProposals(roomId: string) {
  return useLongwayResource<ScoutedProposal[]>(longwayPath(roomId, 'proposals'))
}
