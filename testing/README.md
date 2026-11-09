# testing/

Run everything from `app/`.

## one_off/
A local scratch folder for throwaway checks and their output. Everything in it except its README is git-ignored, because those files are usually built from real book text (see `one_off/README.md`).

The reusable diagnostic scripts (page and block dumps, ingredient frequency, parser traces) live in `tools/diagnostics/`.

## Real tests
Automated tests go in `testing/unit/test_*.py`. Run them with `python3 -m unittest discover testing` (or `python3 -m pytest testing` where pytest is installed). So far: `test_title_lookup.py` (`query_utils/title_lookup.py`) `test_sub_recipes.py` (`match_utils/sub_recipes.py`, matching through sub-recipes) `test_typos.py` (`match_utils/typos.py`), `test_finding_recipes.py` (which recipes a search returns, and listing), `test_actions.py` (`actions/`), `test_chat_state.py`, `test_chat_router.py` and `test_chat_terminal.py` (`chat/`) and `test_web.py` (the website, on temporary folders). Test data must be invented recipe text in each book's format, never lines copied from the books, since this folder is published. Good first candidates:
- `books/*`: `find_recipe_starts`, `extract_title` and `parse_ingredient_line`
- `scale_utils/ingredients.py`: grouping, line-wrap joining, the fallbacks in `line_fallbacks.py`
- `scale_utils/measurement_display.py`, `pan_scaling.py`, `recipe_scaling.resolve_scale_factor`: pure functions, no model or database needed
- `match_utils/`: normalization, "X or Y" options, matching against a small hand-written index
