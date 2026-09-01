# Maya Demo v0.1 编码前预检记录

检查时间：`2026-08-26 18:33（Asia/Shanghai）`
结论：`PASS / READY FOR EXPLICIT CODING AUTHORIZATION`
编码门禁：预检时为 `CLOSED`；用户已于 `2026-08-26 19:06` 明确授权，现为 `OPEN / WAVE 0 IN PROGRESS`
产品源码：不存在；本轮没有创建 `maya-platform`、没有初始化产品 Git、没有写产品代码或派发实现任务

## 1. 本轮检查范围

- 完整重读 `Project.md`，包括第 12 节原始需求历史副本；当前实现仍只认第 0、5、8 节；
- 复核 C01-C11、C12 Visual Draft V2、OpenAPI v0.1 和当前本机素材/环境；
- 检查活动章节中的编号、冻结状态、开发阶段和共享工作簿是否存在误导；
- 检查正式开工时的 Git/密钥隔离、Docker、FFmpeg、3D 素材和真实服务前置项。

## 2. 已完成清理

1. `Project.md` 的 Demo 展示脚本从旧数字 `1/2` 恢复为冻结的 `A/B`；
2. 第 6、7 节标题分别改为 `C02 已冻结`、`C03 已冻结`；
3. M01-M18 表最后一列从“当前尚未完全冻结”改为“开发期实现/后置验证”；
4. M16/M17 明确：ERD、错误/重试/幂等/Provider 合同已经冻结；Alembic、生成 Client、WebSocket 机器 Schema 和真实路由测试属于开发期证明，不是尚缺的产品决定；
5. 修正代码资产事实：Maya 根目录不是 Git worktree，但 Document Validation Agent 内含两个嵌套仓库，private 目录含真实 `.env`；Wave 0 只能在 `Maya/maya-platform/` 初始化独立 Git；
6. V2 Excel 已设为唯一开发共享基准。根目录 `开发文档.xlsx` 指向 `outputs/20260826-pre-code-preflight/开发文档-模块对齐-V2唯一共享基准.xlsx`；旧根目录工作簿和锁文件可恢复地归档到 `archive/pre-code-preflight-20260826/`。

以上均为状态收口和事实修正，没有改变产品需求、OpenAPI 语义、权限、状态机或视觉基线，因此 C01-C11 不需要退回 `DRAFTED`。

## 3. 验证结果

| 检查 | 结果 |
| --- | --- |
| OpenAPI YAML | 3.1.0，可解析 |
| paths / operations / schemas | 58 / 67 / 47 |
| operationId | 0 缺失，0 重复 |
| 内部引用 | 342 次、63 个唯一引用、0 缺失 |
| 公开参辩 slot | 2 个相关 Schema 均为 A-E；内部 `order_index=0..4` |
| V2 共享工作簿 | 两张工作表完成值、公式错误和视觉渲染检查；0 公式错误，无明显裁切 |
| 本机运行时 | Node 24、pnpm 11、Python 3.12、Docker CLI/Compose 可用 |
| Docker 后台 | 尚未启动；Wave 0 当天启动 Docker Desktop 后再运行 Compose 验收 |
| 本机 PATH 安全 | `/opt/homebrew/bin` 当前为 `0777`；不阻塞 Mock Wave 0，但真实 Key 接入/可信发布前应由用户恢复为仅所有者可写；本轮未修改系统权限 |
| 产品代码 | 预检时不存在；当时符合编码门禁关闭要求。用户后续已授权创建 `maya-platform` |

## 4. 不阻塞 Mock Wave 0 的后置项

- `DASHSCOPE_API_KEY`、可选 `DEEPL_API_KEY` 和真实 `FALLBACK_VOICE_PROFILE_ID`；
- Bowen/Kaikai 正式 TikTok Markdown 与基于它们锁定的 RAG `min_score`；
- 真实声音样本和百炼真服务联调；
- 至少 2 个、目标 3 个 TalkingHead 兼容 GLB；当前只发现 1 个可直接试验的 GLB；
- 宿主机没有 FFmpeg；实现时放入 backend Docker 镜像，不要求用户安装宿主机依赖；
- 历史“全部 TTS 失败策略延期”已由 2026-08-28 窄增量部分取代：一次性 attempt=3 技术诊断现已授权并必须覆盖唯一 claim、无重试、脱敏和 outcome_unknown；四回合真实课堂的终止/重试语义仍后置，不得临时猜测或伪装成功。

## 5. 开门条件

本轮没有发现新的产品边界问题。下一步只有两个操作性条件：

1. 开始 Wave 0 前启动 Docker Desktop；
2. 用户明确回复：`允许打开编码门禁，开始 Wave 0`。

用户已于 2026-08-26 19:06 完成第 2 项，C12 已冻结并打开编码门禁。后续仍必须遵守模块 Gate；本预检结论不等于 Wave 0 或完整 Demo 已通过。

## 6. 2026-08-28 Wave 2 人工验收重开

既有编码门禁不关闭，但 Wave 2 人工体验增量重新进入模块 Gate。正常数据测试发现：

- Avatar GLB/Draco 可加载且 canvas 标记 ready，但实际透明空白；
- 当前 Mock TTS 只有1秒提示音，不能验收英文人声、语速或课堂节奏；
- 用户把 live 播放从自动连续改为教师每回合点击“下一步”。

本增量已经完成合同收口，并由独立 `gpt-5.6-sol high` 对稳定磁盘快照签署 `PASS / G1 AUTHORIZED`，P0/P1 为 0。该签字只开放 M07/M08/M12 的 G1；教师 Next、一次性真实 TTS 和人工课堂体验仍必须继续通过 G1.5/G2/G3，Wave 3/4 不开放。
