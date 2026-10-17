# 民生民情诉求数据治理系统（开发环境）

当前目录提供第一阶段环境骨架：FastAPI 服务、Celery 批处理 Worker、Redis 队列，并连接现有 `minsheng-postgis` 和 `minsheng-geoserver` 容器所在的 `minsheng_default` Docker 网络。不会自动写入现有数据库。`frontend/` 中包含治理总览、对话式配置、任务执行监管和成果展示的静态交互原型；交互数据尚未接入后端。

## Open WebUI 参考与集成方向

- 上游源码浅克隆在本地 `reference/open-webui/`（当前参考提交 `f8ae8a6`），该目录已加入 `.gitignore`，不会混入本项目代码提交。
- 原型借鉴其会话历史、消息流和底部输入区；后续建议让 Open WebUI 负责对话入口/模型选择，让本项目 FastAPI 负责配置草稿、校验、样例试跑、治理任务和审计。配置发布必须由用户在治理界面明确确认。
- 不把分类、PostGIS、批处理结果存进 Open WebUI 的聊天存储；这些业务数据保留在本项目 PostgreSQL/PostGIS 中。通过 Docker Compose 编排服务，使用环境变量切换 DeepSeek 云端 API 与局域网 OpenAI 兼容模型端点。
- Open WebUI 当前版本有品牌保留条款及多版本代码许可说明。内部单次部署 5 人符合其文档所述 50 人内例外条件；若之后要将改品牌的派生版本对外分发或商业化，需重新核对完整许可及适用方式。

## 启动

1. 复制 `.env.example` 为 `.env`。
2. 在 `.env` 中填入 DeepSeek API Key 和 PostgreSQL 密码。不要把 `.env` 提交到版本库或发到聊天中。
3. 在本目录运行：

   ```bash
   docker compose up --build -d
   ```

4. 打开 `http://127.0.0.1:8000/docs` 查看 API，`/health` 是服务存活检查。

目前 API 仅提供环境状态接口；尚未实现工单读取、模型抽取、空间检索、复核页面或数据库写入。后续接入模型时应将 DeepSeek API Key 仅从环境变量读取，并让治理结果写入独立结果表。

## 当前配置

- DeepSeek API：`https://api.deepseek.com`，默认模型为当前官方文档列出的 `deepseek-v4-pro`；需要批处理速度/成本对比时可配置 `deepseek-flash`。
- PostgreSQL/PostGIS：`minsheng-postgis:5432/minsheng`。
- GeoServer：`http://minsheng-geoserver:8080/geoserver`。
- Redis：仅供治理服务内部使用，不映射到宿主机端口。
- API：当前仅绑定宿主机 `127.0.0.1:8000`，完成登录认证和权限控制后再开放局域网访问。


## 本地 SQLite 状态库

应用自身的配置草稿、发布版本、样例试跑和数据源连接现在保存在宿主机 `data/minsheng-governance.db`，通过 Docker bind mount 持久化。SQLite WAL 模式用于多读者访问；请让 API/Worker 在同一台宿主机访问该文件，不要放到 SMB/NFS 等网络共享目录。已有 PostgreSQL `governance` 配置表会在启动时尽力复制到 SQLite，原数据不会删除。

`DATABASE_URL` 是可选的外部数据源连接（导入/读取外部 PostgreSQL/PostGIS）；SQLite-only 部署可留空。Oracle 支持通过 `oracledb` thin driver 连接。`MINSHENG_NETWORK_EXTERNAL=false` 时 Compose 创建隔离网络；如果要复用包含现有 PostgreSQL/GeoServer 容器的 `minsheng_default` 网络，设置为 `true`。

数据源密码和模型 API Key 使用 `APP_ENCRYPTION_KEY` 加密后存入 SQLite。首次部署需生成并配置 Fernet key（例如运行 `python3 -c 'import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'`）；该密钥必须保持稳定并安全备份，丢失后已保存凭据无法解密。数据库目录限制为当前部署用户访问。不要提交 `.env`、数据库文件或密钥备份。`data/` 已加入 `.gitignore`。备份时使用 SQLite Online Backup API，或先停止容器再复制数据库及 WAL 文件。

数据源管理页的保存和连接测试已接入后端。PostgreSQL/Oracle 测试在只读事务中运行单条查询，DeepSeek/千问/MiMo 使用 OpenAI 兼容聊天接口进行连通性测试，GeoServer 检查工作区 REST 接口。
