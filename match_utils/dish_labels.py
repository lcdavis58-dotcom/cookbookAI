"""
Dish types for every recipe ("cookie", "soup", "pie"), so a request for a
dish finds recipes whose titles don't say what they are ("Brown Butter
Snickerdoodles" is a cookie, "Chicken Pot Pie" is a pie and a chicken
dish).

The chat model labels each recipe once, when the recipe index is built,
choosing only from word_lists/universal/dish_types.json; anything else
it says is dropped. When the model gives no type (or can't be reached),
a title whose last word names a type gets that type (title_dishes):
"...Snickerdoodles" is a cookie. Only then: titles mislead as often as
they help ("Potato Cake" isn't a cake, "Quick Jus for Roasted Chicken"
is a sauce), and with the model's types it spoiled 11 recipes of the
hand-checked key for every one it fixed (2026-11-25). A type's
"keywords" are specific foods that mean it anywhere in a title, and are
always added ("crepe" is a pancake, "salmon" seafood; title_keywords).
A type's "implies" are added too (a chicken dish is a meat dish).

A type with "needs_name" is kept only when its name or one of its
title words is in the recipe's title or chapter: every doughnut in the
books says so, and the model gave "doughnut" to croissants, kolaches and
a cubed steak (2026-11-25).

The model's labels are kept in DISH_LABELS_PATH with a hash of what it
was shown, so a rebuild only asks about recipes that are new or changed.
Changing the prompt or the model relabels everything (about 80 minutes
with qwen2.5:14b). Changing one type's "about" asks again only the
recipes that have that type now or whose titles name it: a fix to one
type takes minutes, not a full relabel. Its other fields (title words,
keywords, implies, needs_name) aren't shown to the model, so changing
them asks nothing again. If the model
can't be reached, the labels already kept are used and the rest of the
recipes get their title types only, with a warning: building the index
never fails because the model is down.

Last, word_lists/universal/dish_label_overrides.json sets the types of
recipes found wrong in real use (her flags): they replace whatever the
model and the rules gave, and survive every relabel (load_overrides).

tools/diagnostics/dish_labels.py shows how well the labels came out.
"""

import functools
import hashlib
import json
import os
import re

from common import models
from common.config import CHAT_MODEL, DISH_LABELS_PATH, LABEL_MODEL
from common.word_list_loader import load_universal
from query_utils.title_lookup import title_tokens, word_forms

# Recipes per model call. Batches of 20 mixed recipes up (a cake labeled
# a cookie, fried chicken a vegetable side: a neighbour's labels), and
# one at a time was right far more often, and no slower: 2,700 recipes
# in about 11 minutes on this PC's GPU (measured 2026-11-24).
BATCH_SIZE = 1
# Ingredients shown per recipe: enough to tell a savory pie from a
# sweet one, short enough to keep the prompt small.
INGREDIENTS_SHOWN = 8
MAX_TYPES = 3
# How often to print how far it's got, in recipes.
PROGRESS_EVERY = 200
# A cached file in this shape; bump it if the shape changes.
CACHE_FORMAT = 2

_TAIL_RE = re.compile(r"\s+with\s+.*$|\([^)]*\)", re.I)

PROMPT = """You label recipes with dish types, for a cookbook search.
Choose each recipe's types ONLY from this list (name: what it covers):

{types}

Give each recipe 1 to {most} types, the ones a cook would look for it
under: "Chicken Pot Pie" is ["pie", "chicken"], "Brown Butter
Snickerdoodles" is ["cookie"]. If no type fits, give [].

Label a recipe by what the dish is and how it's served, never by one
ingredient it happens to use: a potato salad dressed with mayonnaise is
a salad and a potato dish, not a condiment.

Reply with a JSON object mapping each recipe's number to its list of
types, e.g. {{"1": ["cookie"], "2": ["soup", "beans"]}}."""


def load_types(path=None):
    """{type: {"about", "title_words"}} from dish_types.json."""
    if path:
        with open(path, encoding="utf-8") as f:
            return json.load(f)["types"]
    return load_universal("dish_types.json", {}).get("types", {})


def _hash(value):
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def prompt_hash():
    """Changes with the prompt or the batch size: every label is asked again."""
    return _hash([PROMPT, BATCH_SIZE])


def type_hashes(types):
    """{type: hash of its "about"}, the only part of a type the model is
    shown. A type whose hash changes (or that's added or removed) has its
    recipes asked again (see label_dishes)."""
    return {name: _hash(info.get("about", "")) for name, info in types.items()}


