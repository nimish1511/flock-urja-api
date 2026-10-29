from fastapi.testclient import TestClient


def test_get_consumption_success(test_client: TestClient):
    resp = test_client.get("/api/v1/meters/J100000/consumption")
    assert resp.status_code == 200
    data = resp.json()

    assert data["meter_id"] == "J100000"
    summary = data["summary"]
    assert summary["reading_count"] == 3
    assert summary["min_kwh"] == 48430.00
    assert summary["max_kwh"] == 48438.74
    assert summary["total_kwh"] == 8.74
    assert summary["avg_voltage_r"] == 225.0

    readings = data["readings"]
    assert len(readings) == 3

    # Check first reading
    r0 = readings[0]
    assert r0["timestamp_raw"] == "23/06/2026 22:30"
    assert "2026-06-23T22:30:00" in r0["timestamp_iso"]
    assert r0["kwh"] == 48430.00
    assert r0["kvah"] == 52300.00
    assert r0["voltage_r"] == 224.0
    assert r0["power_factor"] is not None
    assert 0.90 <= r0["power_factor"] <= 1.0


def test_consumption_meter_not_found(test_client: TestClient):
    resp = test_client.get("/api/v1/meters/NONEXISTENT999/consumption")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error"]["code"] == "METER_NOT_FOUND"
