#!/usr/bin/env python3
import sys
import os
import subprocess
import threading
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango

# Path to the CLI tool
CLI_PATH = os.path.abspath("./montecarlo_cli")

class MontecarloUI(Gtk.Window):
    def __init__(self, syspath=None):
        super().__init__(title="Montecarlo Driver Manager")
        self.set_default_size(600, 450)
        self.set_border_width(10)
        
        self.syspath = syspath
        
        # Main Layout
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)
        
        # Header
        header = Gtk.Label()
        header.set_markup("<span size='x-large' weight='bold'>Montecarlo Driver Manager</span>")
        vbox.pack_start(header, False, False, 10)
        
        if self.syspath:
            info_label = Gtk.Label(label=f"Device detected at: {self.syspath}")
            vbox.pack_start(info_label, False, False, 5)
        
        # Notebook (Tabs)
        self.notebook = Gtk.Notebook()
        vbox.pack_start(self.notebook, True, True, 0)
        
        # --- TAB 1: AUTO MODE ---
        self.page_auto = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.page_auto.set_border_width(10)
        
        self.status_label = Gtk.Label(label="Press 'Start' to automatically find and load a driver.")
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
        
        self.btn_run = Gtk.Button(label="Start Automatic Process")
        self.btn_run.connect("clicked", self.on_run_clicked)
        self.page_auto.pack_start(self.btn_run, False, False, 5)
        
        self.notebook.append_page(self.page_auto, Gtk.Label(label="Auto Mode"))
        
        # --- TAB 2: ROOT MODE (Manual) ---
        self.page_root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.page_root.set_border_width(10)
        
        lbl_root = Gtk.Label(label="Manual Driver Management (Root)")
        self.page_root.pack_start(lbl_root, False, False, 5)
        
        self.setup_root_ui()
        
        self.notebook.append_page(self.page_root, Gtk.Label(label="Root Mode"))
        
        # Initialize Root List
        self.refresh_drivers()

    # --- AUTO MODE HANDLERS ---
    def on_run_clicked(self, widget):
        if not self.syspath:
            self.log("Error: No syspath provided (started manually without arguments?)")
            return
            
        self.btn_run.set_sensitive(False)
        self.status_label.set_text("Running Montecarlo algorithm...")
        self.log("--- Starting Montecarlo ---")
        
        thread = threading.Thread(target=self.run_montecarlo_thread)
        thread.daemon = True
        thread.start()

    def run_montecarlo_thread(self):
        try:
            process = subprocess.Popen(
                [CLI_PATH, "run", self.syspath],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            for line in process.stdout:
                GLib.idle_add(self.log, line.strip())
                
            process.wait()
            
            msg = "Montecarlo finished."
            if process.returncode == 0:
                 msg += " Success."
            else:
                 msg += " Failed/Aborted."
                 
            GLib.idle_add(self.status_label.set_text, msg)
            GLib.idle_add(self.log, f"--- {msg} ---")
            
        except Exception as e:
            GLib.idle_add(self.log, f"Error: {e}")
            
        GLib.idle_add(self.btn_run.set_sensitive, True)

    def log(self, text):
        end_iter = self.textbuffer.get_end_iter()
        self.textbuffer.insert(end_iter, text + "\n")
        # Scroll to bottom
        adj = self.textview.get_vadjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    # --- ROOT MODE HANDLERS ---
    def refresh_drivers(self):
        self.store_available.clear()
        self.store_loaded.clear()
        
        # 1. Get all potential drivers from disk (simplification: scan usb/hid dirs)
        candidates = self.scan_disk_drivers()
        
        # 2. Get currently loaded drivers
        loaded = self.get_loaded_modules()
        
        for drv in candidates:
            # Check if loaded
            # Note: module names in lsmod often use underscores instead of dashes
            normalized_drv = drv.replace("-", "_")
            is_loaded = any(l.replace("-", "_") == normalized_drv for l in loaded)
            
            if is_loaded:
                 self.store_loaded.append([drv])
            else:
                 self.store_available.append([drv])

    def scan_disk_drivers(self):
        drivers = set()
        # Scan standard kernel paths for USB/HID drivers
        # This is a heuristic.
        import platform
        kernel_ver = platform.release()
        base_path = f"/lib/modules/{kernel_ver}/kernel/drivers"
        paths = [
            os.path.join(base_path, "usb"),
            os.path.join(base_path, "hid")
        ]
        
        for p in paths:
            if not os.path.exists(p): continue
            for root, dirs, files in os.walk(p):
                for f in files:
                    if f.endswith(".ko") or f.endswith(".ko.xz"):
                        # Extract module name
                        name = f.split(".")[0]
                        drivers.add(name)
        # Also include generic candidates from CLI list just in case
        try:
            output = subprocess.check_output([CLI_PATH, "list"], universal_newlines=True)
            import json
            candidates = json.loads(output)
            for c in candidates:
                drivers.add(c)
        except:
            pass
            
        return sorted(list(drivers))

    def get_loaded_modules(self):
        loaded = []
        try:
            with open("/proc/modules", "r") as f:
                for line in f:
                    # module_name size refcount dependencies state offset
                    loaded.append(line.split(" ")[0])
        except:
             pass
        return loaded

    def setup_root_ui(self):
         # Creating Double Pane UI
         self.store_available = Gtk.ListStore(str)
         self.store_loaded = Gtk.ListStore(str)
         
         grid = Gtk.Grid()
         grid.set_column_spacing(10)
         grid.set_row_spacing(10)
         grid.set_hexpand(True)
         grid.set_vexpand(True)
         
         # Left Pane: Available
         frame_avail = Gtk.Frame(label="Available (Unloaded)")
         frame_avail.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
         
         self.tree_avail = Gtk.TreeView(model=self.store_available)
         col_avail = Gtk.TreeViewColumn("Driver", Gtk.CellRendererText(), text=0)
         self.tree_avail.append_column(col_avail)
         
         scroll_avail = Gtk.ScrolledWindow()
         scroll_avail.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
         scroll_avail.add(self.tree_avail)
         scroll_avail.set_hexpand(True)
         scroll_avail.set_vexpand(True)
         
         frame_avail.add(scroll_avail)
         grid.attach(frame_avail, 0, 0, 1, 1)
         
         # Center: Buttons
         bbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
         bbox.set_valign(Gtk.Align.CENTER)
         
         btn_load = Gtk.Button(label="Load >>")
         btn_load.connect("clicked", self.on_load_clicked)
         bbox.pack_start(btn_load, False, False, 0)
         
         btn_unload = Gtk.Button(label="<< Unload")
         btn_unload.connect("clicked", self.on_unload_clicked)
         bbox.pack_start(btn_unload, False, False, 0)
         
         grid.attach(bbox, 1, 0, 1, 1)
         
         # Right Pane: Loaded
         frame_loaded = Gtk.Frame(label="Active (Loaded)")
         frame_loaded.set_shadow_type(Gtk.ShadowType.ETCHED_IN)
         
         self.tree_loaded = Gtk.TreeView(model=self.store_loaded)
         col_loaded = Gtk.TreeViewColumn("Driver", Gtk.CellRendererText(), text=0)
         self.tree_loaded.append_column(col_loaded)
         
         scroll_loaded = Gtk.ScrolledWindow()
         scroll_loaded.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
         scroll_loaded.add(self.tree_loaded)
         scroll_loaded.set_hexpand(True)
         scroll_loaded.set_vexpand(True)
         
         frame_loaded.add(scroll_loaded)
         grid.attach(frame_loaded, 2, 0, 1, 1)
         
         self.page_root.pack_start(grid, True, True, 0)
         
         # Refresh Button Area
         btn_refresh = Gtk.Button(label="Refresh All")
         btn_refresh.connect("clicked", lambda w: self.refresh_drivers())
         self.page_root.pack_start(btn_refresh, False, False, 5)

         # Selection references
         self.sel_avail = self.tree_avail.get_selection()
         self.sel_loaded = self.tree_loaded.get_selection()

    def on_load_clicked(self, widget):
        model, treeiter = self.sel_avail.get_selected()
        if not treeiter: return
        driver = model[treeiter][0]
        
        self.run_root_cmd("load", driver)
        self.refresh_drivers()

    def on_unload_clicked(self, widget):
        model, treeiter = self.sel_loaded.get_selected()
        if not treeiter: return
        driver = model[treeiter][0]
        
        self.run_root_cmd("unload", driver)
        self.refresh_drivers()



    def run_root_cmd(self, action, driver):
        try:
            subprocess.run([CLI_PATH, action, driver], check=True)
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=f"Action '{action}' on '{driver}' completed."
            )
            dialog.run()
            dialog.destroy()
        except subprocess.CalledProcessError:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=f"Failed to '{action}' driver '{driver}'."
            )
            dialog.run()
            dialog.destroy()


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("Warning: Not running as root. Driver operations may fail.")
    
    syspath = None
    if len(sys.argv) > 1:
        syspath = sys.argv[1]
        
    win = MontecarloUI(syspath)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
