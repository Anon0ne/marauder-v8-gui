"""Marauder V8 0.4.0b Beta: persistent navigation and embedded tool pages."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from marauder_gui import MarauderGUI, PALETTE, BAUD, Marauder, __version__

PALETTE.update(bg='#0c111b', panel='#131b29', panel2='#131b29', entry='#0c111b',
               border='#273448', fg='#e8eef7', muted='#99abc1', accent='#16b8a6')
FONT = ('Segoe UI', 10)
MONO = ('Consolas', 10)


class RoundedCard(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=PALETTE['bg'], **kwargs)
        self.canvas = tk.Canvas(self, bg=PALETTE['bg'], highlightthickness=0, bd=0)
        self.canvas.pack(fill='both', expand=True)
        self.body = ttk.Frame(self.canvas, style='Card.TFrame')
        self.window = self.canvas.create_window(16, 16, window=self.body, anchor='nw')
        self.body.bind('<Configure>', self._body_size)
        self.canvas.bind('<Configure>', self._draw)
        self.after_idle(lambda: self.after_idle(self._sync_size))

    def _sync_size(self):
        self.canvas.configure(height=self.body.winfo_reqheight() + 32)

    def _body_size(self, event):
        self.canvas.configure(height=self.body.winfo_reqheight() + 32)

    def _draw(self, event):
        width, height = event.width, event.height
        radius = 12
        self.canvas.delete('surface')
        points = [radius,1,width-radius,1,width-1,1,width-1,radius,
                  width-1,height-radius,width-1,height-1,width-radius,height-1,
                  radius,height-1,1,height-1,1,height-radius,1,radius,1,1]
        self.canvas.create_polygon(points, smooth=True, splinesteps=24,
                                   fill=PALETTE['panel'], outline=PALETTE['border'],
                                   tags='surface')
        self.canvas.tag_lower('surface')
        self.canvas.itemconfigure(self.window, width=max(1,width-32))
        if height > 32:
            self.canvas.itemconfigure(self.window, height=height-32)


class ToolPage(tk.Frame):
    def __init__(self, app, key):
        super().__init__(app._workspace_container, bg=PALETTE['panel2'])
        self.app = app
        self.key = key

    def title(self, title):
        self.app._page_label.set(title)

    def geometry(self, geometry):
        pass

    def transient(self, parent):
        pass

    def lift(self, above=None):
        self.app._show_page(self)


class WorkspaceGUI(MarauderGUI):
    def __init__(self):
        self._workspace_shutdown = False
        self._connecting = False
        self._pages = {}
        self._nav_buttons = {}
        super().__init__()
        width = min(1240, self.winfo_screenwidth()-60)
        height = min(860, self.winfo_screenheight()-100)
        self.geometry(f'{width}x{height}')
        self.minsize(1080, 720)
        self.title(f'Marauder V8 Workspace — {__version__}')

    def _build_style(self):
        super()._build_style()
        style = ttk.Style(self)
        style.configure('.', font=FONT, lightcolor=PALETTE['border'],
                        darkcolor=PALETTE['border'], bordercolor=PALETTE['border'])
        style.configure('Nav.TButton', background=PALETTE['panel'],
                        borderwidth=0, padding=(12,9), anchor='w', font=FONT)
        style.map('Nav.TButton', background=[('active','#1c293b')])
        style.configure('Selected.Nav.TButton', background='#153b39', foreground='#55d9c8')
        style.map('Selected.Nav.TButton', background=[('active','#1b4946')])
        style.configure('Heading.TLabel', background=PALETTE['bg'],
                        foreground=PALETTE['fg'], font=('Segoe UI',18,'bold'))
        style.configure('Metric.TLabel', background=PALETTE['bg'], font=('Segoe UI',22))
        style.configure('WorkspaceMuted.TLabel', background=PALETTE['bg'], foreground=PALETTE['muted'])
        style.configure('TButton', padding=(12,8), borderwidth=1, relief='flat',
                        lightcolor=PALETTE['border'], darkcolor=PALETTE['border'])
        style.map('TButton', bordercolor=[('focus',PALETTE['accent']),('active','#40516a')])
        style.configure('Treeview', rowheight=30, background=PALETTE['panel'],
                        fieldbackground=PALETTE['panel'], borderwidth=0, font=FONT,
                        lightcolor=PALETTE['panel'],darkcolor=PALETTE['panel'])
        style.configure('Treeview.Heading', background=PALETTE['panel'],
                        foreground=PALETTE['muted'], padding=(8,9), font=FONT,
                        relief='flat',lightcolor=PALETTE['panel'],darkcolor=PALETTE['panel'],
                        bordercolor=PALETTE['panel'])
        style.map('Treeview.Heading', background=[('active','#1c293b')])
        style.configure('TNotebook', background=PALETTE['panel'],bordercolor=PALETTE['border'],
                        lightcolor=PALETTE['border'],darkcolor=PALETTE['border'])
        style.configure('TNotebook.Tab', padding=(14,8), font=FONT,
                        lightcolor=PALETTE['border'],darkcolor=PALETTE['border'])
        style.configure('TEntry',lightcolor=PALETTE['border'],darkcolor=PALETTE['border'])
        style.configure('TMenubutton',lightcolor=PALETTE['border'],darkcolor=PALETTE['border'])
        style.configure('TCombobox',lightcolor=PALETTE['border'],darkcolor=PALETTE['border'])
        style.configure('Vertical.TScrollbar',background=PALETTE['panel'],
                        troughcolor=PALETTE['entry'],lightcolor=PALETTE['panel'],
                        darkcolor=PALETTE['panel'],arrowcolor=PALETTE['muted'])
        style.configure('TPanedwindow', sashwidth=8)

    def _build_toolbar(self):
        header = tk.Frame(self, bg=PALETTE['panel'], padx=24, pady=18)
        header.pack(fill='x')
        tk.Label(header, text='◉', bg=PALETTE['panel'], fg=PALETTE['accent'],
                 font=('Segoe UI',24)).pack(side='left', padx=(0,12))
        brand = ttk.Frame(header)
        brand.pack(side='left')
        ttk.Label(brand, text='MARAUDER    V8 / 0.4.0b Beta', font=('Segoe UI',15,'bold')).pack(anchor='w')
        ttk.Label(brand, text='Radio reconnaissance workspace', style='Muted.TLabel').pack(anchor='w')
        self.connect_btn = ttk.Button(header, text='Connect', style='Accent.TButton',
                                       command=self.toggle_connection)
        self.connect_btn.pack(side='right', padx=(12,0))
        self.status = ttk.Label(header, text='● Disconnected', style='Muted.TLabel')
        self.status.pack(side='right', padx=12)
        settings = ttk.Menubutton(header, text='Connection ▾')
        settings.pack(side='right', padx=8)
        menu = tk.Menu(settings, tearoff=False)
        menu.add_command(label='Port, baud, and auto-connect...', command=self._connection_settings)
        settings.configure(menu=menu)
        # Keep the existing port discovery and connection API, with settings out
        # of the main workspace instead of crowding its header.
        self.port_cb = ttk.Combobox(header, state='readonly')
        self.baud_cb = ttk.Combobox(header, state='readonly', values=['9600','115200','230400','921600'])
        self.baud_cb.set(str(BAUD))
        self.ac_chk = ttk.Checkbutton(header, variable=self.autoconnect)
        self.stop_all_btn = ttk.Button(header, text='Stop', command=self.stop_running)
        ttk.Separator(self).pack(fill='x')

    def _connection_settings(self):
        self.refresh_ports()
        dialog = tk.Toplevel(self)
        dialog.title('Connection settings')
        dialog.configure(bg=PALETTE['panel'])
        dialog.transient(self)
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text='Serial port').pack(anchor='w')
        port = ttk.Combobox(body, state='readonly', width=42, values=self.port_cb['values'])
        port.set(self.port_cb.get())
        port.pack(fill='x', pady=(4,14))
        ttk.Label(body, text='Baud rate').pack(anchor='w')
        baud = ttk.Combobox(body, state='readonly', values=self.baud_cb['values'])
        baud.set(self.baud_cb.get())
        baud.pack(fill='x', pady=(4,14))
        ttk.Checkbutton(body, text='Auto-connect when the board is present', variable=self.autoconnect).pack(anchor='w')
        def apply():
            self.port_cb.set(port.get())
            self.baud_cb.set(baud.get())
            dialog.destroy()
        ttk.Button(body, text='Apply', style='Accent.TButton', command=apply).pack(anchor='e', pady=(18,0))

    def _build_body(self):
        outer = tk.Frame(self, bg=PALETTE['bg'])
        outer.pack(fill='both', expand=True)
        sidebar = tk.Frame(outer, bg=PALETTE['panel'], width=210, padx=12, pady=20)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        def label(text):
            ttk.Label(sidebar, text=text, style='Muted.TLabel', font=('Segoe UI',9)).pack(anchor='w', padx=10, pady=(0,10))
        def nav(key, text, command):
            button = ttk.Button(sidebar, text=text, style='Nav.TButton', command=command)
            button.pack(fill='x', pady=2)
            self._nav_buttons[key] = button
        label('WORKSPACE')
        nav('home','WiFi recon',self._show_workspace)
        nav('ble','BLE devices',self.open_ble_devices)
        nav('sd','SD files',self.open_sd_browser)
        nav('sessions','Sessions',self._session_actions)
        ttk.Separator(sidebar).pack(fill='x', padx=10, pady=18)
        label('TOOLS')
        nav('catalog','Command catalog',self._show_catalog)
        nav('ai','AI Assistant',self.open_ai_dialog)
        nav('dashboard','RF Dashboard',self.open_dashboard)
        nav('survey','Automated Survey',self.open_survey)
        nav('firmware','Firmware',self.open_firmware_dialog)
        nav('pcap','PCAP Inspector',self.open_pcap_dialog)
        ttk.Label(sidebar, text='ESP32 Marauder V8\nUSB serial', style='Muted.TLabel').pack(side='bottom', anchor='w', padx=10, pady=8)
        main = tk.Frame(outer, bg=PALETTE['bg'], padx=22, pady=20)
        main.pack(side='left', fill='both', expand=True)
        self._page_label = tk.StringVar(value='WiFi reconnaissance')
        # The console shares only the right-hand workspace, not the sidebar.
        self.vpane = ttk.Panedwindow(main, orient='vertical')
        self.vpane.pack(fill='both', expand=True)
        self._workspace_container = ttk.Frame(self.vpane, style='Bg.TFrame')
        self.vpane.add(self._workspace_container, weight=4)
        self._workspace_home = ttk.Frame(self._workspace_container, style='Bg.TFrame')
        self._workspace_home.pack(fill='both', expand=True)
        ttk.Label(self._workspace_home, text='WiFi reconnaissance', style='Heading.TLabel').pack(anchor='w')
        ttk.Label(self._workspace_home, text='Live observations from your connected board',
                  style='WorkspaceMuted.TLabel').pack(anchor='w', pady=(4,14))
        metrics = ttk.Frame(self._workspace_home, style='Bg.TFrame')
        metrics.pack(fill='x', pady=(0,14))
        self._workspace_counts = []
        for text in ['Access points','Stations','Channels observed']:
            cell = ttk.Frame(metrics, style='Bg.TFrame')
            cell.pack(side='left', padx=(0,48))
            value = tk.StringVar(value='0')
            self._workspace_counts.append(value)
            ttk.Label(cell, textvariable=value, style='Metric.TLabel').pack(anchor='w')
            ttk.Label(cell, text=text, style='WorkspaceMuted.TLabel').pack(anchor='w')
        recon = RoundedCard(self._workspace_home)
        recon.pack(fill='x', pady=(0,14))
        ttk.Label(recon.body, text='Passive reconnaissance', style='Card.TLabel',
                  font=('Segoe UI',11,'bold')).pack(anchor='w', pady=(0,12))
        self._recon_button = ttk.Button(recon.body, text='▶  Start recon', style='Accent.TButton',
                                        command=lambda: self._do_send('recon wifi'))
        self._recon_button.pack(side='right')
        self._recon_stop = ttk.Button(recon.body, text='■  Stop', style='Stop.TButton',
                                      command=self.stop_running)
        self._recon_stop.pack(side='right', padx=(0,8))
        ttk.Label(recon.body, text='recon wifi', style='Card.TLabel',
                  foreground='#55d9c8', font=('Consolas',11)).pack(side='left')
        observed = RoundedCard(self._workspace_home)
        observed.pack(fill='both', expand=True)
        heading = ttk.Frame(observed.body, style='Card.TFrame')
        heading.pack(fill='x', pady=(0,12))
        ttk.Label(heading,text='Observed access points', style='Card.TLabel',font=('Segoe UI',11,'bold')).pack(side='left')
        ttk.Label(heading,text='Sorted by signal',style='CardMuted.TLabel').pack(side='right')
        columns = ('ssid','band','channel','rssi')
        self._workspace_aps = ttk.Treeview(observed.body, columns=columns, show='headings', height=3)
        for name,text,width in [('ssid','Network',260),('band','Band',95),('channel','Channel',85),('rssi','Signal (dBm)',115)]:
            self._workspace_aps.heading(name,text=text)
            self._workspace_aps.column(name,width=width,minwidth=70,stretch=name=='ssid')
        scroll = ttk.Scrollbar(observed.body, command=self._workspace_aps.yview)
        scroll.pack(side='right',fill='y')
        self._workspace_aps.configure(yscrollcommand=scroll.set)
        self._workspace_aps.pack(fill='both',expand=True)
        self._workspace_empty = ttk.Label(observed.body, text='Connect and start recon to discover access points.',style='CardMuted.TLabel')
        self._workspace_empty.pack(anchor='w',pady=(8,0))
        self._build_catalog_page()
        self._select_nav('home')
        self.after(1000,self._workspace_refresh)
        footer = tk.Frame(self,bg=PALETTE['panel'],padx=24,pady=8)
        footer.pack(side='bottom',fill='x',before=outer)
        ttk.Label(footer,text='Marauder V8 0.4.0b Beta',style='Muted.TLabel').pack(side='left')
        ttk.Label(footer,text='Anon0ne',style='Muted.TLabel').pack(side='right')

    def _build_catalog_page(self):
        self._workspace_catalog = ttk.Panedwindow(self._workspace_container, orient='horizontal')
        nav = ttk.Frame(self._workspace_catalog, style='Card.TFrame',padding=8)
        self._workspace_catalog.add(nav,weight=1)
        self.tree = ttk.Treeview(nav,show='tree',selectmode='browse')
        scroll = ttk.Scrollbar(nav,command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        self.tree.pack(fill='both',expand=True)
        self.tree.tag_configure('attack',foreground=PALETTE['warn'])
        self.tree.tag_configure('group',foreground=PALETTE['accent'])
        self.tree.bind('<<TreeviewSelect>>',self._on_tree_select)
        self.cmd_by_iid = {}
        self._populate_tree()
        build = ttk.Frame(self._workspace_catalog,style='Card.TFrame')
        self._workspace_catalog.add(build,weight=2)
        canvas = tk.Canvas(build,bg=PALETTE['panel2'],highlightthickness=0)
        scrollbar = ttk.Scrollbar(build,command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y')
        canvas.pack(fill='both',expand=True)
        inner = ttk.Frame(canvas,style='Card.TFrame')
        item = canvas.create_window(0,0,window=inner,anchor='nw')
        inner.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(item,width=event.width))
        canvas.bind('<MouseWheel>',lambda event:canvas.yview_scroll(int(-event.delta/120),'units'))
        self._build_builder(inner)

    def _build_console(self):
        notebook = ttk.Notebook(self.vpane)
        self.vpane.add(notebook,weight=1)
        self._output_notebook = notebook
        console_page = ttk.Frame(notebook,style='Card.TFrame',padding=12)
        notebook.add(console_page,text='Serial console')
        raw = ttk.Frame(console_page,style='Card.TFrame')
        raw.pack(side='bottom',fill='x',pady=(8,0))
        self.raw_var = tk.StringVar()
        entry = ttk.Entry(raw,textvariable=self.raw_var,font=MONO)
        entry.pack(side='left',fill='x',expand=True)
        entry.bind('<Return>',lambda event:self._send_raw())
        ttk.Button(raw,text='Send',command=self._send_raw).pack(side='left',padx=8)
        export = ttk.Menubutton(raw,text='Options ▾')
        export.pack(side='left')
        menu = tk.Menu(export,tearoff=False)
        menu.add_command(label='Export console...',command=self.export_console_log)
        menu.add_command(label='Export Nmap targets...',command=self.export_nmap_targets)
        menu.add_command(label='Clear console',command=self._clear_console)
        menu.add_checkbutton(label='Auto-scroll',variable=self.autoscroll)
        menu.add_checkbutton(label='Log scans to CSV',variable=self.csv_logging,command=self._toggle_csv)
        export.configure(menu=menu)
        self.csv_status = ttk.Label(console_page,text='',style='CardMuted.TLabel')
        self.console = tk.Text(console_page,wrap='word',height=5,bg=PALETTE['entry'],fg=PALETTE['fg'],
                               insertbackground=PALETTE['fg'],font=MONO,relief='flat',padx=12,pady=10)
        scroll = ttk.Scrollbar(console_page,command=self.console.yview)
        scroll.pack(side='right',fill='y')
        self.console.configure(yscrollcommand=scroll.set)
        self.console.pack(fill='both',expand=True)
        for name,color in [('tx','#55d9c8'),('sys',PALETTE['muted']),('row',PALETTE['fg'])]:
            self.console.tag_configure(name,foreground=color)
        events = ttk.Frame(notebook,style='Card.TFrame',padding=12)
        notebook.add(events,text='Event log')
        self.evlog_status = ttk.Label(events,text='',style='CardMuted.TLabel')
        self.evlog_status.pack(anchor='w')
        self.eventlog = tk.Text(events,wrap='word',height=5,bg=PALETTE['entry'],fg=PALETTE['fg'],
                                font=MONO,relief='flat',padx=12,pady=10,state='disabled')
        self.eventlog.pack(fill='both',expand=True)
        for name,color in [('start','#55d9c8'),('stop',PALETTE['warn']),('conn',PALETTE['ok']),('info',PALETTE['muted'])]:
            self.eventlog.tag_configure(name,foreground=color)
        self._build_targets_tab(notebook)
        self.tgt_tree.configure(height=4)
        notebook.configure(height=170)

    def _select_nav(self,key):
        for name,button in self._nav_buttons.items():
            button.configure(style='Selected.Nav.TButton' if name==key else 'Nav.TButton')

    def _show_page(self,page,key=None):
        for child in self._workspace_container.winfo_children():
            child.pack_forget()
        page.pack(fill='both',expand=True)
        if key:
            self._select_nav(key)

    def _show_workspace(self):
        self._show_page(self._workspace_home,'home')

    def _show_catalog(self):
        self._show_page(self._workspace_catalog,'catalog')

    def _new_tool_window(self):
        key = self._creating_key
        page = ToolPage(self,key)
        self._pages[key] = page
        return page

    def _open_tool(self,key,build):
        page = self._pages.get(key)
        if page is None or not page.winfo_exists():
            self._creating_key = key
            build()
            page = self._pages.get(key)
            if page is None:
                return
        self._show_page(page,key)

    def open_ai_dialog(self):
        self._open_tool('ai',super().open_ai_dialog)

    def open_ble_devices(self):
        self._open_tool('ble',super().open_ble_devices)

    def open_sd_browser(self):
        self._open_tool('sd',super().open_sd_browser)

    def open_dashboard(self):
        self._open_tool('dashboard',super().open_dashboard)

    def open_survey(self):
        self._open_tool('survey',super().open_survey)

    def open_firmware_dialog(self):
        self._open_tool('firmware',super().open_firmware_dialog)

    def open_pcap_dialog(self):
        def build():
            page = self._new_tool_window()
            ttk.Label(page,text='PCAP Inspector',style='Title.TLabel').pack(anchor='w',padx=20,pady=20)
            ttk.Label(page,text='Inspect a capture from the board’s SD card.',style='CardMuted.TLabel').pack(anchor='w',padx=20)
            row = ttk.Frame(page,style='Card.TFrame')
            row.pack(fill='x',padx=20,pady=16)
            output = tk.Text(page,wrap='word',bg=PALETTE['entry'],fg=PALETTE['fg'],
                             font=MONO,relief='flat',padx=16,pady=16,state='disabled')
            output.pack(fill='both',expand=True,padx=20,pady=(0,20))
            def browse():
                from tkinter import filedialog
                import marauder_pcap
                path = filedialog.askopenfilename(title='Select a capture',filetypes=[('Capture files','*.pcap *.pcapng *.cap')])
                if not path:
                    return
                try:
                    text = marauder_pcap.format_summary(marauder_pcap.summarize(path))
                except Exception as error:
                    messagebox.showerror('PCAP error',str(error))
                    return
                output.configure(state='normal')
                output.delete('1.0','end')
                output.insert('1.0',text)
                output.configure(state='disabled')
                open_external.configure(command=lambda:marauder_pcap.open_in_wireshark(path),
                                        state='normal' if marauder_pcap.find_wireshark() else 'disabled')
            ttk.Button(row,text='Open capture...',style='Accent.TButton',command=browse).pack(side='left')
            open_external = ttk.Button(row,text='Open in Wireshark',state='disabled')
            open_external.pack(side='left',padx=12)
        self._open_tool('pcap',build)

    def _session_actions(self):
        def build():
            page = self._new_tool_window()
            ttk.Label(page,text='Sessions',style='Title.TLabel').pack(anchor='w',padx=20,pady=20)
            ttk.Label(page,text='Record, replay, or export your observations.',style='CardMuted.TLabel').pack(anchor='w',padx=20)
            for label,action in [('Start / stop recording',self.toggle_recording),
                                 ('Replay a session',self.replay_session),('Export inventory',self.export_inventory_report)]:
                ttk.Button(page,text=label,command=action).pack(anchor='w',padx=20,pady=10)
            ttk.Label(page,text='Recordings can contain private network identifiers.',style='CardMuted.TLabel').pack(anchor='w',padx=20,pady=20)
        self._open_tool('sessions',build)

    def _workspace_refresh(self):
        aps = self._lists.get('ap',{})
        channels = {row.get('channel') for row in aps.values() if row.get('channel')}
        for variable,count in zip(self._workspace_counts,[len(aps),len(self._lists.get('sta',{})),len(channels)]):
            variable.set(str(count))
        def signal(item):
            try:
                return int(item[1].get('rssi') or -999)
            except (TypeError,ValueError):
                return -999
        keep = set()
        for position,(key,row) in enumerate(sorted(aps.items(),key=signal,reverse=True)[:500]):
            iid = str(key)
            keep.add(iid)
            values = (row.get('ssid') or '(hidden)',self._band(row.get('channel','')),
                      row.get('channel',''),row.get('rssi',''))
            if self._workspace_aps.exists(iid):
                self._workspace_aps.item(iid,values=values)
                self._workspace_aps.move(iid,'',position)
            else:
                self._workspace_aps.insert('',position,iid=iid,values=values)
        for iid in self._workspace_aps.get_children():
            if iid not in keep:
                self._workspace_aps.delete(iid)
        self._workspace_empty.configure(text='' if aps else 'Connect and start recon to discover access points.')
        state = 'normal' if self.dev else 'disabled'
        self._recon_button.configure(state=state)
        self._recon_stop.configure(state=state)
        self.after(1500,self._workspace_refresh)

    def _connect(self,silent_fail=False):
        if self._connecting:
            return
        label = self.port_cb.get()
        if not label:
            if not silent_fail:
                messagebox.showwarning('No port','Select a serial port in Connection settings.')
            return
        port = self._port_map.get(label,label)
        baud = int(self.baud_cb.get())
        self._connecting = True
        self.connect_btn.configure(text='Connecting...',state='disabled')
        self.status.configure(text=f'Opening {port}...',foreground=PALETTE['muted'])
        results = queue.Queue()
        def work():
            try:
                device = Marauder(port,baud)
                if self._workspace_shutdown:
                    device.close()
                    return
                results.put((device,None))
            except Exception as error:
                results.put((None,str(error)))
        def finish():
            if self._workspace_shutdown:
                return
            try:
                device,error = results.get_nowait()
            except queue.Empty:
                self.after(60,finish)
                return
            self._connecting = False
            self.connect_btn.configure(state='normal')
            if error:
                self.connect_btn.configure(text='Connect')
                self.status.configure(text=f'Connection failed · {port}',foreground=PALETTE['warn'])
                self._emit(f'[connection failed: {port} @ {baud}: {error}]\n','sys')
                self.log_event('ERROR',f'connection failed: {port}: {error}')
                if not silent_fail:
                    messagebox.showerror('Connection failed',error)
                return
            self.dev = device
            self._connected_port = port
            self.reader_stop.clear()
            self.reader_thread = threading.Thread(target=self._reader_loop,daemon=True)
            self.reader_thread.start()
            self.connect_btn.configure(text='Disconnect')
            self.status.configure(text=f'● {port} · {baud}',foreground='#55d9c8')
            self._emit(f'[connected to {port} @ {baud}]\n','sys')
            self.log_event('CONNECT',f'{port} @ {baud}')
            self._recon_button.configure(state='normal')
            self._recon_stop.configure(state='normal')
        threading.Thread(target=work,daemon=True).start()
        self.after(60,finish)

    def _on_close(self):
        self._workspace_shutdown = True
        super()._on_close()


if __name__ == '__main__':
    WorkspaceGUI().mainloop()
