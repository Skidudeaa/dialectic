/**
 * ARCHITECTURE: Notification context for app-wide push setup.
 * WHY: Centralized notification handlers, token registration, and deep linking.
 * TRADEOFF: Provider adds nesting but ensures notifications work from app launch.
 */

import { createContext, useContext, useEffect, useRef } from 'react';
import { AppState, AppStateStatus } from 'react-native';
import * as Notifications from 'expo-notifications';
import { useSession } from './session-context';
import { useLock } from './lock-context';
import { useWebSocketStore } from '@/stores/websocket-store';
import { syncBadgeFromStore } from '@/services/notifications/badge';
import {
  setupNotificationHandler,
  setupNotificationResponseListener,
} from '@/services/notifications/handlers';
import { setupNotificationChannels } from '@/services/notifications/channels';
import {
  handleNotificationNavigation,
  handleInitialNotification,
} from '@/services/notifications/deep-link';
import { registerForPushNotifications } from '@/services/notifications/registration';

interface NotificationContextType {
  // Can be extended for badge count management, etc.
}

const NotificationContext = createContext<NotificationContextType>({});

export function NotificationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { session } = useSession();
  const { isLocked } = useLock();
  const responseListener = useRef<Notifications.Subscription | undefined>(undefined);

  // Get current room from WebSocket store for foreground suppression
  const currentRoomId = useWebSocketStore((state) => state.currentRoomId);
  const getCurrentRoomId = useRef(() => currentRoomId);
  getCurrentRoomId.current = () => currentRoomId;

  // Setup notification channels and handlers once on mount
  useEffect(() => {
    setupNotificationChannels();
    setupNotificationHandler(() => getCurrentRoomId.current());

    responseListener.current = setupNotificationResponseListener((data) => {
      handleNotificationNavigation(data);
    });

    // Handle cold start notification
    handleInitialNotification();

    return () => {
      responseListener.current?.remove();
    };
  }, []);

  // Sync badge when app comes to foreground
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state: AppStateStatus) => {
      if (state === 'active') {
        // Sync badge from store when app comes to foreground
        syncBadgeFromStore();
      }
    });

    return () => subscription.remove();
  }, []);

  // Register for push when user is authenticated and unlocked
  useEffect(() => {
    if (session?.user && !isLocked && session.user.emailVerified) {
      registerForPushNotifications(session.user.id).catch((error) => {
        console.warn('[Notifications] Token registration failed:', error);
      });
    }
  }, [session?.user?.id, isLocked, session?.user?.emailVerified]);

  return (
    <NotificationContext.Provider value={{}}>
      {children}
    </NotificationContext.Provider>
  );
}

export function useNotifications() {
  return useContext(NotificationContext);
}
