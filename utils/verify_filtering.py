#!/usr/bin/env python3
"""
Quick test to verify infrastructure device filtering is working
"""
import ctypes
import sys

# Load library
import os

# Load library
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_PATH = os.path.join(BASE_DIR, "libmontecarlo.so")
lib = ctypes.CDLL(LIB_PATH)

# Define device info struct
class DeviceInfo(ctypes.Structure):
    _fields_ = [
        ("syspath", ctypes.c_char * 256),
        ("vidpid", ctypes.c_char * 32),
        ("product", ctypes.c_char * 128),
        ("driver", ctypes.c_char * 64),
        ("subsystem", ctypes.c_char * 16),
    ]

# Test: List all devices
devices = (DeviceInfo * 200)()
count = lib.mc_list_all_devices(devices, 200)

print(f"\n✅ Total devices found: {count}\n")

# Categorize by subsystem
pci_devices = []
scsi_devices = []
usb_devices = []
hid_devices = []

for i in range(count):
    dev = devices[i]
    subsystem = dev.subsystem.decode('utf-8')
    syspath = dev.syspath.decode('utf-8')
    product = dev.product.decode('utf-8')
    driver = dev.driver.decode('utf-8')
    
    if subsystem == 'pci':
        pci_devices.append((syspath, product, driver))
    elif subsystem == 'scsi':
        scsi_devices.append((syspath, product, driver))
    elif subsystem == 'usb':
        usb_devices.append((syspath, product, driver))
    elif subsystem == 'hid':
        hid_devices.append((syspath, product, driver))

# Display results
print(f"📊 PCI Devices: {len(pci_devices)}")
for path, prod, drv in pci_devices:
    print(f"   - {prod} (driver: {drv})")
    # Check if it looks like a bridge (should NOT appear)
    if 'bridge' in prod.lower() or 'port' in prod.lower():
        print(f"      ⚠️  WARNING: This looks like infrastructure!")

print(f"\n📊 SCSI Devices: {len(scsi_devices)}")
for path, prod, drv in scsi_devices:
    print(f"   - {prod} (driver: {drv})")
    # Check if it looks like a host (should NOT appear)
    if 'host' in path.lower() or 'target' in path.lower():
        print(f"      ⚠️  WARNING: This looks like infrastructure!")

print(f"\n📊 USB Devices: {len(usb_devices)}")
for path, prod, drv in usb_devices[:5]:  # Show first 5
    print(f"   - {prod} (driver: {drv})")
if len(usb_devices) > 5:
    print(f"   ... and {len(usb_devices) - 5} more")

print(f"\n📊 HID Devices: {len(hid_devices)}")
for path, prod, drv in hid_devices[:3]:  # Show first 3
    print(f"   - {prod} (driver: {drv})")
if len(hid_devices) > 3:
    print(f"   ... and {len(hid_devices) - 3} more")

print("\n✅ Test complete!")
