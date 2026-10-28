# tools/diagnostics/

Scripts for finding out how ingest and the parsers see a book. They print output for a person to read and don't pass or fail. Run them from `app/`, as `python3 tools/diagnostics/<script>.py` or `python3 -m tools.diagnostics.<script>`.

Their output quotes the books, so save it under `testing/one_off/` (git-ignored), never somewhere that gets committed.

| Script | What it shows | Needs |
|---|---|---|
| `dump_pages.py "Book Title" [first last]` | What ingest's title detection sees in a real PDF | the PDF |
| `dump_blocks.py "Book Title" "text"` | The PDF text blocks on each page containing the text, with positions and the gap above each block | the PDF |
| `ingredient_frequency.py [--csv out.csv]` | How often each ingredient appears across all ingested recipes, plus normalization and parser gaps | the database |
| `ingredient_trace.py "title" [...]` or `--empty [--next]` | Line by line, what the ingredient parser decided about a stored recipe, for finding out why ingredients go missing | the database |
| `ingredient_trace.py --late-labels` | Component-style headings that come after a recipe's steps, to check by eye after a re-ingest | the database |
| `ingredient_trace.py --groups` | Every recipe's ingredient groups as scaling sees them (batch, component or optional), mixed recipes first | the database |

The PDFs and the database are on the Pi, so these run there.
