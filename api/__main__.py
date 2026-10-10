"""python -m api : lance le serveur (et ouvre le navigateur en local).

HOST et PORT se règlent par variables d'environnement ; un hébergeur fournit en général PORT.
"""

import os
import threading
import webbrowser

import uvicorn

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

if __name__ == "__main__":
    if HOST in ("127.0.0.1", "localhost") and not os.environ.get("NO_BROWSER"):
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    uvicorn.run("api.main:app", host=HOST, port=PORT, proxy_headers=True, forwarded_allow_ips="*")
