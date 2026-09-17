import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('spectacle_server', Path(__file__).parents[1] / 'serve.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Feed = module.Feed


def state(root, seq):
    (root / 'state.json').write_text(json.dumps({'version': 'pons-live-state-1', 'seq': seq}))


def event(seq, kind='HEARTBEAT', **fields):
    return {'seq': seq, 'kind': kind, **fields}


def test_atomic_state_caps_journal_and_partial_line_is_retried(tmp_path):
    state(tmp_path, 1)
    path = tmp_path / 'events-2026-09-13.jsonl'
    second = json.dumps(event(2)).encode()
    path.write_bytes(json.dumps(event(1)).encode()+b'\n'+second[:10])
    feed = Feed(tmp_path)
    assert [e['seq'] for e in feed.read()['events']] == [1]
    with path.open('ab') as file:
        file.write(second[10:]+b'\n')
    assert feed.read(1)['events'] == []
    state(tmp_path, 2)
    assert [e['seq'] for e in feed.read(1)['events']] == [2]
    assert feed.read(2)['events'] == []


def test_midnight_and_replay_include_real_choice_through_credit(tmp_path):
    events = [event(1, 'SNIFF', tick=1, candidates=[{'token': 'A'}]),
              event(2, 'PICK', tick=1, context='FLAT', token='A'),
              event(3, 'OPEN', tick=1, episode_id=123, token='A'),
              event(4, 'PICK', tick=2, context='HELD', episode_id=456, token='A'),
              event(5, 'CLOSE', tick=3, episode_id=123, token='A'),
              event(6, 'CREDIT', tick=3, episode_id=123, token='A')]
    (tmp_path/'events-2026-09-13.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events[:3]))
    (tmp_path/'events-2026-09-14.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events[3:]))
    state(tmp_path, 6)
    feed=Feed(tmp_path)
    assert feed.replay('123')['events'] == events
    assert feed.read()['last_sniff']['candidates'] == [{'token':'A'}]
    assert feed.read(999)['reset'] is True
    feed.events = module.deque(e for e in feed.events if e['seq'] != 4)
    try:
        feed.replay('123')
        assert False
    except LookupError:
        pass


def test_read_only_and_unknown_replay(tmp_path):
    state(tmp_path, 1)
    path=tmp_path/'events-2026-09-13.jsonl'
    path.write_text(json.dumps(event(1))+'\n')
    before={p.name:p.read_bytes() for p in tmp_path.iterdir()}
    feed=Feed(tmp_path)
    feed.read()
    try:
        feed.replay('missing')
        assert False
    except LookupError:
        pass
    assert {p.name:p.read_bytes() for p in tmp_path.iterdir()} == before
