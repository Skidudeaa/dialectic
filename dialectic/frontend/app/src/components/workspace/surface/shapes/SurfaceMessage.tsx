import type { MessageAnchor, MessageRef } from '../../../../types'
import { MessageBubble } from '../../../chat/MessageBubble'
import type { MessageListProps } from '../../../chat/MessageList'
import { surfaceAuthor, type SurfaceMsg } from '../surfaceModel'

export interface SurfaceMessageProps {
  msg: SurfaceMsg
  controls?: MessageListProps
  onOpenRef?: (ref: MessageRef) => void
  onReply?: (id: string) => void
  onInvestigate?: (id: string, quote?: string) => void
  onAnchor?: (anchor: MessageAnchor) => void
  threadSource?: MessageRef | null
  compact?: boolean
  dimmed?: boolean
}

/** Alternate arrangements retain the exact same media, decisions and actions as Record. */
export function SurfaceMessage({ msg, controls, onOpenRef, onReply, onInvestigate, onAnchor, compact, dimmed, threadSource }: SurfaceMessageProps) {
  const parent = controls?.messages.find((message) => message.id === msg.parentId)
  const names = controls?.userNames ?? {}
  return (
    <article className={`surf-msg${compact ? ' surf-msg-compact' : ''}${dimmed ? ' surf-msg-dimmed' : ''}`} data-mid={msg.id}>
      <MessageBubble
        message={msg.message}
        threadSource={threadSource}
        authorName={msg.author.name}
        isSelf={msg.author.isSelf}
        isStreaming={msg.isStreaming}
        userNames={names}
        mentionContext={{ names: Object.values(names), selfName: controls?.currentUserId ? names[controls.currentUserId] ?? null : null }}
        currentUserId={controls?.currentUserId}
        replyToAuthor={parent ? surfaceAuthor(parent, names, controls?.currentUserId ?? null).name : undefined}
        replyToContent={parent?.content}
        replyToMissing={Boolean(msg.message.references_message_id && !parent)}
        reactions={controls?.reactions?.[msg.id]}
        attachments={controls?.attachments?.[msg.id]}
        marks={controls?.marksByMessage?.[msg.id]}
        onFieldChanged={controls?.onFieldChanged}
        onReply={onReply}
        onInvestigate={onInvestigate}
        onFork={controls?.onFork}
        onToggleReaction={controls?.onToggleReaction}
        onEdit={controls?.onEditMessage}
        onDelete={controls?.onDeleteMessage}
        onOpenBench={controls?.onOpenBench}
        onOpenRef={onOpenRef}
        contextRef={controls?.contextRef}
        onAnchor={onAnchor}
      />
    </article>
  )
}
