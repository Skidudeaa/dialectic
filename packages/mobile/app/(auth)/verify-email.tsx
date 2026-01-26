/**
 * ARCHITECTURE: Email verification screen with 6-digit code entry.
 * WHY: Confirms email ownership before granting full access.
 * TRADEOFF: Separate screen vs. modal; screen provides focused UX.
 */

import { View, Text, StyleSheet, Alert } from 'react-native';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';

import { FormInput, FormButton } from '@/components/auth';
import { verifyEmailSchema, type VerifyEmailForm } from '@/lib/validation';
import { verifyEmail as verifyEmailApi } from '@/services/auth';
import { useSession } from '@/contexts/session-context';
import { useThemeColor } from '@/hooks/use-theme-color';

export default function VerifyEmailScreen() {
  const { session, updateSession } = useSession();
  const [loading, setLoading] = useState(false);
  const textColor = useThemeColor({}, 'text');
  const backgroundColor = useThemeColor({}, 'background');

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<VerifyEmailForm>({
    resolver: zodResolver(verifyEmailSchema),
    defaultValues: {
      code: '',
    },
  });

  const onSubmit = async (data: VerifyEmailForm) => {
    setLoading(true);
    try {
      await verifyEmailApi(data.code);
      // Update session to mark email as verified
      if (session) {
        await updateSession({
          user: { ...session.user, emailVerified: true },
        });
      }
      // Navigation to app handled by root layout
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const message =
        axiosError.response?.data?.detail ||
        'Verification failed. Please try again.';
      Alert.alert('Error', message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={[styles.container, { backgroundColor }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: textColor }]}>
          Verify your email
        </Text>
        <Text style={[styles.subtitle, { color: textColor }]}>
          Enter the 6-digit code we sent to{'\n'}
          {session?.user.email || 'your email'}
        </Text>
      </View>

      <View style={styles.form}>
        <FormInput
          control={control}
          name="code"
          label="Verification Code"
          error={errors.code?.message}
          keyboardType="number-pad"
          maxLength={6}
          autoFocus
        />

        <FormButton
          title="Verify Email"
          onPress={handleSubmit(onSubmit)}
          loading={loading}
        />
      </View>

      <Text style={[styles.helpText, { color: textColor }]}>
        Didn't receive a code? Check your spam folder.
      </Text>
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
    marginBottom: 32,
  },
  title: {
    fontSize: 28,
    fontWeight: '700',
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    opacity: 0.7,
    lineHeight: 24,
  },
  form: {
    marginBottom: 24,
  },
  helpText: {
    fontSize: 14,
    textAlign: 'center',
    opacity: 0.6,
  },
});
