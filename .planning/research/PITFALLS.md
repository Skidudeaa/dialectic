# Domain Pitfalls

**Domain:** Real-time collaborative workspace with LLM participant (mobile + web)
**Researched:** 2026-01-20
**Confidence:** MEDIUM-HIGH (verified via multiple authoritative sources)

---

## Critical Pitfalls

Mistakes that cause rewrites, major delays, or fundamental user experience failures.

---

### Pitfall 1: WebSocket Background Handling on Mobile

**What goes wrong:** WebSocket connections are killed or suspended when the app moves to background. On iOS, messages are buffered until foregrounding. On Android, Doze mode blocks network activity. Users miss real-time updates, and the app appears "broken" when they return.

**Why it happens:** Mobile operating systems aggressively optimize for battery life. iOS suspends network activity for backgrounded apps. Android's Doze mode delays all network operations. The WebSocket protocol assumes persistent connections, which fundamentally conflicts with mobile OS design.

**Consequences:**
- Missed messages during background periods
- Stale state when user returns to app
- Sync conflicts if local and server state diverged
- User confusion ("Why didn't I see that message?")

**Prevention:**
1. **Design for disconnection from day one.** Treat WebSocket as "nice to have when available," not as the source of truth.
2. **Implement message gap detection.** Use sequence numbers on all messages. On reconnect, request missing messages.
3. **Use push notifications as the reliability layer.** Critical messages should trigger push notifications, which wake the app.
4. **On iOS:** Accept that background WebSocket is essentially impossible without abusing background modes (which Apple rejects). Design around it.
5. **On Android:** Consider foreground services for critical real-time features, but warn users about battery impact and provide opt-out.

**Detection (warning signs):**
- QA reports "missing messages" during device lock/unlock cycles
- Users report different message histories on same thread
- Reconnection storms after users return from background

**Phase to address:** Phase 1 (Foundation). This is architectural. Retrofitting is extremely painful.

