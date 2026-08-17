# Push Room and Message Deep Links

**Date:** 2026-08-16

**Status:** Approved design; awaiting written-spec review

**Repository:** `/root/DwoodAmo`

## 1. Decision

Every message notification names the room where the message was sent. Tapping
the notification opens that exact room, branch, and message whether the PWA is
already open or starting cold.

Reuse the existing push payload, URL-authoritative room navigator,
`getMessageContext` endpoint, and MessageList scroll-and-flash behavior. Do not
add a notification landing screen, alternate navigation writer, database
migration, or native-only path.

## 2. Proven gap

The backend already puts `room_id`, `thread_id`, and `message_id` into both Web
Push and Expo data. Two downstream gaps discard that work:

- The notification title is only the sender name. `_trigger_push_notifications`
  does not read or pass the room name.
- The service worker reads only `room_id`. A warm tap posts `open-room`; a cold
  tap opens `/?room=<id>`. `thread_id` and `message_id` are ignored.

The frontend already has the remaining primitives. `useRoomNavigation` is the
sole destination writer; search results already load a context window around an
older message; `MessageList` already scrolls the target to center and flashes it.

## 3. Notification content

The notification title is:

```text
Room Name · Sender Name
```

LLM identity remains visually distinct:

```text
Room Name · ✦ Claude
```

The body remains the bounded message preview. Annotation-enriched previews keep
their existing behavior. Room names are permitted on the lock screen because
the current notification already displays message content, which is more
sensitive than the room label.

`_trigger_push_notifications` obtains the canonical room name in the existing
room-membership query and passes it explicitly to
`send_message_notification`. Both Web Push and Expo receive the same title and
the same data:

```json
{
  "type": "new_message",
  "room_id": "uuid",
  "room_name": "Iran/Hormuz Trading Room",
  "thread_id": "uuid",
  "message_id": "uuid"
}
```

No client-supplied room name is trusted.

## 4. Canonical destination

Add a nullable `messageId` axis to `RoomDestination`, serialized as the
`message` query parameter:

```text
/?room=<room-id>&thread=<thread-id>&message=<message-id>
```

`destinationFromSearch` parses it and `destinationUrl` serializes it through
`URLSearchParams`. Existing room, thread, scene, and object links remain
unchanged when no message is present.

A message target is valid only with the thread that navigation actually
installed. If the requested thread no longer belongs to the room, navigation
falls back according to its existing access rules and drops the message target.
Ordinary navigation without `messageId` clears the previous target and removes
the `message` query parameter.

## 5. Warm notification tap

When an app window exists, the service worker:

1. closes the notification;
2. prefers a visible window, otherwise the first controlled window;
3. focuses that window;
4. posts one `open-message` event carrying room, thread, and message IDs.

The `useRoomNavigation` service-worker listener sends that complete destination
through `navigate`. It does not call `setRoom`, `setThread`, or history APIs
directly.

## 6. Cold notification tap

When no app window exists, the service worker builds the canonical URL with
`URLSearchParams` and calls `clients.openWindow`. Authentication and room access
continue through the existing boot path. After authentication, initial-entry
navigation reads the same room/thread/message destination from the unchanged
address bar.

No redirect route or transient local storage handoff is introduced.

## 7. Exact message landing

`useRoomNavigation` exposes the installed `messageId` alongside its existing
`objectId`. `ChatLayout` owns message hydration after the room and thread have
been installed:

- With no message target, load the latest 200 messages exactly as today.
- With a message target, call the existing room-token-fenced
  `getMessageContext(threadId, messageId)` instead of racing a latest-history
  load against a context load.
- After the context window is installed, set the existing `jumpTarget`.
- `MessageList` performs its existing centered scroll and 1.6-second flash.
- Attachments and reactions refresh through their current paths.

If the target message was deleted or is no longer visible, the app still lands
in the resolved room and thread, loads current history, and does not invent a
message placeholder. Access denial keeps the existing corrective Home behavior.

## 8. Notification replacement semantics

The existing Web Push tag remains `room_<room_id>`, so multiple messages in one
room replace that room's notification rather than creating a stack. The payload
of the visible replacement contains the newest message ID; tapping therefore
lands on the message represented by the text the user sees.

Notifications from different rooms keep distinct tags and destinations.

## 9. Compatibility

- Old notifications containing only `room_id` continue opening the room.
- New notifications with room and thread but no message open the branch.
- Existing copied URLs without `message` serialize exactly as before.
- Expo data gains `room_name` but retains all existing keys.
- No backend API, database schema, push-subscription shape, or auth rule changes.
- `useRoomNavigation` remains the only room/thread/history destination writer.

## 10. Test-first implementation gate

Before production code changes, add failing tests proving:

1. human and LLM notification titles include the canonical room name;
2. Web Push and Expo carry identical room/thread/message destination data;
3. the room name comes from the server-side room query;
4. warm taps focus a window and post one complete `open-message` destination;
5. cold taps open an encoded room/thread/message URL;
6. legacy room-only notification payloads still work;
7. `RoomDestination` parses and serializes the message axis without changing
   legacy URLs;
8. service-worker messages enter through `navigate`, not direct store writes;
9. exact-message entry loads `getMessageContext` without racing `getMessages`;
10. a loaded target scrolls and flashes through the existing MessageList path;
11. a missing/deleted message falls back to current thread history;
12. a denied room cannot leak or install the message target;
13. ordinary navigation clears an old message target;
14. two room notifications retain distinct tags and destinations.

Run focused backend notification/transport tests, frontend route/navigation/
MessageList/service-worker tests, the full Dialectic backend and frontend suites,
lint, production build, and browser acceptance for warm and cold taps at phone
and desktop widths.

## 11. Deployment gate

This change requires a Dialectic backend restart and a new PWA release because
it changes both notification production and service-worker/navigation behavior.
Deploy the backend first, then publish the frontend release and reload nginx.

Acceptance must use a real Web Push subscription and two rooms:

1. send a message while the PWA is closed and prove the title names its room;
2. tap it and prove the cold app opens with the target message centered;
3. repeat with the PWA already open in another room;
4. prove the warm tap switches rooms, branches correctly, and flashes the target;
5. send notifications from two rooms and prove each visible notification opens
   its own destination.

Production activation remains separate from implementation and local gates.

## 12. Acceptance

The feature is accepted when a user can read the notification and know who spoke
and where, then tap once and land on the exact persisted message represented by
that notification in both warm and cold PWA states.
