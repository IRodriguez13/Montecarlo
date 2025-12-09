#!/usr/bin/env python3
import sys
import os
import time
import socket
import json
import threading
import ctypes
from ctypes import CDLL, c_int, c_char_p, c_char, POINTER, create_string_buffer, Structure

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Pango
import webbrowser

# --- CONFIG & LIBS ---
SOCK_PATH = "/tmp/montecarlo.sock"

if os.environ.get("MONTECARLO_DEV"):
    LIB_PATH = os.path.abspath("./libmontecarlo.so")
else:
    LIB_PATH = "/usr/lib/libmontecarlo.so"

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
        ("driver", c_char * 64)
    ]

# Signatures
libmc.mc_try_load_driver.argtypes = [c_char_p]
libmc.mc_try_load_driver.restype = c_int

libmc.mc_unload_driver.argtypes = [c_char_p]
libmc.mc_unload_driver.restype = None

libmc.mc_dev_has_driver.argtypes = [c_char_p]
libmc.mc_dev_has_driver.restype = c_int

libmc.mc_dmesg_has_activity.argtypes = [c_char_p]
libmc.mc_dmesg_has_activity.restype = c_int

libmc.mc_list_candidate_drivers.argtypes = [POINTER(c_char), c_int]
libmc.mc_list_candidate_drivers.restype = c_int

libmc.mc_list_all_usb_devices.argtypes = [POINTER(MCDeviceInfo), c_int]
libmc.mc_list_all_usb_devices.restype = c_int

# --- UI CLASS ---

