# REAL-EMBED-E2E 中文固定夹具

本目录只服务 `DEMO-BLOCKER — REAL-EMBED-E2E`。素材全部为原创、虚构、无身份
信息，冻结一份中文单-chunk Markdown、一个可确定性编译的 Persona、一条中文辩题和
预期命中词。

默认检查完全离线，不读取 `.env`、不连接服务、不会调用 Provider：

```text
uv run --project backend python manual-tests/real-core-embedding-zh/scripts/acceptance.py check
uv run --project backend pytest -q manual-tests/real-core-embedding-zh/scripts/test_acceptance.py
```

真实产品验收分为同一数据库上的两个显式阶段，两个服务不得同时运行：

1. 全部 Provider 为 Mock 时运行 `prepare`，通过正式 HTTP API 创建一个已发布的
   Mock 对照 Agent 和一个已确认但未发布的目标 Agent，并写入 mode `0600` 的安全
   checkpoint。
2. 停止服务；单独运行 `scripts/import_provider_policy.py` 导入已人工审核 Policy；
   只把 Embedding 切为 DashScope，其他 Provider 保持 Mock；使用同一数据库重启。
3. 运行 `execute`。脚本先把 checkpoint 持久化为 `executing`，因此中断后不能重跑。
   目标 Agent 首次 publish 必须在 0 调用处返回确认要求；教师确认
   exact manifest 后，重复同一幂等 publish，最多产生 1 次 Snapshot 请求。创建两
   Agent、两轮 Debate 后，query 也必须先确认，再显式 retry，最多产生 1 次 query
   请求。当前 Turn ready 后立即停止服务，不点 Next。
4. 服务停止后运行 `verify`。它只读同一 SQLite，要求持久化 Provider ledger 中
   Snapshot/Query 各恰好 1 次 accepted charge，并验证 final-ready Turn 的中文
   Snapshot/chunk、Receipt、TurnSource 与 Evidence Trace。只有此步可以输出 PASS。

```text
# Phase 1: server is all-Mock
MAYA_BASE_URL=http://127.0.0.1:8080 \
MAYA_STUDENT_PASSWORD='provided-out-of-band' \
uv run --project backend python manual-tests/real-core-embedding-zh/scripts/acceptance.py \
  prepare --checkpoint /tmp/maya-real-embed-checkpoint.json

# Stop server, import reviewed policy separately, restart same DB with only Embedding real.

# Phase 2: server uses real Embedding and Mock companions
MAYA_BASE_URL=http://127.0.0.1:8080 \
MAYA_STUDENT_PASSWORD='provided-out-of-band' \
MAYA_TEACHER_PASSWORD='provided-out-of-band' \
uv run --project backend python manual-tests/real-core-embedding-zh/scripts/acceptance.py \
  execute --checkpoint /tmp/maya-real-embed-checkpoint.json \
  --policy-hash <64-lowercase-hex> --confirm-two-call-cap

# Stop the service before this read-only durable verification.
uv run --project backend python manual-tests/real-core-embedding-zh/scripts/acceptance.py \
  verify --checkpoint /tmp/maya-real-embed-checkpoint.json \
  --database-url sqlite:////absolute/path/to/maya.sqlite3
```

脚本不执行 shell/Policy importer，不接受第二个 base URL，不自动重试，不输出密码、
Key、endpoint、模型、raw response 或学生资料。安全输出仅包含 fixture/checkpoint hash、
opaque product IDs、状态和本次授权调用计数。任何不匹配都会停止；失败后不得追加调用
来制造 PASS。
