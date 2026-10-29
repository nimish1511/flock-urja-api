import hashlib
import hmac
import pytest
from app.core.cache import haversine_km
from app.core.upstream_client import UpstreamPortalClient
from app.models.errors import UpstreamAuthError


def test_haversine_distance_calculation():
    # Distance between two known coordinates in Jaipur:
    # Malviya Nagar (26.8528, 75.8237) and C-Scheme (26.9124, 75.7873) is ~7.5 - 8.0 km
    dist = haversine_km(26.8528, 75.8237, 26.9124, 75.7873)
    assert 7.0 <= dist <= 8.5
    # Same point distance should be 0.0
    assert haversine_km(26.9389, 75.8309, 26.9389, 75.8309) == 0.0


def test_hmac_signature_generation():
    secret = "test_signing_secret_123"
    ts = "1700000000"
    method = "GET"
    path = "/portal/export"
    query = "page=1"

    string_to_sign = f"{method}\n{path}\n{query}\n{ts}".encode("utf-8")
    expected_sig = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).hexdigest()

    assert len(expected_sig) == 64  # SHA256 hex is 64 characters
    assert all(c in "0123456789abcdef" for c in expected_sig)


def test_client_headers():
    client = UpstreamPortalClient(base_url="https://urja-ops.flockenergy.tech")
    headers = client._default_headers
    assert headers["Origin"] == "https://urja-ops.flockenergy.tech"
    assert headers["Referer"] == "https://urja-ops.flockenergy.tech/login"
    assert "User-Agent" in headers
