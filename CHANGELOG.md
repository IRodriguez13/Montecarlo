# Montecarlo Changelog

All notable changes to Montecarlo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2025-12-09

### Added
- **Version information**: `--version` flag for daemon and version display in UI
- **Secure socket path**: Socket now uses `/run/user/$UID/montecarlo.sock` instead of `/tmp`
  - Falls back to `/tmp/montecarlo-$UID.sock` if `/run/user` doesn't exist
  - Socket permissions changed from 0666 to 0600 (user-only access)
- **Universal module display**: Dashboard now shows ALL loaded modules (PCI, SCSI, Ham Radio, etc.)
  - Previously only USB modules appeared when loaded without hardware
  - Modules like `6pack`, `3c589_cs`, `3w_9xxx` now visible as "Loaded Module (Idle/In Use)"

### Changed
- **Infrastructure device filtering**: Enhanced PCI filtering to hide more infrastructure
  - Added SMBus controllers (class 0x0c05)
  - Added System Peripherals (class 0x08) like IOMMU
  - Added `piix4_smbus` to infrastructure driver blacklist
  - Now filters 71% of PCI devices on typical systems (24/34 on test system)
- **Dashboard logic**: Changed from USB-only module display to all-subsystem support
- **Security**: Socket path no longer world-writable

### Fixed
- Modules loaded from repository now correctly appear in dashboard
- Infrastructure devices (bridges, ports, SCSI hosts) properly hidden

## [0.3.0] - 2024

### Added
- Infrastructure device filtering (initial implementation)
- PolicyKit integration for privileged operations
- Desktop notifications for device detection
- Multi-bus support (USB, PCI, HID, SCSI)
- Restore tab for unloaded drivers

### Changed
- Improved safety checks for driver unloading
- Enhanced UI with device details panel
- Better module filtering (dependency detection)

## [0.2.0] - 2024

### Added
- GTK3 user interface
- Real-time device scanning
- Driver loading/unloading capabilities
- Telemetry logging

### Changed
- Migrated from CLI-only to GUI application

## [0.1.0] - 2024

### Added
- Initial release
- Basic USB device detection
- Manual driver matching
- Command-line interface
