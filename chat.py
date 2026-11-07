"""
Chat with the assistant: ask about recipes, scale them and find what you
can make, with follow-ups ("double it", "the second one", "add pecans")
in one conversation. Every message is saved as it's sent.

Run:
    python3 chat.py              # offers to continue the latest chat, else a new one
    python3 chat.py --new        # start a new chat
    python3 chat.py --list       # list saved chats
    python3 chat.py --open 3     # open chat 3 from that list (or by its name)
    python3 chat.py -d           # with each message's route and model timing

Where things live:
    chat/terminal.py    this loop, opening and listing chats
    chat/turn.py        one message: route, act, remember, reply, save
    chat/router.py      which action a message is for
    chat/state.py       what a chat remembers
    chat/store.py       saved chats (CHATS_DIR in common/config.py)

Requires the same packages and chat model as query.py.
"""

import argparse

from chat.terminal import Terminal
from common import cli

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chat with your cookbooks.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--new", action="store_true", help="start a new chat")
    group.add_argument("--list", action="store_true", help="list saved chats and exit")
    group.add_argument("--open", metavar="N", help="open chat N from --list (or a chat's name)")
    parser.add_argument("-d", "--debug", action="store_true", help="show each message's route and model timing")
    args = parser.parse_args()
    cli.DEBUG = args.debug
    terminal = Terminal()
    if args.list:
        terminal.list_chats()
    else:
        terminal.run(new=args.new, open_ref=args.open)
