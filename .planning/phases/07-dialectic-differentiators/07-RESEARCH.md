# Phase 7: Dialectic Differentiators - Research

**Researched:** 2026-01-25
**Domain:** Thread forking, genealogy visualization, LLM heuristic interjection, configuration UI
**Confidence:** HIGH

## Summary

This research covers implementing Dialectic's unique features: thread forking from any message, cladogram-style genealogy visualization, proactive LLM interjection based on heuristics, and user-configurable interjection behavior. The phase depends on the existing backend infrastructure (forking in operations.py, heuristics in heuristics.py) and extends the mobile app to expose these features.

The existing backend already has complete fork_thread and get_thread_messages functions in operations.py that handle fork creation and ancestry traversal. The heuristics.py InterjectionEngine supports turn threshold, question detection, semantic novelty, and stagnation triggers. The rooms table already has interjection_turn_threshold and semantic_novelty_threshold columns. This phase is primarily about mobile UI implementation and extending the WebSocket protocol to support heuristic configuration updates.

For genealogy visualization, react-native-svg with custom drawing is the recommended approach over third-party tree libraries, as cladogram layouts require specific biological taxonomy styling that generic tree libraries don't provide. For the long-press context menu, react-native-hold-menu provides a Telegram-style experience with Reanimated v2 animations.

**Primary recommendation:** Use react-native-hold-menu for the fork context menu, custom react-native-svg drawing for cladogram visualization, extend the existing InterjectionEngine to be room-configurable, and use @react-native-community/slider with preset buttons for the settings UI.

## Standard Stack

The established libraries/tools for this phase:

### Core (Mobile)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `react-native-hold-menu` | ^0.2.x | Long-press context menu | Telegram-style, Reanimated v2, smooth animations |
| `react-native-svg` | ^15.x | Cladogram tree rendering | Already in Expo, custom drawing control |
| `@react-native-community/slider` | ^4.x | Heuristic threshold sliders | Native slider, smooth, accessible |
| `react-native-gesture-handler` | ^2.x | Long-press detection | Already installed (Expo), performant |
| Existing Zustand stores | Phase 3+ | State management | Established patterns |

### Core (Backend Extensions)

| Component | Location | Purpose |
|-----------|----------|---------|
| `operations.py` | `dialectic/` | Already has fork_thread, get_thread_messages |
| `heuristics.py` | `dialectic/llm/` | Already has InterjectionEngine with triggers |
| `rooms` table | `schema.sql` | Already has interjection threshold columns |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `d3-hierarchy` | ^3.x | Tree layout calculations | If cladogram math gets complex |
| `react-native-haptic-feedback` | ^2.x | Long-press haptics | iOS/Android feedback |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `react-native-hold-menu` | `react-native-context-menu-view` | context-menu-view is native but iOS-only |
| Custom SVG cladogram | `react-native-d3-tree-graph` | d3-tree-graph not designed for cladogram style |
| `@react-native-community/slider` | gluestack Slider | Community slider more mature, better native feel |
| Custom genealogy query | PostgreSQL ltree | ltree extension adds complexity, CTE sufficient for depth |

**Installation (Mobile):**
```bash
cd mobile
npm install react-native-hold-menu @react-native-community/slider d3-hierarchy
# react-native-svg and react-native-gesture-handler already installed via Expo
```

## Architecture Patterns

### Recommended Project Structure

```
mobile/
├── components/
│   ├── chat/
│   │   ├── message-bubble.tsx       # Extend with long-press handler
│   │   └── fork-context-menu.tsx    # NEW: Fork option in context menu
│   ├── branches/
│   │   ├── cladogram-view.tsx       # NEW: SVG genealogy tree
│   │   ├── thread-node.tsx          # NEW: Individual node in tree
│   │   └── branch-connector.tsx     # NEW: Line connectors
│   ├── settings/
│   │   ├── llm-settings.tsx         # NEW: Global LLM behavior config
│   │   └── preset-selector.tsx      # NEW: Quiet/Balanced/Active presets
│   └── room/
│       └── room-llm-settings.tsx    # NEW: Per-room override
├── services/
│   └── websocket/
│       └── types.ts                 # Extend with fork_thread, update_settings
├── stores/
│   ├── threads-store.ts             # NEW: Thread genealogy state
│   └── settings-store.ts            # Extend with LLM heuristic settings
└── hooks/
    ├── use-fork.ts                  # NEW: Fork thread hook
    ├── use-genealogy.ts             # NEW: Fetch and layout genealogy
    └── use-llm-settings.ts          # NEW: Settings management hook

dialectic/
├── api/main.py                      # Add genealogy endpoint, settings endpoint
└── transport/handlers.py            # Add update_room_settings handler
```

### Pattern 1: Fork Thread via Long-Press Context Menu

**What:** Long-press message reveals context menu with "Fork from here" option
**When to use:** Any message in the chat

