"""Start the Bag Room clock/indexer with the verified SQLite runtime."""
import argparse
import json
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flytrade.product.sqlite_runtime import activate


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--sqlite-library', required=True)
    parser.add_argument('--verify-runtime', action='store_true')
    args, worker_args = parser.parse_known_args()
    try:
        runtime = activate(args.sqlite_library)
    except Exception as error:
        raise SystemExit('Bag Room runtime rejected: ' + str(error))
    if args.verify_runtime:
        print(json.dumps(runtime))
        return
    print('[bag-runtime] SQLite ' + runtime['sqlite_version'] + '; checksum verified', flush=True)
    sys.argv = ['flytrade.bags.worker', *worker_args]
    runpy.run_module('flytrade.bags.worker', run_name='__main__')


if __name__ == '__main__':
    main()
