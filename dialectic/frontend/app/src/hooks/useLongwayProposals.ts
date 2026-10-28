import { useLongwayResource } from '../organs/longway/useLongwayResource'
import { longwayPath } from '../organs/longway/api'
import type { EvidenceProposal } from '../organs/longway/types'

export function useLongwayProposals(roomId: string) {
  return useLongwayResource<EvidenceProposal[]>(longwayPath(roomId, 'proposals'))
}
