from flask import Flask
from threading import Thread
app = Flask(__name__)
@app.get("/") 
def home(): return "AoE:M Bot is running."
def run(): app.run(host="0.0.0.0", port=8080)
def keepalive(): Thread(target=run, daemon=True).start()
