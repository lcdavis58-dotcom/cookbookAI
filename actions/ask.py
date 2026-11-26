"""
Ask a question about your recipes: a recipe the question names is shown
as the book's exact text; several are listed to pick from; anything else
goes to the model with the closest book excerpts. See query.py.

A question that names recipes ("what can I substitute for buttermilk in
pancakes?") is answered from those recipes' text rather than showing
them. A request to see a recipe that names none in full gets the one
plainly closest title, or the titles with all its words ("my butter
cream recipe from dessert person"), before a "Did you mean" list.
"""

import re
from dataclasses import dataclass, field

from actions import answer_checks
from common import cli, models
from query_utils.recipe_matching import extract_title, semantic_top_recipe_guess
from query_utils.retrieval import candidate_text, retrieve, within_distance
from query_utils.title_lookup import MAX_LISTED, find_recipes, list_titles, load_candidates

DID_YOU_MEAN = "I couldn't find a recipe by exactly that name. Did you mean one of these?"
# Asking to see a recipe, as opposed to asking about something. "Show me
# how to ..." is a technique, not a recipe's name.
WANTS_RECIPE_RE = re.compile(r"^\s*(?:(?:no|ok(?:ay)?|actually|and|so|please)[,\s]+)*"
                             r"(?:show\s+me(?!\s+how\b)|(?:a\s+|the\s+)?recipe\s+for|"
                             r"how\s+(?:do|would|should|can)\s+i\s+make|how\s+to\s+make|find(?:\s+me)?|give\s+me|"
                             r"pull\s+up|open|let\s+me\s+see|can\s+i\s+see|i\s+want\s+to\s+make|"
                             r"i'?d\s+like\s+to\s+make|look\s+up|is\s+there|are\s+there|"
                             r"do\s+(?:i|we|you)\s+have|where(?:'?s|\s+is))\b", re.I)
# A question, as opposed to a request ("show me ..."); see run().
QUESTION_RE = re.compile(r"^\s*(how|what|when|why|where|which|who|can|could|should|do|does|did|is|are|"
                         r"will|would)\b|\?\s*$", re.I)
# What a question about a recipe tends to ask. A question naming a
# recipe without any of these ("what goes with banana bread?") isn't
# answered from that recipe alone.
DETAIL_RE = re.compile(r"\b(bake|baking|chill|chilling|cook|cooking|rest|rise|proof|temperature|oven|degrees|"
                       r"how long|minutes|hours|time|ahead|store|keep|last|freeze|thaw|substitute|instead of|swap|"
                       r"replace|pan|serve|yield|makes|step|steps|ingredients?|need|calls? for|use|uses|"
                       r"how much|how many)\b", re.I)
CLOSEST = "I couldn't find a recipe by exactly that name. This is the closest:"
CLOSEST_SEVERAL = "I couldn't find a recipe by exactly that name. These have all of its words:"
# How many recipes a question naming several is answered from: whole
# recipes are long, and the model's context holds about three.
ABOUT_MAX_RECIPES = 3

# How many of the retrieved chunks get pasted into the prompt if we fall
# through to generation. Kept small, a bigger prompt directly costs more
# time on the Pi's CPU (see TITLE_SEARCH_K in query_utils/retrieval.py for
# the wider search this is a slice of).
LLM_CONTEXT_K = 6

SYSTEM_PROMPT = """You are a cookbook assistant. You may ONLY use the recipe
excerpts provided below to answer. Do not use any outside knowledge, even if
you recognize the dish.

Rules:
- If the excerpts don't contain enough information to answer, say so plainly
  and stop there. Do not guess, do not suggest what a recipe "might be," and
  do not recommend any book, cookbook, or source that isn't one of the
  excerpts given to you. If it isn't in the excerpts, it doesn't exist as
  far as you're concerned.
- Never name a specific dish (like "this is probably a lasagna recipe")
  unless the excerpt itself explicitly names it. Guessing based on
  ingredients alone is not allowed.
- Treat each excerpt as a SEPARATE, independent source. Never combine
  ingredients, instructions, or steps from two different excerpts into one
  answer, even if they mention the same dish. If no single excerpt fully
  answers the question, say what you found in each excerpt separately
  instead of merging them.
- Quote quantities, yields, measurements, and ingredient amounts EXACTLY as
  written in the excerpt. Do not convert units, do not combine multiple
  batch sizes into a summary or range, and do not paraphrase numbers in any
  way. Copy them character for character. Do not add any closing note,
  estimate, or interpretation of a yield or quantity beyond restating it
  exactly as written.
- Always cite the book title for any recipe you reference. Include the page
  number ONLY if it's given as an actual number, if an excerpt is marked
  "page unknown," cite the book and recipe name only, do not invent a page
  number under any circumstances.
- If asked to scale a recipe, extract the ingredient list exactly as written
  and note the original serving size, but do not do the math yourself.
"""


