/**
 * ARCHITECTURE: Context for app lock state with background timeout detection.
 * WHY: Per CONTEXT.md, app locks after 15 minutes in background for security.
 * TRADEOFF: Simple base64 "hash" for PIN - not cryptographically secure, but PIN is device-local only.
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react';
import { secureStorage } from '@/lib/secure-storage';
import { useAppState } from '@/hooks/use-app-state';
import { useSession } from '@/contexts/session-context';

const LOCK_TIMEOUT_MS = 15 * 60 * 1000; // 15 minutes per CONTEXT.md
const PIN_HASH_KEY = 'pinHash';

interface LockContextType {
  isLocked: boolean;
  shouldPromptBiometricSetup: boolean;
  lock: () => void;
  unlock: () => void;
  dismissBiometricPrompt: () => void;
  pinHash: string | null;
  setPin: (pin: string) => Promise<void>;
  verifyPin: (pin: string) => boolean;
}

const LockContext = createContext<LockContextType | null>(null);

export function LockProvider({ children }: { children: ReactNode }) {
  const { session } = useSession();
  const [isLocked, setIsLocked] = useState(false);
  const [shouldPromptBiometricSetup, setShouldPromptBiometricSetup] =
    useState(false);
  const [pinHash, setPinHash] = useState<string | null>(null);
  const [hasPromptedBiometric, setHasPromptedBiometric] = useState(false);

  // Load PIN hash on mount
  useEffect(() => {
    loadPinHash();
  }, []);

  // Check if this is first login (to show biometric setup prompt)
  useEffect(() => {
    if (session && !isLocked && !hasPromptedBiometric) {
      checkFirstLogin();
    }
  }, [session, isLocked, hasPromptedBiometric]);

  async function loadPinHash() {
    // PIN hash is stored alongside session in SecureStore
    const storedSession = await secureStorage.getSession<{
      pinHash?: string;
    }>();
    if (storedSession?.pinHash) {
      setPinHash(storedSession.pinHash);
    }
  }

  async function checkFirstLogin() {
    const biometricEnabled = await secureStorage.getBiometricEnabled();
    // Prompt biometric setup on first successful login if not already enabled
    if (!biometricEnabled && session?.user.emailVerified) {
      setHasPromptedBiometric(true);
      setShouldPromptBiometricSetup(true);
    }
  }

  // Track last active time when going to background
  const handleBackground = useCallback(async () => {
    if (session) {
      await secureStorage.setLastActive(Date.now());
    }
  }, [session]);

  // Check if should lock when coming to foreground
  const handleForeground = useCallback(async () => {
    if (!session) return;

    const lastActive = await secureStorage.getLastActive();
    if (lastActive) {
      const elapsed = Date.now() - lastActive;
      if (elapsed > LOCK_TIMEOUT_MS) {
        setIsLocked(true);
      }
    }
  }, [session]);

  useAppState(handleBackground, handleForeground);

  const lock = useCallback(() => {
    setIsLocked(true);
  }, []);

  const unlock = useCallback(() => {
    setIsLocked(false);
  }, []);

  const dismissBiometricPrompt = useCallback(() => {
    setShouldPromptBiometricSetup(false);
  }, []);

  const setPin = useCallback(async (pin: string) => {
    // Simple base64 encode for demo - PIN is stored locally only, not sent to server
    // For production, use a proper hash function
    const hash = btoa(pin);
    setPinHash(hash);
    // Store with session
    const currentSession = await secureStorage.getSession<object>();
    if (currentSession) {
      await secureStorage.setSession({ ...currentSession, [PIN_HASH_KEY]: hash });
    }
  }, []);

  const verifyPin = useCallback(
    (pin: string): boolean => {
      if (!pinHash) return false;
      return btoa(pin) === pinHash;
    },
    [pinHash]
  );

  return (
    <LockContext.Provider
      value={{
        isLocked,
        shouldPromptBiometricSetup,
        lock,
        unlock,
        dismissBiometricPrompt,
        pinHash,
        setPin,
        verifyPin,
      }}
    >
      {children}
    </LockContext.Provider>
  );
}

export function useLock() {
  const context = useContext(LockContext);
  if (!context) {
    throw new Error('useLock must be used within LockProvider');
  }
  return context;
}
