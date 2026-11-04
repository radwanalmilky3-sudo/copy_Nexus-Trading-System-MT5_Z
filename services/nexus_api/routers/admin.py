from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..data_client import DataServiceClient, DataServiceUnavailable
from ..deps import get_data_service
from ..http_client import new_client
from ..middleware.auth import CurrentUser, create_token, verify_pin

router = APIRouter(tags=["admin"])
UTC = timezone.utc

PERMISSIONS = [
    "users.view","users.create","users.edit","users.disable","users.delete",
    "roles.view","roles.manage","alerts.configure_self","alerts.manage_global",
    "ticker.view","ticker.acknowledge","ticker.manage_global","tts.configure_self",
    "source_manager.view","source_manager.edit","source_manager.test","source_manager.secrets",
    "fundamental.view","fundamental.configure","trading.view","trading.settings","trading.execute",
    "risk.view","risk.modify","audit.view",
]


def _hash_password(password: str) -> str:
    if len(password) < 10:
        raise HTTPException(422, "password must be at least 10 characters")
    salt = secrets.token_bytes(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${base64.b64encode(salt).decode()}${base64.b64encode(key).decode()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        kind,n,r,p,salt_b64,key_b64 = encoded.split("$",5)
        if kind != "scrypt": return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(key_b64)
        got = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


async def _post_data(table: str, record: dict[str, Any]) -> None:
    secret = os.getenv("NEXUS_INTERNAL_API_SECRET", "").strip()
    if not secret:
        raise HTTPException(503, "NEXUS_INTERNAL_API_SECRET is not configured")
    url = os.getenv("NEXUS_DATA_URL", "http://127.0.0.1:9001").rstrip("/") + "/api/data/fundamental/record"
    try:
        async with new_client(timeout=10.0) as client:
            res = await client.post(url, headers={"X-Nexus-Internal-Secret": secret}, json={"table": table, "record": json.loads(json.dumps(record, default=str))})
    except httpx.TransportError as exc:
        raise DataServiceUnavailable("Data service unavailable") from exc
    if not res.is_success:
        # D10-a: surface the upstream rejection detail (validation messages only,
        # no secrets) instead of masking every non-success as a generic 503.
        detail = res.text[:200].replace("\n", " ")
        raise DataServiceUnavailable(f"data service rejected write ({res.status_code}): {detail}")


async def _role_ids(db: DataServiceClient, user_id: str) -> list[str]:
    rows = await db.query("user_role_ids", {"user_id": user_id})
    return [str(r["role_id"]) for r in rows]


async def _permissions(db: DataServiceClient, user_id: str) -> set[str]:
    rows = await db.query("user_permissions", {"user_id": user_id})
    return {str(r["permission_code"]) for r in rows}


async def _require(db: DataServiceClient, user_id: str, permission: str) -> None:
    perms = await _permissions(db, user_id)
    if "*" not in perms and permission not in perms:
        raise HTTPException(403, f"permission required: {permission}")


def require_permission(permission: str):
    """Build a FastAPI dependency that enforces a database-backed permission."""
    async def dependency(
        actor: CurrentUser,
        db: DataServiceClient = Depends(get_data_service),
    ) -> None:
        await _require(db, actor, permission)
    return dependency


async def _audit(actor: str | None, action: str, target_type: str | None=None, target_id: str | None=None, details: dict[str,Any] | None=None) -> None:
    await _post_data("user_audit_log", {
        "audit_id": uuid.uuid4().hex,
        "actor_user_id": actor,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "details_json": json.dumps(details or {}, ensure_ascii=False),
        "created_at": datetime.now(UTC),
    })


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)

class BootstrapIn(BaseModel):
    admin_pin: str
    username: str = Field(min_length=3, max_length=80)
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=10, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    language: str = "ar"
    timezone: str = "Asia/Aden"

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=10, max_length=200)
    email: str | None = Field(default=None, max_length=200)
    role_id: str = "viewer"
    language: str = "ar"
    timezone: str = "Asia/Aden"
    active: bool = True
    avatar_data_url: str | None = None

class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=200)
    role_id: str | None = None
    language: str | None = None
    timezone: str | None = None
    active: bool | None = None
    avatar_data_url: str | None = None

class PasswordReset(BaseModel):
    password: str = Field(min_length=10, max_length=200)

class RolePermissionsIn(BaseModel):
    permissions: list[str]

