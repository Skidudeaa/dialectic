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
export interface Field { path: string; label: string; kind: Kind }
export const stopFields: Field[] = [
  { path: 'name', label: 'Name', kind: 'line' },
  { path: 'kicker', label: 'Kicker', kind: 'line' },
  { path: 'moment/text', label: 'Moment', kind: 'prose' },
  { path: 'moment/cite', label: 'Moment citations (comma separated)', kind: 'list' },
  { path: 'text', label: 'Long text', kind: 'prose' },
  { path: 'reach', label: 'Reach', kind: 'line' },
  { path: 'reach_why', label: 'Reason for reach', kind: 'prose' },
  { path: 'reach_cite', label: 'Reach citations (comma separated)', kind: 'list' },
  { path: 'photos', label: 'Photo keys in order (comma separated)', kind: 'list' },
  { path: 'photo', label: 'Lead photo', kind: 'line' },
  { path: 'camera/zoom', label: 'Camera zoom', kind: 'number' },
  { path: 'camera/pitch', label: 'Camera pitch', kind: 'number' },
  { path: 'camera/bearing', label: 'Camera bearing', kind: 'number' },
  { path: 'pace/hold', label: 'Hold', kind: 'number' },
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