@dataclass
class AskResult:
    """What ask() found. kind is one of:
        "recipe"    the question names one recipe: recipe, text
        "choices"   it names several: choices (best first, at most
                    title_lookup.MAX_LISTED), more (how many past those)
        "answer"    the model answered from the closest excerpts: answer,
                    sources (the hits it was given), generation_time;
                    from about(), recipe is the one recipe it was given
        "nothing"   nothing in the books is close to the question
        "said"      a plain answer in heading, no recipes (actions/filter.py:
                    "None of these use half and half.")
    warnings are problems worth showing whatever the kind (a recipe in the
    index but not the database)."""
    kind: str
    question: str
    recipe: object = None           # title_lookup.Candidate
    text: str = ""
    choices: list = field(default_factory=list)
    more: int = 0
    answer: str = ""
    sources: list = field(default_factory=list)
    generation_time: float = 0.0
    warnings: list = field(default_factory=list)
    heading: str = ""               # for "choices", when it isn't the usual "which one?"
    note: str = ""                  # for "recipe": said first ("the closest I found")
    rest: list = field(default_factory=list)  # for "choices": the ones past those shown, for "more"
    start: int = 1                  # for "choices": the number of the first one (a later page)
    via: dict = field(default_factory=dict)   # recipe key -> the variation it was found through
    notes: dict = field(default_factory=dict)  # recipe key -> a note shown after it ("optional")
    footer: str = ""                # for "choices": said after the list ("The other 3 don't.")
    # for "answer": what actions/answer_checks.py still found wrong after
    # asking the model again ({"kind", "what"} each), shown as a warning
    unchecked: list = field(default_factory=list)


def build_context(hits):
    parts = []
    for h in hits:
        if h["page_confirmed"]:
            label = f"[{h['book']}, page {h['page']}]"
        else:
            label = f"[{h['book']}, page unknown]"
        parts.append(f"{label}\n{h['text']}")
    return "\n\n---\n\n".join(parts)


def page_note(candidate):
    entry = candidate.payload
    return f"p.{entry['page']}" if entry.get("page_confirmed") else "page unknown"


def run(question):
    # Title lookup searches every recipe in the recipe index; only the
    # LLM fallback below is limited to hits within MAX_DISTANCE.
    hits = retrieve(question)
    relevant = within_distance(hits)
    found, source = find_recipes(question, hits)
    wants = bool(WANTS_RECIPE_RE.search(question))
    asking = not wants and bool(QUESTION_RE.search(question)) and bool(DETAIL_RE.search(question))

    # Diagnostic comparison, not used for the actual decision below.
    # Prints what a pure-embedding-distance approach would have guessed,
    # so real queries can be checked for agreement/disagreement over time
    # before considering whether to trust this signal for anything.
    if cli.DEBUG:
        semantic_guess = semantic_top_recipe_guess(relevant)
        semantic_title = (extract_title(semantic_guess["text"], semantic_guess["book"])
                          if semantic_guess else "(too close to call)")
        print(f"[debug] semantic-only guess: {semantic_title}  |  title lookup in the {source}: "
              f"{found.kind} {[c.title for c in found.matches] or ''}, typos read as {found.typos or '(none)'}, "
              f"books named: {found.books or '(none)'}, via variations: {found.via or '(none)'}")

    # Only a title the question names in full is shown directly; a
    # question naming one is answered from it. A near miss ("partial")
    # is offered if the recipe is what's being asked for. Otherwise it
    # goes to the model with the closest chunks, since a question can
    # mention a dish in passing ("what goes with banana bread?") without
    # naming a recipe.
    header_matches = found.matches if found.kind == "match" else []
    if header_matches and asking:
        return about_several(header_matches, question)

    warnings = []
    if len(header_matches) == 1:
        c = header_matches[0]
        text = candidate_text(c)
        if text:
            return AskResult("recipe", question, recipe=c, text=text, via=found.via)
        warnings.append(_stale(c))

    if len(header_matches) > 1:
        if wants:
            # "show me a chocolate chip cookie recipe": every recipe of the
            # dish, not just the titles closest to the words typed (2 of 15).
            # The closest still come first.
            widened = _every_one_of_the_dish(question, header_matches + found.rest)
            if widened:
                return widened
        return AskResult("choices", question, choices=header_matches, more=found.more, via=found.via,
                         rest=found.rest)

    if wants and not header_matches:
        closest = _closest(question, found)
        if closest is not None:
            return closest

    # No direct recipe title match, fall through to the LLM for passing
    # mentions, "similar to" style questions, or content_type="unknown"
    # books that have no recipe-aware chunking profile. Only the closest
    # LLM_CONTEXT_K hits get sent, keeping the prompt (and generation time)
    # small even though we searched more broadly above. A book the
    # question names is the only one it's answered from.
    if found.books:
        relevant = [h for h in relevant if h["book"] in found.books]
    if not relevant:
        return AskResult("nothing", question, warnings=warnings)
    llm_hits = relevant[:LLM_CONTEXT_K]
    context = build_context(llm_hits)
    user_prompt = f"Cookbook excerpts:\n\n{context}\n\nQuestion: {question}"

    answer, seconds, unchecked = _answer(user_prompt, llm_hits, question)
    return AskResult("answer", question, answer=answer, sources=llm_hits,
                     generation_time=seconds, warnings=warnings, unchecked=unchecked)


