"""
What a chat remembers: every message, and the focus, what the
conversation is about right now. Follow-ups are read against the focus,
not the whole transcript:

    recipe      the recipe last shown or scaled: "it", "that one"
    numbered    the last numbered list shown (a "which one did you mean"
                list, or match results): "the second one"
    have        the last ingredients matched: "what about with pecans too"
    scale       the last scale factor and batch size used
    pending     a question the chat asked and is waiting on ("which one
                did you mean?", "which batch size?"), with the request
                it's for, so the answer can finish that request

remember() updates the focus from an action's result (see its table).

Recipes are kept as RecipeRef (recipe_id + book + title), not index
entries. A recipe_id is the recipe's position in its book, so a parser
change and re-ingest can renumber it; refresh() finds each one again in
the current index, by book and title when the id has moved.
"""

import secrets
import string
from dataclasses import asdict, dataclass, field
from datetime import datetime

# Bumped when the saved layout changes, so an old chat can still be read
# (or refused clearly) by a newer version.
FORMAT = 1

TITLE_LENGTH = 60

ACTIONS = ("ask", "scale", "match")


def now():
    return datetime.now().isoformat(timespec="seconds")


def new_id(when=None):
    """Date and time plus a short random tag, e.g. 2026-11-06-1932-k4f2.
    Sorts by when the chat started, and is the chat's file name."""
    tag = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    return f"{(when or datetime.now()):%Y-%m-%d-%H%M}-{tag}"


@dataclass
class RecipeRef:
    recipe_id: str
    book: str
    title: str
    # Set by refresh() when the recipe is no longer in the index. A gone
    # recipe stays in a numbered list so the numbers don't shift.
    gone: bool = False

    @classmethod
    def from_candidate(cls, candidate):
        """From a query_utils.title_lookup.Candidate."""
        return cls(candidate.key, candidate.book, candidate.title)

    @classmethod
    def from_entry(cls, entry):
        """From a recipe index entry."""
        return cls(entry["recipe_id"], entry["book"], entry["title"])


@dataclass
class Numbered:
    """A numbered list that was shown. source is the action it came from."""
    source: str
    items: list                     # RecipeRef, in the order numbered


@dataclass
class Pending:
    """A question the chat asked. kind is "pick_recipe" (the choices are
    focus.numbered), "pick_batch" (options are the batch names, for
    focus.recipe) or "need_recipe" (a request like "double it" with no
    recipe to apply it to). request is the message the question is about."""
    kind: str
    action: str
    request: str
    options: list = field(default_factory=list)


@dataclass
class ScaleUsed:
    factor: float
    batch: str = ""


@dataclass
class Focus:
    recipe: RecipeRef = None
    numbered: Numbered = None
    have: list = field(default_factory=list)
    scale: ScaleUsed = None
    pending: Pending = None


@dataclass
class Turn:
    role: str                       # "user" or "assistant"
    text: str                       # as shown
    at: str
    action: str = None              # the action that produced a reply
    route: str = None               # how the message was routed ("rule: scale current")
    # common/models.CALLS for the reply: {"job", "model", "seconds"} each,
    # read by tools/diagnostics/model_timing.py.
    model_calls: list = field(default_factory=list)


@dataclass
class ChatState:
    id: str
    title: str = ""
    created: str = ""
    updated: str = ""
    messages: list = field(default_factory=list)
    focus: Focus = field(default_factory=Focus)

    @classmethod
    def new(cls):
        stamp = now()
        return cls(new_id(), created=stamp, updated=stamp)

    def add_user(self, text):
        self.messages.append(Turn("user", text, now()))
        if not self.title:
            self.title = short_title(text)
        self.updated = self.messages[-1].at

    def add_reply(self, text, action=None, route=None, model_calls=()):
        self.messages.append(Turn("assistant", text, now(), action, route, list(model_calls)))
        self.updated = self.messages[-1].at

    def unanswered(self):
        """The last message, if it's hers and never got a reply (the
        connection dropped while it was being worked on), else None."""
        if self.messages and self.messages[-1].role == "user":
            return self.messages[-1].text
        return None

    def to_dict(self):
        return {"format": FORMAT, **asdict(self)}

    @classmethod
    def from_dict(cls, data):
        f = data.get("focus") or {}
        numbered = f.get("numbered")
        focus = Focus(
            recipe=_ref(f.get("recipe")),
            numbered=Numbered(numbered["source"], [_ref(r) for r in numbered["items"]]) if numbered else None,
            have=list(f.get("have") or []),
            scale=ScaleUsed(**f["scale"]) if f.get("scale") else None,
            pending=Pending(**f["pending"]) if f.get("pending") else None,
        )
        return cls(data["id"], data.get("title", ""), data.get("created", ""), data.get("updated", ""),
                   [Turn(**t) for t in data.get("messages", [])], focus)


