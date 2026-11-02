"""Specter firmware controls shared by the Workspace and Pro add-on builds.
New controls intentionally have no host entitlement lock during validation.
Firmware team-mode/arming checks remain authoritative.
"""
import time
import tkinter as tk
from tkinter import ttk

BT_MODULES = ('tracker','phantom','beacon','spoofer','predator','sk','wp','karr','skimmer')

def starts_job(command):
    words=command.strip().split()
    if words[:1] and words[0] in ('apclone','apdeauth'):return True
    if words[:2] in (['probetwin','start'],['iotrecon','start'],['guardian','start']):return True
    return (len(words)>1 and words[0] in BT_MODULES and words[1] not in
            ('stop','list','dump','interval','lost','rotate','sig','disconnect')) or command.startswith(
                ('probetwin start ','iotrecon start ','guardian start'))

def stop_command(command):
    first=command.strip().split()[:1]
    if first and first[0] in BT_MODULES: return 'stopble'
    if first==['probetwin']: return 'probetwin stop'
    if first==['iotrecon']: return 'iotrecon stop'
    if first==['guardian']: return 'guardian stop'
    if first==['recon']: return 'recon stop'
    return 'stopscan'

def catalog(P,C):
    target=lambda: P('BT+ device index',kind='int',placeholder='Run tracker list / predator scan first')
    seconds=lambda: P('Seconds',kind='int',default='20')
    return [('Specter',[
      ('Sessions and clock',[
        C('Session status','session status','Device session status.'),
        C('Start device session','session start','Creates a named SD evidence session.',[P('Name',default='Lab session')]),
        C('End device session','session stop','End after stopping running jobs.'),
        C('Clock status','clock status','UTC time and source.'),
        C('Set UTC epoch','clock set','Unix UTC seconds.',[P('Epoch',kind='int')]),
        C('SD date self-test','clock sdtest','Creates and removes its own temporary test file.'),
        C('Apply known file date','filedate','Changes a known existing file modification date.',[P('UTC epoch',kind='int'),P('SD path',default='/capture.pcap')]),
        C('Team mode','team','Explicit firmware Blue/Red mode selection.',[P('Mode',kind='choice',choices=['status','blue','red'],default='status')]),
      ]),
      ('WiFi automation',[
        C('Guardian start','guardian start','Passive deauthentication detection.'),
        C('Guardian status','guardian status','Guardian activity state.'),
        C('Guardian stop','guardian stop','Stop Guardian.'),
        C('Probe to Portal','probetwin start','Exact directed SSID match; existing portal template required; firmware Red Team gate.',[P('Exact SSID')]),
        C('Probe Portal status','probetwin status','Automation state.'),
        C('Stop Probe Portal','probetwin stop','Cancel workflow.'),
        C('IoT Recon range','iotrecon start','Conventional TCP-port discovery on the joined subnet; at most 254 addresses.',[P('First IPv4'),P('Last IPv4')]),
        C('IoT Recon status','iotrecon status','Discovery status.'),
        C('IoT Recon stop','iotrecon stop','Stop discovery.'),
      ]),
      ('BLE discovery',[
        C('BT+ status','bt status','Radio, scan, TX and log status.'),
        C('BT+ help','bt help','Available commands in this firmware.'),
        C('BT+ logs','bt loot','Storage/log path.'),
        C('Tracker scan','tracker scan','Timed tracker discovery; classifications need validation.',[seconds(),P('Log',kind='bool',flag='log')]),
        C('Tracker list','tracker list','BT+ indices are separate from legacy BLE indices.'),
        C('Predator scan','predator scan','Discover connectable BLE devices.',[seconds()]),
        C('Predator GATT recon','predator recon','Read GATT services/characteristics on your selected device; firmware arm gate.',[target()]),
        C('Whisper scan','wp scan','Fast Pair discovery.',[seconds()]),
        C('KARR scan','karr scan','Candidate detection, not a vulnerability verdict.',[seconds()]),
        C('KARR list','karr list','Candidate list.'),
        C('Skimmer scan','skimmer scan','BETA BLE-only heuristic.'),
        C('Skimmer list','skimmer list','Candidates, not confirmed skimmers.'),
      ]),
      ('BLE active tools',[
        C('Begin BT arm','bt arm','Opens firmware confirmation window; explicitly confirm separately.'),
        C('Confirm BT arm','bt arm yes','Explicit authorization confirmation; firmware gates remain.'),
        C('Disarm BT','bt disarm','Disable active BT+ modules.'),
        C('Stop all BT+','stopble','Stop suite modules.'),
        C('Phantom start','phantom start','Existing advertisement module.',[P('Count',kind='int',default='16')]),
        C('Phantom replay','phantom replay','Existing captured advertisement replay.',[target(),P('Count',kind='int',default='1')]),
        C('Phantom lost flag','phantom lost','Existing advertisement option.',[P('State',kind='choice',choices=['on','off'],default='off')]),
        C('Apple spoof','spoofer apple','Existing module; authorized target testing.',[P('Type',default='all')]),
        C('Android spoof','spoofer android','Model IDs require evidence; example defaults are placeholders.',[P('Model ID / all',default='all')]),
        C('Swiftpair spoof','spoofer swift','Existing module.',[P('Name',default='Specter Lab')]),
        C('Beacon iBeacon','beacon ibeacon','Existing beacon module.',[P('UUID'),P('Major',kind='int',default='1'),P('Minor',kind='int',default='1')]),
        C('Beacon URL','beacon url','Existing Eddystone-style URL beacon.',[P('URL',default='https://example.com')]),
        C('Beacon UID','beacon uid','Existing namespace/instance beacon.',[P('Namespace hex'),P('Instance hex')]),
        C('Beacon TLM','beacon tlm','Existing telemetry beacon.'),
        C('Beacon interval','beacon interval','Milliseconds.',[P('Milliseconds',kind='int',default='1000')]),
        C('Spoofer interval','spoofer interval','Milliseconds.',[P('Milliseconds',kind='int',default='1000')]),
        C('Predator honeypot','predator honeypot','Existing module mirrors a prior recon table; owned-device testing only.',[target()]),
        C('Skeleton connect','sk connect','Existing GATT module; select a BT+ device.',[target()]),
        C('Skeleton dump','sk dump','Enumerated GATT table.'),
        C('Skeleton fuzz','sk fuzz','Existing firmware handler; explicit owned-target assessment.',[P('Service UUID / all',default='all'),P('Characteristic / count',default='1'),P('Count (for UUID mode)',default='')]),
        C('Skeleton LED','sk led','Existing writable-characteristic helper.',[P('Value',default='off')]),
        C('Whisper assessment','wp probe','Assessment response is not proof of a CVE or full pairing.',[target()]),
        C('KARR assessment','karr assess','Existing verdict-only handler; no vehicle control.',[target()]),
        C('KARR signature','karr sig','Add a capture-backed detection signature.',[P('Signature arguments')]),
        C('Skimmer verification','skimmer verify','Heuristic verification, not a confirmed finding.',[target()]),
      ]),
    ])]

