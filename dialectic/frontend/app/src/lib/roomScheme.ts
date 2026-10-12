// Room color schemes. Each room paints the whole surface ladder (tokens.css)
// from one hue, so a room is recognisable at a glance and every depth tier
// of its UI is a step of the same palette instead of one brown for all.
//
// The CSS half lives in styles/tokens.css: `[data-room-scheme="<name>"]`
// sets --room-hue / --room-chroma / --room-accent-hue, and every surface,
// border, ink, accent and depth token derives from those. The token blocks
// match `:root, [data-room-scheme]`, so the palette re-derives on ANY element
// carrying the attribute: <html> paints the current room, and a sidebar room
// card wears its own room's palette.

export const ROOM_SCHEMES = [
  'tide', 'moss', 'plum', 'slate', 'oxblood', 'lagoon', 'graphite',
] as const
export type RoomScheme = typeof ROOM_SCHEMES[number]

// Home is the shared hearth: amber light in a blue room.
export const HOME_SCHEME: RoomScheme = 'slate'

// The live rooms, pinned so no two of them ever share a scheme (a hash
// over six schemes put Hormuz and An Alien Mind in the same green).
const PINNED: Readonly<Record<string, RoomScheme>> = {
  '56ba2f1e-5c70-4290-a77d-52404f0095da': 'tide',     // Iran/Hormuz: the strait
  'b9f3b9d2-1d00-4179-957b-284b7cd4a8ad': 'oxblood',  // Japan Rate Shock
  '6805ad0f-0d72-441d-ac1c-2cd9dc63bca3': 'graphite', // AI Capex Unwind
  'e1ff2cca-04ed-4b50-8c38-c0df78520e21': 'plum',     // China Property Cascade
  '8adcabb7-817a-4802-87c6-3bfd42e6a9eb': 'moss',     // Trump Tariffs
  'd428ffef-1902-4f22-9771-5b5765aa73bb': 'lagoon',   // An Alien Mind
}

/** The scheme a room paints with: Home is fixed, the live rooms are pinned,
 *  any other room is a stable hash of its id (same on every device/reload).
 *  ponytail: pinned ids in code; a per-room scheme column + settings picker
 *  is the upgrade path once rooms are created often. */
export function roomSchemeFor(roomId: string, isHome: boolean): RoomScheme {
  if (isHome) return HOME_SCHEME
  if (PINNED[roomId]) return PINNED[roomId]
  let h = 0
  for (let i = 0; i < roomId.length; i++) h = (h * 31 + roomId.charCodeAt(i)) >>> 0
  // Skip Home's scheme so no ordinary room is mistaken for Home.
  const others = ROOM_SCHEMES.filter((s) => s !== HOME_SCHEME)
  return others[h % others.length]
}

/** Paint the document with a room's scheme; null restores the default. */
export function applyRoomScheme(scheme: RoomScheme | null): void {
  const root = document.documentElement
  if (scheme) root.dataset.roomScheme = scheme
  else delete root.dataset.roomScheme
  // The browser/PWA chrome follows the room too.
  const meta = document.querySelector('meta[name="theme-color"]')
  // Resolve --color-void on a transition-free probe: the raw custom property
  // is an unevaluated oklch(calc(...)) string, and body's own background is
  // mid-transition (an interpolated old color) at this instant.
  if (meta && document.body) {
    const probe = document.createElement('div')
    probe.style.cssText = 'display:none;transition:none;background-color:var(--color-void)'
    document.body.appendChild(probe)
    meta.setAttribute('content', getComputedStyle(probe).backgroundColor)
    probe.remove()
  }
}
