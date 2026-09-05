import type { ReactNode } from 'react'
import type { MessageAnchor, MessageRef } from '../../../../types'
import { MessageList, type MessageListProps } from '../../../chat/MessageList'
import type { SurfaceMsg } from '../surfaceModel'
import './shapes.css'

export interface ShapeStreamProps {
  messages: SurfaceMsg[]
  controls?: MessageListProps
  context?: ReactNode
  onOpenRef: (ref: MessageRef) => void
  onReply?: (id: string) => void
  onAnchor?: (anchor: MessageAnchor) => void
}

/** One transcript implementation owns scrolling, media, receipts, proposals and jumps. */
export function ShapeStream({ messages, controls, context, onOpenRef, onReply, onAnchor }: ShapeStreamProps) {
  return (
    <div className="surf-stream">
      <div className="surf-stream-record">
      <MessageList
        currentUserId={null}
        {...controls}
        messages={messages.map((message) => message.message)}
        onReply={onReply}
        onOpenRef={onOpenRef}
        onAnchor={onAnchor}
      />
      </div>
      {context}
    </div>
  )
}
