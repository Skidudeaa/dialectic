/**
 * ARCHITECTURE: Sign-in screen with react-hook-form and zod validation.
 * WHY: Type-safe form handling with inline validation feedback.
 * TRADEOFF: Additional libraries, but eliminates boilerplate validation code.
 */

import { View, Text, StyleSheet, Alert } from 'react-native';
import { Link } from 'expo-router';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';

import { FormInput, FormButton } from '@/components/auth';
import { signInSchema, type SignInForm } from '@/lib/validation';
import { signIn as signInApi } from '@/services/auth';
import { useSession } from '@/contexts/session-context';
import { useThemeColor } from '@/hooks/use-theme-color';

export default function SignInScreen() {
  const { signIn } = useSession();
  const [loading, setLoading] = useState(false);
  const textColor = useThemeColor({}, 'text');
  const backgroundColor = useThemeColor({}, 'background');

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<SignInForm>({
    resolver: zodResolver(signInSchema),
    defaultValues: {
      email: '',
      password: '',
    },
  });

  const onSubmit = async (data: SignInForm) => {
    setLoading(true);
    try {
      const session = await signInApi(data);
      await signIn(session);
      // Navigation handled by root layout based on session state
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const message =
        axiosError.response?.data?.detail || 'Sign in failed. Please try again.';
      Alert.alert('Error', message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={[styles.container, { backgroundColor }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: textColor }]}>Welcome back</Text>
        <Text style={[styles.subtitle, { color: textColor }]}>
          Sign in to continue
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

        <FormInput
          control={control}
          name="password"
          label="Password"
          error={errors.password?.message}
          secureTextEntry
          autoComplete="password"
        />

        <Link href="/(auth)/forgot-password" asChild>
          <Text style={styles.forgotPassword}>Forgot password?</Text>
        </Link>

        <FormButton
          title="Sign In"
          onPress={handleSubmit(onSubmit)}
          loading={loading}
        />
      </View>

      <View style={styles.footer}>
        <Text style={[styles.footerText, { color: textColor }]}>
          Don't have an account?{' '}
        </Text>
        <Link href="/(auth)/sign-up" asChild>
          <Text style={styles.link}>Sign Up</Text>
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
  },
  form: {
    marginBottom: 24,
  },
  forgotPassword: {
    color: '#3b82f6',
    fontSize: 14,
    textAlign: 'right',
    marginBottom: 16,
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'center',
  },
  footerText: {
    fontSize: 14,
  },
  link: {
    color: '#3b82f6',
    fontSize: 14,
    fontWeight: '600',
  },
});
