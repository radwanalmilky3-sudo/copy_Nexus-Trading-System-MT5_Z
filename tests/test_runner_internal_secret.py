from __future__ import annotations

import pytest

import run


def test_runner_requires_internal_service_secret(capsys):
    with pytest.raises(SystemExit):
        run._validate_env({"NEXUS_SECRET_KEY": "configured", "REDIS_URL": "redis://localhost"})

    assert "NEXUS_INTERNAL_API_SECRET" in capsys.readouterr().out


def _valid_env():
    return {
        "NEXUS_SECRET_KEY": "internal-signing-secret",
        "NEXUS_INTERNAL_API_SECRET": "internal-service-secret",
        "NEXUS_RISK_APPROVAL_SECRET": "separate-risk-approval-secret-with-at-least-32-bytes",
        "NEXUS_JWT_SECRET": "a-long-random-jwt-secret-with-at-least-32-chars",
        "REDIS_URL": "redis://localhost",
    }


@pytest.mark.parametrize("secret", ["", "change-me-jwt-secret", "short"])
def test_runner_rejects_missing_placeholder_or_short_jwt_secret(secret, capsys):
    env = _valid_env()
    env["NEXUS_JWT_SECRET"] = secret

    with pytest.raises(SystemExit):
        run._validate_env(env)

    assert "NEXUS_JWT_SECRET" in capsys.readouterr().out


def test_runner_accepts_configured_strong_jwt_secret():
    run._validate_env(_valid_env())


@pytest.mark.parametrize("approval_secret", ["", "short", "internal-service-secret"])
def test_runner_rejects_missing_weak_or_shared_risk_approval_secret(approval_secret, capsys):
    env = _valid_env()
    env["NEXUS_RISK_APPROVAL_SECRET"] = approval_secret

    with pytest.raises(SystemExit):
        run._validate_env(env)

    assert "NEXUS_RISK_APPROVAL_SECRET" in capsys.readouterr().out
