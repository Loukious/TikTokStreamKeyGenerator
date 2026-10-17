"""Persist confirmed campaign views, scoped to the authenticated account."""
import json
import os
import tempfile
from pathlib import Path


def _valid_id(value):
    return isinstance(value, str) and value.isascii() and value.isdigit() and bool(value.strip('0'))


def load_viewed_ids(path):
    if not path:
        return set()
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('viewed'), dict):
        return set()
    return {(user, activity) for user, activities in data['viewed'].items()
            if _valid_id(user) and isinstance(activities, list)
            for activity in activities if _valid_id(activity)}


def save_viewed_ids(path, viewed):
    if not path:
        return
    # Merge views saved by another dialog before replacing the file atomically.
    entries = load_viewed_ids(path) | set(viewed)
    accounts = {}
    for user, activity in sorted(entries):
        if _valid_id(user) and _valid_id(activity):
            accounts.setdefault(user, []).append(activity)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=target.parent,
                                         prefix=target.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump({'version': 1, 'viewed': accounts}, stream)
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
