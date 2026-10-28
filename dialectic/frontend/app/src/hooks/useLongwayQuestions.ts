import { useLongwayResource } from '../organs/longway/useLongwayResource'
import { longwayPath } from '../organs/longway/api'
import type { Question } from '../organs/longway/types'

export function useLongwayQuestions(roomId: string) {
  return useLongwayResource<Question[]>(longwayPath(roomId, 'questions'))
}