def build_page(app,page):
    page.title('Specter firmware')
    ttk.Label(page,text='Specter firmware',style='Title.TLabel').pack(anchor='w',padx=16,pady=12)
    ttk.Label(page,text='Sessions, WiFi automation and BLE tools. Firmware team and arming requirements apply.',wraplength=740).pack(anchor='w',padx=16)
    bar=ttk.Frame(page);bar.pack(fill='x',padx=16,pady=8)
    for title,cmd in [('Status','bt status'),('Help','bt help'),('Session','session status'),('Clock','clock status'),('Stop BLE','stopble')]:
        ttk.Button(bar,text=title,command=lambda c=cmd:app._do_send(c)).pack(side='left',padx=3)
    ttk.Button(bar,text='Sync UTC now',command=lambda:app._do_send('clock set '+str(int(time.time())))).pack(side='left',padx=3)
    ttk.Button(bar,text='Stop active job',command=app.stop_running).pack(side='left',padx=3)
    ttk.Button(page,text='All Specter options → Command catalog',command=app._show_catalog).pack(anchor='w',padx=16,pady=6)
    ttk.Label(page,text='Device replies (all output also appears in the main console)').pack(anchor='w',padx=16)
    output=tk.Text(page,height=16,wrap='word',state='disabled',bg='#0c111b',fg='#e8eef7',insertbackground='#e8eef7',font=('Consolas',10),padx=10,pady=8)
    output.pack(fill='both',expand=True,padx=16,pady=8)
    app._specter_output=output
