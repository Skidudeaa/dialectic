/**
 * ARCHITECTURE: Auth API functions wrapping backend endpoints.
 * WHY: Typed functions provide clean API surface and handle camelCase conversion.
 * TRADEOFF: Manual type conversion from snake_case, but explicit and clear.
 */

import { api } from './api';
import type {
  SignUpData,
  SignInData,
  TokenResponse,
  Session,
  User,
} from '@/types/auth';

// Helper to convert snake_case API response to camelCase Session
function toSession(tokenResponse: TokenResponse, user: User): Session {
  return {
    accessToken: tokenResponse.access_token,
    refreshToken: tokenResponse.refresh_token,
    userId: tokenResponse.user_id,
    user,
  };
}

export async function signUp(data: SignUpData): Promise<Session> {
  const response = await api.post<TokenResponse & { user: User }>(
    '/auth/signup',
    {
      email: data.email,
      password: data.password,
      display_name: data.displayName,
    }
  );
  return toSession(response.data, response.data.user);
}

export async function signIn(data: SignInData): Promise<Session> {
  const response = await api.post<TokenResponse & { user: User }>(
    '/auth/login',
    {
      email: data.email,
      password: data.password,
    }
  );
  return toSession(response.data, response.data.user);
}

export async function refreshTokens(
  refreshToken: string
): Promise<{ accessToken: string }> {
  const response = await api.post<{ access_token: string }>('/auth/refresh', {
    refresh_token: refreshToken,
  });
  return { accessToken: response.data.access_token };
}

export async function logout(): Promise<void> {
  try {
    await api.post('/auth/logout');
  } catch {
    // Ignore logout errors - we're signing out anyway
  }
}

export async function verifyEmail(code: string): Promise<void> {
  await api.post('/auth/verify-email', { code });
}

export async function forgotPassword(email: string): Promise<void> {
  await api.post('/auth/forgot-password', { email });
}

export async function resetPassword(
  email: string,
  code: string,
  newPassword: string
): Promise<Session> {
  const response = await api.post<TokenResponse & { user: User }>(
    '/auth/reset-password',
    {
      email,
      code,
      new_password: newPassword,
    }
  );
  return toSession(response.data, response.data.user);
}
