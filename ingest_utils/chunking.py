"""
Splitting a book's text into chunks for embedding. The recipe-aware path
asks the book's own module (books/) where recipes start; everything
else here is shared by every book.
"""

from common.text_parsing import ALLCAPS_LINE_RE
from common.word_list_loader import load_book_specific
from ingest_utils.pdf_text import page_for_line

# Roughly how many characters per chunk, with overlap so a recipe split
# across the boundary doesn't lose context. Tune this once you see how your
# cookbooks are formatted, recipe-aware chunking (splitting on recipe titles)
# will work better than fixed-size chunking if your PDFs have consistent headers.
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Simple sliding-window chunker, used as a fallback when a segment
    (a recipe, or a stretch of non-recipe text) is too large to embed as
    one chunk, and as the default strategy for books with no specialized
    chunking profile."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


# Default fallback if a book has no word_lists/books/<slug>/ entry of its
# own, harmless for a book with no batch-style subsections at all, since
# an unmatched label here just means find_section_starts() never has
# anything to exclude.
_DEFAULT_SUBSECTION_LABELS = [
    "half batch", "full batch", "mile-high batch", "variation",
    "variations", "note", "notes", "tip", "tips",
]


def find_section_starts(lines, consumed, book_title):
    """Detect standalone non-recipe section headers, like 'PIE PEP TALK' or
    'GLAZES': a short ALL-CAPS line that isn't part of any recipe's title
    block and isn't a known in-recipe subsection label (book-specific,
    see word_lists/books/<slug>/recipe_subsection_labels.json). These get
    their own 'other'-tagged chunk boundary instead of silently being
    absorbed into whichever recipe happens to come right after them.
    """
    labels = set(
        label.upper() for label in
        load_book_specific(book_title, "recipe_subsection_labels.json",
                            {"labels": _DEFAULT_SUBSECTION_LABELS}).get("labels", _DEFAULT_SUBSECTION_LABELS)
    )

    starts = []
    for i, line in enumerate(lines):
        if i in consumed:
            continue
        stripped = line.strip()
        if stripped and ALLCAPS_LINE_RE.match(stripped) and stripped not in labels:
            starts.append(i)
    return starts


def split_on_lines(text, max_chars):
    """Pack whole lines into parts of at most max_chars, never cutting a
    line (and so never an ingredient) in half. No overlap, so
    "\\n".join(parts) gives back the original text exactly, which is what
    lets query_utils.retrieval.full_recipe_text stitch a split recipe back
    together. The one exception is a single line longer than max_chars on
    its own, which gets hard-cut (it can't be an ingredient line at that
    length, so nothing parseable is lost).
    """
    parts, current, current_len = [], [], 0
    for line in text.split("\n"):
        pieces = chunk_text(line, max_chars, 0) if len(line) > max_chars else [line]
        for piece in pieces:
            added = len(piece) + (1 if current else 0)
            if current and current_len + added > max_chars:
                parts.append("\n".join(current))
                current, current_len = [], 0
                added = len(piece)
            current.append(piece)
            current_len += added
    if current:
        parts.append("\n".join(current))
    return parts


def chunk_recipe_aware(lines, page_starts, book_title, profile, max_chunk_chars=3000):
    """Split the book into (text, content_type, page_num, confirmed,
    extra_metadata) chunks. Recipe boundaries (title through its
    variations) come from the book's own find_recipe_starts (profile is
    the book's books module) and become "recipe" chunks.
    Standalone technique/advice sections between recipes become their own
    "other" chunks, rather than bleeding into the next recipe.

    A recipe longer than max_chunk_chars (most of Dessert Person, which
    has long intros and footnotes) is split on line boundaries into
    CHUNK_SIZE parts, each tagged with a shared recipe_id plus its part
    number. Each part still gets its own focused embedding, but once a
    title match lands on part 0, query fetches every part by recipe_id
    and reassembles the whole recipe, so scaling never sees a truncated
    ingredient list. Every recipe gets a recipe_id, even a one-part one,
    so query-time code doesn't need two paths.

    Oversized "other" segments still use the overlapping sliding window,
    those are only ever retrieved piecemeal, never reassembled.
    """
    recipe_starts, consumed = profile.find_recipe_starts(lines)
    section_starts = find_section_starts(lines, consumed, book_title)

    boundary_types = {i: "recipe" for i in recipe_starts}
    boundary_types.update({i: "other" for i in section_starts})
    boundary_points = sorted(boundary_types.keys()) + [len(lines)]

    records = []
    recipe_index = 0
    prev_end = 0
    for boundary in boundary_points:
        segment_text = "\n".join(lines[prev_end:boundary]).strip()
        if segment_text:
            # prev_end == 0 and not itself a detected boundary means this is
            # front matter / table of contents before the first recipe or
            # section, default that to "other" too.
            content_type = boundary_types.get(prev_end, "other")
            page_num, confirmed = page_for_line(prev_end, page_starts)
            if content_type == "recipe":
                if len(segment_text) <= max_chunk_chars:
                    parts = [segment_text]
                else:
                    parts = split_on_lines(segment_text, CHUNK_SIZE)
                recipe_id = f"{book_title}-r{recipe_index}"
                recipe_index += 1
                for part_num, part in enumerate(parts):
                    records.append((part, content_type, page_num, confirmed, {
                        "recipe_id": recipe_id,
                        "part": part_num,
                        "part_count": len(parts),
                    }))
            elif len(segment_text) <= max_chunk_chars:
                records.append((segment_text, content_type, page_num, confirmed, {}))
            else:
                for sub in chunk_text(segment_text, CHUNK_SIZE, CHUNK_OVERLAP):
                    records.append((sub, content_type, page_num, confirmed, {}))
        prev_end = boundary
    return records
