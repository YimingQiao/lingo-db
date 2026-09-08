"""ONLY for the newly provisioned disposable DLAMI g6.8xlarge.

Refuses to dismantle a nonempty NVMe LV or touch EBS. Run with sudo.
Requires explicit --prepare-empty-dlami-nvme authorization.
"""
import argparse
import json
from pathlib import Path
import subprocess

p = argparse.ArgumentParser()
p.add_argument('--prepare-empty-dlami-nvme', action='store_true', required=True)
p.parse_args()

def run(*args):
    subprocess.run(args, check=True)

devices = json.loads(subprocess.check_output(['lsblk', '-J', '-o', 'NAME,MODEL,TYPE']))['blockdevices']
nvme = [d['name'] for d in devices if (d.get('model') or '').strip() == 'Amazon EC2 NVMe Instance Storage']
assert set(nvme) == {'nvme1n1', 'nvme2n1'}, nvme
scratch = Path('/opt/dlami/nvme')
assert {p.name for p in scratch.iterdir()} <= {'lost+found'}, 'Existing data; STOP'
assert not list((scratch / 'lost+found').iterdir()), 'Recovery data; STOP'
run('systemctl', 'disable', 'dlami-nvme.service')
run('umount', str(scratch))
run('lvremove', '--yes', '/dev/vg.01/lv_ephemeral')
run('vgremove', '--yes', 'vg.01')
for i, dev in enumerate(['nvme1n1', 'nvme2n1']):
    run('pvremove', '--yes', f'/dev/{dev}')
    run('mkfs.ext4', '-F', '-E', 'lazy_itable_init=0,lazy_journal_init=0', f'/dev/{dev}')
    mount = Path(f'/mnt/ssd{i}')
    mount.mkdir(exist_ok=True)
    run('mount', '-o', 'noatime,data=ordered', f'/dev/{dev}', str(mount))
    run('chown', 'ubuntu:ubuntu', str(mount))
    with Path('/etc/fstab').open('a') as f:
        f.write(f'/dev/{dev} {mount} ext4 noatime,data=ordered,nofail 0 2\n')
# Both are prerequisites for NVIDIA's kernel-native PCI P2PDMA path.
Path('/etc/modprobe.d/parquet-gds.conf').write_text(
    'options nvme_core multipath=N\n'
    'options nvidia NVreg_RegistryDwords="RMForceStaticBar1=1;ForceP2P=0;RmForceDisableIomapWC=1;"\n')
run('update-initramfs', '-u')
# Survives the required reboot; instance shutdown behavior must be terminate.
Path('/etc/systemd/system/parquet-exp-deadline.service').write_text(
    '[Unit]\nDescription=Disposable experiment deadline\n'
    '[Service]\nType=oneshot\nExecStart=/usr/sbin/shutdown -h now\n')
Path('/etc/systemd/system/parquet-exp-deadline.timer').write_text(
    '[Unit]\nDescription=Terminate experiment after 150 minutes of uptime\n'
    '[Timer]\nOnBootSec=150min\nUnit=parquet-exp-deadline.service\n'
    '[Install]\nWantedBy=timers.target\n')
run('systemctl', 'daemon-reload')
run('systemctl', 'enable', 'parquet-exp-deadline.timer')
