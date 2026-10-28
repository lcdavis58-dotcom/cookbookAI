# CookbookAI

A local, private assistant for your own cookbooks. It reads cookbook PDFs into a vector database, then lets you ask questions about the recipes and scale them up or down. All of it runs on your own hardware with [Ollama](https://ollama.com) and [Chroma](https://www.trychroma.com); nothing is sent to a cloud service.

Currently supported books (each has its own format rules in `books/`):
- *The Book On Pie*
- *Dessert Person*

## What it does

**Ask about a recipe** (`query.py`): finds a recipe by its title or by semantic search, and answers using only the text of your books, with book and page citations.

```
python3 query.py "What page has the recipe for sweet tart dough?"
```

**Scale a recipe** (`scale.py`): by a multiplier, to a target yield, to a pan size, or to fit an ingredient you're short on. Amounts are converted to measuring tools you actually own, and ingredients that shouldn't scale linearly are flagged.

```
python3 scale.py "please double the classic whipped cream recipe"
python3 scale.py "the chocolate whipped cream feeds 6, I need 10"
python3 scale.py "classic whipped cream needs 2 eggs, I only have 1"
```

**Find recipes from what you have** (`match.py`): lists recipes you can make now, and ones missing just one thing, from the ingredients you name. Pantry staples (`word_lists/universal/pantry_staples.json`) are assumed on hand.

```
python3 match.py "pecans, cream cheese, lemons"
```

Add `-d` to any of these commands for debug output.

## Setup

```
pip install pymupdf chromadb ollama
ollama pull nomic-embed-text
ollama pull llama3.2:1b        # or a larger chat model, see below
```

Expected layout:

```
CookbookAI/
├── app/          <- this repository
├── chroma_db/    <- created by ingest.py
└── cookbooks/    <- your PDFs (not included)
```

PDF paths are set in `BOOKS` in `ingest.py`. Then:

```
python3 ingest.py               # build the database
python3 tools/clear_chroma.py   # wipe it before a full re-ingest
python3 tools/build_recipe_index.py   # rebuild only the recipe index, no re-ingest
```

Run every script from `app/`.

### Models

`llama3.2:1b` is fast enough to run on a Raspberry Pi's CPU. `qwen2.5:7b` is much more accurate for scaling, but slow without a GPU.

## Project layout

| Path | Purpose |
|---|---|
| `ingest.py`, `ingest_utils/` | PDF → text → recipe-aware chunks → Chroma |
| `query.py`, `query_utils/` | Retrieval, split-recipe reassembly, title matching |
| `scale.py`, `scale_utils/` | Ingredient parsing, scale factors, measurement display |
| `match.py`, `match_utils/` | Ingredient name normalization, the recipe index (built at ingest), matching |
| `books/` | Per-book format rules (recipe boundaries, titles, ingredient lines) |
| `common/` | Shared config, embeddings, CLI helpers |
| `word_lists/`, `ingredient_rules/` | Data files for detection and scaling rules |
| `tools/` | Maintenance scripts; `tools/diagnostics/` for seeing how ingest and the parsers read a book |
| `testing/` | Tests to come, and a local-only scratch folder (see `testing/README.md`) |

## Adding a book

Add a module to `books/` that implements that book's recipe-start detection, title extraction and ingredient-line parsing (the existing two are good templates). Register it in `books/__init__.py`, then add its PDF to `BOOKS` in `ingest.py`.

## Roadmap

- "What can I make?": find recipes from the ingredients you have on hand
- Move from the Raspberry Pi to a GPU machine
- A locally hosted web interface for household use

## Note

Cookbook PDFs are copyrighted and are not part of this repository. Use books you own.
