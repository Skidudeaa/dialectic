export type Json = string | number | boolean | null | Json[] | JsonObject
export type JsonObject = { [key: string]: Json }
export type DocumentName = 'voyage' | 'record' | 'dossier'
export type EditorView = 'stop' | 'everything' | 'record' | 'dossier'
export interface JourneyDocument {
  slug: string
  name: DocumentName
  format: 'json' | 'text'
  value: JsonObject | string
  protected: string[]
  writable: boolean
  why: string | null
}
export interface Receipt { commit: string; changed: string[]; summary: string }
export interface SetOp { op: 'set'; path: string; value: Json }
export type EditBody = { ops: SetOp[] } | { text: string }
export const pretty = (value: Json) => JSON.stringify(value, null, 2)
export function isObject(value: Json | undefined): value is JsonObject {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

type Kind = 'line' | 'prose' | 'list' | 'number' | 'json'
export type FieldGroup = 'story' | 'reach' | 'photos' | 'camera'
export interface Field { path: string; label: string; kind: Kind; group?: FieldGroup; half?: boolean }
export const stopFieldGroups: { id: FieldGroup; title: string }[] = [
  { id: 'story', title: 'Story and caption' },
  { id: 'reach', title: 'Access and reach' },
  { id: 'photos', title: 'Photographs' },
  { id: 'camera', title: 'Camera and pacing' },
]
export const stopFields: Field[] = [
  { path: 'name', label: 'Name', kind: 'line', group: 'story', half: true },
  { path: 'kicker', label: 'Kicker', kind: 'line', group: 'story', half: true },
  { path: 'moment/text', label: 'Moment', kind: 'prose', group: 'story' },
  { path: 'moment/cite', label: 'Moment citations (comma separated)', kind: 'list', group: 'story' },
  { path: 'text', label: 'Long text', kind: 'prose', group: 'story' },
  { path: 'reach', label: 'Reach', kind: 'line', group: 'reach', half: true },
  { path: 'reach_cite', label: 'Reach citations (comma separated)', kind: 'list', group: 'reach', half: true },
  { path: 'reach_why', label: 'Reason for reach', kind: 'prose', group: 'reach' },
  { path: 'photo', label: 'Lead photo', kind: 'line', group: 'photos', half: true },
  { path: 'photos', label: 'Photo keys in order (comma separated)', kind: 'list', group: 'photos', half: true },
  { path: 'camera/zoom', label: 'Camera zoom', kind: 'number', group: 'camera', half: true },
  { path: 'camera/pitch', label: 'Camera pitch', kind: 'number', group: 'camera', half: true },
  { path: 'camera/bearing', label: 'Camera bearing', kind: 'number', group: 'camera', half: true },
  { path: 'pace/hold', label: 'Hold', kind: 'number', group: 'camera', half: true },
]

export function fieldText(value: Json | undefined, kind: Kind): string {
  if (value === undefined) return ''
  if (kind === 'json') return pretty(value)
  if (kind === 'list' && Array.isArray(value)) return value.join(', ')
  return String(value ?? '')
}
export function fieldValue(field: Field, text: string): Json {
  if (field.kind === 'json') {
    try { return JSON.parse(text) }
    catch { throw new Error(`Check the JSON in ${field.label}.`) }
  }
  if (field.kind === 'list') return text.split(',').map(item => item.trim()).filter(Boolean)
  if (field.kind === 'number') {
    if (!text.trim() || !Number.isFinite(Number(text))) throw new Error(`Enter a number for ${field.label}.`)
    return Number(text)
  }
  return text
}
export function readField(object: JsonObject, path: string): Json | undefined {
  return path.split('/').reduce<Json | undefined>((node, key) => isObject(node) ? node[key] : undefined, object)
}
// Only the known stop fields use nested paths. Keep optional siblings from the server.
export function withField(object: JsonObject, path: string, value: Json): JsonObject {
  const [key, ...rest] = path.split('/')
  const child = object[key]
  return { ...object, [key]: rest.length ? withField(isObject(child) ? child : {}, rest.join('/'), value) : value }
}