```typescript
// Source: react-native-hold-menu documentation
// components/chat/message-bubble.tsx - extended
import { HoldItem } from 'react-native-hold-menu';
import { useRouter } from 'expo-router';

interface MessageBubbleProps {
  message: Message;
  threadId: string;
  roomId: string;
}

export function MessageBubble({ message, threadId, roomId }: MessageBubbleProps) {
  const router = useRouter();
  const { forkThread } = useForkThread();

  const handleFork = async () => {
    // Optional: prompt for name
    const title = await promptForThreadName(); // Or skip for auto-generated

    const newThread = await forkThread({
      roomId,
      sourceThreadId: threadId,
      forkAfterMessageId: message.id,
      title,
    });

    // CONTEXT.md: After forking, navigate immediately to new thread
    router.push(`/room/${roomId}/thread/${newThread.id}`);
  };

  const menuItems = [
    { text: 'Fork from here', icon: 'git-branch', onPress: handleFork },
    { text: 'Reply', icon: 'reply', onPress: () => {} },
    { text: 'Copy', icon: 'copy', onPress: () => {} },
  ];

  return (
    <HoldItem items={menuItems} hapticFeedback="medium">
      <View style={styles.bubble}>
        <MarkdownContent content={message.content} />
      </View>
    </HoldItem>
  );
}
```

### Pattern 2: Genealogy Query with Recursive CTE

**What:** Efficient query to fetch full thread tree for a room
**When to use:** Branches screen, genealogy visualization

```python
# Source: PostgreSQL recursive CTE documentation
# Add to dialectic/api/main.py

class ThreadNode(BaseModel):
    id: UUID
    parent_thread_id: Optional[UUID]
    fork_point_message_id: Optional[UUID]
    title: Optional[str]
    message_count: int
    created_at: datetime
    depth: int
    children: List['ThreadNode'] = []

@app.get("/rooms/{room_id}/genealogy")
async def get_thread_genealogy(
    room_id: UUID,
    token: str = Query(...),
    db=Depends(get_db),
):
    """
    Get full thread genealogy for a room as a tree structure.

    ARCHITECTURE: Recursive CTE with depth tracking.
    WHY: Single query fetches entire tree with depth levels.
    TRADEOFF: Memory for deep trees, but rooms rarely exceed 10 levels.
    """
    await verify_room_token(room_id, token, db)

    # Fetch all threads with message counts using recursive CTE
    rows = await db.fetch(
        """
        WITH RECURSIVE thread_tree AS (
            -- Base case: root threads (no parent)
            SELECT
                t.id,
                t.parent_thread_id,
                t.fork_point_message_id,
                t.title,
                t.created_at,
                0 AS depth
            FROM threads t
            WHERE t.room_id = $1 AND t.parent_thread_id IS NULL

            UNION ALL

            -- Recursive case: child threads
            SELECT
                t.id,
                t.parent_thread_id,
                t.fork_point_message_id,
                t.title,
                t.created_at,
                tt.depth + 1
            FROM threads t
            JOIN thread_tree tt ON t.parent_thread_id = tt.id
            WHERE t.room_id = $1
        )
        SELECT
            tt.*,
            (SELECT COUNT(*) FROM messages m WHERE m.thread_id = tt.id) as message_count
        FROM thread_tree tt
        ORDER BY tt.depth, tt.created_at
        """,
        room_id
    )

    # Build tree structure in Python (flat list to tree)
    nodes = {row['id']: ThreadNode(
        id=row['id'],
        parent_thread_id=row['parent_thread_id'],
        fork_point_message_id=row['fork_point_message_id'],
        title=row['title'],
        message_count=row['message_count'],
        created_at=row['created_at'],
        depth=row['depth'],
        children=[],
    ) for row in rows}

    roots = []
    for node in nodes.values():
        if node.parent_thread_id and node.parent_thread_id in nodes:
            nodes[node.parent_thread_id].children.append(node)
        else:
            roots.append(node)

    return roots
```

### Pattern 3: Cladogram Visualization with react-native-svg

**What:** Biological taxonomy-style tree diagram showing thread relationships
**When to use:** Dedicated "Branches" tab/screen

