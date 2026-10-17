from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from openai import OpenAI
from sqlalchemy import desc, select, text, update
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.engine import URL, make_url

from app.database import data_sources, get_engine
from app.schemas import DataSourceInput, DataSourceTestRequest
from app.settings import settings


class SourceConfigError(ValueError):
    pass


def _cipher() -> Fernet:
    if not settings.APP_ENCRYPTION_KEY:
        raise RuntimeError("未配置 APP_ENCRYPTION_KEY，暂不能安全保存服务凭据")
    try:
        return Fernet(settings.APP_ENCRYPTION_KEY.encode())
    except Exception as exc:
        raise RuntimeError("APP_ENCRYPTION_KEY 格式无效") from exc


def _encrypted(secrets: dict[str, Any]) -> str:
    if not secrets:
        return ""
    return _cipher().encrypt(json.dumps(secrets, ensure_ascii=False).encode()).decode()


def _decrypt(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        return json.loads(_cipher().decrypt(value.encode()))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("凭据无法解密，请检查 APP_ENCRYPTION_KEY 是否与原部署一致") from exc


def _public(row: Any) -> dict[str, Any]:
    result = dict(row)
    result["config"] = result.get("config") or {}
    has_secret = bool(result.pop("encrypted_secrets", ""))
    result["secrets_configured"] = has_secret
    config = result["config"]
    result["configured"] = (has_secret and bool(config.get("host") and config.get("database"))) if result["kind"] == "database" else (has_secret and bool(config.get("base_url") and config.get("model_name"))) if result["kind"] == "model" else bool(config.get("url") and config.get("workspace"))
    result["is_default"] = bool(result.get("is_default"))
    result["enabled"] = bool(result.get("enabled"))
    return result


def list_sources() -> list[dict[str, Any]]:
    engine = get_engine()
    with engine.connect() as connection:
        rows = connection.execute(select(data_sources).order_by(desc(data_sources.c.is_default), data_sources.c.kind, data_sources.c.name)).mappings().all()
    return [_public(row) for row in rows]


def get_source(source_id: str) -> dict[str, Any] | None:
    engine = get_engine()
    with engine.connect() as connection:
        row = connection.execute(select(data_sources).where(data_sources.c.id == source_id)).mappings().first()
    return _public(row) if row else None


def _stored_secrets(source_id: str | None) -> dict[str, Any]:
    if not source_id:
        return {}
    engine = get_engine()
    with engine.connect() as connection:
        encrypted = connection.execute(select(data_sources.c.encrypted_secrets).where(data_sources.c.id == source_id)).scalar_one_or_none()
    return _decrypt(encrypted)


def configured_database_source() -> tuple[dict[str, Any], Any]:
    """Open the enabled default database source saved in the local app store."""
    from sqlalchemy import create_engine

    source = next((item for item in list_sources() if item["kind"] == "database" and item["enabled"] and item["is_default"]), None)
    if not source:
        raise SourceConfigError("请先在数据源管理中启用并设为默认数据库连接")
    secrets = _stored_secrets(source["id"])
    request = DataSourceTestRequest(
        name=source["name"], kind="database", provider=source["provider"],
        config=source["config"], source_id=source["id"],
    )
    try:
        engine = create_engine(
            _db_url(request, secrets), pool_pre_ping=True,
            connect_args={"connect_timeout": 8} if source["provider"] == "postgresql" else {},
        )
    except (ValueError, RuntimeError) as exc:
        raise SourceConfigError(str(exc)) from None
    return source, engine


def save_source(payload: DataSourceInput, source_id: str | None = None) -> dict[str, Any]:
    engine = get_engine()
    now = datetime.now(timezone.utc)
    existing = None
    if source_id:
        with engine.connect() as connection:
            existing = connection.execute(select(data_sources).where(data_sources.c.id == source_id)).mappings().first()
        if not existing:
            raise KeyError("数据源配置不存在")
    merged_secrets = _decrypt(existing["encrypted_secrets"]) if existing else {}
    merged_secrets.update({k: v for k, v in payload.secrets.items() if v not in (None, "")})
    encrypted = _encrypted(merged_secrets)
    values = {
        "name": payload.name.strip(), "kind": payload.kind, "provider": payload.provider,
        "config": payload.config, "encrypted_secrets": encrypted, "is_default": int(payload.is_default),
        "enabled": int(payload.enabled), "updated_at": now,
    }
    with engine.begin() as connection:
        if payload.is_default:
            connection.execute(update(data_sources).where(data_sources.c.kind == payload.kind).values(is_default=0))
        if existing:
            connection.execute(data_sources.update().where(data_sources.c.id == source_id).values(**values))
        else:
            source_id = str(uuid.uuid4())
            values["id"] = source_id
            values["created_at"] = now
            connection.execute(data_sources.insert().values(**values))
    return get_source(source_id)


def seed_environment_sources() -> None:
    """Import current .env integrations once as editable local SQLite records."""
    engine = get_engine()
    with engine.connect() as connection:
        existing = connection.execute(select(data_sources.c.id)).first()
    if existing:
        return
    seeds: list[tuple[DataSourceInput, str]] = []
    if settings.DATABASE_URL:
        try:
            url = make_url(settings.DATABASE_URL)
            provider = "oracle" if url.drivername.startswith("oracle") else "postgresql"
            config = {"host": url.host or "", "port": url.port or (1521 if provider == "oracle" else 5432), "database": url.database or "", "schema": "minsheng", "username": url.username or "", "table": "民生民情信息", "content_column": "核心线索"}
            if provider == "oracle":
                config["service_name"] = url.query.get("service_name", url.database or "")
            secrets = {"password": url.password or ""}
            seeds.append((DataSourceInput(name="民生诉求库", kind="database", provider=provider, config=config, secrets=secrets, is_default=True), "env-postgres"))
        except Exception:
            pass
    if settings.DEEPSEEK_API_KEY:
        seeds.append((DataSourceInput(name="DeepSeek", kind="model", provider="deepseek", config={"base_url": settings.DEEPSEEK_BASE_URL, "model_name": settings.DEEPSEEK_MODEL}, secrets={"api_key": settings.DEEPSEEK_API_KEY}, is_default=True), "env-deepseek"))
    if settings.GEOSERVER_URL:
        seeds.append((DataSourceInput(name="GeoServer", kind="map", provider="geoserver", config={"url": settings.GEOSERVER_URL, "workspace": "minsheng", "store": "minsheng", "username": settings.GEOSERVER_USER, "layer_prefix": "appeal_", "srs": "EPSG:4490"}, secrets={"password": settings.GEOSERVER_PASSWORD}, is_default=True), "env-geoserver"))
    for payload, _ in seeds:
        save_source(payload)


def _db_url(request: DataSourceTestRequest, secrets: dict[str, Any]) -> URL:
    config = request.config
    user = config.get("username") or ""
    password = secrets.get("password") or ""
    host = config.get("host") or ""
    port = int(config.get("port") or (1521 if request.provider == "oracle" else 5432))
    database = config.get("service_name") or config.get("database") or ""
    if not all((user, password, host, database)):
        raise SourceConfigError("请填写主机、数据库/服务名、用户名和密码")
    if request.provider == "postgresql":
        return URL.create("postgresql+psycopg", username=user, password=password, host=host, port=port, database=database)
    if request.provider == "oracle":
        return URL.create("oracle+oracledb", username=user, password=password, host=host, port=port, query={"service_name": database})
    raise SourceConfigError("暂不支持该数据库类型")


def test_database(request: DataSourceTestRequest, secrets: dict[str, Any]) -> dict[str, Any]:
    from sqlalchemy import create_engine
    query = (request.query or "").strip()
    if not re.match(r"^(select|with)\b", query, re.IGNORECASE) or ";" in query:
        raise SourceConfigError("验证查询只允许单条 SELECT / WITH 查询，且不能包含分号")
    engine = create_engine(_db_url(request, secrets), pool_pre_ping=True, connect_args={"connect_timeout": 8} if request.provider == "postgresql" else {})
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            try:
                result = connection.execute(text(query))
            except ProgrammingError:
                raise SourceConfigError("数据库连接成功，但查询执行失败；请检查 SQL 语法、Schema、表名和字段名") from None
            columns = list(result.keys())
            rows = [dict(row._mapping) for row in result.fetchmany(5)]
            return {"ok": True, "message": "连接成功，查询已执行", "columns": columns, "rows": rows, "row_count": len(rows)}
    except OperationalError:
        raise SourceConfigError("无法连接数据库；请检查主机、端口、数据库名、用户名密码及容器网络") from None
    finally:
        engine.dispose()


def test_model(request: DataSourceTestRequest, secrets: dict[str, Any]) -> dict[str, Any]:
    api_key = secrets.get("api_key")
    if not api_key:
        raise SourceConfigError("请先输入 API Key，或保存密钥后再测试")
    client = OpenAI(api_key=api_key, base_url=(request.config.get("base_url") or "").rstrip("/"), timeout=20, max_retries=0)
    # Reasoning models may spend a substantial part of the output budget on
    # reasoning_content before producing message.content. 120 tokens can
    # therefore yield HTTP 200 with an empty user-facing answer.
    response = client.chat.completions.create(
        model=request.config.get("model_name") or "",
        messages=[{"role": "user", "content": request.prompt or "你是什么模型？请用一句话回答。"}],
        max_tokens=2048,
        temperature=0.2,
    )
    choice = response.choices[0]
    content = choice.message.content or ""
    if not content.strip():
        if choice.finish_reason == "length":
            raise SourceConfigError("模型思考内容占用了输出额度，回答被截断；请重试或检查模型输出长度设置")
        raise SourceConfigError("模型接口已连接，但没有返回可展示的回答内容")
    return {"ok": True, "message": content, "model": response.model, "usage": response.usage.total_tokens if response.usage else None}


def test_map(request: DataSourceTestRequest, secrets: dict[str, Any]) -> dict[str, Any]:
    url = (request.config.get("url") or "").rstrip("/")
    workspace = request.config.get("workspace") or ""
    if not url or not workspace:
        raise SourceConfigError("请填写 GeoServer 地址和工作区名称")
    auth = (request.config.get("username") or secrets.get("username") or "", secrets.get("password") or "")
    rest_url = f"{url}/rest"
    headers = {"Accept": "application/json"}
    try:
        with httpx.Client(auth=auth if any(auth) else None, headers=headers, timeout=8) as client:
            workspace_response = client.get(f"{rest_url}/workspaces/{quote(workspace, safe='')}.json")
            if workspace_response.status_code == 401:
                raise SourceConfigError("GeoServer 身份验证失败，请检查账号和密码")
            if workspace_response.status_code == 404:
                raise SourceConfigError(f"GeoServer 可连接，但未找到工作区“{workspace}”")
            workspace_response.raise_for_status()

            workspace_layers_response = client.get(f"{rest_url}/workspaces/{quote(workspace, safe='')}/layers.json")
            workspace_layers_response.raise_for_status()
            workspace_layer_container = workspace_layers_response.json().get("layers", {})
            workspace_data = workspace_layer_container.get("layer", []) if isinstance(workspace_layer_container, dict) else []
            if isinstance(workspace_data, dict):
                workspace_data = [workspace_data]
            workspace_names = {item.get("name", "") for item in workspace_data if isinstance(item, dict)}

            all_layers_response = client.get(f"{rest_url}/layers.json")
            all_layers_response.raise_for_status()
            all_layer_container = all_layers_response.json().get("layers", {})
            all_layer_data = all_layer_container.get("layer", []) if isinstance(all_layer_container, dict) else []
            if isinstance(all_layer_data, dict):
                all_layer_data = [all_layer_data]

            layers = []
            origin = urlsplit(rest_url).netloc
            for item in all_layer_data:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                qualified_name = str(item["name"])
                layer_detail = client.get(f"{rest_url}/layers/{quote(qualified_name, safe='')}.json")
                layer_json = layer_detail.json().get("layer", {}) if layer_detail.is_success else {}
                resource = layer_json.get("resource") or {}
                resource_href = resource.get("href") if isinstance(resource, dict) else None
                title = qualified_name.split(":", 1)[-1]
                if resource_href:
                    parsed_href = urlsplit(resource_href)
                    if parsed_href.netloc == origin and parsed_href.path.startswith(urlsplit(rest_url).path):
                        resource_response = client.get(resource_href)
                        if resource_response.is_success:
                            resource_type = "coverage" if "coverage" in resource_response.json() else "featureType"
                            resource_info = resource_response.json().get(resource_type, {})
                            title = resource_info.get("title") or title
                layer_workspace = qualified_name.split(":", 1)[0] if ":" in qualified_name else ""
                layers.append({
                    "name": qualified_name,
                    "native_name": qualified_name.split(":", 1)[-1],
                    "workspace": layer_workspace,
                    "title": title,
                    "type": layer_json.get("type", ""),
                    "in_workspace": qualified_name in workspace_names or layer_workspace == workspace,
                })
    except SourceConfigError:
        raise
    except httpx.HTTPStatusError as exc:
        raise SourceConfigError(f"GeoServer 返回 HTTP {exc.response.status_code}，请检查服务地址和 REST 访问权限") from None
    except (httpx.RequestError, ValueError, KeyError):
        raise SourceConfigError("无法读取 GeoServer 图层信息；请检查容器网络、REST API 地址和账号权限") from None

    workspace_layer_count = sum(1 for layer in layers if layer["in_workspace"])
    return {
        "ok": True,
        "message": f"GeoServer 连接成功，工作区“{workspace}”可访问；该工作区 {workspace_layer_count} 个图层，服务共 {len(layers)} 个图层",
        "workspace": workspace,
        "workspace_layer_count": workspace_layer_count,
        "layer_count": len(layers),
        "layers": layers,
    }


def test_source(request: DataSourceTestRequest) -> dict[str, Any]:
    secrets = _stored_secrets(request.source_id)
    secrets.update({k: v for k, v in request.secrets.items() if v not in (None, "")})
    if request.kind == "database":
        return test_database(request, secrets)
    if request.kind == "model":
        return test_model(request, secrets)
    if request.kind == "map":
        return test_map(request, secrets)
    raise SourceConfigError("未知服务类型")


def proxy_geoserver_request(workspace: str, service: str, params: list[tuple[str, str]]) -> httpx.Response:
    """Proxy read-only WMS/WFS requests through the configured GeoServer connection."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", workspace):
        raise SourceConfigError("工作区名称格式无效")
    service = service.lower()
    if service not in {"wms", "ows"}:
        raise SourceConfigError("只允许读取 GeoServer WMS / OWS 服务")

    allowed_params = {
        "service", "version", "request", "layers", "query_layers", "styles", "format",
        "transparent", "width", "height", "srs", "crs", "bbox", "info_format",
        "feature_count", "typename", "typenames", "outputformat", "maxfeatures",
        "startindex", "sortby", "propertyname", "cql_filter", "filter", "exceptions",
        "srsname", "count", "format_options", "time", "elevation",
    }
    safe_params = [(key, value) for key, value in params if key.lower() in allowed_params]
    request_name = next((value.lower() for key, value in safe_params if key.lower() == "request"), "")
    if request_name not in {"getmap", "getfeatureinfo", "getcapabilities", "getfeature", "describefeaturetype"}:
        raise SourceConfigError("此地图代理仅允许读取地图、图层信息和要素查询请求")

    candidates = [source for source in list_sources() if source.get("kind") == "map" and source.get("enabled")]
    source = next((item for item in candidates if item.get("is_default")), candidates[0] if candidates else None)
    if not source:
        raise SourceConfigError("请先在数据源管理中配置 GeoServer")
    config = source.get("config") or {}
    raw_url = str(config.get("url") or "").strip().rstrip("/")
    parsed = urlsplit(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SourceConfigError("GeoServer 地址无效，请检查数据源配置")
    base_path = parsed.path.rstrip("/")
    for suffix in (f"/{workspace}/wms", f"/{workspace}/ows", f"/{workspace}/wfs", "/wms", "/ows", "/wfs"):
        if base_path.lower().endswith(suffix.lower()):
            base_path = base_path[:-len(suffix)].rstrip("/")
            break
    base_url = f"{parsed.scheme}://{parsed.netloc}{base_path}"
    target_url = f"{base_url}/{workspace}/{service}"
    secrets = _stored_secrets(str(source["id"]))
    username = str(config.get("username") or secrets.get("username") or "")
    password = str(secrets.get("password") or "")
    auth = (username, password) if username and password else None
    try:
        response = httpx.get(target_url, params=safe_params, auth=auth, timeout=30.0, follow_redirects=False)
    except httpx.HTTPError:
        raise SourceConfigError("无法连接 GeoServer，请检查服务状态和容器网络") from None
    return response
