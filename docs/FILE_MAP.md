# Maya Platform 文件地图

本文档解释当前仓库主要目录和关键文件的职责。它不替代 `Project.md` 的产品合同，也不替代 `docs/PROJECT_STATUS.md` 的进度与审计状态。

## 根目录

| 路径 | 作用 |
| --- | --- |
| `README.md` | 新成员入口：项目目标、安装、运行、Wave、测试和当前缺口。 |
| `Project.md` | 当前产品与工程权威说明。 |
| `AI文化互鉴教学平台-需求文档.md` | 原始业务需求历史副本；不能绕过 `Project.md` 直接实现。 |
| `AGENTS.md` | Sol、Luna 和其他开发 Agent 的工作规则。 |
| `UPLOAD_SCOPE.md` | 私有仓库允许和禁止保存的数据范围。 |
| `开发文档.xlsx` | Wave、模块、未审计范围和下一步的结构化共享状态表。 |
| `package.json` | JavaScript 工作区版本、依赖与统一脚本。 |
| `pnpm-lock.yaml` | 固定 JavaScript 依赖解析结果。 |
| `docker-compose.yml` | Caddy、Next.js、FastAPI 三容器拓扑。 |
| `.env.example` | 本地环境变量模板；真实 `.env` 不进入 Git。 |
| `.gitignore` | 排除环境文件、运行数据、个人输入、构建产物与缓存。 |
| `.prettierignore` | 排除生成文件、二进制与需保持原样的历史 Fixture。 |

## `.github/`

| 路径 | 作用 |
| --- | --- |
| `.github/workflows/quality.yml` | Wave 3 质量矩阵：仓库边界、格式/合同、前端、后端、迁移、Compose 与 Aggregate。 |

CI 固定使用 Mock Provider，不读取或调用真实模型服务。

## `backend/`

### 基础文件

| 路径 | 作用 |
| --- | --- |
| `backend/pyproject.toml` | Python 3.12 依赖，以及 Ruff、mypy、pytest 配置。 |
| `backend/uv.lock` | 固定 Python 依赖。 |
| `backend/Dockerfile` | FastAPI 后端容器构建。 |
| `backend/alembic.ini` | Alembic 配置。 |

### `backend/app/core/`

| 文件 | 作用 |
| --- | --- |
| `config.py` | 读取 Demo、Provider、路径与课堂 Origin 配置。 |
| `db.py` | SQLAlchemy Engine、Session 与 SQLite 生命周期。 |
| `models.py` | 共享 ORM 对象与跨模块关系。 |
| `errors.py` | 平台错误码与 HTTP 错误封装。 |
| `main.py` | FastAPI 组合根、路由注册、任务恢复与应用生命周期。 |

### `backend/app/modules/`

| 模块 | 作用 | 当前状态 |
| --- | --- | --- |
| `auth/` | 用户名/密码、Demo 快速登录、Session、CSRF。 | 历史基线；需最终回归。 |
| `org/` | 课程、小组和成员关系。 | 历史基线。 |
| `agents/` | Agent、草稿、版本、发布、描述和安全删除。 | Wave 1 历史通过。 |
| `knowledge/` | Markdown、分块、Mock 向量、RAG 与快照。 | Wave 1 历史通过；真实质量后置。 |
| `avatars/` | 3D 模板与 Avatar 配置。 | 历史 Mock 路径。 |
| `voices/` | VoiceProfile、上传校验、试听、删除和兜底。 | Mock 路径；真实 TTS 后置。 |
| `debates/setup/` | 创建/修改辩论，冻结参与者、顺序、立场和版本。 | Wave 2 历史通过。 |
| `debates/generation/` | 两轮计划、RAG、模型输出校验与观点更新。 | Wave 2 历史通过。 |
| `debates/playback/` | WebSocket、控制权、媒体票据、Pause/Resume、Finish、Next、Replay。 | 最新 Wave 3 增量未完成 Full 审计。 |
| `interactions/` | 匿名 Token、投票、弹幕、Open/Close、输入冻结。 | M13 已实现；未完成 Full G2。 |
| `reports/` | 匿名洞察、Maya 报告、Revision、引用与下载。 | M14 已实现；未完成 Full G2。 |
| `translations/` | 按需测试译文、缓存、Batch/Job 与历史投影。 | M15 已实现；存在 follower 活性 P1。 |

业务模块通常包含：

- `router.py`：FastAPI 路由；
- `schemas.py`：请求/响应 DTO；
- `models.py`：ORM；
- `service.py`：权威业务规则与事务；
- `policy.py`：可独立验证的确定性策略；
- `task_manager.py`：进程内后台任务（部分模块）。

### 迁移与测试

| 路径 | 作用 |
| --- | --- |
| `backend/migrations/versions/0001...0006...py` | Wave 0–2 与 pre-Wave 3 历史迁移；不得改写。 |
| `backend/migrations/versions/0007_wave3_interaction_report.py` | Wave 3 互动、洞察、报告、翻译与 typed Job。 |
| `backend/tests/` | 后端单元、集成、权限、状态机、恢复与迁移测试。 |

Wave 3 重点测试：