class NotificationPreferencesIn(BaseModel):
    ticker_enabled: bool = True
    assets: list[str] = Field(default_factory=lambda:["XAUUSD","BTCUSD"])
    domains: list[str] = Field(default_factory=lambda:["macro","monetary","cross_asset","geopolitical","flows","news"])
    minimum_severity: str = "medium"
    critical_ttl_seconds: int = Field(default=0, ge=0, le=86400)
    high_ttl_seconds: int = Field(default=600, ge=30, le=86400)
    medium_ttl_seconds: int = Field(default=300, ge=30, le=86400)
    low_ttl_seconds: int = Field(default=120, ge=30, le=86400)
    hide_after_ack: bool = True
    show_acknowledged: bool = False
    show_scheduled: bool = True
    show_breaking: bool = True
    show_source_outage: bool = True
    critical_display_mode: str = "ticker_banner_tts"
    high_display_mode: str = "ticker_toast_sound"
    medium_display_mode: str = "ticker_toast"
    low_display_mode: str = "ticker"
    tts_enabled: bool = True
    tts_language: str = "ar"
    tts_voice: str = "system_arabic"
    tts_volume: float = Field(default=.85, ge=0, le=1)
    tts_rate: float = Field(default=1.0, ge=.6, le=1.5)
    tts_levels: list[str] = Field(default_factory=lambda:["critical","high"])
    tts_repeat_critical: bool = True
    tts_repeat_interval_seconds: int = Field(default=25, ge=10, le=300)
    require_ack_critical: bool = True
    mute_until: datetime | None = None
    quiet_hours_enabled: bool = False
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"


def _save_avatar(user_id: str, data_url: str | None) -> str | None:
    if not data_url: return None
    try:
        header, payload = data_url.split(",",1)
        mime = header.split(";")[0].split(":",1)[1]
        ext = {"image/png":"png","image/jpeg":"jpg","image/webp":"webp"}.get(mime)
        if not ext: raise ValueError("unsupported image type")
        raw = base64.b64decode(payload, validate=True)
        if len(raw) > 2_000_000: raise ValueError("avatar too large")
        root = Path(os.getenv("NEXUS_USER_MEDIA_DIR", "./data/user_avatars")).resolve()
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{user_id}.{ext}"
        path.write_bytes(raw)
        return str(path)
    except Exception as exc:
        raise HTTPException(422, f"invalid avatar: {exc}")


@router.post("/api/v2/auth/bootstrap")
async def bootstrap(payload: BootstrapIn, db: DataServiceClient=Depends(get_data_service)):
    verify_pin(payload.admin_pin)
    rows = await db.query("bootstrap_user_count")
    if rows and int(rows[0]["c"]) > 0: raise HTTPException(409, "bootstrap already completed")
    user_id = uuid.uuid4().hex
    await _post_data("app_users", {"user_id":user_id,"username":payload.username.strip().lower(),"full_name":payload.full_name,"email":payload.email,"password_hash":_hash_password(payload.password),"language":payload.language,"timezone":payload.timezone,"active":True,"deleted":False,"created_at":datetime.now(UTC),"updated_at":datetime.now(UTC)})
    await _post_data("app_user_roles", {"user_id":user_id,"role_id":"super_admin","primary_role":True,"active":True,"created_at":datetime.now(UTC),"updated_at":datetime.now(UTC)})
    await _audit(user_id,"bootstrap.super_admin","user",user_id,{"username":payload.username})
    return {"ok":True,"user_id":user_id}


@router.post("/api/v2/auth/login")
async def login(payload: LoginIn, db: DataServiceClient=Depends(get_data_service)):
    rows = await db.query("user_by_username", {"username": payload.username.strip()})
    if not rows or not rows[0].get("active") or not _verify_password(payload.password, str(rows[0]["password_hash"])):
        raise HTTPException(401, "Invalid credentials")
    user = rows[0]
    roles = await _role_ids(db, str(user["user_id"]))
    await _post_data("app_users", {**user,"last_login_at":datetime.now(UTC),"updated_at":datetime.now(UTC)})
    token = create_token(str(user["user_id"]))
    return {"token":token,"expiresAt":None,"user":{"id":user["user_id"],"username":user["username"],"full_name":user["full_name"],"role":roles[0] if roles else "viewer","avatar_url":f"/api/v2/users/{user['user_id']}/avatar" if user.get("avatar_path") else None}}


@router.post("/api/v2/auth/logout")
async def logout(user_id: CurrentUser):
    await _audit(user_id,"auth.logout","user",user_id)
    return {"ok":True}


