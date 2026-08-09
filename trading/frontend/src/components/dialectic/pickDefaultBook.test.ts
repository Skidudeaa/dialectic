/**
 * Tests for pickDefaultBook — which case the desk opens on.
 *
 * WHY: arriving via Dialectic's "Open Full Dashboard" link is an explicit
 * statement of which case the user means. If a generic default outranked it,
 * the deep link would authenticate you and then drop you on the wrong thesis —
 * which looks exactly like the link not working.
 */

import { describe, it, expect } from "vitest";
import { pickDefaultBook } from "./data";
import type { Room, ThesisBook } from "../../lib/types";

function book(id: string, dialecticRoomId: string | null = null): ThesisBook {
  return { id, filename: `${id}.json`, title: id, nodes: 0, edges: 0, dialecticRoomId };
}

function room(id: string, linked_book_id: string | null): Room {
  return {
    id,
    name: id,
    topic: "",
    linked_book_id,
    participants: [],
    created_at: "2026-08-09T00:00:00Z",
  } as Room;
}

const IRAN = book("iran-hormuz-graph", "56ba2f1e-5c70-4290-a77d-52404f0095da");
const TARIFFS = book("trump-tariffs-graph", "8adcabb7-817a-4802-87c6-3bfd42e6a9eb");
const ORPHAN = book("orphan-graph");

describe("pickDefaultBook", () => {
  it("opens the case discussed by the room the user came from", () => {
    const chosen = pickDefaultBook(
      [ORPHAN, IRAN, TARIFFS],
      [],
      "8adcabb7-817a-4802-87c6-3bfd42e6a9eb",
    );

    expect(chosen?.id).toBe("trump-tariffs-graph");
  });

  it("beats the linked-room default", () => {
    // ORPHAN would win on the old rule (first book with a linked room). The
    // bridged room must outrank it.
    const chosen = pickDefaultBook(
      [ORPHAN, IRAN],
      [room("r1", "orphan-graph")],
      "56ba2f1e-5c70-4290-a77d-52404f0095da",
    );

    expect(chosen?.id).toBe("iran-hormuz-graph");
  });

  it("falls back to the linked book when no room was bridged", () => {
    const chosen = pickDefaultBook([ORPHAN, IRAN], [room("r1", "iran-hormuz-graph")], null);

    expect(chosen?.id).toBe("iran-hormuz-graph");
  });

  it("falls back to the linked book when the bridged room matches nothing", () => {
    // A stale or renamed room must not strand the user on a blank desk.
    const chosen = pickDefaultBook(
      [ORPHAN, IRAN],
      [room("r1", "iran-hormuz-graph")],
      "00000000-0000-4000-8000-000000000000",
    );

    expect(chosen?.id).toBe("iran-hormuz-graph");
  });

  it("falls back to the first book when nothing is linked", () => {
    const chosen = pickDefaultBook([ORPHAN, IRAN], [], null);

    expect(chosen?.id).toBe("orphan-graph");
  });

  it("returns null when there are no books", () => {
    expect(pickDefaultBook([], [], "any-room")).toBeNull();
  });

  it("ignores books whose room id is null when a room is bridged", () => {
    // `undefined === undefined` would otherwise match every unlinked book.
    const chosen = pickDefaultBook([ORPHAN, book("second")], [], "some-room-id");

    expect(chosen?.id).toBe("orphan-graph"); // first-book fallback, not a false match
  });
});
