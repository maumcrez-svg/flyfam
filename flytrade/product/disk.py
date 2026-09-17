"""Conservative disk guard. No deletion and no trading/brain dependencies."""
import os
from pathlib import Path
import shutil
import time


class DiskGuard:
    def __init__(self, roots, *, now=None, interval=10, warning_bytes=5*1024**3,
                 hard_bytes=1024**3, usage=shutil.disk_usage):
        resolved = sorted({Path(p).resolve() for p in roots}, key=lambda p:len(p.parts))
        self.roots = []
        for path in resolved:
            if not any(path.is_relative_to(parent) for parent in self.roots):
                self.roots.append(path)
        self.now = now or time.monotonic
        self.interval = interval
        self.warning_bytes = int(warning_bytes)
        self.hard_bytes = int(hard_bytes)
        if not 0 < self.hard_bytes < self.warning_bytes:
            raise ValueError('Disk warning must precede hard safety threshold')
        self.usage = usage
        self.last = None
        self.snapshot = None
        self.working_bytes = 0

    def reserve_working_space(self, required_bytes):
        self.working_bytes = max(0, int(required_bytes))
        self.last = None

    def sample(self, *, force=False):
        now = self.now()
        if not force and self.last is not None and now-self.last < self.interval:
            return self.snapshot
        files = total = 0
        segments = []
        for root in self.roots:
            if not root.exists():
                continue
            for directory, subdirs, names in os.walk(root, followlinks=False):
                subdirs[:] = [name for name in subdirs if not (Path(directory)/name).is_symlink()]
                for name in names:
                    path = Path(directory)/name
                    try:
                        if path.is_symlink():
                            continue
                        size = path.stat().st_size
                    except FileNotFoundError:
                        continue
                    total += size
                    files += 1
                    if name in ('raw.jsonl','events.jsonl','headers.jsonl'):
                        segments.append({'segment':path.parent.name,'file':name,'bytes':size})
        disks = []
        for root in self.roots:
            probe = root
            while not probe.exists():
                probe = probe.parent
            usage = self.usage(probe)
            disks.append({'free_bytes':usage.free,'total_bytes':usage.total})
        free = min(d['free_bytes'] for d in disks)
        status = 'HARD_STOP' if free <= self.hard_bytes+self.working_bytes else 'WARNING' if free <= self.warning_bytes else 'OK'
        self.snapshot = {'status':status,'data_bytes':total,'files':files,
                         'free_bytes':free,'warning_bytes':self.warning_bytes,
                         'hard_bytes':self.hard_bytes,'reserved_working_bytes':self.working_bytes,'segments':segments[:100],
                         'segments_truncated':len(segments)>100,
                         'sampled_epoch':int(time.time()),
                         'action':'preserve state and stop collection' if status=='HARD_STOP' else None}
        self.last = now
        return self.snapshot

    def stop_reason(self):
        state = self.sample()
        if state['status'] == 'HARD_STOP':
            return ('DISK_SAFETY_STOP', f"free disk {state['free_bytes']} bytes below safety floor plus required working space")
        return None
