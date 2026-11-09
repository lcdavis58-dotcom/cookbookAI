"""
The chat as a website. Serves the app in web/ with Waitress.

Run:
    python3 serve.py               # http://127.0.0.1:8000, this computer only
    python3 serve.py --port 8080

Requires the same packages and chat model as chat.py, plus flask and
waitress.
"""

import argparse

from waitress import serve

from web import create_app

HOST = "127.0.0.1"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve the cookbook chat as a website.")
    parser.add_argument("--port", type=int, default=8000, help="port to listen on (default 8000)")
    args = parser.parse_args()
    print(f"Open http://{HOST}:{args.port} (Ctrl+C to stop)")
    serve(create_app(), host=HOST, port=args.port)
