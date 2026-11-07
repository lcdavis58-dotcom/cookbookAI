"""
The three things the assistant can do, each as a run() that returns its
result as data and a render() that turns a result into the text the
command line prints:

    actions/ask.py      a question about a recipe       (query.py)
    actions/scale.py    scaling a recipe                (scale.py)
    actions/match.py    recipes from what you have      (match.py)

The scripts are thin wrappers: run(), then print(render()). Anything that
needs to act on a result (the chat, a web page) calls run() and reads the
result's fields instead of the printed text. Debug output (-d) that comes
before any result is still printed as the work happens.
"""
