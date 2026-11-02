import os
import sqlite3
from datetime import datetime, timezone
from flask import Flask, request, jsonify, render_template, g

DB_PATH = os.environ.get("DB_PATH", "timetracker.db")
app = Flask(__name__)
_initialized_paths = set()

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                task TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_entries_employee ON entries(employee_id);
            CREATE INDEX IF NOT EXISTS idx_entries_start ON entries(start_time);
        """)

@app.before_request
def ensure_schema():
    if DB_PATH not in _initialized_paths:
        init_db()
        _initialized_paths.add(DB_PATH)

def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def parse_date_arg(value):
    if not value:
        return "", True
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return value, True
    except ValueError:
        return "", False

def entry_duration_seconds(row):
    start = datetime.fromisoformat(row["start_time"])
    end = datetime.fromisoformat(row["end_time"]) if row["end_time"] else datetime.now(timezone.utc)
    return max(0, int((end - start).total_seconds()))

def entry_to_dict(row):
    return {
        "id": row["id"],
        "employee_id": row["employee_id"],
        "task": row["task"],
        "start_time": row["start_time"],
        "end_time": row["end_time"],
        "duration_seconds": entry_duration_seconds(row),
    }

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/employees")
def list_employees():
    rows = get_db().execute("SELECT * FROM employees ORDER BY name COLLATE NOCASE").fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/employees")
def create_employee():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Имя сотрудника не может быть пустым"}), 400
    if len(name) > 100:
        return jsonify({"error": "Имя слишком длинное (макс. 100 символов)"}), 400
    db = get_db()
    cur = db.execute("INSERT INTO employees (name, created_at) VALUES (?, ?)", (name, now_iso()))
    db.commit()
    return jsonify({"id": cur.lastrowid, "name": name}), 201

@app.post("/api/entries/start")
def start_entry():
    data = request.get_json(silent=True) or {}
    employee_id = data.get("employee_id")
    task = (data.get("task") or "").strip()
    if not employee_id:
        return jsonify({"error": "Не указан сотрудник"}), 400
    if not task:
        return jsonify({"error": "Описание задачи не может быть пустым"}), 400

    db = get_db()
    emp = db.execute("SELECT id FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        return jsonify({"error": "Сотрудник не найден"}), 404

    running = db.execute("SELECT id FROM entries WHERE employee_id = ? AND end_time IS NULL", (employee_id,)).fetchone()
    if running:
        return jsonify({"error": f"У сотрудника уже идёт таймер (запись #{running['id']})"}), 409

    cur = db.execute("INSERT INTO entries (employee_id, task, start_time) VALUES (?, ?, ?)", (employee_id, task, now_iso()))
    db.commit()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(entry_to_dict(row)), 201

@app.post("/api/entries/<int:entry_id>/stop")
def stop_entry(entry_id):
    db = get_db()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return jsonify({"error": "Запись не найдена"}), 404

    cur = db.execute("UPDATE entries SET end_time = ? WHERE id = ? AND end_time IS NULL", (now_iso(), entry_id))
    if cur.rowcount == 0:
        return jsonify({"error": "Таймер уже остановлен"}), 409
    db.commit()
    row = db.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return jsonify(entry_to_dict(row))

def _build_range_filters(date_from, date_to):
    clauses, params = [], []
    if date_from:
        clauses.append("start_time >= ?")
        params.append(date_from + "T00:00:00")
    if date_to:
        clauses.append("start_time <= ?")
        params.append(date_to + "T23:59:59.999999")
    return clauses, params

@app.get("/api/entries")
def list_entries():
    date_from, ok_from = parse_date_arg(request.args.get("from"))
    date_to, ok_to = parse_date_arg(request.args.get("to"))
    if not ok_from or not ok_to:
        return jsonify({"error": "Некорректный формат даты (ожидается YYYY-MM-DD)"}), 400

    employee_id = request.args.get("employee_id")
    q = "SELECT * FROM entries WHERE 1=1"
    clauses, params = _build_range_filters(date_from, date_to)
    if employee_id:
        clauses.append("employee_id = ?")
        params.append(employee_id)
    if clauses:
        q += " AND " + " AND ".join(clauses)
    q += " ORDER BY start_time DESC"

    rows = get_db().execute(q, params).fetchall()
    return jsonify([entry_to_dict(r) for r in rows])

@app.get("/api/report")
def report():
    date_from, ok_from = parse_date_arg(request.args.get("from"))
    date_to, ok_to = parse_date_arg(request.args.get("to"))
    if not ok_from or not ok_to:
        return jsonify({"error": "Некорректный формат даты (ожидается YYYY-MM-DD)"}), 400

    db = get_db()
    employees = db.execute("SELECT * FROM employees ORDER BY name COLLATE NOCASE").fetchall()

    q = "SELECT * FROM entries WHERE 1=1"
    clauses, params = _build_range_filters(date_from, date_to)
    if clauses:
        q += " AND " + " AND ".join(clauses)
    rows = db.execute(q, params).fetchall()

    by_employee = {}
    for r in rows:
        by_employee.setdefault(r["employee_id"], []).append(r)

    result = []
    for e in employees:
        entries = by_employee.get(e["id"], [])
        total = sum(entry_duration_seconds(r) for r in entries)
        result.append({
            "employee_id": e["id"],
            "name": e["name"],
            "entries_count": len(entries),
            "total_seconds": total,
        })
    return jsonify(result)

if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)