"""
The website's accounts: a JSON file (USERS_PATH in common/config.py) of
user names and salted password hashes, never the passwords. Accounts are
made with tools/add_user.py; the website has no sign-up page.

A user name also names that user's chats folder, so only letters, digits,
"-" and "_" are allowed.
"""

import hashlib
import json
import os
import re

from werkzeug.security import check_password_hash, generate_password_hash

from common.config import USERS_PATH

FORMAT = 1
NAME_PATTERN = r"[a-z0-9][a-z0-9_-]{0,31}"
MIN_PASSWORD_LENGTH = 8

# Checked when the user name doesn't exist, so a wrong name takes as long
# as a wrong password and can't be told apart by timing.
_NO_SUCH_USER = generate_password_hash(os.urandom(16).hex())


class AccountError(ValueError):
    """A user name or password that can't be used, with why."""


def normalize(name):
    return name.strip().lower()


def valid_name(name):
    return re.fullmatch(NAME_PATTERN, name) is not None


def _read_users(path):
    """{user name: its saved record} for the valid names; empty if there
    are no accounts yet."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    if data.get("format") != FORMAT:
        raise AccountError(f"{path} is in format {data.get('format')!r}, this version reads format {FORMAT}")
    return {name: user for name, user in data["users"].items() if valid_name(name)}


def load(path=USERS_PATH):
    """{user name: password hash}; empty if there are no accounts yet."""
    return {name: user["password"] for name, user in _read_users(path).items()}


def names(path=USERS_PATH):
    """The account names, sorted, without touching any password hash, so
    they're safe to print."""
    return sorted(_read_users(path))


def _save(users, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"format": FORMAT, "users": {n: {"password": h} for n, h in users.items()}}, f, indent=1)
    os.replace(tmp, path)


def set_password(name, password, path=USERS_PATH):
    """Create the account, or change its password. Returns the name used."""
    name = normalize(name)
    if not valid_name(name):
        raise AccountError('A user name is up to 32 letters, digits, "-" or "_", starting with a letter or digit.')
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"A password needs at least {MIN_PASSWORD_LENGTH} characters.")
    users = load(path)
    users[name] = generate_password_hash(password)
    _save(users, path)
    return name


def remove(name, path=USERS_PATH):
    """Delete the account, not its chats. False if there's no such account."""
    users = load(path)
    if users.pop(normalize(name), None) is None:
        return False
    _save(users, path)
    return True


def check(name, password, path=USERS_PATH):
    """Whether this user name and password are right."""
    stored = load(path).get(normalize(name))
    matched = check_password_hash(stored or _NO_SUCH_USER, password)
    return stored is not None and matched


def stamp(password_hash):
    """A short fingerprint of the current password, kept in the login
    cookie, so changing a password signs out every device using the old one."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]
