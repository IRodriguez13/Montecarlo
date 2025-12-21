#!/usr/bin/env python3
import sys
import os
import time
import socket
import json
import threading
import ctypes
from ctypes import CDLL, c_int, c_char_p, c_char, POINTER, create_string_buffer, Structure, cast
import subprocess
import webbrowser

import gi
gi.require_version("Gtk", "3.0")
gi.require_version('Notify', '0.7')
from gi.repository import Gtk, GLib, Pango, Notify, Gdk

# --- CONFIG & LIBS ---

# Version
MONTECARLO_VERSION = "0.4.0"

# Socket Path (same logic as daemon)
def get_socket_path():
    """Get secure socket path for current user"""
    runtime_dir = os.getenv("XDG_RUNTIME_DIR")
    uid = os.getuid()
    
    if runtime_dir:
        return os.path.join(runtime_dir, "montecarlo.sock")
    
    # Check if /run/user/$UID exists
    runtime_path = f"/run/user/{uid}"
    if os.access(runtime_path, os.W_OK):
        return os.path.join(runtime_path, "montecarlo.sock")
    
    # Fallback to /tmp with UID
    return f"/tmp/montecarlo-{uid}.sock"

SOCK_PATH = get_socket_path()

# Path resolution from desktop/ subdir
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.environ.get("MONTECARLO_DEV"):
    HELPER_PATH = os.path.join(BASE_DIR, "montecarlo-helper")
    LIB_PATH = os.path.join(BASE_DIR, "libmontecarlo.so")
    LIBSD_PATH = os.path.join(BASE_DIR, "systemd/libsystemdctl.so")
else:
    HELPER_PATH = "/usr/bin/montecarlo-helper"
    LIB_PATH = "/usr/lib/libmontecarlo.so"
    LIBSD_PATH = "/usr/lib/libsystemdctl.so"

try:
    libmc = CDLL(LIB_PATH)
except OSError as e:
    print(f"Error loading library {LIB_PATH}: {e}")
    sys.exit(1)

# --- C TYPES DEFINITIONS ---

class MCDeviceInfo(Structure):
    _fields_ = [
        ("syspath", c_char * 256),
        ("vidpid", c_char * 32),
        ("product", c_char * 128),
        ("driver", c_char * 64),
        ("subsystem", c_char * 16)
    ]

# Signatures
libmc.mc_try_load_driver.argtypes = [c_char_p]
libmc.mc_try_load_driver.restype = c_int

libmc.mc_unload_driver.argtypes = [c_char_p]
libmc.mc_unload_driver.restype = c_int

# ...

        

libmc.mc_dev_has_driver.argtypes = [c_char_p]
libmc.mc_dev_has_driver.restype = c_int

libmc.mc_dmesg_has_activity.argtypes = [c_char_p]
libmc.mc_dmesg_has_activity.restype = c_int

libmc.mc_get_module_refcount.argtypes = [c_char_p]
libmc.mc_get_module_refcount.restype = c_int

libmc.mc_module_has_holders.argtypes = [ctypes.c_char_p]
libmc.mc_module_has_holders.restype = ctypes.c_int

libmc.mc_driver_is_in_use.argtypes = [ctypes.c_char_p]
libmc.mc_driver_is_in_use.restype = ctypes.c_int

libmc.mc_list_candidate_drivers.argtypes = [POINTER(c_char), c_int]
libmc.mc_list_candidate_drivers.restype = c_int

libmc.mc_list_all_devices.argtypes = [POINTER(MCDeviceInfo), c_int]
libmc.mc_list_all_devices.restype = c_int

libmc.mc_get_device_subsystem.argtypes = [c_char_p]
libmc.mc_get_device_subsystem.restype = c_char_p

# --- SYSTEMD TYPES ---

class ServiceInfo(Structure):
    _fields_ = [
        ("name", c_char * 256),
        ("description", c_char * 512),
        ("state", c_char * 32),
        ("sub_state", c_char * 32)
    ]

# Load Systemd Lib (Path already set in config)
try:
    libsd = CDLL(LIBSD_PATH)
    libsd.mc_list_services.argtypes = [POINTER(ServiceInfo), c_int]
    libsd.mc_list_services.restype = c_int
except OSError:
    print(f"Warning: Could not load {LIBSD_PATH}. Services tab will be empty.")
    libsd = None

# --- UI CLASS ---

