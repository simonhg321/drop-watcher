"""Shared config loading + pre-filter for the scrapers.

web_watcher and feed_watcher both load the same YAML config and pre-filter page text
against the same keyword list before paying for an AI call. These were byte-identical
copies in both agents — if they ever drifted, the two would pre-filter differently and
send different traffic to the paid Haiku API. One impl here keeps them in lockstep.

Side-effect free; cheap to import.
"""
import yaml


def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)


def build_keywords(cool_list, makers_config):
    """Flatten cool_list keywords + maker names/aliases + collab aliases into a
    lowercased, de-duped keyword list for the pre-filter."""
    # str()-coerce everything: a YAML token like 229 or 0044 parses as int and would
    # crash .lower(); a collab entry (makers:[...] with no name) would KeyError. One bad
    # config value must never take down the whole watcher.
    keywords = []
    for bucket in (cool_list or {}).get('keywords', {}).values():
        for kw in (bucket or []):
            if str(kw).strip():
                keywords.append(str(kw).lower())
    for maker in (makers_config or {}).get('makers', []) or []:
        if not isinstance(maker, dict):
            continue
        name = maker.get('name')
        if name:
            keywords.append(str(name).lower())
        for alias in (maker.get('aliases') or []):
            if str(alias).strip():
                keywords.append(str(alias).lower())
    for collab in (makers_config or {}).get('collaborations', []) or []:
        for alias in (collab.get('aliases') or []):
            if str(alias).strip():
                keywords.append(str(alias).lower())
    return list(set(keywords))


def prefilter(text, keywords):
    """Cheap pre-AI screen: does any keyword appear (loose substring) in the page?
    Deliberately broad — precise bounded matching happens later via matching.kw_matches."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)
