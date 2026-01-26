/**
 * ARCHITECTURE: Sign-up screen with email/password/name fields.
 * WHY: Collects minimal required info with password confirmation.
 * TRADEOFF: Display name required upfront vs. later profile completion.
 */

import { View, Text, StyleSheet, Alert } from 'react-native';
import { Link, router } from 'expo-router';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';

import { FormInput, FormButton } from '@/components/auth';
import { signUpSchema, type SignUpForm } from '@/lib/validation';
import { signUp as signUpApi } from '@/services/auth';
import { useSession } from '@/contexts/session-context';
import { useThemeColor } from '@/hooks/use-theme-color';

export default function SignUpScreen() {
  const { signIn } = useSession();
  const [loading, setLoading] = useState(false);
  const textColor = useThemeColor({}, 'text');
  const backgroundColor = useThemeColor({}, 'background');

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<SignUpForm>({
    resolver: zodResolver(signUpSchema),
    defaultValues: {
      email: '',
      password: '',
      confirmPassword: '',
      displayName: '',
    },
  });

  const onSubmit = async (data: SignUpForm) => {
    setLoading(true);
    try {
      const session = await signUpApi({
        email: data.email,
        password: data.password,
        displayName: data.displayName,
      });
      await signIn(session);
      // Navigate to email verification
      router.replace('/(auth)/verify-email');
    } catch (error: unknown) {
      const axiosError = error as { response?: { data?: { detail?: string } } };
      const message =
        axiosError.response?.data?.detail || 'Sign up failed. Please try again.';
      Alert.alert('Error', message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={[styles.container, { backgroundColor }]}>
      <View style={styles.header}>
        <Text style={[styles.title, { color: textColor }]}>Create account</Text>
        <Text style={[styles.subtitle, { color: textColor }]}>
          Join to start collaborating
        </Text>
      </View>

      <View style={styles.form}>
        <FormInput
          control={control}
          name="displayName"
          label="Display Name"
          error={errors.displayName?.message}
          autoComplete="name"
        />

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
          autoComplete="new-password"
        />

        <FormInput
          control={control}
          name="confirmPassword"
          label="Confirm Password"
          error={errors.confirmPassword?.message}
          secureTextEntry
          autoComplete="new-password"
        />

        <FormButton
          title="Create Account"
          onPress={handleSubmit(onSubmit)}
          loading={loading}
        />
      </View>

      <View style={styles.footer}>
        <Text style={[styles.footerText, { color: textColor }]}>
          Already have an account?{' '}
        </Text>
        <Link href="/(auth)/sign-in" asChild>
          <Text style={styles.link}>Sign In</Text>
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
