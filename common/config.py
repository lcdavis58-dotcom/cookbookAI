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

# The folder holding the database, the recipe index, saved chats and
# the PDF extractions: by default the one above app/ (the layout
# CookbookAI/app/, CookbookAI/chroma_db/, ...). COOKBOOK_DATA_DIR puts
# them all somewhere else, e.g. off a synced folder like OneDrive.
DATA_DIR = os.environ.get("COOKBOOK_DATA_DIR", os.path.join(PROJECT_ROOT, ".."))

CHROMA_PATH = os.path.join(DATA_DIR, "chroma_db")
# Built from the database at the end of every ingest (and by
# tools/build_recipe_index.py), see match_utils/recipe_index.py.
RECIPE_INDEX_PATH = os.path.join(DATA_DIR, "recipe_index.json")
# Saved PDF extractions (ingest_utils/extract.py). They quote the books,
# so like chroma_db they live outside app/; EXTRACT_DIR overrides it.
EXTRACT_DIR = os.environ.get("EXTRACT_DIR", os.path.join(DATA_DIR, "extracted"))
# Saved chats (chat/store.py), one file each, in a folder of their own
# so nothing else ends up mixed in with them. CHATS_DIR overrides it.
CHATS_DIR = os.environ.get("CHATS_DIR", os.path.join(DATA_DIR, "chats"))
# The website's accounts (common/accounts.py) and the key that signs its
# login cookies (web/__init__.py). Both stay outside app/, never committed.
USERS_PATH = os.environ.get("USERS_PATH", os.path.join(DATA_DIR, "users.json"))
WEB_SECRET_PATH = os.environ.get("WEB_SECRET_PATH", os.path.join(DATA_DIR, "web_secret.key"))
COLLECTION_NAME = "cookbooks"
EMBED_MODEL = "nomic-embed-text"
# The model for every chat-model job: answering, scaling, routing chat
# messages (all calls go through common/models.py). The CHAT_MODEL
# environment variable tries another without editing this.
CHAT_MODEL = os.environ.get("CHAT_MODEL", "qwen2.5:7b")
# The context size (tokens) every call asks for. One size for all of
# them: Ollama reloads the model whenever a call asks for a different
# one, which cost ~10s a switch. 8192 fits six recipe excerpts plus the
# question, and qwen2.5:7b with it fits in 8 GB of GPU memory.
CHAT_CONTEXT = int(os.environ.get("CHAT_CONTEXT", "8192"))

# Where the PDFs live. Defaults to the Pi; set the COOKBOOKS_DIR
# environment variable to run ingest or the diagnostics on another
# machine. Keep it outside this folder so the PDFs never get synced to
# the Pi twice or committed.
COOKBOOKS_DIR = os.environ.get("COOKBOOKS_DIR", "/home/pi/CookbookAI/cookbooks")

# Book title -> PDF filename in COOKBOOKS_DIR, for every book owned, not
# only the ones ingested (ingest.py picks those). The title is what gets
# stored on every chunk and shown in citations, and it's also the key
# books/ uses to pick a chunking strategy.
BOOK_FILES = {
    "The Book On Pie": "TheBookOnPie.pdf",
    "Dessert Person": "DessertPerson.pdf",
    "BraveTart": "BraveTart.pdf",
    "Flour Water Salt Yeast": "FlourWaterSaltYeast.pdf",
    "Genius Desserts": "GeniusDesserts.pdf",
    "Genius Recipes": "GeniusRecipes.pdf",
    "How to Cook Everything Vegetarian": "HowToCookEverythingVegetarian.pdf",
    "Momofuku Milk Bar": "MomofukuMilkBar.pdf",
    "Ratio": "Ratio.pdf",
    "Salt Fat Acid Heat": "SaltFatAcidHeat.pdf",
    "Savory Baking": "SavoryBaking.pdf",
    "The Complete Cooking For Two Cookbook": "TheCompleteCookingForTwoCookbook.pdf",
    "The Cookie Book": "TheCookieBook.pdf",
    "The Fearless Baker": "TheFearlessBaker.pdf",
    "The Food Lab": "TheFoodLab.pdf",
    "What's For Dessert": "WhatsForDessert.pdf",
}


def book_pdf_path(book_title):
    return os.path.join(COOKBOOKS_DIR, BOOK_FILES[book_title])
