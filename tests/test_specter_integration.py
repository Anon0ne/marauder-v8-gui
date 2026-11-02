import sys,tempfile,types,unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from marauder_specter import starts_job,stop_command
from marauder_portals import offline_preview,device_template_command,template_paths
from marauder_commands import CATALOG
from marauder_sdfs import SDEntry
from marauder_gui import command_runs

class SpecterTests(unittest.TestCase):
 def test_catalog_and_stop_routing(self):
  spec=next(groups for title,groups in CATALOG if title=='Specter')
  bases={cmd['base'] for _,cmds in spec for cmd in cmds}
  self.assertTrue({'session start','clock set','filedate','guardian start','probetwin start','iotrecon start','predator recon','sk connect','karr assess','wp probe','skimmer verify','beacon ibeacon'}<=bases)
  for cmd in ('tracker scan 3','predator scan 20','spoofer apple all','beacon tlm','sk connect 0'):
   self.assertTrue(starts_job(cmd));self.assertEqual(stop_command(cmd),'stopble')
  self.assertEqual(stop_command('iotrecon start 192.168.1.1 192.168.1.2'),'iotrecon stop')
  self.assertFalse(command_runs('evilportal -c sethtml "Rians/Owned Template.html"'))
  self.assertTrue(command_runs('evilportal -c start'))
 def test_templates_paths_preview_and_quoting(self):
  self.assertEqual(template_paths([SDEntry('/Rians/Owned.HTML',False),SDEntry('/folder',True)]),['/Rians/Owned.HTML'])
  self.assertEqual(device_template_command('/Rians/Owned Template.html'),'evilportal -c sethtml "Rians/Owned Template.html"')
  with self.assertRaises(ValueError):device_template_command('/../settings')
  html=offline_preview('<meta http-equiv="refresh" content="0; url=https://example.com"><base href="https://example.com"><script>x()</script><form action="https://example.com">')
  self.assertIn("form-action 'none'",html);self.assertIn("script-src 'none'",html)
  self.assertNotIn('http-equiv="refresh"',html);self.assertNotIn('<base ',html)
 def test_new_pages_available_to_pro_without_new_lock(self):
  from marauder_workspace import WorkspaceGUI
  plugin=types.SimpleNamespace(PLUGIN_API=1,open_feature=Mock())
  with patch.dict(sys.modules,{'marauder_pro':plugin}):app=WorkspaceGUI()
  app.withdraw();app.autoconnect.set(False)
  try:
   app.open_specter();app.open_portal_templates();app.update_idletasks()
   plugin.open_feature.assert_not_called()
   self.assertTrue({'specter','portals'}<=set(app._nav_buttons))
   self.assertIn('Pro',app.title())
   fs=Mock();fs.tree.return_value=[SDEntry('/Rians/Owned Template.html',False,20)]
   fs.stat.return_value='F /Rians/Owned Template.html 20 1790000000'
   def download(remote,local):Path(local).write_text('<h1>Owned test</h1>')
   fs.download.side_effect=download
   def sd_job(work,done,label):
    with ThreadPoolExecutor(max_workers=1) as worker:
     result=worker.submit(work,fs).result(timeout=3)
    done(result)
   app._sd_job=sd_job
   page=app._pages['portals'];page._scan_sd_templates()
   tree=page._portal_tree;tree.selection_set(tree.get_children()[0])
   self.assertEqual(tree.item(tree.selection()[0],'values')[1],'/Rians/Owned Template.html')
   def button(label):
    pending=[page]
    while pending:
     w=pending.pop();pending.extend(w.winfo_children())
     try:
      if w.winfo_class()=='TButton' and w.cget('text')==label:return w
     except Exception:pass
    raise AssertionError(label)
   with patch('webbrowser.open') as browser:
    button('Preview').invoke();browser.assert_called_once()
   app.geometry('1080x720');app.update_idletasks()
   self.assertLessEqual(button('Use SD template').winfo_y()+button('Use SD template').winfo_height(),button('Use SD template').master.winfo_height())
   app.dev=Mock();button('Use SD template').invoke()
   app.dev.send.assert_called_once_with('evilportal -c sethtml "Rians/Owned Template.html"')
   self.assertFalse(app.running)
   app._sd_busy=True
   with patch('marauder_gui.messagebox.showinfo'):
    app._do_send('bt status')
   self.assertEqual(app.dev.send.call_count,1)
   app._sd_busy=False;app._last_running_base='tracker scan 3';app.running=True
   app.stop_running();app.dev.send.assert_called_with('stopble');self.assertFalse(app.running)
   app.dev=None
  finally:app._on_close()

if __name__=='__main__':unittest.main()