def _names(info, name):
    return [name] + info.get("title_words", []) + info.get("keywords", [])


def _named_in(text, words_wanted):
    """Whether any of words_wanted (each maybe several words) is in text."""
    words = set()
    for w in title_tokens(text or ""):
        words |= word_forms(w)
    wanted = [title_tokens(t) for t in words_wanted]
    return any(parts and all(word_forms(k) & words for k in parts) for parts in wanted)


def title_names(entry, types):
    """The types whose name, title words or keywords are anywhere in the
    title: the recipes worth asking again when one of them changes."""
    title = entry.get("title") or ""
    return {name for name, info in types.items() if _named_in(title, _names(info, name))}


def keep_named(labels, entry, types):
    """labels without the "needs_name" types its title and chapter don't
    name."""
    text = f"{entry.get('title') or ''} {entry.get('chapter') or ''}"
    return {label for label in labels
            if not (types.get(label) or {}).get("needs_name") or _named_in(text, _names(types[label], label))}


def _last_word(title):
    words = title_tokens(_TAIL_RE.sub("", title or "")) or title_tokens(title or "")
    return words[-1] if words else ""


def title_dishes(entry, types):
    """The types a title names by its last word, before any "with ..."
    tail: "Chewy Sugar Cookies" -> ["cookie"]."""
    last = _last_word(entry.get("match_title") or entry.get("title"))
    if not last:
        return []
    forms = word_forms(last)
    return sorted(name for name, info in types.items()
                  if any(word_forms(w) & forms for w in [name] + info.get("title_words", []) if " " not in w))


def with_implied(labels, types):
    """labels plus what they imply (dish_types.json "implies"): a chicken
    dish is a meat dish too. Sorted."""
    out = set(labels)
    for label in labels:
        out |= set((types.get(label) or {}).get("implies", []))
    return sorted(out & set(types))


# Whether the model is shown a recipe's chapter and headnote too. Tested
# 2026-11-25 against the hand-checked key (testing/evals/
# dish_label_key.json) with qwen2.5:14b: title and ingredients 84% with
# at least one right type, plus the chapter 83%, plus the headnote 82%,
# and the chapter pulled in wrong types (rosti from a breakfast chapter
# labeled "breakfast"). Off until a test shows they help.
SHOW_CHAPTER = False
SHOW_HEADNOTE = False


def title_keywords(entry, types):
    """The types a title names by one of their "keywords", anywhere in
    it: "Crispy Salmon Cakes" -> ["seafood"]."""
    words = set()
    for w in title_tokens(entry.get("title") or ""):
        words |= word_forms(w)
    return sorted(name for name, info in types.items()
                  if any(word_forms(k) & words for t in info.get("keywords", []) for k in title_tokens(t)))


def shown(entry, chapter=None, note=None):
    """What the model is shown about a recipe, one line: its title, book,
    first ingredients, and, when SHOW_CHAPTER / SHOW_HEADNOTE (or the
    arguments) say so, its chapter (match_utils/chapters.py) and the start
    of its headnote (headnote(), when the build passes the recipe text)."""
    chapter = SHOW_CHAPTER if chapter is None else chapter
    note = SHOW_HEADNOTE if note is None else note
    names = [i["name"] for i in entry.get("ingredients", [])][:INGREDIENTS_SHOWN]
    line = f"{entry['title']} ({entry['book']})"
    if chapter and entry.get("chapter"):
        line += f" - chapter: {entry['chapter']}"
    if names:
        line += " - ingredients: " + ", ".join(names)
    if note and entry.get("headnote"):
        line += f' - the book says: "{entry["headnote"]}"'
    return line


# Where a recipe's headnote ends: its first ingredient.
_HEADNOTE_END_RE = re.compile(r"^\s*(?:[\d½¼¾⅓⅔⅛⅜⅝⅞]|ingredients\b)", re.I)
# Yield and time lines some books print before the headnote ("SERVES 2",
# "MAKES: 4 servings TIME: 30 minutes", "WHY THIS RECIPE WORKS:"): left
# out, and what follows them on the line kept.
_NOT_HEADNOTE_RE = re.compile(r"^(?:(?:serves|makes|yield|yields)\b:?\s*[\d½¼¾⅓⅔ -]*(?:to [\d]+)?\s*"
                              r"(?:servings?|cookies|pieces|cups?|dozen|loaves|loaf)?\s*|"
                              r"(?:active |total |prep )?time:\s*.*?\b(?:minutes?|hours?|days?)\b(?:\s+(?:plus|or|to|and)\s+.*?"
                              r"\b(?:minutes?|hours?|days?)\b)*[,.]?\s*|why this recipe works:\s*)+", re.I)
