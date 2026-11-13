# CookbookAI

[![CI](https://github.com/lcdavis58-dotcom/cookbookAI/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/lcdavis58-dotcom/cookbookAI/actions/workflows/ci.yml)

Version 1.0.0

A local, private assistant for your own cookbooks. It reads cookbook PDFs into a vector database, then lets you ask questions about the recipes, scale them up or down, and find what you can make, in a chat on the command line or a website for your household. All of it runs on your own hardware with [Ollama](https://ollama.com) and [Chroma](https://www.trychroma.com); nothing is sent to a cloud service unless you choose to reach the website through one (see [The website](#the-website)).

Currently supported books (each has its own settings in `books/`):
- *The Book On Pie*
- *Dessert Person*
- *BraveTart*
- *The Fearless Baker*
- *What's For Dessert*
- *The Cookie Book*
- *Savory Baking*
- *Momofuku Milk Bar*
- *Genius Desserts*
- *Genius Recipes*
- *The Complete Cooking For Two Cookbook*
- *How to Cook Everything Vegetarian*
- *The Food Lab*
- *Salt Fat Acid Heat*
- *Flour Water Salt Yeast*
- *Ratio*

## What it does

**Chat** (`chat.py`): all of the below in one conversation, with follow-ups. Answer "which one?" with a number or part of the name, scale what's on screen again ("now halve it" builds on the last scale; "back to the original" undoes it), change the ingredients you searched ("add lemons", "without the pecans"), or ask about the recipe you're looking at.

```
python3 chat.py
> double the whipped cream
I found 2 recipes that could be. Which one? ...
> the classic one
Scaling 'Classic Whipped Cream' (Full Batch) from The Book On Pie... 2.0x
> now halve it
0.5x the 2x version = 1x the recipe as written
> what can I make with pecans and cream cheese
> add lemons
> #1
> how long does it chill?
```

Every message is saved as it's sent (in `chats/`), so a chat can be picked up later: `python3 chat.py` offers to continue the latest one and to answer a message that never got a reply. `--new` starts a new chat, `--list` lists them, `--open N` opens one; in a chat, `/help` lists the commands. Plain rules handle the common follow-ups; anything else goes to the chat model, and when it's unclear what you mean, it asks.

In a chat, "what pumpkin pie recipes do I have" lists every recipe with those words in its title, by book, and a general name like "pie crust" lists every recipe of that kind, whatever the book calls it.

**Ask about a recipe** (`query.py`): finds a recipe by its title (forgiving of plurals, accents, typos and filler words; add "from <book>" to pick a book, misspelled, shortened or as an acronym like "sfah") or by semantic search, and answers using only the text of your books, with book and page citations.

```
python3 query.py "What page has the recipe for sweet tart dough?"
```

**Scale a recipe** (`scale.py`): by a multiplier, to a target yield, to a pan size, or to fit an ingredient you're short on. Amounts are converted to measuring tools you actually own, and ingredients that shouldn't scale linearly are flagged.

```
python3 scale.py "please double the classic whipped cream recipe"
python3 scale.py "the chocolate whipped cream feeds 6, I need 10"
python3 scale.py "classic whipped cream needs 2 eggs, I only have 1"
```

**Find recipes from what you have** (`match.py`): lists recipes that use what you name, the ones using the most of it first, then the ones missing the least. A recipe has to use all of one or two ingredients, or two-thirds of a longer list; if none do, it says so and shows the closest. Pantry staples (`word_lists/universal/pantry_staples.json`) are assumed on hand, and don't count toward how much of your list a recipe uses. A recipe that calls for another of the book's recipes (a crust, a curd, a sauce) counts it as on hand if you have it, have a general form of it ("pie crust" for a specific pie dough), or can make it from what you have. Misspelled ingredients ("cinamon") are corrected, and the correction is printed first.

```
python3 match.py "pecans, cream cheese, lemons"
```

Add `-d` to any of these commands for debug output.

## The website

The same chat in a browser (`serve.py`), for phones and computers: each person signs in and has their own chats, which they can rename (the pencil beside the title) or delete (the ✕ in the chat list). Replies are worked out in the background so a locked phone or lost signal doesn't lose one, and lists and ingredients can be tapped instead of typed.

```
pip install flask flask-login flask-wtf waitress
python3 tools/add_user.py NAME     # create an account, or change its password
python3 serve.py                   # http://127.0.0.1:8000, this computer only
python3 serve.py --lan             # also reachable from your home network
```

There's no sign-up page: `tools/add_user.py` also has `--list` and `--remove NAME`. Changing a password signs that account out everywhere. Each account's chats are in `chats/users/<name>/`, separate from the command line's in `chats/`.

**Reaching it from outside your home:** don't forward a router port to it. Use something that gates access first; [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) with an Access email allowlist works, and connects outward from your machine. Run `python3 serve.py --https`, without `--lan`, which also stops the login cookie being sent without HTTPS. Note that your chats and recipe text then pass through Cloudflare.

## Setup

```
pip install pymupdf chromadb ollama
ollama pull nomic-embed-text
ollama pull qwen2.5:7b         # the chat model, see below
```

Expected layout:

```
CookbookAI/
├── app/          <- this repository
├── chroma_db/    <- created by ingest.py
├── chats/        <- saved chats, one file each (CHATS_DIR overrides it)
├── extracted/    <- saved PDF extractions, created by ingest.py
├── users.json    <- website accounts, password hashes only (USERS_PATH)
├── web_secret.key <- signs website logins, created on first run (WEB_SECRET_PATH)
└── cookbooks/    <- your PDFs (not included)
```

Book titles and PDF filenames are in `BOOK_FILES` in `common/config.py`, and the books to ingest in `INGEST_BOOKS` in `ingest.py`. To keep the PDFs somewhere else, set the `COOKBOOKS_DIR` environment variable. `COOKBOOK_DATA_DIR` moves everything the app writes (`chroma_db/`, `recipe_index.json`, `chats/`, `extracted/`) to another folder; keep it out of a synced folder like OneDrive or Dropbox, which would keep re-uploading a live database. `EXTRACT_DIR` and `CHATS_DIR` move just those. Then:

```
python3 ingest.py               # build or update the database
python3 tools/build_recipe_index.py   # rebuild only the recipe index, no re-ingest
python3 tools/clear_chroma.py   # wipe the database and index
```

Ingest runs in stages: extract (PDF to lines with layout, saved and reused until the PDF changes), structure (lines to recipe chunks), embed (only chunks whose text changed), index. Re-running it after a parsing change only embeds what changed, and replaces each book's old chunks.

Run every script from `app/`.

After cloning, run `git config core.hooksPath .githooks` once. Its pre-commit hook refuses a commit that includes anything `.gitignore` keeps out (a PDF, the database, website accounts, a key), even one added with `git add -f`. CI runs the same check.

### Models

One chat model, `CHAT_MODEL` in `common/config.py` (`qwen2.5:7b`), does every model job: answering questions, reading scaling requests, and routing chat messages. Set the `CHAT_MODEL` environment variable to try another. It's slow on a Raspberry Pi's CPU; most common requests are handled by plain rules and never reach it.

A model call that runs past `MODEL_TIMEOUT` seconds (300 by default) is given up on, and the message stays saved to try again.

Every chat reply saves how long each model call took, and `tools/diagnostics/model_timing.py` summarizes them per model and job, for comparing a larger model's accuracy against its wait.

## Project layout

| Path | Purpose |
|---|---|
| `ingest.py`, `ingest_utils/` | PDF → lines with layout (saved) → recipe-aware chunks → Chroma |
| `actions/` | What `query.py`, `scale.py` and `match.py` do, each returning its result as data plus the text the command line prints; the scripts are thin wrappers |
| `chat.py`, `chat/` | The chat: the terminal loop, routing each message to an action (rules first, then the model), what a chat remembers (the recipe it's on, the last numbered list, a question waiting for an answer), its reply wording, and saving it to `chats/` |
| `serve.py`, `web/` | The website: sign-in, the chat pages, replies worked out in the background |
| `query.py`, `query_utils/` | Retrieval, split-recipe reassembly, title lookup over the recipe index |
| `scale.py`, `scale_utils/` | Ingredient parsing, scale factors, measurement display |
| `match.py`, `match_utils/` | Ingredient name normalization, the recipe index (built at ingest, with sub-recipe links), matching |
| `books/` | Per-book settings, the shared engine that applies them, and ingredient line styles |
| `common/` | Shared config, embeddings, CLI helpers |
| `word_lists/`, `ingredient_rules/` | Data files for detection and scaling rules |
| `tools/` | Maintenance scripts; `tools/diagnostics/` for seeing how ingest and the parsers read a book |
| `testing/` | Unit tests (`python3 -m unittest discover testing`) and a local-only scratch folder (see `testing/README.md`) |

## Adding a book

Most books need only settings. Run `tools/diagnostics/book_report.py "<title>" --anchor "<yield line regex>"` to see the type size of the lines just above each yield line ("Makes ...", "YIELD: ..."), then write a `books/` module giving `TITLE_MIN_SIZE`, `YIELD_RE` and `INGREDIENT_STYLE` (one of the styles in `books/line_styles.py`), plus any of the other settings listed in `books/__init__.py` that the book needs. `books/fearless_baker.py` is a complete example. The shared engine (`books/engine.py`) does the rest; a module defines a function of its own only for something truly specific to the book (BraveTart's ingredient list end, for one).

Register the module in `books/__init__.py`, then add its title to `INGEST_BOOKS` in `ingest.py` (and to `BOOK_FILES` in `common/config.py` if it isn't there). Re-run `book_report.py` to check its recipes, groups and rejected lines, and `tools/diagnostics/structure_baseline.py compare` to check that a change didn't break the books already working.

## Roadmap

- **1.0.1:** clean up oddly read ingredient names, link the remaining sub-recipes, ingredient parser fixes
- **1.0.2:** stop reading some sentences as ingredient lists or scaling requests
- **1.1.0:** filter a list by an ingredient, search by flavor, search by dish and ingredient together
- **1.2.0:** show chat replies word by word, lay recipes out more readably on the website
- **1.3.0 (tentative):** use the technique and "why" chapters of the books about cooking (Salt Fat Acid Heat, Flour Water Salt Yeast, Ratio, The Food Lab)
- Move from the Raspberry Pi to a GPU machine
- **CI with GitHub Actions** (no set version): run the unit tests on every push and pull request
- **More unit tests** (no set version), then raise CI's coverage floor: first `scale_utils/pan_scaling.py`, `books/line_styles.py` and `match_utils/recipe_index.py` (each about a quarter covered), then the command-line wrappers `chat.py`, `serve.py`, `query.py`, `scale.py` and `match.py` (none yet)

## Note

Cookbook PDFs are copyrighted and are not part of this repository. Use books you own.
