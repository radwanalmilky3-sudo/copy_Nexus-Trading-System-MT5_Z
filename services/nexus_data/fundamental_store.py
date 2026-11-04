from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from duckdb import ConstraintException, ConversionException

log = structlog.get_logger("nexus_data.fundamental_store")


class FundamentalStore:
    """Fundamental persistence facade using the nexus-data single DuckDB writer.

    V6.1 distinguishes immutable audit/event rows from mutable canonical rows.
    Mutable rows use deterministic UPSERT rather than ``INSERT OR IGNORE`` so
    lifecycle/status/outcome updates cannot be silently discarded.

    Phase 4 (event timing integrity): ``fund_events`` gained nine nullable
    columns (``timing_quality``, ``authority``, ``release_tzid``,
    ``decision_date_local``, ``scheduled_status``, ``supersedes_event_id``,
    ``cancelled``, ``source_sha256``, ``retrieved_at_utc``).  The migration is
    anchored as ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` in
    ``fundamental_schema.sql`` and runs through :meth:`init_schema`; legacy
    rows keep NULL for all nine columns and are never rewritten.

    Enum reference values (aligned with fx-trading-system-main's central-bank
    calendar contract, consulted as reference only):

    * ``timing_quality`` (5 values): ``verified_actual_publication``,
      ``official_event_scheduled_time``, ``official_rule_derived``,
      ``official_date_only``, ``unverified_external``.  NULL means the
      timing was never classified and downstream logic must treat it as
      unverified (never as clear).
    * ``scheduled_status``: ``scheduled``, ``unscheduled``, ``cancelled``,
      ``superseded``, ``unknown``.  ``unknown`` is the legacy-default state
      for new writers; legacy rows stay NULL (no backfill).

    ``release_tzid`` holds an IANA timezone id (e.g. ``America/New_York``);
    ``decision_date_local`` is the calendar date of the event in that zone.
    ``source_sha256``/``retrieved_at_utc`` are ingestion pass-through fields.

    Cancellation is append-only: :meth:`mark_event_cancelled` INSERTs a new
    row (``cancelled=TRUE``, ``scheduled_status='cancelled'``,
    ``supersedes_event_id`` pointing at the original) instead of deleting or
    overwriting history.  :meth:`get_event_timeline` exposes cancelled and
    superseded rows rather than a silent "net" view.
    """

    ALLOWED = {
        "source_fetch_runs", "source_health_history", "fund_events", "event_expectations",
        "data_vintages", "macro_releases", "central_bank_events", "news_articles",
        "news_nlp_analysis", "market_series_observations", "geopolitical_events",
        "flow_observations", "fundamental_factor_scores", "fundamental_fusion_results",
        "gold_impact_predictions", "prediction_reasoning_steps", "fundamental_explanations",
        "fundamental_blackout_windows", "fundamental_guard_decisions",
        "fundamental_event_outcomes", "fundamental_training_features", "model_evaluations",
        "fundamental_audit_log", "economic_indicator_catalog", "economic_indicator_observations",
        "fundamental_knowledge_sources", "fundamental_knowledge_claims",
        "asset_registry", "asset_factor_profiles", "event_asset_impacts",
        "asset_event_outcomes", "news_story_clusters", "news_ticker_items",
        "alert_delivery_log", "local_ai_analysis_runs",
        "app_users", "app_roles", "app_role_permissions", "app_user_roles",
        "user_notification_preferences", "user_ticker_acknowledgements", "user_audit_log",
        "api_tokens", "ea_commands",
    }

    # Canonical/mutable tables.  Keys are real primary keys in fundamental_schema.sql.
    UPSERT_KEYS: dict[str, tuple[str, ...]] = {
        "economic_indicator_catalog": ("indicator_id",),
        "economic_indicator_observations": ("observation_id",),
        "fundamental_knowledge_sources": ("knowledge_source_id",),
        "fundamental_knowledge_claims": ("claim_id",),
        "asset_registry": ("asset_id",),
        "asset_factor_profiles": ("profile_id",),
        "event_asset_impacts": ("impact_id",),
        "asset_event_outcomes": ("outcome_id",),
        "news_story_clusters": ("story_cluster_id",),
        "news_ticker_items": ("ticker_item_id",),
        "app_users": ("user_id",),
        "app_roles": ("role_id",),
        "app_role_permissions": ("role_id", "permission_code"),
        "app_user_roles": ("user_id", "role_id"),
        "user_notification_preferences": ("user_id",),
        "user_ticker_acknowledgements": ("user_id", "ticker_item_id"),
        "api_tokens": ("token_id",),
        "ea_commands": ("command_id",),
    }
    UPDATED_AT_TABLES = {
        "economic_indicator_catalog", "fundamental_knowledge_claims", "asset_registry", "news_ticker_items",
        "app_users", "app_roles", "app_role_permissions", "app_user_roles", "user_notification_preferences", "user_ticker_acknowledgements",
        "api_tokens", "ea_commands"
    }
    # DuckDB rejects an ON CONFLICT DO UPDATE that touches a unique identity
    # column referenced by another table, even when the value is unchanged.
    # Keep these natural identities immutable after insertion.
    IMMUTABLE_IDENTITY_COLUMNS: dict[str, frozenset[str]] = {
        "asset_registry": frozenset({"symbol"}),
        "economic_indicator_catalog": frozenset({"indicator_code"}),
    }
    # Reference catalogs and reviewed knowledge claims are versioned seed
    # metadata. Startup may replay the same seeds, but revisions must use a
    # new stable ID or an explicit migration rather than rewriting indexed,
    # referenced rows on every service start.
    SEED_ONLY_TABLES = frozenset({
        "asset_registry",
        "economic_indicator_catalog",
        "fundamental_knowledge_claims",
    })
    # An outcome belongs to the exact impact snapshot known at prediction
    # time. Preserve it on retries; later calculations use new snapshot IDs.
    APPEND_ONLY_TABLES = frozenset({"event_asset_impacts"})

    # Phase 4 (event timing integrity) reference enums.  Legacy rows keep
    # NULL for all of these; validation applies only to new explicit writes.
    TIMING_QUALITY_VALUES = frozenset({
        "verified_actual_publication",
        "official_event_scheduled_time",
        "official_rule_derived",
        "official_date_only",
        "unverified_external",
    })
    SCHEDULED_STATUS_VALUES = frozenset({
        "scheduled", "unscheduled", "cancelled", "superseded", "unknown",
    })
    TIMING_COLUMNS = (
        "timing_quality", "authority", "release_tzid", "decision_date_local",
        "scheduled_status", "supersedes_event_id", "cancelled",
        "source_sha256", "retrieved_at_utc",
    )

    REFERENCES: dict[str, tuple[tuple[str, str, str], ...]] = {
        "asset_factor_profiles": (("asset_id", "asset_registry", "asset_id"),),
        "event_asset_impacts": (("asset_id", "asset_registry", "asset_id"),),
        "asset_event_outcomes": (("asset_id", "asset_registry", "asset_id"),),
        "news_ticker_items": (("asset_id", "asset_registry", "asset_id"),),
        "local_ai_analysis_runs": (("asset_id", "asset_registry", "asset_id"),),
        "app_role_permissions": (("role_id", "app_roles", "role_id"),),
        "app_user_roles": (
            ("user_id", "app_users", "user_id"),
            ("role_id", "app_roles", "role_id"),
        ),
        "user_notification_preferences": (("user_id", "app_users", "user_id"),),
        "user_ticker_acknowledgements": (("user_id", "app_users", "user_id"),),
        "api_tokens": (("user_id", "app_users", "user_id"),),
        "ea_commands": (("user_id", "app_users", "user_id"),),
    }

    QUERY_SPECS: dict[str, tuple[str, tuple[str, ...]]] = {
        "bootstrap_user_count": ("SELECT COUNT(*) AS c FROM app_users WHERE deleted=FALSE", ()),
        "user_by_username": ("SELECT * FROM app_users WHERE lower(username)=lower(?) AND deleted=FALSE LIMIT 1", ("username",)),
        "user_by_id": ("SELECT * FROM app_users WHERE user_id=? AND deleted=FALSE LIMIT 1", ("user_id",)),
        "user_profile": ("SELECT user_id,username,full_name,email,avatar_path,language,timezone,active FROM app_users WHERE user_id=? AND deleted=FALSE LIMIT 1", ("user_id",)),
        "user_avatar_path": ("SELECT avatar_path FROM app_users WHERE user_id=? AND deleted=FALSE LIMIT 1", ("user_id",)),
        "user_role_ids": ("SELECT role_id FROM app_user_roles WHERE user_id=? AND active=TRUE", ("user_id",)),
        "user_permissions": ("SELECT rp.permission_code FROM app_role_permissions rp JOIN app_user_roles ur ON ur.role_id=rp.role_id WHERE ur.user_id=? AND ur.active=TRUE AND rp.allowed=TRUE", ("user_id",)),
        "users_list": ("SELECT u.user_id,u.username,u.full_name,u.email,u.language,u.timezone,u.active,u.created_at,u.last_login_at,ur.role_id,u.avatar_path FROM app_users u LEFT JOIN app_user_roles ur ON ur.user_id=u.user_id AND ur.primary_role=TRUE AND ur.active=TRUE WHERE u.deleted=FALSE ORDER BY u.full_name", ()),
        "user_exists": ("SELECT user_id FROM app_users WHERE lower(username)=lower(?) AND deleted=FALSE LIMIT 1", ("username",)),
        "user_tombstone_by_username": ("SELECT user_id, username FROM app_users WHERE lower(username)=lower(?) AND deleted=TRUE LIMIT 1", ("username",)),
        "role_exists": ("SELECT role_id FROM app_roles WHERE role_id=? LIMIT 1", ("role_id",)),
        "user_active_roles": ("SELECT role_id FROM app_user_roles WHERE user_id=? AND active=TRUE", ("user_id",)),
        "roles_list": ("SELECT * FROM app_roles ORDER BY protected DESC,name_en", ()),
        "role_permissions": ("SELECT permission_code FROM app_role_permissions WHERE role_id=? AND allowed=TRUE ORDER BY permission_code", ("role_id",)),
        "role_permission_codes": ("SELECT permission_code FROM app_role_permissions WHERE role_id=?", ("role_id",)),
        "notification_preferences": ("SELECT * FROM user_notification_preferences WHERE user_id=? LIMIT 1", ("user_id",)),
        "user_ticker_acknowledgements": ("SELECT ticker_item_id,acknowledged,acknowledged_at,acknowledge_note FROM user_ticker_acknowledgements WHERE user_id=?", ("user_id",)),
        "audit_entries": ("SELECT * FROM user_audit_log ORDER BY created_at DESC LIMIT ?", ("limit",)),
        "agent_reasoning": ("SELECT * FROM agent_logs WHERE metadata::JSON->>'cycle_id' = ? OR metadata LIKE ? ORDER BY ts", ("cycle_id", "cycle_pattern")),
        "positions_by_status": ("SELECT * FROM positions WHERE status = ? ORDER BY opened_at DESC", ("status",)),
        "position_by_id": ("SELECT * FROM positions WHERE id = ? LIMIT 1", ("position_id",)),
        "event_asset_impacts": ("SELECT * FROM event_asset_impacts WHERE event_id=? ORDER BY calculated_at DESC, asset_id, horizon", ("event_id",)),
        "ticker_item_exists": ("SELECT ticker_item_id FROM news_ticker_items WHERE ticker_item_id=? LIMIT 1", ("ticker_item_id",)),
        "ticker_history": ("SELECT * FROM news_ticker_items ORDER BY created_at DESC LIMIT ?", ("limit",)),
        "asset_event_outcome_by_impact": ("SELECT * FROM asset_event_outcomes WHERE impact_id=? ORDER BY captured_at DESC LIMIT 1", ("impact_id",)),
        "asset_outcomes": ("SELECT * FROM asset_event_outcomes WHERE asset_id=? ORDER BY captured_at DESC LIMIT ?", ("asset_id", "limit")),
        "knowledge_claims": ("SELECT claim_id,domain,concept,statement_ar,conditions_json,counter_conditions_json,required_confirmations_json,exceptions_json,horizon_json FROM fundamental_knowledge_claims WHERE allowed_for_explanation=TRUE AND review_status='reviewed_for_explanation' ORDER BY claim_id LIMIT 100", ()),
        "local_ai_history": ("SELECT analysis_id,asset_id,event_id,impact_id,question,model_name,model_version,schema_valid,latency_ms,created_at,response_json,hallucination_flags_json FROM local_ai_analysis_runs ORDER BY created_at DESC LIMIT ?", ("limit",)),
        "api_token_by_hash": ("SELECT * FROM api_tokens WHERE token_hash=? AND active=TRUE LIMIT 1", ("token_hash",)),
        "api_tokens_by_user": ("SELECT token_id,label,mt5_login,mt5_broker,mt5_server,active,created_at,last_used_at,revoked_at FROM api_tokens WHERE user_id=? ORDER BY created_at DESC", ("user_id",)),
        "api_token_by_id": ("SELECT * FROM api_tokens WHERE token_id=? AND user_id=? LIMIT 1", ("token_id", "user_id")),
        "api_tokens_active_users": ("SELECT DISTINCT user_id FROM api_tokens WHERE active=TRUE", ()),
        # Stale claims (EA died before reporting) re-enter the queue after 5
        # minutes; NexusBridgeEA journals executed command_ids locally, so a
        # re-claim never double-executes on the terminal.
        "ea_pending_commands": ("SELECT * FROM ea_commands WHERE user_id=? AND (status='pending' OR (status='claimed' AND (claimed_at IS NULL OR claimed_at < CURRENT_TIMESTAMP - INTERVAL 5 MINUTE))) ORDER BY created_at LIMIT 20", ("user_id",)),
        "ea_command_by_id": ("SELECT * FROM ea_commands WHERE command_id=? AND user_id=? LIMIT 1", ("command_id", "user_id")),
        "ea_commands_recent": ("SELECT * FROM ea_commands WHERE user_id=? ORDER BY created_at DESC LIMIT 50", ("user_id",)),
    }

    def __init__(self, data_store: Any) -> None:
        self._store = data_store

    async def query_named(self, operation: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Run one registered, parameterized gateway query; caller SQL is never accepted."""
        if not isinstance(params, dict):
            raise ValueError("query parameters must be an object")

        if operation == "research_collection":
            if set(params) != {"resource", "limit", "offset", "query"}:
                raise ValueError("query parameters do not match operation")
            from .research_reader import ResearchReader
            return [await ResearchReader(self._store).collection(**params)]

        if operation == "research_item":
            if set(params) != {"resource", "item_id"}:
                raise ValueError("query parameters do not match operation")
            from .research_reader import ResearchReader
            return [await ResearchReader(self._store).collection(
                params['resource'], limit=1, offset=0, query=None, item_id=params['item_id'])]

        if operation == "fund_sources_by_ids":
            if set(params) != {"source_ids"}:
                raise ValueError("query parameters do not match operation")
            source_ids = params["source_ids"]
            if not isinstance(source_ids, list) or not source_ids or len(source_ids) > 100:
                raise ValueError("source_ids must contain between 1 and 100 identifiers")
            if any(not isinstance(value, str) or not value.strip() or len(value) > 160 for value in source_ids):
                raise ValueError("source_ids must be short strings")
            marks = ",".join("?" for _ in source_ids)
            sql = (
                "SELECT source_id,name_ar,name_en,organization,category,trust_score,health_state,updated_at "
                f"FROM fund_sources WHERE source_id IN ({marks})"
            )
            values = tuple(source_ids)
        else:
            spec = self.QUERY_SPECS.get(operation)
            if spec is None:
                raise ValueError("unknown query operation")
            sql, keys = spec
            if set(params) != set(keys):
                raise ValueError("query parameters do not match operation")
            values_list: list[Any] = []
            for key in keys:
                value = params[key]
                if key == "limit":
                    if type(value) is not int or value < 1:
                        raise ValueError("limit must be a positive integer")
                elif value is not None and (
                    not isinstance(value, str) or not value.strip()
                ):
                    raise ValueError("query parameter value is invalid")
                values_list.append(value)
            values = tuple(values_list)

        rows, columns = await self._store._fetch_with_columns(sql, values)
        return [dict(zip(columns, row)) for row in rows]

    async def init_schema(self) -> None:
        schema_path = Path(__file__).with_name("fundamental_schema.sql")
        sql = schema_path.read_text(encoding="utf-8")
        await self._store._run_script(sql)
        await log.ainfo("fundamental.schema_ready", schema=str(schema_path))

    async def upsert_source(self, source: dict[str, Any]) -> None:
        for key in ("source_id", "name_ar", "name_en", "category", "transport"):
            if not isinstance(source.get(key), str) or not source[key].strip():
                raise ValueError(f"source field must be a non-empty string: {key}")
        await self._write(
            """
            INSERT INTO fund_sources (
                source_id,name_ar,name_en,organization,category,transport,base_endpoint,
                documentation_url,auth_type,api_key_env,polling_interval_sec,
                freshness_limit_sec,rate_limit_per_min,provider_priority,fallback_group,
                trust_score,license_name,storage_allowed,redistribution_allowed,
                commercial_use_notes,enabled,health_state,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(source_id) DO UPDATE SET
                name_ar=excluded.name_ar,name_en=excluded.name_en,
                organization=excluded.organization,category=excluded.category,
                transport=excluded.transport,base_endpoint=excluded.base_endpoint,
                documentation_url=excluded.documentation_url,auth_type=excluded.auth_type,
                api_key_env=excluded.api_key_env,polling_interval_sec=excluded.polling_interval_sec,
                freshness_limit_sec=excluded.freshness_limit_sec,
                rate_limit_per_min=excluded.rate_limit_per_min,
                provider_priority=excluded.provider_priority,fallback_group=excluded.fallback_group,
                trust_score=excluded.trust_score,license_name=excluded.license_name,
                storage_allowed=excluded.storage_allowed,
                redistribution_allowed=excluded.redistribution_allowed,
                commercial_use_notes=excluded.commercial_use_notes,
                enabled=excluded.enabled,health_state=excluded.health_state,
                updated_at=now()
            """,
            (
                source["source_id"], source["name_ar"], source["name_en"], source.get("organization"),
                source["category"], source["transport"], source.get("base_endpoint"),
                source.get("documentation_url"), source.get("auth_type", "none"), source.get("api_key_env"),
                source.get("polling_interval_sec"), source.get("freshness_limit_sec"),
                source.get("rate_limit_per_min"), source.get("provider_priority", 100),
                source.get("fallback_group"), source.get("trust_score", 50), source.get("license_name"),
                source.get("storage_allowed", True), source.get("redistribution_allowed", False),
                source.get("commercial_use_notes"), source.get("enabled", True), source.get("health_state", "unknown"),
            ),
        )

    @staticmethod
    def _encode(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return value

    async def _write(self, sql: str, values: tuple[Any, ...]) -> None:
        try:
            await self._store._run(sql, values)
        except (ConstraintException, ConversionException) as exc:
            # Invalid values and foreign-key races are client errors; operational
            # database failures must still propagate as server errors.
            raise ValueError("record violates schema constraints or field types") from exc

    async def _columns(self, table: str) -> list[tuple[Any, ...]]:
        return await self._store._fetch(
            "SELECT column_name,is_nullable,column_default FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name=?",
            (table,),
        )

    async def insert_record(self, table: str, record: dict[str, Any]) -> None:
        if table not in self.ALLOWED:
            raise ValueError(f"table not allowed: {table}")
        if not record:
            raise ValueError("record is empty")
        columns = await self._columns(table)
        if not columns:
            raise RuntimeError(f"schema unavailable for table: {table}")
        column_names = {column[0] for column in columns}
        if set(record) - column_names:
            raise ValueError("record contains unknown fields")
        for column, nullable, default in columns:
            if nullable == "NO" and (
                (column in record and record[column] is None)
                or (column not in record and default is None)
            ):
                raise ValueError(f"record requires field: {column}")
        # DuckDB cannot add FOREIGN KEY constraints to existing tables with
        # ALTER TABLE. Enforce these relationships at the sole write boundary
        # so current databases receive the same protection without rebuilding
        # their tables or touching existing rows.
        for column, referenced_table, referenced_column in self.REFERENCES.get(table, ()):
            value = record.get(column)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"reference must be a non-empty string: {column}")
            rows = await self._store._fetch(
                f"SELECT 1 FROM {referenced_table} WHERE {referenced_column}=? LIMIT 1",
                (value,),
            )
            if not rows:
                raise ValueError(f"unknown reference: {referenced_table}.{referenced_column}")
        cols = list(record)
        values = [self._encode(record[col]) for col in cols]
        marks = ",".join("?" for _ in cols)
        keys = self.UPSERT_KEYS.get(table)
        if keys and all(k in record for k in keys):
            if table in self.SEED_ONLY_TABLES or table in self.APPEND_ONLY_TABLES:
                sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({marks})"
                await self._write(sql, tuple(values))
                return
            immutable = self.IMMUTABLE_IDENTITY_COLUMNS.get(table, frozenset())
            non_keys = [
                c for c in cols
                if c not in keys and c != "created_at" and c not in immutable
            ]
            assignments = [f"{c}=?" for c in non_keys]
            # Existing project databases predate some of the R4/R5 schema
            # columns.  `CREATE TABLE IF NOT EXISTS` does not add them, so an
            # unconditional updated_at assignment makes every UPSERT fail on
            # those valid legacy tables.  Only update the timestamp when this
            # actual database table exposes the column.
            if (
                table in self.UPDATED_AT_TABLES
                and "updated_at" in column_names
                and "updated_at" not in non_keys
            ):
                assignments.append("updated_at=now()")
            if assignments:
                # Do the insert and update separately.  DuckDB's UPSERT path
                # attempts to rewrite referenced unique keys and fails for
                # legitimate existing registry/catalog rows.  The data service
                # serializes this single writer connection, so the pair is safe
                # within this process.
                insert_sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({marks})"
                await self._write(insert_sql, tuple(values))
                where = " AND ".join(f"{key}=?" for key in keys)
                update_values = [self._encode(record[column]) for column in non_keys]
                update_values.extend(self._encode(record[key]) for key in keys)
                sql = f"UPDATE {table} SET {','.join(assignments)} WHERE {where}"
                await self._write(sql, tuple(update_values))
                return
            else:
                sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({marks})"
        else:
            sql = f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({marks})"
        await self._write(sql, tuple(values))

    async def latest_rows(self, table: str, order_col: str, limit: int = 50) -> list[dict[str, Any]]:
        if table not in self.ALLOWED | {"fund_sources"}:
            raise ValueError(f"table not allowed: {table}")
        # Whitelist order columns; table names are separately allowlisted.
        allowed_order = {"created_at", "updated_at", "calculated_at", "captured_at", "timestamp", "known_at", "published_at", "last_seen_at"}
        if order_col not in allowed_order:
            raise ValueError(f"order column not allowed: {order_col}")
        if order_col not in {column[0] for column in await self._columns(table)}:
            raise ValueError(f"order column does not exist in table: {order_col}")
        rows, cols = await self._store._fetch_with_columns(
            f"SELECT * FROM {table} ORDER BY {order_col} DESC LIMIT ?", (max(1, min(limit, 500)),)
        )
        return [dict(zip(cols, row)) for row in rows]

    async def schema_inventory(self) -> dict[str, Any]:
        tables = await self._store._fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name", ()
        )
        result: dict[str, Any] = {}
        for (table_name,) in tables:
            cols = await self._store._fetch(
                "SELECT column_name,data_type,is_nullable FROM information_schema.columns "
                "WHERE table_schema='main' AND table_name=? ORDER BY ordinal_position",
                (table_name,),
            )
            result[table_name] = [{"name": c[0], "type": c[1], "nullable": c[2]} for c in cols]
        return result

    # ── Phase 4: event timing integrity (append-only) ────────────────────

    async def mark_event_cancelled(
        self,
        event_id: str,
        *,
        new_event_id: str | None = None,
        supersedes: str | None = None,
        reason: str | None = None,
        actor: str = "fundamental_store",
        timing_quality: str | None = None,
        authority: str | None = None,
        release_tzid: str | None = None,
        decision_date_local: date | None = None,
        scheduled_status: str = "cancelled",
        source_sha256: str | None = None,
        retrieved_at_utc: datetime | None = None,
    ) -> str:
        """Append a cancellation row for ``event_id`` without rewriting history.

        fund_events rows are keyed by ``event_id`` (primary key), so a
        cancellation INSERTs a NEW row carrying ``cancelled=TRUE``,
        ``scheduled_status`` (default ``'cancelled'``) and
        ``supersedes_event_id`` pointing at the cancelled original.  The
        original row is never deleted or updated; the optional ``reason`` is
        recorded in ``fundamental_audit_log``.  Returns the new row's id.
        """
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("event_id must be a non-empty string")
        if scheduled_status not in self.SCHEDULED_STATUS_VALUES:
            raise ValueError(f"invalid scheduled_status: {scheduled_status!r}")
        if timing_quality is not None and timing_quality not in self.TIMING_QUALITY_VALUES:
            raise ValueError(f"invalid timing_quality: {timing_quality!r}")
        supersedes_target = supersedes if supersedes is not None else event_id
        if not isinstance(supersedes_target, str) or not supersedes_target.strip():
            raise ValueError("supersedes must be a non-empty string")

        original = await self._store._fetch(
            "SELECT event_id,source_id,category,subcategory,event_type,event_code,"
            "title_en,title_ar,country,currency,declared_impact,gold_relevance,"
            "timing_quality,authority,release_tzid,decision_date_local "
            "FROM fund_events WHERE event_id=? LIMIT 1",
            (event_id,),
        )
        if not original:
            raise ValueError(f"unknown event_id: {event_id}")
        row = original[0]

        candidate = new_event_id if new_event_id is not None else f"{event_id}:cancelled"
        suffix = 2
        while await self._store._fetch(
            "SELECT 1 FROM fund_events WHERE event_id=? LIMIT 1", (candidate,)
        ):
            if new_event_id is not None:
                raise ValueError(f"event_id already exists: {new_event_id}")
            candidate = f"{event_id}:cancelled:{suffix}"
            suffix += 1

        await self._write(
            "INSERT INTO fund_events ("
            "event_id,source_id,category,subcategory,event_type,event_code,"
            "title_en,title_ar,country,currency,"
            "timing_quality,authority,release_tzid,decision_date_local,"
            "scheduled_status,supersedes_event_id,cancelled,"
            "source_sha256,retrieved_at_utc,declared_impact,gold_relevance,received_at"
            ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
            (
                candidate, row[1], row[2], row[3], row[4], row[5],
                row[6], row[7], row[8], row[9],
                timing_quality if timing_quality is not None else row[12],
                authority if authority is not None else row[13],
                release_tzid if release_tzid is not None else row[14],
                decision_date_local if decision_date_local is not None else row[15],
                scheduled_status, supersedes_target, True,
                source_sha256, retrieved_at_utc, row[10], row[11],
            ),
        )
        await self._write(
            "INSERT OR IGNORE INTO fundamental_audit_log ("
            "audit_id,timestamp,actor,action,entity_type,entity_id,before_json,reason"
            ") VALUES (?,now(),?, 'fund_event_cancelled','fund_event',?,?,?)",
            (
                f"fund-event-cancel:{candidate}", actor, candidate,
                json.dumps({"event_id": event_id, "supersedes_event_id": supersedes_target}),
                reason,
            ),
        )
        await log.ainfo(
            "fund_event.cancelled",
            event_id=event_id, new_event_id=candidate,
            supersedes_event_id=supersedes_target, reason=reason,
        )
        return candidate

    async def get_event_timeline(
        self,
        *,
        event_id: str | None = None,
        event_code: str | None = None,
        event_type: str | None = None,
        include_cancelled: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return fund_events rows chronologically; no silent "net" view.

        Cancelled and superseded rows are INCLUDED by default
        (``include_cancelled=True``) so history stays visible; pass
        ``include_cancelled=False`` only to opt out.  At least one of
        ``event_id``/``event_code``/``event_type`` is required.
        """
        if not any((event_id, event_code, event_type)):
            raise ValueError("one of event_id/event_code/event_type is required")
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        clauses: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("event_id", event_id), ("event_code", event_code), ("event_type", event_type),
        ):
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"query parameter value is invalid: {column}")
            clauses.append(f"{column}=?")
            values.append(value)
        if not include_cancelled:
            clauses.append("(cancelled IS NULL OR cancelled=FALSE)")
        sql = (
            "SELECT * FROM fund_events WHERE " + " AND ".join(clauses) +
            " ORDER BY COALESCE(published_at, received_at, created_at) ASC, event_id ASC LIMIT ?"
        )
        values.append(min(limit, 500))
        rows, columns = await self._store._fetch_with_columns(sql, tuple(values))
        return [dict(zip(columns, row)) for row in rows]