```typescript
// Source: Custom SVG drawing pattern
// components/branches/cladogram-view.tsx
import React, { useMemo } from 'react';
import { View, StyleSheet, ScrollView, Pressable, Text } from 'react-native';
import Svg, { G, Line, Circle } from 'react-native-svg';
import { useRouter } from 'expo-router';

interface ThreadNode {
  id: string;
  parentThreadId: string | null;
  title: string | null;
  messageCount: number;
  createdAt: string;
  depth: number;
  children: ThreadNode[];
}

interface CladogramViewProps {
  roots: ThreadNode[];
  roomId: string;
}

// Constants for cladogram layout
const NODE_WIDTH = 150;
const NODE_HEIGHT = 60;
const HORIZONTAL_SPACING = 40;
const VERTICAL_SPACING = 80;
const CONNECTOR_RADIUS = 4;

export function CladogramView({ roots, roomId }: CladogramViewProps) {
  const router = useRouter();

  // Calculate positions for all nodes (cladogram layout)
  const { nodes, links, dimensions } = useMemo(() => {
    return layoutCladogram(roots);
  }, [roots]);

  const handleNodePress = (node: ThreadNode) => {
    router.push(`/room/${roomId}/thread/${node.id}`);
  };

  return (
    <ScrollView
      style={styles.container}
      horizontal
      contentContainerStyle={styles.scrollContent}
    >
      <ScrollView>
        <Svg
          width={dimensions.width}
          height={dimensions.height}
          viewBox={`0 0 ${dimensions.width} ${dimensions.height}`}
        >
          {/* Draw connectors first (behind nodes) */}
          <G>
            {links.map((link, i) => (
              <CladogramConnector
                key={`link-${i}`}
                x1={link.source.x + NODE_WIDTH}
                y1={link.source.y + NODE_HEIGHT / 2}
                x2={link.target.x}
                y2={link.target.y + NODE_HEIGHT / 2}
              />
            ))}
          </G>
        </Svg>

        {/* Render nodes as native Views (for touch handling) */}
        {nodes.map((node) => (
          <ThreadNodeView
            key={node.id}
            node={node}
            onPress={() => handleNodePress(node)}
            style={{
              position: 'absolute',
              left: node.x,
              top: node.y,
            }}
          />
        ))}
      </ScrollView>
    </ScrollView>
  );
}

// Cladogram-style elbow connector
function CladogramConnector({
  x1, y1, x2, y2
}: { x1: number; y1: number; x2: number; y2: number }) {
  // Cladogram uses horizontal-then-vertical lines (not diagonal)
  const midX = x1 + (x2 - x1) / 2;

  return (
    <G>
      {/* Horizontal line from parent */}
      <Line x1={x1} y1={y1} x2={midX} y2={y1} stroke="#94a3b8" strokeWidth={2} />
      {/* Vertical line */}
      <Line x1={midX} y1={y1} x2={midX} y2={y2} stroke="#94a3b8" strokeWidth={2} />
      {/* Horizontal line to child */}
      <Line x1={midX} y1={y2} x2={x2} y2={y2} stroke="#94a3b8" strokeWidth={2} />
      {/* Junction circle */}
      <Circle cx={midX} cy={y1} r={CONNECTOR_RADIUS} fill="#94a3b8" />
    </G>
  );
}

function ThreadNodeView({
  node,
  onPress,
  style,
}: {
  node: ThreadNode & { x: number; y: number };
  onPress: () => void;
  style: object;
}) {
  return (
    <Pressable
      style={[styles.nodeContainer, style]}
      onPress={onPress}
    >
      <Text style={styles.nodeTitle} numberOfLines={1}>
        {node.title || 'Untitled'}
      </Text>
      <Text style={styles.nodeSubtitle}>
        {node.messageCount} messages
      </Text>
      <Text style={styles.nodeTimestamp}>
        {new Date(node.createdAt).toLocaleDateString()}
      </Text>
    </Pressable>
  );
}

// Layout algorithm for cladogram positioning
function layoutCladogram(roots: ThreadNode[]) {
  const nodes: (ThreadNode & { x: number; y: number })[] = [];
  const links: { source: { x: number; y: number }; target: { x: number; y: number } }[] = [];

  let currentY = 20;

  function traverse(node: ThreadNode, depth: number, parentPos?: { x: number; y: number }) {
    const x = depth * (NODE_WIDTH + HORIZONTAL_SPACING) + 20;
    const y = currentY;

    nodes.push({ ...node, x, y });

    if (parentPos) {
      links.push({
        source: parentPos,
        target: { x, y },
      });
    }

    if (node.children.length === 0) {
      currentY += NODE_HEIGHT + VERTICAL_SPACING;
    } else {
      for (const child of node.children) {
        traverse(child, depth + 1, { x, y });
      }
    }
  }

  for (const root of roots) {
    traverse(root, 0);
  }

  const maxX = Math.max(...nodes.map(n => n.x)) + NODE_WIDTH + 40;
  const maxY = currentY;

  return {
    nodes,
    links,
    dimensions: { width: maxX, height: maxY },
  };
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  scrollContent: {
    padding: 20,
  },
  nodeContainer: {
    width: NODE_WIDTH,
    height: NODE_HEIGHT,
    backgroundColor: '#ffffff',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#e2e8f0',
    padding: 8,
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.05,
    shadowRadius: 2,
    elevation: 1,
  },
  nodeTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: '#1e293b',
  },
  nodeSubtitle: {
    fontSize: 11,
    color: '#64748b',
    marginTop: 2,
  },
  nodeTimestamp: {
    fontSize: 10,
    color: '#94a3b8',
    marginTop: 2,
  },
});
```

### Pattern 4: Proactive Interjection with Indicator

**What:** LLM interjects based on heuristics with subtle "unprompted" indicator
**When to use:** Automatic based on conversation state

