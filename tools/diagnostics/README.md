# tools/diagnostics/

Scripts for finding out how ingest and the parsers see a book. They print output for a person to read and don't pass or fail. Run them from `app/`, as `python3 tools/diagnostics/<script>.py` or `python3 -m tools.diagnostics.<script>`.

Their output quotes the books, so save it under `testing/one_off/` (git-ignored), never somewhere that gets committed.

| Script | What it shows | Needs |
|---|---|---|
| `book_report.py "Book Title" [--anchor REGEX]` | A scorecard: font sizes with samples, text problems (glyphs, spaced letters), and for a book with a profile, recipe count, odd titles, empty recipes, rejected lines, group kinds | the PDF |
| `structure_baseline.py save` or `compare [titles]` | Saves what ingest makes of every book (chunk text fingerprints; titles, pages, ingredients and groups for books with a profile), then reports what a change altered | the PDF |
| `dump_pages.py "Book Title" [first last]` | What ingest's title detection sees in a real PDF | the PDF |
| `dump_blocks.py "Book Title" "text"` | Every page containing the text, line by line, with block, position, font size, bold/italic and the gap above | the PDF |
| `ingredient_frequency.py [--csv out.csv]` | How often each ingredient appears across all ingested recipes, plus normalization and parser gaps | the database |
| `sub_recipe_report.py [titles] [--index PATH]` | How the recipe index linked each book's sub-recipes (by title, by kind, unlinked) and its buy-or-make links; the full list goes to `testing/one_off/sub_recipe_links.txt` | the recipe index |
| `ingredient_trace.py "title" [...]` or `--empty [--next]` | Line by line, what the ingredient parser decided about a stored recipe, for finding out why ingredients go missing | the database |
| `ingredient_trace.py --late-labels` | Component-style headings that come after a recipe's steps, to check by eye after a re-ingest | the database |
| `model_timing.py [--chats PATH]` | How long the chat model takes per model and job (routing, answering, scale intent), from the timings saved with each chat reply: count, median, 90th percentile, slowest | saved chats |
| `ingredient_trace.py --groups` | Every recipe's ingredient groups as scaling sees them (batch, component or optional), mixed recipes first | the database |

The database is on the Pi, so the scripts that need it run there. The ones that need only the PDF run anywhere the PDFs are: set `COOKBOOKS_DIR` to their folder. They read the saved extraction (`EXTRACT_DIR`, made from the PDF on first use), and `structure_baseline.py` and `book_report.py` run the whole structure step without the database or a model.

Before and after any change to extraction or parsing, run `structure_baseline.py compare`; save a new baseline only once a change is confirmed good.
