"""
Check that every place the version number is written agrees, and, given
a release tag, that they match it. CI runs it on every change, and the
release workflow runs it on the tag before publishing a release.

Run from app/:
    python3 tools/check_version.py            # print the version
    python3 tools/check_version.py v1.0.1     # fail unless every place says 1.0.1

To write the version somewhere new, add the file and a pattern whose
group captures the number to PLACES.
"""

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

PLACES = [
    ("README.md", r"^Version (\d+\.\d+\.\d+)$"),
]


def find_versions(read=None):
    """{file: version, or None where the pattern isn't found}."""
    if read is None:
        def read(name):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                return f.read()
    found = {}
    for name, pattern in PLACES:
        m = re.search(pattern, read(name), re.MULTILINE)
        found[name] = m.group(1) if m else None
    return found


def problems(found, tag=None):
    """What's wrong, as sentences; empty when every place agrees (and
    matches the tag, if given)."""
    out = [f"{name}: no version found" for name, v in found.items() if v is None]
    versions = sorted({v for v in found.values() if v})
    if len(versions) > 1:
        out.append("The places disagree: " + ", ".join(f"{n} says {v}" for n, v in found.items() if v))
    if tag is not None:
        if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
            out.append(f"Tag {tag!r} isn't in the form v1.2.3")
        elif len(versions) == 1 and versions[0] != tag[1:]:
            out.append(f"Tag {tag} doesn't match the version written, {versions[0]}")
    return out


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else None
    found = find_versions()
    errors = problems(found, tag)
    if errors:
        sys.exit("\n".join(errors))
    print(next(iter(found.values())) + (f" matches {tag}" if tag else ""))
