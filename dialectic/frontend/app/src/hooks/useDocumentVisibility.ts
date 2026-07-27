import { useEffect, useState } from 'react'

/**
 * Whether the tab is currently in the foreground.
 *
 * WHY: "seen" is not the same as "delivered". A message that arrives while the
 * tab is buried in the background has not been read, and marking it read there
 * is what makes an unread badge lie to you.
 */
export function useDocumentVisibility(): boolean {
  const [isVisible, setIsVisible] = useState(
    () => typeof document === 'undefined' || document.visibilityState === 'visible',
  )

  useEffect(() => {
    const onChange = () => setIsVisible(document.visibilityState === 'visible')
    document.addEventListener('visibilitychange', onChange)
    // The tab can also lose focus without a visibility change (another window on
    // top). Focus/blur keeps the two in step for the common desktop case.
    window.addEventListener('focus', onChange)
    return () => {
      document.removeEventListener('visibilitychange', onChange)
      window.removeEventListener('focus', onChange)
    }
  }, [])

  return isVisible
}