```typescript
// Source: CONTEXT.md decisions
// components/ui/llm-message-bubble.tsx - extended for interjection type
import React from 'react';
import { View, Text, StyleSheet, Pressable } from 'react-native';
import { MarkdownContent } from './markdown-content';

interface LLMMessageBubbleProps {
  content: string;
  isStreaming?: boolean;
  isThinking?: boolean;
  modelUsed?: string;
  createdAt?: string;
  // NEW: Distinguish proactive from summoned
  interjectionType: 'summoned' | 'proactive';
  speakerType: 'llm_primary' | 'llm_provoker';
  onStop?: () => void;
}

// CONTEXT.md: Provoker mode uses distinct persona (e.g., "Claude lightning bolt")
const getPersonaName = (speakerType: string, interjectionType: string) => {
  if (speakerType === 'llm_provoker') {
    return 'Claude *'; // Provoker persona
  }
  return 'Claude';
};

export function LLMMessageBubble({
  content,
  isStreaming = false,
  isThinking = false,
  interjectionType,
  speakerType,
  onStop,
}: LLMMessageBubbleProps) {
  const personaName = getPersonaName(speakerType, interjectionType);
  const isProvoker = speakerType === 'llm_provoker';

  return (
    <View style={styles.container}>
      {/* Header with persona and interjection indicator */}
      <View style={styles.header}>
        <View style={[styles.avatar, isProvoker && styles.provokerAvatar]}>
          <Text style={styles.avatarText}>
            {isProvoker ? '*' : 'C'}
          </Text>
        </View>
        <Text style={[styles.label, isProvoker && styles.provokerLabel]}>
          {personaName}
        </Text>
        {/* CONTEXT.md: Subtle indicator for proactive interjections */}
        {interjectionType === 'proactive' && (
          <View style={styles.unpromptedBadge}>
            <Text style={styles.unpromptedText}>unprompted</Text>
          </View>
        )}
      </View>

      {/* Message content or thinking indicator */}
      <View style={[styles.bubble, isProvoker && styles.provokerBubble]}>
        {isThinking ? (
          <ThinkingIndicator />
        ) : (
          <MarkdownContent content={content} isLLM />
        )}

        {/* Streaming cursor */}
        {isStreaming && !isThinking && (
          <View style={styles.streamingCursor} />
        )}
      </View>

      {/* CONTEXT.md: Stop button visible during streaming */}
      {(isStreaming || isThinking) && onStop && (
        <Pressable style={styles.stopButton} onPress={onStop}>
          <Text style={styles.stopButtonText}>Stop</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignSelf: 'center',
    alignItems: 'center',
    maxWidth: '90%',
    marginVertical: 12,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  avatar: {
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: '#6366f1',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 8,
  },
  provokerAvatar: {
    backgroundColor: '#f59e0b', // Amber for provoker
  },
  avatarText: {
    color: '#ffffff',
    fontWeight: 'bold',
    fontSize: 14,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#6366f1',
  },
  provokerLabel: {
    color: '#f59e0b',
  },
  unpromptedBadge: {
    marginLeft: 8,
    backgroundColor: '#f1f5f9',
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  unpromptedText: {
    fontSize: 10,
    color: '#64748b',
    fontStyle: 'italic',
  },
  bubble: {
    backgroundColor: '#eef2ff',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 16,
    minWidth: 120,
  },
  provokerBubble: {
    backgroundColor: '#fef3c7', // Amber-50 for provoker
  },
  streamingCursor: {
    width: 2,
    height: 16,
    backgroundColor: '#6366f1',
    marginLeft: 2,
    opacity: 0.7,
  },
  stopButton: {
    marginTop: 8,
    paddingHorizontal: 16,
    paddingVertical: 6,
    backgroundColor: '#ef4444',
    borderRadius: 16,
  },
  stopButtonText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '600',
  },
});
```

### Pattern 5: Heuristic Configuration UI with Presets

**What:** Settings UI with presets (Quiet/Balanced/Active) and advanced sliders
**When to use:** Global app settings and per-room overrides

