# Somacura Capture

Native iPadOS containing app + Safari Web Extension for local-first rendered-page Markdown capture.

Build facts:

- Minimum target: iOS/iPadOS 18.6.
- WebExtension: Manifest V3, `action.onClicked`, no popup, Defuddle 0.19.3.
- Local commit: App Group `Captures/<capture_id>/{capture.json,content.md,state.json}` before network.
- Credentials: shared Keychain; destination: shared App Group preferences.
- Server: `POST /rooms/{room_id}/reading/capture` with Bearer + `X-Room-Token`.
- The checked-in `com.example.unconfigured` prefix is simulator-only. Replace it once in `Configuration/CaptureConfiguration.xcconfig` after registering the app IDs and App Group.

```bash
nvm use 22
capture-ios/scripts/build-extension.sh
capture-ios/scripts/verify.sh
```

The verification script auto-selects an available iPad Simulator; set `IPAD_SIMULATOR_UDID` only to pin one. A missing iPad runtime fails the gate. Physical signing, registered App Group/Keychain sharing, TestFlight, migration application, and production deployment are separate owner-authorized operations.
