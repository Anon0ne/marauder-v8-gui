"""Authoritative device AP snapshots for actions that depend on volatile indices."""
import json,time,re
from marauder_sdfs import SDError

def read_ap_snapshot(fs):
    fs._start('aplist')
    rows={};deadline=time.monotonic()+fs.line_timeout
    while time.monotonic()<deadline:
        line=fs._readline()
        if line.startswith('@APLIST '):
            row=json.loads(line.split(' ',1)[1]);index=row.get('index');mac=row.get('bssid','')
            if not isinstance(index,int) or index<0 or not re.fullmatch(r'[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}',mac):
                raise SDError('Invalid device AP snapshot')
            row['index']=str(index);row['bssid']=mac.lower();rows[str(index)]=row
        elif line.startswith('@APLIST:END '):
            if int(line.split()[-1])!=len(rows):raise SDError('Incomplete AP snapshot')
            return rows
    raise SDError('Device did not return an AP snapshot. Update to the matching Specter firmware.')

def resolve_clone(rows,index,expected_bssid=''):
    if expected_bssid:
        matches=[row for row in rows.values() if row['bssid'].lower()==expected_bssid.lower()]
        if len(matches)!=1:raise ValueError('That AP is no longer in the device list. Run WiFi Recon again.')
        return matches[0]
    if str(index) not in rows:raise ValueError('No current AP at that index. Run WiFi Recon, stop, then refresh APs.')
    return rows[str(index)]
