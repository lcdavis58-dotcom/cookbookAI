"""
Ask a question against your ingested cookbooks.

Run:
    python3 query.py "What page has a recipe for chicken tikka masala?"
    python3 query.py -d "recipe for sweet tart dough"    # with debug output

Where things live:
    actions/ask.py                   the steps, the prompt, and what this prints
    query_utils/retrieval.py        vector search, split-recipe reassembly
    query_utils/recipe_matching.py   titles, yield lines
    query_utils/title_lookup.py      which recipe a question names

Requires the same packages as ingest.py, plus your chat model pulled, e.g.:
    ollama pull llama3.2:1b
"""

from actions import ask
from common import cli

if __name__ == "__main__":
    question, cli.DEBUG = cli.parse_cli("Ask a question against your ingested cookbooks.")
    print(ask.render(ask.run(question)))