```typescript
// Source: CONTEXT.md decisions
// components/settings/llm-settings.tsx
import React, { useState } from 'react';
import { View, Text, StyleSheet, Pressable, Switch } from 'react-native';
import Slider from '@react-native-community/slider';

interface HeuristicSettings {
  preset: 'quiet' | 'balanced' | 'active';
  turnThreshold: number;
  semanticNoveltyThreshold: number;
  stagnationEnabled: boolean;
}

// CONTEXT.md: Preset definitions
const PRESETS: Record<string, Omit<HeuristicSettings, 'preset'>> = {
  quiet: {
    turnThreshold: 8,
    semanticNoveltyThreshold: 0.85,
    stagnationEnabled: false,
  },
  balanced: {
    turnThreshold: 4,
    semanticNoveltyThreshold: 0.7,
    stagnationEnabled: true,
  },
  active: {
    turnThreshold: 2,
    semanticNoveltyThreshold: 0.5,
    stagnationEnabled: true,
  },
};

const PRESET_DESCRIPTIONS = {
  quiet: 'Claude joins less often, only on clear questions or long pauses',
  balanced: 'Claude joins when natural, about every 4-5 messages',
  active: 'Claude joins frequently, eager to contribute',
};

interface LLMSettingsProps {
  settings: HeuristicSettings;
  onSettingsChange: (settings: HeuristicSettings) => void;
  isRoomOverride?: boolean;
}

export function LLMSettings({
  settings,
  onSettingsChange,
  isRoomOverride = false,
}: LLMSettingsProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handlePresetSelect = (preset: 'quiet' | 'balanced' | 'active') => {
    onSettingsChange({
      ...PRESETS[preset],
      preset,
    });
  };

  const handleAdvancedChange = (
    key: keyof Omit<HeuristicSettings, 'preset'>,
    value: number | boolean
  ) => {
    onSettingsChange({
      ...settings,
      preset: 'custom' as any, // Mark as custom when using advanced
      [key]: value,
    });
  };

  return (
    <View style={styles.container}>
      {isRoomOverride && (
        <Text style={styles.overrideLabel}>
          Room Override (overrides global settings)
        </Text>
      )}

      <Text style={styles.sectionTitle}>Claude Behavior</Text>

      {/* Preset Selector */}
      <View style={styles.presetsContainer}>
        {(['quiet', 'balanced', 'active'] as const).map((preset) => (
          <Pressable
            key={preset}
            style={[
              styles.presetButton,
              settings.preset === preset && styles.presetButtonActive,
            ]}
            onPress={() => handlePresetSelect(preset)}
          >
            <Text
              style={[
                styles.presetButtonText,
                settings.preset === preset && styles.presetButtonTextActive,
              ]}
            >
              {preset.charAt(0).toUpperCase() + preset.slice(1)}
            </Text>
          </Pressable>
        ))}
      </View>

      {/* Preset Description */}
      <Text style={styles.presetDescription}>
        {PRESET_DESCRIPTIONS[settings.preset] || 'Custom settings'}
      </Text>

      {/* Advanced Toggle */}
      <Pressable
        style={styles.advancedToggle}
        onPress={() => setShowAdvanced(!showAdvanced)}
      >
        <Text style={styles.advancedToggleText}>
          {showAdvanced ? 'Hide Advanced' : 'Show Advanced'}
        </Text>
      </Pressable>

      {/* Advanced Sliders */}
      {showAdvanced && (
        <View style={styles.advancedContainer}>
          {/* Turn Threshold */}
          <View style={styles.sliderContainer}>
            <Text style={styles.sliderLabel}>
              Turn Threshold: {settings.turnThreshold}
            </Text>
            <Text style={styles.sliderDescription}>
              Claude joins after this many human messages
            </Text>
            <Slider
              style={styles.slider}
              minimumValue={2}
              maximumValue={12}
              step={1}
              value={settings.turnThreshold}
              onValueChange={(v) => handleAdvancedChange('turnThreshold', v)}
              minimumTrackTintColor="#6366f1"
              maximumTrackTintColor="#e2e8f0"
              thumbTintColor="#6366f1"
            />
          </View>

          {/* Semantic Novelty Threshold */}
          <View style={styles.sliderContainer}>
            <Text style={styles.sliderLabel}>
              Novelty Sensitivity: {(settings.semanticNoveltyThreshold * 100).toFixed(0)}%
            </Text>
            <Text style={styles.sliderDescription}>
              How different a message must be to trigger a response
            </Text>
            <Slider
              style={styles.slider}
              minimumValue={0.3}
              maximumValue={0.95}
              step={0.05}
              value={settings.semanticNoveltyThreshold}
              onValueChange={(v) => handleAdvancedChange('semanticNoveltyThreshold', v)}
              minimumTrackTintColor="#6366f1"
              maximumTrackTintColor="#e2e8f0"
              thumbTintColor="#6366f1"
            />
          </View>

          {/* Stagnation Detection */}
          <View style={styles.switchContainer}>
            <View>
              <Text style={styles.sliderLabel}>Stagnation Detection</Text>
              <Text style={styles.sliderDescription}>
                Claude nudges when conversation gets stuck
              </Text>
            </View>
            <Switch
              value={settings.stagnationEnabled}
              onValueChange={(v) => handleAdvancedChange('stagnationEnabled', v)}
              trackColor={{ false: '#e2e8f0', true: '#c7d2fe' }}
              thumbColor={settings.stagnationEnabled ? '#6366f1' : '#f4f4f5'}
            />
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 16,
  },
  overrideLabel: {
    fontSize: 12,
    color: '#6366f1',
    fontWeight: '500',
    marginBottom: 12,
    fontStyle: 'italic',
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1e293b',
    marginBottom: 16,
  },
  presetsContainer: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 8,
  },
  presetButton: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 8,
    backgroundColor: '#f1f5f9',
    alignItems: 'center',
  },
  presetButtonActive: {
    backgroundColor: '#6366f1',
  },
  presetButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#64748b',
  },
  presetButtonTextActive: {
    color: '#ffffff',
  },
  presetDescription: {
    fontSize: 13,
    color: '#64748b',
    marginBottom: 16,
    fontStyle: 'italic',
  },
  advancedToggle: {
    paddingVertical: 8,
    marginBottom: 8,
  },
  advancedToggleText: {
    fontSize: 14,
    color: '#6366f1',
    fontWeight: '500',
  },
  advancedContainer: {
    marginTop: 8,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: '#e2e8f0',
  },
  sliderContainer: {
    marginBottom: 24,
  },
  sliderLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1e293b',
    marginBottom: 2,
  },
  sliderDescription: {
    fontSize: 12,
    color: '#64748b',
    marginBottom: 8,
  },
  slider: {
    width: '100%',
    height: 40,
  },
  switchContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
});
```

