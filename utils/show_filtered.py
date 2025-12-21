#!/usr/bin/env python3
"""
Show what PCI devices were filtered out
"""
import subprocess

# Get all PCI devices from lspci
lspci_output = subprocess.check_output(['lspci', '-nn'], text=True)
all_pci = []
for line in lspci_output.strip().split('\n'):
    if line:
        bus_id = line.split()[0]
        all_pci.append((bus_id, line))

print(f"🔍 Total PCI devices in system: {len(all_pci)}")

# Get devices shown by Montecarlo
import ctypes

import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB_PATH = os.path.join(BASE_DIR, "libmontecarlo.so")
lib = ctypes.CDLL(LIB_PATH)

class DeviceInfo(ctypes.Structure):
    _fields_ = [
        ("syspath", ctypes.c_char * 256),
        ("vidpid", ctypes.c_char * 32),
        ("product", ctypes.c_char * 128),
        ("driver", ctypes.c_char * 64),
        ("subsystem", ctypes.c_char * 16),
    ]

devices = (DeviceInfo * 200)()
count = lib.mc_list_all_devices(devices, 200)

montecarlo_pci = set()
for i in range(count):
    dev = devices[i]
    subsystem = dev.subsystem.decode('utf-8')
    if subsystem == 'pci':
        syspath = dev.syspath.decode('utf-8')
        # Extract bus ID from syspath (e.g., /sys/.../0000:08:00.0)
        bus_id = syspath.split('/')[-1]
        montecarlo_pci.add(bus_id)

print(f"✅ PCI devices shown by Montecarlo: {len(montecarlo_pci)}")
print(f"❌ PCI devices filtered out: {len(all_pci) - len(montecarlo_pci)}\n")

print("🚫 Filtered devices (NOT shown in Montecarlo):")
for bus_id, desc in all_pci:
    if bus_id not in montecarlo_pci:
        print(f"   {desc}")
