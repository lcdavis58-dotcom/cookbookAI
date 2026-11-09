"""
Which action a chat message is for, and what it's about. route() tries,
in order (cheapest and most certain first):

    pending   an answer to a question the chat asked: a number, a name
              or a book from the list it gave, a batch size, a recipe for
              a request that didn't have one
    rules     plain patterns, no model:
                a numbered reference ("the second one", "#3")
                going back to the recipe as written ("back to the original")
                another batch size of the current recipe ("the mile-high batch")
                scaling ("double it", "for 12 people", "I only have 1 egg")
                ingredients ("what can I make with ...", "add pecans",
                    "without the lemons", "pecans, cream cheese")
                showing a recipe ("show me ...", "recipe for ...", a title)
                a short question about the current recipe ("how long does it chill?")
    model     everything else: the model gets the message, a summary of
              the focus and the last few messages, and picks a tool; its
              answer is checked before anything runs (see _from_model)

Whatever can't be pinned down becomes a question back to her (a "reply"
route), never a guess.

Scaling builds on where the recipe is now: after "double it", "halve it"
is 1x. Words like "original" or "as written" (ORIGINAL_RE) go back to
the recipe as written.
"""

import json
import os
import re
from dataclasses import dataclass

from actions.scale import find_batch, times, without_title_multipliers
from books import strategy_for
from chat.state import Pending, resolve
from common import cli, models
from common.config import RECIPE_INDEX_PATH
from match_utils.matching import parse_have
from match_utils.recipe_index import load_index
from query_utils.retrieval import candidate_text
from query_utils.title_lookup import (REQUEST_WORDS, candidates_from_index, find_books, lookup,
                                      title_tokens, word_forms)
from scale_utils.ingredients import extract_ingredient_groups
from scale_utils.pan_scaling import detect_pan_request
from scale_utils.recipe_scaling import detect_direct_multiplier

ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4, "5th": 5,
            "6th": 6, "7th": 7, "8th": 8, "9th": 9, "10th": 10, "last": -1}
_ORD = "|".join(ORDINALS)
ORDINAL_THE_RE = re.compile(rf"\bthe\s+({_ORD})\b", re.I)
ORDINAL_ALONE_RE = re.compile(rf"^\s*({_ORD})(?:\s+(?:one|recipe|option))?\s*[.!?]?\s*$", re.I)
NUMBER_RE = re.compile(r"(?:^|\s)(?:#\s*|no\.\s*|number\s+|option\s+|recipe\s+#?)(\d{1,2})\b", re.I)
BARE_NUMBER_RE = re.compile(r"^\s*#?(\d{1,2})\s*[.!)]?\s*$")

PRONOUN_RE = re.compile(r"\b(it|that|this|them|these|those|same|the recipe|that recipe|this recipe)\b", re.I)
# Back to what the recipe calls for.
ORIGINAL_RE = re.compile(r"\b(original|as written|recipe'?s (?:own )?amounts|back to normal|normal amounts?|"
                         r"regular amounts?|unscaled|full recipe)\b", re.I)
QUESTION_RE = re.compile(r"^\s*(how|what|when|why|where|which|who|can|could|should|do|does|did|is|are|"
                         r"will|would)\b|\?\s*$", re.I)
SCALE_CUE_RE = re.compile(r"\b(scale|scaled|rescale|for \d+|feeds?|serves?|servings?|people|guests|"
                          r"only have|only got|have only|i just have|i have just|make (?:it|this|that) for)\b", re.I)
# Scaling said outright, which "show me ..." doesn't override ("show me
# it doubled"), unlike "double" alone, which can be part of a name
# ("show me the double chocolate cake").
EXPLICIT_SCALE_RE = re.compile(r"\b(scale|scaled|rescale|doubled|tripled|halved|quadrupled|\d+(?:\.\d+)?\s*x|"
                               r"times|for \d+|feeds?|serves?|servings?|people|guests|only have)\b", re.I)