### Pattern 6: Stream Cancellation

**What:** Cancel in-progress LLM streaming response
**When to use:** User taps stop button during streaming

```typescript
// Source: Extend services/websocket/types.ts
// Mobile: send cancel_llm command
export interface CancelLLMPayload {
  thread_id: string;
}

// hooks/use-llm.ts - extended
export function useLLM(threadId: string) {
  const { cancelResponse } = useLLMStore();

  const cancelStream = useCallback(() => {
    // Send cancel to server
    websocketService.send({
      type: 'cancel_llm',
      payload: { thread_id: threadId },
    });

    // Immediately clear local UI state
    cancelResponse();
  }, [threadId, cancelResponse]);

  return {
    // ... existing
    cancelStream,
  };
}
```

```python
# Source: Backend cancellation tracking
# dialectic/transport/handlers.py - extend _handle_cancel_llm

from asyncio import Task, CancelledError

class MessageHandler:
    def __init__(self, ...):
        # ... existing
        self._active_streams: dict[UUID, Task] = {}  # Track active streaming tasks

    async def _handle_summon_llm(self, conn: Connection, payload: dict) -> None:
        """Handle @Claude summon with cancellation support."""
        thread_id = UUID(payload.get("thread_id") or str(conn.thread_id))

        # Cancel any existing stream for this thread
        if thread_id in self._active_streams:
            self._active_streams[thread_id].cancel()

        # Create task for streaming (allows cancellation)
        task = asyncio.create_task(
            self._stream_llm_response(conn, thread_id, payload)
        )
        self._active_streams[thread_id] = task

        try:
            await task
        except CancelledError:
            logger.info(f"Stream cancelled for thread {thread_id}")
        finally:
            self._active_streams.pop(thread_id, None)

    async def _handle_cancel_llm(self, conn: Connection, payload: dict) -> None:
        """Cancel in-progress LLM stream."""
        thread_id = payload.get("thread_id")
        if thread_id:
            thread_uuid = UUID(thread_id)
            task = self._active_streams.get(thread_uuid)
            if task and not task.done():
                task.cancel()
                logger.info(f"Cancelled LLM stream for thread {thread_id}")

        # Acknowledge cancellation
        await self.connections.send_to_user(conn.user_id, conn.room_id, OutboundMessage(
            type=MessageTypes.LLM_CANCELLED,
            payload={"thread_id": thread_id},
        ))
```

### Anti-Patterns to Avoid

- **Fetching genealogy on every message:** Cache tree structure, update on fork events only
- **Deep tree recursion without limits:** Always add max_depth to recursive CTEs (e.g., 20)
- **Blocking UI during fork:** Fork is a network operation; show optimistic UI immediately
- **Ignoring proactive vs summoned distinction:** Users find excessive interjections annoying without context
- **No cancel mechanism for LLM:** Users must be able to stop unwanted responses
- **Slider with raw values:** Always show human-readable labels (not 0.7, but "70%")

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Long-press context menu | Custom gesture + portal | `react-native-hold-menu` | Animations, haptics, positioning handled |
| Tree layout algorithm | Manual coordinate math | d3-hierarchy or custom cladogram algo | Edge cases with deep/wide trees |
| Slider with gestures | Custom PanResponder | `@react-native-community/slider` | Native feel, accessibility |
| Cancel streaming | Ignore partial response | asyncio.CancelledError + task tracking | Clean cancellation, no zombie streams |
| Recursive tree query | Multiple sequential queries | PostgreSQL recursive CTE | Single query, depth tracking built-in |

**Key insight:** Fork and genealogy seem simple but have edge cases: what happens with very deep trees? What if user forks while offline? What if cancel arrives mid-token? Libraries and established patterns handle these.

## Common Pitfalls

### Pitfall 1: Fork Point Message Not Included

**What goes wrong:** Forked thread starts with message AFTER fork point, missing context
**Why it happens:** Off-by-one in fork_after_message_id logic
**How to avoid:**
- Backend operations.py correctly uses `<= fork_point_seq` (already correct)
- Test that fork includes the fork point message itself
**Warning signs:** Forked threads missing the message user long-pressed on

