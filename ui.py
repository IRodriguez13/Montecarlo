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
        
        # TreeView for drivers
        self.store = Gtk.ListStore(str, str) # Driver Name, Status (Loaded/Unloaded - simplification)
        self.tree = Gtk.TreeView(model=self.store)
        
        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Driver Name", renderer, text=0)
        self.tree.append_column(column)
        
        # Selection
        self.selection = self.tree.get_selection()
        
        scrolled_root = Gtk.ScrolledWindow()
        scrolled_root.set_hexpand(True)
        scrolled_root.set_vexpand(True)
        scrolled_root.add(self.tree)
        self.page_root.pack_start(scrolled_root, True, True, 0)
        
        bbox = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
        bbox.set_layout(Gtk.ButtonBoxStyle.CENTER)
        
        btn_refresh = Gtk.Button(label="Refresh List")
        btn_refresh.connect("clicked", self.on_refresh_clicked)
        bbox.add(btn_refresh)
        
        btn_load = Gtk.Button(label="Load Selected")
        btn_load.connect("clicked", self.on_load_clicked)
        bbox.add(btn_load)
        
        btn_unload = Gtk.Button(label="Unload Selected")
        btn_unload.connect("clicked", self.on_unload_clicked)
        bbox.add(btn_unload)
        
        self.page_root.pack_start(bbox, False, False, 5)
        
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
        self.store.clear()
        try:
            output = subprocess.check_output([CLI_PATH, "list"], universal_newlines=True)
            # Simple parsing of the JSON-like list output by our CLI
            # Expected: [ "driver1", "driver2" ]
            # We can use simple string manipulation or json lib if strict valid json
            import json
            try:
                drivers = json.loads(output)
                for d in drivers:
                    self.store.append([d, "Unknown"])
            except json.JSONDecodeError:
                # Fallback if text format changes
                 pass
        except Exception as e:
            print(f"Error listing drivers: {e}")

    def on_refresh_clicked(self, widget):
        self.refresh_drivers()

    def on_load_clicked(self, widget):
        model, treeiter = self.selection.get_selected()
        if treeiter:
            driver = model[treeiter][0]
            self.run_root_cmd("load", driver)

    def on_unload_clicked(self, widget):
        model, treeiter = self.selection.get_selected()
        if treeiter:
            driver = model[treeiter][0]
            self.run_root_cmd("unload", driver)
            
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
