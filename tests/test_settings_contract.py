"""Contract tests for the dashboard **General Settings** tab ↔ nexus-api backend.

Everything here is offline: routers are imported directly and their handlers are
called with mocked persistence (no Redis, no http://127.0.0.1, no live server).

Coverage:

1. Route contract — every settings endpoint the frontend calls
   (``dashboard/src/app/dashboard/settings/page.tsx`` ``loadAll`` fetches +
   ``dashboard/src/lib/api-client.ts`` settings/system methods) must exist on the
   imported routers (config / risk / intelligence / system / regime / positions
   / env).
2. Response shape — handlers are executed with mocked persistence and the exact
   keys the page reads (``settings``, ``session_gate``, ``agents``,
   ``status == "saved"``, regime threshold keys, ``mode``/``auto_trade``/
   ``kill_switch``, ``live_connected``, health ``redis``) must be present.
3. Safety invariants — write handlers declare the ``CurrentUser`` auth
   dependency (``inspect.signature``), permission checks fire before any work,
   LIVE mode can never be switched on from the dashboard (PIN or not), enabling
   auto-trade / kill-switch requires the admin PIN, and numeric bounds are
   validated (schema type checks + direction checks + ``_BOUNDS`` clamping).
4. Persistence round-trip — ``shared.runtime_settings`` dict → store → dict with
   a mocked Redis store (extras preserved, out-of-range values clamped).
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from pydantic import ValidationError

from services.nexus_api.middleware import auth
from services.nexus_api.routers import (
    config,
    env,
    intelligence,
    positions,
    regime,
    risk,
    system,
)
from shared import runtime_settings
from shared.config_loader import RiskRulesSchema, SettingsSchema

ROOT = Path(__file__).resolve().parents[1]
PAGE_TSX = ROOT / "dashboard" / "src" / "app" / "nexus" / "settings" / "page.tsx"
API_CLIENT_TS = ROOT / "dashboard" / "src" / "lib" / "api-client.ts"
MAIN_PY = ROOT / "services" / "nexus_api" / "main.py"
ENV_ROUTER_PY = ROOT / "services" / "nexus_api" / "routers" / "env.py"

# The 12 deny-listed secret KEY NAMES (never their values).  Cross-checked
# against ``env.SECRET_KEYS`` below so the frontend sources can be scanned for
# leaks against the backend's own deny list.
SECRET_ENV_KEYS: tuple[str, ...] = (
    "NEXUS_PIN",
    "NEXUS_JWT_SECRET",
    "NEXUS_SECRET_KEY",
    "NEXUS_INTERNAL_API_SECRET",
    "NEXUS_ADMIN_PIN",
    "NEXUS_RISK_APPROVAL_SECRET",
    "MT5_PASSWORD",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "NEWSAPI_KEY",
    "GNEWS_KEY",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


ROUTER_MODULES = {
    "config": config,
    "env": env,
    "intelligence": intelligence,
    "risk": risk,
    "system": system,
    "regime": regime,
    "positions": positions,
}


def registered(module) -> set[tuple[str, str]]:
    """All (path, method) pairs the module actually registers on its APIRouter."""
    pairs: set[tuple[str, str]] = set()
    for route in module.router.routes:
        if isinstance(route, APIRoute):
            for method in route.methods or set():
                pairs.add((route.path, method))
    return pairs


def find_route(module, path: str, method: str) -> APIRoute:
    for route in module.router.routes:
        if isinstance(route, APIRoute) and route.path == path and method in (route.methods or set()):
            return route
    raise AssertionError(f"{method} {path} not registered on {module.__name__}")


def is_permission_dependency(dep) -> bool:
    """True when ``dep`` is ``Depends(require_permission(...))``.

    ``admin.require_permission`` returns a closure (``dependency``) that
    delegates to ``admin._require`` — that delegation, via the factory's
    ``__qualname__`` or the closure source, is what makes the dependency a
    *permission* gate.  Recognising the factory by name keeps the check from
    silently degrading into "any dependency at all will do".
    """
    if not _is_depends(dep):
        return False
    fn = dep.dependency
    if str(getattr(fn, "__qualname__", "")).endswith("require_permission.<locals>.dependency"):
        return True
    try:
        return "_require(db, actor, permission)" in inspect.getsource(fn)
    except (OSError, TypeError):
        return False


def is_registered(method: str, path: str) -> bool:
    if path == "/health":  # declared on the FastAPI app itself, not a router
        return '@app.get("/health"' in _read(MAIN_PY)
    return any((path, method) in registered(mod) for mod in ROUTER_MODULES.values())


# ── Expected route lists (derived from the two frontend sources) ──────────────

# page.tsx loadAll() — raw ``fetch(`${API}/…`)`` calls (lines 250-256).
PAGE_FETCH_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/intelligence/settings"),
    ("GET", "/api/regime/thresholds"),
    ("GET", "/api/risk/settings"),
]

# page.tsx loadAll() routes reached through api-client.ts helpers.
PAGE_VIA_CLIENT_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/positions"),   # apiClient.getPositionsSnapshot()
    ("GET", "/health"),          # apiClient.getHealth()
]

# api-client.ts settings/system methods used by the Settings page.
API_CLIENT_SETTINGS_ROUTES: list[tuple[str, str]] = [
    ("GET", "/api/config/settings"),
    ("PUT", "/api/config/settings"),
    ("PUT", "/api/config/risk"),
    ("POST", "/api/intelligence/settings"),
    ("GET", "/api/risk/status"),
    ("GET", "/api/system/mode"),
    ("POST", "/api/system/mode"),
    ("POST", "/api/system/toggle-auto-trade"),
    ("POST", "/api/system/kill-switch"),
    ("GET", "/api/system/env"),    # apiClient.getSystemEnv()
    ("POST", "/api/system/env"),   # apiClient.updateSystemEnv()
]

# Everything the General Settings tab ends up calling.
GENERAL_TAB_ROUTES = PAGE_FETCH_ROUTES + PAGE_VIA_CLIENT_ROUTES


# ── Test doubles ──────────────────────────────────────────────────────────────

class PermissiveDB:
    """Permission store that grants everything (``*``)."""

    async def query(self, operation: str, params: dict | None = None):
        if operation == "user_role_ids":
            return [{"role_id": 1}]
        if operation == "user_permissions":
            return [{"permission_code": "*"}]
        return []


class DenyDB:
    """Permission store that grants nothing."""

    async def query(self, operation: str, params: dict | None = None):
        if operation == "user_role_ids":
            return [{"role_id": 2}]
        return []


class FakeConfig:
    """ConfigLoader stand-in: in-memory snapshot + YAML-ish defaults."""

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        agents: dict[str, Any] | None = None,
        risk_rules: dict[str, Any] | None = None,
    ) -> None:
        self._cache: dict[str, Any] = {}
        if settings is not None:
            self._cache["settings"] = settings
        if agents is not None:
            self._cache["agents"] = agents
        if risk_rules is not None:
            self._cache["risk"] = risk_rules

    def get(self, section: str):
        return self._cache.get(section)

    def load_settings(self) -> dict[str, Any]:
        return SettingsSchema().model_dump()

    def load_agents(self) -> dict[str, Any]:
        return {"market_analyst": {"id": "market_analyst", "name": "Market Analyst"}}

    def load_risk_rules(self) -> dict[str, Any]:
        return RiskRulesSchema().model_dump()


class FakeSettingsStore:
    """JSON document store mimicking ``RedisClient.cache_get/cache_set`` plus the
    raw ``get``/``set`` used by the intelligence router, so a single object can
    back both writers and the shared reader.

    Deliberately has **no** ``.r`` attribute so ``runtime_settings`` degrades to
    its documented non-atomic fallback path instead of needing a real Redis.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    # Raw view (intelligence router): values are stored as JSON strings.
    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    # Cached view (shared.runtime_settings): values are parsed on read,
    # exactly like RedisClient.cache_get/cache_set do.
    async def cache_get(self, key: str, *, prefix: bool = True):
        raw = self.store.get(key)
        return json.loads(raw) if raw is not None else None

    async def cache_set(self, key: str, value: Any, ttl_sec: int | None = None, *, prefix: bool = True) -> None:
        self.store[key] = json.dumps(value, default=str)


