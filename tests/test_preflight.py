from __future__ import annotations

import builtins

import pytest
import redis

import preflight


def test_redis_url_with_credentials_works_and_report_redacts_password(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeRedis:
        def ping(self) -> bool:
            return True

    def fake_from_url(url: str, **kwargs: object) -> FakeRedis:
        calls.append(url)
        return FakeRedis()

    monkeypatch.setattr(redis, "from_url", fake_from_url)
    report = preflight.Report()
    url = "redis://nexus:top-secret@127.0.0.1:6380/2"

    preflight._check_redis(url, report)

    assert calls == [url]
    assert report.checks[0].status == "PASS"
    assert "top-secret" not in report.checks[0].detail
    assert "127.0.0.1:6380" in report.checks[0].detail


def test_redis_tcp_fallback_parses_credentials_without_exposing_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    addresses: list[tuple[str, int]] = []
    real_import = builtins.__import__

    def import_without_redis(name: str, *args: object, **kwargs: object) -> object:
        if name == "redis":
            raise ImportError("redis package intentionally hidden for this test")
        return real_import(name, *args, **kwargs)

    class FakeSocket:
        def __enter__(self) -> FakeSocket:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def fake_create_connection(address: tuple[str, int], timeout: int) -> FakeSocket:
        addresses.append(address)
        return FakeSocket()

    monkeypatch.setattr(builtins, "__import__", import_without_redis)
    monkeypatch.setattr(preflight.socket, "create_connection", fake_create_connection)
    report = preflight.Report()

    preflight._check_redis("redis://nexus:top-secret@127.0.0.1:6381/0", report)

    assert addresses == [("127.0.0.1", 6381)]
    assert report.checks[0].status == "PASS"
    assert "top-secret" not in report.checks[0].detail


@pytest.mark.parametrize(
    ("approval_secret", "expected_status"),
    [
        ("short", "FAIL"),
        ("internal-service-secret", "FAIL"),
        ("separate-risk-approval-secret-with-at-least-32-bytes", "PASS"),
    ],
)
def test_preflight_checks_isolated_risk_approval_secret(approval_secret, expected_status):
    report = preflight.Report()

    preflight._check_env_vars(
        {
            "NEXUS_TRADING_MODE": "paper",
            "NEXUS_INTERNAL_API_SECRET": "internal-service-secret",
            "NEXUS_RISK_APPROVAL_SECRET": approval_secret,
        },
        report,
    )

    check = next(item for item in report.checks if item.name == "Firma de riesgo")
    assert check.status == expected_status


# ── LLM provider-aware preflight (2026-11-06 — إقلاع الصندوق السحابي) ──────


def test_cloud_provider_zai_with_key_passes_without_touching_local_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """zai + مفتاح → PASS، ولا يجب أن يُسأل Ollama المحلي إطلاقاً."""

    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("local /v1/models must not be probed for provider=zai")

    monkeypatch.setattr(preflight.urllib.request, "urlopen", boom)
    report = preflight.Report()

    preflight._check_local_ai(
        {"NEXUS_LLM_PROVIDER": "zai", "ZAI_API_KEY": "test-key"}, report
    )

    check = report.checks[0]
    assert check.status == "PASS"
    assert "zai" in check.detail.lower()


def test_cloud_provider_zai_without_key_fails_closed() -> None:
    report = preflight.Report()

    preflight._check_local_ai({"NEXUS_LLM_PROVIDER": "zai"}, report)

    check = report.checks[0]
    assert check.status == "FAIL"
    assert "ZAI_API_KEY" in check.detail


def test_local_provider_unreachable_endpoint_still_fails() -> None:
    """السلوك الأصلي محفوظ: مزوّد local + نهاية ميتة → FAIL (لا تغيير عقد)."""
    report = preflight.Report()

    preflight._check_local_ai(
        {"NEXUS_LLM_PROVIDER": "local", "NEXUS_LOCAL_LLM_URL": "http://127.0.0.1:9/v1"},
        report,
    )

    check = report.checks[0]
    assert check.status == "FAIL"
