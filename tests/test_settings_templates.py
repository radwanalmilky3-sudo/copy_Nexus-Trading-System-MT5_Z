"""Settings templates: JSON files on disk + "last settings" rollback snapshot.

Offline suite (no Redis, no live server) covering the template feature added to
``services/nexus_api/routers/intelligence.py``:

1. Routes exist and the write handlers declare the ``CurrentUser`` auth dep.
2. ``GET  /api/intelligence/settings/templates`` → folder path + file list +
   the ``last`` rollback snapshot.
3. ``POST /api/intelligence/settings/templates/save`` writes ``<name>.json``
   under ``config/settings_templates`` (name sanitized, values clamped).
4. ``POST /api/intelligence/settings/templates/load`` returns clamped values,
   drops unknown/invalid keys and refuses any path outside the folder.
5. Every dashboard save snapshots the previous document to
   ``nexus:runtime:settings:last`` (one-click rollback source).
6. The shipped ``config/settings_templates/optimal.json`` stays in sync with
   ``shared.runtime_settings`` (known keys, in-range, list/string choices).
7. Hardening: a shipped **builtin** template can never be overwritten (409),
   a save whose resolved target escapes the folder is refused with nothing
   written, and Windows reserved device names (CON/NUL/LPT3…, with or without
   ``.json``) are rejected for both save and load while ``my-con-1`` still
   works.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_settings_contract import (  # noqa: E402  (shared test doubles)
    FakeRawRedis,
    PermissiveDB,
    _async_value,
)

from services.nexus_api.middleware.auth import CurrentUser  # noqa: E402
from services.nexus_api.routers import intelligence  # noqa: E402
from shared import runtime_settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OPTIMAL_JSON = ROOT / "config" / "settings_templates" / "optimal.json"


# ── 1. Route + auth contract ──────────────────────────────────────────────────

def test_template_routes_are_registered():
    reg = {
        (route.path, method)
        for route in intelligence.router.routes
        for method in (route.methods or set())
    }
    assert ("/api/intelligence/settings/templates", "GET") in reg
    assert ("/api/intelligence/settings/templates/save", "POST") in reg
    assert ("/api/intelligence/settings/templates/load", "POST") in reg


def test_template_write_handlers_declare_auth():
    for fn in (intelligence.save_settings_template, intelligence.load_settings_template):
        params = inspect_params(fn)
        assert "actor" in params, f"{fn.__name__} lost its CurrentUser auth dependency"
        # The router module uses postponed annotations → strings.
        assert params["actor"] in (CurrentUser, "CurrentUser", "actor: CurrentUser"), (
            f"{fn.__name__} actor is no longer a CurrentUser"
        )


def inspect_params(fn: Any) -> dict[str, Any]:
    import inspect

    return {name: param.annotation for name, param in inspect.signature(fn).parameters.items()}


# ── 2. GET /settings/templates ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_templates_returns_path_files_and_last(monkeypatch, tmp_path):
    (tmp_path / "mytemplate.json").write_text(
        json.dumps({"_meta": {"name": "قالبي", "description": "اختبار"},
                    "settings": {"max_daily_trades": 3}}),
        encoding="utf-8",
    )
    store = FakeRawRedis({
        "nexus:runtime:settings": json.dumps({"risk_per_trade_pct": 0.5}),
        "nexus:runtime:settings:last": json.dumps({
            "settings": {"max_daily_trades": 7},
            "saved_at": "2026-10-25T00:00:00+00:00",
        }),
    })
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    payload = await intelligence.list_settings_templates()

    assert payload["path"] == str(tmp_path)
    files = [t["file"] for t in payload["templates"]]
    assert "mytemplate.json" in files
    entry = next(t for t in payload["templates"] if t["file"] == "mytemplate.json")
    assert entry["name"] == "قالبي"
    assert entry["keys"] == 1
    assert entry["valid"] is True
    assert payload["last"]["settings"] == {"max_daily_trades": 7}


@pytest.mark.asyncio
async def test_list_templates_survives_a_broken_file(monkeypatch, tmp_path):
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    store = FakeRawRedis({})
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    payload = await intelligence.list_settings_templates()

    broken = next(t for t in payload["templates"] if t["file"] == "broken.json")
    assert broken["valid"] is False and broken["error"]
    assert payload["last"] is None


# ── 3. POST /settings/templates/save ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_save_template_writes_a_clamped_json_file(monkeypatch, tmp_path):
    store = FakeRawRedis({
        "nexus:runtime:settings": json.dumps({
            "max_daily_trades": 3,
            "risk_per_trade_pct": 0.5,
            "off_hours_allowed": False,
        }),
    })
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    payload = await intelligence.save_settings_template(
        intelligence.TemplateSaveRequest(name="قالب المحاذاة", description="t"),
        actor="tester",
        db=PermissiveDB(),
    )

    assert payload["status"] == "saved"
    path = Path(payload["path"])
    assert path.parent in (tmp_path, tmp_path.resolve())
    assert path.is_file()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["_meta"]["name"] == "قالب المحاذاة"
    assert saved["settings"] == {
        "max_daily_trades": 3,
        "risk_per_trade_pct": 0.5,
        "off_hours_allowed": False,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "", "   ", ".hidden", "x" * 65])
async def test_save_template_rejects_unsafe_names(monkeypatch, tmp_path, bad):
    store = FakeRawRedis({"nexus:runtime:settings": json.dumps({"max_daily_trades": 3})})
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        await intelligence.save_settings_template(
            intelligence.TemplateSaveRequest(name=bad),
            actor="tester",
            db=PermissiveDB(),
        )
    assert exc.value.status_code == 400
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_save_template_requires_an_existing_document(monkeypatch, tmp_path):
    store = FakeRawRedis({})
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        await intelligence.save_settings_template(
            intelligence.TemplateSaveRequest(name="empty"),
            actor="tester",
            db=PermissiveDB(),
        )
    assert exc.value.status_code == 400
    assert list(tmp_path.iterdir()) == []


# ── 4. POST /settings/templates/load ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_template_clamps_and_drops_unknown_keys(monkeypatch, tmp_path):
    (tmp_path / "loaded.json").write_text(
        json.dumps({
            "_meta": {"name": "محمل", "description": "d"},
            "settings": {
                "max_daily_trades": 9999,      # out of range → clamped
                "risk_per_trade_pct": "garbage",  # uninterpretable → dropped
                "backtest_default_symbol": 123,   # wrong type → dropped
                "totally_unknown_key": 1,         # not a runtime key → dropped
                "operational_tf": "M15",      # valid select value
            },
        }),
        encoding="utf-8",
    )
    store = FakeRawRedis({})
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    payload = await intelligence.load_settings_template(
        intelligence.TemplateLoadRequest(file="loaded.json"),
        actor="tester",
        db=PermissiveDB(),
    )

    assert payload["status"] == "ok"
    settings = payload["settings"]
    assert settings["operational_tf"] == "M15"
    assert settings["max_daily_trades"] < 9999  # clamped into _BOUNDS
    assert "risk_per_trade_pct" not in settings
    assert "totally_unknown_key" not in settings
    assert "totally_unknown_key" in payload["dropped"]
    # Nothing loadable may exceed the backend clamps.
    for key, value in settings.items():
        if key in runtime_settings._BOUNDS:
            lo, hi = runtime_settings._BOUNDS[key]
            assert lo <= value <= hi, f"{key}={value} escapes {lo}..{hi}"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["../evil.json", "..\\evil.json", "evil.json.bak", "", "a/b.json"])
async def test_load_template_refuses_paths_outside_the_folder(monkeypatch, tmp_path, bad):
    store = FakeRawRedis({})
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        await intelligence.load_settings_template(
            intelligence.TemplateLoadRequest(file=bad),
            actor="tester",
            db=PermissiveDB(),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_load_template_404_for_a_missing_file(monkeypatch, tmp_path):
    store = FakeRawRedis({})
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        await intelligence.load_settings_template(
            intelligence.TemplateLoadRequest(file="nope.json"),
            actor="tester",
            db=PermissiveDB(),
        )
    assert exc.value.status_code == 404


# ── 5. "last settings" rollback snapshot ─────────────────────────────────────

@pytest.mark.asyncio
async def test_dashboard_save_snapshots_the_previous_document(monkeypatch):
    previous = {"max_daily_trades": 5, "risk_per_trade_pct": 1.0}
    store = FakeRawRedis({"nexus:runtime:settings": json.dumps(previous)})
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))

    await intelligence.update_dynamic_settings(
        intelligence.DynamicSettingsUpdate(settings={"max_daily_trades": 9}),
        actor="tester",
        db=PermissiveDB(),
    )

    snapshot = json.loads(store.kv["nexus:runtime:settings:last"])
    assert snapshot["settings"] == previous, "rollback snapshot must hold the PRE-save document"
    assert snapshot["saved_at"]
    # …and the live document moved on.
    assert json.loads(store.kv["nexus:runtime:settings"])["max_daily_trades"] == 9


# ── 6. Shipped template stays in sync with the runtime contract ──────────────

def test_shipped_optimal_template_exists_and_is_pure_settings():
    assert OPTIMAL_JSON.is_file(), "config/settings_templates/optimal.json is missing"
    data = json.loads(OPTIMAL_JSON.read_text(encoding="utf-8"))
    assert isinstance(data.get("_meta"), dict)
    assert data["_meta"].get("name"), "template needs a display name"
    settings = data["settings"]
    assert isinstance(settings, dict) and len(settings) >= 44

    unknown = sorted(key for key in settings if key not in runtime_settings.DEFAULTS)
    assert not unknown, f"optimal.json carries keys the runtime does not know: {unknown}"

    # sanitize_patch must keep every value verbatim: in-range, right type.
    clean = runtime_settings.sanitize_patch(settings)
    assert clean == settings, (
        "optimal.json contains out-of-range or uninterpretable values; "
        f"sanitize changed: { {k: (settings[k], clean.get(k)) for k in settings if clean.get(k) != settings[k]} }"
    )


def test_shipped_optimal_template_covers_every_page_field():
    """The one-click template must fill the whole General Settings form."""
    import io
    import re

    source = io.open(
        ROOT / "dashboard" / "src" / "app" / "dashboard" / "settings" / "page.tsx",
        encoding="utf-8",
    ).read()
    block = re.search(r"const RUNTIME_SECTIONS\b.*?=\s*\[(?P<body>.*?)\n\];", source, flags=re.S)
    assert block, "RUNTIME_SECTIONS not found"
    page_keys = set(re.findall(r"key: '([A-Za-z0-9_]+)'", block.group("body")))

    settings = json.loads(OPTIMAL_JSON.read_text(encoding="utf-8"))["settings"]
    missing = sorted(page_keys - set(settings))
    # allowed_sessions lives in the session-gate card (not RUNTIME_SECTIONS)
    # but is part of the template too.
    assert "allowed_sessions" in settings, "template must also carry the session gate"
    assert not missing, f"optimal.json does not fill these page fields: {missing}"


# ── 7. Hardening: builtin protection (A) ──────────────────────────────────────

def _seed_store(monkeypatch, settings: dict[str, Any] | None = None) -> FakeRawRedis:
    """Install a fake settings store holding ``settings`` (default: 3 trades)."""
    doc = {"max_daily_trades": 3} if settings is None else settings
    store = FakeRawRedis({"nexus:runtime:settings": json.dumps(doc)})
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))
    return store


def test_shipped_optimal_template_is_flagged_builtin():
    """The guard only exists because the shipped preset declares builtin."""
    meta = json.loads(OPTIMAL_JSON.read_text(encoding="utf-8"))["_meta"]
    assert meta.get("builtin") is True


@pytest.mark.asyncio
async def test_save_refuses_to_overwrite_a_builtin_template(monkeypatch, tmp_path):
    builtin = {
        "_meta": {"name": "أفضل الإعدادات (مدمج)", "description": "m",
                  "saved_at": "2026-01-01T00:00:00+00:00", "builtin": True},
        "settings": {"max_daily_trades": 3},
    }
    original = json.dumps(builtin, ensure_ascii=False, indent=2)
    (tmp_path / "optimal.json").write_text(original, encoding="utf-8")
    _seed_store(monkeypatch, {"max_daily_trades": 9})
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        await intelligence.save_settings_template(
            intelligence.TemplateSaveRequest(name="optimal", description="x"),
            actor="tester",
            db=PermissiveDB(),
        )

    assert exc.value.status_code == 409
    assert "مدمج" in str(exc.value.detail), "the Arabic detail must explain it is builtin"
    # Byte-for-byte unchanged: no silent overwrite, no builtin: false persisted.
    assert (tmp_path / "optimal.json").read_text(encoding="utf-8") == original
    assert json.loads(original)["_meta"]["builtin"] is True
    assert sorted(p.name for p in tmp_path.iterdir()) == ["optimal.json"]


@pytest.mark.asyncio
async def test_save_still_persists_a_non_builtin_name(monkeypatch, tmp_path):
    (tmp_path / "optimal.json").write_text(
        json.dumps({"_meta": {"name": "m", "builtin": True},
                    "settings": {"max_daily_trades": 3}}, ensure_ascii=False),
        encoding="utf-8",
    )
    _seed_store(monkeypatch)
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    payload = await intelligence.save_settings_template(
        intelligence.TemplateSaveRequest(name="my preset", description="d"),
        actor="tester",
        db=PermissiveDB(),
    )

    assert payload["status"] == "saved"
    saved = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
    assert saved["_meta"]["builtin"] is False
    assert saved["settings"] == {"max_daily_trades": 3}
    # the builtin neighbour is untouched
    other = json.loads((tmp_path / "optimal.json").read_text(encoding="utf-8"))
    assert other["_meta"]["builtin"] is True


# ── 8. Hardening: save must never leave the folder (B) ────────────────────────

def _plant_escape_link(folder: Path, name: str, outside: Path) -> bool:
    """Make ``folder/<name>.json`` resolve to ``outside`` (a link/junction).

    File symlinks need a privilege this process usually lacks, so a directory
    junction (no privilege required on Windows) is tried first. Returns False
    when no link type can be created, so the caller can emulate one.
    """
    link = folder / f"{name}.json"
    try:
        import _winapi

        _winapi.CreateJunction(str(outside), str(link))
        return True
    except Exception:  # noqa: BLE001 - fall through to a plain symlink
        pass
    try:
        os.symlink(str(outside), str(link), target_is_directory=True)
        return True
    except OSError:
        return False


@pytest.mark.asyncio
async def test_save_refuses_a_target_that_resolves_outside_the_folder(monkeypatch, tmp_path):
    folder = tmp_path / "templates"
    outside = tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    _seed_store(monkeypatch)
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", folder)

    if not _plant_escape_link(folder, "escape", outside):
        # The OS denied links: emulate exactly what a link would do — make
        # resolve() of the target land outside the folder.
        real_resolve = Path.resolve

        def _resolve(self, strict=False):
            resolved = real_resolve(self, strict=strict)
            if resolved.name == "escape.json" and resolved.parent == folder.resolve():
                return real_resolve(outside / "escape.json")
            return resolved

        monkeypatch.setattr(Path, "resolve", _resolve)

    with pytest.raises(HTTPException) as exc:
        await intelligence.save_settings_template(
            intelligence.TemplateSaveRequest(name="escape"),
            actor="tester",
            db=PermissiveDB(),
        )

    assert exc.value.status_code == 400
    assert list(outside.iterdir()) == [], "nothing may be written outside the folder"
    assert not (folder / "escape.json").is_file(), "no file may be written for a target that escapes"


@pytest.mark.asyncio
async def test_save_target_inside_the_folder_is_still_writable(monkeypatch, tmp_path):
    """The escape guard must not block an ordinary in-folder save."""
    _seed_store(monkeypatch)
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    payload = await intelligence.save_settings_template(
        intelligence.TemplateSaveRequest(name="ordinary"),
        actor="tester",
        db=PermissiveDB(),
    )
    assert Path(payload["path"]).parent in (tmp_path, tmp_path.resolve())
    assert Path(payload["path"]).is_file()


# ── 9. Hardening: Windows reserved device names (C) ───────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["CON", "con", "nul", "NUL", "LPT3", "aux", "COM1", "PrN"])
async def test_save_refuses_windows_reserved_device_names(monkeypatch, tmp_path, bad):
    _seed_store(monkeypatch)
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        await intelligence.save_settings_template(
            intelligence.TemplateSaveRequest(name=bad),
            actor="tester",
            db=PermissiveDB(),
        )

    assert exc.value.status_code == 400
    assert "ويندوز" in str(exc.value.detail), "the Arabic detail must name Windows"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["con.json", "NUL.json", "lpt9.json", "prn.json", "COM3.json"])
async def test_load_refuses_windows_reserved_device_names(monkeypatch, tmp_path, bad):
    _seed_store(monkeypatch)
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        await intelligence.load_settings_template(
            intelligence.TemplateLoadRequest(file=bad),
            actor="tester",
            db=PermissiveDB(),
        )

    assert exc.value.status_code == 400, "a reserved name must be refused, not looked up"
    assert "ويندوز" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_names_merely_containing_reserved_words_stay_allowed(monkeypatch, tmp_path):
    _seed_store(monkeypatch)
    monkeypatch.setattr(intelligence, "_TEMPLATES_DIR", tmp_path)

    payload = await intelligence.save_settings_template(
        intelligence.TemplateSaveRequest(name="my-con-1", description="d"),
        actor="tester",
        db=PermissiveDB(),
    )
    assert payload["status"] == "saved"

    loaded = await intelligence.load_settings_template(
        intelligence.TemplateLoadRequest(file="my-con-1.json"),
        actor="tester",
        db=PermissiveDB(),
    )
    assert loaded["status"] == "ok"

    # …and a reserved stem is still the only thing refused: an unknown but
    # legal name answers 404 (it passed the gate), never 400.
    with pytest.raises(HTTPException) as exc:
        await intelligence.load_settings_template(
            intelligence.TemplateLoadRequest(file="my-con-9.json"),
            actor="tester",
            db=PermissiveDB(),
        )
    assert exc.value.status_code == 404
