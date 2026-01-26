/**
 * ARCHITECTURE: Forgot password screen to request reset code.
 * WHY: Simple email entry to trigger password reset flow.
 * TRADEOFF: Explicit error if no account (per CONTEXT.md) vs. silent success.
 */

import { View, Text, StyleSheet, Alert } from 'react-native';
import { Link, router } from 'expo-router';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';

import { FormInput, FormButton } from '@/components/auth';
import { forgotPasswordSchema, type ForgotPasswordForm } from '@/lib/validation';
import { forgotPassword as forgotPasswordApi } from '@/services/auth';
import { useThemeColor } from '@/hooks/use-theme-color';

export default function ForgotPasswordScreen() {
  const [loading, setLoading] = useState(false);
  const textColor = useThemeColor({}, 'text');
  const backgroundColor = useThemeColor({}, 'background');

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotPasswordForm>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: {
      email: '',
    },
  });

  const onSubmit = async (data: ForgotPasswordForm) => {
    setLoading(true);
    try {
      await forgotPasswordApi(data.email);
      // Navigate to reset password screen with email
      router.push({
        pathname: '/(auth)/reset-password',
        params: { email: data.email },
      });
    } catch (error: unknown) {
      // Per CONTEXT.md: explicit error if no account exists
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const message =
        axiosError.response?.data?.detail || 'Failed to send reset code.';
      Alert.alert('Error', message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={[styles.container, { backgroundColor }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: textColor }]}>
          Forgot password?
        </Text>
        <Text style={[styles.subtitle, { color: textColor }]}>
          Enter your email and we'll send you a code to reset your password.
        </Text>
      </View>

      <View style={styles.form}>
        <FormInput
          control={control}
          name="email"
          label="Email"
          error={errors.email?.message}
          autoCapitalize="none"
          keyboardType="email-address"
          autoComplete="email"
        />

        <FormButton
          title="Send Reset Code"
          onPress={handleSubmit(onSubmit)}
          loading={loading}
        />
      </View>

      <View style={styles.footer}>
        <Link href="/(auth)/sign-in" asChild>
          <Text style={styles.link}>Back to Sign In</Text>
        </Link>
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
  footer: {
    alignItems: 'center',
  },
  link: {
    color: '#3b82f6',
    fontSize: 14,
    fontWeight: '600',
  },
});
