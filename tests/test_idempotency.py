from app.samples import load_sample


def test_idempotency_key_reuses_archive(client):
    payload = {"sample": "dual", "idempotency_key": "batch-dual-001"}
    first = client.post("/api/runs", json=payload).json()
    second = client.post("/api/runs", json=payload).json()
    assert first["id"] == second["id"] and second["reused"] is True


def test_idempotency_conflict_blocks_reassignment(client, dual_data):
    client.post("/api/runs", json={"sample": "dual", "idempotency_key": "k-1"})
    changed = load_sample("dual")
    changed["config"]["supply"] = "18.4"
    response = client.post("/api/runs", json={"data": changed, "idempotency_key": "k-1"})
    assert response.status_code == 422
    assert response.json()["code"] == "IDEMPOTENCY_CONFLICT"


def test_distinct_inputs_get_distinct_archives(client, dual_data):
    first = client.post("/api/runs", json={"data": dual_data, "idempotency_key": "a"}).json()
    changed = load_sample("dual")
    changed["config"]["supply"] = "18.4"
    second = client.post("/api/runs", json={"data": changed, "idempotency_key": "b"}).json()
    assert first["id"] != second["id"]


def test_confirmation_dedup_and_tamper_rejection(client):
    run = client.post("/api/runs", json={"sample": "dual", "idempotency_key": "confirm-1"}).json()
    outlet, amount = "201", 2700
    created = client.post(f"/api/runs/{run['id']}/confirmations", json={"outlet": outlet, "amount_l": amount})
    repeated = client.post(f"/api/runs/{run['id']}/confirmations", json={"outlet": outlet, "amount_l": amount})
    assert created.json()["created"] is True
    assert repeated.json()["created"] is False
    listing = client.get(f"/api/runs/{run['id']}/confirmations").json()
    assert listing["count"] == 1 and listing["confirmed_l"] == amount
    tampered = client.post(f"/api/runs/{run['id']}/confirmations", json={"outlet": outlet, "amount_l": amount + 100})
    assert tampered.status_code == 422 and tampered.json()["code"] == "CONFIRM_MISMATCH"
    unknown = client.post(f"/api/runs/{run['id']}/confirmations", json={"outlet": "999", "amount_l": 1})
    assert unknown.status_code == 404


def test_confirmation_survives_retry_without_double_count(client):
    run = client.post("/api/runs", json={"sample": "dual", "idempotency_key": "confirm-2"}).json()
    rid = run["id"]
    for _ in range(3):
        client.post(f"/api/runs/{rid}/confirmations", json={"outlet": "302", "amount_l": 1400})
    listing = client.get(f"/api/runs/{rid}/confirmations").json()
    assert listing["count"] == 1 and listing["confirmed_l"] == 1400
