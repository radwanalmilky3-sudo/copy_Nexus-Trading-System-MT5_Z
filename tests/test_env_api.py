"""Safe .env settings API (``services/nexus_api/routers/env.py``).

Offline suite (no live server, no real ``.env`` access) mirroring
``test_settings_templates.py``:

1. Routes registered on the imported router + ``CurrentUser`` auth dep on POST.
2. ``GET /api/system/env`` — reads a tmp ``.env`` (allow-list keys, comments,
   CRLF, one secret line), returns categories/readonly flags, reports
   ``secrets_protected == 12`` and leaks neither the secret key nor value.
3. ``POST /api/system/env`` — valid int/bool/enum writes create a
   ``.env.bak.*`` backup, update the target line, preserve comments, other
   lines and CRLF, and answer with ``backup`` + ``restart_required: true``.
4. Rejections: unknown / readonly / deny-listed key (same generic 400),
   out-of-range int, bad enum, newline injection, >512 chars — file unchanged.
5. ``DenyDB`` ⇒ 403 before any file work.
6. Backup failure (``shutil.copy2`` raises ``OSError``) ⇒ 503, file unchanged.
7. Backup hygiene: two writes in the same second keep two distinct
   ``.env.bak.*`` files, accumulation is pruned to the newest 20 (``.env``,
   ``.env.example`` and non-matching names untouched) and a prune failure
   never fails an already successful write.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_settings_contract import DenyDB, PermissiveDB  # noqa: E402  (doubles)

from services.nexus_api.middleware.auth import CurrentUser  # noqa: E402
from services.nexus_api.routers import env  # noqa: E402


def _inspect_params(fn: Any) -> dict[str, Any]:
    return {name: p.annotation for name, p in inspect.signature(fn).parameters.items()}


def _write_env(path: Path, content: str) -> bytes:
    """Write the fixture exactly as bytes so CRLF survives on any platform."""
    raw = content.encode("utf-8")
    path.write_bytes(raw)
    return raw


# ── 1. Route + auth contract ──────────────────────────────────────────────────

def test_env_routes_are_registered():
    reg = {
        (route.path, method)
        for route in env.router.routes
        for method in (route.methods or set())
    }
    assert ("/api/system/env", "GET") in reg
    assert ("/api/system/env", "POST") in reg


def test_post_handler_declares_auth_and_permission_check():
    params = _inspect_params(env.update_env_setting)
    assert "actor" in params, "POST lost its CurrentUser auth dependency"
    # The router module uses postponed annotations → strings.
    assert params["actor"] in (CurrentUser, "CurrentUser", "actor: CurrentUser"), (
        "update_env_setting actor is no longer a CurrentUser"
    )
    source = inspect.getsource(env.update_env_setting)
    assert source.index("_require(db, actor") < source.index("_backup_env"), (
        "the trading.settings check must fire before any file work"
    )


def test_get_route_carries_the_settings_read_dependency():
    from fastapi.routing import APIRoute

    route = next(
        r for r in env.router.routes
        if isinstance(r, APIRoute) and r.path == "/api/system/env" and "GET" in (r.methods or set())
    )
    dep_calls = [d.call for d in route.dependant.dependencies]
    assert env._env_read in dep_calls


# ── 2. GET: parse file, metadata, secret filtering ────────────────────────────

@pytest.mark.asyncio
async def test_get_returns_values_categories_and_never_leaks_secrets(monkeypatch, tmp_path):
    secret_key = "MT5_PASSWORD"
    secret_value = "hunter2-very-secret-value"
    original = _write_env(
        tmp_path / ".env",
        "# top comment\r\n"
        "NEXUS_MIN_VERDICT_CONVICTION=70   # inline comment\r\n"
        "NEXUS_DATA_SYNTHETIC_FALLBACK=1\r\n"
        "NEXUS_TRADING_MODE=paper\r\n"
        "NEXUS_ML_PRIORITY=1\r\n"
        "NEXUS_LLM_PROVIDER=zai\r\n"
        f"{secret_key}={secret_value}\r\n"
        "SOME_UNRELATED_KEY=keep-me\r\n",
    )
    assert b"\r\n" in original  # fixture really is CRLF
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    payload = await env.get_env_settings()

    assert payload["env_file"] == str(tmp_path / ".env")
    assert payload["secrets_protected"] == 12
    assert payload["mode"] == "paper"

    by_key = {v["key"]: v for v in payload["vars"]}

    conviction = by_key["NEXUS_MIN_VERDICT_CONVICTION"]
    assert conviction["value"] == "70"          # inline comment stripped
    assert conviction["unset"] is False
    assert conviction["type"] == "int"
    assert conviction["min"] == 0 and conviction["max"] == 100
    assert conviction["category"] == "core" and conviction["editable"] is True
    assert conviction["restart_required"] is True

    fallback = by_key["NEXUS_DATA_SYNTHETIC_FALLBACK"]
    assert fallback["value"] == "1"
    assert fallback["type"] == "bool"
    assert fallback["category"] == "danger" and fallback["editable"] is True
    assert fallback["warning"]

    mode = by_key["NEXUS_TRADING_MODE"]
    assert mode["value"] == "paper"
    assert mode["category"] == "readonly" and mode["editable"] is False

    provider = by_key["NEXUS_LLM_PROVIDER"]
    assert provider["value"] == "zai"
    assert provider["choices"] == ["local", "zai"]  # mirrors shared/llm_factory.SUPPORTED_PROVIDERS

    ml_priority = by_key["NEXUS_ML_PRIORITY"]
    assert ml_priority["value"] == "1"
    assert ml_priority["choices"] == ["0", "1"]

    absent = by_key["STRATEGY_MIN_SHARPE"]
    assert absent["value"] is None and absent["unset"] is True

    # The secret — key AND value — must appear nowhere in the serialized reply.
    text = json.dumps(payload, ensure_ascii=False)
    assert secret_key not in text
    assert secret_value not in text
    assert "SOME_UNRELATED_KEY" not in text
    assert len(env.SECRET_KEYS) == 12
    assert all(k not in text for k in env.SECRET_KEYS)


@pytest.mark.asyncio
async def test_get_on_missing_file_reports_everything_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    payload = await env.get_env_settings()

    assert payload["mode"] == "paper"
    assert payload["secrets_protected"] == 12
    assert all(v["value"] is None and v["unset"] for v in payload["vars"])


# ── 3. POST: valid int / bool / enum writes ───────────────────────────────────

@pytest.mark.asyncio
async def test_post_writes_int_bool_enum_with_backup_and_crlf_preserved(monkeypatch, tmp_path):
    original = _write_env(
        tmp_path / ".env",
        "# header comment\r\n"
        "NEXUS_MIN_VERDICT_CONVICTION=70\r\n"
        "NEXUS_DISABLE_RESEARCH=0\r\n"
        "NEXUS_LLM_PROVIDER=local   # keep this comment\r\n"
        "NEXUS_DATA_SYNTHETIC_FALLBACK=0\r\n"
        "# tail comment\r\n",
    )
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    # int
    resp = await env.update_env_setting(
        env.EnvUpdate(key="NEXUS_MIN_VERDICT_CONVICTION", value="85"),
        actor="tester", db=PermissiveDB(),
    )
    assert resp["status"] == "saved"
    assert resp["key"] == "NEXUS_MIN_VERDICT_CONVICTION"
    assert resp["value"] == "85"
    assert resp["restart_required"] is True
    assert Path(resp["backup"]).is_file()
    assert Path(resp["backup"]).name.startswith(".env.bak.")

    # bool → stored normalized as 1
    resp = await env.update_env_setting(
        env.EnvUpdate(key="NEXUS_DISABLE_RESEARCH", value="true"),
        actor="tester", db=PermissiveDB(),
    )
    assert resp["value"] == "1"
    assert Path(resp["backup"]).is_file()

    # enum
    resp = await env.update_env_setting(
        env.EnvUpdate(key="NEXUS_LLM_PROVIDER", value="zai"),
        actor="tester", db=PermissiveDB(),
    )
    assert resp["value"] == "zai"
    assert resp["restart_required"] is True
    backups = sorted(tmp_path.glob(".env.bak.*"))
    assert len(backups) >= 1
    assert resp["backup"] == str(backups[-1].resolve())

    text = (tmp_path / ".env").read_bytes().decode("utf-8")
    assert "NEXUS_MIN_VERDICT_CONVICTION=85\r\n" in text
    assert "NEXUS_DISABLE_RESEARCH=1\r\n" in text
    assert "NEXUS_LLM_PROVIDER=zai   # keep this comment\r\n" in text
    # comments / other lines / CRLF preserved, order unchanged
    assert "# header comment" in text and "# tail comment" in text
    assert "NEXUS_DATA_SYNTHETIC_FALLBACK=0\r\n" in text
    assert text.replace("\r\n", "").find("\n") == -1, "bare LF must not be introduced"
    assert text.index("NEXUS_MIN_VERDICT_CONVICTION") < text.index("# tail comment")
    # original value was backed up byte-for-byte before the first write
    assert original != (tmp_path / ".env").read_bytes()


@pytest.mark.asyncio
async def test_post_appends_the_key_when_missing(monkeypatch, tmp_path):
    _write_env(tmp_path / ".env", "# only a comment\r\nNEXUS_ENV=development\r\n")
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    resp = await env.update_env_setting(
        env.EnvUpdate(key="IBKR_PORT", value="7497"),
        actor="tester", db=PermissiveDB(),
    )

    assert resp["status"] == "saved" and resp["value"] == "7497"
    text = (tmp_path / ".env").read_bytes().decode("utf-8")
    assert text.endswith("IBKR_PORT=7497\r\n")
    assert "NEXUS_ENV=development\r\n" in text


# ── 4. POST: rejections (400, file untouched) ─────────────────────────────────

_GENERIC_KEYS = [
    ("NOT_A_REAL_KEY", "1"),            # unknown key
    ("NEXUS_TRADING_MODE", "live"),     # readonly key
    ("MT5_PASSWORD", "hunter3"),        # deny-listed secret
]

@pytest.mark.parametrize("key,value", _GENERIC_KEYS)
@pytest.mark.asyncio
async def test_post_refuses_non_editable_keys_with_generic_400(monkeypatch, tmp_path, key, value):
    original = _write_env(tmp_path / ".env", "NEXUS_TRADING_MODE=paper\r\nMT5_PASSWORD=x\r\n")
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    with pytest.raises(HTTPException) as exc:
        await env.update_env_setting(
            env.EnvUpdate(key=key, value=value), actor="tester", db=PermissiveDB(),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == env._GENERIC_REFUSAL
    assert (tmp_path / ".env").read_bytes() == original
    assert list(tmp_path.glob(".env.bak.*")) == []


@pytest.mark.parametrize("key,value", [
    ("NEXUS_MIN_VERDICT_CONVICTION", "150"),   # out of range int (max 100)
    ("NEXUS_MIN_VERDICT_CONVICTION", "abc"),   # not an int
    ("IBKR_PORT", "0"),                        # out of range int (min 1)
    ("NEXUS_LLM_PROVIDER", "claude"),          # bad enum choice
    ("NEXUS_ENV", "Production"),               # enum is exact-match
    ("NEXUS_DISABLE_RESEARCH", "2"),           # bool only 0/1/true/false
    ("NEXUS_MIN_VERDICT_CONVICTION", "70\nEVIL_KEY=1"),  # newline injection
    ("NEXUS_MIN_VERDICT_CONVICTION", "70\rEVIL=1"),      # CR injection
    ("NEXUS_LLM_MODEL", "x" * 513),            # > 512 chars
    ("NEXUS_RESEARCH_SYMBOL", "bad symbol!"),  # str pattern
])
@pytest.mark.asyncio
async def test_post_rejects_invalid_values_with_400(monkeypatch, tmp_path, key, value):
    original = _write_env(
        tmp_path / ".env",
        "NEXUS_MIN_VERDICT_CONVICTION=70\r\nIBKR_PORT=7496\r\n"
        "NEXUS_LLM_PROVIDER=zai\r\nNEXUS_DISABLE_RESEARCH=0\r\n"
        "NEXUS_LLM_MODEL=qwen\r\nNEXUS_ENV=development\r\n"
        "NEXUS_RESEARCH_SYMBOL=EURUSD\r\n",
    )
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    with pytest.raises(HTTPException) as exc:
        await env.update_env_setting(
            env.EnvUpdate(key=key, value=value), actor="tester", db=PermissiveDB(),
        )

    assert exc.value.status_code == 400
    assert (tmp_path / ".env").read_bytes() == original
    assert list(tmp_path.glob(".env.bak.*")) == []


@pytest.mark.asyncio
async def test_post_out_of_range_message_states_the_expected_range(monkeypatch, tmp_path):
    _write_env(tmp_path / ".env", "NEXUS_RESEARCH_INTERVAL_SEC=600\r\n")
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    with pytest.raises(HTTPException) as exc:
        await env.update_env_setting(
            env.EnvUpdate(key="NEXUS_RESEARCH_INTERVAL_SEC", value="99999"),
            actor="tester", db=PermissiveDB(),
        )

    assert exc.value.status_code == 400
    assert "300" in str(exc.value.detail) and "7200" in str(exc.value.detail)


# ── 5. POST: permission denial (DenyDB ⇒ 403, no write) ───────────────────────

@pytest.mark.asyncio
async def test_post_permission_denied_never_touches_the_file(monkeypatch, tmp_path):
    original = _write_env(tmp_path / ".env", "NEXUS_MIN_VERDICT_CONVICTION=70\r\n")
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    with pytest.raises(HTTPException) as exc:
        await env.update_env_setting(
            env.EnvUpdate(key="NEXUS_MIN_VERDICT_CONVICTION", value="80"),
            actor="tester", db=DenyDB(),
        )

    assert exc.value.status_code == 403
    assert (tmp_path / ".env").read_bytes() == original
    assert list(tmp_path.glob(".env.bak.*")) == [], "no backup may be created"


# ── 6. POST: backup failure ⇒ 503, file untouched ─────────────────────────────

@pytest.mark.asyncio
async def test_backup_failure_returns_503_and_writes_nothing(monkeypatch, tmp_path):
    original = _write_env(tmp_path / ".env", "NEXUS_MIN_VERDICT_CONVICTION=70\r\n")
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    def _boom(src, dst, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(env.shutil, "copy2", _boom)

    with pytest.raises(HTTPException) as exc:
        await env.update_env_setting(
            env.EnvUpdate(key="NEXUS_MIN_VERDICT_CONVICTION", value="80"),
            actor="tester", db=PermissiveDB(),
        )

    assert exc.value.status_code == 503
    assert (tmp_path / ".env").read_bytes() == original
    # no stray temp files either
    assert [p.name for p in tmp_path.iterdir()] == [".env"]


# ── 7. Backup hygiene: same-second uniqueness + retention cap ─────────────────

class _FrozenClock:
    """Stand-in for ``datetime`` inside ``_backup_env`` (frozen second)."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 25, 12, 0, 0, tzinfo=tz)