def _every_one_of_the_dish(question, closest):
    """A "which one?" list of every recipe with the dish's words in its
    title or labels (title_lookup.list_titles), the closest first; None
    when that adds nothing to closest."""
    candidates, _ = load_candidates([])
    seen = {c.key for c in closest}
    extra = [c for c in list_titles(question, question, candidates) if c.key not in seen]
    if not extra:
        return None
    every = closest + extra
    return AskResult("choices", question, choices=every[:MAX_LISTED], more=len(every[MAX_LISTED:]),
                     rest=every[MAX_LISTED:], heading=f"You have {len(every)} recipes like that. Which one?")


def _closest(question, found):
    """For a request to see a recipe that names none in full: the one
    plainly closest title, else the titles with all of its words (in
    the book it names), else the near misses to pick from; None if there
    are none."""
    if found.kind == "partial" and found.clear is not None:
        shown = show(found.clear, question)
        if shown.kind == "recipe":
            shown.note, shown.via = CLOSEST, found.via
        return shown
    candidates, _ = load_candidates([])
    listed = list_titles(question, question, candidates)
    if len(listed) == 1:
        shown = show(listed[0], question)
        if shown.kind == "recipe":
            shown.note = CLOSEST
        return shown
    if listed:
        return AskResult("choices", question, choices=listed[:MAX_LISTED], more=len(listed[MAX_LISTED:]),
                         heading=CLOSEST_SEVERAL, rest=listed[MAX_LISTED:])
    if found.kind == "partial":
        return AskResult("choices", question, choices=found.matches, more=found.more, heading=DID_YOU_MEAN,
                         via=found.via, rest=found.rest)
    return None


def more(rest, start):
    """The next MAX_LISTED of a "which one?" list (rest: the Candidates
    not shown yet), numbered from start."""
    return AskResult("choices", "more", choices=rest[:MAX_LISTED], more=len(rest[MAX_LISTED:]),
                     rest=rest[MAX_LISTED:], start=start)


def list_recipes(what, question):
    """Every recipe with what ("pumpkin pie") in its title, by book."""
    candidates, _ = load_candidates([])
    found = list_titles(what, question, candidates)
    if not found:
        return AskResult("said", question, heading=f"I couldn't find a recipe with {what.strip()} in its name.")
    plural = "" if len(found) == 1 else "s"
    return AskResult("choices", question, choices=found, heading=f"You have {len(found)} {what.strip()} recipe{plural}:")


def _answer(user_prompt, sources, question):
    """The model's answer from the excerpts, checked
    (actions/answer_checks.py). One that fails is sent back once with
    what was wrong; returns (answer, seconds, problems left), the
    problems saved with each model call too (models.CALLS "checks")."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}]
    response, seconds = models.chat("answer", messages=messages, options={"temperature": 0.2})
    answer = response["message"]["content"]
    problems = answer_checks.check(answer, sources, question)
    models.note_checks(problems)
    if not problems:
        return answer, seconds, []
    messages += [{"role": "assistant", "content": answer},
                 {"role": "user", "content": answer_checks.for_the_model(problems)}]
    response, more = models.chat("answer again", messages=messages, options={"temperature": 0.2})
    again = response["message"]["content"]
    left = answer_checks.check(again, sources, question)
    models.note_checks(left)
    return again, seconds + more, left


def _stale(candidate):
    return (f"[warning] '{candidate.title}' is in the recipe index but not the database; "
            f"run tools/build_recipe_index.py to update the index.")


def show(candidate, question=""):
    """A recipe that's already been found (picked from a list, say),
    shown as the book's exact text."""
    text = candidate_text(candidate)
    if text:
        return AskResult("recipe", question, recipe=candidate, text=text)
    return AskResult("nothing", question, warnings=[_stale(candidate)])


