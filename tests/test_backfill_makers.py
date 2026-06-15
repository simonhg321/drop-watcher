import os, tempfile, importlib


def _fresh():
    d = tempfile.mkdtemp(); os.environ['DW_DB'] = os.path.join(d, 't.db')
    import db; importlib.reload(db)
    import backfill_makers; importlib.reload(backfill_makers)
    return db, backfill_makers


def test_infers_unambiguous_and_skips_ambiguous():
    db, bf = _fresh()
    db.add_watcher({'id': 'w1', 'email': 'a@b.com', 'url': 'https://x.com',
                    'keywords': 'crk', 'maker': '', 'unsubscribe_token': 't1',
                    'active': 1, 'created': '2026-06-12T00:00:00+00:00'})
    db.add_watcher({'id': 'w2', 'email': 'a@b.com', 'url': 'https://y.com',
                    'keywords': 'pocket knife', 'maker': '', 'unsubscribe_token': 't2',
                    'active': 1, 'created': '2026-06-12T00:00:00+00:00'})
    plan = bf.plan_backfill(db)
    assert plan['set']['w1'] == 'Chris Reeve Knives'
    assert any(w['id'] == 'w2' for w in plan['email'])
    assert (db.get_watcher_by_id('w1')['maker'] or '') == ''   # dry-run: no write


def test_apply_writes_inferred_maker():
    db, bf = _fresh()
    db.add_watcher({'id': 'w1', 'email': 'a@b.com', 'url': 'https://x.com',
                    'keywords': 'crk', 'maker': '', 'unsubscribe_token': 't1',
                    'active': 1, 'created': '2026-06-12T00:00:00+00:00'})
    n = bf.apply_backfill(db, bf.plan_backfill(db))
    assert n == 1
    assert db.get_watcher_by_id('w1')['maker'] == 'Chris Reeve Knives'


def test_global_and_already_makered_watches_are_skipped():
    db, bf = _fresh()
    db.add_watcher({'id': 'g1', 'email': 'a@b.com', 'url': '', 'keywords': 'crk',
                    'maker': 'Chris Reeve Knives', 'unsubscribe_token': 't3',
                    'active': 1, 'created': '2026-06-12T00:00:00+00:00'})
    db.add_watcher({'id': 'u1', 'email': 'a@b.com', 'url': 'https://z.com',
                    'keywords': 'crk', 'maker': 'Already Set', 'unsubscribe_token': 't4',
                    'active': 1, 'created': '2026-06-12T00:00:00+00:00'})
    plan = bf.plan_backfill(db)
    assert 'g1' not in plan['set'] and not any(w['id']=='g1' for w in plan['email'])
    assert 'u1' not in plan['set'] and not any(w['id']=='u1' for w in plan['email'])
