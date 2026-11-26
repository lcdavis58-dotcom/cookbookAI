"""
One turn of a chat: handle(state, message) saves her message, routes it
(chat/router.py), runs the action, updates the focus (chat/state.py
remember), words the reply (chat/reply.py), and saves again with the
reply, how it was routed and how long each model call took.
"""

from dataclasses import dataclass

from actions import ask, match, scale
from actions import filter as recipe_filter
from actions.ask import MAX_LISTED
from chat import narrow, reply, store
from chat.router import Router
from chat.state import Numbered, Pending, _as_ref, remember
from query_utils.title_lookup import ASKING_WORDS, title_tokens, word_forms
from common import models
from common.config import CHATS_DIR


@dataclass
class TurnResult:
    text: str                       # the reply, as shown
    action: str = None              # the action run, None for a plain reply
    result: object = None           # the action's result
    route: object = None            # chat.router.Route


def run_route(router, route):
    """The action's result for a route (not a "reply" one)."""
    if route.action == "ask":
        if route.mode == "show":
            return ask.show(route.recipe, route.request)
        if route.mode == "about":
            return ask.about(route.recipe, route.request)
        if route.mode == "list":
            return ask.list_recipes(route.find_text, route.request)
        if route.mode == "choose":
            choices = route.choices
            return ask.AskResult("choices", route.request, choices=choices[:MAX_LISTED], heading=route.text,
                                 rest=choices[MAX_LISTED:], more=len(choices[MAX_LISTED:]))
        if route.mode == "more":
            return ask.more(route.choices, route.first)
        if route.mode == "filter":
            return recipe_filter.run(route.choices, route.ingredient, route.without, route.what,
                                     index=[c.payload for c in router.candidates if c.payload],
                                     question=route.request, every=route.every)
        return ask.run(route.find_text)
    if route.action == "scale":
        if route.mode == "find":
            recipe, problem = scale.find(route.find_text)
            if problem:
                return problem
            route = router.scale_route(route.how, recipe, route.request, route.detail, route.remember_as)
        return scale.scale_recipe(route.recipe, route.request, base=route.base, batch=route.batch,
                                  factor=route.factor, explanation=route.explanation)
    result = match.run(route.request)
    result.page, result.first_number = route.page, route.first
    return result


def narrowing(route, result):
    """What a list's recipes are, for asking her to narrow it down ("cookie
    recipes"), or None when the list isn't too long to show."""
    if route.action != "ask" or result.kind != "choices" or result.start > 1 or route.detail == "narrow, all":
        return None
    if len(result.choices) + len(result.rest) <= narrow.NARROW_OVER:
        return None
    if route.narrowing:
        return route.narrowing
    if route.mode == "list":
        return f"{route.find_text.strip()} recipes"
    if route.mode == "filter":
        sense = "without" if route.without else "with"
        return f"{route.what + ' recipes' if route.what else 'recipes'} {sense} {route.ingredient}"
    # "show me a cookie recipe": the dish is the words she typed that
    # aren't just asking for it.
    dish = " ".join(w for w in title_tokens(route.find_text or route.request) if not word_forms(w) & ASKING_WORDS)
    return f"{dish} recipes" if dish else "recipes like that"


def ask_to_narrow(state, route, result, what):
    """The reply asking her to narrow a long list down, with the recipes
    kept (focus.numbered.rest) to read her answer against."""
    pool = result.choices + result.rest
    dish = " ".join(w for w in title_tokens(what) if w not in ("recipes", "recipe", "these", "without"))
    words, books = narrow.suggest(pool, dish)
    focus = state.focus
    focus.numbered = Numbered("narrow", [], [_as_ref(c) for c in pool])
    focus.pending = Pending("narrow", "ask", route.remember_as or route.request, narrow.options(words, books), what)
    return TurnResult(narrow.question(len(pool), what, words, books), "ask", result, route)


def respond(state, message, candidates=None):
    """Route and answer a message, updating state (not saving it)."""
    router = Router(state, candidates)
    route = router.route(message)
    if route.action == "reply":
        if route.pending is not None:
            state.focus.pending = route.pending
        return TurnResult(route.text, route=route)
    result = run_route(router, route)
    what = narrowing(route, result)
    if what:
        return ask_to_narrow(state, route, result, what)
    remember(state, route.action, route.remember_as or route.request, result)
    return TurnResult(reply.render(route.action, result), route.action, result, route)


def handle(state, message, directory=CHATS_DIR, candidates=None):
    """One turn, saved before the work starts and again with the reply."""
    state.add_user(message)
    store.save(state, directory)
    return _answer(state, message, directory, candidates)


def retry(state, directory=CHATS_DIR, candidates=None):
    """Answer her last message, saved earlier but never answered (the
    connection dropped, or the reply was stopped). None if there's no
    such message."""
    message = state.unanswered()
    if message is None:
        return None
    return _answer(state, message, directory, candidates)


def _answer(state, message, directory, candidates):
    models.clear()
    turn = respond(state, message, candidates)
    state.add_reply(turn.text, turn.action, turn.route.label if turn.route else None, models.CALLS)
    store.save(state, directory)
    return turn
