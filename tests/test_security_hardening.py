import asyncio
import hashlib
from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient
from app import app
from routers.auth import hash_password, verify_password
from safe_url_fetch import resolve_public


def test_scrypt_and_legacy():
    password = "safe-test-password"
    a, b = hash_password(password), hash_password(password)
    assert a != b and a.startswith("scrypt$")
    assert verify_password(password, a)
    assert not verify_password("wrong", a)
    assert verify_password(password, hashlib.sha256(password.encode()).hexdigest())


@pytest.mark.parametrize("path", ["/api/results/0/scores?task_id=t1", "/api/results/0/details?task_id=t1", "/api/brands", "/api/tasks"])
def test_anonymous_business_api_denied(path):
    assert TestClient(app).get(path).status_code == 401


@pytest.mark.parametrize("path", ["/api/results/0/backfill-citations", "/api/results/0/backfill-url-uc", "/api/evaluations/0/recalculate-scores"])
def test_viewer_cannot_write(path):
    with patch("app.verify_session", AsyncMock(return_value={"role":"viewer","username":"reader"})):
        assert TestClient(app).post(path, headers={"Authorization":"Bearer test"}).status_code == 403


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "::ffff:127.0.0.1", "0.0.0.0"])
def test_private_dns_rejected(ip):
    with patch("socket.getaddrinfo", return_value=[(2,1,6,'',(ip,80))]):
        with pytest.raises(ValueError):resolve_public("http://example.test/path")


def test_public_dns_allowed():
    with patch("socket.getaddrinfo", return_value=[(2,1,6,'',('8.8.8.8',443))]):
        assert resolve_public("https://example.test/")[2] == '8.8.8.8'


def test_bootstrap_not_public():
    from routers.auth import login
    from fastapi import HTTPException
    with patch("routers.auth.db.get_user_by_username",AsyncMock(return_value=None)), patch("routers.auth.db.get_admin_password_hash",AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as e:asyncio.run(login({"username":"admin","password":"a-new-password"}))
        assert e.value.status_code == 403
