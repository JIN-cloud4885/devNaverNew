from flask import Flask, render_template, request, jsonify
import json
import os

app = Flask(__name__)

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "api": {
        "client_id": "",
        "client_secret": ""
    },
    "keywords": [],
    "search": {
        "display": 10,
        "sort": "date"
    }
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    config = load_config()
    return render_template("index.html", config=config)


@app.route("/api/config", methods=["GET"])
def get_config():
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def update_config():
    config = request.get_json()
    save_config(config)
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    from waitress import serve
    serve(app, host="127.0.0.1", port=5000)
