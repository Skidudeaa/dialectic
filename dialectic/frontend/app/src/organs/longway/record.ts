import type { Message } from '../../types'
import type { DispatchMetadata } from './types'

/** Lift the dispatch to its Record day without changing persisted timestamps
 * or reordering the conversation underneath it. The Record groups local days. */
export function dispatchesFirst(messages: Message[]): Message[] {
  const days = new Map<string, Message[]>()
  for (const message of messages) {
    const day = new Date(message.created_at).toDateString()
    const group = days.get(day) ?? []
    group.push(message); days.set(day, group)
  }
  const isDispatch = (message: Message) => message.speaker_type.startsWith('llm_') && Boolean((message.metadata as { longway_dispatch?: DispatchMetadata } | null)?.longway_dispatch)
  return [...days.values()].flatMap(group => [...group.filter(isDispatch), ...group.filter(message => !isDispatch(message))])
}

/** The dispatch contract keeps its question immediately before the reaction line. */
export function dispatchQuestion(content: string): string {
  const beforeReactions = content.split(/^React with 👍/m)[0].trim()
  return beforeReactions.split(/\n\s*\n/).at(-1)?.trim() ?? ''
}
