# CookbookAI

[![CI](https://github.com/lcdavis58-dotcom/cookbookAI/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/lcdavis58-dotcom/cookbookAI/actions/workflows/ci.yml)

Version 1.2.0

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

Every message is saved as it's sent (in `chats/`), so a chat can be picked up later: `python3 chat.py` offers to continue the latest one and to answer a message that never got a reply. `--new` starts a new chat, `--list` lists them, `--open N` opens one; in a chat, `/help` lists the commands, and `/flag` marks the last reply as wrong (see Flagged replies below). Plain rules handle the common follow-ups; anything else goes to the chat model, and when it's unclear what you mean, it asks.

In a chat, "what pumpkin pie recipes do I have" lists every recipe with those words in its title, by book, and a general name like "pie crust" lists every recipe of that kind, whatever the book calls it. A dish type like "cookies" or "soup" also finds recipes whose titles don't say so ("Brown Butter Snickerdoodles"): each recipe is labeled with its dish types when the index is built (see [Dish types](#dish-types)). "Show me a chocolate chip cookie recipe" offers every one you have, not just the closest titles. "More" shows the rest of a long list, numbered on from it. With a recipe on screen, "what about the extra-thick one" shows another recipe of that dish, and "show me the one from dessert person" shows that book's.

Lists can be filtered by an ingredient: "do any of these use half and half" lists the ones that do and says how many don't, "which ones don't use eggs" or "without nuts" lists the ones that don't, and a dish and an ingredient work in one go ("a pumpkin pie without half and half", "do I have a whipped cream recipe that uses chocolate"). An ingredient counts wherever it is: in a crust or other sub-recipe the recipe calls for ("in All-Buttah Pie Dough"), on an optional line, as one choice of a line ("heavy cream or half-and-half", so it can do without it), or in the title ("Chocolate Whipped Cream" uses cocoa). A general name finds its kinds ("chocolate" finds bittersweet chocolate and chocolate chips), except the ones that are different foods (white chocolate, `word_lists/universal/ingredient_varieties.json`). "Something with a pineapple flavor" lists the recipes with pineapple in the title.

More than 30 recipes ("show me a cookie recipe" finds about 200) and it asks you to narrow them down, suggesting the title words and books they have most of. Answer with one of those or anything else, and it's read within the same recipes: "a chocolate chip one", "with peanut butter", "no nuts", "from dessert person", or "show them all". Narrowing again keeps what you said before.

**Ask about a recipe** (`query.py`): finds a recipe by its title (forgiving of plurals, accents, typos, filler words and words written apart or together, "butter cream" for "Buttercream"; add "from <book>" to pick a book, misspelled, shortened or as an acronym like "sfah") or by semantic search, and answers using only the text of your books, with book and page citations. A variation printed inside a recipe finds that recipe, and the reply says so ("Brown Butter Cream Cheese Frosting is a variation of Classic Cream Cheese Frosting"). A question that names a recipe ("what can I substitute for buttermilk in the pancakes?") is answered from that recipe's text instead of showing it. When no title matches exactly, the closest one is shown if it's clearly the closest.

```
python3 query.py "What page has the recipe for sweet tart dough?"
```

**Scale a recipe** (`scale.py`): by a multiplier, to a target yield, to a pan size, or to fit an ingredient you're short on. Amounts are converted to measuring tools you actually own, and ingredients that shouldn't scale linearly are flagged. A yield you state ("it usually feeds 5", "feeds five") is used over the recipe's own, and an amount you have is compared in its own unit (1 egg against the eggs, not their grams). A line naming two ingredients ("3 large eggs plus 1 large egg yolk", "lemon zest plus 1 teaspoon juice") scales both. Things that only come whole (`ingredient_rules/whole_items.json`) are rounded to whole eggs, cans, jars or pinches, with the exact amount in a note, and a crust isn't scaled at all, with a note that more or less filling usually means a different pan.

```
python3 scale.py "please double the classic whipped cream recipe"
python3 scale.py "the chocolate whipped cream feeds 6, I need 10"
python3 scale.py "classic whipped cream needs 2 eggs, I only have 1"
```

**Find recipes from what you have** (`match.py`): lists recipes that use what you name, the ones using the most of it first, then the ones using the rarer of your ingredients (pumpkin before heavy cream), then the ones missing the least. A recipe has to use all of one or two ingredients, or two-thirds of a longer list; if none do, it says so and shows the closest. Pantry staples (`word_lists/universal/pantry_staples.json`) are assumed on hand, and don't count toward how much of your list a recipe uses. A recipe that calls for another of the book's recipes (a crust, a curd, a sauce) counts it as on hand if you have it, have a general form of it ("pie crust" for a specific pie dough), or can make it from what you have. Misspelled ingredients ("cinamon") are corrected, and the correction is printed first.

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

When it asks you to narrow a long list down, its suggestions can be tapped too. Under each reply is a small grey flag: tap it to say the reply was wrong, with an optional note on what was wrong. A flagged reply's flag turns red (tap it again to take the flag back), and green once the problem is fixed.

There's no sign-up page: `tools/add_user.py` also has `--list` and `--remove NAME`. Changing a password signs that account out everywhere. Each account's chats are in `chats/users/<name>/`, separate from the command line's in `chats/`.

**Reaching it from outside your home:** don't forward a router port to it. Use something that gates access first; [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/) with an Access email allowlist works, and connects outward from your machine. Run `python3 serve.py --https`, without `--lan`, which also stops the login cookie being sent without HTTPS. Note that your chats and recipe text then pass through Cloudflare.

## Flagged replies

Replies flagged as wrong, on the website or with `/flag`, are saved in `flags/`, one file each, apart from the chats. Each one keeps everything needed to understand it, even after its chat is deleted: the whole chat up to the flagged reply, the note, what the chat was focused on, how each message was routed and how long the model took, the version, the model, and when the recipe index was built.

```
python3 tools/flagged.py                               # write the summaries, print how many are open
python3 tools/flagged.py handled ID "what covers it"   # a version or a test, e.g. "1.1.2"
python3 tools/flagged.py reopen ID                     # undo a mistaken "handled"
```

Each run rewrites `flags/open_flags.md` (still to fix) and `flags/handled_flags.md`, so they can be read without running it again. Marking a flag handled turns its flag green on the website. Like the chats, flags quote the books, so they stay out of the repository.

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
├── flags/        <- replies flagged as wrong, and their summaries (FLAGS_DIR)
├── extracted/    <- saved PDF extractions, created by ingest.py
├── users.json    <- website accounts, password hashes only (USERS_PATH)
├── web_secret.key <- signs website logins, created on first run (WEB_SECRET_PATH)
└── cookbooks/    <- your PDFs (not included)
```

Book titles and PDF filenames are in `BOOK_FILES` in `common/config.py`, and the books to ingest in `INGEST_BOOKS` in `ingest.py`. To keep the PDFs somewhere else, set the `COOKBOOKS_DIR` environment variable. `COOKBOOK_DATA_DIR` moves everything the app writes (`chroma_db/`, `recipe_index.json`, `chats/`, `flags/`, `extracted/`) to another folder; keep it out of a synced folder like OneDrive or Dropbox, which would keep re-uploading a live database. `EXTRACT_DIR`, `CHATS_DIR` and `FLAGS_DIR` move just those. Then:

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

### Dish types

Building the index (`ingest.py` or `tools/build_recipe_index.py`) also labels each recipe with its dish types ("cookie", "soup", "cheesecake"), chosen by a model, one recipe at a time, from `word_lists/universal/dish_types.json`. That model is `LABEL_MODEL` in `common/config.py` (`qwen2.5:14b`; `ollama pull qwen2.5:14b`), bigger than the chat's because it runs once per recipe rather than while you wait, and it got far more right on a hand-checked set (`testing/evals/dish_label_key.json`, scored with `tools/diagnostics/dish_labels.py --key`). Without it, the chat model labels them, with a warning. When the model gives no type, or Ollama isn't running, a title whose last word names a type ("...Snickerdoodles") gets that type. Some types bring another with them: chicken, turkey, beef, pork, lamb and seafood are meat too, and a salsa is a dip. The labels are kept in `dish_labels.json` in the data folder, so a rebuild only asks about recipes that changed. Editing one type's description asks again only the recipes that have that type or whose titles name it (minutes); editing its title words, keywords or the types it brings with it asks nothing again; changing the prompt or the model labels everything again (about 80 minutes for 2,700 recipes with `qwen2.5:14b` on an RTX 2070 Super). A type can be kept only when the title or chapter names it (`needs_name`: a doughnut always says so). Recipes found wrong in real use get their types set by hand in `word_lists/universal/dish_label_overrides.json`, which replaces what the model and the rules gave and survives every relabel. `tools/diagnostics/dish_labels.py --holdout` scores the labels against `testing/evals/dish_label_holdout.json`, 50 recipes picked at random and never tuned to (38 right, 10 with an extra wrong type, 2 wrong, 2026-11-25). If Ollama isn't running, the index is still built, with the labels kept from before. `tools/diagnostics/dish_labels.py` shows how they came out: how many recipes have each type, and the ones where the model and the title disagree.

### Evals

`tools/run_evals.py` runs a scored set of chat messages (`testing/evals/cases.json`) against your books, database and model, and checks what came of each one: the route, the recipe or list shown, the scale factor, the books an answer cites. It prints the score, how many messages the model routed rather than rules, and the model's time, and saves each run in `evals/` in the data folder, named by version and model, so runs can be compared. Set `CHAT_MODEL` to score another model, and `--repeat 3` to ask each case three times (model answers vary). Cases are added with each version.

## Project layout

| Path | Purpose |
|---|---|
| `ingest.py`, `ingest_utils/` | PDF → lines with layout (saved) → recipe-aware chunks → Chroma |
| `actions/` | What `query.py`, `scale.py` and `match.py` do, and filtering a list by an ingredient, each returning its result as data plus the text the command line prints; the scripts are thin wrappers |
| `chat.py`, `chat/` | The chat: the terminal loop, routing each message to an action (rules first, then the model), what a chat remembers (the recipe it's on, the last numbered list, a question waiting for an answer), its reply wording, saving it to `chats/`, and replies flagged as wrong (`flags/`) |
| `serve.py`, `web/` | The website: sign-in, the chat pages, replies worked out in the background |
| `query.py`, `query_utils/` | Retrieval, split-recipe reassembly, title lookup over the recipe index |
| `scale.py`, `scale_utils/` | Ingredient parsing, scale factors, measurement display |
| `match.py`, `match_utils/` | Ingredient name normalization, the recipe index (built at ingest, with sub-recipe links and dish types), matching, whether a recipe uses an ingredient |
| `books/` | Per-book settings, the shared engine that applies them, and ingredient line styles |
| `common/` | Shared config, embeddings, CLI helpers |
| `word_lists/`, `ingredient_rules/` | Data files for detection and scaling rules |
| `tools/` | Maintenance scripts; `tools/diagnostics/` for seeing how ingest and the parsers read a book |
| `testing/` | Unit tests (`python3 -m unittest discover -s testing/unit -t .`), local tests that need the PDFs, database and model (`testing/local/`), and a local-only scratch folder (see `testing/README.md`) |

## Tests

The unit tests (`testing/unit/`) run in CI on every pull request and cover 80% of the code. The local tests (`testing/local/`) need the cookbook PDFs, the database built from them and the model, so they can't run in the cloud: the books are copyrighted and stay on your own machine. With them included, coverage is 91% (measured for 1.1.1).

## Adding a book

Most books need only settings. Run `tools/diagnostics/book_report.py "<title>" --anchor "<yield line regex>"` to see the type size of the lines just above each yield line ("Makes ...", "YIELD: ..."), then write a `books/` module giving `TITLE_MIN_SIZE`, `YIELD_RE` and `INGREDIENT_STYLE` (one of the styles in `books/line_styles.py`), plus any of the other settings listed in `books/__init__.py` that the book needs. `books/fearless_baker.py` is a complete example. The shared engine (`books/engine.py`) does the rest; a module defines a function of its own only for something truly specific to the book (BraveTart's ingredient list end, for one).

Register the module in `books/__init__.py`, then add its title to `INGEST_BOOKS` in `ingest.py` (and to `BOOK_FILES` in `common/config.py` if it isn't there). Re-run `book_report.py` to check its recipes, groups and rejected lines, and `tools/diagnostics/structure_baseline.py compare` to check that a change didn't break the books already working.

## Releasing

1. In a pull request, change the `Version` line at the top of this README (and anywhere else listed in `PLACES` in `tools/check_version.py`). CI fails if the places disagree.
2. Once it's merged, tag the merge on `main` and push the tag:
   ```
   git switch main && git pull
   git tag v1.0.1
   git push origin v1.0.1
   ```
3. The Release workflow checks that the tag is on `main` and matches the version written, then publishes a GitHub release listing the pull requests merged since the last one.

## Roadmap

- **1.2.1:** check each answer against the excerpts it came from before showing it (every quantity is in the source, every cited book and page was among the sources given); reliability metrics from the saved chats and flags (how often the model is used rather than rules, model tool calls rejected, reply times, flags per version); a section of this README on reliability, evals and guardrails
- **1.3.0:** show chat replies word by word, lay recipes out more readably on the website
- **1.4.0:** a shopping list from the recipes you pick: their ingredients at the scale shown, combined across recipes, without pantry staples
- **1.5.0 (tentative):** use the technique and "why" chapters of the books about cooking (Salt Fat Acid Heat, Flour Water Salt Yeast, Ratio, The Food Lab), and answer general cooking questions ("what's the difference between baking soda and baking powder?")
- Move from the Raspberry Pi to a GPU machine
- compare recipes, mark recipes as favorites so they are prioritized when retrieving recipes
- **Ongoing:** the scored eval set (`tools/run_evals.py`, see [Evals](#evals)), started in 1.2.0 from the existing tests, with cases added for each version above where it applies

## Note

Cookbook PDFs are copyrighted and are not part of this repository. Use books you own.