HEADNOTE_CHARS = 400


def headnote(text, title=""):
    """The start of what the book says about a recipe before its yield
    or ingredients, at most HEADNOTE_CHARS, cut at a word; "" if there's
    none. Only the headnote: the method's passing mentions of an
    ingredient are what the labels shouldn't go by."""
    lines = (text or "").splitlines()
    title_key = " ".join(title.lower().split())
    words, started = [], False
    for line in lines[1:] if lines else []:
        line = line.strip()
        if not line or (not started and " ".join(line.lower().split()) == title_key):
            continue
        if _HEADNOTE_END_RE.match(line):
            break
        if _NOT_HEADNOTE_RE.match(line):
            line = _NOT_HEADNOTE_RE.sub("", line).strip()
            if not line:
                continue
        started = True
        words += line.split()
        if sum(len(w) + 1 for w in words) > HEADNOTE_CHARS:
            break
    out = ""
    for w in words:
        if len(out) + len(w) + 1 > HEADNOTE_CHARS:
            return out.rstrip(" ,;:") + "..."
        out = f"{out} {w}".strip()
    return out


def entry_hash(entry):
    return hashlib.sha1(shown(entry).encode("utf-8"), usedforsecurity=False).hexdigest()[:12]


def clean(labels, types):
    """The model's answer for one recipe, kept to known types, at most
    MAX_TYPES, in its order."""
    if isinstance(labels, str):
        labels = [labels]
    if not isinstance(labels, list):
        return []
    known, out = {t.lower(): t for t in types}, []
    for label in labels:
        name = known.get(str(label).strip().lower())
        if name and name not in out:
            out.append(name)
    return out[:MAX_TYPES]


def _system_prompt(types):
    lines = "\n".join(f"- {name}: {info.get('about', '')}" for name, info in types.items())
    return PROMPT.format(types=lines, most=MAX_TYPES)


def ask_model(batch, types, model=None):
    """{recipe_id: [types]} for a batch of entries, from one model call.
    A recipe missing from the reply is left out; an unreadable reply
    raises ValueError."""
    numbered = "\n".join(f"{n}. {shown(e)}" for n, e in enumerate(batch, 1))
    response, _ = models.chat(
        "dish labels",
        messages=[{"role": "system", "content": _system_prompt(types)},
                  {"role": "user", "content": numbered}],
        options={"temperature": 0},
        format="json",
        model=model,
    )
    reply = json.loads(response["message"]["content"])
    if not isinstance(reply, dict):
        raise ValueError("not a JSON object")
    lists = [v for v in reply.values() if isinstance(v, (list, str))]
    if len(batch) == 1 and "1" not in reply and len(lists) == 1:
        # One recipe, answered under some other key ({"labels": [...]}).
        return {batch[0]["recipe_id"]: clean(lists[0], types)}
    return {e["recipe_id"]: clean(reply[str(n)], types)
            for n, e in enumerate(batch, 1) if str(n) in reply}


