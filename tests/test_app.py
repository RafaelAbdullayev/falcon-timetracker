import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import app as app_module


@pytest.fixture
def client(tmp_path):
    app_module.DB_PATH = str(tmp_path / "test.db")
    app_module._initialized_paths.clear()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


def test_create_employee(client):
    r = client.post("/api/employees", json={"name": "Алиса"})
    assert r.status_code == 201
    assert r.get_json()["name"] == "Алиса"


def test_create_employee_empty_name(client):
    r = client.post("/api/employees", json={"name": "   "})
    assert r.status_code == 400


def test_start_and_stop_timer(client):
    emp = client.post("/api/employees", json={"name": "Боб"}).get_json()
    r = client.post("/api/entries/start", json={"employee_id": emp["id"], "task": "Разработка"})
    assert r.status_code == 201
    entry = r.get_json()
    assert entry["end_time"] is None

    r = client.post(f"/api/entries/{entry['id']}/stop")
    assert r.status_code == 200
    assert r.get_json()["end_time"] is not None


def test_second_start_is_blocked(client):
    emp = client.post("/api/employees", json={"name": "Карл"}).get_json()
    assert client.post("/api/entries/start", json={"employee_id": emp["id"], "task": "A"}).status_code == 201
    r = client.post("/api/entries/start", json={"employee_id": emp["id"], "task": "B"})
    assert r.status_code == 409


def test_stop_already_stopped_returns_409(client):
    emp = client.post("/api/employees", json={"name": "Дина"}).get_json()
    entry = client.post("/api/entries/start", json={"employee_id": emp["id"], "task": "A"}).get_json()
    client.post(f"/api/entries/{entry['id']}/stop")
    r = client.post(f"/api/entries/{entry['id']}/stop")
    assert r.status_code == 409


def test_empty_report_for_employee_without_entries(client):
    client.post("/api/employees", json={"name": "Ева"})
    r = client.get("/api/report")
    assert r.status_code == 200
    data = r.get_json()
    assert len(data) == 1
    assert data[0]["total_seconds"] == 0
    assert data[0]["entries_count"] == 0


def test_report_filters_by_period(client):
    emp = client.post("/api/employees", json={"name": "Фёдор"}).get_json()
    entry = client.post("/api/entries/start", json={"employee_id": emp["id"], "task": "X"}).get_json()
    client.post(f"/api/entries/{entry['id']}/stop")

    r = client.get("/api/report?from=2000-01-01&to=2000-01-02")
    assert r.status_code == 200
    assert r.get_json()[0]["total_seconds"] == 0