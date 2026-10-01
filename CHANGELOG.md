# Changelog

## 0.1.9-beta — 2026-10-01

- Reworked installation into a Z-Mod-native git plugin with Moonraker Update Manager support.
- Moved mutable runtime state outside the git checkout.
- Fixed Klipper SAVE_CONFIG ordering damage from the legacy installer path.
- Added recovery for OV3660 sensor-policy startup failures.
- Added configurable Fluidd stream type and embedded Camera Manager UI integration.
- Restored the verified Creality Nebula / CCX2F3298 DAY-mode controller.
- Added a 60-second Nebula watchdog that re-forces DAY after unwanted AUTO/NIGHT fallback.
- Added config schema v2 migration for existing Nebula profiles.
- Added CI and automated prerelease packaging.
