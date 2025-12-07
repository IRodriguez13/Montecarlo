#!/usr/bin/env python3
import sys
import os
import time
import socket
import json
import threading
import ctypes
from ctypes import c_int, c_char_p, c_char, POINTER, create_string_buffer

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

# --- CTYPES CONFIGURATION ---
try:
    # Assuming libmontecarlo.so is in the same directory or LD_LIBRARY_PATH
    # For dev/demo, we assume current dir
    LIB_PATH = os.path.abspath("./libmontecarlo.so")
    libmc = ctypes.CDLL(LIB_PATH)
except OSError as e:
    print(f"Error loading library: {e}")
    sys.exit(1)

# Define Signatures
# int mc_list_candidate_drivers(char out[][128], int max);
# We need to handle the 2D array. simpler to map it as a flat check or use helper
# But for now, let's map it carefully.
# char out[][128] is basically char* passed, but memory layout is contiguous.

libmc.mc_try_load_driver.argtypes = [c_char_p]
libmc.mc_try_load_driver.restype = c_int

libmc.mc_unload_driver.argtypes = [c_char_p]
libmc.mc_unload_driver.restype = None

libmc.mc_dev_has_driver.argtypes = [c_char_p]
libmc.mc_dev_has_driver.restype = c_int

libmc.mc_dmesg_has_activity.argtypes = [c_char_p]
libmc.mc_dmesg_has_activity.restype = c_int

libmc.mc_get_ids.argtypes = [c_char_p, c_char_p, c_char_p]
libmc.mc_get_ids.restype = None

# list_candidate_drivers is tricky in ctypes with 2D arrays so let's use a helper wrapper
# or just allocate a big buffer and handle offsets.
# char out[256][128]
# 256 * 128 = 32768 bytes
class DriversArray(ctypes.Structure):
    _fields_ = [("drivers", c_char * (256 * 128))]

libmc.mc_list_candidate_drivers.argtypes = [POINTER(c_char), c_int]
libmc.mc_list_candidate_drivers.restype = c_int

SOCKET_PATH = "/tmp/montecarlo.sock"