- `test_wave3_interactions.py`；
- `test_wave3_reports.py`；
- `test_wave3_translations.py`；
- `test_wave3_playback_controls.py`；
- `test_pw3_playback*.py`。

## `backend/config/`

| 路径 | 作用 |
| --- | --- |
| `demo-accounts/accounts.private.md` | 用户明确要求保留的 Demo 账号与密码目录。 |
| `demo_users.yaml` | 旧 Demo 账号兼容配置。 |

这是当前仓库仅有的两类凭据例外。普通 API、前端 Bundle、错误响应与日志不得返回密码。

## `frontend/`

### 应用路由

| 路径 | 作用 |
| --- | --- |
| `frontend/app/page.tsx` | 统一首页和登录入口。 |
| `frontend/app/student/**` | 学生 Agent、知识库、版本和音色工作区。 |
| `frontend/app/teacher/**` | 教师 Agent 检查、辩论列表、创建、播放、互动与报告。 |
| `frontend/app/classroom/[access_token]/page.tsx` | 免登录手机投票/弹幕入口。 |

### 组件

| 路径 | 作用 | 当前状态 |
| --- | --- | --- |
| `components/session-provider/` | Session、CSRF 和角色路由。 | 历史基线。 |
| `components/locale/` | 中英界面与翻译表。 | 历史基线。 |
| `components/avatar/` | 3D 预览与课堂 Avatar。 | 历史 Mock 验收。 |
| `components/debate/setup/` | 辩论草稿与参与者选择。 | Wave 2 历史通过。 |
| `components/debate/stage/` | 课堂舞台、播放、事件恢复与 Replay。 | 最新增量未完成 Full 审计。 |
| `components/interaction/` | 教师互动、二维码和匿名表单。 | M13 未完成 Full 审计。 |
| `components/report/` | 报告状态、生成、Revision 与下载。 | M14 未完成 Full 审计。 |
| `components/history/` | Turn、来源、票数、弹幕与报告历史。 | M15 未完成 Full 审计。 |
| `components/translation/` | 按需测试翻译。 | M15 未完成 Full 审计。 |
| `components/wave3/` | 教师 Wave 3 页面组合层。 | 未完成页面级 Full 审计。 |

### API 与测试

| 路径 | 作用 |
| --- | --- |
| `frontend/lib/api/generated/` | 从冻结 OpenAPI 生成的 TypeScript Schema/Client。 |
| `frontend/lib/api/platform.ts` | 页面使用的 Provider-neutral API 封装。 |
| `frontend/tests/` | Vitest 与 Testing Library 测试。 |

Wave 3 重点前端测试：

- `wave3-interaction.test.tsx`；
- `wave3-report.test.tsx`；
- `wave3-history-translation.test.tsx`；
- `wave3-playback-controls.test.tsx`；
- `wave2-playback.test.tsx`（仍承载大量播放恢复回归）。

## `contracts/`

| 路径 | 作用 |
| --- | --- |
| `openapi-v0.1.yaml` | 前后端唯一 HTTP 合同。 |
| `openapi-v0.1.sha256` | 冻结 OpenAPI Hash。 |
| `response-contract-allowlist.json` | 显式响应差异白名单。 |
| `route-surface-placeholders.json` | 已实现、缺失与基础设施额外路由分类。 |
| `ws-events.v1.schema.json` | 封闭 WebSocket 事件联合 Schema。 |
| `fixtures/` | WS 正例、反例与契约输入。 |

## `scripts/`

| 路径 | 作用 |
| --- | --- |
| `bootstrap_local_demo.py` | 保留账号目录并创建本地 `.env`。 |
| `test_bootstrap_local_demo.py` | 初始化安全探针。 |
| `test_wave1_migration.py` | Wave 1 populated 迁移保留性。 |
| `test_wave2_migration.py` | Wave 2 populated 迁移保留性。 |
| `test_wave3_migration.py` | 0007 fresh/repeat/downgrade/re-upgrade/FK/指纹。 |
| `check_frozen_openapi.mjs` | 检查 OpenAPI 与 Hash。 |
| `compare_route_surface.mjs` | 对比 FastAPI 路由与冻结合同。 |
| `generate_ws_schema.mjs` | 生成/同步 WS Schema。 |
| `generate_ws_fixtures.mjs` | 生成 WS Fixture。 |
| `check_repo_boundary.mjs` | 拒绝 `.env`、运行数据、个人输入与未授权凭据。 |
| `test_repo_boundary.mjs` | 使用临时探针验证边界检查。 |

## `config/`

| 路径 | 作用 |
| --- | --- |
| `repository-data-policy.json` | 私库的精确数据保留策略。 |

## 当前树中禁止出现

- `.env` 与真实 Provider Key；
- `data/`、`backend/data/`；
- SQLite、WAL、SHM；
- 本地 Agent、Debate、Turn、投票、弹幕、报告、翻译运行记录；
- 生成课堂音频、个人音频、`private-inputs/`、临时锁；
- `node_modules`、`.next`、`.venv`、缓存与 Coverage；
- `archive/` 与 `outputs/`。

新成员从 `README.md` 开始；开发前读 `Project.md`；接手未完成工作时再读 `docs/PROJECT_STATUS.md` 与对应 Gate。
