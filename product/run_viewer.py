"""Start only the spectator with its verified SQLite runtime."""
import argparse,json,runpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from flytrade.product.sqlite_runtime import activate

def main():
 p=argparse.ArgumentParser(add_help=False)
 p.add_argument('--sqlite-library',required=True)
 p.add_argument('--verify-runtime',action='store_true')
 args,viewer_args=p.parse_known_args()
 try:runtime=activate(args.sqlite_library)
 except Exception as error:raise SystemExit('Viewer runtime rejected: '+str(error))
 if args.verify_runtime:print(json.dumps(runtime));return
 print('[viewer-runtime] SQLite '+runtime['sqlite_version']+'; checksum verified',flush=True)
 sys.argv=['flytrade.product.api',*viewer_args]
 runpy.run_module('flytrade.product.api',run_name='__main__')
if __name__=='__main__':main()
