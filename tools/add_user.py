"""
Manage the website's accounts (common/accounts.py).

Run from app/:
    python3 tools/add_user.py NAME            # create NAME, or change its password
    python3 tools/add_user.py --list
    python3 tools/add_user.py --remove NAME   # the account, not its chats
"""

import argparse
import getpass
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common import accounts  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage the website's accounts.")
    parser.add_argument("name", nargs="?", help="the account to create, or change the password of")
    parser.add_argument("--list", action="store_true", help="list the accounts")
    parser.add_argument("--remove", metavar="NAME", help="delete an account (its chats are kept)")
    args = parser.parse_args()
    if args.list:
        print("\n".join(sorted(accounts.load())) or "No accounts yet.")
    elif args.remove:
        print("Removed." if accounts.remove(args.remove) else "No account by that name.")
    elif args.name:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Same password again: "):
            sys.exit("Those didn't match. Nothing was changed.")
        try:
            print(f"Saved the account {accounts.set_password(args.name, password)!r}.")
        except accounts.AccountError as e:
            sys.exit(str(e))
    else:
        parser.print_help()
