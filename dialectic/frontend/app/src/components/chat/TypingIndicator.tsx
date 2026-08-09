import './TypingIndicator.css'

interface TypingIndicatorProps {
  typingUsers: string[]
  /**
   * What the LLM is doing right now, when it is doing something more specific
   * than thinking — "checking live prices". Takes the bar over the generic
   * copy: a 20s quote check reads as a hang unless the room can see it.
   */
  activityLabel?: string | null
}

export function TypingIndicator({ typingUsers, activityLabel }: TypingIndicatorProps) {
  if (!activityLabel && typingUsers.length === 0) return null

  const text = activityLabel
    ? `Claude is ${activityLabel}…`
    : typingUsers.length === 1
      ? `${typingUsers[0]} is thinking...`
      : `${typingUsers.join(', ')} are thinking...`

  return (
    <div className="typing-bar active">
      <div className="typing-dots">
        <span /><span /><span />
      </div>
      <span className={activityLabel ? 'typing-tool' : undefined}>{text}</span>
    </div>
  )
}
