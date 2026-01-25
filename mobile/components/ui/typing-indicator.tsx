import React, { useEffect } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withRepeat,
  withTiming,
  withDelay,
  withSequence,
} from 'react-native-reanimated';

interface TypingUser {
  userId: string;
  displayName: string;
}

interface TypingIndicatorProps {
  users: TypingUser[];
}

/**
 * ARCHITECTURE: Animated dots typing indicator.
 * WHY: CONTEXT.md specifies classic "..." animation with stacked indicators.
 * TRADEOFF: Animation complexity vs visual feedback value.
 */
export function TypingIndicator({ users }: TypingIndicatorProps) {
  if (users.length === 0) return null;

  return (
    <View style={styles.container}>
      {users.map((user) => (
        <View key={user.userId} style={styles.userRow}>
          <Text style={styles.name}>{user.displayName}</Text>
          <AnimatedDots />
        </View>
      ))}
    </View>
  );
}

function AnimatedDots() {
  const dot1Opacity = useSharedValue(0.3);
  const dot2Opacity = useSharedValue(0.3);
  const dot3Opacity = useSharedValue(0.3);

  useEffect(() => {
    // Staggered animation for each dot
    const duration = 400;

    dot1Opacity.value = withRepeat(
      withSequence(
        withTiming(1, { duration }),
        withTiming(0.3, { duration })
      ),
      -1, // Infinite
      false
    );

    dot2Opacity.value = withDelay(
      duration / 3,
      withRepeat(
        withSequence(
          withTiming(1, { duration }),
          withTiming(0.3, { duration })
        ),
        -1,
        false
      )
    );

    dot3Opacity.value = withDelay(
      (duration / 3) * 2,
      withRepeat(
        withSequence(
          withTiming(1, { duration }),
          withTiming(0.3, { duration })
        ),
        -1,
        false
      )
    );
  }, []);

  const dot1Style = useAnimatedStyle(() => ({
    opacity: dot1Opacity.value,
  }));

  const dot2Style = useAnimatedStyle(() => ({
    opacity: dot2Opacity.value,
  }));

  const dot3Style = useAnimatedStyle(() => ({
    opacity: dot3Opacity.value,
  }));

  return (
    <View style={styles.dotsContainer}>
      <Animated.View style={[styles.dot, dot1Style]} />
      <Animated.View style={[styles.dot, dot2Style]} />
      <Animated.View style={[styles.dot, dot3Style]} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    gap: 4,
  },
  userRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  name: {
    fontSize: 13,
    color: '#6b7280',
    fontWeight: '500',
  },
  dotsContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
    marginLeft: 2,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: '#6b7280',
  },
});
