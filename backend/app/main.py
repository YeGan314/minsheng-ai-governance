from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.config_service import (
    create_or_update_draft,
    get_draft,
    list_drafts,
    list_versions,
    publish_draft,
    rename_draft,
    run_sample_preview,
    validate_config,
    validate_draft,
)
from app.data_sources import get_intake_profile
from app.source_service import SourceConfigError, list_sources, proxy_geoserver_request, save_source, seed_environment_sources, test_source
from app.database import (get_engine, governance_configs, governance_config_revisions, governance_profiles,
                          governance_profile_versions, initialize_database)
from sqlalchemy import desc, func, select
from datetime import datetime, timezone
import uuid
from app.schemas import AssistantTurnRequest, AssistantTurnResponse, DataSourceInput, DataSourceTestRequest, DraftResponse, DraftTitleRequest, PublishRequest
from app.settings import settings

logger = logging.getLogger("minsheng_governance")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    seed_environment_sources()
    yield


app = FastAPI(
    title="民生民情诉求数据治理服务",
    version="0.2.0",
    description="局域网部署的诉求信息语义结构化、分类和空间标引服务。",
    lifespan=lifespan,
)

GOVERNANCE_SECTIONS = {
    "categories", "fields", "extraction", "spatial", "quality",
}


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.APP_ENV}


@app.get("/api/v1/system/info", tags=["system"])
def system_info() -> dict[str, object]:
    return {
        "model_provider": "openai-compatible",
        "model_name": settings.DEEPSEEK_MODEL,
        "model_key_configured": bool(settings.DEEPSEEK_API_KEY),
        "database_configured": bool(settings.DATABASE_URL),
        "sqlite_configured": True,
        "geoserver_configured": bool(settings.GEOSERVER_URL),
    }


@app.get("/api/v1/governance/config/{section}", tags=["governance-config"])
def read_governance_config(section: str):
    if section not in GOVERNANCE_SECTIONS:
        raise HTTPException(status_code=404, detail="治理配置模块不存在")
    with get_engine().connect() as connection:
        row = connection.execute(select(governance_configs).where(governance_configs.c.section == section)).mappings().first()
    return dict(row) if row else {"section": section, "revision": 0, "config": {}}


@app.put("/api/v1/governance/config/{section}", tags=["governance-config"])
def write_governance_config(section: str, payload: dict):
    if section not in GOVERNANCE_SECTIONS:
        raise HTTPException(status_code=404, detail="治理配置模块不存在")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="配置内容必须为对象")
    engine = get_engine()
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        row = connection.execute(select(governance_configs.c.revision).where(governance_configs.c.section == section)).first()
        revision = (row[0] if row else 0) + 1
        values = {"revision": revision, "config": payload, "updated_at": now}
        if row:
            connection.execute(governance_configs.update().where(governance_configs.c.section == section).values(**values))
        else:
            connection.execute(governance_configs.insert().values(section=section, **values))
        connection.execute(governance_config_revisions.insert().values(section=section, revision=revision, config=payload, created_at=now))
    return {"section": section, "revision": revision, "config": payload, "updated_at": now}


@app.get("/api/v1/governance/config/{section}/revisions", tags=["governance-config"])
def list_governance_config_revisions(section: str):
    if section not in GOVERNANCE_SECTIONS:
        raise HTTPException(status_code=404, detail="治理配置模块不存在")
    with get_engine().connect() as connection:
        rows = connection.execute(select(governance_config_revisions).where(
            governance_config_revisions.c.section == section
        ).order_by(desc(governance_config_revisions.c.revision))).mappings().all()
    return [dict(row) for row in rows]


@app.get("/api/v1/governance/profiles", tags=["governance-config"])
def list_governance_profiles():
    engine = get_engine()
    with engine.connect() as connection:
        rows = connection.execute(select(governance_profiles).order_by(desc(governance_profiles.c.updated_at))).mappings().all()
        output = []
        for row in rows:
            latest = connection.execute(select(governance_profile_versions).where(
                governance_profile_versions.c.profile_id == row["id"]
            ).order_by(desc(governance_profile_versions.c.id)).limit(1)).mappings().first()
            output.append({**dict(row), "latest_version": dict(latest) if latest else None})
    return output