class MontecarloUI(Gtk.Window):
    def __init__(self):
        super().__init__(title="Montecarlo Dashboard")
        self.set_default_size(900, 600)
        self.set_border_width(10)
        
        # State
        self.target_syspath = None
        self.running_auto = False
        
        # Layout (Removed redundant box)
        
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl_title = Gtk.Label()
        lbl_title.set_markup("<span size='x-large' weight='bold'>Montecarlo</span>")
        header_box.pack_start(lbl_title, False, False, 0)
        
        self.spinner = Gtk.Spinner()
        header_box.pack_start(self.spinner, False, False, 0)

        # Help Button (Right aligned)
        lbl_dummy = Gtk.Label()
        header_box.pack_start(lbl_dummy, True, True, 0) # spacer
        
        btn_help = Gtk.Button(label="Help")
        btn_help.set_image(Gtk.Image.new_from_icon_name("help-browser", Gtk.IconSize.BUTTON)) # system-help or help-browser usually ?
        btn_help.set_always_show_image(True)
        btn_help.set_tooltip_text("Help & Usage")
        btn_help.connect("clicked", self.on_help_clicked)
        header_box.pack_start(btn_help, False, False, 0)
        
        # Main Notebook
        self.notebook = Gtk.Notebook()
        
        # --- TAB 1: DASHBOARD ---
        self.build_dashboard_tab()
        
        # --- TAB 2: AVAILABLE MODULES ---
        self.build_repository_tab()

        # --- TAB 3: SERVICES ---
        self.build_services_tab()
        
        # --- TAB 4: TELEMETRY ---
        self.build_telemetry_tab()
        
        # --- TAB 5: RESTORE/HISTORY ---
        self.build_restore_tab()
        
        # --- TAB 6: ABOUT ---
        self.build_about_tab()
        
        # Add header and notebook to a main vertical box
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_vbox.pack_start(header_box, False, False, 5)
        main_vbox.pack_start(self.notebook, True, True, 0)
        self.add(main_vbox)
        
        # CLI Argument handling (if launched by daemon with arg)
        if len(sys.argv) > 1:
            self.target_syspath = sys.argv[1]
            self.log(f"[INIT] New Device Detected: {self.target_syspath}", "bold")
            # Redirect to Available Modules Tab as per user request
            self.notebook.set_current_page(1) # Available Modules is index 1
            
            # Optional: We could try to extract info and filter automatically
            # But user asked to "Allow user to search it based on device"
            self.log("Please search for a driver in the Available Modules list.", "green")
        
        # Start Socket Listener
        t = threading.Thread(target=self.socket_listener)
        t.daemon = True
        t.start()
        
        # Initial Scan
        self.refresh_devices()

        # Initialize Desktop Notifications
        Notify.init("Montecarlo")

        # PID File for Daemon Singleton Check
        self.pid_file = "/tmp/montecarlo_ui.pid"
        try:
            with open(self.pid_file, "w") as f:
                f.write(str(os.getpid()))
        except Exception as e:
            print(f"Failed to write PID file: {e}")

    def copy_to_clipboard(self, text):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        self.log(f"Copied to clipboard: {text}")

    def show_device_notification(self, syspath):
        """Show desktop notification when driverless device is detected."""
        # Extract device name/ID if possible (simplified)
        device_label = syspath.split('/')[-1] if syspath else "Unknown"
        
        notification = Notify.Notification.new(
            "USB Device Detected",
            f"Device without driver detected: {device_label}\nClick to find a driver",
            "drive-harddisk-usb"
        )
        
        # Add action to bring UI to front
        notification.add_action(
            "open",
            "Find Driver",
            self.on_notification_action,
            None
        )
        
        notification.set_urgency(Notify.Urgency.NORMAL)
        notification.show()
    
    def on_notification_action(self, notification, action, data):
        """Handle notification action: bring UI to front and switch to Available Modules."""
        self.present()  # Bring window to front
        self.notebook.set_current_page(1)  # Switch to Available Modules tab
        self.log("[Notification] User requested driver search from notification.", "bold")

    def socket_listener(self):
        # ... (same as before) ...
        server_address = '/tmp/montecarlo_socket'
        try:
            os.unlink(server_address)
        except OSError:
            if os.path.exists(server_address):
                self.log(f"Error removing socket: {server_address}")
                return

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(server_address)
            sock.listen(1)
            # self.log(f"Listening on {server_address}")
            while True:
                connection, client_address = sock.accept()
                try:
                    data = connection.recv(1024)
                    if data:
                        msg = data.decode('utf-8').strip()
                        GLib.idle_add(self.handle_cli_args, msg)
                finally:
                    connection.close()
        except Exception as e:
            # self.log(f"Socket error: {e}") 
            pass  

    def handle_cli_args(self, arg):
        self.target_syspath = arg
        self.log(f"[remote] New Device Detected: {arg}", "bold")
        self.notebook.set_current_page(1)
        self.log("Please search for a driver in the Available Modules list.", "green")

    def build_repository_tab(self):
        self.repo_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.repo_box.set_border_width(10)
        
        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lbl = Gtk.Label(label="Available Modules", xalign=0)
        lbl.get_style_context().add_class("title-3")
        header.pack_start(lbl, False, False, 0)
        
        # Spinner (Right aligned)
        self.repo_spinner = Gtk.Spinner()
        header.pack_end(self.repo_spinner, False, False, 0)
        
        self.repo_box.pack_start(header, False, False, 0)
        
        desc = Gtk.Label(label="Available kernel modules for your system.", xalign=0)
        desc.set_selectable(True)
        desc.set_can_focus(False)
        self.repo_box.pack_start(desc, False, False, 0)
        
        # Filter Controls Box
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        # Search Filter
        self.repo_search = Gtk.SearchEntry()
        self.repo_search.set_placeholder_text("Filter modules by name...")
        self.repo_search.connect("search-changed", self.on_repo_search_changed)
        filter_box.pack_start(self.repo_search, True, True, 0)
        
        # Bus Type Filter Dropdown
        bus_label = Gtk.Label(label="Bus Type:")
        filter_box.pack_start(bus_label, False, False, 0)
        
        self.bus_filter_combo = Gtk.ComboBoxText()
        self.bus_filter_combo.append("all", "All Buses")
        self.bus_filter_combo.append("usb", "USB")
        self.bus_filter_combo.append("pci", "PCI")
        self.bus_filter_combo.append("hid", "HID")
        self.bus_filter_combo.append("i2c", "I²C")
        self.bus_filter_combo.append("sdio", "SDIO")
        self.bus_filter_combo.append("scsi", "SCSI")
        self.bus_filter_combo.set_active_id("all")
        self.bus_filter_combo.connect("changed", self.on_bus_filter_changed)
        filter_box.pack_start(self.bus_filter_combo, False, False, 0)
        
        self.repo_box.pack_start(filter_box, False, False, 0)
        
        # Paned layout (List + Details)
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.repo_box.pack_start(paned, True, True, 0)
        
        # List: Name, Path, Bus (hidden for filtering)
        self.repo_store = Gtk.ListStore(str, str, str) # Name, FullPath, Bus
        
        # Make the underlying store sortable (FIX for GTK warning)
        self.repo_store.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        
        # Filterable Model
        self.repo_filter = self.repo_store.filter_new(None)
        self.repo_filter.set_visible_func(self.repo_filter_func)
        
        self.repo_tree = Gtk.TreeView(model=self.repo_filter)
        
        col_name = Gtk.TreeViewColumn("Module Name", Gtk.CellRendererText(), text=0)
        col_name.set_sort_column_id(0)  # This now works because store is sortable
        self.repo_tree.append_column(col_name)
        
        col_path = Gtk.TreeViewColumn("Path", Gtk.CellRendererText(), text=1)
        self.repo_tree.append_column(col_path)
        
        # Connect selection handler
        self.repo_tree.get_selection().connect("changed", self.on_repo_selection_changed)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add(self.repo_tree)
        paned.pack1(scroll, resize=True, shrink=False)
        
        # Details Pane
        frame_details = Gtk.Frame(label="Module Details")
        self.repo_details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.repo_details_box.set_border_width(10)
        
        self.lbl_repo_module_name = Gtk.Label(label="Select a module to view details.", xalign=0)
        self.lbl_repo_module_name.set_selectable(True)
        self.lbl_repo_module_name.set_can_focus(False)
        self.lbl_repo_module_desc = Gtk.Label(label="", xalign=0)
        self.lbl_repo_module_desc.set_selectable(True)
        self.lbl_repo_module_desc.set_can_focus(False)
        self.lbl_repo_module_desc.set_line_wrap(True)
        
        self.btn_repo_web_search = Gtk.Button(label="Search on Web")
        self.btn_repo_web_search.set_valign(Gtk.Align.START)
        self.btn_repo_web_search.set_halign(Gtk.Align.START)
        self.btn_repo_web_search.set_sensitive(False)
        self.btn_repo_web_search.connect("clicked", self.on_repo_web_search_clicked)
        
        self.repo_details_box.pack_start(self.lbl_repo_module_name, False, False, 0)
        self.repo_details_box.pack_start(self.lbl_repo_module_desc, False, False, 0)
        
        # Helper buttons box
        hlp_box = Gtk.Box(spacing=5)
        self.repo_details_box.pack_start(hlp_box, False, False, 5)
        
        hlp_box.pack_start(self.btn_repo_web_search, False, False, 0)
        
        self.btn_repo_copy = Gtk.Button(label="Copy Name")
        self.btn_repo_copy.set_sensitive(False)
        self.btn_repo_copy.connect("clicked", self.on_repo_copy_clicked)
        hlp_box.pack_start(self.btn_repo_copy, False, False, 0)
        
        frame_details.add(self.repo_details_box)
        paned.pack2(frame_details, resize=False, shrink=False)
        
        # Actions
        btn_box = Gtk.Box(spacing=10)
        
        btn_refresh = Gtk.Button(label="Refresh List")
        btn_refresh.set_image(Gtk.Image.new_from_icon_name("view-refresh", Gtk.IconSize.BUTTON))
        btn_refresh.connect("clicked", self.refresh_repository)
        btn_box.pack_start(btn_refresh, False, False, 0)
        
        self.btn_repo_load = Gtk.Button(label="Load Selected Module")
        self.btn_repo_load.get_style_context().add_class("suggested-action")
        self.btn_repo_load.set_sensitive(False)
        self.btn_repo_load.connect("clicked", self.on_repo_load_clicked)
        btn_box.pack_start(self.btn_repo_load, False, False, 0)
        
        self.repo_box.pack_start(btn_box, False, False, 0)
        
        self.notebook.append_page(self.repo_box, Gtk.Label(label="Available Modules"))
        
        # Auto-load list in background
        GLib.timeout_add(500, self.refresh_repository)

        
    def repo_filter_func(self, model, iter, data):
        # Text search filter
        query = self.repo_search.get_text().lower()
        name = model[iter][0].lower()
        
        if query and query not in name:
            return False
        
        # Bus type filter
        bus_filter = self.bus_filter_combo.get_active_id()
        if bus_filter and bus_filter != "all":
            module_bus = model[iter][2].lower()  # Bus is in column 2
            if bus_filter not in module_bus:
                return False
        
        return True

    def on_repo_search_changed(self, widget):
        self.repo_filter.refilter()
    
    def on_bus_filter_changed(self, widget):
        self.repo_filter.refilter()
        bus_name = widget.get_active_text()
        self.log(f"[Filter] Showing {bus_name} modules only", "bold")
        
    def refresh_repository(self, widget=None):
        if widget: self.repo_spinner.start()
        # Thread out the I/O
        t = threading.Thread(target=self._refresh_repo_thread)
        t.daemon = True
        t.start()
        
    def _refresh_repo_thread(self):
        # Get loaded modules first to exclude them
        try:
            loaded = self.get_loaded_modules_set()
        except:
            loaded = set()
        
        kernel_ver = os.uname().release
        base_path = f"/lib/modules/{kernel_ver}/kernel/drivers"
        
        # Bus directories to scan
        bus_dirs = {
            "usb": "usb",
            "pci": "pci",
            "hid": "hid",
            "i2c": "i2c",
            "scsi": "scsi",
            "mmc": "sdio",  # SDIO is under mmc directory
            "net": "net"    # Network drivers (often PCI)
        }
        
        new_rows = []
        
        for bus_subdir, bus_type in bus_dirs.items():
            bus_path = f"{base_path}/{bus_subdir}"
            if not os.path.exists(bus_path):
                continue
                
            for root, dirs, files in os.walk(bus_path):
                for f in files:
                    if f.endswith(".ko") or f.endswith(".ko.xz") or f.endswith(".ko.zst"):
                        name = f.split('.')[0].replace('-', '_')
                        if name not in loaded:
                            full_path = os.path.join(root, f)
                            new_rows.append([name, full_path, bus_type])
        
        GLib.idle_add(self._update_repo_ui, new_rows)

    def _update_repo_ui(self, rows):
        self.repo_store.clear()
        for r in rows:
            self.repo_store.append(r)
        self.repo_spinner.stop()
        self.log(f"Repository refreshed: {len(rows)} modules available.", "bold")
    
    def on_repo_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter:
            self.btn_repo_load.set_sensitive(True)
            self.btn_repo_web_search.set_sensitive(True)
            self.btn_repo_copy.set_sensitive(True)
            
            # Update Details
            module_name = model[treeiter][0]
            
            self.lbl_repo_module_name.set_markup(f"<b>Module:</b> {module_name}")
            
            # Get Module Description via modinfo
            desc = "No description available."
            try:
                res = subprocess.run(["modinfo", "-F", "description", module_name], capture_output=True, text=True)
                if res.returncode == 0 and res.stdout.strip():
                    desc = res.stdout.strip()
                else:
                    desc = f"Module {module_name} (No description available)"
            except Exception:
                desc = f"Module {module_name}"
            
            self.lbl_repo_module_desc.set_markup(f"<i>{desc}</i>")
        else:
            self.btn_repo_load.set_sensitive(False)
            self.btn_repo_web_search.set_sensitive(False)
            self.btn_repo_copy.set_sensitive(False)
            self.lbl_repo_module_name.set_text("Select a module to view details.")
            self.lbl_repo_module_desc.set_text("")
    
    def on_repo_web_search_clicked(self, widget):
        selection = self.repo_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        
        module_name = model[treeiter][0]
        
        # Open Google search for the module
        url = f"https://www.google.com/search?q=linux+kernel+module+{module_name}"
        self.open_url(url)
                        

    def on_repo_load_clicked(self, widget):
        selection = self.repo_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter: return
        
        module = model[treeiter][0]
        self.log(f"Loading {module} from repository...", "bold")
        
        # Use PolicyKit for privileged operation
        try:
            result = subprocess.run(
                ["pkexec", HELPER_PATH, "load", module],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                self.log(f"  -> Module {module} loaded.", "green")
                # Remove from repo list (it's now loaded)
                # Must convert Filter iter to Child Store iter
                child_iter = self.repo_filter.convert_iter_to_child_iter(treeiter)
                self.repo_store.remove(child_iter)
                
                # Wait for udev to settle (proper sync instead of arbitrary sleep)
                subprocess.run(["udevadm", "settle", "--timeout=2"], capture_output=True)
                self.refresh_devices()
            else:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                self.log(f"  -> Failed to load {module}: {error_msg}", "red")
                
        except subprocess.TimeoutExpired:
            self.log(f"  -> Timeout waiting for authentication.", "red")
        except FileNotFoundError:
            self.log(f"  -> PolicyKit not available. Install policykit-1.", "red")
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="PolicyKit Required"
            )
            dialog.format_secondary_text(
                "Montecarlo requires PolicyKit for privilege elevation.\n\n"
                "Please install: sudo apt install policykit-1"
            )
            dialog.run()
            dialog.destroy()
        except Exception as e:
            self.log(f"  -> Error: {e}", "red")

    def build_services_tab(self):
        self.svc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.svc_box.set_border_width(10)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        lbl = Gtk.Label(label="System Services", xalign=0)
        lbl.get_style_context().add_class("title-3")
        header.pack_start(lbl, False, False, 0)
        
        self.svc_spinner = Gtk.Spinner()
        header.pack_end(self.svc_spinner, False, False, 0)
        self.svc_box.pack_start(header, False, False, 0)

        # Controls & Filter
        control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.svc_search = Gtk.SearchEntry()
        self.svc_search.set_placeholder_text("Filter services...")
        self.svc_search.connect("search-changed", self.on_svc_search_changed)
        control_box.pack_start(self.svc_search, True, True, 0)
        
        btn_refresh = Gtk.Button(label="Refresh")
        btn_refresh.set_image(Gtk.Image.new_from_icon_name("view-refresh", Gtk.IconSize.BUTTON))
        btn_refresh.connect("clicked", self.refresh_services)
        control_box.pack_start(btn_refresh, False, False, 0)
        
        self.svc_box.pack_start(control_box, False, False, 0)

        # List / Details Split
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.svc_box.pack_start(paned, True, True, 0)

        # List
        # Name, Description, State, SubState
        self.svc_store = Gtk.ListStore(str, str, str, str)
        self.svc_filter = self.svc_store.filter_new(None)
        self.svc_filter.set_visible_func(self.svc_filter_func)
        
        self.svc_tree = Gtk.TreeView(model=self.svc_filter)
        
        # Cols
        cols = [
            ("Service", 0),
            ("State", 2),
            ("SubState", 3)
        ]
        
        for title, idx in cols:
            renderer = Gtk.CellRendererText()
            col = Gtk.TreeViewColumn(title, renderer, text=idx)
            if idx == 2: # Colorize state
                col.set_cell_data_func(renderer, self.svc_state_color_func)
            self.svc_tree.append_column(col)

        self.svc_tree.get_selection().connect("changed", self.on_svc_selection_changed)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.add(self.svc_tree)
        paned.pack1(scroll, resize=True, shrink=False)

        # Details & Actions
        frame = Gtk.Frame(label="Service Management")
        details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        details_box.set_border_width(10)
        
        self.lbl_svc_name = Gtk.Label(label="Select a service", xalign=0)
        self.lbl_svc_name.set_selectable(True)
        self.lbl_svc_name.set_can_focus(False)
        self.lbl_svc_desc = Gtk.Label(label="", xalign=0)
        self.lbl_svc_desc.set_selectable(True)
        self.lbl_svc_desc.set_can_focus(False)
        self.lbl_svc_desc.set_line_wrap(True)
        
        details_box.pack_start(self.lbl_svc_name, False, False, 0)
        details_box.pack_start(self.lbl_svc_desc, False, False, 5)

        # Copy btn
        self.btn_svc_copy = Gtk.Button(label="Copy Name")
        self.btn_svc_copy.set_sensitive(False)
        self.btn_svc_copy.set_halign(Gtk.Align.START)
        self.btn_svc_copy.connect("clicked", self.on_svc_copy_clicked)
        details_box.pack_start(self.btn_svc_copy, False, False, 5)

        # Action Buttons
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        self.btn_svc_start = Gtk.Button(label="Start")
        self.btn_svc_stop = Gtk.Button(label="Stop")
        self.btn_svc_enable = Gtk.Button(label="Enable")
        self.btn_svc_disable = Gtk.Button(label="Disable")
        
        for btn in [self.btn_svc_start, self.btn_svc_stop, self.btn_svc_enable, self.btn_svc_disable]:
            btn.set_sensitive(False)
            action_box.pack_start(btn, True, True, 0)

        self.btn_svc_start.connect("clicked", lambda x: self.on_service_action("start"))
        self.btn_svc_stop.connect("clicked", lambda x: self.on_service_action("stop"))
        self.btn_svc_enable.connect("clicked", lambda x: self.on_service_action("enable"))
        self.btn_svc_disable.connect("clicked", lambda x: self.on_service_action("disable"))

        # Destructive actions red
        self.btn_svc_stop.get_style_context().add_class("destructive-action")
        self.btn_svc_start.get_style_context().add_class("suggested-action")
        
        details_box.pack_start(action_box, False, False, 0)
        frame.add(details_box)
        paned.pack2(frame, resize=False, shrink=False)

        self.notebook.append_page(self.svc_box, Gtk.Label(label="Services"))
        
        # Auto-load
        if libsd:
            GLib.timeout_add(1000, self.refresh_services)

    def svc_state_color_func(self, col, cell, model, iter, data):
        state = model[iter][2]
        if state == "active":
            cell.set_property("foreground", "green")
        elif state == "failed":
            cell.set_property("foreground", "red")
        else:
            cell.set_property("foreground", "gray")

    def svc_filter_func(self, model, iter, data):
        query = self.svc_search.get_text().lower()
        if not query: return True
        
        name = model[iter][0].lower()
        return query in name

    def on_svc_search_changed(self, widget):
        self.svc_filter.refilter()
        
    def refresh_services(self, widget=None):
        if not libsd: return
        if widget: self.svc_spinner.start()
        
        t = threading.Thread(target=self._refresh_svc_thread)
        t.daemon = True
        t.start()
        
    def _refresh_svc_thread(self):
        max_svc = 500
        ArrayType = ServiceInfo * max_svc
        svc_array = ArrayType()
        
        count = libsd.mc_list_services(cast(svc_array, POINTER(ServiceInfo)), max_svc)
        
        new_rows = []
        for i in range(count):
            s = svc_array[i]
            new_rows.append([
                s.name.decode('utf-8', 'ignore'),
                s.description.decode('utf-8', 'ignore'),
                s.state.decode('utf-8', 'ignore'),
                s.sub_state.decode('utf-8', 'ignore')
            ])
            
        GLib.idle_add(self._update_svc_ui, new_rows)

    def _update_svc_ui(self, rows):
        # Only update if changed or empty? For now full refresh
        # Preserve selection
        sel = self.svc_tree.get_selection()
        model, iter = sel.get_selected()
        selected_name = model[iter][0] if iter else None
        
        self.svc_store.clear()
        for r in rows:
            self.svc_store.append(r)
            
        # Try restore selection
        if selected_name:
            for row in self.svc_store:
                if row[0] == selected_name:
                    # self.svc_tree.set_cursor(row.path) # Can be annoying if list jumps
                    break

        self.svc_spinner.stop()

    def on_svc_selection_changed(self, selection):
        model, iter = selection.get_selected()
        if iter:
            name = model[iter][0]
            desc = model[iter][1]
            state = model[iter][2]
            
            self.lbl_svc_name.set_markup(f"<b>{name}</b>")
            self.lbl_svc_desc.set_text(desc)
            
            # Enable buttons
            self.btn_svc_start.set_sensitive(True)
            self.btn_svc_stop.set_sensitive(True)
            self.btn_svc_enable.set_sensitive(True)
            self.btn_svc_disable.set_sensitive(True)
            self.btn_svc_copy.set_sensitive(True)
            
            # Smart sensitivity
            if state == "active":
                self.btn_svc_start.set_sensitive(False)
            else:
                self.btn_svc_stop.set_sensitive(False)
        else:
            self.lbl_svc_name.set_text("Select a service")
            self.lbl_svc_desc.set_text("")
            self.btn_svc_start.set_sensitive(False)
            self.btn_svc_stop.set_sensitive(False)
            self.btn_svc_enable.set_sensitive(False)
            self.btn_svc_disable.set_sensitive(False)
            self.btn_svc_copy.set_sensitive(False)

    def on_service_action(self, action):
        sel = self.svc_tree.get_selection()
        model, iter = sel.get_selected()
        if not iter: return
        
        service = model[iter][0]
        self.log(f"Service Action: {action} {service}...", "bold")
        
        # PolicyKit execution
        try:
            result = subprocess.run(
                ["pkexec", HELPER_PATH, "service", action, service],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                self.log(f"  -> Success: {service} {action}d", "green")
                
                # Add to Restore List if stopped/disabled
                if action in ["stop", "disable"]:
                    self.add_restore_item("Service", service)
                
                # Refresh immediately and then again after 1s to catch state changes
                self.refresh_services()
                GLib.timeout_add(1500, self.refresh_services)
                
                Notify.Notification.new("Service Manager", f"Successfully {action}d {service}", "emblem-system").show()
            else:
                err = result.stderr.strip()
                self.log(f"  -> Failed: {err}", "red")
                Notify.Notification.new("Service Error", f"Failed to {action} {service}: {err}", "dialog-error").show()
                
        except Exception as e:
            self.log(f"Error executing service action: {e}", "red")

    def on_svc_copy_clicked(self, widget):
        sel = self.svc_tree.get_selection()
        model, iter = sel.get_selected()
        if iter:
            name = model[iter][0]
            self.copy_to_clipboard(name)

    def on_repo_copy_clicked(self, widget):
        selection = self.repo_tree.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            name = model[treeiter][0]
            self.copy_to_clipboard(name)

    def get_loaded_modules_set(self):
        buf = create_string_buffer(4096 * 10) # 40kb buffer
        count = libmc.mc_list_loaded_modules(buf, ctypes.sizeof(buf))
        
        # Extract string from null-separated buffer
        raw = buf.raw
        names = raw.split(b'\0')
        final_names = []
        for i in range(count):
            if i < len(names):
                final_names.append(names[i].decode('utf-8', 'ignore'))
        
        return set(final_names)

    def build_dashboard_tab(self):
        self.dash_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.dash_box.set_border_width(10)
        
        # Toolbar
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        self.refresh_btn = Gtk.Button(label="Rescan Devices")
        self.refresh_btn.set_image(Gtk.Image.new_from_icon_name("view-refresh", Gtk.IconSize.BUTTON))
        self.refresh_btn.connect("clicked", self.on_refresh_clicked)
        toolbar.pack_start(self.refresh_btn, False, False, 0)
        
        toolbar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 10)
        
        # REMOVED Auto-Find button as per user request (Redundant for already bound devices)
        
        self.btn_unload = Gtk.Button(label="Unload Driver")
        self.btn_unload.connect("clicked", self.on_unload_clicked)
        toolbar.pack_start(self.btn_unload, False, False, 0)
        
        self.dash_box.pack_start(toolbar, False, False, 0)
        
        # Paned view for List / Details
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.dash_box.pack_start(paned, True, True, 0)
        
        # A) Device List
        # Model: Syspath, VidPid, Product, Driver, IconName
        self.dev_store = Gtk.ListStore(str, str, str, str, str)
        self.dev_tree = Gtk.TreeView(model=self.dev_store)
        
        # Columns
        col_prod = Gtk.TreeViewColumn("Device")
        cell_pix = Gtk.CellRendererPixbuf()
        col_prod.pack_start(cell_pix, False)
        col_prod.add_attribute(cell_pix, "icon-name", 4)
        
        cell_text = Gtk.CellRendererText()
        col_prod.pack_start(cell_text, True)
        col_prod.add_attribute(cell_text, "text", 2)
        self.dev_tree.append_column(col_prod)
        
        self.dev_tree.append_column(Gtk.TreeViewColumn("ID", Gtk.CellRendererText(), text=1))
        
        col_drv = Gtk.TreeViewColumn("Driver")
        cell_drv = Gtk.CellRendererText()
        col_drv.pack_start(cell_drv, True)
        col_drv.add_attribute(cell_drv, "text", 3)
        self.dev_tree.append_column(col_drv)
        
        self.dev_tree.get_selection().connect("changed", self.on_dev_selection_changed)
        
        scroll_list = Gtk.ScrolledWindow()
        scroll_list.set_vexpand(True)
        scroll_list.add(self.dev_tree)
        paned.pack1(scroll_list, resize=True, shrink=False)

        # B) Details Pane
        frame_details = Gtk.Frame(label="Device Details")
        self.details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.details_box.set_border_width(10)
        
        self.lbl_detail_name = Gtk.Label(label="Select a device to view details.", xalign=0)
        self.lbl_detail_name.set_selectable(True)
        self.lbl_detail_name.set_can_focus(False)
        self.lbl_detail_id = Gtk.Label(label="", xalign=0)
        self.lbl_detail_id.set_selectable(True)
        self.lbl_detail_id.set_can_focus(False)
        self.lbl_detail_path = Gtk.Label(label="", xalign=0)
        self.lbl_detail_path.set_selectable(True)
        self.lbl_detail_path.set_can_focus(False)
        self.lbl_detail_desc = Gtk.Label(label="", xalign=0) # New Description Label
        self.lbl_detail_desc.set_selectable(True)
        self.lbl_detail_desc.set_can_focus(False)
        self.lbl_detail_desc.set_line_wrap(True)

        self.btn_web_search = Gtk.Button(label="Search on Web")
        self.btn_web_search.set_valign(Gtk.Align.START)
        self.btn_web_search.set_halign(Gtk.Align.START)
        self.btn_web_search.set_sensitive(False)
        self.btn_web_search.connect("clicked", self.on_web_search_clicked)
        
        self.details_box.pack_start(self.lbl_detail_name, False, False, 0)
        self.details_box.pack_start(self.lbl_detail_id, False, False, 0)
        self.details_box.pack_start(self.lbl_detail_path, False, False, 0)
        self.details_box.pack_start(self.lbl_detail_desc, False, False, 0)
        self.details_box.pack_start(self.btn_web_search, False, False, 5)
        
        frame_details.add(self.details_box)
        paned.pack2(frame_details, resize=False, shrink=False)

        self.notebook.append_page(self.dash_box, Gtk.Label(label="Devices Dashboard"))

    # ... Telemetry log logic remains same ...
    def build_telemetry_tab(self):
        self.tele_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.tele_box.set_border_width(10)
        
        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        self.log_view = Gtk.TextView()
        self.log_view.set_editable(False)
        self.log_view.set_monospace(True)
        # Style log
        self.log_view.set_left_margin(10)
        self.log_buf = self.log_view.get_buffer()
        
        self.tag_bold = self.log_buf.create_tag("bold", weight=Pango.Weight.BOLD)
        self.tag_green = self.log_buf.create_tag("green", foreground="green")
        self.tag_red = self.log_buf.create_tag("red", foreground="red")
        
        scroll.add(self.log_view)
        self.tele_box.pack_start(scroll, True, True, 0)
        
        self.notebook.append_page(self.tele_box, Gtk.Label(label="Telemetry Log"))

    def build_restore_tab(self):
        self.restore_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.restore_box.set_border_width(10)
        
        # Split View
        paned = Gtk.Paned(orientation=Gtk.Orientation.VERTICAL)
        self.restore_box.pack_start(paned, True, True, 0)
        
        # --- TOP: MODULES ---
        frame_mod = Gtk.Frame(label="Unloaded Drivers")
        mod_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        mod_box.set_border_width(5)
        
        self.restore_modules_store = Gtk.ListStore(str) # Name
        self.restore_modules_tree = Gtk.TreeView(model=self.restore_modules_store)
        self.restore_modules_tree.append_column(Gtk.TreeViewColumn("Module Name", Gtk.CellRendererText(), text=0))
        
        scroll_mod = Gtk.ScrolledWindow()
        scroll_mod.set_vexpand(True)
        scroll_mod.add(self.restore_modules_tree)
        mod_box.pack_start(scroll_mod, True, True, 0)
        
        btn_box_mod = Gtk.Box(spacing=5)
        btn_restore_mod = Gtk.Button(label="Reload Driver")
        btn_restore_mod.connect("clicked", self.on_restore_module_clicked)
        btn_clear_mod = Gtk.Button(label="Clear List")
        btn_clear_mod.connect("clicked", self.on_clear_modules_clicked)
        
        btn_box_mod.pack_start(btn_restore_mod, False, False, 0)
        btn_box_mod.pack_start(btn_clear_mod, False, False, 0)
        mod_box.pack_start(btn_box_mod, False, False, 0)
        
        frame_mod.add(mod_box)
        paned.pack1(frame_mod, resize=True, shrink=False)
        
        # --- BOTTOM: SERVICES ---
        frame_svc = Gtk.Frame(label="Stopped Services")
        svc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        svc_box.set_border_width(5)
        
        self.restore_services_store = Gtk.ListStore(str) # Name
        self.restore_services_tree = Gtk.TreeView(model=self.restore_services_store)
        self.restore_services_tree.append_column(Gtk.TreeViewColumn("Service Name", Gtk.CellRendererText(), text=0))
        
        scroll_svc = Gtk.ScrolledWindow()
        scroll_svc.set_vexpand(True)
        scroll_svc.add(self.restore_services_tree)
        svc_box.pack_start(scroll_svc, True, True, 0)
        
        btn_box_svc = Gtk.Box(spacing=5)
        btn_restore_svc = Gtk.Button(label="Restart Service")
        btn_restore_svc.connect("clicked", self.on_restore_service_clicked)
        btn_clear_svc = Gtk.Button(label="Clear List")
        btn_clear_svc.connect("clicked", self.on_clear_services_clicked)
        
        btn_box_svc.pack_start(btn_restore_svc, False, False, 0)
        btn_box_svc.pack_start(btn_clear_svc, False, False, 0)
        svc_box.pack_start(btn_box_svc, False, False, 0)
        
        frame_svc.add(svc_box)
        paned.pack2(frame_svc, resize=True, shrink=False)
        
        # Custom Tab Label with Badge
        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        lbl_tab = Gtk.Label(label="Restore")
        self.lbl_restore_badge = Gtk.Label(label="0")
        
        # Badge Styling
        ctx = self.lbl_restore_badge.get_style_context()
        ctx.add_class("badge")
        css_provider = Gtk.CssProvider()
        css = b".badge { background-color: #CC0000; color: white; border-radius: 10px; padding: 2px 6px; font-weight: bold; font-size: 10px; }"
        css_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.lbl_restore_badge.set_visible(False)

        tab_box.pack_start(lbl_tab, False, False, 0)
        tab_box.pack_start(self.lbl_restore_badge, False, False, 0)
        tab_box.show_all()
        self.lbl_restore_badge.set_visible(False)

        self.notebook.append_page(self.restore_box, tab_box)

    def add_restore_item(self, item_type, name):
        store = self.restore_modules_store if item_type == "Module" else self.restore_services_store
        
        # Check duplicates
        for row in store:
            if row[0] == name:
                return # Already exists
        
        store.append([name])
        self.update_restore_badge()
        
    def update_restore_badge(self):
        total = len(self.restore_modules_store) + len(self.restore_services_store)
        self.lbl_restore_badge.set_text(str(total))
        self.lbl_restore_badge.set_visible(total > 0)

    def on_restore_module_clicked(self, widget):
        selection = self.restore_modules_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter: return
        
        name = model[treeiter][0]
        self.log(f"Reloading Module: {name}...", "bold")
        
        try:
            subprocess.run(["pkexec", HELPER_PATH, "load", name], check=True)
            self.log(f"  -> Module {name} reloaded.", "green")
            
            self.restore_modules_store.remove(treeiter)
            self.update_restore_badge()
            
            subprocess.run(["udevadm", "settle"], capture_output=True)
            self.refresh_devices()
        except Exception as e:
            self.log(f"  -> Failed: {e}", "red")

    def on_clear_modules_clicked(self, widget):
        self.restore_modules_store.clear()
        self.update_restore_badge()

    def on_restore_service_clicked(self, widget):
        selection = self.restore_services_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter: return
        
        name = model[treeiter][0]
        self.log(f"Restarting Service: {name}...", "bold")
        
        try:
            subprocess.run(["pkexec", HELPER_PATH, "service", "start", name], check=True)
            self.log(f"  -> Service {name} started.", "green")
            
            self.restore_services_store.remove(treeiter)
            self.update_restore_badge()
            
            self.refresh_services()
            GLib.timeout_add(1500, self.refresh_services)
        except Exception as e:
            self.log(f"  -> Failed: {e}", "red")

    def on_clear_services_clicked(self, widget):
        self.restore_services_store.clear()
        self.update_restore_badge()

    def build_about_tab(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        vbox.set_border_width(40)
        
        # Logo/Title
        title = Gtk.Label()
        title.set_markup(f"<span size='xx-large' weight='bold'>Montecarlo {MONTECARLO_VERSION}</span>")
        vbox.pack_start(title, False, False, 0)
        
        # Subtitle
        sub = Gtk.Label(label="Advanced Linux USB Driver Manager")
        sub.get_style_context().add_class("title-3")
        vbox.pack_start(sub, False, False, 0)
        
        # Description
        desc_txt = (
            "Montecarlo allows you to probe, load, and unload kernel modules safely.\n"
            "It checks for active use before unloading to protect your system.\n\n"
            f"Version: {MONTECARLO_VERSION}"
        )
        desc = Gtk.Label(label=desc_txt)
        desc.set_selectable(True)
        desc.set_can_focus(False)
        desc.set_justify(Gtk.Justification.CENTER)
        vbox.pack_start(desc, False, False, 0)
        
        # Link
        # Gtk.LinkButton sometimes fails as root. Using manual button with privilege drop.
        btn_link = Gtk.Button(label="Visit GitHub Repository")
        btn_link.set_image(Gtk.Image.new_from_icon_name("web-browser", Gtk.IconSize.BUTTON))
        btn_link.connect("clicked", lambda x: self.open_url("https://github.com/IRodriguez13/Montecarlo"))
        vbox.pack_start(btn_link, False, False, 0)
        
        # Credits
        credits = Gtk.Label(label="Developed by I. Rodriguez")
        credits.get_style_context().add_class("dim-label")
        vbox.pack_end(credits, False, False, 0)
        
        self.notebook.append_page(vbox, Gtk.Label(label="About"))

    def open_url(self, url):
        self.log(f"Opening {url}...", "bold")
        sudo_user = os.environ.get('SUDO_USER')
        if sudo_user:
            try:
                subprocess.Popen(['runuser', '-u', sudo_user, '--', 'xdg-open', url])
            except Exception as e:
                self.log(f"Failed to open browser as {sudo_user}: {e}", "red")
        else:
            webbrowser.open(url)

    def on_help_clicked(self, widget):
        dialog = Gtk.Dialog(
            title="Help & Tutorial",
            transient_for=self,
            flags=0
        )
        dialog.set_default_size(600, 500)
        
        # Content area
        box = dialog.get_content_area()
        box.set_border_width(20)
        box.set_spacing(15)
        
        # Title
        title = Gtk.Label()
        title.set_markup("<span size='x-large' weight='bold'>Welcome to Montecarlo</span>")
        box.pack_start(title, False, False, 0)
        
        # Scrolled window for content
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=15)
        content_box.set_border_width(10)
        
        # Section 1: What is a driver?
        section1_title = Gtk.Label()
        section1_title.set_markup("<b>❓ What is a driver?</b>")
        section1_title.set_xalign(0)
        content_box.pack_start(section1_title, False, False, 0)
        
        section1_text = Gtk.Label(
            label="A driver is a piece of software that allows your operating system to communicate "
                  "with hardware devices. Without the correct driver, your USB device might not work at all.\n\n"
                  "Linux drivers are called 'kernel modules' and are stored in /lib/modules/."
        )
        section1_text.set_selectable(True)
        section1_text.set_can_focus(False)
        section1_text.set_line_wrap(True)
        section1_text.set_xalign(0)
        content_box.pack_start(section1_text, False, False, 0)
        
        # Section 2: When to use Montecarlo
        section2_title = Gtk.Label()
        section2_title.set_markup("<b>🔌 When should I use Montecarlo?</b>")
        section2_title.set_xalign(0)
        content_box.pack_start(section2_title, False, False, 0)
        
        section2_text = Gtk.Label(
            label="Use Montecarlo when:\n"
                  "  • You connect a USB device and it doesn't work\n"
                  "  • You see an 'Unknown device' in your system\n"
                  "  • You need to test different drivers for generic USB chips\n"
                  "  • You want to safely unload unused drivers\n\n"
                  "Montecarlo automatically detects devices without drivers and helps you find the right module."
        )
        section2_text.set_selectable(True)
        section2_text.set_can_focus(False)
        section2_text.set_line_wrap(True)
        section2_text.set_xalign(0)
        content_box.pack_start(section2_text, False, False, 0)
        
        # Section 3: How to use
        section3_title = Gtk.Label()
        section3_title.set_markup("<b>📖 How to use Montecarlo</b>")
        section3_title.set_xalign(0)
        content_box.pack_start(section3_title, False, False, 0)
        
        section3_text = Gtk.Label(
            label="1. Dashboard Tab: View all connected USB devices and their current drivers\n"
                  "2. Available Modules Tab: Browse and load drivers from your system\n"
                  "3. Connect a device: Montecarlo will notify you if it needs a driver\n"
                  "4. Load a driver: Select it from the list and click 'Load Module'\n"
                  "5. Authentication: You'll be asked for your password (via PolicyKit)\n\n"
                  "Safety Features:\n"
                  "  • Can't unload drivers in active use\n"
                  "  • Warns you before dangerous operations\n"
                  "  • Restores removed drivers if needed"
        )
        section3_text.set_selectable(True)
        section3_text.set_can_focus(False)
        section3_text.set_line_wrap(True)
        section3_text.set_xalign(0)
        content_box.pack_start(section3_text, False, False, 0)
        
        # Section 4: Tips
        section4_title = Gtk.Label()
        section4_title.set_markup("<b>💡 Pro Tips</b>")
        section4_title.set_xalign(0)
        content_box.pack_start(section4_title, False, False, 0)
        
        section4_text = Gtk.Label(
            label="• Use the search box to filter modules by name\n"
                  "• Click 'Search on Web' to find more info about a driver\n"
                  "• Module descriptions show what each driver is for\n"
                  "• Check the Telemetry tab to see what Montecarlo is doing\n"
                  "• Visit the Restore tab to reload previously removed drivers"
        )
        section4_text.set_selectable(True)
        section4_text.set_can_focus(False)
        section4_text.set_line_wrap(True)
        section4_text.set_xalign(0)
        content_box.pack_start(section4_text, False, False, 0)
        
        scrolled.add(content_box)
        box.pack_start(scrolled, True, True, 0)
        
        # Close button
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def log(self, text, tag=None):
        def _log():
            end = self.log_buf.get_end_iter()
            ts = time.strftime("[%H:%M:%S] ")
            self.log_buf.insert(end, ts)
            
            end = self.log_buf.get_end_iter()
            if tag:
                self.log_buf.insert_with_tags_by_name(end, text + "\n", tag)
            else:
                self.log_buf.insert(end, text + "\n")
                
            # Scroll to end using mark (avoids get_vadjustment deprecation)
            mark = self.log_buf.get_insert()
            self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        
        GLib.idle_add(_log)

    # --- LOGIC ---

    def on_refresh_clicked(self, widget):
        self.refresh_devices()

    def refresh_devices(self):
        self.log("Scanning USB devices...")
        self.spinner.start()
        self.refresh_btn.set_sensitive(False)
        self.scanning = True
        t = threading.Thread(target=self._scan_thread)
        t.daemon = True
        t.start()

    def update_dev_list(self, ui_list):
        self.dev_store.clear()
        for item in ui_list:
            self.dev_store.append(item)
            
        self.spinner.stop()
        self.refresh_btn.set_sensitive(True)
        self.scanning = False
        self.log(f"Scan complete. Found {len(ui_list)} items.")

    def _scan_thread(self):
        # 1. Physical Devices
        max_devs = 64
        devs_buf = (MCDeviceInfo * max_devs)()
        count = libmc.mc_list_all_devices(devs_buf, max_devs)
        
        # 2. Loaded Modules
        try:
            loaded_set = self.get_loaded_modules_set()
        except:
            loaded_set = set()

        # Track used drivers
        used_drivers = set()
        
        # Prepare list for UI
        ui_list = []
        
        for i in range(count):
            d = devs_buf[i]
            s_syspath = d.syspath.decode('utf-8', 'ignore')
            s_vidpid = d.vidpid.decode('utf-8', 'ignore')
            s_product = d.product.decode('utf-8', 'ignore')
            s_driver = d.driver.decode('utf-8', 'ignore')
            
            if s_driver != "None":
                used_drivers.add(s_driver)
                # USER REQ: Explicitly show (In Use)
                s_driver_display = f"{s_driver} (In Use)"
            else:
                s_driver_display = s_driver
            
            icon = "drive-harddisk-usb" # default
            p_lower = s_product.lower()
            d_lower = s_driver.lower()
            
            if "mouse" in p_lower: icon = "input-mouse"
            elif "keyboard" in p_lower: icon = "input-keyboard"
            elif "hub" in p_lower: icon = "network-server"
            elif "cam" in p_lower or "video" in p_lower: icon = "camera-web"
            elif "audio" in p_lower or "sound" in p_lower: icon = "audio-card"
            elif "print" in p_lower: icon = "printer"
            elif "storage" in p_lower or "flash" in p_lower: icon = "drive-removable-media"
            elif "bluetooth" in p_lower: icon = "bluetooth"
            elif "net" in p_lower or "wifi" in p_lower or "wlan" in p_lower: icon = "network-wireless"
            
            ui_list.append([
                s_syspath,
                s_vidpid,
                s_product,
                s_driver_display, # Use display version
                icon
            ])
            
        # 3. Add Loaded Modules that DON'T have hardware present (Idle modules)
        # CRITICAL: Only show SAFE modules that users can actually unload
        # DO NOT show kernel subsystems (filesystems, netfilter, crypto, etc.)
        
        def is_safe_module(mod):
            """
            Check if module is safe to show for unloading.
            STRICT FILTERING: Only real hardware drivers, never kernel subsystems.
            """
            
            # ========================================
            # CATEGORY 1: KERNEL CORE (NEVER TOUCH)
            # ========================================
            
            # CPU / ACPI / BIOS / Firmware
            kernel_core = {
                "cpuid", "msr", 
                "acpi_pad", "acpi_cpufreq", "acpi_thermal",
                "dmi_sysfs", "dmi_notifier",
                "efi_pstore", "efivars", "efivarfs",
                "pstore", "pstore_blk", "pstore_ram",
            }
            
            # Memory / Block / Compression
            memory_block = {
                "zram", "zsmalloc",
                "loop", "nbd",
            }
            
            # RAID / DM / MD
            raid_dm = {
                "raid0", "raid1", "raid10", "raid456", "raid6_pq",
                "dm_mod", "dm_crypt", "dm_mirror", "dm_snapshot",
                "md_mod", "linear", "multipath",
            }
            
            # Filesystems (NEVER unload - can cause data loss)
            filesystems = {
                "ext4", "ext3", "ext2", "jbd2", "mbcache",
                "btrfs", "xfs", "jfs", "reiserfs", "minix",
                "vfat", "fat", "msdos", "ntfs", "ntfs3",
                "fuse", "fuseblk", "overlayfs",
                "squashfs", "iso9660", "udf",
                "nfs", "nfsd", "lockd", "exportfs",
                "cifs", "smb", "smbfs",
            }
            
            # Sound Core (not individual drivers)
            sound_core = {
                "soundcore", 
                "snd", "snd_seq", "snd_seq_device", "snd_seq_midi", 
                "snd_seq_midi_event", "snd_timer", "snd_pcm",
                "snd_rawmidi", "snd_hwdep",
                "snd_hda_core", "snd_hda_codec", "snd_hda_codec_generic",
                "snd_hda_intel",  # This is borderline, but keep excluded for safety
            }
            
            # HID Base / Input Core (not individual device drivers)
            hid_input_core = {
                "hid", "hid_generic", "uhid", "hidp",
                "usbhid", "usbkbd", "usbmouse",
                "joydev", "evdev", "mousedev",
                "input_leds", "led_class",
            }
            
            # Virtualization
            virtualization = {
                "kvm", "kvm_intel", "kvm_amd",
                "vboxdrv", "vboxnetflt", "vboxnetadp", "vboxpci",
                "vmw_balloon", "vmw_vmci", "vmw_vsock_vmci_transport",
                "virtio", "virtio_pci", "virtio_balloon", "virtio_blk", "virtio_net",
                "vhost", "vhost_net", "vhost_vsock",
            }
            
            # Network Core / Bridging
            network_core = {
                "bridge", "stp", "llc", "bonding", "8021q",
                "veth", "tun", "tap",
            }
            
            # Parport / Legacy
            legacy_subsystems = {
                "parport", "parport_pc", "ppdev", "lp",
            }
            
            # Check all core categories
            all_core_modules = (
                kernel_core | memory_block | raid_dm | filesystems |
                sound_core | hid_input_core | virtualization |
                network_core | legacy_subsystems
            )
            
            if mod in all_core_modules:
                return False
            
            # ========================================
            # CATEGORY 2: PATTERN-BASED EXCLUSIONS
            # ========================================
            
            dangerous_patterns = [
                # Netfilter / iptables / nftables
                "xt_", "nf_", "nft_", "ip_", "ip6_", "ipt_", "ip6t_",
                "nfnetlink", "netfilter", "conntrack",
                # Crypto
                "crypto_", "sha", "aes", "ghash", "crc32", "md5", "des",
                "ecb", "cbc", "gcm", "ccm", "ctr",
                # CPU / Thermal
                "k10temp", "coretemp", "ssse3", "aesni", "cpu_", 
                "cpufreq", "intel_", "amd_", "x86_pkg_temp",
                # ACPI additional
                "acpi", "battery", "ac", "button", "fan", "thermal",
                # I2C / SPI (bus infrastructure)
                "i2c_", "spi_", "smbus",
                # PCI infrastructure (already in basic_exclude but double-check)
                "pcieport", "pci_bridge", "shpchp",
                # SCSI infrastructure
                "scsi_mod", "sd_mod", "sr_mod", "sg", "st",
                # Block layer core
                "nvme_core",
                # Video core (not drivers)
                "videodev", "videobuf", "v4l2_common",
                # Sound additional patterns
                "snd_",
                # HID additional
                "hid_",
                # Virtualization additional
                "vbox", "vmw_",
            ]
            
            for pattern in dangerous_patterns:
                if mod.startswith(pattern):
                    return False
            
            # ========================================
            # CATEGORY 3: HARDWARE MODALIAS CHECK
            # ========================================
            # STRICT: Module MUST have real hardware alias
            
            try:
                result = subprocess.run(
                    ["modinfo", "-F", "alias", mod],
                    capture_output=True,
                    text=True,
                    timeout=1
                )
                
                if result.returncode != 0 or not result.stdout:
                    # No aliases = not a hardware driver
                    return False
                
                aliases = result.stdout.strip()
                
                # Check if ANY alias indicates real hardware
                hardware_prefixes = ["pci:", "usb:", "platform:", "hid:", "serio:", "of:"]
                has_hardware_alias = False
                
                for alias_line in aliases.split('\n'):
                    for prefix in hardware_prefixes:
                        if alias_line.strip().startswith(prefix):
                            has_hardware_alias = True
                            break
                    if has_hardware_alias:
                        break
                
                # STRICT: If no hardware alias, reject
                if not has_hardware_alias:
                    return False
                        
            except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
                # If modinfo fails, reject for safety
                return False
            
            # ========================================
            # PASSED ALL CHECKS
            # ========================================
            return True
        
        # Filter Loaded Modules (only safe ones)
        for mod in loaded_set:
            # Skip if already shown as in-use
            if mod in used_drivers:
                continue
            
            # CRITICAL: Only show safe modules
            if not is_safe_module(mod):
                continue
            
            # Skip if has holders (it's a dependency)
            has_holders = libmc.mc_module_has_holders(mod.encode('utf-8'))
            if has_holders:
                continue
            
            # Check if actually in use via bus binding
            in_use = libmc.mc_driver_is_in_use(mod.encode('utf-8'))
            
            # Determine status
            if in_use:
                status_str = "Loaded Module (In Use)"
                status_tag = " (In Use)"
                icon_name = "package-x-generic"
            else:
                status_str = "Loaded Module (Idle)"
                status_tag = " (Idle)"
                icon_name = "application-x-addon"
            
            # Show it in dashboard
            ui_list.append([
                f"module:{mod}",      # syspath (or module ID)
                "Module",              # vidpid (show as "Module" to distinguish)
                status_str,            # product (display name)
                mod + status_tag,      #driver (module name with status)
                icon_name              # icon
            ])

        GLib.idle_add(self.update_dev_list, ui_list)

    def on_dev_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter:
            self.btn_unload.set_sensitive(True)
            self.btn_web_search.set_sensitive(True)
            
            # Update Details
            syspath = model[treeiter][0]
            vidpid = model[treeiter][1]
            product = model[treeiter][2]
            driver = model[treeiter][3]
            
            self.lbl_detail_name.set_markup(f"<b>Device:</b> {product}")
            self.lbl_detail_id.set_markup(f"<b>ID:</b> {vidpid}")
            self.lbl_detail_path.set_text(f"Path: {syspath}")
            
            # Get Driver Description via modinfo
            desc = "No driver loaded."
            if driver and driver != "None":
                try:
                    # Run modinfo -F description <driver>
                    res = subprocess.run(["modinfo", "-F", "description", driver], capture_output=True, text=True)
                    if res.returncode == 0 and res.stdout.strip():
                        desc = res.stdout.strip()
                    else:
                        desc = f"Driver {driver} (No description available)"
                except Exception:
                    desc = f"Driver {driver}"
            
            self.lbl_detail_desc.set_markup(f"<i>{desc}</i>")
            
        else:
            self.btn_unload.set_sensitive(False)
            self.btn_web_search.set_sensitive(False)
            self.lbl_detail_name.set_text("Select a device to view details.")
            self.lbl_detail_id.set_text("")
            self.lbl_detail_path.set_text("")
            self.lbl_detail_desc.set_text("")

    def on_web_search_clicked(self, widget):
        model, treeiter = self.dev_tree.get_selection().get_selected()
        if not treeiter: return
        vidpid = model[treeiter][1]
        
        # Open Google or DeviceHunt
        url = f"https://www.google.com/search?q=linux+usb+driver+{vidpid}"
        self.open_url(url)

    def on_unload_clicked(self, widget):
        model, treeiter = self.dev_tree.get_selection().get_selected()
        if not treeiter: return
        
        driver = model[treeiter][3]
        if driver == "None":
            self.log("Device has no driver to unload.", "red")
            return
            
        # Clean driver name (remove tags like " (Idle)")
        real_driver = driver.split(' ')[0]
        
        # CHEQUEO DE SEGURIDAD (Double Check)
        
        # 1. DEPENDENCY CHECK (Holders)
        # If module has holders -> BLOCK ACTION (It's a dependency of another active module)
        has_holders = libmc.mc_module_has_holders(real_driver.encode('utf-8'))
        
        if has_holders:
            self.log(f"BLOCKED: Module {real_driver} is held by others.", "red")
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=f"Cannot Unload {real_driver}"
            )
            dialog.format_secondary_text(
                f"The module '{real_driver}' is currently being used by other kernel modules (Dependency).\n\n"
                "You must unload the dependent modules first."
            )
            dialog.run()
            dialog.destroy()
            return

        # 2. BUS/HARDWARE CHECK
        # Check if driver is IN USE by actual hardware bindings
        ref = libmc.mc_get_module_refcount(real_driver.encode('utf-8'))
        in_use = libmc.mc_driver_is_in_use(real_driver.encode('utf-8'))
        
        if ref > 0 or in_use:
            # ES UN DRIVER EN USO. PELIGRO EXTREMO.
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.WARNING, # Or ERROR to be scary
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text=f"BE CAREFUL: {real_driver} is IN USE!"
            )
            dialog.format_secondary_text(
                f"The driver '{real_driver}' is currently controlling active hardware.\n\n"
                "⚠️ IF YOU UNLOAD THIS:\n"
                "1. The device will STOP working immediately.\n"
                "2. Your session may crash if it's a keyboard/mouse.\n"
                "3. You will likely need to REBOOT to fix it.\n\n"
                "Are you absolutely sure you want to sabotage this driver?"
            )
            # Make default response CANCEL
            dialog.set_default_response(Gtk.ResponseType.CANCEL)
            
        else:
            # Driver is NOT in use (Idle) or unknown
            # Simple Warning for Idle Drivers
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text="Unload Idle Driver?"
            )
            dialog.format_secondary_text(
                f"The driver '{real_driver}' appears to be idle (no bound devices).\n\n"
                "Are you sure you want to unload it?"
            )

        response = dialog.run()
        dialog.destroy()
        
        if response != Gtk.ResponseType.OK:
            self.log("Unload cancelled by user.")
            return

        self.log(f"Unloading driver {real_driver}...", "bold")
        
        # Use PolicyKit for privileged operation
        try:
            result = subprocess.run(
                ["pkexec", HELPER_PATH, "unload", real_driver],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                self.log(f"FAILED. Could not unload {real_driver}: {error_msg}", "red")
                dialog = Gtk.MessageDialog(
                    transient_for=self,
                    flags=0,
                    message_type=Gtk.MessageType.ERROR,
                    buttons=Gtk.ButtonsType.OK,
                    text="Unload Failed"
                )
                dialog.format_secondary_text(f"The system refused to unload '{real_driver}'.\n{error_msg}")
                dialog.run()
                dialog.destroy()
                return
                
        except subprocess.TimeoutExpired:
            self.log(f"Timeout waiting for authentication.", "red")
            return
        except FileNotFoundError:
            self.log(f"PolicyKit not available. Install policykit-1.", "red")
            return
        except Exception as e:
            self.log(f"Error: {e}", "red")
            return
        
        # Add to history if not present
        exists = False
        for row in self.restore_store:
            if row[0] == real_driver:
                exists = True
                break
        if not exists:
            self.restore_store.append([real_driver])
        
        time.sleep(0.5)
        self.refresh_devices()

    def on_restore_clicked(self, widget):
        model, treeiter = self.restore_tree.get_selection().get_selected()
        if not treeiter: return
        
        module = model[treeiter][0]
        self.log(f"Restoring module {module}...", "bold")
        
        # Try load
        ret = libmc.mc_try_load_driver(module.encode('utf-8'))
        if ret:
            self.log(f"  -> Module {module} reloaded successfully.", "green")
            # Remove from history
            self.restore_store.remove(treeiter)
            time.sleep(1.0) # wait for bind
            self.refresh_devices()
        else:
             self.log(f"  -> Failed to reload {module}.", "red")

    def on_clear_restore_clicked(self, widget):
        if len(self.restore_store) == 0: return

        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Clear Restore History?"
        )
        dialog.format_secondary_text(
            "This will remove all modules from the Restore list.\n\n"
            "You will not be able to quickly reload them from this tab.\n"
            "Make sure you don't need these modules explicitly."
        )
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.OK:
            self.restore_store.clear()
            self.log("Restore history cleared.", "bold")

    def on_auto_find_clicked(self, widget):
        model, treeiter = self.dev_tree.get_selection().get_selected()
        if not treeiter: return
        
        name = model[treeiter][2]
        
        # SAFETY DIALOG
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Start Brute-Force Driver Search?"
        )
        dialog.format_secondary_text(
            f"Montecarlo will attempt to load kernel modules one by one for '{name}'.\n\nRisk: Low to Moderate. This might cause temporary system freezes.\n\nContinue?"
        )
        response = dialog.run()
        dialog.destroy()
        
        if response != Gtk.ResponseType.OK:
            self.log("Auto-Find cancelled by user.")
            return
        
        syspath = model[treeiter][0]
        
        self.log(f"Starting Montecarlo Auto-Find for: {name}", "bold")
        self.notebook.set_current_page(1) # Switch to logs
        
        t = threading.Thread(target=self.run_montecarlo_logic, args=(syspath,))
        t.daemon = True
        t.start()

    def run_montecarlo_logic(self, syspath):
        self.spinner.start()
        GLib.idle_add(self.set_sensitive, False)
        
        enc_syspath = syspath.encode('utf-8')
        
        # 1. List Candidates
        drivers_buf = create_string_buffer(256 * 128)
        count = libmc.mc_list_candidate_drivers(drivers_buf, 256)
        
        self.log(f"Found {count} candidate drivers in kernel.")
        
        found_driver = None
        
        for i in range(count):
            offset = i * 128
            raw_name = drivers_buf[offset:offset+128]
            name_bytes = raw_name.split(b'\0', 1)[0]
            name = name_bytes.decode('utf-8', 'ignore')
            
            self.log(f"Testing candidate: {name}...")
            
            # Load
            if libmc.mc_try_load_driver(name_bytes) == 0:
                self.log(f"  -> Load failed.", "red")
                continue
                
            time.sleep(1.0) 
            
            # Check Binding
            if libmc.mc_dev_has_driver(enc_syspath):
                self.log(f"  -> MATCH! Device verified bound to {name}.", "green")
                found_driver = name
                break
                
            # Check Dmesg
            if libmc.mc_dmesg_has_activity(name_bytes):
                self.log(f"  -> PROBABLE MATCH (Dmesg activity) for {name}.", "green")
                found_driver = name
                break
            
            # UNLOAD SAFETY CHECK
            # 1. Check Module Use Count (Kernel generic)
            ref = libmc.mc_get_module_refcount(name_bytes)
            
            # 2. Check Bus Bindings (Specific Device Links) - "Regla de Oro"
            in_use = libmc.mc_driver_is_in_use(name_bytes)
            
            if ref > 0 or in_use:
                reason = []
                if ref > 0: reason.append(f"Refcnt={ref}")
                if in_use: reason.append("BusDevices Bound")
                # GOLDEN RULE: Never unload a driver that is in use.
                self.log(f"  -> SAFETY LOCK: Keeping {name} ({', '.join(reason)}).", "bold")
                self.log(f"     [!] Montecarlo will NOT unload drivers in use.", "green")
            else:
                # Safe to attempt unload
                libmc.mc_unload_driver(name_bytes)
            
        if found_driver:
            self.log(f"SUCCESS. Driver {found_driver} is active.", "bold")
        else:
            self.log("FAILED. No suitable driver found in standard modules.", "red")

        self.spinner.stop()
        GLib.idle_add(self.set_sensitive, True)
        GLib.idle_add(self.refresh_devices)

    def socket_listener(self):
        # Allow connecting/reconnecting
        while True:
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(SOCK_PATH)
                self.log("Connected to Daemon.")
                
                while True:
                    data = sock.recv(4096)
                    if not data: break
                    try:
                        msg = json.loads(data.decode("utf-8"))
                        if msg.get("event") == "add" and "syspath" in msg:
                            sp = msg["syspath"]
                            self.log(f"[DAEMON EVENT] Device Added: {sp}", "bold")
                            
                            # Show desktop notification
                            GLib.idle_add(self.show_device_notification, sp)
                            
                            # Refresh device list
                            GLib.idle_add(self.refresh_devices)
                    except Exception as e:
                        print(e)
                sock.close()
            except:
                time.sleep(2)


    def quit_app(self, *args):
        try:
            if os.path.exists(self.pid_file):
                os.unlink(self.pid_file)
        except:
            pass
        Gtk.main_quit()

if __name__ == "__main__":
    win = MontecarloUI()
    win.connect("destroy", win.quit_app)
    win.show_all()
    Gtk.main()
