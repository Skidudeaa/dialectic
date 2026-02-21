import './TypingIndicator.css'

interface TypingIndicatorProps {
  typingUsers: string[]
}

export function TypingIndicator({ typingUsers }: TypingIndicatorProps) {
  if (typingUsers.length === 0) return null

  const text = typingUsers.length === 1
    ? `${typingUsers[0]} is thinking...`
    : `${typingUsers.join(', ')} are thinking...`

  return (
    <div className="typing-bar active">
      <div className="typing-dots">
        <span /><span /><span />
      </div>
      <span>{text}</span>
    </div>
  )
}
