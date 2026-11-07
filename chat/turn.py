"""
One turn of a chat: handle(state, message) saves her message, routes it
(chat/router.py), runs the action, updates the focus (chat/state.py
remember), words the reply (chat/reply.py), and saves again with the
reply, how it was routed and how long each model call took.
"""

from dataclasses import dataclass

from actions import ask, match, scale
from chat import reply, store
from chat.router import Router
from chat.state import remember
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
        return ask.run(route.find_text)
    if route.action == "scale":
        if route.mode == "find":
            recipe, problem = scale.find(route.find_text)
            if problem:
                return problem
            route = router.scale_route(route.how, recipe, route.request, route.detail, route.remember_as)
        return scale.scale_recipe(route.recipe, route.request, base=route.base, batch=route.batch,
                                  factor=route.factor, explanation=route.explanation)
    return match.run(route.request)


def respond(state, message, candidates=None):
    """Route and answer a message, updating state (not saving it)."""
    router = Router(state, candidates)
    route = router.route(message)
    if route.action == "reply":
        if route.pending is not None:
            state.focus.pending = route.pending
        return TurnResult(route.text, route=route)
    result = run_route(router, route)
    remember(state, route.action, route.remember_as or route.request, result)
    return TurnResult(reply.render(route.action, result), route.action, result, route)


def handle(state, message, directory=CHATS_DIR, candidates=None):
    """One turn, saved before the work starts and again with the reply."""
    state.add_user(message)
    store.save(state, directory)
    models.clear()
    turn = respond(state, message, candidates)
    state.add_reply(turn.text, turn.action, turn.route.label if turn.route else None, models.CALLS)
    store.save(state, directory)
    return turn
