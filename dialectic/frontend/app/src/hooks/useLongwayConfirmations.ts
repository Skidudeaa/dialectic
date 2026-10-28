import { useLongwayResource } from '../organs/longway/useLongwayResource'
import { longwayPath } from '../organs/longway/api'
import type { Confirmation } from '../organs/longway/types'

export function useLongwayConfirmations(roomId: string) {
  return useLongwayResource<Confirmation[]>(longwayPath(roomId, 'confirmations'))
}
