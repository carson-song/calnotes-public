"""The local vault: the only place that maps placeholders back to real people, orgs and events.

Stays on the machine (vault/ is git-ignored). The frontier side sees handles like `h_3fa9c01b`
and placeholders like `[PERSON_2]`, never the mapping.
"""
import hashlib
import hmac
import json
import re
import secrets
from pathlib import Path

PLACEHOLDER = re.compile(r"\[(PERSON|ORG)_\d+\]")
HANDLE = re.compile(r"\bh_[0-9a-f]{10}\b")


def _norm(name: str) -> str:
    return " ".join(name.lower().split())


class Vault:
    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.exists():
            d = json.loads(self.path.read_text())
        else:
            d = {"secret": secrets.token_hex(16), "people": {}, "orgs": {}, "handles": {}}
        self.secret = bytes.fromhex(d["secret"])
        self.people: dict[str, str] = d["people"]    # "ben okafor" -> "[PERSON_3]"
        self.orgs: dict[str, str] = d["orgs"]        # "lumenware" -> "[ORG_1]"
        self.handles: dict[str, str] = d["handles"]  # "h_..." -> source event id

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"secret": self.secret.hex(), "people": self.people, "orgs": self.orgs, "handles": self.handles}
        self.path.write_text(json.dumps(data, indent=1))

    # --- forward: real -> opaque ---------------------------------------------
    def handle(self, item_id: str) -> str:
        """Stable per vault, but unlinkable to the Google id without the local secret."""
        h = "h_" + hmac.new(self.secret, item_id.encode(), hashlib.sha256).hexdigest()[:10]
        self.handles[h] = item_id
        return h

    def _token(self, table: dict, kind: str, name: str) -> str:
        key = _norm(name)
        if key not in table:
            table[key] = f"[{kind}_{len(table) + 1}]"
        return table[key]

    def person(self, name: str) -> str:
        return self._token(self.people, "PERSON", name)

    def org(self, name: str) -> str:
        return self._token(self.orgs, "ORG", name)

    def pseudonymize(self, text: str, people=(), orgs=()) -> str:
        """Replace every known person and org in text with its placeholder.

        Full names first, then the parts of multi-word names ("Ben Okafor" also covers a bare "Okafor").
        """
        for n in people:
            self.person(n)
        for o in orgs:
            self.org(o)
        targets = {}
        for name, tok in self.people.items():
            targets[name] = tok
            for part in name.split():
                if len(part) >= 3 and part not in targets:
                    targets[part] = tok
        for name, tok in self.orgs.items():
            targets.setdefault(name, tok)
        for name in sorted(targets, key=len, reverse=True):
            text = re.sub(rf"\b{re.escape(name)}\b", targets[name], text, flags=re.IGNORECASE)
        return text

    def real_names(self) -> set[str]:
        names = set(self.people) | set(self.orgs)
        names |= {p for n in self.people for p in n.split() if len(p) >= 3}
        return names

    # --- backward: opaque -> real (local only, just before an action runs) ---------
    def reidentify(self, obj):
        rev = {tok: name for name, tok in self.people.items()}
        rev.update({tok: name for name, tok in self.orgs.items()})

        def fix(s: str) -> str:
            s = PLACEHOLDER.sub(lambda m: rev.get(m.group(0), m.group(0)), s)
            return HANDLE.sub(lambda m: self.handles.get(m.group(0), m.group(0)), s)

        if isinstance(obj, str):
            return fix(obj)
        if isinstance(obj, list):
            return [self.reidentify(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.reidentify(v) for k, v in obj.items()}
        return obj
