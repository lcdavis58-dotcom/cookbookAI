"""
The chat as a website. Serves the app in web/ with Waitress. Accounts
are made with tools/add_user.py.

Run:
    python3 serve.py               # http://127.0.0.1:8000, this computer only
    python3 serve.py --lan         # also reachable from the home network
    python3 serve.py --https       # reached over HTTPS through a Cloudflare Tunnel
    python3 serve.py --port 8080

Don't forward a router port to this: reach it from outside the home
only through something that gates access, like Cloudflare Access.

Requires the same packages and chat model as chat.py, plus flask,
flask-login, flask-wtf and waitress.
"""

import argparse

from waitress import serve

from common import accounts
from web import create_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve the cookbook chat as a website.")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on (default 8000)")
    parser.add_argument("--lan", action="store_true", help="listen on the home network, not just this computer")
    parser.add_argument("--https", action="store_true", help="the site is reached over HTTPS (a Cloudflare Tunnel)")
    args = parser.parse_args()
    if not accounts.load():
        print("No accounts yet, so nobody can sign in. Make one with: python3 tools/add_user.py NAME")
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    print(f"Listening on {host}:{args.port} (Ctrl+C to stop)")
    serve(create_app(https=args.https), host=host, port=args.port)
