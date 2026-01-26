/**
 * ARCHITECTURE: Layout for room routes including branches and thread screens.
 * WHY: Shared stack configuration for all room-related screens.
 * TRADEOFF: Nested layout vs flat, but provides route organization.
 */

import React from 'react';
import { Stack, useLocalSearchParams, useRouter } from 'expo-router';
import { Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

export default function RoomLayout() {
  const router = useRouter();
  const { roomId } = useLocalSearchParams<{ roomId: string }>();

  return (
    <Stack>
      <Stack.Screen
        name="index"
        options={{
          title: 'Room',
          headerRight: () => (
            <Pressable
              onPress={() =>
                (router.push as (path: string) => void)(
                  `/room/${roomId}/branches`
                )
              }
              style={{ marginRight: 8 }}
            >
              <Ionicons name="git-branch-outline" size={24} color="#6366f1" />
            </Pressable>
          ),
        }}
      />
      <Stack.Screen
        name="branches"
        options={{
          title: 'Branches',
          headerBackTitle: 'Back',
        }}
      />
      <Stack.Screen
        name="thread/[threadId]"
        options={{
          title: 'Thread',
          headerRight: () => (
            <Pressable
              onPress={() =>
                (router.push as (path: string) => void)(
                  `/room/${roomId}/branches`
                )
              }
              style={{ marginRight: 8 }}
            >
              <Ionicons name="git-branch-outline" size={24} color="#6366f1" />
            </Pressable>
          ),
        }}
      />
    </Stack>
  );
}
