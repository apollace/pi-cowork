"""Tests for the read-only observations endpoint (Ticket #170)."""

import json

from pi_cowork.db import get_db


class TestObservationsAPI:
    def test_empty_observations(self, client):
        res = client.get("/api/observations")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["observations"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    def test_failed_agent_run_appears(self, client, default_board):
        res = client.post(
            "/api/tickets",
            json={"title": "Test ticket", "board_id": default_board["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        with client.application.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO agent_runs (ticket_id, agent_id, status, exit_code) VALUES (?, ?, ?, ?)",
                (tid, 1, "failed", 1),
            )
            db.commit()

        res = client.get("/api/observations")
        assert res.status_code == 200
        data = json.loads(res.data)
        assert data["total"] >= 1
        runs = [o for o in data["observations"] if o["source_table"] == "agent_runs"]
        assert any(r["type"] == "failed" and r["ticket_id"] == tid for r in runs)

    def test_gate_failure_appears(self, client, default_board):
        res = client.post(
            "/api/tickets",
            json={"title": "Gate test", "board_id": default_board["id"]},
        )
        ticket = json.loads(res.data)
        tid = ticket["id"]

        with client.application.app_context():
            db = get_db()
            db.execute("PRAGMA foreign_keys = OFF")
            db.execute(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, output) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tid, 1, 1, 2, "failed", "pytest failed"),
            )
            db.execute("PRAGMA foreign_keys = ON")
            db.commit()

        res = client.get("/api/observations")
        assert res.status_code == 200
        data = json.loads(res.data)
        reviews = [o for o in data["observations"] if o["source_table"] == "gate_reviews"]
        assert any(r["type"] == "failed" and r["ticket_id"] == tid for r in reviews)

    def test_system_log_appears(self, client):
        with client.application.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO system_logs (timestamp, level, action_type, message, details, ticket_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2024-01-01 00:00:00", "INFO", "http_request", "GET /api/tickets", None, None),
            )
            db.commit()

        res = client.get("/api/observations")
        assert res.status_code == 200
        data = json.loads(res.data)
        logs = [o for o in data["observations"] if o["source_table"] == "system_logs"]
        assert any(log["type"] == "http_request" for log in logs)

    def test_event_log_appears(self, client):
        with client.application.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO event_log (event_name, payload) VALUES (?, ?)",
                ("ticket.created", '{"ticket_id": 42}'),
            )
            db.commit()

        res = client.get("/api/observations")
        assert res.status_code == 200
        data = json.loads(res.data)
        events = [o for o in data["observations"] if o["source_table"] == "event_log"]
        assert any(e["type"] == "ticket.created" for e in events)

    def test_filter_by_ticket_id(self, client, default_board):
        res = client.post(
            "/api/tickets",
            json={"title": "Ticket A", "board_id": default_board["id"]},
        )
        ticket_a = json.loads(res.data)
        res = client.post(
            "/api/tickets",
            json={"title": "Ticket B", "board_id": default_board["id"]},
        )
        ticket_b = json.loads(res.data)

        with client.application.app_context():
            db = get_db()
            db.execute("PRAGMA foreign_keys = OFF")
            db.execute(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, output) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ticket_a["id"], 1, 1, 2, "failed", "fail A"),
            )
            db.execute(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, output) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (ticket_b["id"], 1, 1, 2, "failed", "fail B"),
            )
            db.execute("PRAGMA foreign_keys = ON")
            db.commit()

        res = client.get(f"/api/observations?ticket_id={ticket_a['id']}")
        data = json.loads(res.data)
        assert all(o["ticket_id"] == ticket_a["id"] for o in data["observations"] if o["ticket_id"] is not None)
        assert any(o["body"] == "fail A" for o in data["observations"])
        assert not any(o["body"] == "fail B" for o in data["observations"])

    def test_filter_by_type(self, client, default_board):
        with client.application.app_context():
            db = get_db()
            db.execute("PRAGMA foreign_keys = OFF")
            db.execute(
                "INSERT INTO agent_runs (ticket_id, agent_id, status, exit_code) VALUES (?, ?, ?, ?)",
                (1, 1, "failed", 1),
            )
            db.execute(
                "INSERT INTO gate_reviews (ticket_id, gate_id, from_status_id, to_status_id, status, output) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (1, 1, 1, 2, "passed", "ok"),
            )
            db.execute("PRAGMA foreign_keys = ON")
            db.commit()

        res = client.get("/api/observations?type=failed")
        data = json.loads(res.data)
        assert all(o["type"] == "failed" for o in data["observations"])

    def test_pagination(self, client, default_board):
        with client.application.app_context():
            db = get_db()
            for i in range(5):
                db.execute(
                    "INSERT INTO system_logs (timestamp, level, action_type, message, details, ticket_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (f"2024-01-01 00:00:0{i}", "INFO", "http_request", f"msg {i}", None, None),
                )
            db.commit()

        res = client.get("/api/observations?per_page=2&page=1")
        data = json.loads(res.data)
        assert len(data["observations"]) == 2
        assert data["total"] == 5
        assert data["total_pages"] == 3

        res = client.get("/api/observations?per_page=2&page=2")
        data = json.loads(res.data)
        assert len(data["observations"]) == 2
        assert data["page"] == 2

        res = client.get("/api/observations?per_page=2&page=3")
        data = json.loads(res.data)
        assert len(data["observations"]) == 1

    def test_search(self, client, default_board):
        with client.application.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO system_logs (timestamp, level, action_type, message, details, ticket_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2024-01-01 00:00:00", "INFO", "http_request", "alpha message", None, None),
            )
            db.execute(
                "INSERT INTO system_logs (timestamp, level, action_type, message, details, ticket_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2024-01-01 00:00:01", "INFO", "http_request", "beta message", None, None),
            )
            db.commit()

        res = client.get("/api/observations?search=alpha")
        data = json.loads(res.data)
        assert all("alpha" in (o["title"] + o["body"]) for o in data["observations"])
        assert not any("beta" in (o["title"] + o["body"]) for o in data["observations"])

    def test_date_filter(self, client, default_board):
        with client.application.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO system_logs (timestamp, level, action_type, message, details, ticket_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2024-01-01 00:00:00", "INFO", "http_request", "old", None, None),
            )
            db.execute(
                "INSERT INTO system_logs (timestamp, level, action_type, message, details, ticket_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2024-06-01 00:00:00", "INFO", "http_request", "new", None, None),
            )
            db.commit()

        res = client.get("/api/observations?date_from=2024-05-01&date_to=2024-12-31")
        data = json.loads(res.data)
        assert all(
            "new" in (o["title"] + o["body"]) for o in data["observations"] if o["source_table"] == "system_logs"
        )
        assert not any(
            "old" in (o["title"] + o["body"]) for o in data["observations"] if o["source_table"] == "system_logs"
        )

    def test_combined_filters(self, client, default_board):
        with client.application.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO system_logs (timestamp, level, action_type, message, details, ticket_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2024-01-01 00:00:00", "INFO", "http_request", "search me", None, None),
            )
            db.execute(
                "INSERT INTO system_logs (timestamp, level, action_type, message, details, ticket_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("2024-06-01 00:00:00", "INFO", "http_request", "search me", None, None),
            )
            db.commit()

        res = client.get("/api/observations?search=search&date_from=2024-05-01")
        data = json.loads(res.data)
        assert len(data["observations"]) == 1
        assert "search me" in data["observations"][0]["body"]

    def test_source_id_matches_id(self, client, default_board):
        with client.application.app_context():
            db = get_db()
            db.execute(
                "INSERT INTO event_log (event_name, payload) VALUES (?, ?)",
                ("ticket.created", '{"ticket_id": 1}'),
            )
            db.commit()

        res = client.get("/api/observations")
        data = json.loads(res.data)
        event = next(o for o in data["observations"] if o["source_table"] == "event_log")
        assert event["source_id"] == event["id"]


