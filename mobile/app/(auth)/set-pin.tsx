/**
 * ARCHITECTURE: PIN setup screen with confirmation step.
 * WHY: Two-step PIN entry prevents typos and ensures user remembers their PIN.
 * TRADEOFF: Extra step vs single entry, but prevents lockout from mistyped PIN.
 */

import { View, Text, StyleSheet, Alert } from 'react-native';
import { useState } from 'react';

import { PinInput } from '@/components/auth';
import { useLock } from '@/contexts/lock-context';
import { useThemeColor } from '@/hooks/use-theme-color';

type Step = 'enter' | 'confirm';

export default function SetPinScreen() {
  const { setPin, unlock } = useLock();
  const [step, setStep] = useState<Step>('enter');
  const [firstPin, setFirstPin] = useState('');
  const [error, setError] = useState<string | undefined>();
  const textColor = useThemeColor({}, 'text');
  const backgroundColor = useThemeColor({}, 'background');

  const handlePinComplete = async (pin: string) => {
    if (step === 'enter') {
      setFirstPin(pin);
      setStep('confirm');
    } else {
      if (pin === firstPin) {
        await setPin(pin);
        Alert.alert('PIN Set', 'Your PIN has been set successfully.', [
          {
            text: 'OK',
            onPress: () => {
              unlock();
            },
          },
        ]);
      } else {
        setError('PINs do not match');
        setStep('enter');
        setFirstPin('');
        setTimeout(() => setError(undefined), 2000);
      }
    }
  };

  return (
    <View style={[styles.container, { backgroundColor }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: textColor }]}>
          {step === 'enter' ? 'Create a PIN' : 'Confirm your PIN'}
        </Text>
        <Text style={[styles.subtitle, { color: textColor }]}>
          {step === 'enter'
            ? 'Enter a 6-digit PIN for quick unlock'
            : 'Re-enter your PIN to confirm'}
        </Text>
      </View>

      <PinInput onComplete={handlePinComplete} error={error} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingHorizontal: 24,
    justifyContent: 'center',
  },
  header: {
    alignItems: 'center',
    marginBottom: 48,
  },
  title: {
    fontSize: 24,
    fontWeight: '700',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 14,
    opacity: 0.7,
    textAlign: 'center',
  },
});