class FakeSystemRedis:
    """Minimal RedisClient double for the system router."""

    def __init__(self) -> None:
        self.kv: dict[str, Any] = {}
        self.published: list[tuple[str, Any]] = []

    async def cache_get(self, key: str, *, prefix: bool = True):
        return self.kv.get(key)

    async def cache_set(self, key: str, value: Any, ttl_sec: int | None = None, *, prefix: bool = True) -> None:
        self.kv[key] = value

    async def publish_channel(self, channel: str, data: Any) -> None:
        self.published.append((channel, data))


class FakeRawRedis:
    """Raw ``get``/``set`` store for the intelligence + regime routers."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.kv: dict[str, str] = dict(initial or {})
        self.ttl: dict[str, int | None] = {}

    async def get(self, key: str):
        return self.kv.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.kv[key] = value
        self.ttl[key] = ex


# ── 1. Route contract ─────────────────────────────────────────────────────────

class TestRouteContract:
    def test_page_general_tab_sources_still_reference_expected_routes(self):
        page = _read(PAGE_TSX)
        for _, path in PAGE_FETCH_ROUTES:
            assert path in page, f"page.tsx no longer calls {path}; update this contract test"
        for _, path in PAGE_VIA_CLIENT_ROUTES:
            assert f"'{path}'" in _read(API_CLIENT_TS), f"api-client.ts no longer calls {path}"

    def test_api_client_sources_still_reference_expected_routes(self):
        client = _read(API_CLIENT_TS)
        for _, path in API_CLIENT_SETTINGS_ROUTES:
            assert f"'{path}'" in client, f"api-client.ts no longer calls {path}; update this contract test"

    @pytest.mark.parametrize(("method", "path"), GENERAL_TAB_ROUTES)
    def test_page_general_tab_routes_are_registered(self, method, path):
        assert is_registered(method, path), f"{method} {path} called by the General tab is not served"

    @pytest.mark.parametrize(("method", "path"), API_CLIENT_SETTINGS_ROUTES)
    def test_api_client_settings_routes_are_registered(self, method, path):
        assert is_registered(method, path), f"{method} {path} used by api-client.ts is not served"

    def test_intelligence_settings_supports_both_read_and_write(self):
        reg = registered(intelligence)
        assert ("/api/intelligence/settings", "GET") in reg
        assert ("/api/intelligence/settings", "POST") in reg

    def test_config_settings_supports_both_read_and_write(self):
        reg = registered(config)
        assert ("/api/config/settings", "GET") in reg
        assert ("/api/config/settings", "PUT") in reg
        assert ("/api/config/risk", "PUT") in reg

    def test_positions_snapshot_route_uses_app_root_path(self):
        # api-client fetches '/api/positions' (no trailing slash).
        assert ("/api/positions", "GET") in registered(positions)

    def test_read_routes_carry_a_permission_dependency(self):
        # These handlers enforce permission at route level (``dependencies=[...]``),
        # so it is invisible in their own signature — assert on the route object.
        # Each route must carry a dependency built by ``require_permission(...)``,
        # not merely *some* dependency (recognition via is_permission_dependency).
        for module, path in (
            (intelligence, "/api/intelligence/settings"),
            (system, "/api/system/mode"),
            (env, "/api/system/env"),
        ):
            route = find_route(module, path, "GET")
            assert route.dependencies, f"GET {path} lost its route-level dependency"
            assert any(is_permission_dependency(d) for d in route.dependencies), (
                f"GET {path} must depend on require_permission(...) — a plain "
                "dependency is not a permission gate"
            )


# ── 2. Response shape ─────────────────────────────────────────────────────────

class TestResponseShape:
    # ── GET /api/intelligence/settings ── page.tsx reads ``d.settings`` / ``d.error``
    @pytest.mark.asyncio
    async def test_intelligence_settings_returns_the_envelope_the_page_reads(self, monkeypatch):
        document = {"risk_per_trade_pct": 1.5, "max_daily_trades": 3, "notif_enable_browser": True}

        async def fake_redis_get(key: str):
            assert key == "nexus:runtime:settings"
            return json.dumps(document)

        monkeypatch.setattr(intelligence, "_redis_get", fake_redis_get)
        payload = await intelligence.get_dynamic_settings()

        assert payload["settings"] == document
        assert payload["source"] == "redis"
        assert "error" not in payload, "an error marker would make page.tsx freeze stale values"

    @pytest.mark.asyncio
    async def test_intelligence_settings_empty_store_is_defaults_not_error(self, monkeypatch):
        async def fake_redis_get(key: str):
            return None

        monkeypatch.setattr(intelligence, "_redis_get", fake_redis_get)
        payload = await intelligence.get_dynamic_settings()

        assert payload["settings"] == {}
        assert payload["source"] == "defaults"
        assert "error" not in payload

    # ── POST /api/intelligence/settings ── page.tsx save() requires status == 'saved'
    @pytest.mark.asyncio
    async def test_intelligence_settings_write_reports_saved_and_merges(self, monkeypatch):
        store = FakeRawRedis({"nexus:runtime:settings": json.dumps({"max_daily_trades": 5, "keep_me": 1})})
        monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))

        req = intelligence.DynamicSettingsUpdate(settings={"max_daily_trades": 9, "extra_key": True})
        payload = await intelligence.update_dynamic_settings(req, actor="tester", db=PermissiveDB())

        assert payload["status"] == "saved"
        assert payload["settings"] == {"max_daily_trades": 9, "keep_me": 1, "extra_key": True}

    @pytest.mark.asyncio
    async def test_intelligence_settings_write_treats_null_as_delete(self, monkeypatch):
        store = FakeRawRedis({"nexus:runtime:settings": json.dumps({"stale_override": 4})})
        monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))

        req = intelligence.DynamicSettingsUpdate(settings={"stale_override": None})
        payload = await intelligence.update_dynamic_settings(req, actor="tester", db=PermissiveDB())

        assert payload["status"] == "saved"
        assert "stale_override" not in payload["settings"]
        assert "stale_override" not in json.loads(store.kv["nexus:runtime:settings"])

    # ── GET /api/risk/settings ── page.tsx reads ``session_gate`` / ``settings``
    @pytest.mark.asyncio
    async def test_risk_settings_passthrough_keeps_session_gate_shape(self, monkeypatch):
        async def fake_proxy(method: str, path: str, body: Any = None):
            assert (method, path) == ("GET", "/api/risk/settings")
            return {
                "settings": {"risk_per_trade_pct": 1.0},
                "session_gate": {"off_hours_allowed": True, "allowed_sessions": ["london", "new_york"]},
                "daily_trade_count": 2,
            }

        monkeypatch.setattr(risk, "_risk_proxy", fake_proxy)
        payload = await risk.get_risk_settings(actor="tester", db=PermissiveDB())

        gate = payload["session_gate"]
        assert isinstance(gate["off_hours_allowed"], bool)
        assert isinstance(gate["allowed_sessions"], list)
        assert all(isinstance(s, str) for s in gate["allowed_sessions"])
        assert payload["settings"] == {"risk_per_trade_pct": 1.0}

    @pytest.mark.asyncio
    async def test_risk_settings_does_not_fabricate_a_session_gate(self, monkeypatch):
        calls: list[Any] = []

        async def fake_proxy(method: str, path: str, body: Any = None):
            calls.append(path)
            return {"settings": {}}

        monkeypatch.setattr(risk, "_risk_proxy", fake_proxy)
        payload = await risk.get_risk_settings(actor="tester", db=PermissiveDB())

        # page.tsx must be able to tell "gate unknown" from "gate off".
        assert "session_gate" not in payload
        assert calls == ["/api/risk/settings"]

    # ── GET /api/regime/thresholds ── page.tsx dynamic-thresholds panel
    @pytest.mark.asyncio
    async def test_regime_thresholds_echo_the_keys_the_page_reads(self, monkeypatch):
        thresholds = {
            "quality_score_threshold": 62,
            "conviction_min": 0.55,
            "overall_wr": 0.47,
            "total_trades": 138,
            "bad_hours": ["02:00"],
            "good_hours": ["09:00"],
            "regime_min_wr": {"trend": 0.52},
        }
        store = FakeRawRedis({"nexus:trade_memory:thresholds": json.dumps(thresholds)})
        monkeypatch.setattr(regime, "_get_redis", lambda: _async_value(store))

        payload = await regime.get_dynamic_thresholds()

        for key in thresholds:
            assert payload[key] == thresholds[key], f"regime/thresholds dropped {key}"

    @pytest.mark.asyncio
    async def test_regime_thresholds_empty_store_still_has_total_trades(self, monkeypatch):
        store = FakeRawRedis({})
        monkeypatch.setattr(regime, "_get_redis", lambda: _async_value(store))

        payload = await regime.get_dynamic_thresholds()

        assert payload["total_trades"] == 0
        assert "error" in payload  # honest "nothing computed" marker for the UI

    # ── GET /api/config/settings + /agents ── settings / agents nesting
    @pytest.mark.asyncio
    async def test_config_settings_exposes_every_schema_field(self):
        cfg = FakeConfig()
        payload = await config.get_settings(actor="tester", cfg=cfg, db=PermissiveDB())

        missing = set(SettingsSchema.model_fields) - set(payload)
        assert not missing, f"GET /api/config/settings dropped schema fields: {sorted(missing)}"
        assert payload["trading_mode"] == "paper"
        assert payload["auto_trade_enabled"] is False

    @pytest.mark.asyncio
    async def test_config_agents_returns_an_agent_id_mapping(self):
        cfg = FakeConfig(agents={"market_analyst": {"id": "market_analyst", "enabled": True}})
        payload = await config.get_agent_configs(actor="tester", cfg=cfg, db=PermissiveDB())

        assert "market_analyst" in payload
        assert payload["market_analyst"]["enabled"] is True

    # ── GET /api/config/risk ── must be marked as runtime-authoritative
    @pytest.mark.asyncio
    async def test_config_risk_read_is_marked_runtime_effective(self, monkeypatch):
        async def fake_proxy(method: str, path: str, body: Any = None):
            return {"settings": {"max_daily_trades": 5}, "session_gate": {"off_hours_allowed": False, "allowed_sessions": []}}

        monkeypatch.setattr(risk, "_risk_proxy", fake_proxy)
        payload = await config.get_risk_rules(actor="tester", db=PermissiveDB())

        assert payload["persistence"] == "runtime"
        assert payload["runtime_effective"] is True
        assert payload["source"] == "nexus-risk:runtime"
        assert payload["session_gate"]["off_hours_allowed"] is False  # passthrough, not re-invented

    # ── GET/POST /api/system/mode ── api-client.ts response type
    @pytest.mark.asyncio
    async def test_system_mode_shape_matches_the_api_client_type(self):
        payload = await system.get_mode(redis=FakeSystemRedis())

        assert set(payload) == {"mode", "auto_trade", "kill_switch"}
        assert payload["mode"] in ("paper", "live")
        assert payload["auto_trade"] is False
        assert payload["kill_switch"] is False

    # ── GET /api/positions ── page.tsx reads ``data.live_connected``
    def test_positions_snapshot_model_declares_live_connected(self):
        field = positions.PositionList.model_fields.get("live_connected")
        assert field is not None, "page.tsx reads live_connected from GET /api/positions"
        assert field.default is False

    # ── GET /health ── page.tsx looks for a component named 'redis'
    def test_health_endpoint_declares_the_redis_component(self):
        source = _read(MAIN_PY)
        assert '@app.get("/health"' in source
        match = re.search(r"def _health_payload\(.*?(?=\ndef |\Z)", source, flags=re.S)
        assert match, "_health_payload not found in main.py"
        assert '"redis"' in match.group(0)
        # api-client.ts maps raw.redis → component named 'redis'
        assert "raw.redis" in _read(API_CLIENT_TS)

    # ── Save status contract: page.tsx only trusts status === 'saved' ──
    def test_page_save_only_accepts_saved_status(self):
        page = _read(PAGE_TSX)
        assert "res.data?.status === 'saved'" in page, (
            "page.tsx must keep treating anything but status 'saved' as a failed save"
        )


# ── The ``defaults`` sibling of ``settings`` (page.tsx fallback display map) ──

@pytest.mark.asyncio
async def test_intelligence_settings_ships_defaults_next_to_the_raw_document(monkeypatch):
    """``GET /api/intelligence/settings`` → raw ``settings`` + full ``defaults``.

    page.tsx renders ``runtime[f.key] !== undefined ? runtime[f.key] :
    runtimeDefaults[f.key]`` — without the ``defaults`` sibling every knob the
    user never saved renders empty (the "35 empty fields" regression).
    """
    document = {"risk_per_trade_pct": 1.5, "max_daily_trades": 3}
    unset_key = "trade_memory_window"

    async def fake_redis_get(key: str):
        assert key == "nexus:runtime:settings"
        return json.dumps(document)

    monkeypatch.setattr(intelligence, "_redis_get", fake_redis_get)
    payload = await intelligence.get_dynamic_settings()

    # ``settings`` stays the RAW stored document (pinned page contract) …
    assert payload["settings"] == document
    assert unset_key not in payload["settings"]
    assert payload["source"] == "redis"

    # … and the sibling ``defaults`` map fills in what was never saved.
    defaults = payload["defaults"]
    assert isinstance(defaults, dict)
    assert len(defaults) >= 44, f"payload['defaults'] carries only {len(defaults)} keys"
    assert unset_key in defaults, "an unset knob must still be renderable from defaults"
    assert defaults == runtime_settings.DEFAULTS


@pytest.mark.asyncio
async def test_intelligence_settings_defaults_survive_an_empty_store(monkeypatch):
    async def fake_redis_get(key: str):
        return None

    monkeypatch.setattr(intelligence, "_redis_get", fake_redis_get)
    payload = await intelligence.get_dynamic_settings()

    assert payload["settings"] == {}
    defaults = payload.get("defaults")
    assert isinstance(defaults, dict) and len(defaults) >= 44


# ── 3. Safety invariants ──────────────────────────────────────────────────────

def declares_current_user(fn) -> bool:
    """True when the handler takes the ``actor: CurrentUser`` auth dependency."""
    for param in inspect.signature(fn).parameters.values():
        if param.name == "actor" and "CurrentUser" in str(param.annotation):
            return True
    return False


AUTH_SENSITIVE_HANDLERS = [
    pytest.param(config.get_settings, id="GET /api/config/settings"),
    pytest.param(config.update_settings, id="PUT /api/config/settings"),
    pytest.param(config.get_agent_configs, id="GET /api/config/agents"),
    pytest.param(config.update_agent_config, id="PUT /api/config/agents/{agent_id}"),
    pytest.param(config.get_risk_rules, id="GET /api/config/risk"),
    pytest.param(config.update_risk_rules, id="PUT /api/config/risk"),
    pytest.param(risk.get_risk_settings, id="GET /api/risk/settings"),
    pytest.param(risk.update_risk_settings, id="POST /api/risk/settings"),
    pytest.param(intelligence.update_dynamic_settings, id="POST /api/intelligence/settings"),
    pytest.param(env.update_env_setting, id="POST /api/system/env"),
    pytest.param(system.switch_mode, id="POST /api/system/mode"),
    pytest.param(system.toggle_auto_trade, id="POST /api/system/toggle-auto-trade"),
    pytest.param(system.kill_switch, id="POST /api/system/kill-switch"),
]


def _is_depends(marker) -> bool:
    """FastAPI ≥0.118 exposes ``Depends`` as a factory function, not a class."""
    return callable(getattr(marker, "dependency", None)) and hasattr(marker, "use_cache")


class TestAuthInvariants:
    @pytest.mark.parametrize("handler", AUTH_SENSITIVE_HANDLERS)
    def test_settings_handlers_declare_the_auth_dependency(self, handler):
        assert declares_current_user(handler), (
            f"{handler.__module__}.{handler.__name__} must take `actor: CurrentUser` "
            "(Annotated[str, Depends(get_current_user)]) so unauthenticated callers get 401"
        )

    def test_current_user_is_wired_to_get_current_user(self):
        deps = [a for a in get_args(auth.CurrentUser)[1:] if _is_depends(a)]
        assert deps, "CurrentUser must carry a Depends(...)"
        assert any(d.dependency is auth.get_current_user for d in deps)

    @pytest.mark.asyncio
    async def test_get_current_user_rejects_missing_and_malformed_headers(self):
        with pytest.raises(HTTPException) as excinfo:
            await auth.get_current_user(None)
        assert excinfo.value.status_code == 401

        with pytest.raises(HTTPException) as excinfo:
            await auth.get_current_user("Basic dXNlcjpwYXNz")
        assert excinfo.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_rejects_an_unsigned_token(self, monkeypatch):
        monkeypatch.setenv("NEXUS_JWT_SECRET", "contract-test-secret-please-be-32-bytes-long")
        with pytest.raises(HTTPException) as excinfo:
            await auth.get_current_user("Bearer not-a-jwt")
        assert excinfo.value.status_code == 401

    @pytest.mark.asyncio
    async def test_intelligence_settings_read_enforces_permission(self, monkeypatch):
        async def fake_redis_get(key: str):
            return "{}"

        monkeypatch.setattr(intelligence, "_redis_get", fake_redis_get)
        with pytest.raises(HTTPException) as excinfo:
            await intelligence._trading_settings(actor="tester", db=DenyDB())
        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_settings_write_rejects_unauthorized_actor_before_persisting(self):
        cfg = FakeConfig(settings=SettingsSchema().model_dump())
        body = config.UpdateSettingsRequest(settings={"trading_mode": "live"})

        with pytest.raises(HTTPException) as excinfo:
            await config.update_settings(body, actor="tester", cfg=cfg, db=DenyDB())
        assert excinfo.value.status_code == 403
        assert cfg.get("settings") == SettingsSchema().model_dump(), "snapshot must stay untouched"

    @pytest.mark.asyncio
    async def test_intelligence_settings_write_rejects_unauthorized_actor(self, monkeypatch):
        store = FakeRawRedis({"nexus:runtime:settings": json.dumps({"max_daily_trades": 5})})
        monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))

        req = intelligence.DynamicSettingsUpdate(settings={"max_daily_trades": 9})
        with pytest.raises(HTTPException) as excinfo:
            await intelligence.update_dynamic_settings(req, actor="tester", db=DenyDB())
        assert excinfo.value.status_code == 403
        assert json.loads(store.kv["nexus:runtime:settings"]) == {"max_daily_trades": 5}

    @pytest.mark.asyncio
    async def test_risk_settings_read_fails_closed_before_proxying(self, monkeypatch):
        calls: list[str] = []

        async def fake_proxy(method: str, path: str, body: Any = None):
            calls.append(path)
            return {}

        monkeypatch.setattr(risk, "_risk_proxy", fake_proxy)
        with pytest.raises(HTTPException) as excinfo:
            await risk.get_risk_settings(actor="tester", db=DenyDB())
        assert excinfo.value.status_code == 403
        assert calls == [], "an unauthorized caller must never reach nexus-risk"


class TestDangerousOperationInvariants:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("pin", [None, "0000", "123456"])
    async def test_live_mode_cannot_be_enabled_from_the_dashboard(self, pin):
        """LIVE is process-level: the dashboard must get 409 no matter the PIN."""
        body = system.SwitchModeRequest(mode="live", pin=pin)
        with pytest.raises(HTTPException) as excinfo:
            await system.switch_mode(body, actor="tester", redis=FakeSystemRedis())
        assert excinfo.value.status_code == 409
        assert "live" in str(excinfo.value.detail).lower()

    @pytest.mark.asyncio
    async def test_paper_switch_while_live_process_is_refused(self, monkeypatch):
        monkeypatch.setenv("NEXUS_TRADING_MODE", "live")
        body = system.SwitchModeRequest(mode="paper")
        with pytest.raises(HTTPException) as excinfo:
            await system.switch_mode(body, actor="tester", redis=FakeSystemRedis())
        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_enabling_auto_trade_without_pin_is_rejected(self):
        body = system.ToggleAutoTradeRequest(enabled=True, pin=None)
        with pytest.raises(HTTPException) as excinfo:
            await system.toggle_auto_trade(
                body, actor="tester", redis=FakeSystemRedis(), db=PermissiveDB()
            )
        assert excinfo.value.status_code == 422
        assert "pin" in str(excinfo.value.detail).lower()

    @pytest.mark.asyncio
    async def test_enabling_auto_trade_with_wrong_pin_is_rejected(self, monkeypatch):
        monkeypatch.setenv("NEXUS_ADMIN_PIN", "424242")
        body = system.ToggleAutoTradeRequest(enabled=True, pin="000000")
        with pytest.raises(HTTPException) as excinfo:
            await system.toggle_auto_trade(
                body, actor="tester", redis=FakeSystemRedis(), db=PermissiveDB()
            )
        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_enabling_auto_trade_with_valid_pin_persists(self, monkeypatch):
        monkeypatch.setenv("NEXUS_ADMIN_PIN", "424242")
        redis = FakeSystemRedis()
        body = system.ToggleAutoTradeRequest(enabled=True, pin="424242")

        payload = await system.toggle_auto_trade(
            body, actor="tester", redis=redis, db=PermissiveDB()
        )

        assert payload["auto_trade"] is True
        assert redis.kv["system:auto_trade"] is True

    @pytest.mark.asyncio
    async def test_disabling_auto_trade_needs_no_pin(self):
        redis = FakeSystemRedis()
        body = system.ToggleAutoTradeRequest(enabled=False, pin=None)
        payload = await system.toggle_auto_trade(
            body, actor="tester", redis=redis, db=PermissiveDB()
        )
        assert payload["auto_trade"] is False
        assert redis.kv["system:auto_trade"] is False

    @pytest.mark.asyncio
    async def test_kill_switch_rejects_a_wrong_pin_and_never_latches(self, monkeypatch):
        monkeypatch.setenv("NEXUS_ADMIN_PIN", "424242")
        redis = FakeSystemRedis()
        body = system.KillSwitchRequest(pin="000000", reason="test")

        with pytest.raises(HTTPException) as excinfo:
            await system.kill_switch(body, actor="tester", redis=redis)

        assert excinfo.value.status_code == 403
        assert "system:kill_switch" not in redis.kv
        assert redis.published == []

    @pytest.mark.asyncio
    async def test_kill_switch_with_valid_pin_latches_and_publishes(self, monkeypatch):
        monkeypatch.setenv("NEXUS_ADMIN_PIN", "424242")
        redis = FakeSystemRedis()
        body = system.KillSwitchRequest(pin="424242", reason="drill")

        payload = await system.kill_switch(body, actor="tester", redis=redis)

        assert payload["status"] == "kill_switch_activated"
        assert redis.kv["system:kill_switch"] is True
        assert redis.kv["system:auto_trade"] is False
        assert [c for c, _ in redis.published] == ["system:commands"]

    def test_verify_pin_has_no_insecure_fallback(self, monkeypatch):
        monkeypatch.delenv("NEXUS_ADMIN_PIN", raising=False)
        with pytest.raises(HTTPException) as excinfo:
            auth.verify_pin("")
        assert excinfo.value.status_code == 503  # unset PIN ⇒ refuse, never accept

        monkeypatch.setenv("NEXUS_ADMIN_PIN", "424242")
        with pytest.raises(HTTPException) as excinfo:
            auth.verify_pin("wrong")
        assert excinfo.value.status_code == 403
        assert auth.verify_pin("424242") is None

    def test_system_dangerous_ops_call_verify_pin(self):
        source = inspect.getsource(system)
        assert source.count("verify_pin(") >= 2, (
            "kill-switch and auto-trade enable must both verify the admin PIN"
        )


# ── Numeric bounds validation ─────────────────────────────────────────────────

class TestNumericBounds:
    @pytest.mark.asyncio
    async def test_config_put_settings_rejects_unknown_runtime_knobs(self):
        """Runtime trading knobs belong to POST /api/intelligence/settings."""
        cfg = FakeConfig(settings=SettingsSchema().model_dump())
        body = config.UpdateSettingsRequest(settings={"trading_mode_type": "scalping"})

        with pytest.raises(HTTPException) as excinfo:
            await config.update_settings(body, actor="tester", cfg=cfg, db=PermissiveDB())
        assert excinfo.value.status_code == 422
        assert cfg.get("settings") == SettingsSchema().model_dump(), "failed update must not corrupt the snapshot"

    @pytest.mark.asyncio
    async def test_config_put_settings_rejects_non_numeric_values(self):
        cfg = FakeConfig(settings=SettingsSchema().model_dump())
        body = config.UpdateSettingsRequest(settings={"heartbeat_interval": "not-a-number"})

        with pytest.raises(HTTPException) as excinfo:
            await config.update_settings(body, actor="tester", cfg=cfg, db=PermissiveDB())
        assert excinfo.value.status_code == 422

    @pytest.mark.asyncio
    async def test_config_put_settings_accepts_a_valid_patch_and_marks_it_display_only(self):
        cfg = FakeConfig(settings=SettingsSchema().model_dump())
        body = config.UpdateSettingsRequest(settings={"heartbeat_interval": 15})

        payload = await config.update_settings(body, actor="tester", cfg=cfg, db=PermissiveDB())

        assert payload["heartbeat_interval"] == 15
        assert payload["persistence"] == "display_only"
        assert payload["runtime_effective"] is False
        assert cfg.get("settings")["heartbeat_interval"] == 15

    @pytest.mark.asyncio
    async def test_config_put_risk_rejects_hardcoded_safety_fields(self):
        """Hardcoded safety limits must never be writable through the API."""
        cfg = FakeConfig(risk_rules=RiskRulesSchema().model_dump())
        body = config.UpdateRiskRulesRequest(rules={"max_daily_loss_pct": 50.0})

        with pytest.raises(HTTPException) as excinfo:
            await config.update_risk_rules(body, actor="tester", cfg=cfg, db=PermissiveDB())
        assert excinfo.value.status_code in (403, 422)
        assert cfg.get("risk")["max_daily_loss_pct"] == RiskRulesSchema().max_daily_loss_pct

    @pytest.mark.asyncio
    async def test_config_put_risk_reports_hardcoded_fields_as_forbidden(self):
        # Regression guard: HARDCODED_RISK_FIELDS must be reported as 403
        # (not masked by the 422 unknown-fields check) — config.py checks
        # the forbidden set first.
        cfg = FakeConfig(risk_rules=RiskRulesSchema().model_dump())
        body = config.UpdateRiskRulesRequest(rules={"max_daily_loss_pct": 50.0})

        with pytest.raises(HTTPException) as excinfo:
            await config.update_risk_rules(body, actor="tester", cfg=cfg, db=PermissiveDB())
        assert excinfo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_config_put_risk_rejects_a_loosening_update(self):
        cfg = FakeConfig(risk_rules=RiskRulesSchema().model_dump())  # max_risk_per_trade_pct = 2.0
        body = config.UpdateRiskRulesRequest(rules={"max_risk_per_trade_pct": 9.0})

        with pytest.raises(HTTPException) as excinfo:
            await config.update_risk_rules(body, actor="tester", cfg=cfg, db=PermissiveDB())
        assert excinfo.value.status_code == 422

    @pytest.mark.asyncio
    async def test_config_put_risk_rejects_unknown_and_empty_updates(self):
        cfg = FakeConfig(risk_rules=RiskRulesSchema().model_dump())

        with pytest.raises(HTTPException) as unknown:
            await config.update_risk_rules(
                config.UpdateRiskRulesRequest(rules={"bogus_field": 1}),
                actor="tester", cfg=cfg, db=PermissiveDB(),
            )
        assert unknown.value.status_code == 422

        with pytest.raises(HTTPException) as empty:
            await config.update_risk_rules(
                config.UpdateRiskRulesRequest(rules={}), actor="tester", cfg=cfg, db=PermissiveDB()
            )
        assert empty.value.status_code == 422

    @pytest.mark.asyncio
    async def test_config_put_risk_accepts_a_tightening_update(self):
        cfg = FakeConfig(risk_rules=RiskRulesSchema().model_dump())  # daily_trade_limit = 10
        body = config.UpdateRiskRulesRequest(rules={"daily_trade_limit": 4})

        payload = await config.update_risk_rules(body, actor="tester", cfg=cfg, db=PermissiveDB())

        assert payload["daily_trade_limit"] == 4
        assert payload["persistence"] == "display_only"

    def test_runtime_settings_clamp_out_of_range_values(self):
        merged = runtime_settings.merge_with_defaults(
            {
                "risk_per_trade_pct": 99,
                "max_daily_loss_pct": 0.01,
                "max_daily_trades": 10_000,
                "max_open_positions": -5,
                "min_mtf_agreement": 7,
                "research_interval_sec": 999_999,
                "unknown_key": "must be dropped",
            }
        )

        assert merged["risk_per_trade_pct"] == 5.0
        assert merged["max_daily_loss_pct"] == 1.0
        assert merged["max_daily_trades"] == 100
        assert merged["max_open_positions"] == 1
        assert merged["min_mtf_agreement"] == 3
        assert merged["research_interval_sec"] == 7200
        assert "unknown_key" not in merged

    def test_runtime_settings_fall_back_to_defaults_on_garbage_input(self):
        merged = runtime_settings.merge_with_defaults(
            {"risk_per_trade_pct": "not-a-number", "max_daily_trades": None, "require_mtf_confirmation": "yes"}
        )

        assert merged["risk_per_trade_pct"] == runtime_settings.DEFAULTS["risk_per_trade_pct"]
        assert merged["max_daily_trades"] == runtime_settings.DEFAULTS["max_daily_trades"]
        assert merged["require_mtf_confirmation"] is True

    def test_settings_schema_rejects_non_numeric_input(self):
        with pytest.raises(ValidationError):
            SettingsSchema(heartbeat_interval="abc")
        with pytest.raises(ValidationError):
            SettingsSchema(auto_trade_enabled="banana")


def test_sanitize_patch_drops_uninterpretable_values_instead_of_resetting():
    """A malformed write must not erase a valid saved override.

    ``sanitize_patch`` runs on POST /api/intelligence/settings: coercing
    garbage to the default would silently rewrite the user's policy, and
    bool-coercing an unknown string would switch a safety toggle off.
    """
    patch = runtime_settings.sanitize_patch(
        {
            "risk_per_trade_pct": "not-a-number",   # unparsable number
            "max_daily_trades": "",                 # empty numeric field
            "require_mtf_confirmation": "banana",   # unknown bool token
            "research_interval_sec": {"nested": 1}, # wrong type
            "min_mtf_agreement": 999,               # parsable, out of range
            "min_conviction_override": "0.85",      # parsable special key
        }
    )

    assert "risk_per_trade_pct" not in patch
    assert "max_daily_trades" not in patch
    assert "require_mtf_confirmation" not in patch
    assert "research_interval_sec" not in patch
    assert patch["min_mtf_agreement"] == 3                 # clamped, kept
    assert patch["min_conviction_override"] == pytest.approx(0.85)


def test_sanitize_patch_keeps_reset_and_extras_semantics():
    """``None`` still resets to default; extras still pass through untouched."""
    patch = runtime_settings.sanitize_patch(
        {"min_conviction_override": None, "custom_flag": 7, "llm_provider": "openai"}
    )

    assert patch["min_conviction_override"] is None
    assert patch["custom_flag"] == 7
    assert patch["llm_provider"] == "local"


def test_sanitize_patch_clamps_and_drops_the_settings_tab_new_keys():
    """New DEFAULTS keys must obey the same clamp / drop rules as the old ones.

    Out-of-range numerics are clamped (never stored as policy), unparsable
    numerics and non-string values for whitelisted selects are DROPPED so a
    malformed write cannot overwrite a valid saved override.
    """
    patch = runtime_settings.sanitize_patch(
        {
            "trade_memory_window": 99999,       # numeric, way above _BOUNDS hi
            "min_rr_ratio": 99,                 # float, way above _BOUNDS hi
            "dl_seq_len": "abc",                # unparsable number
            "backtest_default_symbol": 123,     # whitelisted select, not a string
        }
    )

    assert patch["trade_memory_window"] == 500            # clamped to _BOUNDS hi
    assert patch["min_rr_ratio"] == pytest.approx(5.0)    # clamped to _BOUNDS hi
    assert "dl_seq_len" not in patch, "garbage number must be dropped, not stored"
    assert "backtest_default_symbol" not in patch, (
        "a non-string select value must be dropped (never persisted as policy)"
    )

    # A legal select value still round-trips in its canonical spelling.
    assert runtime_settings.sanitize_patch({"backtest_default_symbol": "eurusd"})[
        "backtest_default_symbol"
    ] == "EURUSD"


# ── Session gate (بوابة الجلسات) ───────────────────────────────────────────


def test_session_gate_keys_are_part_of_the_runtime_contract():
    """The gate must be front-configurable: both keys live in DEFAULTS."""
    assert isinstance(runtime_settings.DEFAULTS["off_hours_allowed"], bool)
    assert isinstance(runtime_settings.DEFAULTS["allowed_sessions"], list)

    merged = runtime_settings.merge_with_defaults({"allowed_sessions": ["london"]})
    assert merged["allowed_sessions"] == ["LONDON"]
    assert isinstance(merged["off_hours_allowed"], bool)


def test_sanitize_patch_normalizes_session_names_and_drops_unknowns():
    patch = runtime_settings.sanitize_patch(
        {"allowed_sessions": ["london", "NEW_YORK", "not_a_session", "london", " overlap "]},
    )
    # canonical names, canonical order (TradingSession declaration order), no dupes
    assert patch["allowed_sessions"] == ["LONDON", "NEW_YORK", "OVERLAP"]


def test_sanitize_patch_session_list_handles_bad_input():
    # Unusable values are DROPPED so a malformed write never wipes the stored set…
    assert "allowed_sessions" not in runtime_settings.sanitize_patch({"allowed_sessions": 42})
    assert "allowed_sessions" not in runtime_settings.sanitize_patch({"allowed_sessions": ""})
    assert "allowed_sessions" not in runtime_settings.sanitize_patch(
        {"allowed_sessions": {"LONDON": True}}
    )
    # …but an explicitly empty list is a real choice (kill switch) and is kept.
    assert runtime_settings.sanitize_patch({"allowed_sessions": []})["allowed_sessions"] == []
    # A comma-separated string is accepted as input.
    assert runtime_settings.sanitize_patch({"allowed_sessions": "tokyo,london"})[
        "allowed_sessions"
    ] == ["TOKYO", "LONDON"]


def test_session_gate_policy_prefers_the_stored_override():
    doc = {"off_hours_allowed": True, "allowed_sessions": ["sydney", "NEW_YORK"]}
    off_ok, allowed = runtime_settings.session_gate_policy(
        doc, default_off_hours=False, default_sessions=["LONDON"],
    )
    assert off_ok is True
    assert allowed == {"SYDNEY", "NEW_YORK"}  # normalized, not raw


def test_session_gate_policy_falls_back_to_the_deployment_default():
    # A document without the gate keys ⇒ env-seeded defaults supplied by caller.
    off_ok, allowed = runtime_settings.session_gate_policy(
        {"risk_per_trade_pct": 1.0},
        default_off_hours=False,
        default_sessions=["LONDON", "NEW_YORK"],
    )
    assert off_ok is False
    assert allowed == {"LONDON", "NEW_YORK"}

    # Store reachable but never written ⇒ same contract, no exception.
    off_ok, allowed = runtime_settings.session_gate_policy(
        {}, default_off_hours=True, default_sessions=["LONDON"],
    )
    assert off_ok is True
    assert allowed == {"LONDON"}


def test_session_gate_policy_defaults_to_the_refreshed_process_cache(monkeypatch):
    """No explicit document ⇒ the sync path reads the cache every async read fills."""
    monkeypatch.setattr(
        runtime_settings, "_cache", {"off_hours_allowed": True, "allowed_sessions": ["TOKYO"]}
    )
    off_ok, allowed = runtime_settings.session_gate_policy(
        default_off_hours=False, default_sessions=["LONDON"],
    )
    assert off_ok is True
    assert allowed == {"TOKYO"}


def test_session_gate_policy_stored_garbage_never_opens_the_gate():
    """Uninterpretable stored values fall back to defaults — never coerce to ON."""
    off_ok, allowed = runtime_settings.session_gate_policy(
        {"off_hours_allowed": "banana", "allowed_sessions": 42},
        default_off_hours=False,
        default_sessions=["LONDON"],
    )
    assert off_ok is False
    assert allowed == {"LONDON"}


def test_session_gate_policy_off_hours_in_allowed_set_is_equivalent_to_on():
    """Historical rule: ALLOW_OFF_HOURS or 'OFF_HOURS' in ALLOWED_SESSIONS."""
    off_ok, allowed = runtime_settings.session_gate_policy(
        {"off_hours_allowed": False, "allowed_sessions": ["OFF_HOURS"]},
        default_off_hours=False,
        default_sessions=["LONDON"],
    )
    assert off_ok is True
    assert allowed == {"OFF_HOURS"}


def test_session_gate_policy_empty_allowed_set_is_a_kill_switch():
    off_ok, allowed = runtime_settings.session_gate_policy(
        {"off_hours_allowed": False, "allowed_sessions": []},
        default_off_hours=False,
        default_sessions=["LONDON"],
    )
    assert off_ok is False
    assert allowed == set()


def test_page_offers_the_session_gate_as_editable_controls():
    """The Settings tab must expose the gate (not a read-only status line)."""
    page = _read(PAGE_TSX)
    assert "SESSION_CHOICES" in page
    assert "setRuntimeField('off_hours_allowed'" in page
    assert "setRuntimeField('allowed_sessions'" in page
    assert "تعديلها يتطلب تغيير إعدادات الخادم" not in page


def frontend_number_bounds() -> dict[str, tuple[float, float]]:
    """Parse ``{ key: '...', type: 'number', min: X, max: Y }`` from page.tsx."""
    source = _read(PAGE_TSX)
    out: dict[str, tuple[float, float]] = {}
    for match in re.finditer(r"key: '(?P<key>[A-Za-z0-9_]+)',(?P<body>[^{}]*)", source):
        body = match.group("body")
        if "type: 'number'" not in body:
            continue
        bounds = re.search(r"min: (-?\d+(?:\.\d+)?),\s*max: (-?\d+(?:\.\d+)?)", body)
        if bounds:
            out[match.group("key")] = (float(bounds.group(1)), float(bounds.group(2)))
    return out


def test_frontend_numeric_fields_are_parsed_from_page_tsx():
    """Guard: the contract test below must not pass because parsing silently broke."""
    parsed = frontend_number_bounds()
    assert {"max_daily_trades", "min_mtf_agreement", "research_interval_sec"} <= set(parsed)
    assert any(key.startswith("risk_per_trade") for key in parsed), "risk budget field disappeared"
    assert len(parsed) >= 20
    assert all(lo < hi for lo, hi in parsed.values())


def test_frontend_declared_bounds_stay_inside_backend_clamps():
    """The UI must never offer a value the backend will silently clamp away."""
    frontend = frontend_number_bounds()
    shared_keys = sorted(set(frontend) & set(runtime_settings._BOUNDS))
    assert {"max_daily_trades", "min_mtf_agreement", "research_interval_sec"} <= set(shared_keys)

    mismatches: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}
    for key in shared_keys:
        fe_lo, fe_hi = frontend[key]
        be_lo, be_hi = runtime_settings._BOUNDS[key]
        if fe_lo < be_lo or fe_hi > be_hi:
            mismatches[key] = ((fe_lo, fe_hi), (be_lo, be_hi))
    assert not mismatches, f"UI advertises values the backend will clamp: {mismatches}"


# ── Settings-tab DEFAULTS extension (the "35 empty fields" regression) ───────

# The keys added to runtime_settings.DEFAULTS for the General Settings tab.
# Pinned here so a future trim of DEFAULTS cannot silently re-open the bug
# where the page rendered fields with no server-side value.
NEW_SETTINGS_KEYS: tuple[str, ...] = (
    # Risk & Sizing
    "max_spread_pips", "sl_atr_multiplier", "tp_atr_multiplier", "min_rr_ratio",
    "max_hold_bars", "cooling_off_streak", "sl_floor_atr_mult",
    "entry_displacement_atr_mult",
    # Signals & quality
    "quality_score_threshold", "autonomous_ml", "pre_signal_spread_filter",
    "signal_cooldown_sec", "min_confidence_floor", "conviction_min",
    # Models & training
    "retrain_interval_hours", "outcome_weight", "allow_synthetic_training",
    "dl_seq_len", "dl_confidence_threshold", "rl_n_epochs",
    # Notifications
    "notif_enable_browser", "notif_blackout", "notif_brief", "notif_corr_divergence",
    # Correlation
    "corr_refresh_sec", "corr_divergence_threshold", "corr_window_default",
    # Trade memory
    "trade_memory_window", "cooling_off_duration_sec",
    # Backtesting
    "backtest_initial_equity", "backtest_default_symbol",
    # GenAI & research
    "disable_research", "strategy_min_profit_factor", "strategy_min_win_rate",
    "genai_max_calls_per_hour",
)


def runtime_section_keys() -> list[str]:
    """Parse every field ``key: '…'`` declared inside ``RUNTIME_SECTIONS``.

    Scoped to that one literal so inline ``FieldRow`` fields living elsewhere
    (``session_gate`` card, ``local`` card's ``soundAlerts``) don't pollute the
    "page field must be backed by a server default" contract.
    """
    source = _read(PAGE_TSX)
    block = re.search(r"const RUNTIME_SECTIONS\b.*?=\s*\[(?P<body>.*?)\n\];", source, flags=re.S)
    assert block, "RUNTIME_SECTIONS not found in page.tsx"
    return re.findall(r"key: '([A-Za-z0-9_]+)'", block.group("body"))


def test_every_page_field_is_backed_by_a_server_default():
    """Regression guard for "35 fields rendered empty".

    Every key the Settings page can render from ``RUNTIME_SECTIONS`` must have
    a ``runtime_settings.DEFAULTS`` entry, otherwise ``defaults[key]`` is
    ``undefined`` and the input shows blank / never round-trips a value.
    """
    keys = runtime_section_keys()
    assert len(keys) >= 40, f"parsed only {len(keys)} fields from RUNTIME_SECTIONS — parser broke?"
    assert len(keys) == len(set(keys)), "duplicate field key in RUNTIME_SECTIONS"

    missing = sorted(k for k in keys if k not in runtime_settings.DEFAULTS)
    assert not missing, (
        "page.tsx renders fields with no server default (they would display empty): "
        f"{missing}"
    )

    # The session gate keys must stay part of the runtime contract too.
    assert "off_hours_allowed" in runtime_settings.DEFAULTS
    assert "allowed_sessions" in runtime_settings.DEFAULTS
    assert "off_hours_allowed" in keys, "the Trading Core off-hours row vanished"


def test_runtime_settings_defaults_is_substantial():
    count = len(runtime_settings.DEFAULTS)
    assert count >= 44, (
        f"runtime_settings.DEFAULTS shrank to {count} keys (expected >= 44); "
        "the Settings tab would render empty fields again"
    )
    # All 35 Settings-tab additions must still be present.
    missing = sorted(set(NEW_SETTINGS_KEYS) - set(runtime_settings.DEFAULTS))
    assert not missing, f"DEFAULTS dropped the Settings-tab keys: {missing}"


def test_new_settings_bounds_stay_inside_backend_clamps():
    """Scoped mirror of ``test_frontend_declared_bounds_stay_inside_backend_clamps``:
    a future edit must not widen a NEW page range beyond the backend clamp."""
    frontend = frontend_number_bounds()

    checked = 0
    for key in NEW_SETTINGS_KEYS:
        if key not in frontend:
            continue
        assert key in runtime_settings._BOUNDS, (
            f"{key} is declared numeric in page.tsx but has no backend _BOUNDS entry"
        )
        fe_lo, fe_hi = frontend[key]
        be_lo, be_hi = runtime_settings._BOUNDS[key]
        assert fe_lo >= be_lo and fe_hi <= be_hi, (
            f"{key}: page range {fe_lo}..{fe_hi} escapes backend clamp {be_lo}..{be_hi}"
        )
        checked += 1
    assert checked >= 20, (
        f"only {checked} of the new numeric fields parsed with min/max — parser broke?"
    )


def test_page_keeps_the_restored_original_ui_elements():
    """Source-level guard for the UI pieces restored in the settings rewrite."""
    page = _read(PAGE_TSX)

    # Trading Core: the off-hours row (Arabic label), bound to the session-gate key.
    row = next((line for line in page.splitlines() if "التداول خارج الجلسات" in line), None)
    assert row is not None, "the Arabic off-hours row disappeared from Trading Core"
    assert "key: 'off_hours_allowed'" in row, (
        "the off-hours row must be bound to off_hours_allowed"
    )
    assert "allow_off_hours" not in page, (
        "legacy allow_off_hours key must not come back (off_hours_allowed is the contract)"
    )

    # Connection card: DeepSeek API row.
    assert "DeepSeek API" in page
    assert "env: DEEPSEEK_API_KEY" in page

    # Auto-trade toggle inside the 'local' card (import + render).
    assert "import { AutoTradeToggle } from '@/components/trade-controls';" in page
    assert page.count("<AutoTradeToggle") >= 1, "AutoTradeToggle is imported but never rendered"

    # Mode badge (header + 'local' card) with its definition.
    assert "function ModeBadge(" in page
    assert page.count("<ModeBadge mode={systemMode} />") >= 2, (
        "ModeBadge must render in the header and in the 'local' card"
    )
    assert "وضع التداول" in page

    # Dynamic-thresholds row.
    assert "Risk/Reward (RR)" in page

    # The session_gate card must remain (its editable controls are covered by
    # test_page_offers_the_session_gate_as_editable_controls).
    assert 'id="session_gate"' in page
    assert 'id="local"' in page
    assert 'id="connection"' in page


def test_page_titles_and_labels_are_in_arabic():
    """The operator reads Arabic titles; technical terms stay English (ATR/RR/TF...)."""
    page = _read(PAGE_TSX)

    # Page header + the general tab's section titles.
    assert "لوحة الإعدادات" in page
    for title in (
        "نواة التداول (Trading Core)",
        "المخاطرة والحجم (Risk & Sizing)",
        "الإشارات والجودة (Signals & Quality)",
        "بوابة الجلسات الفعلية",
        "وضع التشغيل",
        "الاتصال",
        "العتبات الديناميكية (TradeMemory)",
    ):
        assert title in page, f"Arabic section title missing: {title}"

    # Every RUNTIME_SECTIONS field label must carry Arabic script.
    block = re.search(r"const RUNTIME_SECTIONS\b.*?=\s*\[(?P<body>.*?)\n\];", page, flags=re.S)
    assert block, "RUNTIME_SECTIONS not found"
    labels = re.findall(r"label: '([^']+)'", block.group("body"))
    assert len(labels) >= 40, f"only {len(labels)} field labels parsed — parser broke?"
    non_arabic = [label for label in labels if not re.search(r"[\u0600-\u06FF]", label)]
    assert not non_arabic, f"field labels without Arabic script: {non_arabic}"

    # No Spanish leftovers in the general tab (legacy labels were Spanish).
    for spanish in ("Fuera de sesión", "Guardar todo", "Revertir", "THRESHOLDS DINÁMICOS",
                    "HORAS MALAS", "Modo de operación", "Riesgo/Recompensa", "OVERRIDES MANUALES"):
        assert spanish not in page, f"Spanish UI string still present: {spanish}"


def test_page_offers_settings_templates_card():
    """Template save/load UI: folder path shown, file picker, built-in + last-settings."""
    page = _read(PAGE_TSX)

    assert 'id="templates"' in page, "templates card vanished from the general tab"
    assert "قوالب الإعدادات" in page
    # The storage folder must be visible to the operator.
    assert "templatesPath" in page
    # Save-as-template input + server call.
    assert "saveSettingsTemplate" in page
    # Stored-template loader + built-in preset + rollback + browser file picker.
    assert "loadSettingsTemplate" in page
    assert "optimal.json" in page
    assert "آخر إعدادات" in page
    assert "fileInputRef" in page and 'type="file"' in page
    # Client-side fill only: persistence still goes through the save button.
    assert "applyTemplateValues" in page


def test_page_offers_the_env_card_and_never_renders_secrets():
    """The ``.env`` card must exist end-to-end — and never render a secret.

    Covers the three layers of the feature: page.tsx (card id, the three Arabic
    group headings, the shield line and the restart notice), api-client.ts (the
    two methods talking to ``/api/system/env``) and the backend allow-list
    (``NEXUS_LLM_MODEL`` must never be droppable).  Negative half: none of the
    12 deny-listed secret key NAMES may appear in the frontend sources.
    """
    page = _read(PAGE_TSX)
    client = _read(API_CLIENT_TS)
    env_source = _read(ENV_ROUTER_PY)

    # ── Positive: the card, its Arabic groups, the shield + restart messaging ──
    assert 'id="env"' in page, "the .env section card vanished from the settings page"
    assert "بيئة النظام" in page, "the env card label vanished"
    for heading in ("أساسي (Core)", "خطير ⚠ (Danger)", "للقراءة فقط (Read-only)"):
        assert heading in page, f"env group heading missing: {heading}"
    assert "متغيرات أسرار محمية" in page, "the secrets shield line vanished"
    assert "يتطلب إعادة تشغيل" in page, "the restart notice must stay visible"

    # The api-client methods the card drives.
    assert "getSystemEnv" in client, "api-client.ts lost getSystemEnv"
    assert "updateSystemEnv" in client, "api-client.ts lost updateSystemEnv"

    # ── Negative: no secret key NAME may reach the frontend sources ────────────
    # The list must stay in lockstep with the backend deny list (env.SECRET_KEYS).
    assert len(SECRET_ENV_KEYS) == 12
    assert set(SECRET_ENV_KEYS) == set(env.SECRET_KEYS), (
        "the test's secret list drifted from env.SECRET_KEYS"
    )
    for key in SECRET_ENV_KEYS:
        assert key not in client, f"api-client.ts references secret {key}"
        if key == "DEEPSEEK_API_KEY":
            # Single, pinned, display-only LABEL in the connection card — a key
            # NAME (never a value), pinned by
            # test_page_keeps_the_restored_original_ui_elements.
            assert page.count(key) == 1, "DEEPSEEK_API_KEY gained extra occurrences in page.tsx"
            assert "env: DEEPSEEK_API_KEY" in page
        else:
            assert key not in page, f"page.tsx references secret {key}"

    # ── The backend allow-list keeps the model knob ────────────────────────────
    assert '"NEXUS_LLM_MODEL"' in env_source, (
        "NEXUS_LLM_MODEL dropped from the env allow-list — the model knob would disappear"
    )


# ── 4. Persistence round-trip ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_runtime_settings_dict_store_dict_round_trip(monkeypatch):
    monkeypatch.setattr(runtime_settings, "_cache", dict(runtime_settings._cache))
    monkeypatch.setattr(runtime_settings, "_last_fetch", 0.0)
    store = FakeSettingsStore()

    patch = {
        "risk_per_trade_pct": 2.5,
        "max_daily_trades": 7,
        "min_mtf_agreement": 2,
    }
    written = await runtime_settings.update_settings(patch, redis=store)

    # Stored document: a complete, JSON-stable dict that survives dict → store → dict.
    document = json.loads(store.store[runtime_settings.SETTINGS_KEY])
    assert json.loads(json.dumps(document)) == document
    assert set(runtime_settings.DEFAULTS) <= set(document), "stored document must stay complete"
    assert document["risk_per_trade_pct"] == 2.5
    assert document["max_daily_trades"] == 7
    assert document["min_mtf_agreement"] == 2

    # Read view: known keys come back merged over defaults, at the same values.
    view = await runtime_settings.get_settings(store, force=True)
    assert view["risk_per_trade_pct"] == 2.5
    assert view["max_daily_trades"] == 7
    assert view["min_mtf_agreement"] == 2
    assert written["max_daily_trades"] == 7


@pytest.mark.asyncio
async def test_runtime_settings_write_clamps_and_preserves_extras(monkeypatch):
    monkeypatch.setattr(runtime_settings, "_cache", dict(runtime_settings._cache))
    monkeypatch.setattr(runtime_settings, "_last_fetch", 0.0)
    store = FakeSettingsStore()
    # Extras are normally written by POST /api/intelligence/settings (raw Redis).
    store.store[runtime_settings.SETTINGS_KEY] = json.dumps(
        {"notif_enable_browser": True, "trade_memory_window": 150}
    )

    await runtime_settings.update_settings({"max_daily_trades": 99_999, "risk_per_trade_pct": 50}, redis=store)

    document = json.loads(store.store[runtime_settings.SETTINGS_KEY])

    # Bounds are enforced on the write path …
    assert document["max_daily_trades"] == 100
    assert document["risk_per_trade_pct"] == 5.0
    # … and a later write must not drop keys another writer stored (lost update).
    assert document["notif_enable_browser"] is True
    assert document["trade_memory_window"] == 150


@pytest.mark.asyncio
async def test_intelligence_write_then_runtime_read_round_trip(monkeypatch):
    """POST /api/intelligence/settings (router) → shared store → runtime read."""
    monkeypatch.setattr(runtime_settings, "_cache", dict(runtime_settings._cache))
    monkeypatch.setattr(runtime_settings, "_last_fetch", 0.0)
    store = FakeSettingsStore()
    monkeypatch.setattr(intelligence, "_get_redis", lambda: _async_value(store))

    req = intelligence.DynamicSettingsUpdate(
        settings={"max_daily_trades": 12, "notif_enable_browser": False}
    )
    payload = await intelligence.update_dynamic_settings(req, actor="tester", db=PermissiveDB())
    assert payload["status"] == "saved"

    # The router writes the raw document under the shared key …
    assert json.loads(store.store["nexus:runtime:settings"])["max_daily_trades"] == 12

    # … and the shared reader exposes the same value through its clamped view.
    view = await runtime_settings.get_settings(store, force=True)
    assert view["max_daily_trades"] == 12


def _async_value(value: Any):
    """Return a zero-arg coroutine factory yielding ``value`` (lazy import-safe)."""

    async def _factory():
        return value

    return _factory()
