import { useLayoutEffect, useRef } from 'react'
import type { ReactNode } from 'react'

// Native dialogs occupy the browser's top layer and restore focus to the opener.
export function VoyageDialog({ label, className, close, children }: {
  label: string; className: string; close: () => void; children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useLayoutEffect(() => {
    const dialog = ref.current!
    dialog.showModal()
    return () => dialog.close()
  }, [])
  return <dialog ref={ref} className={className} aria-label={label} onCancel={event => {
    event.stopPropagation()
    event.preventDefault()
    close()
  }}>{children}</dialog>
}
