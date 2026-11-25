import json
import math
import random
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.serving import is_running_from_reloader

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DB_PATH = BASE_DIR / "history.db"
LEGACY_DATA_PATH = BASE_DIR / "history_data.jsonl"
LEGACY_MESSAGES_PATH = BASE_DIR / "history_messages.jsonl"

SAMPLE_INTERVAL_S = 1.5
STALE_AFTER_S = 15
MAX_READINGS = 400_000  # about a week of samples
MAX_HISTORY_LIMIT = 500
MAX_MESSAGE_LENGTH = 1000
MIN_REFRESH_MS = 100
WIDGETS = ("chart", "gauge", "value")

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    timestamp REAL NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY,
    timestamp REAL NOT NULL,
    text TEXT NOT NULL
);
"""

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

PARAM_RANGES = {
    "oxygen": (85.0, 100.0),
    "heart_rate": (50.0, 140.0),
    "temperature": (34.0, 42.0),
    "energy": (0.0, 100.0),
}

MOODS = ["happy", "curious", "sleepy", "excited", "calm"]

state = {
    "oxygen": 97.0,
    "heart_rate": 72.0,
    "temperature": 36.6,
    "energy": 80.0,
    "mood": "calm",
}


def clamp(value, low, high):
    return max(low, min(high, value))


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    validate_config(config)
    return config


def is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def validate_config(config):
    """Raise ValueError describing the first problem found."""
    if not isinstance(config, dict):
        raise ValueError("config must be an object")
    interval = config.get("refresh_interval_ms", 1500)
    if not is_number(interval) or interval < MIN_REFRESH_MS:
        raise ValueError(f"refresh_interval_ms must be a number >= {MIN_REFRESH_MS}")
    if not isinstance(config.get("params"), list):
        raise ValueError("params must be a list")
    for index, param in enumerate(config["params"]):
        try:
            validate_param(param)
        except ValueError as exc:
            raise ValueError(f"params[{index}]: {exc}") from exc


def validate_param(param):
    if not isinstance(param, dict):
        raise ValueError("must be an object")
    for field in ("key", "label"):
        if not isinstance(param.get(field), str) or not param[field]:
            raise ValueError(f"{field} must be a non-empty string")
    if not isinstance(param.get("unit", ""), str):
        raise ValueError("unit must be a string")
    if param.get("widget") not in WIDGETS:
        raise ValueError(f"widget must be one of: {', '.join(WIDGETS)}")
    low, high = param.get("min", 0), param.get("max", 100)
    if not (is_number(low) and is_number(high) and low < high):
        raise ValueError("min and max must be numbers with min < max (default 0 and 100)")


def parse_message(payload):
    """Return the message text, or raise ValueError if it is not acceptable."""
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("message text is required")
    text = text.strip()
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"message is longer than {MAX_MESSAGE_LENGTH} characters")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("message contains invalid characters") from None
    return text


@contextmanager
def connect():
    """Open a connection that commits on success and is always closed."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db():
    with connect() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(SCHEMA)
        if db.execute("PRAGMA user_version").fetchone()[0] == 0:
            import_legacy_history(db)
            db.execute("PRAGMA user_version = 1")


def import_legacy_history(db):
    """Copy the old JSONL history into the database; the files are kept."""
    db.executemany(
        "INSERT INTO readings (timestamp, payload) VALUES (?, ?)",
        ((timestamp, json.dumps(values))
         for timestamp, values in read_legacy(LEGACY_DATA_PATH, "values")),
    )
    prune_readings(db)
    db.executemany(
        "INSERT INTO messages (timestamp, text) VALUES (?, ?)",
        read_legacy(LEGACY_MESSAGES_PATH, "text"),
    )


def read_legacy(path, field):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                yield record["timestamp"], record[field]
            except (json.JSONDecodeError, KeyError, TypeError):
                app.logger.warning("%s:%d: skipping unreadable line", path.name, number)


def prune_readings(db):
    db.execute(
        "DELETE FROM readings WHERE id <= (SELECT MAX(id) FROM readings) - ?",
        (MAX_READINGS,),
    )


def save_reading(record):
    with connect() as db:
        db.execute(
            "INSERT INTO readings (timestamp, payload) VALUES (?, ?)",
            (record["timestamp"], json.dumps(record["values"])),
        )
        prune_readings(db)


def latest_readings(limit):
    with connect() as db:
        rows = db.execute(
            "SELECT timestamp, payload FROM readings ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {"timestamp": row["timestamp"], "values": json.loads(row["payload"])}
        for row in reversed(rows)
    ]


def latest_messages(limit):
    with connect() as db:
        rows = db.execute(
            "SELECT timestamp, text FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def requested_limit():
    limit = request.args.get("limit", type=int, default=50)
    return clamp(limit, 0, MAX_HISTORY_LIMIT)


def step_state():
    for key, (low, high) in PARAM_RANGES.items():
        span = (high - low) * 0.02
        state[key] = round(clamp(state[key] + random.uniform(-span, span), low, high), 1)

    if random.random() < 0.1:
        state["mood"] = random.choice(MOODS)

    return dict(state)


def sample_forever():
    while True:
        try:
            save_reading({"timestamp": time.time(), "values": step_state()})
        except sqlite3.Error:
            app.logger.exception("could not save reading")
        time.sleep(SAMPLE_INTERVAL_S)


def start_sampler():
    threading.Thread(target=sample_forever, name="sampler", daemon=True).start()


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/config")
def api_config():
    try:
        return jsonify(load_config())
    except (OSError, ValueError) as exc:
        return jsonify({"error": f"invalid config: {exc}"}), 500


@app.get("/api/data")
def api_data():
    readings = latest_readings(1)
    if not readings or time.time() - readings[0]["timestamp"] > STALE_AFTER_S:
        return jsonify({"error": "no recent reading"}), 503
    return jsonify(readings[0])


@app.post("/api/message")
def api_message():
    try:
        text = parse_message(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RecursionError:
        return jsonify({"error": "message is nested too deeply"}), 400
    record = {"timestamp": time.time(), "text": text}
    with connect() as db:
        db.execute(
            "INSERT INTO messages (timestamp, text) VALUES (:timestamp, :text)", record
        )
    return jsonify(record), 201


@app.get("/api/history")
def api_history():
    limit = requested_limit()
    return jsonify({"messages": latest_messages(limit), "data": latest_readings(limit)})


@app.get("/api/messages")
def api_messages():
    return jsonify({"messages": latest_messages(requested_limit())})


if __name__ == "__main__":
    # With the reloader on, only its child process serves requests.
    if is_running_from_reloader():
        init_db()
        start_sampler()
    app.run(host="127.0.0.1", port=5000, debug=True)
