"""
How the chat words an action's result. It reuses the command line's
formatting (actions/*.render and their helpers) and changes only what
doesn't fit a conversation: "run again with ..." hints become "say a
number or the book", and match results are numbered so "the third one"
can be asked for.
"""

from actions import answer_checks, ask, match, scale

PICK_HINT = "Type a number, or part of the recipe's name or book."


MORE_HINT = 'Say "more" to see them.'


def _numbered(choices, more, label=lambda c: c.title, start=1):
    lines = [f"  {i}. {label(c)}  ({c.book})" for i, c in enumerate(choices, start)]
    if more:
        lines.append(f"  ...and {more} more. {MORE_HINT} Or add more of the name to narrow it down.")
    return lines


def ask_reply(result):
    lines = [f"{w}\n" for w in result.warnings]
    if result.kind == "recipe":
        c = result.recipe
        lines += [f"{line}\n" for line in (result.note, ask.variation_note(result)) if line]
        lines += [f"{c.title}, from {c.book} ({ask.page_note(c)}):\n", result.text]
    elif result.kind == "choices":
        total = len(result.choices) + result.more
        heading = result.heading or f"I found {total} recipes for that. Which one?"
        if result.start > 1:
            heading = "More of them:"
        lines += [heading + "\n",
                  *_numbered(result.choices, result.more, lambda c: ask.choice_label(result, c), result.start)]
        if result.footer:
            lines.append(result.footer)
        lines.append(f"\n{PICK_HINT}")
    elif result.kind == "answer":
        sources = []
        for h in result.sources:
            source = f"{h['book']}, " + (f"p.{h['page']}" if h["page_confirmed"] else "page unknown")
            if source not in sources:
                sources.append(source)
        lines += [result.answer, f"\n(From {'; '.join(sources)})"]
        if result.unchecked:
            lines.append(answer_checks.for_her(result.unchecked))
    elif result.kind == "said":
        lines.append(result.heading)
    else:
        lines.append("I couldn't find anything relevant to that in your cookbooks.")
    return "\n".join(lines)


def scale_reply(result):
    if result.kind == "choices":
        if result.partial:
            head = "I couldn't find a recipe by exactly that name. Did you mean one of these?\n"
        else:
            head = f"I found {len(result.choices) + result.more} recipes that could be. Which one?\n"
        return "\n".join([head, *_numbered(result.choices, result.more), f"\n{PICK_HINT}"])
    if result.kind == "pick_batch":
        lines = [f"{result.title} comes in more than one batch size. Which one?\n"]
        lines += [f"  - {name}" + (f" ({description})" if description else "")
                  for name, description in result.batches]
        return "\n".join(lines)
    return scale.render(result)


def match_reply(result):
    if result.kind != "matches":
        return match.render(result)
    lines = [match.describe_typos(result.corrections)] if result.corrections else []
    lines.append(f"You have: {', '.join(result.have)}  (plus pantry staples)")
    lines += [f"  ({note})" for note in result.assumptions]
    if result.only_partial and not result.page:
        lines.append(f"\n{match.ONLY_PARTIAL}")
    number = result.first_number - 1
    for heading, name in match.SECTIONS:
        results = getattr(result, name)
        shown = match.section_page(result, results)
        if not shown:
            continue
        lines.append(f"\n{heading} ({len(results)}){', continued' if result.page else ''}:")
        for r in shown:
            number += 1
            entry_lines = match.describe(r)
            entry_lines[0] = f"  {number}. {entry_lines[0].lstrip()}"
            lines += entry_lines
        left = match.left_after(result, results)
        if left:
            lines.append(f"  ...and {left} more. {MORE_HINT}")
    if number < result.first_number:
        lines.append("\nThat's all of them." if result.page else "\nI couldn't find any recipes that use those.")
    else:
        lines.append('\nTo see a recipe, type its number. To change your search, type "add" or "without" '
                     'and an ingredient, like "add lemons."')
    return "\n".join(lines)


def render(action, result):
    return {"ask": ask_reply, "scale": scale_reply, "match": match_reply}[action](result)
