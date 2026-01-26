/**
 * ARCHITECTURE: Text input with @Claude mention detection and highlighting.
 * WHY: CONTEXT.md requires explicit LLM summon via @mention.
 * TRADEOFF: Library dependency vs custom parsing complexity.
 */

import React, { useCallback, useState, useMemo } from 'react';
import {
  View,
  StyleSheet,
  TouchableOpacity,
  Text,
  useColorScheme,
} from 'react-native';
import {
  MentionInput as RNMentionInput,
  SuggestionsProvidedProps,
  Suggestion,
  TriggersConfig,
  Triggers,
} from 'react-native-controlled-mentions';
import { useMentionDetection } from '@/hooks/use-mention-detection';

interface MentionInputProps {
  value: string;
  onChange: (text: string) => void;
  onSubmit: () => void;
  onMentionDetected?: (hasMention: boolean) => void;
  placeholder?: string;
  editable?: boolean;
}

// Only Claude is a valid mention target
const suggestions: Suggestion[] = [{ id: 'claude', name: 'Claude' }];

// Define trigger name as string literal type
type TriggerName = 'mention';

// Trigger configuration for @mentions
const triggersConfig: TriggersConfig<TriggerName> = {
  mention: {
    trigger: '@',
    allowedSpacesCount: 0,
    isInsertSpaceAfterMention: true,
    textStyle: {
      fontWeight: 'bold',
      color: '#6366f1', // Indigo - Claude's color
    },
  },
};

export function MentionInput({
  value,
  onChange,
  onSubmit,
  onMentionDetected,
  placeholder = 'Type a message...',
  editable = true,
}: MentionInputProps) {
  const colorScheme = useColorScheme();
  const isDark = colorScheme === 'dark';
  const [currentTriggers, setCurrentTriggers] = useState<Triggers<TriggerName>>(
    {} as Triggers<TriggerName>
  );

  const { detectMention } = useMentionDetection({
    onMentionDetected,
  });

  const handleChange = useCallback(
    (text: string) => {
      onChange(text);
      detectMention(text);
    },
    [onChange, detectMention]
  );

  const handleTriggersChange = useCallback(
    (triggers: Triggers<TriggerName>) => {
      setCurrentTriggers(triggers);
    },
    []
  );

  // Render suggestions popup when @ is typed
  const renderSuggestions = useCallback((): React.ReactNode => {
    const mentionProps = currentTriggers.mention;
    if (!mentionProps || mentionProps.keyword === undefined) {
      return null;
    }

    const { keyword, onSelect } = mentionProps;

    // Filter to suggestions matching the keyword
    const filtered = suggestions.filter((s) =>
      s.name.toLowerCase().startsWith(keyword.toLowerCase())
    );

    if (filtered.length === 0) {
      return null;
    }

    return (
      <View
        style={[
          styles.suggestionsContainer,
          isDark && styles.suggestionsContainerDark,
        ]}
      >
        {filtered.map((suggestion) => (
          <TouchableOpacity
            key={suggestion.id}
            style={styles.suggestionItem}
            onPress={() => onSelect(suggestion)}
          >
            <View style={styles.suggestionAvatar}>
              <Text style={styles.suggestionAvatarText}>C</Text>
            </View>
            <Text
              style={[
                styles.suggestionText,
                isDark && styles.suggestionTextDark,
              ]}
            >
              {suggestion.name}
            </Text>
          </TouchableOpacity>
        ))}
      </View>
    );
  }, [currentTriggers, isDark]);

  return (
    <View style={styles.container}>
      {renderSuggestions()}
      <RNMentionInput<TriggerName>
        value={value}
        onChange={handleChange}
        triggersConfig={triggersConfig}
        onTriggersChange={handleTriggersChange}
        placeholder={placeholder}
        placeholderTextColor={isDark ? '#6b7280' : '#9ca3af'}
        style={[styles.input, isDark && styles.inputDark]}
        editable={editable}
        multiline
        onSubmitEditing={onSubmit}
        blurOnSubmit={false}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  input: {
    fontSize: 16,
    paddingHorizontal: 16,
    paddingVertical: 12,
    maxHeight: 120,
    color: '#1f2937',
  },
  inputDark: {
    color: '#f9fafb',
  },
  suggestionsContainer: {
    position: 'absolute',
    bottom: '100%',
    left: 0,
    right: 0,
    backgroundColor: '#ffffff',
    borderTopLeftRadius: 12,
    borderTopRightRadius: 12,
    borderWidth: 1,
    borderColor: '#e5e7eb',
    borderBottomWidth: 0,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: -2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 4,
    zIndex: 1000,
  },
  suggestionsContainerDark: {
    backgroundColor: '#1f2937',
    borderColor: '#374151',
  },
  suggestionItem: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 12,
  },
  suggestionAvatar: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: '#6366f1',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
  },
  suggestionAvatarText: {
    color: '#ffffff',
    fontWeight: 'bold',
    fontSize: 14,
  },
  suggestionText: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1f2937',
  },
  suggestionTextDark: {
    color: '#f9fafb',
  },
});
