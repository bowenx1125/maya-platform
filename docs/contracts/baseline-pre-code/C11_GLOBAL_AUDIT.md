# C11 全局合同冲突审计

合同版本：`g0-2026-08-28.6-manual-acceptance-delta`
状态：`INCREMENT FROZEN — SOL HIGH G0-S PASS / G1 AUTHORIZED`
审计范围：Project 当前契约、C01-C10、OpenAPI v0.1
产品源码：Wave 0/Wave 1 已存在；本次 Wave 2 合同增量尚未创建业务代码

## 1. 审计方法

1. 主窗口完整阅读 `Project.md`，包括历史原始需求；只以第 0/5/8 节为当前权威。
2. 三个 Sol High 只读设计挑战分别覆盖：
   - `/root/g0_ux_permission_audit`：C01/C04/C09；
   - `/root/g0_data_api_audit`：C02/C03/C07/C08；
   - `/root/g0_state_gate_audit`：C05/C06/C07/C10/C11。
3. 主窗口对审计建议逐项取舍，不能由子 Agent 修改产品决定或给 Gate 最终签字。
4. 对 OpenAPI 执行 YAML 解析、内部 `$ref`、operationId 唯一、path 参数、关键路径和幂等覆盖检查。
5. 对 Project/G0/OpenAPI 做角色、版本、RAG、轮次、互动、Maya、语音、3D、留存和供应商泄漏的人工交叉核对。

## 2. Sol 设计挑战处理

| 建议/发现 | 决定 | 原因/落点 |
| --- | --- | --- |
| Debate.completed 不应要求报告成功 | 接受 | 首次洞察/报告链到 ready/failed 后 completed；报告失败只属于子域 |
| Playback 不使用 replaying 独立状态 | 接受 | 使用六状态 + `mode=live|replay`，减少状态组合 |
| turn.ready 必须文字/结构/来源/音频全部 ready | 接受 | 避免前端对 ready 含义产生两套解释 |
| Report 重生失败不能隐藏旧成功 | 接受 | 分离 generation/latest attempt/current success revision |
| Debate events 持久化 | 接受 | 支持 `snapshot_sequence + since_sequence` 可靠重连 |
| 组文档“移出草稿”和“组级隐藏”分离 | 接受 | 防止影响同组其他 Agent；发布快照永不删除 |
| 教师读取发布快照需要专用 API | 接受 | 增加 snapshot metadata/RAG/source download |
| start 携带 expected current audio debate ID | 接受 | 防止确认后并发变化导致误删新音频 |
| 正式种子只有 1/2，但应验证 2-5 人 | 接受 | 3/4/5 只进入测试 fixture，不污染产品种子 |
| 学生端提供课堂报告回顾 | 不进入 Demo | 学生账号职责冻结为制作；课堂历史/报告由教师空间负责 |
| TTS 失败重试一次后整场 failed | 不接受为当前课堂产品策略 | 现在只开放一次性 attempt=3 技术诊断并覆盖失败/timeout安全状态；四回合真实课堂的终止/重试语义仍为后置决定，不静默降级 |
| finalized 互动和已清理音频使用 410 | 接受 | 资源曾存在但已按生命周期失效；未知 ID 仍 404 |
| 直接复制参考代码以节省时间 | 明确禁止 | 用户要求只参考和借鉴；C10 每个 Gate 有 originality/no-copy 检查 |

### 2.1 2026-08-28 人工验收增量

- 旧 `.5` 的“点击开始后自动连续播放”只保留为历史事实，已被教师逐回合 Next 取代；
- 增加 live-only `waiting_next`、派生 `next_turn_ready`、REST `advanceDebatePlayback`、WS `playback.waiting_next` 和 media action `next`；full replay 仍可自动连续；
- 新增 `0005_wave2_manual_advance`，不得改写 0004；
- 3D 正常路径必须真实可见像素，不能以 ready 空白或静态兜底签 PASS；
- 真实 TTS 从后置改为一次性安全诊断 Gate：0 enrollment、最多1次 TTS、无自动重试、durable ledger、安全错误分类、失败不激活；
- 较低 effort 的首轮问题查找只作为缺陷输入，不具有 Gate 签字权。当前由独立 `gpt-5.6-sol high` 对稳定磁盘快照执行最终 G0-S；只有其明确 `PASS / G1 AUTHORIZED` 后才可实施教师 Next 或触发真实 TTS。

## 3. OpenAPI 机械验证

验证文件：`openapi-v0.1.yaml`。