### Pitfall 2: Genealogy Visualization Too Slow

**What goes wrong:** Branches screen takes seconds to render with many threads
**Why it happens:** O(n^2) layout algorithm or fetching all messages
**How to avoid:**
- Only fetch thread metadata (not messages) for genealogy
- Use memoized layout calculation
- Consider virtualization for very large trees (>100 nodes)
**Warning signs:** Lag on Branches tab, ANR warnings on Android

### Pitfall 3: Proactive Interjection Feels Intrusive

**What goes wrong:** Users annoyed by Claude jumping in too often
**Why it happens:** Default thresholds too aggressive, no visual distinction
**How to avoid:**
- CONTEXT.md: "unprompted" badge distinguishes proactive from summoned
- Default to "Balanced" preset, not "Active"
- Minimum is "Quiet", never fully disabled
**Warning signs:** User complaints about Claude being "annoying"

### Pitfall 4: Settings Not Persisting

**What goes wrong:** User changes thresholds, restarts app, settings reset
**Why it happens:** Not persisting to both MMKV (local) and server (per-room)
**How to avoid:**
- Global settings: MMKV (immediate) + sync to server on next connect
- Per-room settings: API call to update rooms table
- Load from local first, then validate against server
**Warning signs:** Settings reset after app restart

### Pitfall 5: Cancel Doesn't Actually Cancel

**What goes wrong:** User taps stop, response keeps streaming
**Why it happens:** Missing task tracking in backend, or only clearing UI state
**How to avoid:**
- Backend must track active streaming tasks per thread
- On cancel, call task.cancel() to interrupt httpx stream
- Client must clear partialResponse AND streaming flags
**Warning signs:** Response continues after cancel, or ghost text

### Pitfall 6: Tree Layout Overlapping Nodes

**What goes wrong:** Nodes overlap in cladogram when tree is wide
**Why it happens:** Not accounting for sibling width in layout algorithm
**How to avoid:**
- Use proper tree layout (reserve vertical space for descendants)
- Calculate "subtree height" before positioning parent
- Test with trees that have many siblings at same level
**Warning signs:** Overlapping rectangles in Branches view

### Pitfall 7: Thinking Indicator Before Proactive Interjection

**What goes wrong:** User confused why Claude is thinking when no one mentioned it
**Why it happens:** Showing thinking for heuristic interjection same as summoned
**How to avoid:**
- CONTEXT.md: Show thinking indicator for 1-2 seconds before proactive response
- Add slight delay before starting stream for proactive
- Distinguish visually from summoned response thinking
**Warning signs:** User surprise at unprompted thinking indicator

## Code Examples

### Backend: Room Settings Update Endpoint

```python
# Source: Extend dialectic/api/main.py

class UpdateRoomSettingsRequest(BaseModel):
    interjection_turn_threshold: Optional[int] = None
    semantic_novelty_threshold: Optional[float] = None
    auto_interjection_enabled: Optional[bool] = None

@app.patch("/rooms/{room_id}/settings")
async def update_room_settings(
    room_id: UUID,
    request: UpdateRoomSettingsRequest,
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """Update room LLM settings."""
    await verify_room_token(room_id, token, db)

    updates = []
    params = [room_id]
    param_idx = 2

    if request.interjection_turn_threshold is not None:
        updates.append(f"interjection_turn_threshold = ${param_idx}")
        params.append(request.interjection_turn_threshold)
        param_idx += 1

    if request.semantic_novelty_threshold is not None:
        updates.append(f"semantic_novelty_threshold = ${param_idx}")
        params.append(request.semantic_novelty_threshold)
        param_idx += 1

    if request.auto_interjection_enabled is not None:
        updates.append(f"auto_interjection_enabled = ${param_idx}")
        params.append(request.auto_interjection_enabled)
        param_idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No settings to update")

    query = f"UPDATE rooms SET {', '.join(updates)} WHERE id = $1"
    await db.execute(query, *params)

    # Log event
    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid4(), datetime.utcnow(), EventType.ROOM_SETTINGS_UPDATED.value,
        room_id, user_id, request.model_dump(exclude_none=True)
    )

    return {"status": "updated"}
```

### Mobile: Fork Thread Hook

```typescript
// Source: Mobile client pattern
// hooks/use-fork.ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/services/api';
import { websocketService } from '@/services/websocket';

interface ForkParams {
  roomId: string;
  sourceThreadId: string;
  forkAfterMessageId: string;
  title?: string;
}

interface ThreadResponse {
  id: string;
  room_id: string;
  parent_thread_id: string;
  title: string | null;
  message_count: number;
}

export function useForkThread() {
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: async (params: ForkParams): Promise<ThreadResponse> => {
      // Can use REST or WebSocket - REST is simpler for mutations
      const response = await api.post(
        `/threads/${params.sourceThreadId}/fork`,
        {
          source_thread_id: params.sourceThreadId,
          fork_after_message_id: params.forkAfterMessageId,
          title: params.title,
        }
      );
      return response.data;
    },

    onSuccess: (newThread, params) => {
      // Invalidate threads list to show new thread
      queryClient.invalidateQueries({
        queryKey: ['threads', params.roomId],
      });

      // Invalidate genealogy
      queryClient.invalidateQueries({
        queryKey: ['genealogy', params.roomId],
      });
    },
  });

  return {
    forkThread: mutation.mutateAsync,
    isForking: mutation.isPending,
    error: mutation.error,
  };
}
```

