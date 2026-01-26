/**
 * ARCHITECTURE: Cladogram tree visualization using react-native-svg.
 * WHY: Biological taxonomy-style diagram shows thread ancestry visually.
 * TRADEOFF: Custom layout algorithm vs library, but provides exact styling control.
 */

import React, { useMemo, useCallback } from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import Svg, { G, Line, Circle } from 'react-native-svg';
import { useRouter } from 'expo-router';
import { ThreadNodeView, NODE_WIDTH, NODE_HEIGHT } from './thread-node';
import type { ThreadNode } from '@/hooks/use-genealogy';

interface CladogramViewProps {
  roots: ThreadNode[];
  roomId: string;
  currentThreadId?: string;
}

const HORIZONTAL_SPACING = 40;
const VERTICAL_SPACING = 80;
const PADDING = 20;
const CONNECTOR_RADIUS = 4;

interface PositionedNode extends ThreadNode {
  x: number;
  y: number;
}

interface Link {
  source: { x: number; y: number };
  target: { x: number; y: number };
}

function layoutCladogram(roots: ThreadNode[]): {
  nodes: PositionedNode[];
  links: Link[];
  dimensions: { width: number; height: number };
} {
  const nodes: PositionedNode[] = [];
  const links: Link[] = [];
  let currentY = PADDING;

  function traverse(
    node: ThreadNode,
    depth: number,
    parentPos?: { x: number; y: number }
  ) {
    const x = depth * (NODE_WIDTH + HORIZONTAL_SPACING) + PADDING;
    const y = currentY;

    nodes.push({ ...node, x, y });

    if (parentPos) {
      links.push({
        source: parentPos,
        target: { x, y },
      });
    }

    if (node.children.length === 0) {
      // Leaf node - advance Y for next sibling/cousin
      currentY += NODE_HEIGHT + VERTICAL_SPACING;
    } else {
      // Branch node - traverse children first
      for (const child of node.children) {
        traverse(child, depth + 1, { x, y });
      }
    }
  }

  for (const root of roots) {
    traverse(root, 0);
  }

  const maxX = nodes.length > 0
    ? Math.max(...nodes.map((n) => n.x)) + NODE_WIDTH + PADDING
    : PADDING * 2;
  const maxY = currentY;

  return {
    nodes,
    links,
    dimensions: { width: maxX, height: maxY },
  };
}

// Cladogram-style connector (horizontal-then-vertical)
function CladogramConnector({
  x1,
  y1,
  x2,
  y2
}: {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}) {
  const midX = x1 + (x2 - x1) / 2;
  const sourceY = y1 + NODE_HEIGHT / 2;
  const targetY = y2 + NODE_HEIGHT / 2;

  return (
    <G>
      {/* Horizontal from parent */}
      <Line
        x1={x1 + NODE_WIDTH}
        y1={sourceY}
        x2={midX}
        y2={sourceY}
        stroke="#94a3b8"
        strokeWidth={2}
      />
      {/* Vertical connector */}
      <Line
        x1={midX}
        y1={sourceY}
        x2={midX}
        y2={targetY}
        stroke="#94a3b8"
        strokeWidth={2}
      />
      {/* Horizontal to child */}
      <Line
        x1={midX}
        y1={targetY}
        x2={x2}
        y2={targetY}
        stroke="#94a3b8"
        strokeWidth={2}
      />
      {/* Junction circle */}
      <Circle cx={midX} cy={sourceY} r={CONNECTOR_RADIUS} fill="#94a3b8" />
    </G>
  );
}

export function CladogramView({
  roots,
  roomId,
  currentThreadId,
}: CladogramViewProps) {
  const router = useRouter();

  const { nodes, links, dimensions } = useMemo(
    () => layoutCladogram(roots),
    [roots]
  );

  const handleNodePress = useCallback(
    (node: ThreadNode) => {
      // Type assertion needed as dynamic route structure isn't fully typed
      (router.push as (path: string) => void)(
        `/room/${roomId}/thread/${node.id}`
      );
    },
    [roomId, router]
  );

  return (
    <ScrollView
      style={styles.container}
      horizontal
      contentContainerStyle={styles.scrollContent}
    >
      <ScrollView>
        <View style={{ width: dimensions.width, height: dimensions.height }}>
          {/* SVG for connectors */}
          <Svg
            width={dimensions.width}
            height={dimensions.height}
            style={StyleSheet.absoluteFill}
          >
            <G>
              {links.map((link, i) => (
                <CladogramConnector
                  key={`link-${i}`}
                  x1={link.source.x}
                  y1={link.source.y}
                  x2={link.target.x}
                  y2={link.target.y}
                />
              ))}
            </G>
          </Svg>

          {/* Native Views for nodes (touch handling) */}
          {nodes.map((node) => (
            <View
              key={node.id}
              style={{
                position: 'absolute',
                left: node.x,
                top: node.y,
              }}
            >
              <ThreadNodeView
                node={node}
                onPress={() => handleNodePress(node)}
                isCurrentThread={node.id === currentThreadId}
              />
            </View>
          ))}
        </View>
      </ScrollView>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8fafc',
  },
  scrollContent: {
    padding: PADDING,
  },
});
