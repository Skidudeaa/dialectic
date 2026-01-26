# Windows Build Instructions

This directory will contain the Visual Studio project for Dialectic Windows app.

## Prerequisites

**Required (must run on Windows machine):**

1. **Windows 10/11** - Development machine running Windows
2. **Visual Studio 2022** with workloads:
   - Desktop development with C++
   - Universal Windows Platform development
   - Windows 10/11 SDK (10.0.19041.0 or newer)
3. **Node.js 18+** and Yarn
4. **.NET 6.0+ SDK**

## Generate Project

Run this command from `packages/windows/` directory on a Windows machine:

```powershell
# Install dependencies first
yarn install

# Generate Visual Studio project with C++ template (New Architecture/Fabric)
npx react-native-windows-init --overwrite --template cpp-app
```

This creates:
- `windows/DialecticWin.sln` - Visual Studio solution
- `windows/DialecticWin/` - C++ source files, XAML, assets

## Build and Run

```powershell
# Development build
yarn windows

# Release build
yarn build
```

## Template Choice: cpp-app

We use `--template cpp-app` (not `cpp-lib` or `cs-app`) because:

1. **New Architecture (Fabric)**: Default in RN-Windows 0.80+, required for 0.82+
2. **WinAppSDK**: Modern Windows APIs instead of deprecated UWP
3. **Performance**: C++ template has better performance than C#

## Troubleshooting

- **"MSBuild not found"**: Install Visual Studio with C++ workload
- **"SDK version not found"**: Install Windows SDK via Visual Studio Installer
- **Build fails**: Delete `windows/` directory and regenerate

## Documentation

- [React Native Windows Getting Started](https://microsoft.github.io/react-native-windows/docs/getting-started)
- [New Architecture Guide](https://microsoft.github.io/react-native-windows/docs/new-architecture)
- [Visual Studio Setup](https://microsoft.github.io/react-native-windows/docs/rnw-dependencies)
