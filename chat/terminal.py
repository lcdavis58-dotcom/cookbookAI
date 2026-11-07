"""
The chat in a terminal (chat.py): a prompt, her messages answered one
turn at a time (chat/turn.py), and saved chats opened again.

Opening a saved chat re-finds its recipes in the current index
(chat.state.refresh) and says which are gone, shows the last two
exchanges, and offers to answer a message that never got a reply.

Reading and writing go through the read and write functions given, so
tests can drive it with scripted input.
"""

import traceback
from datetime import datetime, timedelta

from chat import store, turn
from chat.router import load_candidates
from chat.state import ChatState, refresh
from common import cli, models
from common.config import CHATS_DIR

HISTORY_TURNS = 4                   # the last two exchanges
HISTORY_LINES = 3                   # lines shown of each

HELP = """Type a message, or one of:
  /new       start a new chat
  /list      list saved chats
  /open N    open chat N from the list (or by its name)
  /quit      leave (every message is already saved)
  /help      this list"""


def when(stamp, now=None):
    """A saved time as "just now", "20 minutes ago", "today 9:32 PM",
    "yesterday 9:32 PM" or "Nov 5"."""
    try:
        then = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return "at an unknown time"
    now = now or datetime.now()
    minutes = (now - then).total_seconds() / 60
    clock = then.strftime("%I:%M %p").lstrip("0")
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{int(minutes)} minute{'s' if int(minutes) != 1 else ''} ago"
    if then.date() == now.date():
        return f"today {clock}"
    if then.date() == (now - timedelta(days=1)).date():
        return f"yesterday {clock}"
    return f"{then:%b} {then.day}"


def is_connection_error(error):
    """Ollama isn't running or can't be reached."""
    return isinstance(error, ConnectionError) or type(error).__name__ in ("ConnectError", "ConnectTimeout")


class Terminal:
    def __init__(self, read=input, write=print, directory=CHATS_DIR, candidates=None):
        self.read, self.write = read, write
        self.directory = directory
        self._candidates = candidates
        self.state = None

    @property
    def candidates(self):
        if self._candidates is None:
            self._candidates = load_candidates()
        return self._candidates

    def ask_yes(self, question):
        answer = self.read(f"{question} [Y/n] ").strip().lower()
        return answer in ("", "y", "yes")

    # -- choosing a chat --

    def numbered_chats(self):
        return store.list_chats(self.directory)

    def list_chats(self):
        chats = self.numbered_chats()
        readable = [c for c in chats if c.error is None]
        if not readable:
            self.write("No saved chats yet.")
        for i, c in enumerate(readable, 1):
            title = c.title if len(c.title) <= 40 else c.title[:37] + "..."
            self.write(f"  {i}. {title:<40}  {when(c.updated):<20}  ({c.message_count} messages)")
        broken = [c for c in chats if c.error]
        if broken:
            self.write(f"  ({len(broken)} chat{'s' if len(broken) != 1 else ''} couldn't be read: "
                       + "; ".join(f"{c.id}.json, {c.error}" for c in broken) + ")")
        return readable

    def find_chat(self, ref):
        """A chat by its number in list_chats or by its id; None (and a
        note) if there isn't one."""
        readable = [c for c in self.numbered_chats() if c.error is None]
        if str(ref).isdigit() and 1 <= int(ref) <= len(readable):
            ref = readable[int(ref) - 1].id
        try:
            return store.load(str(ref), self.directory)
        except store.ChatFileError as e:
            self.write(f"Couldn't open chat {ref}: {e}.")
            return None

    def open(self, state):
        """Make state the current chat, catching it up with the index and
        with a message left unanswered."""
        self.state = state
        gone = refresh(state, self.candidates)
        if state.messages:
            store.save(state, self.directory)
        self.write(f'\n--- "{state.title or "New chat"}" ({when(state.updated)}) ---')
        for line in self.history_lines():
            self.write(line)
        if gone:
            titles = ", ".join(gone)
            self.write(f"(Not in the books anymore, they were re-ingested: {titles}.)")
        waiting = state.unanswered()
        if waiting and self.ask_yes(f'Your last message didn\'t get an answer: "{waiting}". Answer it now?'):
            self.answer(lambda: turn.retry(state, self.directory, self.candidates))

    def history_lines(self):
        lines = []
        for t in self.state.messages[-HISTORY_TURNS:]:
            text = t.text.strip().splitlines() or [""]
            who = "You" if t.role == "user" else "Assistant"
            lines.append(f"{who}: {text[0]}")
            lines += [f"  {line}" for line in text[1:HISTORY_LINES]]
            if len(text) > HISTORY_LINES:
                lines.append("  ...")
        return lines

    def new(self):
        self.state = ChatState.new()
        self.write("--- New chat ---")

    def start(self, new=False, open_ref=None):
        """Pick the chat to begin with. False if the one asked for can't
        be opened."""
        if open_ref is not None:
            state = self.find_chat(open_ref)
            if state is None:
                return False
            self.open(state)
            return True
        latest = None if new else store.latest(self.directory)
        if latest and self.ask_yes(f'Continue "{latest.title}" from {when(latest.updated)}?'):
            self.open(latest)
        else:
            self.new()
        return True

    # -- the loop --

    def answer(self, work):
        """Run a turn (work()) and print its reply. A stopped reply
        (Ctrl+C) or an error leaves her message saved and unanswered."""
        try:
            result = work()
        except KeyboardInterrupt:
            self.write("(Stopped. Your message is saved: send it again, or reopen this chat to answer it.)")
            return
        except Exception as e:  # noqa: BLE001 -- the chat goes on, her message is saved
            if is_connection_error(e):
                self.write("I couldn't reach the model. Is Ollama running? Your message is saved, "
                           "so you can send it again once it is.")
            else:
                self.write(f"Something went wrong ({type(e).__name__}: {e}). Your message is saved.")
            if cli.DEBUG:
                self.write(traceback.format_exc())
            return
        if result is None:
            return
        self.write(result.text)
        if cli.DEBUG and models.CALLS:
            self.write("[timing] " + ", ".join(f"{c['job']} {c['seconds']:.1f}s" for c in models.CALLS))

    def command(self, line):
        """A /command. False to leave."""
        name, _, arg = line[1:].strip().partition(" ")
        name, arg = name.lower(), arg.strip()
        if name in ("quit", "exit", "q"):
            return False
        if name == "new":
            self.new()
        elif name == "list":
            self.list_chats()
        elif name == "open":
            if not arg:
                self.write("Which one? /open N, with N from /list.")
            else:
                state = self.find_chat(arg)
                if state is not None:
                    self.open(state)
        elif name == "help":
            self.write(HELP)
        else:
            self.write(f"Unknown command /{name}. {HELP}")
        return True

    def run(self, new=False, open_ref=None):
        if not self.start(new, open_ref):
            return
        self.write('(Type /help for commands, /quit to leave.)')
        while True:
            try:
                line = self.read("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                self.write("\nChat saved.")
                return
            if not line:
                continue
            if line.startswith("/"):
                if not self.command(line):
                    self.write("Chat saved.")
                    return
                continue
            state = self.state
            self.answer(lambda: turn.handle(state, line, self.directory, self.candidates))
