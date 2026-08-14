import type { Message } from '../../types'
import { markGlyph } from '../../lib/productIdentity'
import './SignatureMark.css'

interface SignatureMarkProps {
  speakerType: Message['speaker_type']
  authorName: string
}

/**
 * Purely decorative: the author name sitting beside it already carries the
 * accessible name ("Amo", "Dan", "Dialectic"), so a screen reader does not
 * need to announce the glyph a second time. See `markGlyph` in
 * `lib/productIdentity.ts` for what the glyph is and why.
 */
export function SignatureMark({ speakerType, authorName }: SignatureMarkProps) {
  return (
    <span className="signature-mark" aria-hidden="true">
      {markGlyph(speakerType, authorName)}
    </span>
  )
}