def _ref(data):
    return RecipeRef(**data) if data else None


def short_title(text):
    text = " ".join(text.split())
    if len(text) <= TITLE_LENGTH:
        return text
    return text[:TITLE_LENGTH].rsplit(" ", 1)[0] + "..."


# ---- the focus, from each action's result ------------------------------

def remember(state, action, request, result):
    """Update the focus from what an action returned (actions/*.run).

        ask, recipe                  recipe; nothing pending
                                     (a different recipe also clears scale,
                                     everywhere recipe is set)
        ask, answer                  nothing pending (she moved on)
        ask or scale, choices        numbered = the choices; pending: pick one,
                                     for this request
        scale, scaled                recipe, scale; nothing pending
        scale, pick_batch            recipe; pending: pick a batch, for this request
        scale, no_factor or
               no_ingredients        recipe (it was found); nothing pending
        match, matches               have, numbered = the recipes shown;
                                     nothing pending
        anything else (not found,    unchanged, so a failed follow-up doesn't
        nothing relevant, ...)       lose the current recipe or question
    """
    focus = state.focus
    kind = result.kind

    def show(candidate):
        # The last scale factor belongs to the recipe it scaled.
        ref = RecipeRef.from_candidate(candidate)
        if focus.recipe is None or (focus.recipe.book, focus.recipe.title) != (ref.book, ref.title):
            focus.scale = None
        focus.recipe = ref

    if kind == "choices" and action in ("ask", "scale"):
        focus.numbered = Numbered(action, [RecipeRef.from_candidate(c) for c in result.choices])
        focus.pending = Pending("pick_recipe", action, request)
    elif action == "ask" and kind == "recipe":
        show(result.recipe)
        focus.pending = None
    elif action == "ask" and kind == "answer":
        focus.pending = None
    elif action == "scale" and kind == "scaled":
        show(result.recipe)
        focus.scale = ScaleUsed(result.factor, result.batch)
        focus.pending = None
    elif action == "scale" and kind == "pick_batch":
        show(result.recipe)
        focus.pending = Pending("pick_batch", "scale", request, [name for name, _ in result.batches])
    elif action == "scale" and kind in ("no_factor", "no_ingredients"):
        show(result.recipe)
        focus.pending = None
    elif action == "match" and kind == "matches":
        from actions.match import SHOW_PER_SECTION  # what the list shows, numbered in that order
        shown = [r for section in (result.ready, result.from_scratch, result.missing_some)
                 for r in section[:SHOW_PER_SECTION]]
        focus.have = list(result.have)
        focus.numbered = Numbered("match", [RecipeRef.from_entry(r["entry"]) for r in shown])
        focus.pending = None


# ---- finding saved recipes again ----------------------------------------

def resolve(ref, candidates):
    """The Candidate (query_utils.title_lookup) a saved RecipeRef stands
    for: the same recipe_id with the same book and title, else the same
    book and title under a new id (a re-ingest renumbered it), else None."""
    for c in candidates:
        if c.key == ref.recipe_id and c.book == ref.book and c.title == ref.title:
            return c
    for c in candidates:
        if c.book == ref.book and c.title == ref.title:
            return c
    return None


def refresh(state, candidates):
    """Check every recipe the focus holds against the current index
    (candidates_from_index of it): moved ids are updated, recipes no
    longer there are dropped from focus.recipe and marked gone in a
    numbered list. Returns the titles that were gone, for a note."""
    gone = []

    def check(ref):
        found = resolve(ref, candidates)
        if found is None:
            ref.gone = True
            if ref.title not in gone:
                gone.append(ref.title)
        else:
            ref.recipe_id, ref.gone = found.key, False
        return found

    focus = state.focus
    if focus.recipe and check(focus.recipe) is None:
        focus.recipe = None
        if focus.pending and focus.pending.kind == "pick_batch":
            focus.pending = None
    if focus.numbered:
        for ref in focus.numbered.items:
            check(ref)
    return gone