| 检查 | 结果 |
| --- | --- |
| YAML 可解析 | PASS：OpenAPI 3.1.0 |
| paths | PASS：59 |
| operations | PASS：68 |
| schemas | PASS：50 |
| `$ref` | PASS：419 次引用、75 个唯一引用、0 个缺失 |
| operationId | PASS：0 重复 |
| path parameters | PASS：0 缺失 |
| 必需主链路径 | PASS：0 缺失 |
| 禁止课程/小组写接口 | PASS：0 |
| 关键命令 Idempotency-Key | PASS：0 缺失 |
| round_count / hard time | PASS：round_count const=2；两个 hard time 字段只能为 null |
| participant slot | PASS：字母枚举 A-E；与教师点击顺序和数值型 order_index 一致 |
| Provider/API Key 外泄字段 | PASS：DTO schema 无 provider/model/external voice/key 字段 |
| Maya 弹幕输入 | PASS：Report 只引用 BarrageInsight；raw named barrage 只在教师互动 DTO |

YAML 解析使用系统 Ruby/Psych；本机没有 PyYAML，因此未把缺少 Python 包误报为合同失败。

`.6` 当前机械证据另包括：父/产品 OpenAPI 字节一致与 SHA/生成 Client/Redocly/68-operation response PASS；严格 route `55 implemented / 13 placeholders` 与 13 个负例 PASS；WS events `30 positive / 17 negative`、commands `6/7`、private results `5/6` 及 clean-diff PASS；`0005` fresh/repeat/populated/downgrade/re-upgrade/全指纹/Voice ledger/FK PASS。以上只证明合同产物一致，不能替代本次 Sol High G0-S 签字。

`g0-2026-08-26.3` 是用户最终视觉决定引起的窄变更：公开参辩 `slot` 从整数 1-5 恢复为字母枚举 A-E，`order_index=0..4` 继续承担确定性排序，辩论人数、轮次、权限和状态机不变。主窗口重新执行 YAML、路径/operation/schema、内部 `$ref` 和两个公开 slot Schema 检查：仍为 58 paths、67 operations、47 schemas、342 次/63 个唯一内部引用、0 缺失引用，两个 slot 均为 `A|B|C|D|E`。该窄变更未重新消耗一次 Sol High；编码期仍必须用生成 TypeScript Client、服务端路由和 E2E 验证字母槽位贯穿一致。

`g0-2026-08-27.5` 是 Wave 2 开工前的高风险合同增量，不改变已确认的 2-5 人、A-E、固定两轮或 Wave 3 边界。三路 Sol High 分别审计数据/迁移、RAG/生成和播放/WS，均在主窗口修复反例后最终 `PASS`。增量冻结了 draft/start CAS、精确复合 FK、Job/cancellation fence、先 journal 后 rename 的音频 swap、final-ready 前驱前缀、typed receipt/used-only sources、结构化 validator、单一 controller/current-only media ticket、pre/post-ack failure、snapshot watermark、同源 URL、Range/ETag 和 private command result。OpenAPI 仍为 58 paths/67 operations，当前实现前 route surface 为 40/27，Wave 2 目标为 54/13；WS events 为 29 正例/14 反例，commands 为 5/7，private results 为 5/6，route comparator 为 13 个负例。该记录只签设计，不替代 0004、路由、G2 或 G3。

## 4. 跨合同一致性结果

### 4.1 Scope 与角色

- PASS：1 教师、6 学生、1 课程、2×3 小组；观众不是 User。
- PASS：不存在课程/小组写操作、PDF/TXT、在线知识正文编辑、评分/Evaluation、硬时长输入。
- PASS：教师课堂历史/报告；学生只负责本组制作；匿名端只提交两项。

### 4.2 权限

- PASS：跨组 Agent/Version/Document/Snapshot/Voice 列表、详情、下载、关联、测试、发布均 404。
- PASS：教师可读已发布完整历史，不读未发布草稿或未绑定组资料。
- PASS：所有课堂控制/翻译/互动开关/报告重生只允许课程教师。
- PASS：匿名 token 不读取 transcript、票数、原始弹幕墙或报告。

### 4.3 Agent、版本与 RAG

- PASS：一组多 Agent；组内 MD 可复用但必须逐草稿明确启用。
- PASS：AGENT.md 和 RAG 是不同对象；限制分别 12,000 和启用合计 100,000 字符。
- PASS：发布是唯一正式 snapshot 入口；发布版/快照不可变；旧辩论固定旧版。
- PASS：matched/no_match/general reasoning 与来源 DTO、E2E 一致。

### 4.4 辩论与播放

