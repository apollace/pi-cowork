import json
from unittest.mock import patch


def test_create_questions(client, default_board):
    res = client.post(
        "/api/tickets",
        json={
            "title": "Q",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    res = client.post(
        f"/api/tickets/{tid}/questions",
        json={
            "questions": [
                {"body": "What is the color?", "options": ["Red", "Blue"]},
                {"body": "Any notes?"},
            ]
        },
    )
    assert res.status_code == 201
    data = json.loads(res.data)
    assert len(data["ids"]) == 2

    res = client.get(f"/api/tickets/{tid}/questions")
    assert res.status_code == 200
    qs = json.loads(res.data)
    assert len(qs) == 2
    assert qs[0]["body"] == "What is the color?"
    assert qs[0]["options"] == ["Red", "Blue"]
    assert qs[1]["options"] is None


def test_answer_question_creates_comment(client, default_board):
    res = client.post(
        "/api/tickets",
        json={
            "title": "Q",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    res = client.post(f"/api/tickets/{tid}/questions", json={"questions": [{"body": "What is the color?"}]})
    qid = json.loads(res.data)["ids"][0]

    res = client.put(f"/api/questions/{qid}/answer", json={"answer": "Blue"})
    assert res.status_code == 200

    res = client.get(f"/api/tickets/{tid}/questions")
    assert len(json.loads(res.data)) == 0

    res = client.get(f"/api/tickets/{tid}/comments")
    comments = json.loads(res.data)
    assert len(comments) == 1
    assert "**Q:** What is the color?" in comments[0]["body"]
    assert "**A:** Blue" in comments[0]["body"]


def test_spawn_blocked_by_questions(client, default_workflow, default_board):
    statuses = json.loads(client.get("/api/statuses?workflow_id=1").data)
    research = next(s for s in statuses if s["name"] == "Research")
    design = next(s for s in statuses if s["name"] == "Design")

    res = client.post(
        "/api/tickets",
        json={
            "title": "Q",
            "board_id": default_board["id"],
            "status_id": research["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    client.post(f"/api/tickets/{tid}/questions", json={"questions": [{"body": "Blocked?"}]})

    with patch("app.subprocess.Popen") as mock_popen:
        res = client.put(f"/api/tickets/{tid}", json={"status_id": design["id"]})
        assert res.status_code == 200
        assert not mock_popen.called

    comments = json.loads(client.get(f"/api/tickets/{tid}/comments").data)
    assert any("Waiting for 1 unanswered question" in c["body"] for c in comments)


def test_answer_last_question_triggers_agent_spawn(client, default_workflow, default_board):
    statuses = json.loads(client.get("/api/statuses?workflow_id=1").data)
    research = next(s for s in statuses if s["name"] == "Research")

    # Create ticket in Research status — suppress agent spawn on creation
    # so the test can isolate the spawn-triggering-by-answer behavior.
    with patch("pi_cowork.api.tickets.spawn_agent_for_ticket"):
        res = client.post(
            "/api/tickets",
            json={
                "title": "Q",
                "board_id": default_board["id"],
                "status_id": research["id"],
            },
        )
    tid = json.loads(res.data)["id"]

    res = client.post(f"/api/tickets/{tid}/questions", json={"questions": [{"body": "Trigger?"}]})
    qid = json.loads(res.data)["ids"][0]

    with patch("app.subprocess.Popen") as mock_popen:
        res = client.put(f"/api/questions/{qid}/answer", json={"answer": "Yes"})
        assert res.status_code == 200
        assert mock_popen.called


def test_question_wait_comment_dedup(client, default_workflow, default_board):
    statuses = json.loads(client.get("/api/statuses?workflow_id=1").data)
    research = next(s for s in statuses if s["name"] == "Research")
    design = next(s for s in statuses if s["name"] == "Design")

    res = client.post(
        "/api/tickets",
        json={
            "title": "Q",
            "board_id": default_board["id"],
            "status_id": research["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    client.post(f"/api/tickets/{tid}/questions", json={"questions": [{"body": "Dedup?"}]})

    with patch("app.subprocess.Popen"):
        client.put(f"/api/tickets/{tid}", json={"status_id": design["id"]})
        client.put(f"/api/tickets/{tid}", json={"status_id": research["id"]})

    comments = json.loads(client.get(f"/api/tickets/{tid}/comments").data)
    wait_comments = [c for c in comments if "Waiting for 1 unanswered question" in c["body"]]
    assert len(wait_comments) == 1


def test_batch_answer_creates_single_comment(client, default_workflow, default_board):
    statuses = json.loads(client.get("/api/statuses?workflow_id=1").data)
    research = next(s for s in statuses if s["name"] == "Research")

    # Create ticket in Research status — suppress agent spawn on creation
    # so the test can isolate the batch-answer comment behavior.
    with patch("pi_cowork.api.tickets.spawn_agent_for_ticket"):
        res = client.post(
            "/api/tickets",
            json={
                "title": "Q",
                "board_id": default_board["id"],
                "status_id": research["id"],
            },
        )
    tid = json.loads(res.data)["id"]

    res = client.post(
        f"/api/tickets/{tid}/questions",
        json={
            "questions": [
                {"body": "What is the color?", "options": ["Red", "Blue"]},
                {"body": "Any notes?"},
            ]
        },
    )
    qids = json.loads(res.data)["ids"]

    with patch("app.subprocess.Popen"):
        res = client.post(
            f"/api/tickets/{tid}/answers",
            json={
                "answers": [
                    {"question_id": qids[0], "answer": "Red"},
                    {"question_id": qids[1], "answer": "Some notes"},
                ]
            },
        )
    assert res.status_code == 200
    data = json.loads(res.data)
    assert data["answered"] == 2

    res = client.get(f"/api/tickets/{tid}/questions")
    assert len(json.loads(res.data)) == 0

    res = client.get(f"/api/tickets/{tid}/comments")
    comments = json.loads(res.data)
    user_comments = [
        c
        for c in comments
        if not c["body"].startswith("🤖") and not c["body"].startswith("⏳") and not c["body"].startswith("⚠️")
    ]
    assert len(user_comments) == 1
    body = user_comments[0]["body"]
    assert "**Q:** What is the color?" in body
    assert "**A:** Red" in body
    assert "**Q:** Any notes?" in body
    assert "**A:** Some notes" in body


def test_questions_cascade_on_board_delete(client, default_board):
    res = client.post(
        "/api/tickets",
        json={
            "title": "Q",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    client.post(f"/api/tickets/{tid}/questions", json={"questions": [{"body": "Cascade?"}]})

    client.delete(f"/api/boards/{default_board['id']}")

    res = client.get(f"/api/tickets/{tid}/questions")
    assert res.status_code == 404


def test_ticket_includes_question_count(client, default_board):
    res = client.post(
        "/api/tickets",
        json={
            "title": "Q",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(res.data)["id"]

    client.post(f"/api/tickets/{tid}/questions", json={"questions": [{"body": "Count?"}]})

    res = client.get(f"/api/tickets/{tid}")
    data = json.loads(res.data)
    assert data["question_count"] == 1

    res = client.get(f"/api/tickets?board_id={default_board['id']}")
    data = json.loads(res.data)
    assert len(data) == 1
    assert data[0]["question_count"] == 1


def test_questions_endpoint_in_spawn_prompt(client, default_workflow, default_board):
    """A mocked spawn should include the questions API in its prompt."""
    import json
    from unittest.mock import patch

    agent = client.post(
        "/api/agents",
        json={
            "name": "QuestionPromptAgent",
            "description": "You are a question agent.",
            "workflow_id": default_workflow["id"],
        },
    )
    aid = json.loads(agent.data)["id"]

    s1 = client.post(
        "/api/statuses",
        json={
            "name": "QuestionStage",
            "sort_order": 1,
            "agent_id": aid,
            "workflow_id": default_workflow["id"],
        },
    )
    id1 = json.loads(s1.data)["id"]

    ticket = client.post(
        "/api/tickets",
        json={
            "title": "Question Prompt Ticket",
            "board_id": default_board["id"],
        },
    )
    tid = json.loads(ticket.data)["id"]

    captured_cmd = []

    def capture_popen(cmd, **kwargs):
        class FakeProc:
            pid = 9999

        captured_cmd[:] = cmd
        return FakeProc()

    with patch("app.subprocess.Popen", side_effect=capture_popen):
        res = client.put(f"/api/tickets/{tid}", json={"status_id": id1})
        assert res.status_code == 200

    assert captured_cmd
    context_msg = captured_cmd[-1]

    assert f"/api/tickets/{tid}/questions" in context_msg
    assert "ask questions" in context_msg
    assert "paused until a human answers" in context_msg
    assert "If anything is ambiguous or missing, ask clarifying questions before proceeding." in context_msg
