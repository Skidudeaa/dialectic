/**
 * Metro configuration for React Native macOS
 *
 * ARCHITECTURE: Monorepo-aware Metro config with workspace resolution.
 * WHY: macOS workspace needs to resolve dependencies from both local
 *      node_modules and the monorepo root, plus @dialectic/app shared code.
 * TRADEOFF: Complex resolution vs single-package simplicity - required for code sharing.
 *
 * @see https://facebook.github.io/metro/docs/configuration
 * @see https://docs.expo.dev/guides/monorepos/#metro-configuration
 */

const path = require('path');
const { getDefaultConfig, mergeConfig } = require('@react-native/metro-config');

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, '../..');

const config = {
  // Watch all files in the monorepo
  watchFolders: [workspaceRoot],

  resolver: {
    // Resolve modules from both local and root node_modules
    nodeModulesPaths: [
      path.resolve(projectRoot, 'node_modules'),
      path.resolve(workspaceRoot, 'node_modules'),
    ],

    // Map workspace packages to their source directories
    extraNodeModules: {
      '@dialectic/app': path.resolve(workspaceRoot, 'packages/app'),
    },

    // Ensure react-native-macos is resolved correctly
    resolveRequest: (context, moduleName, platform) => {
      // Let the default resolver handle everything
      return context.resolveRequest(context, moduleName, platform);
    },
  },

  transformer: {
    getTransformOptions: async () => ({
      transform: {
        experimentalImportSupport: false,
        inlineRequires: true,
      },
    }),
  },
};

module.exports = mergeConfig(getDefaultConfig(projectRoot), config);