@router.get("/api/v2/auth/me")
async def me(user_id: CurrentUser, db: DataServiceClient=Depends(get_data_service)):
    rows = await db.query("user_profile", {"user_id": user_id})
    if not rows or rows[0].get("active") is not True:
        # A valid JWT can outlive its account (for example after a database
        # restore). Signal an expired session so clients discard that token.
        raise HTTPException(401, "Session is no longer valid; sign in again")
    u = rows[0]; roles=await _role_ids(db,user_id); perms=await _permissions(db,user_id)
    return {**u,"roles":roles,"permissions":sorted(perms),"avatar_url":f"/api/v2/users/{user_id}/avatar" if u.get("avatar_path") else None}


@router.get("/api/v2/users/{user_id}/avatar")
async def avatar(user_id: str, actor: CurrentUser, db: DataServiceClient=Depends(get_data_service)):
    if actor != user_id:
        await _require(db, actor, "users.view")
    rows=await db.query("user_avatar_path", {"user_id": user_id})
    if not rows or not rows[0].get("avatar_path"): raise HTTPException(404,"avatar not found")
    p=Path(str(rows[0]["avatar_path"]))
    if not p.exists(): raise HTTPException(404,"avatar file missing")
    return FileResponse(p)


@router.get("/api/admin/users")
async def list_users(actor: CurrentUser, db: DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,"users.view")
    rows=await db.query("users_list")
    for u in rows: u["avatar_url"] = f"/api/v2/users/{u['user_id']}/avatar" if u.get("avatar_path") else None; u.pop("avatar_path",None)
    return {"users":rows}


@router.post("/api/admin/users")
async def create_user(payload: UserCreate, actor: CurrentUser, db: DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,"users.create")
    exists=await db.query("user_exists", {"username": payload.username})
    if exists: raise HTTPException(409,"username already exists")
    role=await db.query("role_exists", {"role_id": payload.role_id})
    if not role: raise HTTPException(422,"unknown role")
    now=datetime.now(UTC)
    # D10-c: UNIQUE(username) survives soft delete. A tombstoned username would
    # make INSERT OR IGNORE silently skip the new row (HTTP 200, nothing stored)
    # and the role write would then fail with "unknown reference". Resurrect the
    # tombstoned row in place (same user_id — audit trail stays coherent).
    tomb=await db.query("user_tombstone_by_username", {"username": payload.username})
    if tomb:
        uid=str(tomb[0]["user_id"])
        await _post_data("app_users",{"user_id":uid,"username":payload.username.strip().lower(),"full_name":payload.full_name,"email":payload.email,"password_hash":_hash_password(payload.password),"avatar_path":_save_avatar(uid,payload.avatar_data_url),"language":payload.language,"timezone":payload.timezone,"active":payload.active,"deleted":False,"updated_at":now})
    else:
        uid=uuid.uuid4().hex
        await _post_data("app_users",{"user_id":uid,"username":payload.username.strip().lower(),"full_name":payload.full_name,"email":payload.email,"password_hash":_hash_password(payload.password),"avatar_path":_save_avatar(uid,payload.avatar_data_url),"language":payload.language,"timezone":payload.timezone,"active":payload.active,"deleted":False,"created_at":now,"updated_at":now})
    try:
        await _post_data("app_user_roles",{"user_id":uid,"role_id":payload.role_id,"primary_role":True,"active":True,"created_at":now,"updated_at":now})
    except Exception:
        # D10-b: never leave a half-created user (no role row) behind — roll the
        # identity row back best-effort (upsert keys on username), then propagate.
        try:
            await _post_data("app_users",{"user_id":uid,"username":payload.username.strip().lower(),"deleted":True,"active":False,"updated_at":datetime.now(UTC)})
        except Exception:
            pass
        raise
    await _audit(actor,"users.create","user",uid,{"role_id":payload.role_id})
    return {"ok":True,"user_id":uid}


@router.put("/api/admin/users/{target_id}")
async def update_user(target_id: str, payload: UserUpdate, actor: CurrentUser, db: DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,"users.edit")
    rows=await db.query("user_by_id", {"user_id": target_id})
    if not rows: raise HTTPException(404,"user not found")
    u=rows[0]; changes=payload.model_dump(exclude_none=True); role_id=changes.pop("role_id",None); avatar_data=changes.pop("avatar_data_url",None)
    # Authorize every requested operation before any persistent side effect.
    if role_id:
        await _require(db,actor,"roles.manage")
        role = await db.query("role_exists", {"role_id": role_id})
        if not role:
            raise HTTPException(422, "unknown role")
    if changes.get("active") is False:
        await _require(db, actor, "users.disable")
    if actor==target_id and changes.get("active") is False: raise HTTPException(409,"cannot disable current account")
    if avatar_data: changes["avatar_path"]=_save_avatar(target_id,avatar_data)
    await _post_data("app_users",{**u,**changes,"updated_at":datetime.now(UTC)})
    if role_id:
        old=await db.query("user_active_roles", {"user_id": target_id})
        for r in old:
            # Upsert existing as non-primary; historical row remains auditable.
            await _post_data("app_user_roles",{"user_id":target_id,"role_id":r["role_id"],"primary_role":False,"active":False,"updated_at":datetime.now(UTC)})
        await _post_data("app_user_roles",{"user_id":target_id,"role_id":role_id,"primary_role":True,"active":True,"updated_at":datetime.now(UTC)})
    await _audit(actor,"users.edit","user",target_id,{"fields":sorted(changes),"role_id":role_id})
    return {"ok":True}