def about(candidate, question):
    """A question about one recipe ("how long does it chill?"),
    answered by the model from that recipe's text alone."""
    return about_several([candidate], question)


def about_several(candidates, question):
    """A question about the recipes it names, answered by the model from
    the text of the first ABOUT_MAX_RECIPES of them ("how long does
    whipped cream keep?" names every whipped cream). With one recipe,
    the result's recipe is that one."""
    sources, warnings = [], []
    for candidate in candidates[:ABOUT_MAX_RECIPES]:
        text = candidate_text(candidate)
        if not text:
            warnings.append(_stale(candidate))
            continue
        entry = candidate.payload or {}
        sources.append({"book": candidate.book, "page": entry.get("page", 0),
                        "page_confirmed": entry.get("page_confirmed", False), "distance": 0.0, "text": text})
    if not sources:
        return AskResult("nothing", question, warnings=warnings)
    about_what = " / ".join(c.title for c in candidates[:ABOUT_MAX_RECIPES])
    answer, seconds, unchecked = _answer(f"Cookbook excerpts:\n\n{build_context(sources)}\n\n"
                                         f"Question (about {about_what}): {question}", sources, question)
    return AskResult("answer", question, recipe=candidates[0] if len(candidates) == 1 else None,
                     answer=answer, sources=sources, generation_time=seconds, warnings=warnings,
                     unchecked=unchecked)


def variation_note(result):
    """"X is a variation of Y" for a recipe found through one of its
    variations, else ""."""
    c = result.recipe
    name = result.via.get(c.key) if c is not None else None
    return f"{name} is a variation of {c.title}; it's near the end." if name else ""


def choice_label(result, candidate):
    """A listed recipe's title, plus the variation it was listed for."""
    name = result.via.get(candidate.key)
    label = f"{candidate.title} (its {name} variation)" if name else candidate.title
    note = result.notes.get(candidate.key)
    return f"{label} - {note}" if note else label


def render(result):
    """The result as the command line shows it."""
    lines = [f"{w}\n" for w in result.warnings]
    if result.kind == "recipe":
        c = result.recipe
        lines += [f"{line}\n" for line in (result.note, variation_note(result)) if line]
        lines += [f"Found this directly in {c.book} ({page_note(c)}), showing the exact text:\n",
                  result.text,
                  "\n(matched instantly, no generation needed)"]
    elif result.kind == "choices":
        choices = result.choices
        total = len(choices) + result.more
        lines.append((result.heading or f"I found {total} recipes matching \"{result.question}\". "
                                         "Which one did you mean?") + "\n")
        lines += [f"  {i}. {choice_label(result, c)}  ({c.book}, {page_note(c)})"
                  for i, c in enumerate(choices, 1)]
        if result.more:
            lines.append(f"  ...and {result.more} more.")
        if result.footer:
            lines.append(result.footer)
        first = choices[0]
        # The same name in two books: naming the book picks one.
        same_name = sum(c.title.lower() == first.title.lower() for c in choices) > 1
        example = f"{first.title.lower()} from {first.book}" if same_name else first.title.lower()
        lines += ["\nRun again with a more specific name (or the book's name) to see the full recipe, e.g.:",
                  f'  python3 query.py "recipe for {example}"',
                  "\n(matched instantly, no generation needed)"]
    elif result.kind == "nothing":
        lines.append("I couldn't find anything relevant to that in your cookbooks.")
    elif result.kind == "said":
        lines.append(result.heading)
    elif result.kind == "answer":
        lines += [result.answer,
                  *([answer_checks.for_her(result.unchecked)] if result.unchecked else []),
                  f"\n(generation took {result.generation_time:.2f}s)",
                  "--- Retrieved from ---"]
        for h in result.sources:
            page_label = f"p.{h['page']}" if h["page_confirmed"] else "page unknown"
            lines.append(f"  {h['book']}, {page_label} (distance {h['distance']:.3f})")
    return "\n".join(lines)
