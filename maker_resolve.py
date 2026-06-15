# Copyright (c) 2026 Simon SGH — instockornot.club — ELv2 License
"""maker_resolve.py — turn free text into a canonical maker or a suggestion.

Single brain for the signup form and the backfill script. Reads makers.yaml via
config_load. Pure and dependency-light (stdlib difflib only). Never raises."""
import difflib
import re

import paths
from config_load import load_yaml

_PUNCT = re.compile(r"[^a-z0-9 ]+")


def _norm(s):
    return _PUNCT.sub("", (s or "").strip().lower()).strip()


def _indexes(makers_file):
    """Build (alias_to_name, model_to_names, all_keys) from makers.yaml.
    alias_to_name: norm(alias|name) -> canonical Name (exact identity).
    model_to_names: norm(model) -> set(canonical Names) (suggestion identity).
    """
    data = load_yaml(makers_file) or {}
    alias_to_name, model_to_names = {}, {}
    for m in data.get("makers", []) or []:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()
        if not name:
            continue
        keys = [name] + [str(a) for a in (m.get("aliases") or [])]
        for k in keys:
            nk = _norm(k)
            if nk:
                alias_to_name.setdefault(nk, name)
        models = m.get("notable_models") or {}
        if isinstance(models, dict):
            flat = [v for grp in models.values() for v in (grp or [])]
        else:
            flat = models or []
        for mod in flat:
            nmod = _norm(str(mod))
            if nmod:
                model_to_names.setdefault(nmod, set()).add(name)
    return alias_to_name, model_to_names, list(alias_to_name.keys())


def resolve(text, makers_file=None):
    """Return {canonical, suggestion, kind}.
    kind: exact|alias  -> canonical set (confident);
          model|typo   -> suggestion set (needs confirm);
          ambiguous    -> both None (>1 maker);
          unknown      -> both None (store literal as-typed)."""
    makers_file = makers_file or paths.MAKERS_YAML
    raw = (text or "").strip()
    if not raw:
        return {"canonical": None, "suggestion": None, "kind": "unknown"}
    try:
        alias_to_name, model_to_names, all_keys = _indexes(makers_file)
    except Exception:
        return {"canonical": None, "suggestion": None, "kind": "unknown"}
    k = _norm(raw)
    if k in alias_to_name:
        name = alias_to_name[k]
        kind = "exact" if k == _norm(name) else "alias"
        return {"canonical": name, "suggestion": None, "kind": kind}
    if k in model_to_names:
        names = sorted(model_to_names[k])
        if len(names) == 1:
            return {"canonical": None, "suggestion": names[0], "kind": "model"}
        return {"canonical": None, "suggestion": None, "kind": "ambiguous"}
    return {"canonical": None, "suggestion": None, "kind": "unknown"}