class MontecarloUI(Gtk.Window):
    def __init__(self):
        super().__init__(title="Montecarlo Driver Manager")
        self.set_default_size(600, 450)
        self.set_border_width(10)
        
        self.syspath = None  # Will be set via socket or manual arg to debug
        
        # Main Layout
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)
        
        # Header
        self.header = Gtk.Label()
        self.header.set_markup("<span size='x-large' weight='bold'>Montecarlo Driver Manager</span>")
        vbox.pack_start(self.header, False, False, 10)
        
        self.info_label = Gtk.Label(label="Waiting for daemon...")
        vbox.pack_start(self.info_label, False, False, 5)
        
        # Notebook (Tabs)
        self.notebook = Gtk.Notebook()
        vbox.pack_start(self.notebook, True, True, 0)
        
        # --- TAB 1: AUTO MODE ---
        self.page_auto = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.page_auto.set_border_width(10)
        
        self.status_label = Gtk.Label(label="Ready.")
        self.page_auto.pack_start(self.status_label, False, False, 10)
        
        # Log view
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_hexpand(True)
        scrolled_window.set_vexpand(True)
        self.textview = Gtk.TextView()
        self.textview.set_editable(False)
        self.textbuffer = self.textview.get_buffer()
        scrolled_window.add(self.textview)
        self.page_auto.pack_start(scrolled_window, True, True, 0)
        
        self.btn_run = Gtk.Button(label="Run Montecarlo")
        self.btn_run.connect("clicked", self.on_run_clicked)
        self.btn_run.set_sensitive(False) # Wait for target
        self.page_auto.pack_start(self.btn_run, False, False, 5)
        
        self.notebook.append_page(self.page_auto, Gtk.Label(label="Auto Mode"))
        
        # --- TAB 2: ROOT MODE (Manual) ---
        self.page_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.page_root.set_border_width(10)
        
        lbl_root = Gtk.Label(label="Manual Driver Management (Root)")
        self.page_root.pack_start(lbl_root, False, False, 5)
        
        self.setup_root_ui()
        
        self.notebook.append_page(self.page_root, Gtk.Label(label="Root Mode"))
        
        # Start connection thread
        t = threading.Thread(target=self.connect_to_daemon)
        t.daemon = True
        t.start()

    def connect_to_daemon(self):
        try:
            GLib.idle_add(self.log, "Connecting to daemon socket...")
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(SOCKET_PATH)
            
            data = sock.recv(4096)
            if data:
                try:
                    msg = json.loads(data.decode("utf-8"))
                    if msg.get("event") == "add" and "syspath" in msg:
                        self.syspath = msg["syspath"]
                        GLib.idle_add(self.update_ui_with_syspath, self.syspath)
                    else:
                        GLib.idle_add(self.log, "No active device or unknown event.")
                except Exception as e:
                    GLib.idle_add(self.log, f"JSON Error: {e}")
            
            sock.close()
        except Exception as e:
             # Fallback for manual testing support
             args = sys.argv
             if len(args) > 1:
                 self.syspath = args[1]
                 GLib.idle_add(self.log, f"Using CLI arg syspath: {self.syspath}")
                 GLib.idle_add(self.update_ui_with_syspath, self.syspath)
             else:
                 GLib.idle_add(self.log, f"Socket Connect Error: {e}. Waiting...")

    def update_ui_with_syspath(self, syspath):
        self.info_label.set_text(f"Target Device: {syspath}")
        self.btn_run.set_sensitive(True)
        self.log(f"Target acquired: {syspath}")
        
        # Auto-start if desired, but user asked for "dispara la UI... y arranca a trabajar"
        # "dispara la UI y arranca a trabajar la lógica" implies auto start or at least ready to start.
        # User said "si no tiene, dispara la UI y arranca a trabajar la lógica" -> maybe auto start.
        # I'll leave it as a button press for safety OR auto-click.
        # Let's auto-click for the "User Experience" requested.
        self.on_run_clicked(self.btn_run)

    # --- AUTO MODE LOGIC (Monte Carlo in Python via ctypes) ---
    def on_run_clicked(self, widget):
        self.btn_run.set_sensitive(False)
        self.status_label.set_text("Running Montecarlo...")
        
        t = threading.Thread(target=self.run_montecarlo_logic)
        t.daemon = True
        t.start()

    def run_montecarlo_logic(self):
        if not self.syspath:
            return

        # 1. Get info
        vendor = create_string_buffer(32)
        product = create_string_buffer(32)
        enc_syspath = self.syspath.encode('utf-8')
        
        libmc.mc_get_ids(enc_syspath, vendor, product)
        v_str = vendor.value.decode('utf-8', 'ignore')
        p_str = product.value.decode('utf-8', 'ignore')
        
        GLib.idle_add(self.log, f"Device: Vendor={v_str}, Product={p_str}")

        # 2. List candidates
        # Create a large buffer. 256 drivers max, 128 bytes each.
        drivers_buf = create_string_buffer(256 * 128)
        count = libmc.mc_list_candidate_drivers(drivers_buf, 256)
        
        GLib.idle_add(self.log, f"Found {count} candidate drivers.")
        
        if count == 0:
            GLib.idle_add(self.log, "No candidates found.")
            GLib.idle_add(self.status_label.set_text, "Failed: No candidates.")
            GLib.idle_add(self.btn_run.set_sensitive, True)
            return

        # 3. Iterate
        found = False
        
        for i in range(count):
            # Extract string at offset i * 128
            offset = i * 128
            raw_name = drivers_buf[offset:offset+128]
            # terminate at first null
            name_bytes = raw_name.split(b'\0', 1)[0]
            name = name_bytes.decode('utf-8', 'ignore')
            
            GLib.idle_add(self.log, f"Testing driver: {name}")
            
            # Load
            if libmc.mc_try_load_driver(name_bytes) == 0:
                GLib.idle_add(self.log, "  -> Load failed (modprobe).")
                continue
                
            time.sleep(1.0) # Wait for kernel
            
            # Check 1: Sysfs binding
            if libmc.mc_dev_has_driver(enc_syspath):
                GLib.idle_add(self.log, f"  -> SUCCESS! Device bound to {name}.")
                found = True
                break
                
            # Check 2: Dmesg
            if libmc.mc_dmesg_has_activity(name_bytes):
                GLib.idle_add(self.log, f"  -> SUCCESS! Activity detected for {name}.")
                found = True
                break
                
            # Unload if failed
            libmc.mc_unload_driver(name_bytes)
            
        if found:
            GLib.idle_add(self.status_label.set_text, "Success: Driver found.")
        else:
             GLib.idle_add(self.log, "All candidates failed.")
             GLib.idle_add(self.status_label.set_text, "Failed: None worked.")

        GLib.idle_add(self.btn_run.set_sensitive, True)
        # Refresh root list
        GLib.idle_add(self.refresh_drivers)

    def log(self, text):
        end_iter = self.textbuffer.get_end_iter()
        self.textbuffer.insert(end_iter, text + "\n")
        adj = self.textview.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    # --- ROOT MODE HANDLERS ---
    def refresh_drivers(self):
        self.store_available.clear()
        self.store_loaded.clear()
        
        # Re-use C function logic or similar for listing, but loaded modules needs /proc/modules
        # We can implement a helper or just do it in python as before since it is easy.
        
        # 1. Candidates from C
        drivers_buf = create_string_buffer(256 * 128)
        count = libmc.mc_list_candidate_drivers(drivers_buf, 256)
        candidates = []
        for i in range(count):
            offset = i * 128
            raw = drivers_buf[offset:offset+128].split(b'\0', 1)[0]
            candidates.append(raw.decode('utf-8'))
            
        # 2. Loaded
        loaded = []
        try:
            with open("/proc/modules", "r") as f:
                for line in f:
                    loaded.append(line.split(" ")[0])
        except: pass
        
        for drv in candidates:
            # Normalize
            norm = drv.replace("-", "_")
            is_loaded = any(l.replace("-", "_") == norm for l in loaded)
            
            if is_loaded:
                self.store_loaded.append([drv])
            else:
                self.store_available.append([drv])

    def setup_root_ui(self):
         self.store_available = Gtk.ListStore(str)
         self.store_loaded = Gtk.ListStore(str)
         
         grid = Gtk.Grid()
         grid.set_column_spacing(10)
         grid.set_row_spacing(10)
         grid.set_hexpand(True)
         grid.set_vexpand(True)
         
         # Left Pane
         frame_avail = Gtk.Frame(label="Available")
         self.tree_avail = Gtk.TreeView(model=self.store_available)
         self.tree_avail.append_column(Gtk.TreeViewColumn("Driver", Gtk.CellRendererText(), text=0))
         scroll_avail = Gtk.ScrolledWindow()
         scroll_avail.add(self.tree_avail)
         
         frame_avail.add(scroll_avail)
         grid.attach(frame_avail, 0, 0, 1, 1)
         
         # Buttons
         bbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
         bbox.set_valign(Gtk.Align.CENTER)
         
         btn_load = Gtk.Button(label="Load >>")
         btn_load.connect("clicked", self.on_load_clicked)
         bbox.pack_start(btn_load, False, False, 0)
         
         btn_unload = Gtk.Button(label="<< Unload")
         btn_unload.connect("clicked", self.on_unload_clicked)
         bbox.pack_start(btn_unload, False, False, 0)
         
         grid.attach(bbox, 1, 0, 1, 1)
         
         # Right Pane
         frame_loaded = Gtk.Frame(label="Active")
         self.tree_loaded = Gtk.TreeView(model=self.store_loaded)
         self.tree_loaded.append_column(Gtk.TreeViewColumn("Driver", Gtk.CellRendererText(), text=0))
         scroll_loaded = Gtk.ScrolledWindow()
         scroll_loaded.add(self.tree_loaded)
         
         frame_loaded.add(scroll_loaded)
         grid.attach(frame_loaded, 2, 0, 1, 1)
         
         self.page_root.pack_start(grid, True, True, 0)
         
         btn_refresh = Gtk.Button(label="Refresh All")
         btn_refresh.connect("clicked", lambda w: self.refresh_drivers())
         self.page_root.pack_start(btn_refresh, False, False, 5)
         
         self.sel_avail = self.tree_avail.get_selection()
         self.sel_loaded = self.tree_loaded.get_selection()

    def on_load_clicked(self, widget):
        model, treeiter = self.sel_avail.get_selected()
        if not treeiter: return
        driver = model[treeiter][0]
        
        # Use C function
        ret = libmc.mc_try_load_driver(driver.encode('utf-8'))
        if ret:
            self.log(f"Manual load of {driver} success.")
        else:
            self.log(f"Manual load of {driver} failed.")
        self.refresh_drivers()

    def on_unload_clicked(self, widget):
        model, treeiter = self.sel_loaded.get_selected()
        if not treeiter: return
        driver = model[treeiter][0]
        
        libmc.mc_unload_driver(driver.encode('utf-8'))
        self.log(f"Manual unload of {driver} initiated.")
        self.refresh_drivers()

if __name__ == "__main__":
    win = MontecarloUI()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
