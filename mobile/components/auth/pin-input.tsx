/**
 * ARCHITECTURE: Number pad component for PIN entry.
 * WHY: Custom keypad provides consistent UX across platforms vs native keyboard.
 * TRADEOFF: More code vs TextInput, but better control over layout and behavior.
 */

import { View, Text, StyleSheet, Pressable } from 'react-native';
import { useState, useEffect } from 'react';
import { useThemeColor } from '@/hooks/use-theme-color';

interface PinInputProps {
  length?: number;
  onComplete: (pin: string) => void;
  error?: string;
  label?: string;
}

export function PinInput({
  length = 6,
  onComplete,
  error,
  label,
}: PinInputProps) {
  const [pin, setPin] = useState('');
  const textColor = useThemeColor({}, 'text');

  useEffect(() => {
    if (pin.length === length) {
      onComplete(pin);
      // Reset after a short delay to allow for verification feedback
      setTimeout(() => setPin(''), 300);
    }
  }, [pin, length, onComplete]);

  const handlePress = (digit: string) => {
    if (pin.length < length) {
      setPin((prev) => prev + digit);
    }
  };

  const handleDelete = () => {
    setPin((prev) => prev.slice(0, -1));
  };

  const digits = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', 'del'];

  return (
    <View style={styles.container}>
      {label && <Text style={[styles.label, { color: textColor }]}>{label}</Text>}

      <View style={styles.dotsContainer}>
        {Array.from({ length }).map((_, i) => (
          <View
            key={i}
            style={[
              styles.dot,
              i < pin.length && styles.dotFilled,
              error && styles.dotError,
            ]}
          />
        ))}
      </View>

      {error && <Text style={styles.error}>{error}</Text>}

      <View style={styles.keypad}>
        {digits.map((digit, i) => (
          <Pressable
            key={i}
            style={[styles.key, !digit && styles.keyEmpty]}
            onPress={() => {
              if (digit === 'del') {
                handleDelete();
              } else if (digit) {
                handlePress(digit);
              }
            }}
            disabled={!digit}
          >
            <Text style={[styles.keyText, { color: textColor }]}>
              {digit === 'del' ? '\u232B' : digit}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
  },
  label: {
    fontSize: 16,
    marginBottom: 24,
  },
  dotsContainer: {
    flexDirection: 'row',
    marginBottom: 24,
    gap: 16,
  },
  dot: {
    width: 16,
    height: 16,
    borderRadius: 8,
    borderWidth: 2,
    borderColor: '#d1d5db',
  },
  dotFilled: {
    backgroundColor: '#3b82f6',
    borderColor: '#3b82f6',
  },
  dotError: {
    borderColor: '#ef4444',
  },
  error: {
    color: '#ef4444',
    fontSize: 14,
    marginBottom: 16,
  },
  keypad: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    width: 280,
    justifyContent: 'center',
  },
  key: {
    width: 80,
    height: 80,
    justifyContent: 'center',
    alignItems: 'center',
    margin: 4,
  },
  keyEmpty: {
    opacity: 0,
  },
  keyText: {
    fontSize: 28,
    fontWeight: '500',
  },
});
