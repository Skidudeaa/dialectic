/**
 * ARCHITECTURE: Reset password screen with code and new password entry.
 * WHY: Completes password reset flow with auto-login on success.
 * TRADEOFF: Auto-login (per CONTEXT.md) vs. requiring manual sign-in.
 */

import { View, Text, StyleSheet, Alert } from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';

import { FormInput, FormButton } from '@/components/auth';
import { resetPasswordSchema, type ResetPasswordForm } from '@/lib/validation';
import { resetPassword as resetPasswordApi } from '@/services/auth';
import { useSession } from '@/contexts/session-context';
import { useThemeColor } from '@/hooks/use-theme-color';

export default function ResetPasswordScreen() {
  const { email } = useLocalSearchParams<{ email: string }>();
  const { signIn } = useSession();
  const [loading, setLoading] = useState(false);
  const textColor = useThemeColor({}, 'text');
  const backgroundColor = useThemeColor({}, 'background');

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<ResetPasswordForm>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: {
      code: '',
      password: '',
      confirmPassword: '',
    },
  });

  const onSubmit = async (data: ResetPasswordForm) => {
    if (!email) {
      Alert.alert('Error', 'Email is required. Please go back and try again.');
      return;
    }

    setLoading(true);
    try {
      // Per CONTEXT.md: auto-login after successful password reset
      const session = await resetPasswordApi(email, data.code, data.password);
      await signIn(session);
      // Navigation handled by root layout
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const message =
        axiosError.response?.data?.detail ||
        'Password reset failed. Please try again.';
      Alert.alert('Error', message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={[styles.container, { backgroundColor }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: textColor }]}>Reset password</Text>
        <Text style={[styles.subtitle, { color: textColor }]}>
          Enter the code sent to {email} and your new password.
        </Text>
      </View>

      <View style={styles.form}>
        <FormInput
          control={control}
          name="code"
          label="Reset Code"
          error={errors.code?.message}
          keyboardType="number-pad"
          maxLength={6}
        />

        <FormInput
          control={control}
          name="password"
          label="New Password"
          error={errors.password?.message}
          secureTextEntry
          autoComplete="new-password"
        />

        <FormInput
          control={control}
          name="confirmPassword"
          label="Confirm New Password"
          error={errors.confirmPassword?.message}
          secureTextEntry
          autoComplete="new-password"
        />

        <FormButton
          title="Reset Password"
          onPress={handleSubmit(onSubmit)}
          loading={loading}
        />
      </View>
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
});