**Sources:**
- [React Native WebSocket background issues (GitHub)](https://github.com/facebook/react-native/issues/11795)
- [Ably: Websockets React Native client-side challenges](https://ably.com/topic/websockets-react-native)

---

### Pitfall 2: State Synchronization Without Conflict Strategy

**What goes wrong:** Two users (or a user and the LLM) edit the same data simultaneously. Without a conflict resolution strategy, you either lose data silently, corrupt state, or confuse users with inconsistent views.

**Why it happens:** Developers often assume "real-time = instantaneous" and skip conflict handling. They test with low latency and single users. Real networks have delays, and real users work offline.

**Consequences:**
- Silent data loss (Last Write Wins destroys careful edits)
- Corrupted state requiring manual intervention
- Users lose trust in the system ("My changes disappeared")
- Cascading bugs from inconsistent state

**Prevention:**
1. **Choose a conflict strategy during design, not after launch:**
   - **CRDTs** for rich collaborative editing (text, lists)
   - **Last Write Wins** only for non-collaborative, low-stakes data
   - **Manual resolution UI** for high-stakes conflicts
2. **Surface conflicts to users** rather than hiding them. Show "You and [other user] both edited this. Which version do you want?"
3. **Log both versions** of conflicted data for recovery.
4. **Test with simulated network delays** (500ms-2000ms) and concurrent edits.

**Detection (warning signs):**
- Users report "my changes disappeared"
- Different users see different content for same item
- Data integrity bugs that "only happen sometimes"

**Phase to address:** Phase 1 (Foundation). Conflict strategy affects data model design. Cannot be added later without migration.

**Sources:**
- [CRDT vs OT comparison (DEV Community)](https://dev.to/puritanic/building-collaborative-interfaces-operational-transforms-vs-crdts-2obo)
- [Conflict Resolution in Offline-First Apps (Medium)](https://shakilbd.medium.com/conflict-resolution-in-offline-first-apps-when-local-and-remote-diverge-12334baa01a7)

---

### Pitfall 3: LLM Latency Destroying Real-Time Experience

**What goes wrong:** LLM responses take 1-5 seconds. During this time, the collaborative experience feels frozen. Users don't know if the system is working. The "real-time" promise is broken.

**Why it happens:** LLMs have fundamental latency: Time To First Token (TTFT) of 200ms-1000ms, plus generation time. This is incompatible with user expectations of "instant" chat responses.

**Consequences:**
- Users think the app is frozen
- "Is it broken?" support requests
- Users abandon the session
- The LLM feels like an interruption, not a participant

**Prevention:**
1. **Stream LLM responses token-by-token.** Show partial output immediately. First token matters more than total time.
2. **Add typing indicators** that appear immediately when LLM is generating.
3. **Set user expectations** through UI design. The LLM "participant" should feel different from instant human chat.
4. **Consider parallel model architecture:** Fast small model for immediate acknowledgment, larger model for full response.
5. **Pre-generate when possible.** If heuristics predict LLM will speak soon, start generation before the trigger.

**Detection (warning signs):**
- Users repeatedly click "send" thinking nothing happened
- Session abandonment during LLM "thinking" periods
- Feedback about the app being "slow" or "laggy"

**Phase to address:** Phase 2 (LLM Integration). Must be addressed when integrating LLM, not after.

**Sources:**
- [LLM Latency Benchmark (AI Multiple)](https://research.aimultiple.com/llm-latency-benchmark/)
- [Why Real-Time Is the Missing Piece in AI Agents (Stream)](https://getstream.io/blog/realtime-ai-agents-latency/)
- [Latency Optimization in LLM Streaming (Latitude)](https://latitude-blog.ghost.io/blog/latency-optimization-in-llm-streaming-key-techniques/)

---

### Pitfall 4: Push Notification Complexity Underestimation

**What goes wrong:** Push notifications seem simple but require managing APNS (iOS) and FCM (Android) separately, handling token lifecycle, dealing with platform-specific behaviors, and managing credentials. Teams budget 1 week; it takes 4-6 weeks to get right.

**Why it happens:** Push notification complexity is hidden behind simple APIs. The real work is in:
- Certificate/credential management
- Token refresh and invalidation
- Platform-specific payload formats
- Background vs foreground handling
- User preference management

**Consequences:**
- Notifications work on one platform, fail silently on another
- Token expiration causes notifications to stop working after months
- Users don't receive critical updates
- Debugging is extremely difficult (silent failures)

**Prevention:**
1. **Use Expo Push Notification service** (if using Expo) to abstract APNS/FCM complexity.
2. **Implement token refresh logic** from day one. Tokens change on app reinstall, backup restore, and periodically.
3. **Build notification debugging tools:** Log all send attempts, track delivery receipts, surface failures.
4. **Test on real devices only.** Push notifications don't work on simulators/emulators.
5. **Plan for 12-month provisioning profile expiry** (iOS) and credential rotation.

**Detection (warning signs):**
- "I'm not getting notifications" user reports (often weeks after deploy)
- Notifications work in dev, fail in production
- Gradually declining notification delivery rates

**Phase to address:** Phase 2-3 (depends on roadmap). Allow 4-6 weeks, not 1-2.

**Sources:**
- [Expo Push Notifications FAQ](https://docs.expo.dev/push-notifications/faq/)
- [Why Mobile Push Notification Architecture Fails (Netguru)](https://www.netguru.com/blog/why-mobile-push-notification-architecture-fails)
- [Technical Side of Mobile Push Notifications (MagicBell)](https://www.magicbell.com/blog/technical-side-of-mobile-push-notifications)

---

### Pitfall 5: Cross-Platform UI/UX Divergence

**What goes wrong:** "Write once, run anywhere" becomes "write once, test everywhere, fix platform-specific bugs forever." UI that looks perfect on iOS looks wrong on Android (or vice versa). Native behaviors differ (back button, gestures, safe areas).

**Why it happens:** iOS and Android have different design languages, navigation paradigms, and user expectations. React Native/Flutter abstract this, but the abstraction leaks. First-time cross-platform developers don't know what to test for.

**Consequences:**
- App feels "non-native" on one or both platforms
- Platform-specific crashes from untested code paths
- User complaints about "weird" behavior
- Doubled QA effort as platform differences emerge

**Prevention:**
1. **Test on both platforms from day one.** Don't save Android testing for "later."
2. **Use platform-specific components** where appropriate (Platform.select() in React Native).
3. **Know the differences:** Safe areas, status bar heights, navigation patterns, keyboard behavior.
4. **Hire or consult with someone who has cross-platform experience** for architecture review.
5. **Accept that some UI should differ:** Back button on Android, swipe navigation on iOS.

**Detection (warning signs):**
- All testing happens on one platform
- Bug reports cluster on one platform
- "It works on my phone" (developer uses different platform than users)

**Phase to address:** Phase 1 (Foundation). Establish dual-platform testing habit immediately.

**Sources:**
- [React Native Platform-Specific Code (Official Docs)](https://reactnative.dev/docs/platform-specific-code)
- [Handling iOS and Android Differences in React Native (Medium)](https://medium.com/@tusharkumar27864/navigating-the-two-worlds-handling-platform-specific-differences-in-react-native-f2805d9f7fce)

---

## Moderate Pitfalls

Mistakes that cause delays, technical debt, or degraded user experience.

---

### Pitfall 6: WebSocket Authentication and Token Refresh

**What goes wrong:** Initial authentication works, but token expiry during a long session breaks the connection. Users are suddenly logged out mid-conversation. Refresh logic is complex because WebSocket doesn't support standard HTTP auth headers.

**Prevention:**
1. **Implement ephemeral tokens:** Get a short-lived WebSocket token via REST, use it for WS connection. Refresh before expiry.
2. **Handle token refresh within WebSocket protocol:** Send refresh token as first message after reconnect, or use a dedicated refresh message type.
3. **Don't put tokens in query strings** for logging security. Use first-message authentication.
4. **Test long sessions** (1+ hour) with token expiry.

**Phase to address:** Phase 1 (Foundation). Authentication architecture.

**Sources:**
- [Essential Guide to WebSocket Authentication (Ably)](https://ably.com/blog/websocket-authentication)
- [Sessions vs Tokens in WebSocket Communication (Medium)](https://weber-stephen.medium.com/sessions-vs-a6872e063dbd)

---

### Pitfall 7: Message Ordering and Gap Handling

**What goes wrong:** Messages arrive out of order due to network variance or server processing. Without sequence numbers and gap detection, users see conversations that don't make sense ("answers" appear before "questions").

**Prevention:**
1. **Add sequence numbers to all messages** at the server.
2. **Buffer out-of-order messages** on client until gap is filled (with timeout).
3. **Implement gap request protocol:** If message N+2 arrives before N+1, request N+1 explicitly.
4. **Display "loading earlier messages" UI** rather than showing gaps.

**Phase to address:** Phase 1 (Foundation). Message protocol design.

**Sources:**
- [Designing Chat Architecture for Reliable Message Ordering (Ably)](https://ably.com/blog/chat-architecture-reliable-message-ordering)

---

### Pitfall 8: Battery Drain from WebSocket Keep-Alives

**What goes wrong:** Aggressive keep-alive pings (every 30 seconds) prevent the device from sleeping. Users report excessive battery drain. App gets uninstalled.

**Prevention:**
1. **Tune keep-alive intervals** based on NAT timeout research (typically 60-300 seconds is sufficient).
2. **Reduce keep-alive frequency when backgrounded** or use OS-managed push instead.
3. **Monitor battery usage** in testing (Android Battery Historian, Xcode Energy Gauge).
4. **Batch message sends** at 200ms intervals rather than sending instantly.

**Phase to address:** Phase 2-3 (Performance optimization).

**Sources:**
- [WebSocket Performance Optimization for Android (MoldStud)](https://moldstud.com/articles/p-achieving-high-performance-with-websockets-in-android-applications-a-comprehensive-guide)
- [WebSockets and Android Apps (Ably)](https://ably.com/topic/websockets-android)

---

### Pitfall 9: React Native Version Upgrade Pain

**What goes wrong:** React Native version upgrades are notoriously difficult. Dependencies break, native modules need updates, and the new architecture (Fabric/TurboModules) requires migration work. Teams avoid upgrades, accumulating tech debt.

**Prevention:**
1. **Stay within 2 minor versions of latest.** Don't fall behind.
2. **Use React Native Upgrade Helper** (react-native-community/upgrade-helper) for guided diffs.
3. **Minimize custom native modules.** Each one is upgrade friction.
4. **Budget 1-2 weeks per major version upgrade.**
5. **Keep dependencies that support the new architecture** (check before adopting).

**Phase to address:** Ongoing maintenance. Budget for this in roadmap.

**Sources:**
- [React Native New Architecture Migration (Shopify Engineering)](https://shopify.engineering/react-native-new-architecture)
- [React Native New Architecture 2025 (Medium)](https://medium.com/react-native-journal/react-natives-new-architecture-in-2025-fabric-turbomodules-jsi-explained-bf84c446e5cd)

---

### Pitfall 10: Third-Party Library Compatibility (New Architecture)

**What goes wrong:** You adopt a library that doesn't support React Native's new architecture (Fabric/TurboModules). It works in development but causes blank screens, crashes, or performance issues in production.

**Prevention:**
1. **Check library compatibility before adopting:** Look for TurboModule support, Fabric renderer compatibility.
2. **Use `npm outdated` regularly** to identify lagging packages.
3. **Have fallback options** for critical dependencies.
4. **Contribute fixes upstream** if you depend on a library that's behind.

**Phase to address:** Phase 1 (Foundation). Technology selection.

**Sources:**
- [React Native New Architecture Explained (Medium)](https://medium.com/@baheer224/react-native-new-architecture-explained-2025-guide-cc37c8f36a96)

---

### Pitfall 11: LLM as "Participant" Behavior Design

**What goes wrong:** The LLM either talks too much (annoying, dominates conversation) or too little (feels absent, not a "participant"). Finding the right interjection heuristics is harder than expected.

**Prevention:**
1. **Start conservative.** It's easier to add LLM presence than remove annoyance.
2. **Make interjection triggers configurable** per room/conversation.
3. **Provide user controls:** "Speak less" / "Speak more" / "Be quiet for now."
4. **Test with real users** early. Developer intuition about "helpful" is often wrong.
5. **Track interjection quality metrics:** User dismissals, explicit feedback, conversation continuation.

**Phase to address:** Phase 2 (LLM Integration). Iterative refinement needed.

**Sources:**
- [Human-LLM Interaction Patterns (EmergentMind)](https://www.emergentmind.com/topics/human-llm-interaction-patterns)
- ["Please stop talking..." - LLM Design Patterns (Medium/Singapore GDS)](https://medium.com/singapore-gds/please-stop-talking-edc728ce8f02)

---

### Pitfall 12: CRDT Memory Overhead on Mobile

**What goes wrong:** CRDTs for collaborative editing add 16-32 bytes of metadata per character. A 10KB document becomes 320KB. Mobile devices with limited memory struggle. UI becomes laggy.

**Prevention:**
1. **Use optimized CRDT libraries** (Yjs, Automerge with columnar encoding).
2. **Implement garbage collection** for old tombstones (deleted markers).
3. **Consider CRDT only for data that truly needs it.** Chat messages may not need CRDTs if server-ordered.
4. **Test with realistic document sizes** on low-end devices.

**Phase to address:** If implementing collaborative editing beyond chat.

**Sources:**
- [CRDT Implementation Guide (Velt)](https://velt.dev/blog/crdt-implementation-guide-conflict-free-apps)
- [Best CRDT Libraries 2025 (Velt)](https://velt.dev/blog/best-crdt-libraries-real-time-data-sync)

---

## Minor Pitfalls

Mistakes that cause annoyance or minor delays but are fixable without major rework.

---

### Pitfall 13: Simulator/Emulator-Only Testing

**What goes wrong:** App works perfectly in simulator but fails on real devices. Push notifications don't work at all on simulators. Performance characteristics differ dramatically.

**Prevention:**
- Test on real devices from week 1
- Use low-end devices for performance testing
- Budget for device acquisition or use cloud device farms (BrowserStack, Firebase Test Lab)

---

### Pitfall 14: Ignoring Keyboard Behavior Differences

**What goes wrong:** Keyboard handling differs between iOS and Android. Chat input gets hidden behind keyboard. Scroll behavior is wrong.

**Prevention:**
- Use KeyboardAvoidingView (React Native) with platform-specific behavior
- Test all text input flows on both platforms
- Handle keyboard appearance/dismissal events explicitly

---

### Pitfall 15: Not Handling Reconnection Gracefully

**What goes wrong:** After network reconnection, app state is stale. Users must manually refresh, or worse, app crashes from unexpected state.

**Prevention:**
- Implement exponential backoff for reconnection attempts
- Re-sync state after reconnection (don't assume clean continuation)
- Show reconnection status to users ("Reconnecting...")

---

### Pitfall 16: Ignoring App Store Review Requirements

**What goes wrong:** App rejected for reasons that could have been anticipated: missing privacy policy, improper use of background modes, unauthorized push notification usage.

**Prevention:**
- Read iOS App Store Review Guidelines and Google Play policies before starting
- Justify any background mode usage
- Include privacy policy, terms of service
- Prepare for review questions about LLM/AI features

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Foundation | WebSocket background handling | Design for disconnection, use push as fallback |
| Foundation | Cross-platform testing gaps | Dual-platform testing from day 1 |
| Foundation | Sync conflicts | Choose conflict strategy before implementation |
| LLM Integration | LLM latency perception | Streaming responses, typing indicators |
| LLM Integration | Over-talkative LLM | Start conservative, add controls |
| Push Notifications | Silent failures | Build debugging/monitoring from start |
| Push Notifications | Token lifecycle | Implement refresh logic, log failures |
| Performance | Battery drain | Tune keep-alives, batch messages |
| Maintenance | RN version upgrades | Stay current, budget upgrade time |

---

## Decision Framework: When to Seek Deeper Research

Flag for additional research if:

1. **Choosing between CRDTs and simpler approaches:** Depends heavily on specific collaboration features. Research trade-offs for YOUR use case.

2. **Implementing offline-first:** Complexity varies dramatically based on data model. Research sync patterns for your specific schema.

3. **Custom native modules:** If you need native code (camera, sensors, etc.), research the specific APIs and their cross-platform abstraction options.

4. **LLM provider selection:** Latency, cost, and capability trade-offs change frequently. Research current options when implementing.

---

## Sources Summary

### HIGH Confidence (Official documentation, authoritative sources)
- [React Native Official Docs](https://reactnative.dev/docs/)
- [Expo Push Notifications Documentation](https://docs.expo.dev/push-notifications/)
- [Flutter WebSockets Cookbook](https://docs.flutter.dev/cookbook/networking/web-sockets)

### MEDIUM Confidence (Engineering blogs, verified patterns)
- [Shopify Engineering: React Native New Architecture](https://shopify.engineering/react-native-new-architecture)
- [Ably: Chat Architecture Message Ordering](https://ably.com/blog/chat-architecture-reliable-message-ordering)
- [Ably: WebSockets React Native](https://ably.com/topic/websockets-react-native)
- [Stream: Real-time AI Agents Latency](https://getstream.io/blog/realtime-ai-agents-latency/)

### LOW Confidence (Community patterns, may need validation)
- Individual Medium posts on specific implementation patterns
- GitHub issue discussions (good for identifying problems, less reliable for solutions)
