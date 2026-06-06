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
    keywords = []
    for bucket in cool_list.get('keywords', {}).values():
        for kw in bucket:
            keywords.append(kw.lower())
    for maker in makers_config.get('makers', []):
        keywords.append(maker['name'].lower())
        for alias in maker.get('aliases', []):
            keywords.append(alias.lower())
    for collab in makers_config.get('collaborations', []):
        for alias in collab.get('aliases', []):
            keywords.append(alias.lower())
    return list(set(keywords))


def prefilter(text, keywords):
    """Cheap pre-AI screen: does any keyword appear (loose substring) in the page?
    Deliberately broad — precise bounded matching happens later via matching.kw_matches."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)
