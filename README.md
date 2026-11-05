# CookbookAI

A local, private assistant for your own cookbooks. It reads cookbook PDFs into a vector database, then lets you ask questions about the recipes and scale them up or down. All of it runs on your own hardware with [Ollama](https://ollama.com) and [Chroma](https://www.trychroma.com); nothing is sent to a cloud service.

Currently supported books (each has its own settings in `books/`):
- *The Book On Pie*
- *Dessert Person*
- *BraveTart*
- *The Fearless Baker*
- *What's For Dessert*
- *The Cookie Book*
- *Savory Baking*
- *Momofuku Milk Bar*

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
├── extracted/    <- saved PDF extractions, created by ingest.py
└── cookbooks/    <- your PDFs (not included)
```

Book titles and PDF filenames are in `BOOK_FILES` in `common/config.py`, and the books to ingest in `INGEST_BOOKS` in `ingest.py`. To keep the PDFs or the extractions somewhere else, set the `COOKBOOKS_DIR` or `EXTRACT_DIR` environment variable. Then:

```
python3 ingest.py               # build or update the database
python3 tools/build_recipe_index.py   # rebuild only the recipe index, no re-ingest
python3 tools/clear_chroma.py   # wipe the database and index
```

Ingest runs in stages: extract (PDF to lines with layout, saved and reused until the PDF changes), structure (lines to recipe chunks), embed (only chunks whose text changed), index. Re-running it after a parsing change only embeds what changed, and replaces each book's old chunks.

Run every script from `app/`.

### Models

`llama3.2:1b` is fast enough to run on a Raspberry Pi's CPU. `qwen2.5:7b` is much more accurate for scaling, but slow without a GPU.

## Project layout

| Path | Purpose |
|---|---|
| `ingest.py`, `ingest_utils/` | PDF → lines with layout (saved) → recipe-aware chunks → Chroma |
| `query.py`, `query_utils/` | Retrieval, split-recipe reassembly, title matching |
| `scale.py`, `scale_utils/` | Ingredient parsing, scale factors, measurement display |
| `match.py`, `match_utils/` | Ingredient name normalization, the recipe index (built at ingest), matching |
| `books/` | Per-book settings, the shared engine that applies them, and ingredient line styles |
| `common/` | Shared config, embeddings, CLI helpers |
| `word_lists/`, `ingredient_rules/` | Data files for detection and scaling rules |
| `tools/` | Maintenance scripts; `tools/diagnostics/` for seeing how ingest and the parsers read a book |
| `testing/` | Tests to come, and a local-only scratch folder (see `testing/README.md`) |

## Adding a book

Most books need only settings. Run `tools/diagnostics/book_report.py "<title>" --anchor "<yield line regex>"` to see the type size of the lines just above each yield line ("Makes ...", "YIELD: ..."), then write a `books/` module giving `TITLE_MIN_SIZE`, `YIELD_RE` and `INGREDIENT_STYLE` (one of the styles in `books/line_styles.py`), plus any of the other settings listed in `books/__init__.py` that the book needs. `books/fearless_baker.py` is a complete example. The shared engine (`books/engine.py`) does the rest; a module defines a function of its own only for something truly specific to the book (BraveTart's ingredient list end, for one).

Register the module in `books/__init__.py`, then add its title to `INGEST_BOOKS` in `ingest.py` (and to `BOOK_FILES` in `common/config.py` if it isn't there). Re-run `book_report.py` to check its recipes, groups and rejected lines, and `tools/diagnostics/structure_baseline.py compare` to check that a change didn't break the books already working.

## Roadmap

- Add the remaining books
- Check sub-recipes when matching ingredients (a recipe that calls for "1 recipe Brioche Dough" also needs that recipe's ingredients), designed once every book's way of referring to its own recipes is known
- Forgiving recipe title lookup for scaling ("chocolate chip cookies" finding "Chocolate Chip Cookie")
- Move from the Raspberry Pi to a GPU machine
- A locally hosted web interface for household use

## Note

Cookbook PDFs are copyrighted and are not part of this repository. Use books you own.