@app.post("/api/v1/governance/profiles", tags=["governance-config"])
def save_governance_profile(payload: dict):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="请填写治理方案名称")
    profile_id = str(payload.get("id") or uuid.uuid4())
    description = str(payload.get("description") or "")[:2000]
    profile_settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    now = datetime.now(timezone.utc)
    engine = get_engine()
    with engine.begin() as connection:
        exists = connection.execute(select(governance_profiles.c.id).where(governance_profiles.c.id == profile_id)).first()
        values = {"name": name, "description": description, "settings": profile_settings, "status": "draft", "updated_at": now}
        if exists:
            connection.execute(governance_profiles.update().where(governance_profiles.c.id == profile_id).values(**values))
        else:
            connection.execute(governance_profiles.insert().values(id=profile_id, created_at=now, **values))
        row = connection.execute(select(governance_profiles).where(governance_profiles.c.id == profile_id)).mappings().one()
    return dict(row)


@app.post("/api/v1/governance/profiles/{profile_id}/publish", tags=["governance-config"])
def publish_governance_profile(profile_id: str, payload: dict):
    publisher = str(payload.get("publisher") or "管理员")[:100]
    engine = get_engine()
    with engine.begin() as connection:
        profile = connection.execute(select(governance_profiles).where(governance_profiles.c.id == profile_id)).mappings().first()
        if not profile:
            raise HTTPException(status_code=404, detail="治理方案不存在")
        previous = connection.execute(select(func.count()).select_from(governance_profile_versions).where(
            governance_profile_versions.c.profile_id == profile_id
        )).scalar_one()
        version = f"v1.{previous + 1}"
        profile_settings = profile["settings"] or {}
        included = profile_settings.get("sections") or list(GOVERNANCE_SECTIONS)
        selected_revisions = profile_settings.get("revisions") or {}
        snapshot = {}
        for section in included:
            selected_revision = selected_revisions.get(section)
            query = select(governance_config_revisions).where(governance_config_revisions.c.section == section)
            if selected_revision:
                query = query.where(governance_config_revisions.c.revision == int(selected_revision))
            else:
                query = query.order_by(desc(governance_config_revisions.c.revision))
            rule_revision = connection.execute(query.limit(1)).mappings().first()
            if rule_revision:
                snapshot[section] = {"revision": rule_revision["revision"], "config": rule_revision["config"]}
        snapshot["profile"] = {"id": profile_id, "name": profile["name"], "description": profile["description"], "settings": profile["settings"]}
        now = datetime.now(timezone.utc)
        connection.execute(governance_profile_versions.insert().values(
            profile_id=profile_id, version=version, snapshot=snapshot, publisher=publisher, published_at=now
        ))
        connection.execute(governance_profiles.update().where(governance_profiles.c.id == profile_id).values(status="published", updated_at=now))
        row = connection.execute(select(governance_profile_versions).where(
            governance_profile_versions.c.profile_id == profile_id
        ).order_by(desc(governance_profile_versions.c.id)).limit(1)).mappings().one()
    return dict(row)


@app.get("/api/v1/governance/profile-versions", tags=["governance-config"])
def list_governance_profile_versions(limit: int = Query(default=50, ge=1, le=200)):
    with get_engine().connect() as connection:
        rows = connection.execute(select(governance_profile_versions, governance_profiles.c.name.label("profile_name"))
            .join(governance_profiles, governance_profiles.c.id == governance_profile_versions.c.profile_id)
            .order_by(desc(governance_profile_versions.c.id)).limit(limit)).mappings().all()
    return [dict(row) for row in rows]


@app.get("/api/v1/data-sources", tags=["data-sources"])
def data_source_configs():
    return list_sources()


