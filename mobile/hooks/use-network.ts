/**
 * ARCHITECTURE: Network state hook using @react-native-community/netinfo.
 * WHY: Network awareness enables smart reconnection and offline indicators.
 * TRADEOFF: Extra dependency, but provides reliable cross-platform network detection.
 */

import { useEffect, useState } from 'react';
import NetInfo, { NetInfoState } from '@react-native-community/netinfo';

export function useNetwork() {
  const [state, setState] = useState<NetInfoState | null>(null);

  useEffect(() => {
    // Subscribe to network state changes
    const unsubscribe = NetInfo.addEventListener(setState);

    // Fetch initial state
    NetInfo.fetch().then(setState);

    return () => unsubscribe();
  }, []);

  return {
    /** Whether device has network connectivity (null if unknown) */
    isConnected: state?.isConnected ?? null,
    /** Whether internet is reachable (null if unknown) */
    isInternetReachable: state?.isInternetReachable ?? null,
    /** Network type: 'wifi', 'cellular', 'none', 'unknown', etc. */
    type: state?.type ?? 'unknown',
  };
}