# Anything a scaling request has to say: a number, or a word about size.
# The model's choice to scale is only trusted for a message with one.
SOUNDS_LIKE_SCALING_RE = re.compile(r"\d|%|\b(bigger|smaller|larger|more|less|fewer|half|halve|double|triple|"
                                    r"quadruple|twice|thrice|scale|size|batch|serv|people|guests|feed|crowd|pan|"
                                    r"amount|portion|original|written|enough|times|two|three|four|five|six|"
                                    r"seven|eight|nine|ten|twelve|dozen)", re.I)
# What a question about the recipe at hand tends to ask.
DETAIL_RE = re.compile(r"\b(bake|baking|chill|chilling|cook|cooking|rest|rise|proof|temperature|oven|degrees|"
                       r"how long|minutes|hours|time|ahead|store|keep|freeze|thaw|substitute|instead of|swap|"
                       r"replace|pan|serve|yield|makes|step|steps|ingredients?|need|calls? for)\b", re.I)
ASK_RE = re.compile(r"^\s*(?:show\s+me|(?:a\s+|the\s+)?recipe\s+for|how\s+(?:do|would|should|can)\s+i\s+make|"
                    r"how\s+to\s+make|find(?:\s+me)?|give\s+me|pull\s+up|open|let\s+me\s+see|can\s+i\s+see|"
                    r"i\s+want\s+to\s+make|i'?d\s+like\s+to\s+make|look\s+up)\b", re.I)

MATCH_NEW_RE = re.compile(r"^\s*(?:what|anything|something)\b.*?\b(?:can|could)\s+(?:i|we)\s+(?:make|cook|bake)\b"
                          r".*?\b(?:with|using|from)\s+(.+)$", re.I)
I_HAVE_RE = re.compile(r"^\s*(?:i|we)\s+(?:have|'ve\s+got|have\s+got|got)\s+(.+)$", re.I)
MATCH_ADD_RE = re.compile(r"^\s*(?:add|also|plus|and\s+also|i\s+also\s+have|also\s+have)\s+(.+?)\s*[.!?]?\s*$", re.I)
WHAT_ABOUT_RE = re.compile(r"^\s*(?:and\s+)?(?:what|how)\s+about\s+(?:with\s+|adding\s+|if\s+i\s+(?:also\s+)?"
                           r"(?:add|have)\s+)?(.+?)\s*[.!?]?\s*$", re.I)
TOO_RE = re.compile(r"^(.+?)\s+(?:too|as\s+well|also)\s*[.!?]?\s*$", re.I)
MATCH_REMOVE_RE = re.compile(r"^\s*(?:(?:ok(?:ay)?|actually|oh|wait|and|so),?\s+)*(?:(?:what|how)\s+about\s+)?"
                             r"(?:without|remove|minus|take\s+out|drop|forget(?:\s+about)?|skip|leave\s+out|"
                             r"scratch|i\s+don'?t\s+have(?:\s+any)?|i'?m\s+out\s+of|no\s+more)\s+(.+?)"
                             r"\s*[.!?]?\s*$", re.I)
# Asking for every recipe of something: "what pumpkin pie recipes do i
# have". A plural is what makes "show me pumpkin pie recipes" a list and
# "show me a pumpkin pie recipe" a request for one.
LIST_RES = tuple(re.compile(p, re.I) for p in (
    r"^\s*(?:(?:tell|show)\s+me\s+|list\s+)?(?:what|which)\s+(?:kinds?\s+of\s+)?(.+?)\s+recipes?\s+"
    r"(?:do\s+|did\s+)?(?:i|we)\s+(?:have|got|own)\b",
    r"^\s*(?:do|did)\s+(?:i|we)\s+have\s+(?:any|some)\s+(.+?)\s+recipes\b",
    r"^\s*(?:show|list|give|find)(?:\s+me)?\s+(?:all|every)(?:\s+of)?(?:\s+(?:the|my))?\s+(.+?)\s+recipes?\b",
    r"^\s*(?:show(?:\s+me)?|list)\s+(?:(?:the|my)\s+)?(.+?)\s+recipes\b",
    r"^\s*all\s+(?:the\s+|my\s+)?(.+?)\s+recipes\s*[.!?]?\s*$",
))
_LEADING_RE = re.compile(r"^\s*(?:with|the|my|some|any|a|an|also)\s+", re.I)
_TRAILING_RE = re.compile(r"\s+(?:too|as\s+well|also|instead)\s*$", re.I)


