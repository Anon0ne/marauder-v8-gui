import json,sys,unittest,types
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from marauder_ap_targets import read_ap_snapshot,resolve_clone
from marauder_sdfs import SDError
from marauder_gui import command_runs

class APTargetTests(unittest.TestCase):
 def test_snapshot_and_bssid_remap(self):
  row={'index':1,'ssid':'Owned Lab','bssid':'02:11:22:33:44:55','channel':6,'rssi':-45}
  fs=Mock();fs.line_timeout=1;fs._readline.side_effect=['#aplist','@APLIST '+json.dumps(row),'@APLIST:END 1']
  rows=read_ap_snapshot(fs);fs._start.assert_called_once_with('aplist')
  self.assertEqual(resolve_clone(rows,'4','02:11:22:33:44:55')['index'],'1')
  with self.assertRaises(ValueError):resolve_clone(rows,'4','02:11:22:33:44:66')
  with self.assertRaises(ValueError):resolve_clone(rows,'4')
 def test_incomplete_snapshot_rejected(self):
  fs=Mock();fs.line_timeout=1;fs._readline.side_effect=['@APLIST:END 2']
  with self.assertRaises(SDError):read_ap_snapshot(fs)
 def test_parameterized_jobs_have_stop(self):
  for command in ('iotrecon start','probetwin start','guardian start','apclone -a','apdeauth -a','tracker scan','predator recon'):
   self.assertTrue(command_runs(command),command)
 def test_gui_clone_preserves_template_and_stop_is_visible(self):
  from marauder_workspace import WorkspaceGUI
  with patch.dict(sys.modules,{'marauder_pro':types.SimpleNamespace(PLUGIN_API=1)}):app=WorkspaceGUI()
  app.withdraw();app.autoconnect.set(False)
  try:
   app.update_idletasks();self.assertEqual(app.stop_all_btn.winfo_manager(),'pack')
   app.dev=Mock();app.running=False;app._portal_selected_path='/Rians/Owned Portal.html'
   app._lists['ap']={'4':{'ssid':'Old label','bssid':'02:11:22:33:44:55'}}
   rows={'1':{'index':'1','ssid':'Owned Lab','bssid':'02:11:22:33:44:55','channel':6,'rssi':-45}}
   fs=Mock();fs.stat.return_value='F /Rians/Owned Portal.html 100 1790000000'
   app._sd_job=lambda work,done,label:done(work(fs))
   with patch('marauder_ap_targets.read_ap_snapshot',return_value=rows),patch('marauder_gui.messagebox.askyesno',return_value=True):
    app._do_send('apclone -a 4')
   app.dev.send.assert_called_once_with('apclone -a 1 -b 02:11:22:33:44:55 -w "Rians/Owned Portal.html"')
   self.assertTrue(app.running);app.stop_running();app.dev.send.assert_called_with('stopscan')
   app._track_list_line('ESP-ROM:esp32c5');self.assertFalse(app._lists['ap'])
   app.dev=None
  finally:app._on_close()
if __name__=='__main__':unittest.main()