@pytest.mark.asyncio
async def test_two_saves_in_the_same_second_keep_two_distinct_backups(monkeypatch, tmp_path):
    original = _write_env(
        tmp_path / ".env",
        "NEXUS_MIN_VERDICT_CONVICTION=70\r\nNEXUS_LLM_PROVIDER=zai\r\n",
    )
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")
    monkeypatch.setattr(env, "datetime", _FrozenClock)  # force the collision

    first = await env.update_env_setting(
        env.EnvUpdate(key="NEXUS_MIN_VERDICT_CONVICTION", value="80"),
        actor="tester", db=PermissiveDB(),
    )
    second = await env.update_env_setting(
        env.EnvUpdate(key="NEXUS_LLM_PROVIDER", value="zai"),
        actor="tester", db=PermissiveDB(),
    )

    names = sorted(p.name for p in tmp_path.glob(".env.bak.*"))
    assert names == [".env.bak.20261025_120000", ".env.bak.20261025_120000_2"], names
    assert first["backup"] != second["backup"], "the second save must not overwrite the backup"
    assert Path(first["backup"]).read_bytes() == original, "backup is taken before the write"
    text = (tmp_path / ".env").read_bytes().decode("utf-8")
    assert "NEXUS_MIN_VERDICT_CONVICTION=80\r\n" in text
    assert "NEXUS_LLM_PROVIDER=zai\r\n" in text