@dataclass
class Route:
    """What to do with a message.
        action  "ask", "scale", "match", or "reply" (just say text, and
                wait on pending if given)
        mode    ask: "find" (look up find_text), "show" (recipe),
                "about" (a question about recipe), "list" (every recipe
                with find_text in its title)
                scale: "find" (look up find_text, then scale), "recipe"
                match: "run"
    request is what the action is asked (the scaling request, the
    question, the ingredient list); remember_as is the request a result
    is remembered under when it finishes an earlier one."""
    action: str
    how: str                        # "pending", "rule" or "model"
    detail: str = ""
    mode: str = ""
    recipe: object = None           # title_lookup.Candidate
    find_text: str = ""
    request: str = ""
    remember_as: str = None
    base: float = 1.0
    batch: str = None
    factor: float = None
    explanation: str = None
    text: str = ""
    pending: Pending = None

    @property
    def label(self):
        return f"{self.how}: {self.action}" + (f" {self.detail}" if self.detail else "")


# ---- the recipe index -----------------------------------------------------

_cache = {"key": None, "candidates": []}


def load_candidates():
    """Every recipe in the index as a title_lookup.Candidate, reloaded
    only when the index file changes."""
    try:
        key = os.path.getmtime(RECIPE_INDEX_PATH)
    except OSError:
        key = None
    if key is None or key != _cache["key"]:
        _cache["candidates"] = candidates_from_index(load_index() or [])
        _cache["key"] = key
    return _cache["candidates"]


def recipe_batches(candidate):
    """The batch sizes a recipe comes in (Half, Full, Mile-High), if any."""
    text = candidate_text(candidate)
    if not text:
        return []
    return list(extract_ingredient_groups(text, strategy_for(candidate.book)).batches)


# ---- reading a message ----------------------------------------------------

def list_number(message):
    """The list item a message points at: 2 for "2", "#2", "the second
    one", "number 2"; -1 for "the last one"; else None."""
    for regex in (BARE_NUMBER_RE, NUMBER_RE):
        m = regex.search(message)
        if m:
            return int(m.group(1))
    m = ORDINAL_THE_RE.search(message) or ORDINAL_ALONE_RE.search(message)
    return ORDINALS[m.group(1).lower()] if m else None


def pick_from(message, candidates):
    """The one candidate a message names by its words ("the classic one")
    or its book ("the one from book on pie"), or None."""
    books, _ = find_books(message, {c.book for c in candidates})
    if books:
        in_books = [c for c in candidates if c.book in books]
        if len(in_books) == 1:
            return in_books[0]
        candidates = in_books or candidates
    said = set()
    for w in title_tokens(message):
        said |= word_forms(w)
    best, fits = 0, []
    for c in candidates:
        shared = sum(1 for w in set(title_tokens(c.title)) if word_forms(w) & said)
        if shared > best:
            best, fits = shared, [c]
        elif shared == best and shared:
            fits.append(c)
    # Shared by every candidate ("whipped cream" in a list of whipped
    # creams) tells them apart no better than nothing.
    if len(fits) == 1 and not (len(candidates) > 1 and all(
            sum(1 for w in set(title_tokens(c.title)) if word_forms(w) & said) == best for c in candidates)):
        return fits[0]
    return None


def clean_items(text):
    """Ingredient words from a follow-up, without "the", "too" and such."""
    text = _TRAILING_RE.sub("", text.strip(" .!?"))
    while _LEADING_RE.match(text):
        text = _LEADING_RE.sub("", text, count=1)
    return parse_have(re.sub(r"\b(?:the|my|some|any)\s+", "", text, flags=re.I))


def mostly_title(message, candidate):
    """At least half the message's words (leaving out a book's name and
    request words like "make") are the title's: "classic whipped cream"
    or "lemon curd from dessert person" name a recipe, "something with
    chicken I can make tonight" only mentions one ("Chicken with
    Vinegar" is named by "chicken" alone)."""
    _, cleaned = find_books(message, {candidate.book})
    words = [w for w in title_tokens(cleaned) if w not in REQUEST_WORDS]
    title = set()
    for w in title_tokens(candidate.title):
        title |= word_forms(w)
    return bool(words) and 2 * sum(1 for w in words if word_forms(w) & title) >= len(words)


