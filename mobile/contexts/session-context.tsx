/**
 * ARCHITECTURE: Session context following Expo Router auth pattern.
 * WHY: Centralized session state with automatic persistence to SecureStore.
 * TRADEOFF: Context re-renders on session change, but auth state rarely changes.
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import { secureStorage } from '@/lib/secure-storage';
import type { Session, User } from '@/types/auth';

interface SessionContextType {
  session: Session | null;
  user: User | null;
  isLoading: boolean;
  signIn: (session: Session) => Promise<void>;
  signOut: () => Promise<void>;
  updateSession: (updates: Partial<Session>) => Promise<void>;
}

const SessionContext = createContext<SessionContextType | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    loadSession();
  }, []);

  async function loadSession() {
    try {
      const stored = await secureStorage.getSession<Session>();
      if (stored) {
        setSession(stored);
      }
    } catch (error) {
      console.error('Failed to load session:', error);
    } finally {
      setIsLoading(false);
    }
  }

  const signIn = useCallback(async (newSession: Session) => {
    await secureStorage.setSession(newSession);
    setSession(newSession);
  }, []);

  const signOut = useCallback(async () => {
    await secureStorage.deleteSession();
    setSession(null);
  }, []);

  const updateSession = useCallback(
    async (updates: Partial<Session>) => {
      if (!session) return;
      const updated = { ...session, ...updates };
      await secureStorage.setSession(updated);
      setSession(updated);
    },
    [session]
  );

  const user = session?.user ?? null;

  return (
    <SessionContext.Provider
      value={{ session, user, isLoading, signIn, signOut, updateSession }}
    >
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within SessionProvider');
  }
  return context;
}