@pytest.mark.asyncio
async def test_backups_are_pruned_to_the_newest_twenty(monkeypatch, tmp_path):
    _write_env(tmp_path / ".env", "NEXUS_MIN_VERDICT_CONVICTION=70\r\n")
    (tmp_path / ".env.example").write_bytes(b"# template\r\n")
    (tmp_path / ".env.bak").write_bytes(b"legacy backup without suffix\r\n")
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")

    now = time.time()
    oldest = newest = None
    for i in range(25):                      # 25 old backups …
        old = tmp_path / f".env.bak.20200101_{i:06d}"
        old.write_bytes(b"old")
        stamp = now - 5000 + i               # strictly increasing mtimes
        os.utime(old, (stamp, stamp))
        if oldest is None:
            oldest = old
        newest = old

    resp = await env.update_env_setting(
        env.EnvUpdate(key="NEXUS_MIN_VERDICT_CONVICTION", value="80"),
        actor="tester", db=PermissiveDB(),
    )

    backups = list(tmp_path.glob(".env.bak.*"))
    assert len(backups) == env._BACKUP_KEEP == 20, f"expected 20, got {len(backups)}"
    assert newest.exists(), "the newest pre-existing backup must survive"
    assert not oldest.exists(), "the oldest backup must be pruned"
    assert Path(resp["backup"]).exists(), "the backup just created must survive"
    # nothing outside the `.env.bak.*` family may ever be touched
    assert (tmp_path / ".env.example").read_bytes() == b"# template\r\n"
    assert (tmp_path / ".env.bak").read_bytes() == b"legacy backup without suffix\r\n"
    assert b"NEXUS_MIN_VERDICT_CONVICTION=80" in (tmp_path / ".env").read_bytes()