@router.post("/api/admin/users/{target_id}/reset-password")
async def reset_password(target_id: str,payload:PasswordReset,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,"users.edit")
    rows=await db.query("user_by_id", {"user_id": target_id})
    if not rows: raise HTTPException(404,"user not found")
    await _post_data("app_users",{**rows[0],"password_hash":_hash_password(payload.password),"updated_at":datetime.now(UTC)})
    await _audit(actor,"users.reset_password","user",target_id)
    return {"ok":True}


@router.delete("/api/admin/users/{target_id}")
async def delete_user(target_id:str,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,"users.delete")
    if actor==target_id: raise HTTPException(409,"cannot delete current account")
    rows=await db.query("user_by_id", {"user_id": target_id})
    if not rows: raise HTTPException(404,"user not found")
    await _post_data("app_users",{**rows[0],"active":False,"deleted":True,"updated_at":datetime.now(UTC)})
    await _audit(actor,"users.delete","user",target_id)
    return {"ok":True}


@router.get("/api/admin/roles")
async def roles(actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,"roles.view")
    rs=await db.query("roles_list")
    for r in rs:
        ps=await db.query("role_permissions", {"role_id": r["role_id"]}); r["permissions"]=[x["permission_code"] for x in ps]
    return {"roles":rs,"available_permissions":PERMISSIONS}


@router.put("/api/admin/roles/{role_id}/permissions")
async def update_role_permissions(role_id:str,payload:RolePermissionsIn,actor:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,"roles.manage")
    if role_id=="super_admin": raise HTTPException(409,"super_admin permissions are locked")
    role = await db.query("role_exists", {"role_id": role_id})
    if not role: raise HTTPException(404,"role not found")
    bad=[p for p in payload.permissions if p not in PERMISSIONS]
    if bad: raise HTTPException(422,f"unknown permissions: {bad}")
    existing=await db.query("role_permission_codes", {"role_id": role_id})
    for p in existing: await _post_data("app_role_permissions",{"role_id":role_id,"permission_code":p["permission_code"],"allowed":False,"updated_at":datetime.now(UTC)})
    for p in payload.permissions: await _post_data("app_role_permissions",{"role_id":role_id,"permission_code":p,"allowed":True,"updated_at":datetime.now(UTC)})
    await _audit(actor,"roles.permissions","role",role_id,{"permissions":payload.permissions})
    return {"ok":True}


@router.get("/api/user/notification-preferences")
async def get_prefs(user_id:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    rows=await db.query("notification_preferences", {"user_id": user_id})
    if not rows: return NotificationPreferencesIn().model_dump()
    r=rows[0]
    for src,dst in (("assets_json","assets"),("domains_json","domains"),("tts_levels_json","tts_levels")):
        try:r[dst]=json.loads(r.pop(src) or "[]")
        except Exception:r[dst]=[]
    r.pop("user_id",None); r.pop("updated_at",None)
    return r


@router.put("/api/user/notification-preferences")
async def put_prefs(payload:NotificationPreferencesIn,user_id:CurrentUser,db:DataServiceClient=Depends(get_data_service)):
    await _require(db,user_id,"alerts.configure_self")
    d=payload.model_dump(); d.update({"user_id":user_id,"assets_json":json.dumps(d.pop("assets")),"domains_json":json.dumps(d.pop("domains")),"tts_levels_json":json.dumps(d.pop("tts_levels")),"updated_at":datetime.now(UTC)})
    await _post_data("user_notification_preferences",d); await _audit(user_id,"alerts.preferences","user",user_id)
    return {"ok":True,"preferences":payload.model_dump()}


@router.get("/api/admin/audit")
async def audit(actor:CurrentUser, limit:int=100, db:DataServiceClient=Depends(get_data_service)):
    await _require(db,actor,"audit.view")
    rows=await db.query("audit_entries", {"limit": max(1,min(limit,500))})
    return {"items":rows}
