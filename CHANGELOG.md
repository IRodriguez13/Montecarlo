# Montecarlo Changelog

All notable changes to Montecarlo will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0]

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

### Security
- **CRITICAL: Safe module filtering**: Implemented strict filtering to prevent unloading kernel subsystems
  - **Explicit category exclusions**: 9 categories with 80+ specific modules excluded
    - Kernel core: CPU (cpuid, k10temp), ACPI (dmi_sysfs, acpi_thermal), Firmware (efi_pstore, pstore)
    - Memory/Block: zram, zsmalloc, loop, nbd
    - RAID: raid0-6, dm_mod, md_mod
    - Filesystems: ext4, btrfs, xfs, ntfs, fuse, nfs, cifs (all filesystem modules)
    - Sound core: snd_*, soundcore, snd_seq_midi, snd_hda_intel
    - HID/Input: hid_generic, usbhid, joydev, evdev
    - Virtualization: kvm, vbox*, vmw_*, virtio*
    - Network core: bridge, stp, llc, bonding
    - Legacy: parport_pc, ppdev
  - **Pattern-based exclusions**: Netfilter (xt_*, nf_*, nft_*), crypto (sha*, aes*), thermal, I2C/SPI bus, video/sound infrastructure
  - **Hardware modalias requirement**: Module MUST have real hardware alias (pci:, usb:, platform:, hid:, serio:, of:) to be shown
  - **Fail-safe**: If modinfo fails or no alias found, module is hidden
  - Prevents accidental unloading of critical system components (swap, filesystems, input drivers, sound stack, etc.)

### Fixed
- Modules loaded from repository now correctly appear in dashboard
- Infrastructure devices (bridges, ports, SCSI hosts) properly hidden
- **Driver "In Use" detection**: Fixed bug where USB/WiFi drivers showed as "Idle" when actually in use
  - Now checks `/sys/bus/usb/drivers/` in addition to `/sys/bus/pci/drivers/`
  - Added `/sys/module/<name>/holders` check for module dependencies
  - Added name normalization (lowercase, strip hyphens/underscores) for comparison
  - Fixes rtw88_8821cu and similar WiFi/USB drivers showing incorrect status

## [0.3.0] 

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

## [0.2.0]

### Added
- GTK3 user interface
- Real-time device scanning
- Driver loading/unloading capabilities
- Telemetry logging

### Changed
- Migrated from CLI-only to GUI application

## [0.1.0]

### Added
- Initial release
- Basic USB device detection
- Manual driver matching
- Command-line interface
