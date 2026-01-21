/**
 * ARCHITECTURE: Zod schemas for form validation.
 * WHY: Type-safe validation with automatic TypeScript inference.
 * TRADEOFF: Additional dependency, but eliminates manual validation code.
 */

import { z } from 'zod';

export const emailSchema = z
  .string()
  .min(1, 'Email is required')
  .email('Invalid email address');

export const passwordSchema = z
  .string()
  .min(8, 'Password must be at least 8 characters');

export const displayNameSchema = z
  .string()
  .min(1, 'Display name is required')
  .max(50, 'Display name must be 50 characters or less');

export const codeSchema = z
  .string()
  .length(6, 'Code must be 6 digits')
  .regex(/^\d+$/, 'Code must contain only numbers');

export const signInSchema = z.object({
  email: emailSchema,
  password: z.string().min(1, 'Password is required'),
});

export const signUpSchema = z
  .object({
    email: emailSchema,
    password: passwordSchema,
    confirmPassword: z.string(),
    displayName: displayNameSchema,
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  });

export const verifyEmailSchema = z.object({
  code: codeSchema,
});

export const forgotPasswordSchema = z.object({
  email: emailSchema,
});

export const resetPasswordSchema = z
  .object({
    code: codeSchema,
    password: passwordSchema,
    confirmPassword: z.string(),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  });

export type SignInForm = z.infer<typeof signInSchema>;
export type SignUpForm = z.infer<typeof signUpSchema>;
export type VerifyEmailForm = z.infer<typeof verifyEmailSchema>;
export type ForgotPasswordForm = z.infer<typeof forgotPasswordSchema>;
export type ResetPasswordForm = z.infer<typeof resetPasswordSchema>;
