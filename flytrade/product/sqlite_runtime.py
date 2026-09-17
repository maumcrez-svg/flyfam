"""Load the pinned process-local SQLite before Python's sqlite module is imported.

The Conda extension has an RPATH to its old SQLite. Loading the verified library
by absolute path and SONAME first lets the normal _sqlite3 binding reuse it.
No global Conda files, Python modules or SQL semantics change.
"""
import ctypes
import hashlib
import json
from pathlib import Path
import sys

VERSION='3.51.3'
SOURCE_ID='2026-03-13 10:38:09 737ae4a34738ffa0c3ff7f9bb18df914dd1cad163f28fd6b6e114a344fe6d618'
SOURCE_SHA3='32d5424f97e0a7fc5ed2f6335afbb58be4e0298bd7117a34e39d345ff13d859e'
_handle=None

def activate(library):
 global _handle
 if '_sqlite3' in sys.modules:raise RuntimeError('SQLite must be selected before any database import')
 library=Path(library).resolve(strict=True)
 manifest=json.loads(library.with_name('manifest.json').read_text())
 if manifest.get('version')!=VERSION or manifest.get('source_id')!=SOURCE_ID or manifest.get('source_sha3_256')!=SOURCE_SHA3:
  raise RuntimeError('Viewer SQLite manifest does not match the pinned official release')
 if hashlib.sha256(library.read_bytes()).hexdigest()!=manifest.get('library_sha256'):
  raise RuntimeError('Viewer SQLite binary checksum mismatch')
 _handle=ctypes.CDLL(str(library),mode=ctypes.RTLD_GLOBAL)
 import sqlite3
 with sqlite3.connect(':memory:') as db:source_id=db.execute('SELECT sqlite_source_id()').fetchone()[0]
 db.close()
 if sqlite3.sqlite_version!=VERSION or source_id!=SOURCE_ID or sqlite3.threadsafety!=3:
  raise RuntimeError('Viewer loaded an unexpected SQLite library; refusing unsafe fallback')
 return {'sqlite_version':sqlite3.sqlite_version,'sqlite_source_id':source_id,'sqlite_threadsafety':sqlite3.threadsafety}


def require_fixed_runtime(component='Viewer', launcher='product/run_viewer.py'):
 import sqlite3
 if sqlite3.sqlite_version_info < (3,51,3):
  raise RuntimeError(f'{component} requires SQLite >=3.51.3. Start {launcher} with the verified --sqlite-library; do not run the affected Conda SQLite.')