- PASS：2-5 Agent、有序 A-E、固定两轮；Maya 不在参与者中。
- PASS：第一轮观点+RAG；第二轮反驳/提问/更新；最后一位 audience reflection。
- PASS：LLM 不决定下一人；前端不推进业务状态。
- PASS：pause 可恢复、stop 不可恢复、skip 保留内容；prepared 最多一位且不提前泄漏。
- PASS：Playback 使用 status + live/replay mode；后端重启从当前 turn 开头且不重新生成。

### 4.5 互动、洞察与报告

- PASS：最后 turn 后由教师手动打开；failed/stopped 不能打开；finalized 不可重开。
- PASS：Vote/Barrage 分表、分 API、分 submission ID，刷新可再次提交。
- PASS：大屏保存全部昵称原文；洞察去昵称、按真实 ID 计数；少数相关观点不得被过滤。
- PASS：Maya 不读取原始弹幕、完整 Agent RAG 或未使用证据；不宣布赢家。
- PASS：零互动正常报告；报告修订不可变；失败不回滚辩论/互动或隐藏旧成功。

### 4.6 Provider、文件与留存

- PASS：前端只认平台 DTO；Key/供应商/外部 voice/file path 不外泄。
- PASS：原声音频 success/failure/timeout 后清理；Voice 删除保持历史 ID 并解析 fallback。
- PASS：所有文字/来源/弹幕/票数/报告长期；仅每课程最近已启动场音频保留。
- PASS：snapshot promote、voice delete、audio swap、interaction close 有原子/恢复边界。
- PASS：attempt=3 诊断只允许一次、失败不激活、timeout/outcome_unknown 禁止再调用；四回合课堂 TTS 失败语义仍后置且不伪装已有降级方案。

### 4.7 禁止复制代码

- PASS：合同包未复制参考项目实现代码。
- PASS：OpenMAIC/Parallax/TalkingHead/MotionEngine 只作为设计/兼容参考。
- PASS：C10 要求所有 Worker 从 Maya 合同独立实现，禁止任何参考仓库实现片段复用，没有例外。

## 5. 已知非阻塞外部项

- 百炼 API Key；
- 可选 DeepL Key；
- 真实 `FALLBACK_VOICE_PROFILE_ID`；
- Bowen/KaiKai 正式 TikTok Markdown；
- 至少 2 个、目标 3 个 TalkingHead 兼容头脸；
- 真实 Embedding 模型名与基于正式资料测得的 min_score。

这些只阻塞对应 G5 真实验收，不阻塞合同冻结或 Mock 骨架。

## 6. 历史基线审计结论（2026-08-26）

`PASS FOR C12 REVIEW`。Project 同步和机械复查已经完成；当时只剩用户 C12：

1. 用户审阅非技术总览与验收边界；
2. 用户明确完成 C12 后，才打开编码门禁。

后续状态：用户已于 2026-08-26 19:06 完成 C12 并明确授权开始 Wave 0；本 C11 审计结论保持有效，编码门禁现已打开。

### 6.1 当前 `.6` 增量审计结论（2026-08-28）

独立 `gpt-5.6-sol high` 已对最终稳定磁盘快照签署 `PASS / G1 AUTHORIZED`，P0/P1 均为 0。签字仅覆盖 M07/M08/M12 人工验收增量；教师 Next、一次性 TTS 和最终课堂体验仍须经过 Luna G1、机械 G1.5、独立 Sol High G2 与主窗口 G3。Wave 3/4 继续锁定，真实 TTS 调用还必须使用锁定 backend Docker 环境并完成调用前安全检查。

## 7. Wave 0 G0-S 合同修正（2026-08-26）

首轮 Sol 设计审计在实现前发现五项可机器验证缺口；合同版本由 `.3` 升为 `.4`，没有改变产品行为：

- 所有 31 个已认证 mutation 在 OpenAPI 中显式要求 `X-CSRF-Token`；`/auth/me` 返回可恢复 CSRF 的 `AuthSession`，`csrf_token` 不再误标为 response writeOnly；
- C02 冻结 UUIDv5 namespace、全部组织 seed key/精确 ID、fingerprint 与冲突事务失败规则；
- C06 要求按 event type 判别的完整 WebSocket payload union 和泄漏/提前正文反例；
- C10 将 `frontend/lib/api/generated/**` 唯一分配给 M17 contract owner；
- Wave 0 Gate Packet 经依赖复审将 TypeScript 固定为 openapi-typescript 支持的 5.9.3、ESLint 固定为可执行的 9.39.1、jsdom 固定为兼容 Node 24.14 的 29.0.1，并显式补齐 Vite/testing-library-dom、完整直接依赖、镜像锁定和 seed/pragma 验收。

这些修正必须由同一个 Sol G0-S 复审通过后，M03/M16/M17/M18 才能进入 Luna 实现。
