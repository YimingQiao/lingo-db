"""AWS kernel builds nvme_core in: modprobe options alone do not apply."""
from pathlib import Path
import subprocess

Path('/etc/default/grub.d/99-parquet-gds.cfg').write_text(
    'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT nvme_core.multipath=N"\n')
subprocess.run(['update-grub'], check=True)
