/**
 * ARCHITECTURE: TypeScript types for authentication domain.
 * WHY: Single source of truth for auth data shapes across mobile app.
 * TRADEOFF: Duplicates some backend types but allows frontend-specific camelCase naming.
 */

export interface User {
  id: string;
  email: string;
  displayName: string;
  emailVerified: boolean;
}

export interface Session {
  accessToken: string;
  refreshToken: string;
  userId: string;
  user: User;
}

export interface SignUpData {
  email: string;
  password: string;
  displayName: string;
}

export interface SignInData {
  email: string;
  password: string;
}

/**
 * Token response from the API (snake_case).
 * Converted to Session (camelCase) by auth service.
 */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user_id: string;
}

export interface ApiError {
  detail: string;
}