@pytest.mark.asyncio
async def test_prune_failure_never_fails_a_successful_write(monkeypatch, tmp_path, caplog):
    _write_env(tmp_path / ".env", "NEXUS_MIN_VERDICT_CONVICTION=70\r\n")
    monkeypatch.setattr(env, "_env_path", lambda: tmp_path / ".env")
    for i in range(25):
        (tmp_path / f".env.bak.20200101_{i:06d}").write_bytes(b"old")

    def _deny(self, *args, **kwargs):        # every unlink throws
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "unlink", _deny)

    with caplog.at_level("WARNING"):
        resp = await env.update_env_setting(
            env.EnvUpdate(key="NEXUS_MIN_VERDICT_CONVICTION", value="80"),
            actor="tester", db=PermissiveDB(),
        )

    assert resp["status"] == "saved", "a prune failure must never fail the request"
    assert b"NEXUS_MIN_VERDICT_CONVICTION=80" in (tmp_path / ".env").read_bytes()
    assert len(list(tmp_path.glob(".env.bak.*"))) == 26, "nothing may be lost on failure"
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("env.backup_prune_failed" in w for w in warnings), warnings
    logged = next(w for w in warnings if "env.backup_prune_failed" in w)
    assert "NEXUS_MIN_VERDICT_CONVICTION" in logged, "the key must identify the failure"
    assert "80" not in logged, "values must never be logged"