@app.post("/api/v1/data-sources", tags=["data-sources"])
def create_data_source(request: DataSourceInput):
    try:
        return save_source(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except SQLAlchemyError:
        logger.exception("Could not save data source configuration")
        raise HTTPException(status_code=503, detail="无法保存数据源配置") from None


@app.put("/api/v1/data-sources/{source_id}", tags=["data-sources"])
def update_data_source(source_id: str, request: DataSourceInput):
    try:
        return save_source(request, source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except SQLAlchemyError:
        logger.exception("Could not update data source configuration")
        raise HTTPException(status_code=503, detail="无法更新数据源配置") from None


@app.post("/api/v1/data-sources/test", tags=["data-sources"])
def test_data_source(request: DataSourceTestRequest):
    try:
        return test_source(request)
    except SourceConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except Exception as exc:
        logger.exception("Data source test failed (%s)", request.kind)
        raise HTTPException(status_code=502, detail="服务测试失败，请检查地址、凭据、权限或服务状态") from None


@app.get("/api/v1/maps/geoserver/{workspace}/{service}", tags=["maps"])
def geoserver_proxy(workspace: str, service: str, request: Request):
    try:
        upstream = proxy_geoserver_request(workspace, service, list(request.query_params.multi_items()))
    except SourceConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=60"},
    )


@app.get("/api/v1/maps/tianditu/client-config", tags=["maps"])
def tianditu_client_config():
    """Provide a browser-scoped key to the map client; browser requests require a browser-type TK."""
    tk = settings.TIANDITU_TK.strip()
    if not tk:
        raise HTTPException(status_code=503, detail="尚未配置天地图 TK")
    return JSONResponse({"tk": tk}, headers={"Cache-Control": "no-store"})


@app.get("/api/v1/datasets/intake/profile", tags=["datasets"])
def intake_profile() -> dict[str, object]:
    try:
        return get_intake_profile()
    except SQLAlchemyError:
        logger.exception("Could not read source dataset profile")
        raise HTTPException(status_code=503, detail="无法读取接诉即办数据集元信息") from None


@app.get("/api/v1/config-drafts", response_model=list[DraftResponse], tags=["configuration"])
def drafts(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return list_drafts(limit)
    except SQLAlchemyError:
        logger.exception("Could not list configuration drafts")
        raise HTTPException(status_code=503, detail="无法读取配置草稿") from None


@app.get("/api/v1/config-drafts/{draft_id}", response_model=DraftResponse, tags=["configuration"])
def draft(draft_id: str):
    try:
        result = get_draft(draft_id)
    except SQLAlchemyError:
        logger.exception("Could not read configuration draft")
        raise HTTPException(status_code=503, detail="无法读取配置草稿") from None
    if not result:
        raise HTTPException(status_code=404, detail="配置草稿不存在")
    return result


@app.patch("/api/v1/config-drafts/{draft_id}/title", response_model=DraftResponse, tags=["configuration"])
def update_draft_title(draft_id: str, request: DraftTitleRequest):
    try:
        return rename_draft(draft_id, request.title)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        logger.exception("Could not rename configuration conversation")
        raise HTTPException(status_code=503, detail="无法保存对话标题") from None


@app.post("/api/v1/config-assistant/messages", response_model=AssistantTurnResponse, tags=["configuration"])
def assistant_turn(request: AssistantTurnRequest):
    try:
        return create_or_update_draft(request.message, request.draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except SQLAlchemyError:
        logger.exception("Could not save configuration assistant turn")
        raise HTTPException(status_code=503, detail="无法保存配置草稿") from None
    except Exception:
        logger.exception("Configuration assistant failed")
        raise HTTPException(status_code=502, detail="配置助手处理失败，请检查模型输出或稍后重试") from None


@app.post("/api/v1/config-drafts/{draft_id}/validate", response_model=DraftResponse, tags=["configuration"])
def validate_saved_draft(draft_id: str):
    try:
        return validate_draft(draft_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except SQLAlchemyError:
        logger.exception("Could not validate configuration draft")
        raise HTTPException(status_code=503, detail="无法保存校验结果") from None


@app.post("/api/v1/config-drafts/{draft_id}/sample-run", tags=["configuration"])
def sample_run(draft_id: str, limit: int = Query(default=5, ge=1, le=5)):
    try:
        return run_sample_preview(draft_id, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except SQLAlchemyError:
        logger.exception("Could not persist sample preview")
        raise HTTPException(status_code=503, detail="无法保存样例试跑结果") from None


@app.post("/api/v1/config/validate", tags=["configuration"])
def validate_unsaved_config(config: dict):
    try:
        return validate_config(config)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"配置结构无效：{exc}") from None


@app.post("/api/v1/config-drafts/{draft_id}/publish", tags=["configuration"])
def publish_saved_draft(draft_id: str, request: PublishRequest):
    try:
        return publish_draft(draft_id, request.publisher)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except SQLAlchemyError:
        logger.exception("Could not publish configuration")
        raise HTTPException(status_code=503, detail="无法发布配置版本") from None


@app.get("/api/v1/config-versions", tags=["configuration"])
def versions(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return list_versions(limit)
    except SQLAlchemyError:
        logger.exception("Could not list configuration versions")
        raise HTTPException(status_code=503, detail="无法读取配置版本") from None


_frontend = Path(__file__).resolve().parents[2] / "frontend"
if _frontend.exists():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
