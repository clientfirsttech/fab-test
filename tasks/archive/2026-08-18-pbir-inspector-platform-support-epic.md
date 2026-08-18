# PBIR Inspector Platform Support Epic

**Status**: ✅ COMPLETED
**Goal**: Make the PBIR Inspector analyzer download and run the correct native binary for the current operating system.

## Overview

The fab-test tool bootstrapper currently downloads the Linux PBIR Inspector binary on every platform. On Windows this produces a `WinError 193` at runtime. The upstream fab-inspector release already ships Windows and macOS archives, so the bootstrapper should be platform-aware and select the right asset.

---

## Platform-aware tool download

Extend `_analyzer_tool_bootstrap.py` to choose a platform-specific download URL and executable subpath when they are declared in `analyzers.json`. Keep backward compatibility with the existing single `install_url` / `executable_subpath` fields for analyzers that do not need platform selection.

**Requirements**:
- Given a user runs `fab-test pbir` on Windows, then the Windows `win-x64-FabInspCLI.zip` archive should be downloaded and `win-x64/FabInspCLI/fab-inspector.exe` should be executed.
- Given a user runs `fab-test pbir` on Linux, then the Linux `linux-x64-FabInspCLI.zip` archive should be downloaded and `linux-x64/FabInspCLI/fab-inspector` should be executed.
- Given a user runs `fab-test pbir` on macOS, then the macOS archive should be downloaded and the correct executable should be used.
- Given an analyzer registry entry only has the legacy `install_url` field, then the bootstrapper should continue to use it as a fallback.

---

## Update PBIR Inspector registry for Windows/macOS

Update `.github/metadata/analyzers.json` so the `pbir_inspector.tool_install` block declares platform-specific URLs and executable subpaths.

**Requirements**:
- Given the registry is loaded on Windows, then the bootstrapper resolves to the Windows asset.
- Given the registry is loaded on Linux, then the bootstrapper resolves to the Linux asset.
- Given the registry is loaded on macOS, then the bootstrapper resolves to the macOS asset.

---

## Fail fast on unsupported platforms

If `requires_platform` is set and the current platform is not supported, raise a clear `RuntimeError` before downloading or attempting to run the binary.

**Requirements**:
- Given `requires_platform` is `linux` and the user is on Windows, then `resolve_executable` should raise a clear error stating the analyzer is not supported on this platform.
- Given `requires_platform` is absent or the current platform is supported, then resolution proceeds normally.

---

## Regression tests

Add tests covering platform selection and backward compatibility.

**Requirements**:
- Given a registry entry with platform-specific `install_urls` and `executable_subpaths`, then `resolve_executable` selects the correct URL for the current platform.
- Given a registry entry with only legacy `install_url` and `executable_subpath`, then `resolve_executable` still works.
- Given `requires_platform` does not match the current platform, then `resolve_executable` raises `RuntimeError`.
