/**
 * ARCHITECTURE: Render text with highlighted search matches.
 * WHY: Visual feedback for search relevance.
 * TRADEOFF: Regex parsing vs structured data, but snippets come as strings.
 */

import React from 'react';
import { Text, StyleSheet, TextStyle } from 'react-native';

interface HighlightedTextProps {
  text: string;
  style?: TextStyle;
  highlightStyle?: TextStyle;
}

/**
 * Renders text with <mark> tags converted to highlighted spans.
 *
 * @example
 * <HighlightedText text="Hello <mark>world</mark>!" />
 * // Renders "Hello " in normal text and "world" highlighted
 */
export function HighlightedText({
  text,
  style,
  highlightStyle,
}: HighlightedTextProps) {
  // Split by <mark> and </mark> tags
  const parts = text.split(/(<mark>|<\/mark>)/);

  let isHighlighted = false;
  const elements: React.ReactNode[] = [];

  for (let i = 0; i < parts.length; i++) {
    const part = parts[i];

    if (part === '<mark>') {
      isHighlighted = true;
      continue;
    }

    if (part === '</mark>') {
      isHighlighted = false;
      continue;
    }

    if (part) {
      elements.push(
        <Text
          key={i}
          style={[
            style,
            isHighlighted && [styles.highlight, highlightStyle],
          ]}
        >
          {part}
        </Text>
      );
    }
  }

  return <Text style={style}>{elements}</Text>;
}

const styles = StyleSheet.create({
  highlight: {
    backgroundColor: '#fef08a', // Yellow highlight
    fontWeight: '600',
  },
});
