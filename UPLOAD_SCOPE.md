# Maya Platform 私有仓库范围

本仓库用于 Maya Demo 的团队协作和代码审计。它保持私有，但不再作为完整运行快照保存任何人的本地使用历史。

## 当前 HEAD 保留

- 产品源码、测试、迁移与工程脚本；
- OpenAPI、WebSocket Schema、Fixtures 与生成 Client；
- `Project.md`、README、原始需求与当前 Gate；
- `manual-tests/` 中的人工测试输入；
- 根目录唯一共享状态表 `开发文档.xlsx`；
- Demo 账号与密码：
  - `backend/config/demo-accounts/accounts.private.md`
  - `backend/config/demo_users.yaml`

Demo 账号只用于授权团队，不得转移到公开仓库，也不得通过前端/API 返回密码。

## 当前 HEAD 不保留

- `.env` 与真实 Provider Key；
- SQLite、WAL、SHM；
- 本地创建的 Agent、AgentVersion、Debate、Turn、Interaction、Report 与 Translation 记录；
- `data/`、`backend/data/`；
- KnowledgeSnapshot 与生成音频；
- 个人声音样本与 `private-inputs/`；
- 锁文件、日志、缓存、依赖与构建产物；
- 历史 `archive/` 与 `outputs/`。

本次清洗不改写旧 Git 历史；旧提交仍可能包含曾经上传的运行快照。当前及未来分支不得再次把这些文件加入 Git。

## 本地运行

每个开发者在本地生成自己的：

```text
.env
data/
backend/data/
private-inputs/
```

其中 `private-inputs/` 只用于本地真实服务调试，必须保持 Git ignored。

第一次启动运行：

```bash
pnpm install --frozen-lockfile
pnpm bootstrap:local
docker compose up -d --build
```

`pnpm bootstrap:local` 保留仓库中的 Demo 账号目录，只创建本地 `.env`；如果账号目录缺失，脚本才会生成一份新的固定身份目录。

## CI

CI 必须使用：

```text
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=mock
TTS_PROVIDER=mock
VOICE_PROVIDER=mock
TRANSLATION_PROVIDER=mock
```

CI 不读取真实 Key，不调用真实 Provider，也不依赖开发者运行数据库。
