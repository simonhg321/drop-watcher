# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""Infer a maker for existing maker-less URL watches from their keywords, using the
same resolver the signup form uses (maker_resolve.first_maker_in). Confident hits are
set automatically; the rest are queued for an opt-in email. Dry-run by default."""
import maker_resolve


def _infer(keywords):
    """Return a canonical/suggested maker name from a keyword list, or None."""
    r = maker_resolve.first_maker_in(keywords)
    if r['kind'] in ('exact', 'alias'):
        return r['canonical']
    if r['kind'] == 'model':
        return r['suggestion']
    return None


def plan_backfill(db):
    """{'set': {watch_id: maker}, 'email': [watch rows]} — no writes."""
    out = {'set': {}, 'email': []}
    for w in db.get_all_watchers():
        if not w.get('active'):
            continue
        if (w.get('maker') or '').strip():
            continue
        if not (w.get('url') or '').strip():
            continue  # global watches already require a maker
        name = _infer(w.get('keywords'))
        if name:
            out['set'][w['id']] = name
        else:
            out['email'].append(w)
    return out


def apply_backfill(db, plan):
    for wid, name in plan['set'].items():
        db.update_watcher(wid, maker=name)
    return len(plan['set'])
