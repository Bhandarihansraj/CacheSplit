"""
tests/test_ui_routes.py
Verifies that all frontend dashboard pages, scripts, and static assets return HTTP 200.
"""
import pytest
from starlette.testclient import TestClient
from api.server import app

client = TestClient(app)

def test_root_and_dashboard_pages():
    for path in ["/", "/dashboard", "/dashboard.html", "/index.html"]:
        res = client.get(path)
        assert res.status_code == 200, f"Failed on {path}: {res.text}"
        assert "CacheSplit" in res.text or "text/html" in res.headers.get("content-type", "")

def test_v4_dashboard_page():
    for path in ["/v4", "/v4_dashboard", "/v4_dashboard.html"]:
        res = client.get(path)
        assert res.status_code == 200, f"Failed on {path}: {res.text}"
        assert "<!DOCTYPE html>" in res.text

def test_auxiliary_pages():
    for path in ["/simulation", "/simulation_dashboard.html", "/demo", "/developer_demo.html", "/test_cases", "/test_cases.html"]:
        res = client.get(path)
        assert res.status_code == 200, f"Failed on {path}: {res.text}"

def test_static_js_and_css_assets():
    assets = [
        ("/style.css", "text/css"),
        ("/app.js", "javascript"),
        ("/app_v4.js", "javascript"),
        ("/services_v4.js", "javascript"),
    ]
    for path, expected_type in assets:
        res = client.get(path)
        assert res.status_code == 200, f"Asset {path} failed with {res.status_code}"
        assert expected_type in res.headers.get("content-type", "")
