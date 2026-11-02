"""SD/local template library; offline previews disable scripts, forms and network."""
from pathlib import Path
import os,re,tempfile,webbrowser
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from app_paths import APP_DIR

MAX_PREVIEW=512*1024

def template_paths(entries):
    return sorted((e.name for e in entries if not e.is_dir and Path(e.name).suffix.lower() in ('.html','.htm')),key=str.casefold)

def device_template_command(path):
    from marauder_sdfs import _quote
    path=path.lstrip('/')
    if not path or '..' in Path(path).parts:raise ValueError('Invalid SD template path')
    return 'evilportal -c sethtml '+_quote(path)

def portal_start_command(path):
    return device_template_command(path).replace('evilportal -c sethtml ', 'evilportal -c start -w ', 1)

def offline_preview(source):
    # A leading CSP governs even scripts/forms/styles retained from a template.
    source=re.sub(r'<\s*base\b[^>]*>','',source,flags=re.I)
    source=re.sub(r'<meta\b[^>]*http-equiv\s*=\s*[\'\"]?refresh[^>]*>','',source,flags=re.I)
    csp="default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'none'; base-uri 'none'; script-src 'none'; frame-src 'none'"
    return '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'+csp+'"></head><body>'+source+'</body></html>'

def build_page(app,page):
    page.title('Evil Portal templates')
    bar=ttk.Frame(page);bar.pack(side='bottom',fill='x',padx=16,pady=8)
    ttk.Label(page,text='Evil Portal templates',style='Title.TLabel').pack(anchor='w',padx=16,pady=10)
    status=tk.StringVar(value='Browse templates on the device SD card, including Rian’s folders.')
    ttk.Label(page,textvariable=status,wraplength=750).pack(anchor='w',padx=16)
    chosen=tk.StringVar(value=getattr(app,'_portal_selected_path',''))
    selection=ttk.Frame(page);selection.pack(fill='x',padx=16,pady=3)
    ttk.Label(selection,text='Selected template').pack(side='left')
    ttk.Entry(selection,textvariable=chosen,state='readonly').pack(side='left',fill='x',expand=True,padx=6)
    setup=ttk.Frame(page);setup.pack(fill='x',padx=16,pady=3)
    ttk.Label(setup,text='Scanned AP index').pack(side='left')
    ap=tk.StringVar();ap_picker=ttk.Combobox(setup,textvariable=ap,width=28)
    ap_picker.pack(side='left',padx=6)
    def refresh_aps(request=False):
        if request:
            app._do_send('list -a');page.after(500,refresh_aps)
        records=getattr(app,'_lists',{}).get('ap',{})
        ap_picker['values']=[str(i)+' — '+str(row.get('ssid','')) for i,row in records.items()]
    def set_ap():
        value=ap.get().split(' — ',1)[0].strip()
        if not value.isdecimal():messagebox.showinfo('AP setup','Choose an AP index from your scanned AP list.');return
        app._do_send('evilportal -c setap '+value)
        status.set('AP configuration sent. Starting the portal is a separate action.')
    ttk.Button(setup,text='Refresh APs',command=lambda:refresh_aps(True)).pack(side='left',padx=3)
    ttk.Button(setup,text='Set AP',command=set_ap).pack(side='left',padx=3)
    ttk.Button(setup,text='Scan APs',command=lambda:app._do_send('recon wifi')).pack(side='left',padx=3)
    refresh_aps()
    root=tk.StringVar(value='/')
    nav=ttk.Frame(page);nav.pack(fill='x',padx=16,pady=6)
    ttk.Label(nav,text='SD folder').pack(side='left');ttk.Entry(nav,textvariable=root,width=38).pack(side='left',padx=6)
    filterbar=ttk.Frame(page);filterbar.pack(fill='x',padx=16,pady=4)
    query=tk.StringVar();ttk.Label(filterbar,text='Filter templates').pack(side='left')
    ttk.Entry(filterbar,textvariable=query).pack(side='left',fill='x',expand=True,padx=6)
    content=ttk.Panedwindow(page,orient='vertical');content.pack(fill='both',expand=True,padx=16,pady=6)
    treeframe=ttk.Frame(content);content.add(treeframe,weight=2)
    tree=ttk.Treeview(treeframe,columns=('location','path'),show='headings',height=7)
    tree.heading('location',text='Source');tree.column('location',width=80,stretch=False)
    tree.heading('path',text='Template path');tree.pack(side='left',fill='both',expand=True)
    scrollbar=ttk.Scrollbar(treeframe,orient='vertical',command=tree.yview)
    scrollbar.pack(side='right',fill='y');tree.configure(yscrollcommand=scrollbar.set)
    source=tk.Text(content,height=4,wrap='word',bg='#0c111b',fg='#e8eef7',insertbackground='#e8eef7',font=('Consolas',10),padx=10,pady=8);content.add(source,weight=1)
    initial_sash = [False]
    def size_panes(event):
        if not initial_sash[0] and event.height > 150:
            content.sashpos(0, int(event.height * .6));initial_sash[0] = True
    content.bind('<Configure>',size_panes)
    page._portal_tree=tree;page._portal_status=status
    templates=[];paths={};loaded={'html':None};cache=tempfile.TemporaryDirectory(prefix='specter-portals-')
    # Keep previews alive until the page/app is destroyed, never overwrite an original.
    page._portal_cache=cache
    def select():
        ids=tree.selection()
        if not ids:messagebox.showinfo('Templates','Select a template.');return None
        return paths[ids[0]]
    def show_source(text):
        loaded['html']=text;source.delete('1.0','end');source.insert('1.0',text)
        status.set('Template loaded. Preview is offline; scripts/forms/network are disabled.')
    def add(kind,path):
        key=tree.insert('', 'end',values=(kind,str(path)));paths[key]=(kind,str(path))
    def repaint(*_):
        tree.delete(*tree.get_children());paths.clear()
        for kind,path in templates:
            if query.get().casefold() in str(path).casefold():add(kind,path)
    query.trace_add('write',repaint)
    def scan_sd():
        folder = root.get().strip() or "/"
        def done(entries):
            templates[:]=[('SD',path) for path in template_paths(entries)]
            loaded['html']=None;repaint()
            status.set(f'{len(paths)} HTML templates found on SD. Select one, then View source / Preview.')
        app._sd_job(lambda fs:fs.tree(folder),done,'Find SD templates')
    page._scan_sd_templates=scan_sd
    ttk.Button(nav,text='Find SD templates',command=scan_sd).pack(side='left',padx=4)
    def local(folder=None):
        folder=folder or filedialog.askdirectory(title='Local portal library')
        if not folder:return
        templates[:]=[('Local',path) for path in sorted(Path(folder).rglob('*'))
                      if path.is_file() and path.suffix.lower() in ('.html','.htm')]
        loaded['html']=None;repaint()
        status.set(f'{len(paths)} local HTML templates found')
    def load(preview=False):
        item=select()
        if not item:return
        kind,path=item
        def display(text):
            show_source(text)
            if preview:
                target=Path(cache.name)/'preview.html';target.write_text(offline_preview(text),encoding='utf-8')
                webbrowser.open(target.as_uri())
        if kind=='Local':
            try:
                if Path(path).stat().st_size>MAX_PREVIEW:raise ValueError('Template exceeds preview size limit')
                display(Path(path).read_text(encoding='utf-8',errors='replace'))
            except (OSError,ValueError) as exc:messagebox.showerror('Template',str(exc))
        else:
            def work(fs):
                # stat reports size after path; bound the transfer before downloading.
                info=fs.stat(path)
                if info.startswith('F ') and int(info.rsplit(' ',2)[1])>MAX_PREVIEW:raise ValueError('Template exceeds preview size limit')
                target=Path(cache.name)/'download.html';fs.download(path,str(target))
                return target.read_text(encoding='utf-8',errors='replace')
            app._sd_job(work,display,'Read SD template')
    def select_for_portal(path):
        chosen.set(path);app._portal_selected_path=path
        app._do_send(device_template_command(path))
        status.set('Template selection sent. Stop any scan before starting the portal.')
    def use():
        item=select()
        if item and item[0]=='SD':
            if getattr(app,'running',False):messagebox.showinfo('Portal','Stop the current operation before changing portal setup.');return
            select_for_portal(item[1])
        elif item:messagebox.showinfo('Template','Upload the local template to SD first.')
    def start_portal():
        path=chosen.get()
        if not path:messagebox.showinfo('Portal','Select an SD template with Use SD template first.');return
        if getattr(app,'running',False):messagebox.showinfo('Portal','Stop the current operation before starting the portal.');return
        # Validate the same path that Start will send; do not guess or truncate it.
        def checked(info):
            if not info.startswith('F '):status.set('The selected path is not a file.');return
            app._do_send(portal_start_command(path))
            status.set('Start request sent using the selected template. Check the device reply for success.')
        app._sd_job(lambda fs:fs.stat(path),checked,'Check portal template')
    def stop_portal():
        app._do_send('stopscan',event_kind='STOP');status.set('Stop request sent.')
    page._start_portal=start_portal
    def upload():
        item=select()
        if not item or item[0]!='Local':messagebox.showinfo('Upload','Select a local HTML template.');return
        path=Path(item[1]);destination='/'+path.name
        if not messagebox.askyesno('Upload template',f'Upload {path.name} to SD root? An existing file with this name will be replaced.'):return
        app._sd_job(lambda fs:fs.upload(str(path),destination),lambda _:status.set('Uploaded '+destination+'. Refresh SD templates to select it.'),'Upload template')
    for label,fn in [('View source',load),('Preview',lambda:load(True)),('Use SD template',use),('Start portal',start_portal),('Stop portal',stop_portal),('Local folder',local),('Upload local',upload)]:
        ttk.Button(bar,text=label,command=fn).pack(side='left',padx=3)
    # Present bundled local files immediately, without opening serial automatically.
    local(APP_DIR/'portals')
    status.set('Local templates shown. Use Find SD templates for Rian’s library on your device.')
