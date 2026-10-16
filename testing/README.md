# testing/

Run everything from `app/`.

## one_off/
Diagnostic scripts used while debugging. They print output for a person to read and don't pass or fail.

| Script | What it shows |
|---|---|
| `dump_pages.py "Book Title" [first last]` | What ingest's title detection sees in a real PDF (needs the PDF, so run it on the Pi) |
| `title_boundary_test.py` | Dessert Person title detection against 8 real title blocks |
| `book_on_pie_line_check.py` | Book on Pie ingredient-line parsing for a set of real lines |
| `ingredient_frequency.py [--csv out.csv]` | How often each ingredient appears across all ingested recipes, plus normalization and parser gaps (needs the database, so run it on the Pi) |
| `ingredient_trace.py "title" [...]` or `--empty [--next]` | Line by line, what the ingredient parser decided about a stored recipe, for finding out why ingredients go missing (run it on the Pi) |
| `ingredient_trace.py --late-labels` | Component-style headings that come after a recipe's steps, to check by eye after a re-ingest |
| `ingredient_trace.py --groups` | Every recipe's ingredient groups as scaling sees them (batch, component or optional), mixed recipes first |

Each one runs as `python3 testing/one_off/<script>.py` or `python3 -m testing.one_off.<script>`.

## Real tests (to come)
Put automated tests in `testing/unit/test_*.py` and run them with `python3 -m pytest testing`. Good first candidates, which can mostly be built from the one-off scripts above:
- `books/*`: `find_recipe_starts`, `extract_title` and `parse_ingredient_line` on real text
- `scale_utils/ingredients.py`: grouping and line-wrap joining
- `scale_utils/measurement_display.py`, `pan_scaling.py`, `recipe_scaling.resolve_scale_factor`: pure functions, no model or database needed