def is_question(message):
    return bool(QUESTION_RE.search(message))


def scale_cues(message):
    return (detect_direct_multiplier(message) is not None or detect_pan_request(message)
            or bool(SCALE_CUE_RE.search(message)))


def same_recipe(a, b):
    return a is not None and b is not None and (a.book, a.title) == (b.book, b.title)


# ---- routing --------------------------------------------------------------

class Router:
    def __init__(self, state, candidates=None):
        self.state = state
        self.focus = state.focus
        self.candidates = load_candidates() if candidates is None else candidates

    def resolve(self, ref):
        return None if ref is None else resolve(ref, self.candidates)

    def current(self):
        return self.resolve(self.focus.recipe)

    def base_for(self, candidate, message=""):
        """The factor a recipe is at: the last scale, if it was this
        recipe and the message doesn't go back to the original."""
        scale = self.focus.scale
        if scale and same_recipe(self.focus.recipe, candidate) and not ORIGINAL_RE.search(message):
            return scale.factor
        return 1.0

    def numbered_item(self, n, how):
        """The Candidate for item n of the last list, or a reply route
        saying why not."""
        numbered = self.focus.numbered
        if not numbered or not numbered.items:
            return None, Route("reply", how, "no list", text="There's no numbered list to pick from yet.")
        items = numbered.items
        if n == -1:
            n = len(items)
        if not 1 <= n <= len(items):
            return None, Route("reply", how, "out of range",
                               text=f"The last list only had {len(items)} recipe{'s' if len(items) != 1 else ''}.")
        ref = items[n - 1]
        found = None if ref.gone else self.resolve(ref)
        if found is None:
            return None, Route("reply", how, "gone",
                               text=f"{ref.title} isn't in the recipe index anymore (the books were re-ingested).")
        return found, None

    def scale_route(self, how, candidate, message, detail, remember_as=None):
        request = without_title_multipliers(message, candidate)
        if ORIGINAL_RE.search(message) and detect_direct_multiplier(request) is None and not scale_cues(request):
            return Route("scale", how, f"{detail}, as written", mode="recipe", recipe=candidate, request=request,
                         remember_as=remember_as, factor=1.0, explanation="The recipe as written (1x)",
                         batch=self.focus.scale.batch if self.focus.scale else None)
        return Route("scale", how, detail, mode="recipe", recipe=candidate, request=request,
                     remember_as=remember_as, base=self.base_for(candidate, message),
                     batch=self.focus.scale.batch if self.focus.scale and same_recipe(self.focus.recipe, candidate)
                     else None)

    def finish(self, action, candidate, request, how, detail):
        """Finish an earlier request (pending) with the recipe it's for."""
        if action == "scale":
            return self.scale_route(how, candidate, request, detail, remember_as=request)
        return Route("ask", how, detail, mode="show", recipe=candidate, request=request, remember_as=request)

    # -- pending --

    def from_pending(self, message):
        pending = self.focus.pending
        if pending is None:
            return None
        if pending.kind == "pick_batch":
            recipe = self.current()
            name = find_batch(message, pending.options)
            if recipe is None or name is None:
                return None
            route = self.scale_route("pending", recipe, pending.request, f"batch {name}", remember_as=pending.request)
            route.batch = name
            return route
        if pending.kind in ("pick_recipe", "need_recipe"):
            n = list_number(message)
            if n is not None and self.focus.numbered:
                found, problem = self.numbered_item(n, "pending")
                return problem or self.finish(pending.action, found, pending.request, "pending", f"#{n}")
            if pending.kind == "pick_recipe" and self.focus.numbered:
                choices = [c for c in (self.resolve(r) for r in self.focus.numbered.items if not r.gone) if c]
                found = pick_from(message, choices)
                if found is not None:
                    return self.finish(pending.action, found, pending.request, "pending", "by name")
            if pending.kind == "need_recipe":
                named = lookup(message, self.candidates)
                if named.kind == "match" and not scale_cues(without_title_multipliers(message, named.matches[0])):
                    if len(named.matches) == 1:
                        return self.finish(pending.action, named.matches[0], pending.request, "pending", "named")
                    return Route(pending.action, "pending", "named, several", mode="find", find_text=message,
                                 request=pending.request, remember_as=pending.request)
        return None

    # -- rules --

    def from_rules(self, message):
        focus = self.focus
        named = lookup(message, self.candidates)
        named_one = named.matches[0] if named.kind == "match" and len(named.matches) == 1 else None
        current = self.current()

        n = list_number(message)
        if n is not None and not named_one:
            found, problem = self.numbered_item(n, "rule")
            if problem:
                return problem
            if scale_cues(message):
                return self.scale_route("rule", found, message, f"#{n}")
            return Route("ask", "rule", f"show #{n}", mode="show", recipe=found, request=message)

        for pattern in LIST_RES:
            m = pattern.match(message)
            if m:
                return Route("ask", "rule", "list", mode="list", find_text=m.group(1), request=message)

        if current and focus.scale and ORIGINAL_RE.search(message) and not named_one \
                and detect_direct_multiplier(message) is None and not is_question(message):
            return self.scale_route("rule", current, message, "current")

        if current and re.search(r"\bbatch\b", message, re.I) and (not named_one or same_recipe(named_one, current)):
            batches = recipe_batches(current)
            name = find_batch(message, batches)
            if name:
                rest = message
                for w in title_tokens(name):
                    rest = re.sub(rf"\b{re.escape(w)}\b", " ", rest, flags=re.I)
                if detect_direct_multiplier(rest) is not None:
                    return Route("scale", "rule", f"current, {name}", mode="recipe", recipe=current,
                                 request=" ".join(rest.split()), batch=name)
                factor = focus.scale.factor if focus.scale and same_recipe(focus.recipe, current) else 1.0
                return Route("scale", "rule", f"current, {name}", mode="recipe", recipe=current, request=message,
                             batch=name, factor=factor,
                             explanation=f"{name} at {times(factor)}" + (" (as written)" if factor == 1 else ""))

        match = self.match_rule(message, named_one)
        if match:
            return match

        asking = bool(ASK_RE.search(message)) and not EXPLICIT_SCALE_RE.search(message)
        multiplier = detect_direct_multiplier(without_title_multipliers(message, named_one) if named_one else message)
        if not asking and (multiplier is not None or (scale_cues(message) and not is_question(message))):
            if named_one and not (current and PRONOUN_RE.search(message) and not same_recipe(named_one, current)):
                return Route("scale", "rule", "named", mode="find", find_text=message, request=message)
            if current and (named.kind == "none" or PRONOUN_RE.search(message)):
                return self.scale_route("rule", current, message, "current")
            if named.kind != "none":
                return Route("scale", "rule", "named", mode="find", find_text=message, request=message)
            text = ("Which recipe should I scale? Say a number from the last list or a recipe's name."
                    if focus.numbered else "Which recipe should I scale?")
            return Route("reply", "rule", "need recipe", text=text,
                         pending=Pending("need_recipe", "scale", message))

        if ASK_RE.search(message):
            if current and named.kind == "none" and PRONOUN_RE.search(message):
                return Route("ask", "rule", "show current", mode="show", recipe=current, request=message)
            return Route("ask", "rule", "find", mode="find", find_text=message, request=message)

        if named.kind == "match" and not is_question(message) and mostly_title(message, named.matches[0]):
            return Route("ask", "rule", "find", mode="find", find_text=message, request=message)

        # A question about the recipe at hand: "how long does it chill?",
        # "what temperature?". One that names another dish, even in part,
        # or doesn't sound like it's about a recipe ("what's for
        # dinner?") goes to the model.
        if current and is_question(message) and (
                (PRONOUN_RE.search(message) and named.kind != "match")
                or (named.kind == "none" and DETAIL_RE.search(message))):
            return Route("ask", "rule", "about current", mode="about", recipe=current, request=message)
        return None

    def match_rule(self, message, named_one):
        have = self.focus.have
        last_was_match = self.focus.numbered is not None and self.focus.numbered.source == "match"

        def run(items, detail):
            return Route("match", "rule", detail, mode="run", request=", ".join(items))

        if have:
            m = MATCH_REMOVE_RE.match(message)
            if m:
                drop = clean_items(m.group(1))
                kept = [h for h in have if h not in drop]
                if len(kept) == len(have):
                    return Route("reply", "rule", "nothing to remove",
                                 text=f"{', '.join(drop) or 'That'} wasn't in your list. You have: {', '.join(have)}.")
                if not kept:
                    return Route("reply", "rule", "nothing left", text="That leaves no ingredients. What do you have?")
                return run(kept, f"remove {drop}")
            m = MATCH_ADD_RE.match(message) or (last_was_match and not named_one and (
                WHAT_ABOUT_RE.match(message) or TOO_RE.match(message)))
            if m:
                extra = [i for i in clean_items(m.group(1)) if i not in have]
                if extra:
                    return run(have + extra, f"add {extra}")
        m = MATCH_NEW_RE.match(message) or (I_HAVE_RE.match(message) if not is_question(message)
                                            and not PRONOUN_RE.search(message) else None)
        if m:
            items = clean_items(m.group(1))
            if items:
                return run(items, "new")
        if "," in message and not named_one and not scale_cues(message) and not ASK_RE.search(message) \
                and not is_question(message):
            items = clean_items(message)
            if len(items) > 1:
                return run(items, "list")
        return None

    # -- the model --

    def summary(self):
        """What the model is told about the conversation so far."""
        focus, lines = self.focus, []
        if focus.recipe:
            line = f"Current recipe: {focus.recipe.title} ({focus.recipe.book})"
            if focus.scale:
                line += f", now scaled to {times(focus.scale.factor)}" + (f", {focus.scale.batch}" if focus.scale.batch else "")
            lines.append(line)
        if focus.numbered and focus.numbered.items:
            shown = focus.numbered.items[:10]
            lines.append(f"Last numbered list (from {focus.numbered.source}): " + "  ".join(
                f"{i}. {r.title} ({r.book})" for i, r in enumerate(shown, 1))
                + (f"  ...{len(focus.numbered.items)} in all" if len(focus.numbered.items) > 10 else ""))
        if focus.have:
            lines.append(f"Last ingredients searched: {', '.join(focus.have)}")
        if focus.pending:
            lines.append(f'Waiting for her answer about: "{focus.pending.request}"')
        recent = []
        for turn in self.state.messages[-5:-1]:
            first = turn.text.strip().splitlines()[0] if turn.text.strip() else ""
            recent.append(f"{'She' if turn.role == 'user' else 'Assistant'}: {first[:150]}")
        if recent:
            lines += ["Recent messages:"] + recent
        return "\n".join(lines) or "Nothing yet: this is the first message."

    def from_model(self, message):
        response, _ = models.chat(
            "route",
            messages=[{"role": "system", "content": ROUTER_PROMPT},
                      {"role": "user", "content": f"{self.summary()}\n\nNew message: {message}"}],
            tools=ROUTER_TOOLS,
            options={"temperature": 0.1},
        )
        calls = response["message"].get("tool_calls") or []
        if not calls:
            return Route("reply", "model", "no tool", text=NOT_SURE)
        function = calls[0]["function"]
        args = function.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if cli.DEBUG:
            print(f"[route] model chose {function.get('name')} {args}")
        return self._from_model(function.get("name"), args, message)

    def _from_model(self, name, args, message):
        """The model's tool call, checked: a real tool, a list number in
        range, "current" only when there's a current recipe."""
        detail = f"{name}"
        if name == "ask_user":
            question = str(args.get("question") or "").strip()
            return Route("reply", "model", "ask user", text=question or NOT_SURE)
        if name == "find_by_ingredients":
            items = args.get("ingredients") or []
            if isinstance(items, str):
                items = [items]
            items = clean_items(", ".join(str(i) for i in items))
            mode = args.get("mode") or "new"
            have = self.focus.have
            if mode == "add":
                items = have + [i for i in items if i not in have]
            elif mode == "remove":
                items = [h for h in have if h not in items]
            if not items:
                return Route("reply", "model", f"{detail} empty", text="Which ingredients do you have?")
            return Route("match", "model", f"{mode} {items}", mode="run", request=", ".join(items))
        if name not in ("find_or_answer", "scale_recipe"):
            return Route("reply", "model", f"unknown tool {name!r}", text=NOT_SURE)

        action = "ask" if name == "find_or_answer" else "scale"
        text = str(args.get("question") or args.get("request") or "").strip() or message
        if action == "scale" and not SOUNDS_LIKE_SCALING_RE.search(message):
            # "what's for dinner" once came back as "scale the current
            # recipe"; a message with no amount or size in it isn't
            # scaled on the model's word alone.
            recipe = self.current()
            what = recipe.title if recipe else "a recipe"
            return Route("reply", "model", "scale, but no amount",
                         text=f'Do you want me to scale {what}? Tell me how much, e.g. "double it" or "for 8 people".')
        ref = str(args.get("recipe") or "none").strip().lower()
        if ref == "current":
            recipe = self.current()
            if recipe is None:
                return Route("reply", "model", f"{action} current, but none",
                             text="Which recipe do you mean?", pending=Pending("need_recipe", action, text))
            if action == "scale":
                if args.get("from_original"):
                    text = f"{text} (original)"
                return self.scale_route("model", recipe, text, "current")
            return Route("ask", "model", "about current", mode="about", recipe=recipe, request=text)
        if ref.lstrip("#").isdigit():
            found, problem = self.numbered_item(int(ref.lstrip("#")), "model")
            if problem:
                return problem
            if action == "scale":
                return self.scale_route("model", found, text, f"#{ref}")
            return Route("ask", "model", f"show #{ref}", mode="show", recipe=found, request=text)
        if action == "scale":
            return Route("scale", "model", "named", mode="find", find_text=text, request=text)
        return Route("ask", "model", "find", mode="find", find_text=text, request=text)

    def route(self, message):
        for step in (self.from_pending, self.from_rules, self.from_model):
            route = step(message)
            if route is not None:
                if cli.DEBUG:
                    print(f"[route] {route.label}")
                return route


