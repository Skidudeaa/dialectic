/**
 * Metro configuration for monorepo
 *
 * ARCHITECTURE: Extends Expo's metro config with monorepo watch/resolution.
 * WHY: Metro needs to see packages/app and root node_modules for workspace deps.
 * TRADEOFF: More config complexity but enables code sharing.
 */

const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');

// Get the project root (mobile package)
const projectRoot = __dirname;

// Get the monorepo root (two levels up from packages/mobile)
const monorepoRoot = path.resolve(projectRoot, '../..');

const config = getDefaultConfig(projectRoot);

// Watch all files in the monorepo (for packages/app changes)
config.watchFolders = [monorepoRoot];

// Let Metro know where to resolve packages
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, 'node_modules'),
  path.resolve(monorepoRoot, 'node_modules'),
];

// Ensure packages/app is resolved correctly
config.resolver.disableHierarchicalLookup = true;

module.exports = config;
