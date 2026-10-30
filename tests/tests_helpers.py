import uuid


def make_job(client, account, state="queued", **changes):
    body = {
        "account_id": account,
        "request_id": str(uuid.uuid4()),
        "payload": {"kind": "post", "text": "Hello X"},
        "state": state,
    }
    body.update(changes)
    r = client.post("/api/jobs", json=body)
    assert r.status_code == 200, r.text
    return r.json()