### Mobile: Genealogy Hook

```typescript
// Source: Mobile client pattern
// hooks/use-genealogy.ts
import { useQuery } from '@tanstack/react-query';
import { api } from '@/services/api';

interface ThreadNode {
  id: string;
  parent_thread_id: string | null;
  fork_point_message_id: string | null;
  title: string | null;
  message_count: number;
  created_at: string;
  depth: number;
  children: ThreadNode[];
}

export function useGenealogy(roomId: string) {
  return useQuery({
    queryKey: ['genealogy', roomId],
    queryFn: async (): Promise<ThreadNode[]> => {
      const response = await api.get(`/rooms/${roomId}/genealogy`);
      return response.data;
    },
    staleTime: 30000, // Cache for 30 seconds
  });
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat thread list | Tree genealogy with fork visualization | Dialectic-specific | Better conversation history understanding |
| Binary LLM enable/disable | Preset + advanced sliders | 2024+ | More nuanced control over AI participation |
| Tap-only interactions | Long-press context menus | iOS 13+ standard | Discoverable advanced actions |
| Aggressive AI interjection | Heuristic-based with thresholds | 2025+ | Less annoying, more contextual |
| Single AI persona | Mode-based personas (primary/provoker) | Dialectic-specific | Different conversation dynamics |

**Deprecated/outdated:**
- Simple tap menus for context actions: Long-press is standard for mobile
- Global AI on/off toggle: Fine-grained control preferred
- D3.js DOM manipulation in React Native: Use react-native-svg directly

## Open Questions

Things that couldn't be fully resolved:

1. **Maximum tree depth for genealogy**
   - What we know: Recursive CTEs need depth limits to prevent runaway queries
   - What's unclear: What's a reasonable max depth for conversations?
   - Recommendation: Start with 20, add pagination/virtualization if exceeded

2. **Thinking delay for proactive interjections**
   - What we know: CONTEXT.md says 1-2 seconds thinking indicator
   - What's unclear: Should this be configurable? Does it vary by context?
   - Recommendation: Start with 1.5 seconds fixed, may adjust based on feedback

3. **Offline fork behavior**
   - What we know: Fork requires server round-trip for new thread ID
   - What's unclear: Should we allow optimistic fork creation offline?
   - Recommendation: Require online for fork (show error if offline), queue is complex

4. **Very wide trees in cladogram**
   - What we know: Many siblings at same level will cause horizontal overflow
   - What's unclear: At what point to collapse or virtualize?
   - Recommendation: Allow horizontal scroll, add collapse if >10 children

## Sources

### Primary (HIGH confidence)

- [PostgreSQL Recursive CTEs](https://www.postgresql.org/docs/current/queries-with.html) - Official documentation
- [react-native-hold-menu](https://github.com/enesozturk/react-native-hold-menu) - Context menu library
- [react-native-svg](https://docs.expo.dev/versions/latest/sdk/svg/) - Expo SVG documentation
- [@react-native-community/slider](https://github.com/callstack/react-native-slider) - Slider component
- Existing codebase: `dialectic/operations.py` - Fork implementation
- Existing codebase: `dialectic/llm/heuristics.py` - Interjection engine

### Secondary (MEDIUM confidence)

- [react-native-gesture-handler Long Press](https://docs.swmansion.com/react-native-gesture-handler/docs/gestures/long-press-gesture/) - Gesture documentation
- [d3-hierarchy](https://github.com/d3/d3-hierarchy) - Tree layout algorithms
- [PostgreSQL Tree Patterns](https://wiki.postgresql.org/wiki/Getting_list_of_all_children_from_adjacency_tree) - Adjacency list queries

### Tertiary (LOW confidence)

- WebSearch results for cladogram visualization in React - Limited RN-specific results
- Medium articles on tree layouts - Needs validation with react-native-svg

## Metadata

**Confidence breakdown:**
- Fork implementation: HIGH - Backend already exists, well-documented
- Genealogy query: HIGH - Standard PostgreSQL recursive CTE
- Cladogram visualization: MEDIUM - Custom implementation, no perfect library
- Heuristic configuration: HIGH - Backend schema exists, UI is standard patterns
- Stream cancellation: MEDIUM - Requires careful asyncio task management
- Long-press menu: HIGH - react-native-hold-menu is well-documented

**Research date:** 2026-01-25
**Valid until:** 2026-02-25 (30 days - stable ecosystem)
