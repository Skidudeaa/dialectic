/**
 * ARCHITECTURE: Markdown renderer using react-native-markdown-display.
 * WHY: CONTEXT.md requires full markdown for LLM responses.
 * TRADEOFF: Library dependency vs hand-rolled parsing.
 */

import React, { useMemo } from 'react';
import { StyleSheet, useColorScheme } from 'react-native';
import Markdown from 'react-native-markdown-display';

interface MarkdownContentProps {
  content: string;
  isLLM?: boolean;
}

export function MarkdownContent({ content, isLLM = false }: MarkdownContentProps) {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';

  const styles = useMemo(
    () =>
      StyleSheet.create({
        body: {
          fontSize: 16,
          lineHeight: 24,
          color: isLLM ? '#1f2937' : isDark ? '#f9fafb' : '#1f2937',
        },
        heading1: {
          fontSize: 24,
          fontWeight: 'bold',
          marginTop: 12,
          marginBottom: 8,
          color: isDark ? '#f9fafb' : '#1f2937',
        },
        heading2: {
          fontSize: 20,
          fontWeight: 'bold',
          marginTop: 10,
          marginBottom: 6,
          color: isDark ? '#f9fafb' : '#1f2937',
        },
        heading3: {
          fontSize: 18,
          fontWeight: '600',
          marginTop: 8,
          marginBottom: 4,
          color: isDark ? '#f9fafb' : '#1f2937',
        },
        paragraph: {
          marginTop: 0,
          marginBottom: 8,
        },
        bullet_list: {
          marginLeft: 8,
        },
        ordered_list: {
          marginLeft: 8,
        },
        list_item: {
          marginBottom: 4,
        },
        code_inline: {
          backgroundColor: isDark ? '#374151' : '#f3f4f6',
          paddingHorizontal: 6,
          paddingVertical: 2,
          borderRadius: 4,
          fontFamily: 'monospace',
          fontSize: 14,
        },
        code_block: {
          backgroundColor: isDark ? '#1f2937' : '#f3f4f6',
          padding: 12,
          borderRadius: 8,
          marginVertical: 8,
          fontFamily: 'monospace',
          fontSize: 14,
        },
        fence: {
          backgroundColor: isDark ? '#1f2937' : '#f3f4f6',
          padding: 12,
          borderRadius: 8,
          marginVertical: 8,
          fontFamily: 'monospace',
          fontSize: 14,
        },
        blockquote: {
          backgroundColor: isDark ? '#374151' : '#f9fafb',
          borderLeftWidth: 4,
          borderLeftColor: '#6366f1',
          paddingLeft: 12,
          paddingVertical: 4,
          marginVertical: 8,
        },
        link: {
          color: '#6366f1',
          textDecorationLine: 'underline',
        },
        strong: {
          fontWeight: 'bold',
        },
        em: {
          fontStyle: 'italic',
        },
      }),
    [isDark, isLLM]
  );

  return <Markdown style={styles}>{content}</Markdown>;
}
