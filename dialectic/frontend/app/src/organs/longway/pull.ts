/**
 * Strip evidence citation markers (plain `S123` or markdown `[S123](url)`)
 * from introductory pull prose that friends read first, tidying the spacing
 * and punctuation they leave behind while leaving ordinary words such as
 * `SS Sudan` or `S-curve` untouched.
 */
export function cleanPull(text: string): string {
  return text
    .replace(/\[S\d+\](?:\([^)]*\))?/g, '')
    .replace(/(?<![\w-])S\d+(?![\w-])/g, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/[ \t]+([,.;:!?)\]])/g, '$1')
    .replace(/([([])[ \t]+/g, '$1')
    .replace(/^[ \t]+|[ \t]+$/gm, '')
    .trim()
}
