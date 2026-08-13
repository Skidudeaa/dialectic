// The approved scene vocabulary for the living workroom.
//
// WHY two lists: WORKSPACE_SCENES is the full approved NAME space, so a URL
// naming a future scene parses as a known name rather than garbage.
// IMPLEMENTED_WORKSPACE_SCENES is what actually renders today. Keeping them
// separate is what lets an approved-but-unbuilt scene fall back cleanly instead
// of exposing dead UI -- the program forbids shipping a scene name that opens
// nothing.
export const WORKSPACE_SCENES = [
  'house',
  'record',
  'bench',
  'library',
  'ledger',
  'field',
  'focus',
  'judgment',
  'atlas',
] as const

export type WorkspaceScene = (typeof WORKSPACE_SCENES)[number]

export const IMPLEMENTED_WORKSPACE_SCENES = ['house', 'record'] as const

export type ImplementedWorkspaceScene =
  (typeof IMPLEMENTED_WORKSPACE_SCENES)[number]

export interface WorkspaceLocation {
  scene: ImplementedWorkspaceScene
}

export function isWorkspaceScene(value: string | null): value is WorkspaceScene {
  return value !== null
    && (WORKSPACE_SCENES as readonly string[]).includes(value)
}

export function isImplementedWorkspaceScene(
  value: WorkspaceScene | null,
): value is ImplementedWorkspaceScene {
  return value !== null
    && (IMPLEMENTED_WORKSPACE_SCENES as readonly string[]).includes(value)
}
