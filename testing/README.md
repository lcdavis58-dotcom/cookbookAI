# testing/

Run everything from `app/`.

## one_off/
A local scratch folder for throwaway checks and their output. Everything in it except its README is git-ignored, because those files are usually built from real book text (see `one_off/README.md`).

The reusable diagnostic scripts (page and block dumps, ingredient frequency, parser traces) live in `tools/diagnostics/`.

## Unit tests (run by CI)
Automated tests go in `testing/unit/test_*.py`. Run them with `python3 -m unittest discover -s testing/unit -t .` (or `python3 -m pytest testing/unit` where pytest is installed). So far: `test_title_lookup.py` (`query_utils/title_lookup.py`) `test_sub_recipes.py` (`match_utils/sub_recipes.py`, matching through sub-recipes) `test_typos.py` (`match_utils/typos.py`), `test_finding_recipes.py` (which recipes a search returns, and listing), `test_actions.py` (`actions/`), `test_chat_state.py`, `test_chat_router.py` and `test_chat_terminal.py` (`chat/`), `test_web.py` (the website, on temporary folders), `test_pan_scaling.py` (`scale_utils/pan_scaling.py`), `test_line_styles.py` (`books/line_styles.py`), `test_recipe_index.py` (`match_utils/recipe_index.py`, with a stand-in Chroma collection), `test_scripts.py` (the command-line scripts, run with their work replaced by stand-ins) and `test_known_gaps.py` (bugs not fixed yet, each skipped with the version planned to fix it; remove the skip in the fix). To see which lines the tests reach, install `requirements-dev.txt` and run `python3 -m coverage run -m unittest discover -s testing/unit -t .`, then `python3 -m coverage report` (or `coverage html` for a browsable `htmlcov/`); `.coveragerc` leaves out `testing/` and `tools/`. CI does the same, puts the table in each run's summary, saves the HTML report as an artifact, and fails if coverage drops below its floor. CI also lints with `python3 -m ruff check .` (rules in `ruff.toml`) and `bandit -r . -x ./testing`; both are in `requirements-dev.txt`, so run them before pushing. Test data must be invented recipe text in each book's format, never lines copied from the books, since this folder is published. Good next candidates (least covered first):
- `query_utils/retrieval.py`, with a stand-in collection as in `test_recipe_index.py`
- `books/*`: `find_recipe_starts`, `extract_title` and `parse_ingredient_line` (BraveTart, Flour Water Salt Yeast, Ratio and Savory Baking are under half covered), and `books/engine.py`
- `common/text_parsing.py` and `scale_utils/measurement_display.py`: pure functions, no model or database needed
- `scale_utils/ingredients.py`: grouping, line-wrap joining, the fallbacks in `line_fallbacks.py`

## Local tests (not run by CI)
`testing/local/` tests the real PDFs, database, index and model, so they run only on a machine that has them (set `COOKBOOKS_DIR` and `COOKBOOK_DATA_DIR`). Each test skips itself when what it needs is missing (`needs.py`), so on a machine with none of it they all skip. Run them with `python3 -m unittest discover -s testing/local -t .`.
- `test_pdfs.py`: what ingest's structure step makes of each book (recipe counts, known titles, recipes with no ingredients). A few seconds, no model. When a parser change alters a count on purpose, update the number in the same commit; `tools/diagnostics/structure_baseline.py` shows what changed.
- `test_index.py`: the real index and database with no model: listings, "what can I make", scaling by name, a replayed chat, and that the index has the same recipe counts as the PDFs (fails until the index is rebuilt after a parser change).
- `test_model.py`: the model's jobs (reading scaling requests, routing, answering) and replayed chats. A minute or so. The model isn't fully predictable, so `MODEL_REPEAT=5` asks each case 5 times to see how reliable it is. Known gaps are skipped with the version planned to fix them.

The repository is public: these tests hold only titles, counts and numbers, never book text.

## Before a push
`.githooks/pre-push` runs the unit tests as CI does (with empty data folders and no model, at CI's coverage floor, read from `ci.yml`), ruff and bandit, then `test_pdfs.py` and `test_index.py`. About 40 seconds. A failure stops the push; `git push --no-verify` skips it, and CI still checks. It tests the files in the folder, uncommitted changes included. Turn the hooks on once per clone with `git config core.hooksPath .githooks`; it uses the venv in `COOKBOOK_DATA_DIR` if there is one, with `requirements-dev.txt` installed. The model tests are left out (slow, and the model can be wrong by chance): run `test_model.py` by hand before a release, or after changing the router, the prompts or the model.
