# Monte Carlo Driver Manager

Monte Carlo is an advanced, automated driver management tool for Linux. It abstracts the complexity of kernel modules, allowing users to probe, load, and manage USB drivers safely and efficiently.

It is designed to detect devices without drivers and help users find the correct module, while actively preventing system instability through rigorous safety checks.

---

## Key Features

### 🛡️ Active Safety System
Montecarlo prioritizes system stability.
*   **Dependency Protection**: Before unloading a module, it checks for dependent modules (holders) and blocks the action if it would break other drivers.
*   **Hardware Locking**: It detects if a driver is currently controlling active hardware (e.g., your mouse or keyboard) and prevents accidental unloading.

### 🧠 Smart Dashboard
The dashboard provides a clean, noise-free view of your system.
*   **Intelligent Filtering**: Automatically hides internal kernel dependencies, showing only the "Root Modules" that you actually installed or loaded.
*   **Status Indicators**: Clearly marks drivers as `(In Use)` or `(Idle)` with distinct icons.

---

## User Interface

### 1. The Dashboard
Your command center. View all loaded USB drivers in real-time. The list is filtered to remove kernel noise, focusing on the drivers that matter.

![Dashboard Main View](Assets/dash.png)
*Active drivers are verified against hardware bindings.*

### 2. Available Modules (Repository)
Don't know which driver to use? Browse your kernel's native module repository. You can search, filter, and load drivers dynamically to test compatibility.

![Module Repository](Assets/modls.png)
*Search and load drivers specific to your kernel version.*

### 3. Telemetry & Logs
Transparency is key. Watch Montecarlo's decision-making process in real-time. See exactly what the daemon is doing, which devices are detected, and why a driver is allowed or blocked.

![Real-time Logs](Assets/logs.png)
*Detailed audit log of all actions.*

### 4. Restore & History
Made a mistake? The Restore tab keeps a history of all modules unloaded during the session, allowing you to quickly reload them with a single click.

![Restore History](Assets/restore.png)
*Undo capabilities for driver management.*

---

## Architecture

The system consists of three main components: a C Daemon, a Python UI, and a Shared Library.

```mermaid
graph TD
    subgraph Kernel Space
        UD["UDev Events"] --> Daemon
        Drivers["Kernel Drivers"]
    end

    subgraph User Space
        Daemon["Daemon Service<br>(C / Systemd)"]
        Socket(("Unix Socket<br>/tmp/montecarlo.sock"))
        UI["User Interface<br>(Python / GTK)"]
        Lib["Shared Library<br>(libmontecarlo.so)"]
    end

    Daemon -->|Listens| UD
    Daemon -->|Launches on Match| UI
    Daemon -->|Sends Target Syspath| Socket
    UI -->|Connects| Socket
    UI -->|Calls via Ctypes| Lib
    Lib -->|modprobe / rmmod| Drivers
    Lib -->|Checks Binding/Dmesg| Drivers
```

## Installation and Testing

### Prerequisites
*   `gcc`, `make`
*   `libudev-dev`
*   `python3`, `python3-gi` (GTK3)

### Build
```bash
# Clone the repository
git clone https://github.com/IRodriguez13/Montecarlo.git
cd Montecarlo

# Build Daemon and Shared Library
make
```

### Run Locally (Dev Mode)
To test the UI without installing the system service:

```bash
sudo MONTECARLO_DEV=1 python3 ui.py
```

## License

This project is licensed under the **GNU General Public License v3.0 (GPLv3)**.
