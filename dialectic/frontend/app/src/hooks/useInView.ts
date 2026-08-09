import { useEffect, useRef, useState, type RefObject } from 'react'

/**
 * Whether an element has ever been near the viewport.
 *
 * Latching (never returning to false) is deliberate: this gates a fetch, and
 * un-fetching is not a thing. The margin starts the work slightly before the
 * element is on screen so images are usually decoded by the time they arrive.
 *
 * Degrades to "always in view" where IntersectionObserver is unavailable —
 * eager loading is a worse default than lazy, but a blank image is worse still.
 */
export function useInView<T extends HTMLElement>(rootMargin = '300px'): [RefObject<T | null>, boolean] {
  const ref = useRef<T>(null)
  const [inView, setInView] = useState(typeof IntersectionObserver === 'undefined')

  useEffect(() => {
    if (inView) return
    const element = ref.current
    if (!element) return

    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        setInView(true)
        observer.disconnect()
      }
    }, { rootMargin })

    observer.observe(element)
    return () => observer.disconnect()
  }, [inView, rootMargin])

  return [ref, inView]
}
