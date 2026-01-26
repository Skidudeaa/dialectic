/**
 * Babel configuration for React Native macOS
 *
 * ARCHITECTURE: Module resolution aliasing for monorepo workspace imports.
 * WHY: Enables import { ... } from '@dialectic/app' to resolve correctly.
 * TRADEOFF: Build-time path rewriting vs runtime resolution - more predictable.
 */

module.exports = {
  presets: ['module:@react-native/babel-preset'],
  plugins: [
    [
      'module-resolver',
      {
        root: ['./'],
        alias: {
          '@dialectic/app': '../app/src',
        },
      },
    ],
  ],
};
