import { useLongwayResource } from '../organs/longway/useLongwayResource'
import { longwayPath } from '../organs/longway/api'
import type { ScoutRun } from '../organs/longway/types'

export function useLongwayScoutRuns(roomId: string) {
  // Poll while the desk is open: this also discovers runs begun nightly or on another device.
  return useLongwayResource<ScoutRun[]>(longwayPath(roomId, 'scout/runs'), '', 10_000)
}
