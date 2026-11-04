"""
Save what ingest makes of each book (chunk counts and a fingerprint of
every chunk's text, plus recipe titles, pages, ingredients and groups for
books with a profile), then check later changes against it.
Runs the whole structure step without embedding or touching Chroma, so
it takes seconds and works anywhere the PDFs are.

Run from app/ (either form works):
    python3 tools/diagnostics/structure_baseline.py save [BOOK_TITLE ...]
    python3 tools/diagnostics/structure_baseline.py compare [BOOK_TITLE ...]

With no titles it covers all 16 books, so a change to the shared rules
shows up in books without a profile too (as changed chunk text). The
baseline and the full diff quote the books, so both go in
testing/one_off/baseline/ (git-ignored). compare prints a short summary
per book; the details are in <book>_diff.txt next to the baseline.
"""

import hashlib
import json
import os
import sys
from collections import Counter, defaultdict

# Lets this run as a plain file path, not only with -m: put app/ on the
# import path so the shared modules can be found.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from common.config import BOOK_FILES, PROJECT_ROOT, book_pdf_path  # noqa: E402
from ingest_utils.pdf_text import build_line_stream  # noqa: E402
from ingest_utils.structure import structure_book  # noqa: E402
from match_utils.recipe_index import index_entry  # noqa: E402

BASELINE_DIR = os.path.join(PROJECT_ROOT, "testing", "one_off", "baseline")


def slug(book_title):
    return "".join(c if c.isalnum() else "_" for c in book_title.lower()).strip("_")


def snapshot(book_title):
    """Everything worth comparing about one book's structure, as plain
    JSON-able data."""
    pdf_path = book_pdf_path(book_title)
    records, page_count, _ = structure_book(pdf_path, book_title)

    recipes = defaultdict(lambda: {"parts": []})
    for text, content_type, page_num, confirmed, extra in records:
        if content_type != "recipe":
            continue
        r = recipes[extra["recipe_id"]]
        r["parts"].append((extra["part"], text))
        if extra["part"] == 0:
            r["page"] = page_num if confirmed else 0
            r["page_confirmed"] = confirmed

    out = []
    for recipe_id, r in recipes.items():
        text = "\n".join(t for _, t in sorted(r["parts"]))
        entry = index_entry(recipe_id, {"book": book_title, "text": text,
                                        "page": r["page"], "page_confirmed": r["page_confirmed"]})
        out.append({
            "title": entry["title"],
            "page": entry["page"],
            "part_count": len(r["parts"]),
            "chars": len(text),
            "text_hash": hashlib.sha1(text.encode("utf-8")).hexdigest()[:12],
            "ingredients": [i["name"] for i in entry["ingredients"]],
            "optional": [i["name"] for i in entry["optional"]],
            "sub_recipes": entry["sub_recipes"],
            "your_choice": entry["your_choice"],
            "groups": entry["groups"],
        })
    # One fingerprint per content type over every chunk's text, in order,
    # so a book with no profile (all "unknown" chunks) is still checked.
    by_type = defaultdict(hashlib.sha1)
    for text, content_type, _, _, _ in records:
        by_type[content_type].update(text.encode("utf-8") + b"\0")
    return {
        "book": book_title,
        "lines": len(build_line_stream(pdf_path)[0]),
        "pages": page_count,
        "chunks": Counter(rec[1] for rec in records),
        "chunk_hashes": {t: h.hexdigest()[:12] for t, h in sorted(by_type.items())},
        "recipes": out,
    }


def keyed(recipes):
    """Recipes keyed by (title, page), with a counter on repeats so two
    recipes sharing a title on one page don't collide."""
    seen = Counter()
    result = {}
    for r in recipes:
        base = (r["title"], r["page"])
        seen[base] += 1
        result[base + (seen[base],)] = r
    return result


def compare(old, new):
    """(summary lines, detail lines) describing how new differs from old."""
    summary, detail = [], []
    for field in ("pages", "lines"):
        if old[field] != new[field]:
            summary.append(f"{field}: {old[field]} -> {new[field]}")
    if dict(old["chunks"]) != dict(new["chunks"]):
        summary.append(f"chunks: {dict(old['chunks'])} -> {dict(new['chunks'])}")
    old_h, new_h = old.get("chunk_hashes"), new["chunk_hashes"]
    if old_h is not None:
        changed_types = sorted(t for t in old_h.keys() | new_h.keys() if old_h.get(t) != new_h.get(t))
        if changed_types:
            summary.append("chunk text changed: " + ", ".join(changed_types))

    old_k, new_k = keyed(old["recipes"]), keyed(new["recipes"])
    gone = [k for k in old_k if k not in new_k]
    added = [k for k in new_k if k not in old_k]
    if gone or added:
        summary.append(f"recipes: {len(old_k)} -> {len(new_k)} "
                       f"({len(gone)} gone, {len(added)} new)")
    for k in gone:
        detail.append(f"GONE  p{k[1]}  {k[0]}  ({len(old_k[k]['ingredients'])} ingredients)")
    for k in added:
        detail.append(f"NEW   p{k[1]}  {k[0]}  ({len(new_k[k]['ingredients'])} ingredients)")

    changed = Counter()
    for k in old_k.keys() & new_k.keys():
        o, n = old_k[k], new_k[k]
        notes = []
        if o["text_hash"] != n["text_hash"]:
            changed["text"] += 1
            notes.append(f"text {o['chars']} -> {n['chars']} chars")
        for field in ("ingredients", "optional", "sub_recipes", "your_choice"):
            if o[field] != n[field]:
                changed[field] += 1
                lost = [x for x in o[field] if x not in n[field]]
                got = [x for x in n[field] if x not in o[field]]
                notes.append(f"{field}: -{lost} +{got}" if lost or got else f"{field}: reordered")
        if o["groups"] != n["groups"]:
            changed["groups"] += 1
            notes.append(f"groups: {o['groups']} -> {n['groups']}")
        if notes:
            detail.append(f"CHANGED  p{k[1]}  {k[0]}")
            detail.extend(f"    {note}" for note in notes)
    if changed:
        summary.append("changed recipes: " + ", ".join(f"{v} {f}" for f, v in sorted(changed.items())))
    elif not summary:
        summary.append(f"no changes ({len(new_k)} recipes)" if new_k else "no changes")
    return summary, detail


def main(argv):
    if not argv or argv[0] not in ("save", "compare"):
        sys.exit(__doc__)
    action, titles = argv[0], argv[1:]
    if not titles:
        titles = list(BOOK_FILES)
    os.makedirs(BASELINE_DIR, exist_ok=True)

    for title in titles:
        if title not in BOOK_FILES:
            sys.exit(f"{title!r} isn't in common/config.BOOK_FILES")
        path = os.path.join(BASELINE_DIR, slug(title) + ".json")
        new = snapshot(title)
        print(f"=== {title} ===")
        if action == "save":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(new, f, indent=1, ensure_ascii=False)
            print(f"saved {len(new['recipes'])} recipes, {dict(new['chunks'])} chunks to {path}")
            continue
        if not os.path.isfile(path):
            print(f"no baseline at {path}, run save first")
            continue
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        summary, detail = compare(old, new)
        diff_path = os.path.join(BASELINE_DIR, slug(title) + "_diff.txt")
        with open(diff_path, "w", encoding="utf-8") as f:
            f.write("\n".join(summary + [""] + detail) + "\n")
        print("\n".join(summary))
        if detail:
            print(f"{len(detail)} detail lines in {diff_path}")


if __name__ == "__main__":
    main(sys.argv[1:])