def load_cache(path=DISH_LABELS_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return {}
    return data if data.get("format") == CACHE_FORMAT else {}


def save_cache(cache, path=DISH_LABELS_PATH):
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _label_batch(batch, types, ask):
    """The model's labels for a batch, retrying one at a time if the
    batch reply can't be read or leaves recipes out."""
    try:
        found = ask(batch, types)
    except ValueError:
        found = {}
    for entry in batch:
        if entry["recipe_id"] not in found and len(batch) > 1:
            try:
                found.update(ask([entry], types))
            except ValueError:
                pass
        # Still no answer: no labels from the model, only the title's.
        found.setdefault(entry["recipe_id"], [])
    return found


def label_model(log=print):
    """LABEL_MODEL, or CHAT_MODEL (with a warning) when it isn't pulled."""
    if LABEL_MODEL != CHAT_MODEL and models.installed(LABEL_MODEL) is False:
        log(f"Warning: {LABEL_MODEL} isn't pulled (ollama pull {LABEL_MODEL}), so the dish types are "
            f"labeled with {CHAT_MODEL}, which gets more of them wrong.")
        return CHAT_MODEL
    return LABEL_MODEL


def _override_key(title, book):
    return (" ".join((title or "").lower().split()), book or "")


def load_overrides(path=None):
    """{(title, book): [types]} from dish_label_overrides.json: recipes
    whose types were set by hand after a flag. Matched on the title,
    case and spacing aside, so two recipes of one title in one book get
    the same types."""
    if path:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = load_universal("dish_label_overrides.json", {})
    return {_override_key(r["title"], r["book"]): list(r["types"]) for r in data.get("recipes", [])}


def override_for(entry, overrides):
    return overrides.get(_override_key(entry.get("title"), entry.get("book")))


def label_dishes(entries, path=DISH_LABELS_PATH, ask=ask_model, types=None, log=print, model=None,
                 overrides=None):
    """Sets entry["dishes"] on every entry: the model's types (kept or
    newly asked; the title's when it gave none) plus keywords and what
    they imply, or the types in overrides (default: load_overrides())
    for a recipe listed there. model defaults to label_model(). Returns {"asked",
    "kept", "missing"}: how many recipes the model labeled now, how many
    kept their saved labels, and how many have none from the model (it
    was down)."""
    types = load_types() if types is None else types
    overrides = load_overrides() if overrides is None else overrides
    if model is None:
        model = label_model(log) if ask is ask_model else LABEL_MODEL
    if ask is ask_model:
        ask = functools.partial(ask_model, model=model)
    cache = load_cache(path)
    hashes = type_hashes(types)
    if cache.get("prompt") != prompt_hash() or cache.get("model") != model:
        stale = cache.get("recipes", {})
        cache = {"format": CACHE_FORMAT, "prompt": prompt_hash(), "model": model, "types": hashes, "recipes": {}}
    else:
        stale = {}
    saved = cache["recipes"]
    old = cache.get("types") or {}
    changed = {name for name in set(old) | set(hashes) if old.get(name) != hashes.get(name)}
    if changed:
        # Only these types' recipes are asked again. Their saved hash is
        # cleared (labels kept until the new ones come) before the new
        # type hashes are saved, so a run cut short still asks them.
        log(f"Dish types changed: {', '.join(sorted(changed))}")
        for entry in entries:
            kept = saved.get(entry["recipe_id"])
            if kept and (set(kept.get("dishes", [])) & changed or title_names(entry, types) & changed):
                kept["hash"] = ""
        cache["types"] = hashes
        save_cache(cache, path)

    todo = [e for e in entries if (saved.get(e["recipe_id"]) or {}).get("hash") != entry_hash(e)]
    stats = {"asked": 0, "kept": len(entries) - len(todo), "missing": 0}
    if todo and types:
        log(f"Labeling {len(todo)} recipes with dish types ({model})...")
    for start in range(0, len(todo) if types else 0, BATCH_SIZE):
        batch = todo[start:start + BATCH_SIZE]
        try:
            found = _label_batch(batch, types, ask)
        except Exception as error:  # noqa: BLE001 - any model failure leaves the rest unlabeled
            if not (models.is_connection_error(error) or models.is_timeout(error)):
                raise
            log(f"Warning: the model couldn't be reached ({type(error).__name__}), so "
                f"{len(todo) - start} recipes have only the dish types their titles name. "
                f"Rebuild the index with Ollama running to label them.")
            break
        for entry in batch:
            saved[entry["recipe_id"]] = {"hash": entry_hash(entry), "dishes": found[entry["recipe_id"]]}
        stats["asked"] += len(batch)
        save_cache(cache, path)
        if stats["asked"] // PROGRESS_EVERY > (stats["asked"] - len(batch)) // PROGRESS_EVERY:
            log(f"  {stats['asked']}/{len(todo)}")

    for entry in entries:
        kept = saved.get(entry["recipe_id"]) or stale.get(entry["recipe_id"])
        if kept is None:
            stats["missing"] += 1
        model = clean((kept or {}).get("dishes", []), types)
        # The title only when the model has nothing: see the module docstring.
        # needs_name first, so a recipe whose only type it drops falls
        # back on its title ("Tartar Sauce" given only "dressing").
        model = keep_named(model, entry, types)
        labels = (model or set(title_dishes(entry, types))) | set(title_keywords(entry, types))
        entry["dishes"] = with_implied(keep_named(labels, entry, types), types)
        fixed = override_for(entry, overrides)
        if fixed is not None:
            entry["dishes"] = with_implied(set(fixed), types)
    return stats


def model_labels(path=DISH_LABELS_PATH):
    """{recipe_id: [types]} as the model gave them, for the diagnostic."""
    return {key: value.get("dishes", []) for key, value in load_cache(path).get("recipes", {}).items()}
