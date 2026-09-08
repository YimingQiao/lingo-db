"""Prepare ONLY four empty instance-store disks on a disposable G6 DLAMI."""
import argparse
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--prepare-empty-four-disk-dlami', action='store_true', required=True)
p.parse_args()

def run(*args):
    subprocess.run(args, check=True)

blocks = json.loads(subprocess.check_output(['lsblk','-J','-o','NAME,MODEL,TYPE']))['blockdevices']
devices = sorted(d['name'] for d in blocks if (d.get('model') or '').strip() == 'Amazon EC2 NVMe Instance Storage')
assert devices == ['nvme1n1','nvme2n1','nvme3n1','nvme4n1'], devices
scratch = Path('/opt/dlami/nvme')
assert scratch.is_mount()
source = subprocess.check_output(['findmnt','-n','-o','SOURCE','--target',str(scratch)],text=True).strip()
assert Path(source).resolve() == Path('/dev/vg.01/lv_ephemeral').resolve(), source
volumes = json.loads(subprocess.check_output(['lvs','--reportformat','json','-o','vg_name,lv_name']))['report'][0]['lv']
assert [x['lv_name'] for x in volumes if x['vg_name']=='vg.01'] == ['lv_ephemeral'], volumes
assert {x.name for x in scratch.iterdir()} <= {'lost+found'}
if (scratch/'lost+found').exists():
    assert not list((scratch/'lost+found').iterdir())
pvs = json.loads(subprocess.check_output(['pvs','--reportformat','json','-o','pv_name,vg_name']))['report'][0]['pv']
assert {x['pv_name'] for x in pvs if x['vg_name'] == 'vg.01'} == {'/dev/'+d for d in devices}
run('systemctl','disable','dlami-nvme.service')
run('umount',str(scratch))
run('lvremove','--yes','/dev/vg.01/lv_ephemeral')
run('vgremove','--yes','vg.01')
for i, dev in enumerate(devices):
    run('pvremove','--yes','/dev/'+dev)
    run('mkfs.ext4','-F','-E','lazy_itable_init=0,lazy_journal_init=0','/dev/'+dev)
    mount = Path('/mnt/ssd'+str(i))
    mount.mkdir()
    run('mount','-o','noatime,data=ordered','/dev/'+dev,str(mount))
    run('chown','ubuntu:ubuntu',str(mount))
print(json.dumps({'prepared_devices':devices}))