class MontecarloUI(Gtk.Window):
    def __init__(self):
        super().__init__(title="Montecarlo Dashboard")
        self.set_default_size(900, 600)
        self.set_border_width(10)
        
        # State
        self.target_syspath = None
        self.running_auto = False
        
        # Layout
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)
        
        # Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lbl_title = Gtk.Label()
        lbl_title.set_markup("<span size='x-large' weight='bold'>Montecarlo</span>")
        header_box.pack_start(lbl_title, False, False, 0)
        
        self.spinner = Gtk.Spinner()
        header_box.pack_start(self.spinner, False, False, 0)
        vbox.pack_start(header_box, False, False, 5)
        
        # Main Notebook
        self.notebook = Gtk.Notebook()
        vbox.pack_start(self.notebook, True, True, 0)
        
        # --- TAB 1: DASHBOARD ---
        self.build_dashboard_tab()
        
        # --- TAB 2: TELEMETRY (Logs) ---
        self.build_telemetry_tab()
        
        # CLI Argument handling (if launched by daemon with arg)
        if len(sys.argv) > 1:
            self.target_syspath = sys.argv[1]
            self.log(f"[INIT] Launched with target: {self.target_syspath}")
            # Switch to telemetry and start auto-process? Or show in Dashboard?
            # User wants visibility. Let's select it in dashboard if possible.
            # But scanning takes time. We will scan then try to highlight.
            pass
        
        # Start Socket Listener
        t = threading.Thread(target=self.socket_listener)
        t.daemon = True
        t.start()
        
        # Initial Scan
        self.refresh_devices()

        # PID File for Daemon Singleton Check
        self.pid_file = "/tmp/montecarlo_ui.pid"
        try:
            with open(self.pid_file, "w") as f:
                f.write(str(os.getpid()))
        except Exception as e:
            print(f"Failed to write PID file: {e}")

    def build_dashboard_tab(self):
        self.dash_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.dash_box.set_border_width(10)
        
        # Toolbar
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        
        btn_refresh = Gtk.Button(label="Rescan Devices")
        btn_refresh.set_image(Gtk.Image.new_from_icon_name("view-refresh", Gtk.IconSize.BUTTON))
        btn_refresh.connect("clicked", self.on_refresh_clicked)
        toolbar.pack_start(btn_refresh, False, False, 0)
        
        toolbar.pack_start(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL), False, False, 10)
        
        self.btn_auto = Gtk.Button(label="Auto-Find Driver")
        self.btn_auto.set_image(Gtk.Image.new_from_icon_name("system-run", Gtk.IconSize.BUTTON))
        self.btn_auto.get_style_context().add_class("suggested-action")
        self.btn_auto.connect("clicked", self.on_auto_find_clicked)
        toolbar.pack_start(self.btn_auto, False, False, 0)
        
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
        self.lbl_detail_id = Gtk.Label(label="", xalign=0)
        self.lbl_detail_path = Gtk.Label(label="", xalign=0)
        self.btn_web_search = Gtk.Button(label="Search on Web")
        self.btn_web_search.set_valign(Gtk.Align.START)
        self.btn_web_search.set_halign(Gtk.Align.START)
        self.btn_web_search.set_sensitive(False)
        self.btn_web_search.connect("clicked", self.on_web_search_clicked)
        
        self.details_box.pack_start(self.lbl_detail_name, False, False, 0)
        self.details_box.pack_start(self.lbl_detail_id, False, False, 0)
        self.details_box.pack_start(self.lbl_detail_path, False, False, 0)
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
                
            adj = self.log_view.get_vadjustment()
            adj.set_value(adj.get_upper() - adj.get_page_size())
        
        GLib.idle_add(_log)

    # --- LOGIC ---

    def on_refresh_clicked(self, widget):
        self.refresh_devices()

    def refresh_devices(self):
        self.log("Scanning USB devices...")
        self.spinner.start()
        # Run scan in thread to avoid freezing UI for spinner
        t = threading.Thread(target=self._refresh_thread)
        t.daemon = True
        t.start()

    def _refresh_thread(self):
        max_devs = 64
        arr = (MCDeviceInfo * max_devs)()
        count = libmc.mc_list_all_usb_devices(arr, max_devs)
        
        def _update():
            self.dev_store.clear()
            self.log(f"Scan complete. Found {count} devices.")
            
            for i in range(count):
                d = arr[i]
                syspath = d.syspath.decode('utf-8', 'ignore')
                vidpid = d.vidpid.decode('utf-8', 'ignore')
                product = d.product.decode('utf-8', 'ignore')
                driver = d.driver.decode('utf-8', 'ignore')
                
                icon = "input-mouse" 
                if "None" in driver:
                    icon = "dialog-warning" 
                elif "hub" in driver:
                    icon = "computer"
                else:
                    icon = "drive-harddisk"
                
                self.dev_store.append([syspath, vidpid, product, driver, icon])
            
            self.spinner.stop()
            
        GLib.idle_add(_update)

    def on_dev_selection_changed(self, selection):
        model, treeiter = selection.get_selected()
        if treeiter:
            self.btn_auto.set_sensitive(True)
            self.btn_unload.set_sensitive(True)
            self.btn_web_search.set_sensitive(True)
            
            # Update Details
            syspath = model[treeiter][0]
            vidpid = model[treeiter][1]
            product = model[treeiter][2]
            
            self.lbl_detail_name.set_markup(f"<b>Device:</b> {product}")
            self.lbl_detail_id.set_markup(f"<b>ID:</b> {vidpid}")
            self.lbl_detail_path.set_text(f"Path: {syspath}")
            
        else:
            self.btn_auto.set_sensitive(False)
            self.btn_unload.set_sensitive(False)
            self.btn_web_search.set_sensitive(False)
            self.lbl_detail_name.set_text("Select a device to view details.")
            self.lbl_detail_id.set_text("")
            self.lbl_detail_path.set_text("")

    def on_web_search_clicked(self, widget):
        model, treeiter = self.dev_tree.get_selection().get_selected()
        if not treeiter: return
        vidpid = model[treeiter][1]
        
        # Open Google or DeviceHunt
        url = f"https://www.google.com/search?q=linux+usb+driver+{vidpid}"
        self.log(f"Opening browser for {vidpid}...")
        webbrowser.open(url)

    def on_unload_clicked(self, widget):
        model, treeiter = self.dev_tree.get_selection().get_selected()
        if not treeiter: return
        
        driver = model[treeiter][3]
        if driver == "None":
            self.log("Device has no driver to unload.", "red")
            return
            
        # SAFETY DIALOG
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Unload Driver?"
        )
        dialog.format_secondary_text(
            f"Unloading '{driver}' may stop your device from working or destabilize the system.\n\nAre you sure you want to continue?"
        )
        response = dialog.run()
        dialog.destroy()
        
        if response != Gtk.ResponseType.OK:
            self.log("Unload cancelled by user.")
            return

        self.log(f"Unloading driver {driver}...", "bold")
        libmc.mc_unload_driver(driver.encode('utf-8'))
        
        time.sleep(0.5)
        self.refresh_devices()

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
            
            # Unload
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
                            GLib.idle_add(self.refresh_devices)
                            # Could auto-select or auto-run here
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
