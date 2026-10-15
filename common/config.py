"""
Paths and names shared by every script. Defined once here so ingest.py,
query.py and tools/clear_chroma.py can't drift apart on where the
database lives or which embedding model built it.
"""

import os

# The app/ folder (this file is app/common/config.py). Everything else is
# anchored to it rather than the current working directory, so paths
# resolve the same way regardless of where a script is run from.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Assumes the layout CookbookAI/app/ and CookbookAI/chroma_db/
CHROMA_PATH = os.path.join(PROJECT_ROOT, "..", "chroma_db")
COLLECTION_NAME = "cookbooks"
EMBED_MODEL = "nomic-embed-text"