class TestSystemImprovementNotSeeded:
    def test_system_improvement_workflow_not_present(self, client):
        res = client.get("/api/workflows")
        assert res.status_code == 200
        wfs = json.loads(res.data)
        assert not any(w["name"] == "System Improvement" for w in wfs)

    def test_system_board_not_present(self, client):
        res = client.get("/api/boards")
        assert res.status_code == 200
        boards = json.loads(res.data)
        assert not any(b["name"] == "System" for b in boards)

    def test_synthesizer_agent_not_present(self, client):
        res = client.get("/api/agents?workflow_id=1")
        assert res.status_code == 200
        agents = json.loads(res.data)
        assert not any(a["name"] == "Synthesizer" for a in agents)

    def test_self_improvement_settings_not_seeded(self, client):
        for key in ("self_improvement_enabled", "self_improvement_batch_cron", "high_comment_threshold"):
            res = client.get(f"/api/settings/{key}")
            assert res.status_code == 404

    def test_observations_page_renders(self, client):
        res = client.get("/observations")
        assert res.status_code == 200
        assert b"Observations" in res.data

    def test_observations_api_renders(self, client):
        res = client.get("/api/observations")
        assert res.status_code == 200

    def test_no_recurring_self_improvement_task(self, client):
        res = client.get("/api/recurring?board_id=1")
        assert res.status_code == 200
        tasks = json.loads(res.data)
        assert not any(t["title"] == "Self-improvement batch" for t in tasks)
