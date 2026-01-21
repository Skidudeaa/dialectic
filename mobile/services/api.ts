/**
 * ARCHITECTURE: Axios instance with automatic token attachment and refresh.
 * WHY: Centralized HTTP client ensures all API calls are authenticated.
 * TRADEOFF: Request interceptor adds async overhead, but ensures consistent auth.
 */

import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';
import { secureStorage } from '@/lib/secure-storage';
import type { Session } from '@/types/auth';

// Use environment variable for API URL
const API_URL = process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000';

export const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Track refresh state to prevent multiple simultaneous refreshes
let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: Error) => void;
}> = [];

const processQueue = (error: Error | null, token: string | null) => {
  failedQueue.forEach((promise) => {
    if (error) {
      promise.reject(error);
    } else if (token) {
      promise.resolve(token);
    }
  });
  failedQueue = [];
};

// Request interceptor: attach access token
api.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    const session = await secureStorage.getSession<Session>();
    if (session?.accessToken) {
      config.headers.Authorization = `Bearer ${session.accessToken}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor: handle 401 and refresh token
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    // Only attempt refresh for 401 errors that haven't been retried
    if (error.response?.status !== 401 || originalRequest._retry) {
      return Promise.reject(error);
    }

    // If already refreshing, queue this request
    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        failedQueue.push({
          resolve: (token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            resolve(api(originalRequest));
          },
          reject: (err: Error) => {
            reject(err);
          },
        });
      });
    }

    originalRequest._retry = true;
    isRefreshing = true;

    try {
      const session = await secureStorage.getSession<Session>();
      if (!session?.refreshToken) {
        throw new Error('No refresh token');
      }

      // Call refresh endpoint directly (avoid interceptor loop)
      const response = await axios.post(`${API_URL}/auth/refresh`, {
        refresh_token: session.refreshToken,
      });

      const { access_token } = response.data;

      // Update stored session with new access token
      const updatedSession: Session = {
        ...session,
        accessToken: access_token,
      };
      await secureStorage.setSession(updatedSession);

      processQueue(null, access_token);

      originalRequest.headers.Authorization = `Bearer ${access_token}`;
      return api(originalRequest);
    } catch (refreshError) {
      processQueue(refreshError as Error, null);

      // Clear session on refresh failure - will trigger redirect to login
      await secureStorage.deleteSession();

      return Promise.reject(refreshError);
    } finally {
      isRefreshing = false;
    }
  }
);
