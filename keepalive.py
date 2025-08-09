import threading
from flask import Flask

app = Flask(__name__)

@app.get("/")
def root(): return "ok"

@app.get("/health")
def health(): return "ok"

def keepalive():
    def run():
        app.run(host="0.0.0.0", port=8080)
    threading.Thread(target=run, daemon=True).start()