def route(state, message, candidates=None):
    return Router(state, candidates).route(message)


NOT_SURE = "I'm not sure what you mean. Could you say it another way, or name the recipe?"

ROUTER_PROMPT = """You route messages in a chat with a cookbook assistant. The person
cooks from their own cookbooks. Call exactly one tool.

Use the conversation state to work out what "it", "that one" or "the
second one" refer to. A number refers to the last numbered list. Scaling
builds on the current scale unless she says "original" or "as written".
Never invent a recipe. If you can't tell what she means, call ask_user
with one short question instead of guessing."""

_RECIPE_ARG = {
    "type": "string",
    "description": ('Which recipe: "current" (the current recipe), a number (that item of the last '
                    'numbered list), "named" (a recipe named in the message), or "none".'),
}

ROUTER_TOOLS = [
    {"type": "function", "function": {
        "name": "find_or_answer",
        "description": "Show a recipe, or answer a question from the cookbooks.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string",
                         "description": "Her request, reworded so it makes sense on its own."},
            "recipe": _RECIPE_ARG,
        }, "required": ["question", "recipe"]}}},
    {"type": "function", "function": {
        "name": "scale_recipe",
        "description": "Scale a recipe up or down: a multiplier, a number of servings, a pan size, "
                       "or the amount of one ingredient she has.",
        "parameters": {"type": "object", "properties": {
            "request": {"type": "string",
                        "description": 'The scaling request on its own, e.g. "halve it", "for 12 people".'},
            "recipe": _RECIPE_ARG,
            "from_original": {"type": "boolean",
                              "description": "True if she means the recipe as written, not its current scale."},
        }, "required": ["request", "recipe"]}}},
    {"type": "function", "function": {
        "name": "find_by_ingredients",
        "description": "Find recipes she can make from ingredients she has.",
        "parameters": {"type": "object", "properties": {
            "ingredients": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": ["new", "add", "remove"],
                     "description": "new: only these; add or remove: change the last ingredients searched."},
        }, "required": ["ingredients", "mode"]}}},
    {"type": "function", "function": {
        "name": "ask_user",
        "description": "Ask her one short question when the message is unclear.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string"},
        }, "required": ["question"]}}},
]
