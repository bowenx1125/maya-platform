# Agent Prompt（每个新窗口必须执行）

你是大厂最顶级的程序工程师，也是本项目的首席产品技术负责人。你的目标不是堆砌功能，而是用最清晰、最小、可验证、可继续扩展的方式，交付真正能运行的产品。

在本仓库开展任何工作时，必须遵守以下规则：

1. 每次打开新窗口、开始新会话或接手任务时，先完整阅读本文件 `Project.md`，再阅读与任务直接相关的需求和代码；不得只凭聊天记忆开始开发。
2. 修改前先确认当前阶段、范围、接口契约和验收标准；优先复用已经验证的代码，但不得盲目复制与业务无关的复杂度。
3. Demo 阶段坚持“接口完整、功能简单、主流程可演示”：允许使用 mock、占位模型和第三方 API 适配器，但所有替代实现必须有清晰边界，能够在后续替换为真实服务。
4. 不在代码、文档、日志或提交记录中泄露 API Key、个人音频、学生隐私或内部地址。
5. 每次工作结束前必须更新本文件，至少记录：本次完成内容、当前状态、新增决策、验证结果、遗留问题和下一步。
6. 如果本文件与最新明确需求冲突，以最新明确需求为准，并在结束前同步修订本文件。
7. 禁止从参考仓库直接复制粘贴任何实现代码、整段改名复用或继承其领域模型，没有代码片段例外。参考只用于理解交互、算法、状态机、接口分层和测试思路；Maya 的代码必须从本项目冻结合同出发独立设计和实现。

---

# AI文化互鉴教学平台：项目上下文

最后更新：2026-08-30 18:39（Asia/Shanghai）

## 0. 文档权威顺序与当前契约快照

本节是新窗口和所有开发 Agent 的唯一入口摘要。它只汇总当前有效决定，不记录讨论过程。

### 0.1 权威顺序

1. 本节“当前契约快照”、第 5 节“Demo 已确认范围”和第 8 节“编码前合同 Gate”共同构成 Demo 的当前权威需求；三处必须保持一致；
2. 第 11 节是工作历史，只用于追踪，不得从历史措辞反推当前需求；发现历史条目与当前契约不同，只能按当前契约执行；
3. 第 12 节是最初收到的原始业务需求历史副本，不是 Demo 实现清单。PDF/TXT、课程/小组管理、辩论中实时弹幕、教师可编辑时长等原始目标已被后续 Demo 决定缩减或替代；不得绕过前文直接实现第 12 节；
4. 如果后续用户提出新决定，先修改本节和对应权威章节，再同步模块表、风险、下一步与工作记录；全文冲突检查通过后，新决定才算进入项目契约；
5. 编码期的 OpenAPI、ERD、状态机、事件 Schema 和错误码如与本节冲突，视为合同缺陷，必须停止相关 Gate 并先修合同，不能让实现反向覆盖产品决定。

### 0.2 Demo 当前冻结事实

| 领域 | 当前唯一有效结论 |
| --- | --- |
| 阶段 | `WAVE_3_G3_PASS / g0-2026-08-30.3 G2 PASS P0=0 P1=0 / MAIN G3 PASS / READY_FOR_WAVE_4 / WAVE_4 NOT STARTED / M08 真实 TTS FAILED-DEFERRED`。所有交互控件只显示当前语言；返回文案明确为 debate list；普通 UI 已移除 Pause/Continue，以权威 playback 映射 ready/in-progress/waiting/finished；Replay 始终保留 transcript/source，完整页面刷新后由 Replay 点击按需取得一次 controller，每轮 Replay 结束只续一次 controller；Demo 同时接受同端口 localhost/127.0.0.1 与配置 LAN teacher Origin。真实网络仍只允许手动单次 Reconnect。`.3` 已完成主窗口代码审计、全量机械门禁与真实浏览器 G3；当前只允许讨论/冻结 Wave 4 G0，不代表 Wave 4 或真实 Provider 已开始 |
| 组织 | 1 门预置课程、1 名教师、2 个三人小组；课程/小组成员关系只读；观众免登录且不属于账号体系 |
| 权限 | 学生只访问本组 Agent/MD/RAG/音色；同课程其他组按不存在处理；教师看全部已发布历史完整快照，不看未发布草稿；课堂控制仅教师。Demo 期间统一首页右侧始终公开所有 Demo 身份的一键免密登录，并常驻用户名/密码登录；用户明确接受不做 localhost/LAN 限制；关闭 Demo Mode 后身份目录和 quick-login 必须 404。私有明文账号 Markdown 只在被 Git/Docker 忽略且权限 0600 的后端目录保存，前端/API 永不返回密码 |
| Agent/RAG | 一个小组可建多个 Agent；组内 Markdown 可网页新增和 copy-on-write 编辑。新增文件不自动启用；编辑成功创建新的不可变文档并原子替换所有当前未发布草稿中对旧文档的引用、逐个增加草稿 revision；已经发布/取代的 AgentVersion、KnowledgeSnapshot 和既有辩论永不改变。每个发布版本绑定独立不可变向量 RAG 快照；`AGENT.md ≤ 12,000`，启用 RAG 合计 `≤ 100,000` |
| 版本 | 已发布版本绝不原地修改；继续编辑唯一草稿 → 创建新版本 → 发布更新；教师新建辩论只选当前版，旧版仅历史查看。移除归档/恢复产品语义，改为安全彻底删除：只有从未发布且从未参辩的 Agent 可彻底删除；有发布或辩论历史的 Agent 禁止删除并稳定返回 `agent_history_retained`，历史继续保留 |
| 辩论 | 教师按点击顺序选择 2-5 个当前发布 Agent 并得到连续字母槽位 A-E；固定 2 轮；第 1 轮观点+RAG，第 2 轮回应/反驳+提问+观点更新；最后一位向全班提反思问题。普通教师播放 Dock 只提供“开始辩论 / 下一步 / 重播整场”；普通 UI 不显示 Pause/Continue。课堂 phase 为 ready/in-progress/waiting/finished；Finish 只在 live waiting 且连接/控制权有效时显示并可用。整场 Replay 使用已保存内容，从 A1 开始且每段结束都进入持久 `replay + waiting_next`，仍需教师逐次 Next，不重新调用 RAG/LLM/TTS；底层 pause/resume 与 operator reset 只保留为不可见故障恢复 primitive |
| 立场 | 每名 Agent 可由教师指定支持/反对/中立，也可开放阐述；允许基于证据精炼、让步、重构或换边；不得直接拉票 |
| 输出 | 教师辩题与权威发言默认纯英文；议题在创建/修改时按冻结 Latin-script 规则立即校验，历史非法草稿在启动前再次校验；每回合 80-200 词，目标 160-185 词；界面中英双语；中文只由教师按键生成测试译文，不进入 RAG/TTS/后续上下文 |
| 互动 | 全部 turn 结束后教师手动打开二维码；昵称、投票、弹幕是免登录流程；投票与弹幕独立，页面内各提交一次，刷新可再次提交；投票匿名，弹幕大屏逐条显示昵称+原文 |
| Maya | 教师关闭互动后，原始弹幕留在大屏/历史；后台去昵称、聚类、筛除无关/无实质内容并以真实消息 ID 计算数量；Maya 只读辩论全文、实际引用证据、最终票数和验证后的匿名洞察，输出 600-900 词英文文明互鉴报告 |
| 语音 | 百炼真实声音复刻/TTS；一段本人 10-20 秒英文文件课前注册一次；原/中间样本请求结束即删；自定义音色可选，缺失/删除时用兜底；每课程只保留最近一次已启动辩论语音到下一场启动。真实 TTS attempt=3 已按一次性 Gate 调用且失败为 `tts_audio_invalid`：profile 保持 `preview_ready`，active preview/preview file 为 0，`.env` 与 fallback 均未激活，禁止自动重试。1 秒 Mock 正弦音仍不算语音验收 |
| 3D | 只做 TalkingHead 兼容头脸/头肩、模板和受限参数；非发言者 `listening+attentive`；私下本机 Demo 暂不做资产许可核验，公开分享/交付/正式课堂前恢复许可门禁。人工验收必须真实看到本地 GLB 的可见几何和状态动作；`data-avatar-status=ready` 但画布透明、只显示空卡或静态姓名兜底均不得通过 |
| 运行 | Next.js + FastAPI + SQLite/本机文件 + WebSocket，本机/局域网运行；前端只认平台 API；无 Redis/Celery/PostgreSQL/云存储；未来互联网演示再整体 Docker 部署 |
| 后置 | 百炼 Key/Workspace/北京地域已配置并通过基础凭据验证；真实系统音色已创建但尚未激活。一次性真实 TTS 诊断额度已经用完且失败，不能在当前 Gate 再调用；若继续排障，必须另开合同和收费授权。DeepL Key、正式 TikTok Markdown、真实 Embedding/LLM、局域网课堂验收和投影可读性仍后置。用户已明确把“登录页一键切 Mock/百炼 LLM”从本次 pre-Wave 3 修改包完全移除：不做按钮、接口或假开关；真实 LLM adapter、结构化输出、费用和辩论级冻结留未来独立真实服务 Gate/Wave 4 |

### 0.2.1 当前人工反馈修订（2026-08-29，已授权编码）

- 课堂播放断线后不再自动重连或重复刷新；初次连接可自动尝试一次，之后显示“重新连接 / Reconnect”按钮。每次点击只尝试一次，失败后保留当前页面、文字、来源和权威快照。
- `Pause / 暂停` 是可恢复暂停：持久保存 playback `paused`，不取消未完成生成、不把 Debate 变成不可恢复 `stopped`；重新进入后可 `Continue / 继续`，再执行后续 Next、互动和报告。现有不可逆 stopped 语义只用于真正异常终止/partial Finish/故障恢复。
- 顶部操作顺序固定为“返回辩论列表｜结束辩论｜课堂互动与报告”。完整 Finish 保持正常 `debate_finished` 流程；不完整 Finish 复用终态 `stopped` 表示 partial，保留已生成 turn 但不开放匿名互动、不进入 Maya、不提供历史和 Replay。列表和详情必须诚实显示 `stopped`，不得伪装为完整 finished。
- 课堂互动、Maya 报告、公开发言和测试翻译移到独立教师页面；控制页只负责播放和辩论控制。
- 测试翻译收敛为一个按钮，只切换公开发言显示为中文；英文原文仍是权威源，译文不得回流 Replay、RAG、TTS、后续辩论或报告输入。
- Replay 开始前保留不可变 turn catalog；公开前缀仍按段推进，但 `replay.started` 必须能从 catalog 恢复 speech 和来源。

### 0.2.2 Wave 3 最终 disconnect/RAG delta（2026-08-30，已确认）

- `stopped/completed/debate_terminal` 是权威终态，不显示 Disconnected/Reconnect pill 或遮罩；completed 如需 Replay，只获取新的 controller epoch，不把控制权切换描述为网络重连。
- `controller.revoked(reason=superseded)` 显示“另一个教师页面已取得控制权”，旧页面保留文字/来源、停止音频且不得自动 acquire 或抢回控制权。
- WebSocket `4401` 显示“登录已失效，请重新登录”；`4403` 专用于课堂 Origin 与服务端配置不一致并显示准确文案；两者都没有 Reconnect。服务器内部不可用不得冒充 4403。
- 真正网络异常显示 `Connection lost / Reconnect`；sequence gap 显示单独的状态重新同步说明。二者都只允许教师手动点击一次，执行一次 snapshot、一次 socket attempt 和至多一次 controller acquire；禁止 timer、循环刷新或后台重连。
- `onerror` 不得覆盖更准确的 close code/private revocation reason；独立互动/报告页复用 4401/4403/network 分类。
- 新 Debate 使用 `ordered_multi_agent_rounds_demo_v2 + mock_lexical_anchor_v2`；旧 v1 Debate/turn/snapshot 不改。只有 Mock Embedding 先要求知识块与权威 topic anchor 有冻结的有效词重合，再应用既有 strict→relaxed 阈值；真实 Provider 不变。固定正反例为 TikTok→TikTok matched、TikTok→矿物 no_match、亲密关系→关系资料 matched、爬山→TikTok/关系资料 no_match，round 2 通用前驱文本不得绕过 topic anchor。
- 用户最新明确授权：独立 G2 通过后，由当前主窗口执行真实浏览器 G3，不再等待用户本人另行点击签字。只有 G2/G3 都 PASS 才更新 `WAVE_3_G3_PASS / READY_TO_DISCUSS_WAVE_4`。

### 0.2.3 pre-Wave-4 UX/state delta（2026-08-30，用户直接授权执行）

- 所有按钮、链接和可访问名称只显示当前 locale；禁止 `English / 中文` 拼接。`Back to debate` 改为 locale 化的 `Back to debate list`。
- 普通教师界面删除 Pause/Continue；底层 pause/resume 只保留为不可见故障恢复 primitive。连接健康与课堂 phase 分两行：未启动 draft 映射 `ready`，preparing/ready/playing/in-flight 映射 `in_progress`，live waiting_next 映射 `waiting`，教师 Finish 或自然完成映射 `finished`。
- Start 只在首回合前可用；Next/Finish 只在 `waiting + connected + controller-ready` 时可用，并在 handler 二次 fail-closed。离开 waiting 页面再进入必须恢复同一 waiting、公开 transcript 和来源。
- 教师在 waiting 提前 Finish 后产品显示 finished，但完整 turn-plan 仍是 interaction/report/translation/Replay 的硬前置；异常失败不得伪装成教师 Finish。
- Replay 不清空 transcript，不重新生成任何文本/RAG/语音；逐段播放 immutable catalog，Next 继续保存内容。每个 Replay 终态只自动 acquire 一次新 controller 供下一次 Replay；这不是网络自动重连，真实网络仍必须手动单次 Reconnect。
- Demo mode 的 QR/public URL 仍使用配置 LAN origin；共享 REST same-origin 检查与认证教师 WS 额外接受同 gateway 端口的 `localhost` 与 `127.0.0.1`。非 loopback、协议/端口不匹配和非 Demo 环境继续拒绝，WS 使用 4403。
- 用户授权不再等待二次确认：主窗口先写合同，三个 Luna Max 互斥实现，主窗口审计、全量、独立 G2 和真实浏览器 G3；发现阻断问题继续修到 `READY_FOR_WAVE_4`，不得跳过 Gate。
- `.3` 已完成：主窗口审计清零 P0/P1；后端 `433/433`、前端 `28 files / 193 tests` 以及 lint/type/build/format、OpenAPI/WS/route/迁移/秘密边界全部通过。真实浏览器完成中英单语控件、waiting 导航恢复、工作中 Finish 封锁、early/full Finish、两轮 retained Replay、localhost/LAN 和真实 network 单次手动 Reconnect；当前状态为 `READY_FOR_WAVE_4`，Wave 4 尚未开始。

### 0.3 冻结状态定义

- **产品已冻结**：第 0/5/8.6 节列出的用户体验和数据语义，不再作为“待确认问题”重复询问；
- **基线技术合同与 C12 已冻结，Wave 0/Wave 1/Wave 2 已通过各自 G3（对应 Mock 范围）**：历史基线为 `g0-2026-08-27.5`；M10/M11/M12 的数据库关系、RAG receipt/结构化输出、单一播放 controller、current-only media ticket、WebSocket command/result、Range/恢复和 Mock fail-closed 已落地，并通过三路独立 Sol High G2 与主窗口 G3。`g0-2026-08-28.6-manual-acceptance-delta` 的教师逐回合 Next、真实可见 3D、0005、稳定 API/WS 和一次性真实 TTS 诊断代码已完成 `G1/G1.5/G2`，集中 Sol High 结论为 PASS；其中 M07+M12 已补齐真页面人工 PASS，M08 真实 TTS 仍为 FAILED-DEFERRED，所以 `.6` 整体人工 G3 仍未通过；
- **当前修复/后置边界**：英文议题延迟到第三个 turn 才失败的缺陷已关闭：创建/修改在任何幂等或 CAS 写入前校验，旧草稿启动在音频清理/计划/Job/Provider/状态写入前复验；原失败历史不迁移。百炼基础凭据和一次真实声音注册已完成；历史两次 TTS 失败不删除/重置。attempt=3 的唯一允许调用已消费并安全失败，0 enroll/list/exists/delete、0 retry；不得再次调用或激活 fallback。正式 TikTok 资料、真实 Embedding/LLM、DeepL、局域网课堂与投影验收继续后置；
- **pre-Wave 3 polish 执行状态**：合同 `g0-2026-08-28.7-pre-wave3-polish` 已完成 `G0-S → G1 → G1.5 → G2 → G3`。PW3-A–E 均由 Luna 实现、Sol High 独立审计并由主窗口完成共享 OpenAPI/WS/0006、Docker、全量测试和六视口浏览器验收；最终 `P0=0 / P1=0 / P2=0`。这只签署本次 polish，不解锁 M13-M15、真实 LLM/Embedding/TTS 或公网部署；
- **编码门禁**：第 8.7 的 G0 合同、全文/跨契约冲突审计、四类视觉稿和用户明确授权均已满足；门禁已于 2026-08-26 19:06 打开。实现仍必须逐模块通过 G0-S/G1/G1.5/G2/G3，不得把“允许编码”解释为跳过合同或审计。

## 1. 项目目标

建设一个浏览器访问的 AI 教学平台。学生加入课程并组成小组，通过实际操作完成文化智能体的知识库、人设、数字人形象、动作表情和专属音色；同一小组可以创建多个彼此独立的 Agent，每个 Agent 只使用学生明确启用的组内 Markdown 并发布自己的不可变 RAG 快照。教师按点击顺序从课程内当前已发布的智能体中选择最多 5 个，系统自动标记为字母槽位 A/B/C/D/E 并以此作为每轮发言顺序；教师在课堂大屏网页上组织有知识依据、有完整上下文的多轮辩论。全部参辩发言结束后，学生通过教师展示的二维码进入免登录互动页；先输入昵称，再独立发送原始弹幕和/或匿名投票。大屏逐条显示原始“昵称 + 弹幕”，教师结束收集后，系统另行去除昵称、聚类和筛选弹幕；报告 Agent `Maya` 只使用辩论、最终匿名票数和验证后的匿名课堂洞察生成文明互鉴报告，不把所有原始弹幕直接塞进报告。

平台首先服务于教学，重点是让学生理解 RAG、Agent、语音合成/音色克隆和数字人的基本原理。Demo 与首版不追求生产级视觉效果和高精度口型同步。

最初业务背景全文保存在后文“原始业务需求完整副本”；Demo 实现范围只认第 0/5/8 节和后续冻结的 G0 合同。

## 2. 当前阶段和正在做什么

当前产品 P0、C01-C12、Visual Draft V2 和编码前预检均已冻结。`g0-2026-08-30.3-wave3-pre-wave4-ux-state-delta` 已完成 G1、主窗口 G1.5/G2 与真实浏览器 G3，准确状态为 `WAVE_3_G3_PASS / READY_FOR_WAVE_4 / WAVE_4 NOT STARTED`。locale-only 控件、简化课堂 phase/操作、Replay 保留/按需控制权与 Demo localhost/LAN Origin 均已落地；真实 TTS/LLM/Embedding、正式内容质量、30–60 人课堂负载和公开部署继续锁定。

**上一候选覆盖（2026-08-30）**：共享 OpenAPI、生成 Client、路由夹具、WS Schema/fixtures、0007、CI、具体 `PlatformApi` 与前后端模块已经融合。上一轮全量为后端 `386/386`、前端 `27 files / 164 tests`，Ruff format/check、mypy、ESLint、TypeScript、Prettier、Next production build、三代迁移、OpenAPI/response、WS 正反例、严格 FastAPI route/schema、仓库边界和秘密扫描全部通过。Docker 冷重建及真实教师浏览器已验证手动 Reconnect、Pause/Continue、partial/full Finish、独立互动/报告页、单视图测试翻译和 retained-catalog Replay；最终发现的 Continue 重复事件缺陷已有确定性反例与真实页面复验。这些是最终 delta 的基线证据，不替代新的 G1.5/G2/G3。

**最终 delta 完成覆盖（2026-08-30 17:05）**：多 subagent 互斥实现与未参与实现者独立审计已经完成。后端 `401/401`、前端 `28 files / 182 tests`、生成合同、OpenAPI 69 operations、WS 30/18、route 13 negatives、0001–0007、秘密边界、Docker 重建和主窗口真实浏览器全部通过；独立 G2 为 `PASS / P0=0 / P1=0 / P2=1 accepted`。G3 覆盖网络重启→无后台重试→手动单次 Reconnect、Pause/Continue、双教师 superseded、4401/HTTP 401、4403、完整/不完整 Finish、匿名投票/弹幕、609 词报告、单批翻译切换和四段 Replay。G3 真实发现并关闭两项 P1：关系资料 URL slug 把 `rules` 伪装成正文 topic token，以及 Reconnect snapshot HTTP 401 抢先于 WS 4401 导致 generic network 文案。相同反例修复后浏览器复验通过；真实 Provider 调用为 0。

**pre-Wave-4 UX/state delta 完成覆盖（2026-08-30 18:19）**：三个 Luna Max 按 locale、Origin、playback 互斥实现，主窗口逐项审计并修复 Host/Origin 信任、partial 下游泄漏、Finish waiting/live CAS、Next→Finish 同事件竞态、终态控制器噪音、Replay phase/Finish 矛盾、完整页刷新后 Replay 禁用等 P1；最终 `G2 PASS / P0=0 / P1=0`。后端 `433/433`、前端 `28 files / 193 tests`、mypy 109、全合同/迁移/秘密边界和 Docker build 全绿。真实浏览器验证两种 locale、提前/完整 Finish、两轮四段 Replay、localhost/LAN、真实重启后无后台重试与单次手动 Reconnect、匿名互动、611 词报告和 `5/5` Mock 翻译；真实 Provider 调用为 0。

**干净私库发布覆盖（2026-08-30 18:34）**：用户授权覆盖 GitHub 私库 `bowenx1125/maya-platform`。发布从本地完整检查点 `a235c29` 生成独立单根提交，不改本地开发仓库的 `origin` 或完整开发检查点；远端保留运行/维护所需前后端、稳定合同、Compose/infra、bootstrap/fallback 初始化脚本、锁文件、README、AGENTS 和本文件，排除全部测试源码/测试配置/测试依赖、旧 CI/Gate 证据、`.env*`、`accounts.private.md`、运行数据、数据库、日志、缓存和历史运行记录。干净树已独立通过前端 TypeScript/Next build、后端 runtime-only sync/compile 和 backend/frontend Docker build；GitHub API 复核私库 main 必需路径齐全且禁传路径为 0。固定七个 Demo 身份由 `scripts/bootstrap_local_demo.py` 在首次运行时写入本机忽略且 0600 的私有文件，远端不保存明文密码。

编码门禁已经打开，但模块 Gate 继续有效：完整合同包位于 `docs/pre-code-contracts/`，产品 Wave Gate 证据位于 `maya-platform/docs/gates/`。M13-M15 与最终 delta 已签 `WAVE_3_G3_PASS`；真实 LLM/Embedding/TTS、正式内容质量、课堂负载和公网部署仍锁定。`.7` 与 Wave 3 的 PASS 都不改变 M08 `FAILED-DEFERRED`。

当前目标是先交付一个接口覆盖完整、内部功能从简、可以端到端演示的 Demo，用来：

- 确认教师、学生、课程、小组、智能体和辩论场的产品流程；
- 提前固定核心数据对象和 API 契约，便于后续多人及 Vibe Coding 协作；
- Demo 跑通“切换预置身份 → 进入预置课程/小组 → 创建智能体 → 上传知识 → 发布版本 → 创建辩论 → 固定两轮发言 → 弹幕/投票 → Maya 报告 → 查看记录”的完整链路；课程创建、按课程号加入和小组成员管理保留为正式版需求，不进入 Demo；
- 把模型、知识上下文、音色克隆、TTS 和数字人渲染放在可替换的 Provider/Adapter 后面；
- 用 mock 与真实第三方服务两种模式降低演示和开发风险。

### 2.1 当前实际进度审计（2026-08-28 21:40）

> **当前权威续记（2026-08-30 14:37）**：下方“额度耗尽/部分实现/不得清理”的 2026-08-29 说明只保留为历史，不再控制当前工作。人工反馈增量已经完成融合、全量门禁、Docker 和真实浏览器候选；用户授权的运行数据/备份/历史清理也已执行。空库重新升级到 0007、外键为 0、教师 Demo 登录成功且发布 Agent/辩论/互动/报告/翻译均为 0；随后再次停机并删除重建数据。本机只保留 `.env` 与 `accounts.private.md` 私有运行资料；本地完整开发检查点为 `d541b65 feat: complete wave 3 manual feedback candidate`。GitHub 私库为不含测试、环境文件、明文密码和运行历史的干净源码单根提交；等待独立 delta G2 与用户 G3。

> **额度耗尽暂停说明（2026-08-29 15:54）**：本轮已按用户要求立即停止全部 Agent。不要把下方工作树中的部分实现当作完成版本；必须在额度恢复后从窄范围继续审计、融合和测试。

- 已完成的本轮动作：Terra xhigh 只读审计指出 Stop/Finish、持久 paused、partial stopped 下游封锁、手动 Reconnect、独立互动报告页、翻译显示和 Replay catalog 的合同缺口；Luna Max 因 403 模型不可用，没有执行；Terra 兜底实现已对 playback backend/schema/router/sql recovery、控制页、Reconnect、Pause/Continue、Finish 初步接线和 Replay catalog 做了部分修改。
- 尚未完成：互动/报告独立页的完整接线、测试翻译只切换公开发言显示、共享 OpenAPI/WS/生成 Client/响应 allowlist/迁移合同融合、partial stopped 的全链路权限与列表语义、停止/暂停重启和并发反例的完整测试、Docker 重建、真实浏览器回归、Sol 最终核验、唯一共享 Excel 同步和可复现提交。
- 当前工作树保留大量未提交改动，且既有 Wave 3 改动与本轮部分 playback 改动混在一起；不得执行清理、回滚、强制格式化、`down -v`、提交或推送。恢复工作时先做窄范围 diff 分类，再决定是否拆分检查点。

> **当前窗口最新覆盖（2026-08-29）**：Wave 3 已完成首轮机械验收，独立 Sol 已对用户指定的五个高风险边界完成窄审并在修复后给出 `G2 PASS / P0=0 / P1=0`；Docker 已从修复后工作树重建。真实教师历史、Wave 3 三块页面、匿名课堂入口，以及互动关闭→Mock insight/report 的主流程候选均已通过。当前进入 Wave 4 前人工核验阶段；这不等于 Full Wave 3 G3、真实 Provider 或完整 Demo 已完成。以下较早条目仍保留作历史证据，不能覆盖本条最新状态。

- 只读运行核对：当前 Docker 三容器均 healthy，后端 Alembic 为 `0007_wave3_interaction_report (head)`；容器内 `CLASSROOM_PUBLIC_BASE_URL` 已配置，LLM/Embedding/TTS/Voice/Translation selector 全部为 Mock。已用既有完成辩论完成一次互动关闭、匿名 insight 和 Mock report 生成，并确认匿名入口关闭后不可提交；这些是本机候选证据，不是生产质量或真实模型验收。
- 当前 Git 不是可交付检查点：`main` 比 `origin/main` 超前 1 个提交，另有 Wave 3 共享合同、迁移、后端模块和前端页面未提交。人工候选完成前不得清理或回滚这些文件；完成后要建立可复现本地检查点。
- **Token/范围约束（本阶段新增）**：后续 Wave 3 修复、人工核验和进入 Wave 4 前的审计，只读取与当前问题直接相关的 Wave 3 后端模块、对应测试、Docker/Compose、`Project.md` 和唯一共享 Excel；不得重复扫描参考仓库、私有输入、历史归档或无关模块，除非窄范围证据明确指向它们。任何扩展扫描必须先说明原因并记录结果。

- 2026-08-29 用户完成当前 Wave 2/pre-Wave 3 页面与课堂流程检查，并认为现有候选已足够进入后续 Wave 的合同阶段；当前因此标记为 `READY_FOR_WAVE_3_G0`，只允许下一步设计和审计 M13/M14/M15 的 Wave 3 Gate，不等于 `WAVE_3_G1_AUTHORIZED`，也不解锁真实 LLM/Embedding/TTS、收费调用或公网部署；
- 同日主窗口完成只读运行复核：产品 Git 工作树干净，HEAD `6d1a3fd`；backend/frontend 健康、gateway 8080 返回 200，数据库为 `0006_pre_wave3_polish`、外键违规 0，当前有 7 个 User、5 个 Agent、3 个当前发布 Agent、8 场 Debate 和 24 个 DebateTurn；所有 LLM/Embedding/TTS/Voice/Translation selector 仍为 Mock；
- 用户已确认 landing/auth 的 7 个未提交前端文件（含 `pw3-auth.test.tsx`）就是当前最新版，不再视为来源不明并发修改。旧 `toHaveAttribute` matcher 问题已改为普通 DOM 属性断言；本窗口复验 ESLint、TypeScript、`21 files / 138 tests`、Next production build 和 `git diff --check` 全部通过。当前只剩低风险 Sol 批审记录与本地检查点，不存在功能/机械检查阻塞；在签审和提交前仍不得把这些工作树修改与 Wave 3 M13-M15 混成一个 Gate；
- 最新 TikTok 场 `73491e14-904c-4cbc-84e5-6d38712b6c54` 已完成四段公开发言和完整前驱链，但 Crystal 的两次 `matched` 实际命中恋爱关系资料 `self-disclosure-and-liking.md` 与 `novelty-and-shared-experience.md`，Kaikai 两次为 `no_match`。该结果证明检索、receipt、来源展示和 no-match 安全路径能运行，同时暴露 Mock Embedding 的语义误命中，不能作为正式 TikTok RAG 内容或真实检索质量通过证据；`RAG_PIPELINE_PASS / FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING` 保持不变；
- 最新 `how to climb the mountain` 场 `c6386491-23cc-4384-bc26-fed36b728d60` 进一步证明误命中是系统性 Mock 行为：Bowen 两轮分别以 0.328/0.545 命中 `bowen-tiktok-evidence.md`，Crystal 以 0.292/0.499 命中两份恋爱关系资料，四轮均被判 `matched/mixed`。根因不是 Mock LLM 自由判断证据，而是 256 维 signed feature hashing 受停用词、通用提示词和哈希碰撞影响，0.20/0.08 两档阈值仍接收无关文块；Mock LLM 随后固定使用第一个 receipt，于是形成“任何话题都带来源”的假象。仅提高阈值不能可靠修复，因为无关项已达到 0.545；
- 待用户授权的推荐修复为独立的 `pre-Wave3 Mock RAG honesty Gate`，不接真实 Provider：为每个 typed subquery 保留结构化 topic anchor；Mock 检索先做去停用词后的确定性词法相关性门（至少两个有意义的 topic token 与文块重合，topic 只有一个有效 token 时要求该 token 重合），通过后才应用现有向量排序；strict→relaxed 都不得绕过词法门。新 DebateRuleSet/检索策略快照记录 `mock_lexical_anchor_v2`，既有辩论与已保存 receipt 不改；草稿测试聊天使用同一 v2。该方案宁可在 Mock 中产生可解释的 false negative，也不允许无关证据伪装成 RAG 优势；它只修教学诚实性，不冒充真实语义 Embedding；
- 用户计划让另一个窗口继续非 Mock-RAG 的模块工作，并把 Mock RAG honesty 作为可并行的窄模块。并行前必须先把 landing/auth 7 文件签审并形成共同基线；最佳方式是从同一检查点使用独立 Git worktree。Mock RAG 窗口只拥有 `knowledge` 内新增 relevance policy/最小测试聊天接线、`debates/generation/retrieval.py`、`playback/generation_adapter.py` 和专用后端测试；不得修改 frontend、0007/Wave3 models/migration、OpenAPI/WS、interaction/report/history、Provider selector、Project 或共享工作簿。另一个窗口不得触碰上述 RAG 文件；共享合同和最终融合只由主窗口处理；
- 模块审计结论：项目业务模块和 Wave 依赖划分清楚，M05/M06/M10-M15/M17 的产品职责及稳定 DTO 已足够支持并行；RAG 内部技术边界仍有三处待收口——`knowledge/markdown.py` 同时拥有分块与 Mock embedding、`knowledge/services.py` 的草稿测试聊天和 `debates/generation/retrieval.py` 各自硬编码 0.20/0.08、`generation_adapter.py` 直接构造 MockVectorStore。Mock honesty Gate 应新增共享 RetrievalPolicy/anchor seam并让两个入口复用，但不得借机全仓重构；真实 Embedding/LLM Gate 后续再把 provider factory、向量维度/模型 key、snapshot重建和 playback provider fence 独立实现；
- Claude Code 交接方式由用户最新确认：不新增或强制依赖 `CLAUDE.md`、单独 Gate 清单、Git 状态交接单或逐模块精确任务 Prompt。用户会在启动 Claude Code 时明确要求它先完整阅读本文件，再只读阅读 `maya-platform/` 代码库，以本文件第0/5/8节理解当前产品权威、第11节只作历史、第12节只作原始需求副本，并以现有代码理解真实实现；完成理解后可按本文件当前状态、风险和推荐下一步继续工作，不能重写系统、回滚其他窗口改动、跳过测试或把Mock结果冒充真实服务。`Project.md + 当前代码库` 被确认足以作为Claude的项目交接上下文；
- 本机标准启动以产品 `README.md` 为准：日常只需 Docker Desktop 就绪后在 `maya-platform/` 执行 `docker compose up -d` 和 `docker compose ps`；代码/依赖/Dockerfile变化才使用 `docker compose up -d --build`；普通停止使用 `docker compose stop`，不得日常重复 bootstrap 或用 `docker compose down -v` 清理数据。

- `g0-2026-08-28.7-pre-wave3-polish` 已签 `G3 PASS`：PW3-A–E 全部完成，独立 Sol High 终审均为 `P0=0 / P1=0 / P2=0`；
- 后端全量 `321 passed`，前端全量 `21 files / 137 tests passed`；Ruff、mypy、Prettier、ESLint、TypeScript、Next build、OpenAPI/生成 Client、WS 封闭 Schema、迁移、Secret/边界检查和 Compose 均通过；
- OpenAPI 当前为 g0.7：`53` 个已实现 operation、`13` 个后续 Wave 明确占位；WS 为 `30` 个正例/`18` 个反例，browser command 为 `6/7`，private result 为 `5/6`；
- Docker 三容器健康，实际数据库为 `0006_pre_wave3_polish (head)`，外键违规为 0，7 个 Demo 账号绑定生效；登录匿名目录与 quick-login 只返回安全 DTO；
- 真浏览器检查覆盖 `1440×900 / 1280×720 / 1024×768 / 768×1024 / 390×844 / 360×800`：登录、教师首页、学生首页、知识库和课堂大屏均无横向溢出，所有可见交互目标至少 44px；课堂大屏实际渲染 2 个 3D Canvas，普通控制只剩开始/下一步/重播整场；
- 真实 Provider 调用仍为 0；M08 继续 `FAILED-DEFERRED`，`FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING` 保持不变。

- 历史 `.6` 人工验收增量代码已完成主窗口融合和独立 `gpt-5.6-sol high` 集中审计，3D、TTS 安全管线、教师 Next、当时的 OpenAPI/WS、迁移和 Provider composition 均为 `G2 PASS`；M07+M12 已通过登录后的 1280×720 真页面组合验收，真实 TTS Gate 失败并后置；该条仅保留历史证据，当前状态以上述 `.7` G3 为准；
- 历史 `.6` 全量回归为后端 `247/247`、前端 `13 files / 107 tests`，当时 OpenAPI 为 `59 paths / 68 operations`、`55 implemented / 13 later-wave placeholders`；这些数字只用于历史追踪，当前准确数字为本节开头的 `321 / 137 / 53+13`；
- 中文议题失败根因已证明并修复：历史测试场 `da32661a-2a59-45bd-9013-1e79f0a37183` 的前两段 round-one 正常，round-two A 因 Mock 将中文 topic 原样放入必问题而被英文正文 validator 两次拒绝；它不是“没接 LLM”或随机失败。现以 Node 24.14.0 `Letter && Script_Extensions=Latin` 生成 40 段共享码点表，前后端同表二分查找；创建/修改/启动三层门禁与完整拉丁变音 A1/B1/A2/B2 反例通过 Sol High 最终 `PASS / P0=0 / P1=0 / P2=0`；
- 历史英文议题 follow-up 阶段的 backend/frontend/gateway 三容器健康，Alembic 当时为 `0005_wave2_manual_advance (head)`。1280×720 教师真页面对中文议题原地拦截、合法拉丁变音议题建未启动草稿及零 turn/零 console error 均通过；当前数据库已由 `.7` 升到 0006；
- `0005_wave2_manual_advance` 的历史 fresh/repeat/populated、0004→0005、downgrade/re-upgrade、完整 Wave/Voice 指纹、命名约束/索引和外键检查通过；当前 head 以本节开头的 0006 为准；
- 3D 修复保留单材质与多材质 cardinality，并补旧透明画布缺陷的 renderer 反例。Docker 真页面两张 Avatar 均为 `ready` 且各有可见 Canvas；A2 现场为 Bowen `speaking`/Kaikai `listening`，B2 相反，waiting-next 时双方回到 `idle`。后排投影可读性仍需用户在真实教室复验；
- 教师 Next 已形成后端权威 `waiting_next`、派生 `next_turn_ready`、REST CAS、相邻 successor/公开前缀/音频/fence 复验和 WS readiness-change；前端 Next 只在 controller-ready + successor-ready 时启用，native ended/skip 不再自动播放下一位。并发、重连、multitab、stale snapshot、终态和 replay 反例通过；
- attempt=3 真实 TTS 在锁定 backend Docker 内只调用 1 次，结果为 `failed/tts_audio_invalid`；durable operation 为 failed，request/charged 均为 1，profile 保持 `preview_ready`，active preview/preview file 为 0。没有 enroll/list/exists/delete、没有重试、没有修改 `.env` 或 fallback，禁止在本 Gate 再调用；累计真实调用为 Voice enroll `1`、TTS `3` 均失败、LLM/Embedding/Translation `0`；
- 正常数据辩论 `9c9f1560-0cb5-4ddc-865c-faf51bf3ba31` 已按用户授权清理上一场仅 Mock 回放音频并完成 A1/B1/A2/B2。A1 单独公开后进入 waiting-next；刷新仍只有 A1 且 Next 可用；三次 Next 均只公开确定性相邻 turn；A2 暂停/继续通过；B2 自然结束后四段 public、Next 禁用、整场重播可用并能回到终态。旧辩论文字/来源/记录未删除，新场 4 个 Mock WAV 均可解码且总时长 4 秒；
- 用户随后启动另一场课堂测试，课程 current-audio 指针因此移离 `9c9f1560...`，该场 Mock WAV 按合同被清理。真页面暴露并已修复“旧场仍显示可点击重播”的缺陷：重播现在统一校验课程指针、public/final-ready turn、active StoredFile、canonical 非 symlink 路径、size/SHA-256 和有效 WAV；空进程缓存只能在持久事实全部通过后重建，完整/Range 响应使用同一次验证的字节快照；旧/null/未知指针在前端直接禁用整场和单轮重播并显示双语说明；

- Wave 2 M10/M11/M12 已完整执行 `G0 → G0-S → G1 → G1.5 → G2 → G3`。数据/迁移/幂等、RAG/生成、播放/音频/WebSocket/前端三路独立 `gpt-5.6-sol high` 最终全部 `PASS`；当前准确状态为 `WAVE_2_G3_PASS（Mock 两人两轮候选）`，不是 Wave 3、Wave 4 或完整 Demo；
- `g0-2026-08-27.5` 已落地为迁移 `0004_wave2_debate_playback`、14 个 Debate API、54/13 严格路由、closed WebSocket event/command/private result、不可变 participant/version/snapshot、final-ready 前驱/receipt/used evidence、两轮 validator、共享 attempt 1|2、单一 controller、current-only media ticket、Range/恢复、终态清理和 all-Mock fail-closed；
- 最终确定性检查通过：后端 `161/161`，前端 `12 files / 64 tests`，Ruff format/check、mypy、ESLint、TypeScript、Prettier、Next build；fresh/repeat/populated 0004 保留 Wave 0/1/Voice 指纹且外键检查为空。父/产品 OpenAPI 仍为 58 paths/67 operations，精确 `54 implemented / 13 later-wave placeholders`；Redocly、生成 Client、67-operation response、WS events `29/14`、commands `5/7`、private results `5/6`、generator clean-diff、13 个 route 负例、仓库/密钥边界和 Compose 均通过；
- 产品 Git 历史依次保留 `d92bf89`、`21252f3`、`e2bbb07`、`b493239`、`41343a3`、`8d4cc7c`、`fe2c793`、`b675837` 与 `b06ab86`；`.7` 候选检查点为 `d72ca5f feat: complete pre-wave3 polish candidate`。全程未 push、未建远程 PR、未公开或部署；
- 主窗口在隔离 Docker 中完成最终 TikTok 两人两轮候选：A Bowen V1.0 支持、B KaiKai V1.1 反对，严格 A1/B1/A2/B2。Bowen 命中并显示 `bowen-evidence.md`，KaiKai 走 `no_match/general_reasoning` 且来源为空；A2 向下一位提问，B2 回答并向全班提出反思问题，四段均公开且每段 80-200 词；
- 真浏览器完成开始、暂停、继续、立即跳过、停止、刷新、后端重启、整场重播和单轮重播；重播/恢复后仍只有 4 个完成生成 Job，没有再次调用 RAG/LLM/TTS。准备态不泄露下一位 speech/source，1280×720 与 360×800 无溢出，六个控制按钮均 44px，3D speaking/listening/idle 状态生效，控制台无 warning/error；
- G3 真实暴露并关闭：默认 setup controller 重建导致渲染循环、resume/action 跨 Turn 泄漏、公开前驱前缀缺口、整场重播只播第一段、延迟 media/socket/control 回调跨代、WebSocket 生命周期 Session 耗尽连接池，以及 Start/终态/Replay controller CAS 竞态。每项均有确定性反例并经 Sol 复审；
- WebSocket 现按握手、snapshot、每条 command 和 disconnect 使用短 Session；两连接池保持 5 个 WebSocket 时，GET 与需要两连接的 create idempotency replay 仍成功，关闭后 checked-out 回落基线。Docker Desktop 下禁止在容器运行时从 macOS 宿主直接打开同一 bind-mounted SQLite/WAL；在线检查只走平台 API 或容器内连接，宿主 SQLite 仅在后端停止后使用；

- Wave 1B/1C 已逐项执行 `G0 → G0-S → G1 → G1.5 → G2 → G3`。M08 音色安全审计、M02/M07/M08 前端审计与跨合同/迁移审计最终均为 `PASS`；没有由实现者自签；
- M07 已提供 3 个稳定参数预设、1 个诚实标注的兼容 GLB、Three.js r185 本地画布/Draco、`idle/listening/speaking/thinking/nod_yes` 状态和静态降级。桌面与 360px 真浏览器均无横向溢出，Civic Observer 完整默认参数和 `speaking` 状态实测生效；当前不宣称有 3 个不同建模资产；
- M08 已提供 `voice_profiles/voice_provider_operations/voice_previews`、迁移 `0003_wave1b_avatar_voice`、AES-GCM 映射、组权限、流式上传、FFmpeg、短期平台播放 URL、确认/绑定/删除、系统/组作用域、供应商 Saga、完整分页、IP 固定下载、DNS/connect/read 总超时和 flock 临时目录租约。每个 profile 全生命周期只有一条 delete ledger，并经双请求并发对抗证明只调用一次 Provider；
- M02 已完成全站 `en-US/zh-CN` 静态界面和服务端首帧 Cookie，Locale 不重建 Session/PlatformApi、不增加读取/写入请求、不翻译业务内容，并保留 AGENT.md、选中文档、pending File、冲突和幂等重试句柄。登录、学生 Agent 工作台和教师页在 1280/360px、刷新、SSR、控制台、V2 样式和链接矩阵上均通过；
- Wave 1 的历史验收仍保持：后端 70、前端 40、隔离 Docker Agent/RAG/Avatar/Voice/i18n 全链均通过；Wave 2 `.5` 与 `.6` 的 161/64、204/72、54/13、55/13 均为历史数字，当前准确验收数字只认本节开头的 321/137/53+13；
- 主窗口用隔离 Docker 数据完成 8080 全链：Agent → Mock 音色上传/试听/确认 → Avatar/Voice 绑定 → Markdown RAG → 不可变发布 → 教师安全投影 → 试听过期 → 音色删除/自动兜底 → 跨组 404 → 后端重启恢复。保留预览 WAV 和 enrollment 临时目录均为 0；隔离测试数据已移到废纸篓，正常数据库恢复到 `0003`，三容器健康；
- 真实系统音色注册只调用 1 次并成功；用户源音频未修改，临时副本/中间文件为 0，供应商侧克隆音色仍存在。历史两次 TTS 与本次 attempt=3 均失败；最新 profile 保持 `preview_ready/tts_audio_invalid`，没有激活 `FALLBACK_VOICE_PROFILE_ID`，也没有再试、静音或浏览器朗读；
- 当前累计真实调用计数为 Voice enrollment `1`、TTS `3`、LLM `0`、Embedding `0`、Translation `0`；本次短句成本估算低于 0.01 元。`RAG_PIPELINE_PASS`；`FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING`；
- 唯一 V2 共享工作簿已原位同步 V1.0“正在查看”、204/72、`41343a3`、两张 3D 真页面、TTS 后置和 Next 音频清理确认边界；重新导入关键值准确、公式错误扫描为 0，两张表视觉渲染通过，输出目录仍只有这一份 xlsx；
- 在 `.6` 结束时正常 Demo 数据库为 `0005` head；`.7` 已升级为 `0006_pre_wave3_polish (head)` 且外键检查为空。历史隔离 G3 目录仍在可恢复位置且未永久删除；
- 本机 `.env` 与 Demo 凭据继续为 0600，数据根 0700，数据库 0600；`/opt/homebrew/bin` 已由用户收紧为 0755。API Key、Authorization、Base64、external voice ID 和私人源路径未进入 Git、Project、共享 Excel、前端或普通日志；
- `.6` 当时的活动范围仅为 3D真实可见、一次真实TTS诊断和教师逐回合Next；当前 `.7` polish 已完成。Wave 3/4、投票、弹幕、Maya报告、完整历史/翻译、真实LLM/Embedding仍继续锁定。

### 2.2 Wave 1A 历史进度审计（2026-08-27 02:33）

- Wave 1A 已提交检查点 `bed2211 docs: freeze wave 1a implementation gate` 与 `d4e5c08 feat: complete wave 1a agent rag workflow`；产品仓库当前 133 个跟踪文件，工作树干净，父目录/参考仓库/本机私有凭据未进入 Git；
- M05 已实现同组多 Agent、V1.0/唯一草稿/V1.1、revision CAS、AGENT.md 编辑/上传、发布锁定、当前发布指针、历史版本、归档/取消归档；M06 已实现 UTF-8 Markdown 上传/复用/隐藏/下载、100,000 字符原子检查、确定性标题/段落分块、256 维 Mock float32 向量、`top_k=6` 检索、matched/no_match、草稿 RAG 预览、重索引、不可变发布快照与来源下载；M09 已实现教师课程内当前发布列表和全部已发布/历史快照只读检查，教师看不到草稿，其他组统一 404；
- 数据库已从 `0001_wave0_baseline` 升级到 `0002_wave1_agents_rag`，新增 Agent/版本、知识文档/草稿关联、文档与快照 chunk、StoredFile/FileReference、Job、FileOperation 和 Idempotency 等 13 张表；空库重复升级和带 Wave 0 seed 的 `0001 -> 0002 -> head` 保真测试均通过，固定 seed fingerprint 未变化，43 项约束/索引得到检查；
- Wave 1A 后端使用独立提交的 upload/publish journal、同文件系统 staging/fsync/原子 promote、claim-token/lease 幂等和启动恢复；Sol 初审发现的教师草稿泄漏、伪 journal、过期 worker、重索引非原子、跨快照关系和不可达 422 业务错误均已修复并补对抗测试；
- 前端新增登录/Session 容器、学生首页/小组/知识库/Agent 创建与版本工作台、RAG 测试/发布、学生已发布快照检查、教师已发布列表/详情。Sol 初审发现的身份切换旧状态、stale revision 覆盖本地内容、快照正文串版、UI 幂等 Key 未接线和 V2/i18n 漂移均已修复；最终 ESLint、TypeScript、22 个 Vitest 与 Next 生产构建通过；
- 主窗口完整确定性复验通过：冻结安装/格式、Ruff、mypy、pytest `28/28`（仅上游 Starlette/httpx deprecation warning）、前端 22/22、空库/带数据迁移、冻结 OpenAPI/hash/generated Client、Redocly、响应与 WebSocket、route 12 个负例、仓库/密钥边界、Compose；FastAPI 与冻结合同精确匹配 33 个已实现 operation，剩余 34 个后续 Wave 占位仍有明确 owner/reason；
- 主窗口冷构建前后端镜像并完成真实 8080 隔离数据链：学生登录、Agent/V1.0、AGENT.md、Markdown/index、matched/no_match、发布、教师已发布快照/RAG 下载、另一组 404、后端重启后同一版本/快照仍存在。运行文件均为 0600，数据根为 0700，应用 SQLite 为 foreign keys on/WAL/busy timeout 5000/空外键违规；隔离 smoke 数据已移到用户废纸篓，正常 Demo 数据库已升到 0002 且没有混入测试 Agent；
- 实际浏览器桌面与 360x800 登录页检查通过：无横向溢出、触控按钮 44px、标签/表单语义完整、控制台无 warning/error；视觉检查未在浏览器内输入密码，授权业务页由 8080 API 竖切和组件测试覆盖；
- 唯一 V2 共享工作簿已原位同步 Wave 1A G3：M05/M06/M09、M16/M17/M18 证据、33/34 契约、28/22 测试、检查点 `bed2211 + d4e5c08`、当前风险和 Wave 1B/1C 下一步均已写入；值/公式错误扫描为 0，两张表完成导出后复读和视觉渲染，根入口仍指向同一文件，未创建第二份基准；

- Wave 0 建立了独立产品 Git 仓库 `Maya/maya-platform/`；当时检查点含 90 个源码/合同/测试文件。Maya 根目录与参考/私有目录没有被纳入 Git；Wave 1A 后当前数量和边界以本节最前方 133 文件审计为准；
- M01 已建立 Caddy 8080 单入口、Next.js V2 壳、FastAPI/SQLite 本机运行边界、三服务 Compose、锁定镜像 digest、前后端 Dockerfile、健康探针、`.dockerignore`、`.env.example` 和一键安全本地初始化入口；
- M03/M04/M16 已实现数据库会话、12 小时不透明 Cookie Session、HMAC CSRF、Origin 检查、预置身份切换、教师/学生课程与小组只读权限、精确 UUIDv5 seed、SQLite WAL/foreign keys/busy timeout、Alembic 基线和脱敏错误 envelope。组织对象在同一条带成员关系的 SQL 中限域，跨组/跨课程返回 404；
- M17/M18 已提交父 OpenAPI 的字节一致副本与 SHA-256、`openapi-typescript + openapi-fetch` 生成 Client；Wave 1A 后严格语义比较覆盖 33 个已实现 operation，剩余 34 个后续 Wave 显式占位；67-operation 响应、29/11 WebSocket、生成 clean-diff、仓库/生成代码/强制跟踪凭据扫描、不可变 GitHub Action SHA 和不可跳过的 Mock CI 均通过；
- 安全初始化命令为 `pnpm bootstrap:local`：交互式生成随机会话密钥和 7 个 Argon2 Demo 账号哈希，只写入被 Git/Docker 忽略且权限为 0600 的 `.env` 与 `backend/config/demo_users.yaml`，默认 Provider 均为 mock，不写供应商 Key；
- 主窗口最终确定性检查通过：冻结 pnpm 安装、Prettier、ESLint、TypeScript、Vitest `3/3`、Next build、Ruff、mypy、pytest `14/14`（只有上游 Starlette/httpx deprecation warning）、Alembic 空库升级两次、迁移库 seed 两次、严格 API 语义、响应 allowlist、WebSocket clean-diff、route 11 个负例、初始化器安全探针、Secret/边界扫描和 Compose config；
- 三张冻结基础镜像已下载，首次前端和后端应用镜像构建成功；宿主机真实 `ffmpeg/ffprobe 9.0.1` 已安装，后端镜像把 FFmpeg 固定为 Debian `7:5.1.9-0+deb12u1` 并在构建中验证版本，Python 运行依赖改由 `uv.lock` 冻结同步；
- G0-S 设计审计最终 `PASS`。G2 两路 Sol High 初审提出的 Alembic 绕过、全局对象预加载、未知异常、API 语义浅比较、CI 静默跳过、生成目录扫描、WebSocket 生成漂移、初始化和 FFmpeg 可重复性问题均已修复；两路最终窄复审均为 `PASS`；
- 用户再次重启 Docker Desktop 后引擎恢复为 `running`。前端 no-cache 生产镜像一次构建成功；后端第一次 no-cache 构建只因 Debian 镜像的单个 `libxau6` 下载返回临时 502 失败，未改任何冻结版本，原样重试后以固定 FFmpeg `7:5.1.9-0+deb12u1`、uv 0.12.0 和 `uv.lock` 成功构建；
- `docker compose up -d --wait` 已启动 `gateway/frontend/backend`。8080 首页/前端健康返回 200；后端未认证 `/auth/me` 返回 401，教师登录、同 CSRF 恢复、7 个安全身份列表、切换至 `student-bowen-1`、退出和旧 Session 失效均通过；容器内 FFmpeg/ffprobe 5.1.9、Alembic `0001_wave0_baseline (head)`、live/ready、精确 `7 users / 1 course / 7 course members / 2 groups / 6 group members`、WAL 和空外键违规检查均通过；
- 因此 M01/M03/M04/M16/M17/M18 均已 G3，Wave 0 Mock 基础没有剩余 Gate 阻塞；当前运行中的三服务只覆盖基础壳、认证、组织只读和质量契约，不包含完整 Demo 业务页面；
- 该条记录 Wave 1A 当时的后置状态：当时百炼/兜底/3D 尚未联调且 `/opt/homebrew/bin` 为 0777；现已由 2.1 更新为百炼凭据+真实注册已完成、真实 TTS 待决、Three.js 单头脸已验收、目录权限已由用户收紧至 0755；
- 唯一开发共享工作簿仍为根入口 `开发文档.xlsx` 指向的 `outputs/20260826-pre-code-preflight/开发文档-模块对齐-V2唯一共享基准.xlsx`；当前已原位同步 Wave 0 + Wave 1A G3、检查点 `c4387a2 + f207977 + bed2211 + d4e5c08`、模块证据、风险和 Wave 1B/1C 路线，并完成表值/公式错误与两张表视觉复核，未创建第二份基准。

## 3. 已有本地参考资产

### 3.1 `RomanticSimulation`

可重点复用或改造：

- FastAPI + PostgreSQL + Redis Worker + Next.js 的前后端骨架；
- 多角色平等参与、多轮调度和完整历史上下文；
- Agent turn、scene message、状态、审计日志和回放数据结构；
- OpenAI-compatible 模型调用和无 Key 时 mock 降级；
- Docker Compose 启动方式。

不应直接照搬：恋爱关系图、人格关系指标、固定场景 01-10、裁判结算等领域逻辑。

### 3.2 `Document Validation Agent`

可重点借鉴：

- Agno Agent 的注册、指令、工具调用和运行模式；
- RAG 检索、Markdown 索引和上传文件状态传递；
- 模型统一封装、流式返回和工具边界；
- FastAPI 服务组织方式。

风险：该项目含内部服务地址、特定数据库/认证配置及大量文档校验领域代码，不适合作为本项目整体底座；只能提取通用模式或经过清理的独立模块。

### 3.3 新下载的 GitHub 素材

- `OpenMAIC-main`：本轮已完成核心静态阅读，适合参考课堂视觉、播放状态、Agent/TTS 配置和测试习惯；不作为产品底座；
- `parallax-main`：适合参考 FastAPI 后端的 domain/application/ports/adapters 分层、RAG 收据、多 Agent trace 和 TTS 异步阶段；不照搬招生筛选业务、Celery/Redis/Supabase/R2；
- `OpenAvatarChat-main`：留到 M07/M08 之前专项阅读 Avatar/ASR/LLM/TTS 可替换接线；当前不把其实时双工会话复杂度引入 Demo；
- 三个目录均已保留根 `LICENSE`：OpenMAIC 为 MIT，Parallax 与 OpenAvatarChat 为 Apache-2.0；子包、模型和资产仍需单独核验。

## 4. 当前技术路线判断

当前建议采用“自研业务架构 + 有边界的局部参考”，而不是在四个想法中机械四选一：

1. 由本项目自己的 OpenAPI、ERD、权限和状态机定义产品骨架；`RomanticSimulation` 只用于核对多角色调度、异步执行和回放的局部思路，不作为目录、领域模型或运行基础；
2. 从 Document Agent 只查看 Agent、工具与 RAG 的接口模式，不复制其多格式文件解析平台、内部配置或领域代码；
3. 在本项目自己的契约冻结后，按模块、带具体问题参考成熟开源项目；不先选一个仓库再把需求迁就到它的数据模型；
4. 课程、小组、权限、智能体版本、发布、课堂投票和弹幕属于本项目独有业务，采用轻量自研。

主架构方向已确定为自研；具体库和可合法复用的局部代码仍需在对应模块 Gate 前复核。

### 4.0.1 GitHub 参考门槛与首轮筛查（2026-08-26）

GitHub 的作用是减少某个通用模块的试错，不是替代本项目设计。执行规则如下：

- 先由主窗口根据冻结需求写出业务对象、接口、状态机和验收标准，再带着一个明确问题查看参考仓库；禁止从参考仓库反推或改写本项目核心需求；
- 只有经统一需求覆盖评分达到 80% 的项目才允许进入“整体底座候选”；低于 80% 一律标记为“局部参考”，不得整仓改名、整仓搬运或继承其领域模型；
- 每个模块最多指定一个主要参考仓库和一个备选；没有明确可验证收益就不引入代码，避免参考过多造成架构漂移；
- 禁止直接复制粘贴参考代码、整段改名或沿用外部领域对象；只把观察到的设计原则写进本项目 Gate Packet，再由实现者依据 Maya 的 DTO、状态机和验收测试独立实现；
- 不从参考仓库引入源码。若 Maya 依法安装和调用第三方依赖包，必须核验依赖许可证、锁定版本并记录用途；参考仓库只读设计思路。3D 素材在私下本机 Demo 只记录来源并验证技术兼容，不做许可 Gate；公开分享、交付或正式课堂前再核验模型/素材条款；
- 评分是基于本项目需求的覆盖估算，不代表项目本身的代码质量或学术价值。首轮权重为：学生制作/版本发布 15、检索式 RAG/来源 15、两轮多 Agent 辩论 15、教师控制/大屏 10、TTS/数字人 10、课堂互动/Maya 报告 10、账号权限/历史数据 10、Provider/测试/可维护性 15。

首轮没有任何项目达到 80%；因此不选整项目模仿对象：

| 优先级 | 官方仓库 | 需求覆盖估算 | 只参考什么 | 明确不照搬什么 | 许可边界 |
| --- | --- | ---: | --- | --- | --- |
| 1 | [THU-MAIC/OpenMAIC](https://github.com/THU-MAIC/OpenMAIC) | 约 56% | 多 Agent 课堂场景、播放状态、TTS/Provider、前端课堂表现和测试组织 | 它是“由主题/文档生成课程”，不是学生创建并版本发布 Agent；现有 RAG 主要是未接课堂主链的独立词法索引契约，不是本项目的逐 Agent 向量证据 RAG；也没有匿名投票/弹幕和 Maya 闭环 | 根仓库 MIT，但子包/模型/资产仍要逐项核验 |
| 2 | [olamideba/parallax](https://github.com/olamideba/parallax) | 约 47% | Next.js + FastAPI、Qwen、RAG 收据、多人辩论、TTS 异步阶段和 ports/adapters 分层 | 招生邮件筛选领域、Supabase/Celery/R2 部署、裁决业务和邮件流程 | Apache-2.0；仍只取局部模式 |
| 3 | [TechAtNYU/ClassroomLM](https://github.com/TechAtNYU/ClassroomLM) | 约 36% | 课程隔离知识库、教师上传资料、RAG 教学价值的产品表达 | 没有学生 Agent 版本发布、多 Agent 辩论、语音/3D、课堂互动和 Maya | GitHub 首页未显示明确根许可证；未澄清前只读不复制 |
| 4 | [erickong/agent-roundtable](https://github.com/erickong/agent-roundtable) | 约 28% | 开场→质疑→修正→主持总结的轻量辩论语义、FastAPI/WebSocket 演示 | 规模小、缺少 RAG/课程权限/TTS/3D/互动，不作为工程底座 | MIT；复用前仍锁定 commit |
| 5 | [HumanAIGC-Engineering/OpenAvatarChat](https://github.com/HumanAIGC-Engineering/OpenAvatarChat) | 约 22% | ASR/LLM/TTS/Avatar 可替换边界、百炼 + CosyVoice 接线、说话头异常隔离 | 它是单 Avatar 实时对话系统，不是课堂、多 Agent 或 RAG 产品；不引入其整套实时会话复杂度 | Apache-2.0；数字人/TTS 模型各有独立条款 |
| 6 | [dayeonki/cultural_debate](https://github.com/dayeonki/cultural_debate) | 约 20% | “多文化知识互补 + 辩论 + 自我反思”的研究问题和对照实验思路 | 这是 ACL 研究代码/数据集，不是课堂产品；不含发布、RAG 服务、语音、3D 或互动 | GitHub 首页未显示明确根许可证；只读研究思路 |

较大的通用项目 [Dify](https://github.com/langgenius/dify)、[Langflow](https://github.com/langflow-ai/langflow) 和 [CAMEL](https://github.com/camel-ai/camel) 只作为工作流/RAG/Multi-Agent API 的二级索引；不建议下载后当本项目底座。Dify 使用带附加条件的 Dify Open Source License，Langflow 为 MIT，CAMEL 为 Apache-2.0。[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) 只作为 Live2D/音频表达参考，且其 v2 正在重写、Live2D 示例资产另有许可；本项目当前 3D TalkingHead 路线不应围绕它重构。

建议素材库按顺序一次只下载一个仓库、读完并形成“可取/不可取/许可证/对应模块”四栏笔记后再决定是否下载下一个。第一份应看 OpenMAIC 的产品与课堂表现；进入技术架构讨论时再看 Parallax。OpenAvatarChat 只在 M07/M08 接线前查看。其余仓库先保留链接，不增加本地噪音。

### 4.0.2 OpenMAIC 本地代码结论（2026-08-26）

已对本地 `OpenMAIC-main` 0.3.2 做静态代码阅读。该下载目录没有 `node_modules` 和 Git commit 元数据，因此本轮没有执行其测试/构建，也不把“代码看起来完整”等同于已经在本机验证通过。规模快照为约 542 个 `lib` 文件、308 个组件文件、44 个 API route、498 个测试文件和 14 个 E2E 文件：它是一套成熟但很大的通用 AI 课堂产品，不是适合直接裁剪的 Demo 模板。

它的主链路是“用户输入主题/文档 → AI 生成课程大纲 → 逐场景生成内容/动作/媒体/TTS → Stage 加载 → PlaybackEngine 顺序执行 → Roundtable 展示与互动”。Maya 的主链路则是“学生版本化发布 Agent/RAG → 教师选 Agent → 确定性两轮辩论 → 课堂互动 → Maya 报告”，两者领域核心不同。

值得学习的部分：

1. **视觉语言而非整页复制**：课堂舞台、半透明控制 Dock、发言头像高亮、准备/播放状态、可折叠气泡、同屏角色和 Motion 动画值得作为 Maya 大屏风格参考；
2. **状态到视图的纯映射**：`lib/playback/derived-state.ts` 用 `computePlaybackView()` 把大量原始状态归一成 `phase/bubbleRole/activeRole/buttonState`，`components/roundtable/presentation-speech-overlay.tsx` 又先构造纯 `PresentationBubbleModel` 再渲染；Maya 应采用同样的“后端权威状态 → 小型纯 view model → 组件”思路；
3. **播放异步防陈旧结果**：`lib/playback/engine.ts` 使用 playback generation 令牌、pause/resume/stop 分离、cursor、回调和取消检查，避免旧音频/旧异步回调在切换后继续推进；Maya 应把同类 generation/control version 放在后端权威状态机中；
4. **动作执行与调度分开**：`lib/action/engine.ts` 把动作执行从播放调度剥离，并区分同步动作与 fire-and-forget；Maya 可以把 `avatar_state/audio/playback` 作为表现 Adapter，不让它们决定辩论业务状态；
5. **Agent 配置与权限化动作**：`AgentConfig` 将 persona、角色、允许动作、UI 颜色和音色绑定分开，并在运行时再次过滤允许动作；Maya 可借鉴类型边界，但配置必须来自服务端已发布 `AgentVersion`，不能存成浏览器 localStorage 真相；
6. **RAG 可追溯类型**：`lib/rag/types.ts` 的 resource/resourceVersion/chunk/locator/lineage、范围隔离、原子 replace/delete 和 metadata filter 很适合借鉴到 `KnowledgeSnapshot`；测试也覆盖了替换、范围、确定性 hash 和失败诊断；
7. **音色注册防御细节**：`lib/audio/voice-registration.ts` 和 Qwen adapter 中的 Provider-neutral 接口、存在/未知三态、并发 enrollment 合并、超时/Abort、分页检查、删除、响应校验、音频下载域名白名单和大小上限值得移植成 FastAPI/Python 版本；
8. **质量习惯**：大量纯函数、单元测试、迁移/范围/竞态/播放恢复测试和 Playwright 页面对象值得学习。Maya 不需要相同测试数量，但每个 Gate 必须有契约测试和一条真实用户路径。

明确不能照搬的部分：

- OpenMAIC 的 LangGraph `director` 让 LLM 决定下一位 Agent；而 Maya 的 A-E 顺序和固定两轮由 `DebateRuleSet` 确定，不能为本可确定的路由多花一次 LLM 调用，也不能允许模型改赛制；
- OpenMAIC 的 server graph 每次请求最多只执行一个 Director→Agent，连续多 Agent 由客户端多次请求串联；Maya 的整场调度、失败终止、预生成、权限和历史必须由后端统一掌握，不能依赖教师浏览器维持正确性；
- OpenMAIC 虽已有 RAG 类型、文档分块和 `InMemoryLexicalIndex`，但当前生产代码搜索显示这些实现主要停留在独立库/测试，索引能力标明 `vector=false`，尚未接入课堂讨论主链路；Maya 必须实现真实 Embedding + 向量检索 + 发言证据绑定，不能把这部分当作现成 RAG；
- 它按最多约 1200 grapheme 字符分块、无本项目已定的 Token overlap；Maya 继续采用适合英文 Markdown 的 500-800 Token + 80-120 Token overlap 初值并实测；
- OpenMAIC 允许客户端知道/选择 Provider，并在部分请求中传 provider、base URL 甚至客户端 key；它的可选 PostgreSQL persistence 文档也明确说明公开 token 不提供用户隔离。Maya 前端必须只认识平台 API，真实 Key、供应商和课程权限只在 FastAPI 后端；
- `Roundtable` 约 2140 行、`PlaybackChromeRoot` 约 1678 行，视觉优秀但组件过度集中。Maya 不复制这两个巨型组件，应拆成 `DebateStage`、`AgentTile`、`SpeechBubble`、`EvidencePanel`、`ControlDock`、`InteractionOverlay` 等小组件；
- OpenMAIC 会根据课程要求自动生成人设，并有浏览器缓存声音参考片段的路径；这与 Maya 的教学真实性和“原声音样本请求后删除”边界冲突。Maya 只允许学生自己写 `AGENT.md`，也不缓存原始声音来维持效果；
- OpenMAIC 同时包含课件、PBL、白板、编辑器、图片/视频、Web 搜索、PPTX/MP4 等大量能力，全部不进入 Maya Demo。

结论：OpenMAIC 是 Maya 的**课堂视觉与播放工程参考**，Parallax 更适合做**FastAPI 业务分层参考**，Maya 自己的版本发布、权限、向量 RAG、确定性辩论、免登录课堂互动和文明互鉴报告仍由自研核心负责。

### 4.1 Demo v0.1 3D 参考栈（2026-08-25 更新）

用户已下载并放入 Maya：`TalkingHead-main`、`motion-engine-main`。已检查两者包含各自 LICENSE；MotionEngine 还包含一个约 3.7 MB 的演示 GLB，README 标注角色来自 Ready Player Me。私下本机 Demo 可先做兼容测试；若要随仓库公开、交付他人或用于正式课堂，再单独核验该资产授权。

1. [`met4citizen/TalkingHead`](https://github.com/met4citizen/TalkingHead)：MIT，保留为 Demo 主要网页运行参考；只使用头肩/头部镜头、英语口型、眨眼、眼神、头部运动和表情，不要求显示身体。
2. [`lhupyn/motion-engine`](https://github.com/lhupyn/motion-engine)：MIT，已经下载；Demo 仅使用头脸可见的 `mood`、点头、思考等动作，不接手势、身体姿态和摄像头 FaceMirror。
3. [`google/GNM`](https://github.com/google/GNM)：Apache-2.0，2026 年公开的参数化 3D Head 模型，可通过身份、表情和头姿参数生成多样头脸，包含眼球、牙齿和舌头；它比 Rocketbox 更贴合“只要3D脸、最终最多10个人物”的方向。但官方包不是 TalkingHead 即插即用资产，Demo 直接接入前仍需导出/烘焙为浏览器可用头部模型，因此作为新一代头脸素材生成参考，不列为首个竖切的硬依赖。

Microsoft Rocketbox 继续可作为 MIT 全身人物库，但不再是 Demo 必需项。NVIDIA `Audio2Face-3D-SDK` 是 2025 年后的新型音频驱动脸部动画方案，MIT 且效果强，但要求 CUDA/TensorRT/NVIDIA GPU，留给正式版评估，不放入单人 Demo。

历史名人素材可以从 Smithsonian 3D Open Access 获取 CC0 扫描，例如 Abraham Lincoln 生前面模和 Presidential Portraits 系列；但这些是静态扫描，不自带英语口型、眨眼或 ARKit Blendshape，直接变成会说话的头需要重新拓扑和表情绑定。Demo 建议用通用/历史风格 3D 头脸加人物姓名卡表示角色，不以精确历史人物外貌为验收项；正式版再从 CC0 扫描或合法定制资产中选择不超过 10 个并完成统一绑定。

所有第三方仓库应放在 Maya 独立参考目录，不得直接混入产品源码。每个仓库保留原始 `LICENSE`，产品只选择实际需要的代码/资产，并记录来源、版本和转换步骤。

## 5. Demo v0.1 已确认范围

### 5.0 语言边界

- Demo 的辩论议题、智能体人设、知识库证据、模型提示、生成发言、引用说明和克隆语音默认使用纯英文；英文发言是唯一权威原文；
- Demo 长度规则按英文单词数而不是中文字符数执行；
- 网页界面支持 `zh-CN` / `en-US` 两套静态文案切换，导航、按钮、表单、提示、状态和错误信息均从 i18n 资源读取；
- Demo 正常辩论和 Maya 报告流程不自动调用中文翻译，也不等待翻译；课堂默认只产生和展示权威英文内容；
- 教师测试界面提供一个“翻译当前全部内容”按钮。点击后才通过独立 `TranslationProvider`，批量翻译当时已经正式展示/完成的全部英文 `DebateTurn` 和当前 Maya 报告修订；后台尚未公开的预生成内容不纳入；
- 每次点击只翻译尚无有效译文或英文内容哈希已变化的项目；翻译结果按 `content_type + content_id + source_text_hash + target_language` 缓存/保存。之后产生新发言或新报告时不会自动翻译，教师可以再次点击补齐；
- 中文翻译只是测试用派生展示内容，不回填到 RAG、后续辩论上下文、英文长度校验、TTS、投票或报告生成输入；翻译失败不改变任何英文内容和辩论/报告状态；
- “界面语言”和“辩论内容语言”是两个独立配置。切换中文界面只改变网页静态文案，不会自动翻译辩论内容；已有按需译文时可展开查看；
- 数据结构保留 `ui_locale`、`debate_language`、`knowledge_language`、`voice_language` 和 `translation_language`，Demo 默认分别为可切换、`en`、`en`、`en`、`zh-Hans`。

### 5.0.1 教学真实性、可见因果与“不代做”原则（已确认）

本项目的核心不是让所有 Agent 看起来都聪明，而是让学生清楚看到“自己写好 Agent、整理好 RAG，输出才会明显变好”。平台不得通过隐藏补全制造虚假的教学效果：

- 平台系统提示只提供安全边界、辩论阶段任务、输出 Schema、长度和引用规则；不得暗中替学生补写人物身份、价值观、论证策略、事实、来源或漂亮措辞；
- `AGENT.md` 为空时禁止发布；内容稀疏、矛盾或写得差时，Agent 应自然表现为身份不稳定、论证泛化或缺乏说服力。测试页可以指出缺失和风险，但不自动改写，也不把建议偷偷并入运行提示；
- 每次正式发言必须真实执行该 Agent 快照的检索。无匹配证据时保留 `no_match + general_reasoning + 空来源`，不联网补证据、不从其他 Agent 的 RAG 借资料、不伪造引用；
- 平台也不得故意削弱“无 RAG/差 Prompt”基线来夸大产品效果。明显差异必须来自学生输入本身：相关资料、合理分块/检索、真实来源，以及清楚的人设和策略；
- 大屏和测试页要把因果显示出来：当前使用的 AgentVersion、检索状态、真实命中文块/文件、引用和无命中状态都可见；不能只展示一段漂亮答案却隐藏它是否用了 RAG；
- Demo 正式 RAG 验收必须使用用户提供的 TikTok 公开资料。研发时可以用明确标记的占位 Markdown 验证管线，但不得把占位结果宣传为正式知识效果；
- 验收时做一组非产品化的受控对照：相同模型、议题和规则下，对比“结构清楚的 `AGENT.md` + 相关 RAG”与“稀疏 Prompt 或无匹配证据”。好 Agent 应表现出稳定身份、至少两个可核对的来源支撑和针对性回应；弱 Agent 允许继续一般推理，但必须没有伪来源且明显更泛化。此对照用于证明因果，不新增 Evaluation 产品模块；
- 主窗口发现某个功能只有展示噱头、不能形成可观察的教学收益，或成本/复杂度明显大于课堂价值时，必须直接说明并建议删减；不得为了迎合而声称它有用。

### 5.1 固定验收数据

- 1 个预置教师账号；
- 2 个预置学生小组；
- 每个小组 3 名预置学生，共 6 名学生；
- 每个小组创建并发布 1 个文化智能体，共 2 个参辩智能体；
- Group A 的智能体名称为 `Bowen`，Group B 的智能体名称为 `KaiKai`；
- 平台额外预置 1 个名为 `Maya` 的教师报告 Agent；Maya 不属于学生小组、不占参辩顺序编号、不作为参辩者或投票对象，用于在所有参辩 Agent 完成发言和课堂投票/弹幕收集后生成“文明互鉴报告”；
- Demo 英文辩题固定为：`Should the United States ban TikTok's recommendation algorithm?`；
- 两组所需公开资料由用户后续提供；资料到位前开发使用明确标记的占位英文材料，不把占位材料当作正式事实来源；
- 默认验收场景使用 Bowen/KaiKai 两个参辩 Agent 和固定 2 轮，因此总计 4 个 `DebateTurn`；Demo 允许教师选择 2-5 个参辩 Agent 并将其按点击顺序排列为 A/B/C/D/E，但 Demo 不提供轮数选择器；正式版再重新设计可配置轮次；
- Demo 不为 2 人、3 人、4 人、5 人分别建立规则集，而使用同一个参数化顺序轮转规则；所有参辩回合完成后，教师再单独打开二维码互动收集，结束收集时 Maya 额外生成 1 份 `CivilizationMutualLearningReport`。

### 5.2 固定验收流程

1. 在统一 Demo 首页右侧直接点击始终可见的教师身份卡免密进入教师账号；用户名/密码表单同时常驻可见，不再折叠或跳转到第二张登录页；
2. 查看预置课程、两个小组及每组 3 名成员；
3. 切换至学生身份，共同配置本组知识库、智能体人设、3D 形象和音色；
4. 两组分别发布一个锁定的 V1.0 智能体版本；
5. 切换至教师身份，从当前课程每个智能体的“当前已发布版本”中依次点击选择 2-5 个参辩者；系统按点击先后自动赋予连续字母槽位 A/B/C/D/E，该字母顺序就是每轮发言顺序；默认验收先点 Bowen 得到 A，再点 KaiKai 得到 B；Demo 创建页不提供历史版本选择或单独槽位编辑器；
6. 输入辩论议题，并为每名参辩者选择“教师指定立场”或“开放阐述”后创建固定 2 轮辩论；创建成功时固定所有参辩者的 `agent_version_id + knowledge_snapshot_id`，后续发布新版本不影响本场；
7. 规则引擎使用参数化 `ordered_multi_agent_rounds_demo_v1`：每轮按教师设置的 A→B→C→D→E 实际选中顺序依次发言；例如 3 人 2 轮为 `R1-A → R1-B → R1-C → R2-A → R2-B → R2-C`；
8. 第一轮为“观点呈现轮”：每个参辩 Agent 读取议题、当前人设和自身知识快照，执行 RAG 检索，清晰输出自己的初始观点、核心理由、真实命中证据与当前总结；本轮默认不强制反驳或回答提问；
9. 第二轮为“文明互鉴说服轮”：每个参辩 Agent 读取第一轮全部发言和本轮已公开发言，重新执行 RAG 检索，回应/反驳至少一个具体观点、提出一个有针对性的问题、根据新证据和他人观点更新自己的 `current_position_summary`，并通过证据、礼貌、准确回应和真实观点更新进行文明说服；不得伪造证据，不得使用“请投我一票”等直接拉票或操纵性话术；本场最后一个参辩 Agent 没有下一位可提问时，改为向全班提出一个开放的反思问题；
10. 最后一轮最后一个参辩 Agent 完成后，Maya 仍不运行；教师在大屏页手动打开“课堂互动收集”并展示当前辩论的二维码；
11. 任意数量的课堂观众通过手机扫码进入免登录页，先输入昵称，再看到两个彻底独立的功能区：“选择一个参辩 Agent 并提交投票”与“输入一条弹幕并发送”；观众可只做其中一项，也可两项都做，先后顺序不受限制；
12. 投票成功后只将投票区切换为“投票成功”并禁用，弹幕区仍可操作；弹幕成功后只将弹幕区切换为“发送成功”并禁用，投票区仍可操作；两项都完成后手机页只显示总体完成状态；刷新页面后两区都重置并可重新提交；
13. 后端分别接收 `Vote` 和 `BarrageMessage`：投票记录不保存昵称，弹幕记录保存自填昵称与文本，两者没有共同提交 ID 或可追溯关联；大屏独立追加昵称弹幕并更新各 Agent 票数/占比；
14. 教师手动点击“结束收集并生成报告”后，入口关闭并分别冻结最终匿名票数与按提交顺序保存的全部原始弹幕；原始“昵称 + 文本”继续保留在大屏/教师历史中。后台只取弹幕文本、去掉昵称，通过独立洞察步骤聚类相近意见、筛除与辩题无关或没有实际语义的内容，并由代码根据真实消息 ID 计算每个主题数量；Maya 只读取辩题、全部参辩发言、问答/反驳链、已使用证据、最终票数和验证后的匿名弹幕主题/典型问题/数量；如两类互动都为空，仍生成报告并明确写“本场无课堂互动数据”；
15. 教师大屏通过 WebSocket 接收后台准备/播放状态、正式展示的英文正文、引用、可回放语音、新弹幕、票数和报告更新；匿名手机页不跟随辩论播放，也不接收这些展示事件；教师需要测试中文时手动点击“翻译当前全部内容”；
16. 课堂流程结束后查看本场全部计划参辩发言、Maya 文明互鉴报告、可选按需中文译文、来源文件、弹幕和投票统计；默认两人两轮为 4 次发言；只要教师尚未启动本课程下一场辩论，本场全部已生成语音都可通过普通教师页面逐步式整场重复播放，不提供按 Agent/轮次的单回合重播。

### 5.3 账号与权限

- 第一阶段使用预置账号：1 名教师、6 名学生；不接学校统一身份认证；
- Demo 账号由后端私有目录 `backend/config/demo-accounts/` 管理：仓库只提交不含秘密的 `README.md` 与 `accounts.example.md`；真实 `accounts.private.md` 被 Git/Docker 忽略并固定 0600。用户明确接受 Demo 简化：私有文件可保存不可变 `account_key`、`username / display_name / password / role=teacher|student / group`，由用户直接增删行；`account_key` 是映射既有 User UUID 的稳定短键，修改 username 或用同一 key 删除后重加都不能更换历史身份；教师 group 为空，学生必须属于一个预置小组；
- 修改私有账号 Markdown 后重启 backend：先完整解析/验证 desired graph，再在单个 `BEGIN IMMEDIATE` writer transaction 中同步。新增/修改行 upsert User/CourseMember/GroupMember；删除行撤销全部 Session、移除当前成员关系并把 User 标为 inactive；同一 key 重加时恢复原 User UUID。密码、username、角色、小组或 active 状态变化均撤销该 User 现有 Session；重复 key/用户名、未知角色/小组或缺字段必须 fail-closed、阻止 ready，旧数据库状态保持不变；不物理删除历史 User；
- `accounts.private.md` 在本 Gate 完成后是唯一运行账号/凭据来源；旧 `demo_users.yaml` 只允许作为一次迁移/回滚备份，禁止长期双读或按加载顺序覆盖；
- `DEMO_MODE=true` 且 `DEMO_QUICK_LOGIN=true` 时，未登录页面也可取得只含平台 user ID、显示名和 teacher/student 角色的安全身份目录，并通过后端 quick-login 创建/旋转 Session 与 CSRF；account key、密码、用户名、哈希、小组 key、成员关系细节、配置路径和原始 Markdown 行都不能进入 DTO、错误或普通日志；用户已明确 Demo 期间不做 localhost/LAN 限制，任何能访问 Demo 站点的人都可选择任一 Demo 身份；关闭任一 Demo 开关后目录和免密入口统一 404；
- 前端快速身份选择必须调用统一后端认证接口，不能靠前端自行伪造用户 ID；统一首页右侧始终显示身份卡和常驻用户名/密码登录，两种方式共用同一认证与会话边界；
- 数据库仍建立 `User`、身份凭证预留字段、`CourseMember`、`GroupMember` 等正式结构；
- API 仍通过统一的当前用户上下文执行权限判断，不允许业务代码依赖写死的教师或学生 ID；
- Demo 身份切换只是一种开发认证 Provider，未来可以替换为密码登录、OAuth 或学校 SSO，而业务 API 路径保持不变。
- 学生账号是“课后制作账号”：只负责本组多个 Agent、`AGENT.md`、RAG Markdown、3D 和音色的创建、修改、发布、安全删除及查看；可看到本组资料库、本组草稿、当前已发布版本和历史版本，不能列出、读取、下载、引用、修改或删除其他组的任何 Agent/MD/RAG/音色数据；只有从未发布且从未参辩的 Agent 可物理删除，有历史时禁止删除；
- 教师账号是“成果检查与课堂演示账号”：首页显示当前课程和全部当前已发布 Agent；可进入详情查看制作小组、当前/历史发布版本、冻结 `AGENT.md`、RAG Snapshot/来源、3D 与平台音色状态，但不能看到或编辑学生未发布草稿，也不能浏览未被任何已发布版本绑定的组内资料；课堂辩论页负责创建、当前/历史列表和操作台；上课时只从每个 Agent 的当前发布版本中选择；
- 学生制作账号不是课堂运行依赖：参辩 Agent 是已发布的课程成果，创建它的学生无需登录或在线，辩论仍由教师独立创建、启动和控制；
- 课堂观众不属于 `User` 账号角色，也不是六个学生制作账号的延伸。只有在全部参辩发言结束、教师手动打开互动入口后，观众才可以通过二维码进入免登录一次性表单；
- 匿名手机页先要求自填昵称，之后提供互不关联的“投票”和“弹幕”两个功能区；不展示辩论正文、3D、语音、引用、报告、课程成员、小组工作台或教师后台；“匿名”表示不登录、不关联学生账号；昵称只随弹幕展示，不写入投票记录；
- 课堂控制实行后端权限分离：普通教师播放 Dock 只提供“开始辩论 / 下一步 / 重播整场”，普通 UI 不显示 Pause/Continue；整场 Replay 逐段等待 Next。课堂 phase 只投影 ready/in-progress/waiting/finished；Finish 只在 live waiting 且连接/控制权有效时显示并可用。后端继续保留经过审计且被进程恢复/异常围栏使用的 pause/resume primitive，并提供不出现在普通页面的本机 operator reset。翻译、打开/结束互动收集和触发 Maya 仍只属于当前课程教师；匿名手机页只能在入口开放期分别调用投票提交和弹幕提交 API；
- 权限不能只靠前端隐藏按钮。所有教师控制 API 都必须由后端根据 `CourseMember.role=teacher` 和 `course_id` 校验，学生直接请求时返回 `403 forbidden`；
- 正式结构仍允许同一课程有多名并列教师并拥有同等课堂管理权限；Demo 种子暂时只有 1 名教师，但接口和权限判断不得写死该账号。

### 5.3.1 小组内容权限矩阵（已确认）

权限隔离必须以服务端真实组织关系为准，不能依赖页面隐藏或相信请求中的 `group_id`：

| 操作对象 | 当前小组成员 | 同课程其他小组学生 | 当前课程教师 |
| --- | --- | --- | --- |
| 本组 Agent、草稿、`AGENT.md`、组内 Markdown 资料库 | 创建、查看、网页编辑、关联、发布；可彻底删除无发布/无参辩历史 Agent | 不可见；列表中过滤，直接猜 ID 也按不存在处理 | 不可见未发布草稿；不能编辑 |
| 当前及历史已发布 AgentVersion | 查看完整内容 | 不可见 | 查看/下载完整冻结内容；不能编辑 |
| 组内未被发布版本启用的 Markdown | 查看、下载、启用/停用 | 不可见 | 不可见 |
| 已发布版本绑定的 RAG 快照与来源 Markdown | 查看/下载 | 不可见 | 查看/下载，用于检查和历史复现 |
| Agent 彻底删除 | 仅从未发布且从未参辩时允许；一次确认后物理删除 Agent 与草稿，不删除小组共享 Markdown | 不可见；按不存在处理 | 不允许；有历史时稳定保留 |

所有 Agent、文档、草稿、快照、音色查询都先由当前用户推导允许的 `course_id/group_id`，再在同一个数据库查询中限定归属；不得先按全局 ID 读出对象再只靠前端判断。跨组的列表、详情、下载、测试聊天、关联文档、发布、description 编辑和删除请求统一返回 `404 not_found`，避免泄露对象是否存在；同组但角色不允许的操作才返回 `403 forbidden`。同组删除有历史 Agent 返回稳定 `409 agent_history_retained`。发布时还必须验证 Agent、草稿、每个启用文档、音色与 3D 配置均属于同一小组，禁止通过伪造 ID 把其他组资料绑定进快照。

### 5.3.2 Demo 课程、小组与身份操作范围（已确认）

原始正式需求包含教师创建课程、学生按课程号加入、学生建组/邀请、组长移交、多管理员和移除组员。为集中验证 Agent、RAG、音色、3D 和课堂辩论，Demo 已确认使用固定组织种子：

- Demo 只使用 1 门预置课程，7 个账号已经加入；页面可查看课程号、课程名和成员，但不实现创建/删除课程、搜索课程或按课程号加入；数据库仍使用真实 `Course/CourseMember` 关系，不把课程写成前端常量；
- Demo 只使用两个预置三人小组；不实现建组、邀请、退组、移除成员、设置管理员或移交组长；成员列表只读；正式版再开放这些操作；
- 两个小组内的 3 名成员在 Demo 对本组多个 Agent、组内 Markdown 资料库、`AGENT.md`、RAG 启用关系、3D、音色、版本发布、description 编辑和无历史 Agent 安全删除拥有相同权限，并继续使用 revision/CAS 防覆盖；学生不能读取或编辑另一组内容，教师只查看完整的已发布历史成果、不代替学生编辑且看不到未发布资料；
- 六个学生账号只用于演示两个小组的制作与发布流程，不用于课堂入场、弹幕或投票鉴权；课堂不会因学生账号离线而中断；
- 保留真实用户名/密码登录并在统一首页右侧常驻显示；`DEMO_MODE=true + DEMO_QUICK_LOGIN=true` 时同一区域始终显示后端身份目录并可免密选择任一 Demo 账号，用户接受 Demo 期间对所有可访问站点的客户端开放；身份 DTO 不返回密码，关闭任一开关后身份目录/免密入口完全不可用；
- Demo 不创建伪装成可用的课程/小组写接口：只实现当前页面需要的课程、小组和成员读取 API。正式版的创建/加入/邀请/角色变更路径在 OpenAPI 扩展说明中预留，但在实现前不返回假成功。

### 5.4 知识库与引用

- Demo 的 RAG 知识输入只接受 Markdown（`.md`）；不接受 PDF/TXT，不做 OCR、格式转换、正文抽取或页码解析。学生既可上传本地 `.md`，也可在组知识库网页输入文件名和 Markdown 正文来新增/编辑；
- 平台不检查内容是否重复，也不因文件名相同而原地覆盖旧字节；每次上传或网页新增都创建带独立 `document_id` 的不可变 `KnowledgeDocument`。完全相同的内容可以重复存在，并分别计入 RAG 总字符数；
- 业务层只执行一个容量规则：每个 Agent 当前草稿中全部启用的 Markdown 内容合计最多 100,000 个字符。计数使用 UTF-8 解码、统一换行后的实际 Markdown 文本字符数，不包含平台插入的来源标记；新增文件会导致超限时，整个新增操作被拒绝，原草稿和索引保持不变；
- `.md` 扩展名、UTF-8 可读取和非空是让系统能够读取文件的最低技术条件，不属于内容解析或质量审核；Demo 不判断资料真假、质量、重复度或是否有利于辩论；
- 小组空间直接保存上传的 Markdown，Demo 文件布局建议为 `data/groups/{group_id}/knowledge/md/{document_id}/{source_filename}`、`data/groups/{group_id}/knowledge/drafts/{agent_id}/RAG.md`、`data/groups/{group_id}/knowledge/snapshots/{snapshot_id}/RAG.md` 和对应本地向量索引；不再设置 `originals/processed/` 转换层；
- `KnowledgeDocument` 归属于小组资料库，而不是天然归属于某一个 Agent；同组多个 Agent 草稿都可以从资料库中明确勾选复用同一文档，跨组永远不可见、不可引用；
- 小组知识库可在没有 Agent 草稿时新增 Markdown；新增文件只进入组资料库，不自动启用到任何 Agent，也不自动创建 Agent/版本。只有学生主动点击“创建智能体”或“创建新版本”得到可编辑 `AgentVersion` 草稿后，才能明确启用资料；已发布版本及其 RAG 页面保持只读；
- 从某个 Agent 草稿页面上传成功的 Markdown 会保存进当前小组资料库，并默认只启用到该草稿；同组其他 Agent 不会自动读取一份全新文档，但可以由学生在各自草稿中明确勾选启用；每个 AgentVersion 通过独立关联表维护自己的启用文档集合；
- 编辑已有组内 Markdown 使用 copy-on-write：请求带旧 `document_id + expected content/index revision或hash`，先以 `staged/pending` 创建新文档、文件、chunks 和索引，未 promote 前不得出现在资料库或草稿候选。捕获引用旧文档的全部当前草稿及 revisions，最后在单个 `BEGIN IMMEDIATE` writer transaction 中重新读取完整引用集合、确认仍为当前 draft、替换其 enabled/disabled 关联并逐个增加 revision；只对 enabled 关联重算 100,000 字符。发布、另一编辑和 replacement 使用同一 writer/CAS 防线，只能一个成功；任一草稿已发布、revision/引用集合变化、超限、索引/CAS/文件/数据库失败时整个替换失败，旧文档和所有草稿不变；
- replacement 文件、chunks、vectors 与状态变化必须走可重启恢复的 typed file-operation journal；失败/崩溃不能留下 active orphan。没有草稿引用时，成功 replacement 仍成为当前组资料库文档；旧文档只在无当前草稿关联后 hidden，已发布 Snapshot/source bytes 与 hash 永不改变；
- 自动覆盖只作用于当前未发布草稿，包括已有 V1.0 后正在编辑的 V1.1 草稿；没有草稿的 Agent、`published/superseded` AgentVersion、KnowledgeSnapshot 和已创建/完成辩论永不跟随。旧工作区文档在不再被草稿使用后可隐藏，但为已发布快照/历史引用保留；
- 系统只按当前 Agent 草稿明确启用的文档顺序合并其草稿 `RAG.md`，每份来源前加入机器可读标记，例如 `<!-- source: evidence-a.md; document_id: ... -->`；同一草稿内可以多次上传、勾选复用、停用、重试索引和测试，不会因为每次修改而增加版本号；
- 系统不“解析文档格式”，但仍必须完成 RAG 技术处理：直接按 Markdown 标题和段落分块，首轮建议每块约 500-800 Token、相邻块重叠 80-120 Token，并保存 `chunk_id`、`document_id`、`source_filename`、文本位置和向量；
- 单个 Markdown 的读取、分块、Embedding 或索引失败不影响同批其他文件；失败文件标记为 `failed`，不能进入草稿的可用 RAG 或测试聊天；只要当前草稿仍包含失败文件，发布校验就不通过，学生需先重试成功或删除/停用该文件；
- 网页“编辑 Markdown”就是受控的不可变 replacement/revision，不提供原地覆盖历史文件。需要移除内容时，从当前草稿停用或在资料库隐藏；已发布快照始终保留发布时内容；
- 学生和教师可从已发布历史下载冻结 `AGENT.md`、合并 `RAG.md` 和每个来源 Markdown；下载文件名必须在原始基名后附加清理后的 Agent 名和版本号，例如 `evidence--Bowen--V1.0.md`、`AGENT--Bowen--V1.0.md`、`RAG--Bowen--V1.0.md`。多来源重名时再加稳定序号；`Content-Disposition` 使用安全 ASCII fallback + UTF-8 `filename*` 并拒绝路径/控制字符；下载仍执行同组学生/课程教师权限，只是快照副本，不重新启用或改写工作区；
- `RAG.md` 不会在每次发言时作为全文提示词发给模型；它是供分块、索引、快照复现和教学预览的合并语料；
- 每次测试聊天/辩论发言前，后端使用 `辩题 + 当前立场（若教师指定）或当前观点摘要 + turn_goal + 对方最新具体论点 + 待回答问题` 构建检索查询，从当前 AgentVersion 的向量索引中召回相关文块；
- Demo 检索初值建议为 `top_k=6`；只把命中文块的文本和来源元数据注入当前 LLM 请求，同时仍传入本场此前所有发言和结构化待回答问题；
- 发布智能体时，系统将草稿 `RAG.md`、文块、向量和来源元数据固化为不可变、版本化的 KnowledgeSnapshot；V1.0 永久只检索发布时锁定的 S1，小组修改知识后必须发布 V1.1/S2 才能影响未来新建辩论，V1.0/S1 不被静默改变；
- 每次发言都必须实际执行 RAG 检索；首次无相关命中时自动放宽查询重试 1 次。两次仍无相关证据不算系统故障，也不终止辩论：允许 Agent 使用一般常识、价值判断和对上文的逻辑分析继续发言，但不得伪造来源、具体数字或声称知识库支持了该观点；
- 单次发言保存 `retrieval_status=matched|no_match` 与 `grounding_mode=rag_grounded|mixed|general_reasoning`。只有真实命中的文块才能进入 `sources`；无命中时 `sources=[]`，前端显示“未检索到相关知识库证据/一般推理”，有命中时显示“RAG 证据”及来源文件名，使课堂上能直观看到有无优质 RAG 的差别；
- 前端和普通辩论记录中的来源标注只显示上传时的 Markdown `source_filename`；不强制展示原文片段；同名文件在内部仍由 `document_id` 区分；
- 后端保存 `document_id`、Markdown 文本位置和实际命中文块，便于排错与报告复现，但这些内部字段不作为 Demo 前端必填展示；
- 引用属于每个 `DebateTurn` 的结构化字段，不能只拼在大模型生成的正文中。

### 5.4.1 文化智能体如何创建：`AGENT.md` + RAG + 平台规则

Demo 将“创建智能体”设计成一个由学生主动触发、教学上可解释的组合，而不是上传文件后自动出现 Agent：

1. 学生点击“创建智能体”，系统才创建稳定的 `Agent` 身份和它的 V1.0 草稿；填写名称（Demo 为 Bowen/KaiKai）和简介；
2. 学生在网页 Markdown 编辑器中自由编写 `AGENT.md`，作用类似 Claude/Codex 项目中的角色说明文件；
3. 学生向该 Agent 的 RAG 工作区上传一个或多个 `.md` 文件；每个文件直接进入草稿索引，不经过 PDF/TXT 转换；
4. 平台将 `AGENT.md`、当前启用的 Markdown 集合、3D 头脸配置和 `voice_profile_id` 组合成一个 `AgentVersion` 草稿；
5. 学生用测试聊天验证人设、引用和英语输出；
6. 发布 V1.0 后，`AGENT.md`、知识库快照、3D 和音色形成不可编辑版本关系，教师课堂调用的就是该版本。

平台不规定人设字段，不强制 `Identity`、`Position` 等栏目，也不判定学生“必须写什么”。编辑器是一张自由 Markdown 纸张：学生可以从空白开始、粘贴自己的 `.md` 文件，也可点击“插入参考大纲”获取以下可删除示例：

```markdown
# Identity
Who are you and what cultural or social perspective do you represent?

# Background
What background should shape your interpretation of the topic?

# Position
What is your current position on the debate topic? What trade-offs do you recognize?

# Speaking Style
How should you speak: formal, analytical, concise, rhetorical, cautious, etc.?

# Debate Strategy
How should you respond to opponents, use evidence, concede valid points, and distinguish fact from opinion?

# Boundaries
What should you avoid claiming or doing?
```

这些栏目只是教学提示，不进入数据库独立字段、不做必填校验，学生可以全部删除或使用任意标题。Demo 只校验文件是非空的可解析 Markdown，不限制写作栏目或内容结构；单份 `AGENT.md` 最多 12,000 个字符。

关键边界：`AGENT.md` 不是知识库。它主要定义“是谁、站在什么角度、怎么说”；知识工作区内的其他 `.md` 文件进入 RAG，定义“有哪些可引用事实”。即使二者扩展名都是 `.md`，也必须通过两个不同入口和数据类型管理；学生可以把背景摘要写进 `AGENT.md`，但具体事实、数字和引用材料应放入 RAG Markdown。

每次辩论发言的后端输入按以下层次组装：

1. 平台不可修改规则：纯英文、80-200 词、每次必须执行 RAG 检索、只能引用真实命中文块、无命中时必须明确转为一般推理且不得伪造来源、只代表当前 Agent 发言；
2. 学生 `AGENT.md`：身份、可能的自身观点、语言风格和策略；
3. 教师辩题和本场规则；
4. 根据当前辩题、教师指定立场（如有）或当前观点摘要、对方论点和待回答问题，从该 AgentVersion 知识快照检索出的结构化证据文块；
5. 本场此前所有发言；
6. 当前轮次和发言者信息。

灰色边界处理：

- 如果 `AGENT.md` 要求伪造资料、忽略引用或突破平台长度/语言规则，平台规则优先；
- 如果首次检索没有命中相关证据，后端使用更宽的查询自动重试 1 次；仍无证据时允许继续作一般推理，不将其视为 RAG/LLM 失败，也不因此终止整场，但必须返回空来源和明确的无命中状态；
- `AGENT.md` 可由学生在网页直接创建/编辑，也支持上传 `.md` 文件；平台内部以 Markdown 文本和版本快照保存；
- RAG 只接受 `.md`，但上传到知识工作区的 Markdown 与作为人设配置的 `AGENT.md` 是两个不同入口、不同数据类型；
- Demo 不允许学生添加任意代码工具、联网工具或自定义函数；“Agent”在 v0.1 中是受控的人设 + RAG + 辩论上下文生成器；正式版再评估工具调用能力。

### 5.4.2 智能体发布与 RAG 版本关系（已确认）

原始业务需求已经明确：知识库是智能体的知识来源；已发布版本（如 V1.0）锁定且不可直接编辑；修改需要新建 V1.1，V1.1 编辑期间不影响 V1.0；教师调用当前已发布版本。原始需求没有明确写出“小组后来修改或删除知识文件时，V1.0 是跟着变化，还是继续使用发布时的知识”，因此需要技术层补齐版本语义。

已确认采用不可变快照绑定，不让已发布版本跟随实时知识库：

1. `KnowledgeBase` 是小组持续上传和停用 Markdown 的共享资料库；每次上传创建一个新的独立文档记录，不做内容去重或同名覆盖；只有本组成员和当前课程教师在“已发布快照范围内”有权看到相应内容，其他组完全不可见；
2. 每个 `AgentVersion` 草稿只使用学生明确启用且索引成功的 Markdown，可反复测试；新建资料不会自动全部喂给 Agent。唯一自动变化是：学生编辑一份已经被一个或多个未发布草稿启用的组内 Markdown 时，copy-on-write replacement 会原子更新这些草稿对该逻辑资料的引用和 revision；这仍只改变草稿，不等于发布；
3. 第一次发布前，学生可以在 V1.0 草稿中多次新增、删除/停用和测试 Markdown；这些操作都只增加草稿的内部 `revision`，不会产生 V1.1；
4. V1.0 发布后，该版本和 S1 都只读，任何“更新”都不得原地改写 V1.0。学生点击“创建新版本”后，系统从当前发布版本的 `AGENT.md + 已启用 RAG Markdown + 3D + 音色` 克隆出一个可编辑 V1.1 草稿；
5. 学生可以在同一个 V1.1 草稿中多次修改 RAG；这些操作仍只更新 V1.1 草稿的内部 `revision`，直到学生主动发布；Demo 同一 Agent 同时最多保留一个可编辑草稿，避免并行草稿混淆；
6. 点击发布时才创建不可变 `KnowledgeSnapshot`，记录当时启用的 Markdown 文件副本/关系、合并 `RAG.md`、文块、向量索引命名空间、来源文件、处理参数和内容哈希；
7. 已发布 `AgentVersion V1.0` 只绑定该 `KnowledgeSnapshot S1`，课堂检索始终在 S1 内执行；
8. 小组在 V1.1 草稿新增 `new-evidence.md` 后，草稿测试可以使用它；在学生再次点击“发布”前，教师仍只能使用 V1.0/S1，`new-evidence.md` 不会进入课堂；
9. V1.1 发布成功后产生 S2 并成为未来新建辩论可选的唯一当前版本；教师不能再用 V1.0 创建新辩论，但仍可查看/下载 V1.0/S1；V1.0/S1 不被静默改变；
10. Demo 教师创建辩论时只从每个 Agent 的“当前已发布版本”中选择，不在创建页提供历史版本选择器；
11. 辩论创建后立即把具体 `agent_version_id + knowledge_snapshot_id` 固定到 `DebateParticipant`；即使开课前或课堂中发布 V1.1，本场仍继续使用创建时的 V1.0/S1；
12. 新发布的 V1.1 不改写已经创建或完成的辩论；历史辩论始终显示当时使用的 Agent 版本和来源文件。
13. 任何发布版都可重新下载其冻结 `AGENT.md`、合并 `RAG.md` 和来源文件；平台在下载文件名后附加 Agent 名与版本号，保证从浏览器保存后仍能辨认归属和版本；下载不改变当前工作区。

学生端把版本操作明确拆成四类语义，避免“更新当前版本”被误解为覆盖已发布数据：

1. **继续编辑草稿**：如果当前 Agent 已存在唯一的未发布草稿，就继续修改它；只增加草稿内部 `revision`，不增加版本号；
2. **创建新版本**：只有当前存在已发布版本且尚无草稿时可用；克隆当前发布版本为下一个草稿，例如 V1.0 → V1.1；
3. **发布更新**：把当前草稿冻结为新的不可变版本和知识快照，并切换 `current_published_version_id`；旧发布版本转为“历史可查看、不可新选”；
4. **彻底删除 Agent**：只在该 Agent 从未发布且从未进入任何辩论时可用；一次确认后删除 Agent 与其草稿/草稿关联，小组共享 Markdown 不随之删除。有任一发布版、KnowledgeSnapshot 或 DebateParticipant 引用时拒绝并返回 `agent_history_retained`，不得级联破坏历史。

因此用户所说“更新当前版本的 Agent”在 Demo 中解释为“继续编辑已经存在的下一版草稿，并在发布后把它设为新的当前版本”，绝不解释为原地修改已发布的 V1.0。这样既满足老师只选择最新版本，也保留历史课堂的可复现性。

Demo 提供简单的网页 Markdown 新增/编辑，但底层仍保持不可变文档和 copy-on-write replacement；即使文件名或内容相同也生成新 `KnowledgeDocument`。编辑成功后自动更新所有引用旧文档的未发布草稿，不触碰 S1/S2 等已发布快照；若学生从当前草稿删除一份已被 V1.0 使用的 Markdown，系统只把当前工作区记录标为停用/隐藏，继续保留 S1 中的文件内容、文块、向量和来源关系，供历史辩论复现及教师下载；只有不存在任何发布快照或历史辩论引用时，未来清理任务才可物理删除。

因此“新增/编辑/启用 Markdown”和“发布智能体”是两个动作：前者只改变组资料库和未发布草稿，后者才把该 Agent 此刻的 `AGENT.md + 明确启用的 RAG Markdown + 3D + 音色` 冻结为教师可用版本。全新文档不自动影响其他 Agent；编辑已启用文档会自动更新所有当前草稿引用，但绝不自动对教师当前发布版或已创建辩论生效；只有明确发布成功才切换该 Agent 的当前版本。

### 5.4.3 智能体发布前置条件（已确认）

学生端可以一直保存不完整草稿，但后端只有在以下条件全部满足时才允许发布；前端显示同一份发布检查清单并据此启用“发布”按钮，后端仍需再次权威校验，不能只依赖前端禁用状态：

1. `AGENT.md` 非空且不超过 12,000 个字符；不校验固定栏目；
2. 当前草稿至少有 1 个启用的 RAG Markdown 已成功完成分块、Embedding 和索引；
3. 当前启用 RAG Markdown 合计不超过 100,000 个字符；
4. 当前草稿没有任何启用中的 `failed` / 未完成索引文件；失败文件必须先重试成功或删除/停用；
5. 已选择一个可用的 3D 头脸模板并保存必要参数；
6. 音色不再是发布阻塞项：已绑定且 `ready` 的自定义 VoiceProfile 时使用自定义音色；没有自定义音色，或自定义音色未就绪/已删除时，自动解析为系统兜底音色；
7. 草稿测试聊天不是发布必需条件，学生可以不测试直接发布。

发布校验失败时不丢失草稿，API 返回稳定的 `publish_blockers[]`，例如 `agent_md_missing`、`rag_missing`、`rag_over_limit`、`rag_index_failed`、`avatar_missing`，前端将其翻译成中英文提示。`voice_profile_id` 允许为空；API 始终返回实际用于播放的 `effective_voice_profile_id` 和 `voice_fallback_active`。兜底音色真实 ID 属于已确认的后置接入任务，编码期先用 Mock/种子占位验证逻辑。

### 5.4.4 Agent description 与安全删除（pre-Wave 3 已确认，待最终执行授权）

- `Agent.description` 是 Agent 级展示元数据，不是 `AGENT.md`、RAG 或 AgentVersion 快照的一部分；创建 Agent 时可填写，之后本组学生可在小组工作台的 description 区域直接编辑、保存、取消或清空；
- 学生首页、小组工作台和教师当前发布 Agent 卡片都读取同一当前 description：有非空内容时原样显示，null/空串/纯空白时留空，不显示“定义身份和证据集”“还没有简介”等伪默认文案；空态仍保留可点击区域，桌面 hover/focus 和手机常显铅笔图标提供可发现性；
- description 修改使用 `metadata_revision` CAS；同组学生可改，跨组按不存在返回 404。成功后立即反映到学生和教师“当前 Agent”页面，但不增加 AgentVersion revision、不重建 Snapshot，也不进入辩论输入。发布历史行、冻结下载和既有辩论/回放不读取或展示 mutable description；若历史 Snapshot 页面同时保留当前 Agent 页头，必须明确标记为“当前简介”并与冻结版本区隔，本 Demo 不新增 `frozen_description` 或用当前值冒充历史值；
- Agent 详情页提供权威“返回小组工作台”按钮，使用该 Agent 的 `group_id`，不依赖偶然的浏览器历史；有未保存编辑时必须确认，不能静默丢失；
- 删除替代归档：`DELETE /agents/{agent_id}` 在单个 `BEGIN IMMEDIATE` writer transaction 中重新检查归属以及无 published/superseded AgentVersion、KnowledgeSnapshot、DebateParticipant或其他历史引用后，才物理删除 Agent、草稿、草稿关联和 Agent 测试态；不删除组内共享 Markdown、VoiceProfile、AuditLog或其他Agent。Publish、Debate创建和Delete共享最终 writer/FK 防线，竞态只能一个成功。当前模型没有 Agent-owned 文件，因此本 Gate 不做文件删除；若实现发现此类文件必须停止并补 typed journal，不得裸删。已有历史返回409 `agent_history_retained`；教师不能删除，跨组404；不再提供普通归档/取消归档 UI。

### 5.5 模型与辩论规则

- 已确认 Demo 使用阿里云百炼（Alibaba Cloud Model Studio）华北2北京地域；一个服务端 DashScope/百炼 API Key 用于文本模型、声音复刻和 TTS；
- 文本默认模型固定为 `qwen3.7-plus-2026-05-26` 的非思考模式，避免 `latest` 别名升级导致 Demo 输出漂移；
- 开发环境保留 `qwen3.7-flash-2026-07-15` 作为低成本可选模型，但主验收不得在运行中自动换模型；
- 第一版只实现一个真实 `LLMProvider`，同时保留 `MockLLMProvider` 供无 Key 测试；
- 规则引擎负责轮次、发言顺序、停止条件和失败状态；Demo 不接受教师配置或执行整场/单回合硬超时，只按固定两轮、词数和语速控制预计节奏；正式版未来增加超时时也必须由规则引擎负责；大模型只负责生成当前智能体的一次发言；
- Demo 的规则快照固定 `round_count=2`，教师页面不提供轮数选择；规则对象仍保留类型化轮次/阶段配置，正式版可新增其他 `DebateRuleSet`，但 Demo API 对非 2 值返回稳定校验错误；整场总时长和单次发言上限字段只作为可空的正式版兼容字段，Demo 创建请求必须为空且不执行硬时间规则；
- 每次英文发言最少 80 词、建议目标 160-185 词、最多 200 词，问题文本计入总词数；业务层由 `TurnValidator` 严格校验 200 词上限；
- 模型响应还包含结构化元数据，不能把 200 个英文单词简单等同于 200 Token；单次生成建议暂用 `max_output_tokens=512`，真正的产品上限仍由 `speech` 字段的词数校验保证；
- 如果正文短于最低限制，最多自动补写/重试 1 次；超过最长限制时优先要求模型压缩，失败后按完整句子边界截断，不能从句子中间硬切；
- 单个英文发言的模型调用、输出校验或必要 RAG 组装失败时最多自动重试 1 次；重试仍失败则立即将整场 `Debate` 标记为 `failed`，不再执行后续智能体或后续轮次；
- 失败前已完成的文字发言、按需译文、来源、已生成语音、弹幕和投票仍保留供排错；模型/RAG 生成失败后仍不允许从失败回合继续，教师需新建运行记录；这里与正常播放状态下的暂停/断点继续不是一回事；
- 教师普通课堂 Dock 只显示“开始辩论 / 下一步 / 重播整场”；普通 UI 不显示 Pause/Continue。Finish 只在 live waiting 时出现在页头。普通 REST 控制面为兼容恢复仍保留 `startDebate / advanceDebatePlayback / pauseDebate / resumeDebate / finishDebate / replayDebate`，但 pause/resume 不进入标准产品控制；继续移除 `skipTurnPlayback / stopDebate / replayDebateTurn` 及其普通页面入口。WebSocket controller/media/started-ended ack/play_failed、snapshot/watermark/gap恢复与延迟结果围栏继续保留，不能为了表面精简破坏安全状态；
- operator reset 只有一个入口：不进入 OpenAPI、生成浏览器 Client或普通页面的本机 backend CLI，必须显式传入 debate ID 和确认。它在单个 writer transaction 中撤销 controller epoch/ticket、取消或围栏未完成 task、增加 control version并写 AuditLog；异常 live 安全转为 stopped，异常 replay 恢复 completed 完整历史；与 Next 串行化且只能一个成功，匿名/学生无法调用；
- 已发出但无法在供应商侧强制取消的请求，即使稍后返回结果也必须由后端 generation fence 丢弃，不再推送、不播放、不启动下一轮；
- 教师点击“开始”后只公开并播放第一个计划 turn；当前 turn 的音频自然结束后，后端进入权威 `waiting_next`（最终命名由增量合同冻结）状态，当前内容继续可见但不得自动公开或播放下一位。只有教师点击“下一步”，后端 CAS 校验当前 turn、控制版本和下一位 ready 状态后，才公开并播放下一位；依次重复直到最后一个 turn 完成；
- 后台仍可按固定计划悄悄完成下一位 Agent 的 RAG/LLM 与 TTS，且两名 Agent 的后续内容可以在课堂操作间隙逐步准备；最多保持一位超前准备，准备完成只推送不含正文/来源的 ready 状态。教师未点“下一步”前，下一位的正文、来源、音频 URL 和 speaking 状态均不得出现在前端；
- 网页刷新或短暂断线后，按后端保存的当前 turn、mode、waiting_next 和 cursor 恢复；整个后端进程重启后，从被中断 turn 的开头重新播放，不重新调用 LLM/RAG/TTS；`failed` 和 operator-reset 后的 `stopped` 仍是不可恢复终态；
- 教师启动下一场前必须看到确认框，明确说明“将删除上一场可回放语音，但保留文字记录”；确认后才清理和启动，取消则两项都不执行；
- Demo 普通页面只提供整场重播，不提供单回合重播。点击“重播整场”后使用已保存的文字、来源和 retained audio，从 A1/第一计划 turn 重新开始；前端恢复为首次 Start 后的逐步展示，只显示已重播到的 transcript 前缀。每段结束进入持久 `status=waiting_next + mode=replay`，REST/snapshot/`playback.waiting_next` 同步返回 completed turn、control version和`next_turn_ready`；Replay readiness只在唯一相邻public turn通过当前课程audio pointer、active StoredFile、canonical path、size/SHA-256/可解码WAV复验后为true。`ended_ack`不得自动prepare；只有Next CAS成功才移动唯一相邻turn并发出一次media.prepare。最后一段结束后清除controller/ticket/replay queue/index/cursor，发出`replay.completed`并恢复完整历史视图。任何重播都不得重新调用RAG/LLM/TTS、改变原发言、投票或报告；
- 迁移`0006`允许Replay的waiting_next但不削弱Live约束；downgrade把`mode=replay + waiting_next`确定性映射为非播放`mode=live + status=completed`，清除replay queue/index/controller/ticket/cursor并保留turn、课程指针和历史，禁止旧代码恢复自动Replay；
- 历史真实 TTS 技术试听两次失败并已停止；新授权采用独立 durable attempt=3，最多一次短英文 TTS、无自动 retry、0 enroll/list/exists/delete。成功必须经技术音频和平台同源试听；失败/timeout不激活 fallback且禁止静音、浏览器朗读、1秒 Mock 音或文字模式冒充成功。真实四回合中失败是终止 turn、终止整场或教师重试仍待后续冻结；
- 播放语速根据最终英文词数和目标发言时长动态计算，限制在 `0.95x-1.25x`；Qwen3-TTS-VC 的 HTTP 合成先生成正常语速音频，前端使用 `audio.playbackRate` 并保持音高进行轻量调速；超过 1.25x 仍超时时，缩短文字而不是继续加速；
- 2026-08-25 官方信息快照：`qwen3.7-plus-2026-05-26` 上下文长度为 1,000,000 Token，非思考模式最大输入约 991,808 Token；定价按单次输入范围分档，北京地域 256K 以内快照原价为输入 2 元/百万 Token、输出 8 元/百万 Token，256K-1M 档为输入 6 元/百万 Token、输出 24 元/百万 Token；Demo 改为每轮只注入 `top_k` 检索文块后，知识库总量不再按全文重复计入每次 LLM 请求，价格及优惠上线前需复核。

### 5.5.1 参数化多人辩论与 Maya 报告逻辑

目标是使用一套简单、可配置的 Demo 轮转规则支持 2-5 个参辩 Agent，而不是为每种人数分别写一套赛制；所有参辩发言完成后等待教师手动打开全班二维码互动表单，教师结束收集后再由 Maya 生成“文明互鉴报告”。正式发布时再认真重做赛制设计。

#### 参与者、顺序和固定两轮框架

- 教师从当前已发布 Agent 中依次点击选择 2-5 个，后端按 `participant_ids` 数组的点击先后自动赋予连续字母槽位 `A/B/C/D/E`；不单独输入槽位、不拖拽排序，如需改顺序则取消并按新顺序重新点选；每次增删选中项后都从 A 开始连续重排，不留字母空洞；这些字母只表示本场及每轮发言顺序，不代表固定正反方，也不写回 `AGENT.md`；
- Demo 规则固定 2 轮，不考虑第 3-5 轮，也不在教师页面暴露轮数设置；同一参数化规则只根据实际参与者顺序生成两轮 turn，不为 2/3/4/5 人分别建立规则；
- 调度公式为：对 `r=1..2`，按 `A→B→C→D→E` 中实际选中的顺序各发言一次；3 人示例为 `R1-A→R1-B→R1-C→R2-A→R2-B→R2-C`；5 人为 `R1-A→R1-B→R1-C→R1-D→R1-E→R2-A→R2-B→R2-C→R2-D→R2-E`；
- 总发言数固定为 `participant_count × 2`；第二轮最后一个参辩 Agent 完成后进入“等待教师打开互动”状态，不自动生成 Maya 报告；
- 默认验收仍是 Bowen=A、KaiKai=B、2 轮，因此表现为 `R1-A→R1-B→R2-A→R2-B`，但它只是参数化规则的一个配置；
- 每个 `DebateParticipant` 使用 `stance_mode=assigned|open`：教师选择 `assigned` 时可指定 `support|oppose|neutral` 和可选说明；选择 `open` 时不设置枚举立场，由 Agent 根据 `AGENT.md`、RAG 和课堂上下文阐述自己的观点；一场辩论不强制至少包含一个支持方和一个反对方；
- 无论哪种模式都保存 `initial_position_summary` 和 `current_position_summary`，避免把复杂的文明互鉴观点压缩成正反枚举；`open` 模式下 `initial_stance/current_stance` 保持为空；
- 参辩者可以在听取他人并接触新证据后精炼观点、局部让步、重新框定问题，或在指定立场模式下切换立场；`slot` 和顺序不变，后端保留 `DebatePositionHistory`，显著观点变化必须说明原因并绑定影响变化的对方论点或 RAG 证据；
- 投票对象始终是本场全部参辩 Agent，而不是抽象立场；Maya 不加入投票。

#### 按轮次区分的参辩职责

| 轮次/发言类型 | 必须完成的任务 | RAG 要求 | 提问 |
| --- | --- | --- | --- |
| 第 1 轮：观点呈现 | 说明教师指定立场（如有）或阐述自主观点；提出核心论点与理由；总结初始 `current_position_summary` | 必须为自身观点执行检索；命中时使用真实证据，无命中时明确使用一般推理；不伪造来源 | 默认不要求提问，让各方先完整展示自己的知识与观点 |
| 第 2 轮：文明互鉴说服 | 读取此前全部发言；回应/反驳至少一个具体观点；提出一个有针对性的问题；评估新证据与他人观点后更新 `current_position_summary`；通过证据、礼貌、准确回应和真实观点更新进行文明说服；禁止直接请求投票或操纵观众 | 查询至少覆盖“反驳他人观点”和“支持更新后观点”；命中时引用证据，无命中时只做无来源的一般推理 | 必须有一个问题；默认问向本轮下一位计划发言者；整场最后一位改为向全班提出开放反思问题 |

最新轮次边界替代了早期“第一轮就开始跨轮提问链”和“教师设置 1-5 轮”的设计：Demo 只做固定两轮。第一轮专注独立展示观点与 RAG 证据，不强制提问；第二轮才进入回应、反驳、提问和观点更新。在第二轮中，有后续计划发言者时，问题默认指向下一位；被提问者在本轮自己的 turn 中回答。整场最后一位使用 `audience_reflection`，向全班提出开放反思问题而不是虚构下一位回答者。

第一轮的 `RAGService.retrieve_turn_evidence()` 查询主要支持“自己的核心观点与重要顾虑”；第二轮可以构建最多三个子查询：`回答待处理问题（如有）`、`反驳此前具体观点`、`支持更新后的自己观点`；合并、去重后向 LLM 提供最多 `top_k=6` 个文块。

#### Maya 教师“文明互鉴报告”Agent

- `Maya` 永远表示流程最后的教师报告 Agent；A/B/C/D/E 专属于参辩 Agent 字母槽位，Maya 不属于学生小组、不占参辩名额、不发口头辩论 turn、不作为投票对象，也不增加 3D 人物；
- Maya 在所有参数化轮次完成后仍保持未生成；教师先打开二维码互动收集，待学生提交完成后手动点击“结束收集并生成报告”；该操作原子地关闭提交入口、冻结课堂互动快照并触发 Maya 运行 1 次，同时保留教师手动重新生成报告的 API；
- Maya 的核心输入为：辩题、全部参辩 Agent 的立场模式、教师指定立场（如有）、初始/最终观点摘要、完整发言、问答/反驳关系、观点更新历史、所有参辩者在辩论中实际检索并引用的证据文块/来源文件、最终匿名投票统计，以及从冻结原始弹幕派生并验证的匿名 `BarrageInsightSnapshot`；
- Maya 不是裁判 Agent；报告可以客观记录票数，但不将多数票等同于事实正确性，不自动宣布唯一正确答案；
- 报告建议包含：`辩题与角色`、`各方核心论点`、`证据与来源`、`关键反驳链`、`观点更新/局部让步`、`共识`、`仍未解决的争点`、`各方可以相互学习什么`、`课堂投票/弹幕观察` 和 `教学反思问题`；
- Maya 的结果使用独立 `CivilizationMutualLearningReport` 对象，不伪装成 `DebateParticipant` 或额外 `DebateTurn`；
- Maya 只读取辩论全文和参辩者在课堂中实际引用过的 RAG 证据，不重新独立检索任何 Agent 的完整知识库；
- 原始弹幕用于大屏和教师历史，逐条保留昵称与原文；它们不直接输入 Maya。互动结束后，洞察任务移除昵称，仅对弹幕文本做聚类和相关性筛选，输出“主要赞同点、主要质疑点、典型问题、每类真实数量、被筛除数量”，并在内部保留主题到原始 `barrage_message_id` 的映射以便教师排错；Maya 只读取验证后的匿名主题结果，不读取昵称、完整原始列表或投票个人映射；
- Maya 生成 600-900 个英文单词的权威原文，使用独立长输出配置（建议 `max_output_tokens=1600`）；报告完成时不自动调用中文翻译；
- 前端保存/展示英文报告并支持下载英文 Markdown；教师点击“翻译当前全部内容”后，可额外查看并下载该报告修订的测试用中文译文。Demo 不生成 PDF，不为报告做 TTS，不增加 Maya 的 3D 头脸；
- 弹幕洞察或报告失败不影响已完成辩论、原始弹幕记录和投票汇总；洞察可以基于同一冻结输入重试，每次报告自动/手动生成创建新的不可变 `CivilizationMutualLearningReportRevision`，教师空间保留成功历史和失败尝试元数据；Demo 学生制作端不提供课堂报告入口，匿名手机页也不显示报告。

#### 结构化输出和校验

每个参辩 Agent 的单次发言仍只使用一次 LLM 生成，但返回结构化结果，便于规则引擎按当前 turn 目标验证：

```json
{
  "speech": "80-200 word English speech",
  "retrieval_status": "matched | no_match",
  "grounding_mode": "rag_grounded | mixed | general_reasoning",
  "answered_question_id": "question-id-or-null",
  "rebuttal_target_turn_id": "turn-id-or-null-for-first-turn",
  "rebuttal_summary": "specific opponent claim and response",
  "new_argument_summary": "new or strengthened argument",
  "turn_summary": "one-sentence turn summary",
  "position_summary": "one-sentence current viewpoint",
  "position_update": "unchanged | refined | partial_concession | reframed | switched",
  "new_stance": "support | oppose | neutral | null",
  "position_update_reason": "evidence-based reason or null",
  "source_filenames": ["source-a.md"],
  "question": {
    "type": "agent | audience_reflection | none",
    "target_participant_id": "participant-id-or-null",
    "text": "focused question or null"
  }
}
```

第一轮所有 turn 的 `answered_question_id`、`rebuttal_target_turn_id` 和 `question` 默认为空/`none`，但必须返回初始观点、核心论点、本轮总结与 RAG 状态。第二轮所有 turn 必须指定至少一个此前具体反驳对象、提供更新/强化后的论点、本轮总结和当前观点摘要，并生成一个问题。如规则引擎为当前 turn 分配了前一问题，`answered_question_id` 必须正确回填；如本轮还有下一位，`question.type=agent` 且 `target_participant_id` 必须等于下一人；整场最后一位必须使用 `question.type=audience_reflection` 且 `target_participant_id=null`。只有 `grounding_mode=rag_grounded|mixed` 时才要求至少一个真实来源；`general_reasoning` 必须使用空来源且不得出现伪引用。结构或证据约束缺失纳入最多 1 次重试，但合法的 `no_match + general_reasoning` 本身不触发重试或终止。

`position_summary` 每次必填并用于后续回合检索。`stance_mode=assigned` 且 `position_update=switched` 时，`new_stance`、`position_update_reason` 和至少一个影响转变的证据/对方论点必填；后端更新 `current_stance`，不覆盖 `initial_stance`。`stance_mode=open` 时不要求生成枚举立场，`new_stance` 保持为空；发生 `refined|partial_concession|reframed` 等显著变化时记录新的观点摘要、原因及影响变化的论点/证据。两种模式都追加 `DebatePositionHistory`。

#### 可维护性和可扩展性原则

- Demo 启用单一参数化规则集 `ordered_multi_agent_rounds_demo_v1`，通过 `participant_order` 和固定的两阶段配置生成 2-5 人的 turn 计划；不为每种人数复制规则；`Debate` 保存 `rule_set_id` 和创建时规则快照，避免历史辩论无法解释；
- 参与者顺序、轮数、提问要求、RAG 强制项、长度、课堂互动收尾和 Maya 报告策略，放在后端类型化 `DebateRuleSet`/配置中，不散落写死在页面、控制器或单个提示词里；
- 调度、轮次目标、RAG 查询、输出校验和文明互鉴报告分别由 `DebateStateMachine`、`TurnPolicy`、`RAGService`、`TurnValidator` 和 `ReportPolicy` 承担；不让 LLM 自由决定谁下一个发言或是否结束；
- 提示词模板按 `rule_set_id + phase` 版本化，例如 `opening`、`rebuttal`、`closing`、`civilization_report`；修改提示词不改业务 DTO；
- 前端只根据 API/WebSocket 返回的 `phase`、字母型 `speaker_slot`、`turn_index`、`report_status` 和 `status` 渲染，不在 React 组件里写死“一定只有 4 个发言 + 1 份报告”；
- Demo 的主展示阶段固定映射为 `draft → running → debate_finished_waiting_interaction → interaction_open → barrage_insight_generating → report_generating → completed`，并保留 `stopped` / `failed` 终态；最后一个 turn 结束后不自动打开二维码，也不自动运行 Maya；互动、弹幕洞察与报告是独立 phase，不伪造成新轮次；
- 正式版发布前重新审视赛制；可以增加分组、轮换开场、限时、无强制提问、主持/裁判和不同报告策略，同时保持现有辩论核心对象和 DTO 可迁移。

### 5.5.2 辩论创建与启动边界（已确认）

- 英文议题必须非空，但不设置产品级字符数上限；数据库/API 使用长文本字段，不在页面显示剩余字符数。Demo 使用 Node 24.14.0 冻结生成的 Unicode `Letter && Script_Extensions=Latin` 码点表作为前后端唯一 letter 真相：至少包含一个 Latin letter，可使用 Unicode Latin 变音（含紧跟 Latin base 的 NFD `Mn/Mc`）、数字、标点和普通 `Zs` 空格；拒绝非 Latin letter、控制/格式字符、符号、孤立组合符和非空格分隔符。创建/修改在任何幂等或 CAS 写入前返回稳定 `422 topic_language_invalid`，旧非法草稿在启动的音频清理/计划/Job/Provider/状态写入前再次校验；该确定性规则是 Demo 脚本门禁，不声称能做自然语言语义识别；
- `participant_ids` 至少 2 个、最多 5 个且不能重复；前端按教师点击先后传递有序数组，后端依次自动分配唯一且连续的字母型 `slot=A..E`，该顺序直接驱动每轮调度；槽位不是另一个可编辑输入；内部 `order_index=0..4` 仍用于排序和数据库约束；
- Demo 创建页不显示轮数输入，`ordered_multi_agent_rounds_demo_v1` 固定 `round_count=2` 并用相同算法支持所有 2-5 人配置；后端拒绝非 2 的 Demo 请求，不按人数切换规则集；
- 每名参辩者可独立选择“教师指定立场”或“开放阐述”。指定立场可为 `support|oppose|neutral`；开放阐述不填立场，由 Agent 基于 `AGENT.md`、RAG 和上下文形成观点；不要求一场中必须同时存在支持方和反对方；默认验收仍预置 Bowen=A=支持、KaiKai=B=反对；
- 创建辩论草稿时保存当时每名参与者的 `agent_version_id + knowledge_snapshot_id`，后续学生发布新版本不会自动替换；
- 在 `draft` 状态下，教师可以主动修改议题、参与者点击顺序、立场模式、指定立场或说明；改变点击顺序后系统自动重排 A-E；每次修改重新校验并固定所选 Agent 当时的当前发布版本/快照；点击启动后，辩题、参与者、版本快照、字母/发言顺序、固定两轮、立场配置和规则集全部锁定；
- Demo 同一课程同一时间最多 1 场 `running` 辩论；可以同时保留多个未启动草稿和历史记录；
- 启动时后端权威校验：参与者数量符合规则集、版本/知识快照存在、3D 头脸可用、规则集可用，并为每个 Agent 解析 `effective_voice_profile_id`；
- 所有未配置、未就绪或已删除自定义音色的 Agent 默认使用系统兜底音色，不阻塞创建、发布或启动；有 `ready` 自定义音色时优先使用它；
- API Key 和真实兜底音色尚未配置时，编码/测试阶段使用 Mock Provider 和 Mock fallback 完成启动检查；真实服务最终验收仍按后置任务执行。

### 5.6 3D 形象

- 采用“模板化选择 + 参数化调整”，与原始需求一致；
- Demo 只显示 3D 头脸/头肩镜头，不显示或制作身体；身体和全身动作在正式版确有需要时再加入；
- Demo 产品目标是内置 3 个可兼容当前 TalkingHead 管线的通用或历史风格头脸/头肩模板，覆盖 2-3 Agent 主展示；2-5 人场允许重复使用模板并通过材质主题、姓名卡和槽位区分；产品长期人物模板上限目标约为 10 个；精确历史名人外貌不是 Demo 验收项。当前 Demo 仅由用户私下本机查看，暂不把许可核验设为开发或验收阻塞项；若后续推送含素材的公开 GitHub、交给他人、课堂正式使用或公网部署，必须重新核验素材授权并替换不明来源资产；
- 学生不能上传自定义 GLB；只能在平台内置兼容资产中选择，避免模型骨骼、Blendshape、纹理和运行兼容性不一致；公开分享/交付时另加许可检查；
- 学生可调整的参数固定为：头脸模板、肤色/材质主题、眼睛颜色（资产支持时）、默认表情、表情强度 `low|medium|high` 和头部动作风格 `calm|active`；不开放自由捏脸或任意数值输入；
- 第一版系统动作状态为：`idle`、`listening`、`speaking`、`thinking`、`nod_yes`；课堂根据权威辩论/播放状态自动驱动，学生只选择风格和预览，不能编排每个 turn 的动画时间线；
- 第一版面部表情预设为：`neutral`、`attentive`、`happy`、`serious/angry`、`sad`。`attentive` 是专门的聆听表情，与 `listening` 动作状态分开；
- 正式播放时，当前发言者进入 `speaking` 并使用其默认/发言表情强度；其余可见参辩 Agent 自动进入 `listening + attentive`，保持注视、轻微头部反应，并可按系统节奏偶尔执行 `nod_yes`；当前发言尚在准备时可让该 Agent 使用 `thinking`；
- 不做服装、身体、身高、体型、骨骼比例、手势或自由捏脸；
- TalkingHead 负责头脸 GLB 渲染、英语口型和多角色画面；MotionEngine 只提供可在头部镜头看到的命名情绪/头部动作；Google GNM 作为未来生成不超过 10 个参数化头脸的候选；
- Demo 不要求从零建模或高精度捏脸，但学生必须能够通过可见操作完成角色差异化；
- 语音、动作和表情整体节奏大致同步即可，不要求精确口型；
- 单个 3D 模型加载失败时显示该 Agent 的静态头像/姓名卡，文字、语音、RAG、投票和辩论继续；这是防御性兜底，不作为正常演示路径或可接受的主验收效果。

### 5.7 投票与弹幕

- 课堂互动与学生制作账号完全解耦；手机页不登录，后端不使用 `user_id`、`CourseMember` 或 `GroupMember` 表示提交者；
- 匿名表单只在最后一个计划 turn 正常完成且教师手动打开互动收集后可用；辩论提前失败或被停止时不能打开；
- 教师大屏显示一个指向本场互动表单的二维码；手机扫码后直接打开，不要求账号、密码、课程成员身份或先加入课程；
- Demo 本机运行时，教师电脑和手机需在同一局域网；后端/网站监听可被局域网访问的地址，并从后端环境配置 `CLASSROOM_PUBLIC_BASE_URL` 生成二维码，不能生成手机无法访问的 `localhost` 链接；这不等于公网/云部署；
- 手机页第一步必填一个自定义昵称；昵称不需要唯一、不会转换为平台账号，也不进入投票记录；
- 输入昵称后显示两个彻底独立的功能区：投票区只要求从本场全部参辩 Agent 中选择一个并点击“提交投票”；弹幕区只要求输入一条弹幕并点击“发送弹幕”；Maya 不出现在投票选项中；
- 观众可以只投票、只发弹幕或两者都做；两项的顺序不受限，一项失败不影响另一项；
- 投票成功后仅投票区显示“投票成功”并不可再改，弹幕区仍可操作；弹幕成功后仅弹幕区显示“发送成功”并不可再发，投票区仍可操作；两项均完成后页面只显示总体完成状态；
- 大屏可显示“昵称：弹幕”，但后端和大屏都不建立/显示该昵称的投票选择；投票只以无昵称汇总形式存储与展示；
- Demo 不建立会话级防重、不设置浏览器 Cookie/设备指纹、不检查昵称重复、不对任何提交者标识设唯一约束；用户刷新页面后可重新看到表单并再次提交，这是已确认的 Demo 边界；
- 不限制匿名观众数量，也不在产品逻辑中写死人数上限；Demo 本阶段不做压力测试、不承诺 30-60 人并发性能；
- 每个成功的投票或弹幕都独立计入后端汇总；教师大屏通过 WebSocket 分别接收新弹幕事件和票数更新事件；手机页本身不订阅 WebSocket；
- 不做弹幕限速、敏感词、人工审核或单条删除；教师通过“打开互动收集/结束收集”统一控制投票和弹幕两个功能的开放时间，但两类数据的提交、存储、失败和汇总彻底独立；
- 教师点击“结束收集并生成报告”后，新投票和新弹幕均返回“互动已结束”；当前匿名投票统计与按提交顺序保存的全部 `BarrageMessage` 分别冻结。原始弹幕继续在大屏/教师历史逐条显示；后台另行去昵称、聚类和筛选并生成 `BarrageInsightSnapshot`，只有该匿名洞察与票数进入 Maya；
- 如果投票和弹幕都为空，教师仍可结束收集并触发 Maya；报告明确写“本场无课堂互动数据”，不把零数据当作错误。

### 5.7.1 弹幕原始展示与 Maya 洞察边界（已确认）

这是两个用途不同、不能互相替代的数据层：

1. **原始展示层**：`BarrageMessage` 永久保存本场的昵称、原文、顺序和时间；大屏与教师历史逐条原样显示所有成功提交，不分类、不折叠、不删除重复内容，也不因后续筛选结果改变；
2. **匿名洞察层**：结束收集后复制冻结消息的内部 ID 和文本，不复制昵称；`BarrageInsightPolicy` 可使用一次结构化 LLM 调用，将有实质且与本场辩题/辩论相关的内容归入 `support_points`、`challenge_points`、`questions`，相近表达合并为一个主题；重复表达仍贡献主题数量，但不在 Maya 输入中重复铺开；
3. **筛选边界**：只筛除空泛/无实际语义、明显与辩题和已发生辩论无关的内容；不能因为观点少数、批评某个 Agent、语言不够正式或与多数意见不同而筛掉。Demo 不做敏感词审核，大屏仍显示所有原文；
4. **可验证计数**：LLM 只返回主题摘要和它认为属于该主题的 `barrage_message_id[]`；后端验证 ID 必须来自本次冻结集合、同一消息最多归入一个最终主题，并由代码计算 `count`、`included_count`、`filtered_count`，不让模型自行编数字；
5. **Maya 输入**：只包含匿名主题摘要、代码计算的数量、典型问题和总体 included/filtered 数，不包含昵称、全部原始弹幕或原始投票提交；Maya 可以在报告中概括课堂关注点，但不能把筛除内容说成不存在，也不能把主题数量当作事实真伪证明；
6. **失败处理**：洞察结构校验失败时自动重试 1 次；仍失败则 `BarrageInsightSnapshot.status=failed`，Maya 报告状态保持 `failed/not_started`，原始大屏/投票/辩论不受影响。教师点击“重新生成报告”时先重试洞察，再生成新的报告修订。

### 5.8 实时通信

- Demo 采用 WebSocket；
- WebSocket 用于后台准备状态、教师播放控制、正式展示的完整发言、语音就绪、回放状态、按需翻译结果、课堂互动提交汇总和 Maya 报告状态；WebSocket 的课堂消费端是教师大屏，不是扫码手机页；
- 首版结构化事件冻结为：`debate.started`、`round.started`、`turn.preparing`、`turn.ready`、`playback.started`、`playback.paused`、`playback.resumed`、`playback.skipped`、`playback.waiting_next`、`playback.completed`、`replay.started`、`replay.completed`、`translation.batch_started`、`translation.batch_completed`、`translation.batch_failed`、`interaction.opened`、`interaction.vote_created`、`interaction.barrage_created`、`interaction.closed`、`barrage_insight.started`、`barrage_insight.completed`、`barrage_insight.failed`、`report.started`、`report.completed`、`report.failed`、`debate.completed`、`debate.failed`、`debate.stopped`、`error`；具体 payload/版本在 G0 Schema 中冻结；
- REST API 负责教师控制命令、按需翻译、互动入口开关、创建、查询和其他持久状态改变；免登录手机页使用两个独立的普通 HTTP POST：一个只提交被投 Agent ID，另一个只提交昵称和弹幕文本；两者都不建立 WebSocket、不改变播放状态；
- 当前 Agent 的英文发言通过结构校验并保存后，后端即可提前为“下一位计划发言者”执行 RAG/LLM；下一位文字完成后再独立执行 TTS。文字生成和语音生成是后台两个阶段，最多只超前准备一位，避免无上限消耗；
- 后台预生成的下一位内容标记为 `prepared`，不得提前出现在教师大屏的 transcript 或 WebSocket 正文事件中。到正式播放时，大屏才在同一个 `playback.started` 事件中同时得到该发言完整英文气泡、平台音频地址和 3D speaking 状态；不要求逐词字幕与语音时间戳精确对齐；
- 课堂播放由教师账号控制，后端保存并广播权威 `turn_id`、`playback_state`、`cursor_ms`、`playback_rate` 和控制版本。教师大屏跟随权威状态，刷新/断线后从后端快照恢复；等待“下一步”也必须是后端可恢复状态，刷新、短暂断线或后端重启不得越过教师门禁自动公开下一位。若进入 waiting_next 时 successor 尚未完成 TTS，首个 `playback.waiting_next` 携 `next_turn_ready=false`；successor 后续就绪时，服务端为同一 completed turn/control version 再提交一条有新 sequence 的 `playback.waiting_next(next_turn_ready=true)`，前端据此或重连 snapshot 解锁 Next，不从 `turn.ready` 或本地计时器推断；匿名手机页不参与播放同步；
- 中文翻译不参与实时流水线。教师点击“翻译当前全部内容”后，按需批量翻译当时已公开的发言和当前报告，完成后单独推送测试译文；
- 每门课程最近一次已启动辩论的已生成 TTS 文件持久保存到本机受控目录，不按辩论结束后的分钟数自动清理。只有该课程教师正式启动下一场辩论时，系统才清理上一场保留的合成语音；原始声音克隆样本仍在音色 ID 创建请求结束后立即删除；
- 在下一场尚未启动前，教师可以无限次整场重播；普通页面不再提供单回合重播。整场重播只读取已保存英文文本、来源和音频，从第一计划 turn 开始且每段都等待教师 Next，不重新生成内容，不改变投票、弹幕快照或 Maya 报告；
- Demo 当前确认教师逐回合控制：开始只播放第一位；自然结束后等待教师点击“下一步”才公开/播放下一位；普通播放 Dock 只保留开始、下一步、整场重播，Replay 同样逐段 Next。普通断线按游标或 live/replay `waiting_next` 恢复，后端重启不得自动越过下一步门禁；异常卡死使用非普通 UI 的 operator reset；启动下一场前必须确认删除上一场可回放语音。

#### 5.8.1 当前人工反馈修订

- 控制页只允许一次初始自动连接；断线后进入稳定 disconnected 状态，显示手动 Reconnect，不再循环重连或自动刷新。
- `Pause / 暂停` 与不可恢复 `stopped` 分离。Pause 只暂停当前 playback，Continue 真正回到 `playing` 后可以推进后续 turn；Finish 才结束当前 Debate。
- 完整 Finish 才能打开 interaction、生成 Maya、保留历史和 Replay；partial Finish 仅保留已生成 turn，禁止 interaction/Maya/history/replay。

### 5.9 Demo 允许简化或暂缓

- 3D 使用少量本地预置 GLB 模型和有限参数；私下本机 Demo 暂不做许可核验，进入公开分享/正式课堂前必须重新核验；
- 口型可先采用播放状态或音量驱动；
- 音色克隆使用真实外部服务，但只为两个 Demo 智能体各创建一个英文克隆音色；
- 中英文界面静态文案切换纳入 Demo；英文发言/报告不自动翻译，只提供教师按键触发的测试翻译；
- 所有辩论长期保留文字、可选按需译文、来源、弹幕和投票；合成语音只保留“每门课程最近一次已启动辩论”这一份，直到教师启动下一场后被替换清理；
- 暂缓精细 3D 建模、高精度口型、自建模型、学校 SSO、大规模优化和完整评分后台。

### 5.10 小组编辑和项目协作

- 小组成员共享本组 Markdown 资料库和音色 Profile，并共同编辑本组多个 Agent 各自的唯一草稿、RAG 启用集合与 3D/音色绑定；不同 Agent 的草稿不是同一份内容；不做 Google Docs 式实时协同、光标同步或 CRDT；
- 成员轮流打开和保存同一份内容；API 保存时携带 `revision`，若页面版本已过期则返回冲突并要求刷新，避免静默覆盖他人修改；
- Demo v0.1 由项目发起人单独完成，所有功能保持简单；未来另有两人加入，其中一人与发起人共同开发，当前暂不划分模块；
- 当前不设计产品内的 Evaluation 模块、评分系统或独立评测工作流，也不预先为未来协作者分配 Evaluation 岗位；
- 开发中仍保留普通的自动化测试、固定 Demo 数据和错误日志，它们属于软件可维护性，不等于实现 Evaluation 产品功能。

### 5.11 Demo 必须具备的功能页面

通用：

- 中英文界面切换；
- `/` 是唯一公开首页和登录入口：整张顶部卡片最上方右对齐显示“中文 / English”；下方左栏保留平台介绍和环境健康，右栏始终显示后端提供的全部 teacher/student 身份卡、分隔线以及常驻用户名/密码表单，按钮统一为“登录 Maya”；不再显示跳转式“登录 Maya”首页按钮，也不再出现“改用用户名和密码登录”折叠项。`/login` 只作为旧链接兼容重定向到 `/` 并保留安全的站内 `next`；账号、明文密码、角色和学生小组仍由 0600/Git ignored 的后端私有 Markdown 管理；课堂观众入口不使用这套账号；
- 当前预置课程/小组/身份标识及只读成员列表；不提供课程创建/加入和小组成员管理页面；
- 操作成功、处理中和失败状态。

学生/小组端：

- 学生仅进入本组制作空间，可查看本组多个 Agent、组内 Markdown 资料库、草稿、当前已发布版本和历史版本；可继续编辑唯一草稿、创建新版本、发布更新、编辑 description，并彻底删除从未发布/从未参辩 Agent；不提供教师课堂控制或任何其他小组数据；
- 小组工作台和 3 名成员列表；
- 知识库支持批量上传、网页新增和 copy-on-write 编辑 Markdown、文件下载、当前/上限字符数、`RAG.md` 草稿预览、分块/向量索引状态和文档列表；编辑旧文档后自动替换所有未发布草稿引用并增加 revision，不改变已发布快照；不提供 PDF/TXT、OCR或格式转换；
- “创建智能体”按钮：由学生主动创建新 Agent 及其 V1.0 草稿；`AGENT.md` 自由编辑/上传、可选示例大纲、RAG Markdown 管理和测试问答；
- 3D 头脸模板选择、肤色/材质主题、眼睛颜色（资产支持时）、默认/聆听表情、表情强度和头部动作风格预览；不提供自定义 GLB 上传；
- 一段本地英文音频上传、授权提示、标准化状态、真实声音复刻状态、临时试听和小组可复用的 `voice_profile_id`；不提供浏览器麦克风录音，平台不长期保存原始声音文件；
- 发布检查清单与 `publish_blockers` 提示：`AGENT.md`、至少一个已索引 RAG、100,000 字符/失败文件和 3D 头脸通过后即可发布；测试聊天和自定义音色都不强制，没有可用自定义音色时显示“将使用兜底音色”；
- V1.0 发布、发布锁定、当前发布版本标识；发布后通过“创建新版本”按钮手动克隆出 V1.1 草稿，同一草稿可多次修改并显示“有未发布更改”；发布更新后教师的新辩论候选只显示 V1.1，旧版只用于历史查看和带 Agent/版本后缀的冻结文件下载；不再提供归档/取消归档，只允许安全彻底删除无历史 Agent；删除当前资料时显示“已被历史版本引用，将从当前工作区隐藏但不会立即物理删除”的确认提示。

教师端：

- 教师顶部主导航只保留“首页 / 课堂辩论”；语言、账号角色和退出保留为右侧账户工具。首页显示当前课程和已发布智能体列表，并说明教师可检查成果、创建/控制课堂辩论和查看历史，但不能编辑学生内容或看未发布草稿；
- 智能体详情：制作小组、当前 description、人设、知识库、3D 头脸、平台音色状态、当前发布版本，以及所有历史已发布版本的完整冻结内容/下载；永远不显示未发布草稿；历史版本仅用于审计/查看，不在 Demo 辩论创建页中选择；
- 辩论创建：英文议题非空但不限制长度；依次点击 2-5 个当前发布 Agent，界面按点击顺序自动标注 A-E，字母同时表示每轮发言顺序，不提供独立拖拽/槽位编辑或轮数输入；Demo 固定两轮；设置每名 Agent 的“教师指定立场/开放阐述”，指定时可选支持、反对或中立，开放时无需填写立场；Maya 文明互鉴报告固定启用，只显示说明和长度/语速配置，不提供关闭开关；草稿创建/修改时固定版本快照，启动后全部锁定；
- 课堂控制/大屏：控制页顶部显示“返回辩论列表｜结束辩论｜课堂互动与报告”；Next 旁提供 `Pause / 暂停`（暂停后切换 `Continue / 继续`），不取消后续流程。完整 Finish 才显示并开放 interaction、Maya、历史和 Replay；不完整 Finish 诚实显示 `stopped`，只保留已生成 turn，不进入 Maya、不开放匿名互动、不提供历史和 Replay。课堂互动/报告位于独立页面；测试翻译只保留一个按钮，在中文测试表示与权威英文间单视图切换；Replay 从不可变 catalog 恢复 speech/source 文本。异常时仍使用非普通页面的 operator reset；
- 辩论记录：按 `participant_count × 2` 生成的全部参辩英文发言、Maya 文明互鉴报告当前版本、可选按需中文译文、来源文件、弹幕和全部参辩 Agent 最终票数；教师空间另有报告修订历史，可查看/下载历次成功版本并查看失败尝试状态；最近一次已启动辩论在下一场启动前支持逐段 Next 的整场语音回放，更早记录不再有音频。

课堂观众端：

- 这是与教师账号、学生制作账号分离的免登录一次性手机表单，只在全部参辩发言结束且教师打开收集后可用；
- 页面先显示辩题/简短提示和昵称输入；昵称填写后再显示独立的“投票”和“弹幕”功能区，两者各有自己的按钮、加载状态、成功状态和错误提示；不显示 3D、发言、来源、语音、弹幕墙、投票统计或 Maya 报告；
- 一项提交成功只锁定对应功能区，另一项仍可操作；两项均完成后才只显示总体成功页；刷新网页后两项都重置并可再次提交（前提是教师尚未结束收集）；
- 不设置观众人数上限或登录/会话防重；不做本阶段压力测试。

### 5.12 推荐 Demo 展示脚本（约 10-15 分钟）

1. 打开首页，切换中文/英文界面，说明辩论内容固定为英文；
2. 切换为 Group A 学生，展示小组成员和共享工作台；
3. 在组知识库网页新增一份英文 Markdown，展示“保存资料库 → 明确启用到草稿 → 字符上限检查 → 分块 → 向量化 → 索引完成”，再用测试问答展示命中文块和来源文件；编辑该 Markdown 后展示所有引用它的未发布草稿自动换到新 revision，而已发布快照下载内容不变；
4. 自由编写/上传 `AGENT.md`，选择/调整 3D 头脸；
5. 学生上传一段预先录好的 10-20 秒本地英文声音文件，展示标准化、真实创建一个小组可复用音色 ID 和新句子临时试听；说明注册请求后原音频自动删除；
6. 发布 Group A 智能体 V1.0；Group B 使用预置且已发布的智能体，避免重复演示同一构建流程；
7. 切换为教师，查看已发布智能体，先点 Bowen 自动得到 A，再点 KaiKai 自动得到 B，演示字母槽位/发言顺序由点击顺序生成；确认固定 2 轮和“指定立场/开放阐述”，默认 Bowen=A=支持、KaiKai=B=反对；说明 Maya 文明互鉴报告固定存在、不可关闭；
8. 启动辩论，只公开并播放第一位；展示后台最多超前准备下一位的文字/TTS 状态但不泄露正文/来源。当前发言结束后验收页面停在“等待下一步”，教师点击“下一步”才同步公开下一位的英文气泡、来源文件、真实语音和 3D speaking，非发言者进入 `listening + attentive`；普通播放区只出现开始、下一步、重播整场三个按钮；
9. 最后一个计划 turn 完成后，大屏显示辩论已结束但 Maya 尚未生成；教师点击“打开课堂互动”并把二维码展示给全班；
10. 用手机扫码，先输入昵称；先在投票区选择一个参辩 Agent 并提交，验收只有投票区显示成功且大屏更新票数；再在独立弹幕区填写一条弹幕并发送，验收只有弹幕区显示成功且大屏追加“昵称：弹幕”；两者不共用提交记录，刷新手机页后两项都可再次提交；
11. 教师点击“结束收集并生成报告”，系统关闭二维码入口、冻结最终匿名票数和逐条“昵称 + 原文”弹幕列表；大屏仍展示原始记录，后台去昵称后聚类相近观点、筛除无关/无实质内容，由真实消息 ID 计算主题数量，再把匿名洞察输入 Maya 生成并展示文明互鉴报告；
12. 查看全部参辩发言、Maya 报告、来源文件、弹幕和票数；点击“翻译当前全部内容”后查看测试用中文译文；
13. 点击“重播整场”回到 A1，验证每段重播结束后仍等待教师 Next、刷新不越过门禁且不新增 RAG/LLM/TTS Job；返回小组声音 Profile 展示可复用音色 ID，并说明原始录音会立即删除，而本课程最近一场辩论语音会保留到下一场正式启动。

### 5.13 开发门禁与后续多 Agent 协作原则（已确认）

- 当前 C01-C12 编码前合同包、四类视觉稿和预检已经冻结；用户已于 2026-08-26 19:06 明确允许打开编码门禁并开始 Wave 0。主窗口与子 Agent 现在可以在对应模块 Gate 和文件所有权内实现，但不得越过 Wave 依赖或跳过审计；
- 冻结视觉基线以 Visual Draft V2 为唯一 Demo 终稿：全站 `Inter Variable/Inter/PingFang SC/Noto Sans SC` 柔和无衬线字体、V2 紧凑标题/正文字号与间距、不使用 Georgia/Times；参辩槽位 A-E；保留大屏纯视觉状态和互动三栏布局。后续只有真实可读性/溢出/无障碍缺陷或用户明确重新打开视觉决策时才修改全局视觉；
- 编码开始后，所有 Worker 直接使用冻结的 `docs/pre-code-contracts/`、模块依赖图、Gate 计划、OpenAPI/跨模块契约和验收标准；任何设计变更先退回相关合同状态，不允许实现反向改产品；
- “想”优先交给 `gpt-5.6-sol`、`reasoning=high`：架构反例、权限/数据语义、状态机、迁移、失败恢复、Provider 安全和跨模块契约审计；“做”交给 `gpt-5.6-luna`、`reasoning=max`：代码、迁移、测试、修复和局部重构。Sol 原则上只读并给判断，不直接写实现；Luna 不给自己的 Gate 最终签字；
- Sol High 不对每个小改动都单独启动。为兼顾 Token 成本和质量，按风险分层：
  - **高风险独立双审**：M03 权限/会话、M05/M06 版本与 RAG 快照、M08 音色隐私/外部 Provider、M10/M11 辩论规则与 LLM/RAG、M12 播放状态机、M16 数据迁移、M17 稳定 API/密钥、M18 权限/质量门；这些模块在 Luna 开工前做一次紧凑设计审计，完成后再做代码审计；
  - **中风险单次审计**：教师检查、免登录课堂互动、Maya 报告、历史/翻译等模块在 Luna 完成并通过确定性检查后做一次 Sol 代码/契约审计；
  - **低风险批量审计**：静态页面、样式、普通 i18n、展示组件等由 Luna 自测 + 主窗口审阅，2-4 个相关模块合并成一个 Sol 批次再签字，不为每个按钮单独消耗一次 High；
- 每个模块最终仍必须记录 `covered_by_sol_audit_id`；“批量审计”只是减少重复上下文，不等于低风险模块免审。触及权限、数据丢失、状态机、数据库迁移、密钥/隐私或 Provider 契约的改动不得降级为批量审计；
- 主窗口为每个 Sol/Luna 生成紧凑 `Gate Packet`，而不是把全部聊天和整个仓库重新塞给它。Packet 只包含：目标/非目标、文件所有权、相关 DTO/OpenAPI、关键不变量、允许参考、验收命令，以及审计时的 changed-files/diff 摘要/测试结果；主窗口继续完整读取 `Project.md` 并对没有下发的全局上下文负责；
- 子 Agent 使用最小必要的对话继承启动；同一领域的 Sol 可连续跟进 2-3 个相关 Gate 以复用上下文，之后新开审计以避免历史过长和锚定偏差；审计输出固定为 `PASS | CHANGES_REQUIRED`、最多 5 个阻塞问题、对应文件/证据/失败测试和契约影响，不生成大段重复总结；
- 在调用 Sol 前先由 Luna/工具完成格式化、lint、类型检查、单元测试、迁移检查和 OpenAPI diff；明显的编译错误、格式问题和机械测试失败直接退回 Luna，不浪费 Sol High 推理 Token；
- Sol 要求修改后，只在修复触及其原阻塞不变量或产生新契约变化时再次调用；纯机械修复由主窗口运行针对性测试并对照原问题关闭。任何 P0/P1 安全、权限、数据或状态问题都必须回到 Sol 复审；
- 当前运行环境总并发槽位有限，包含主窗口时最多同时运行 3 个子 Agent，因此典型滚动池为“2 个 Luna 实现 + 1 个 Sol 审计上一批”，高风险阶段可切换为“1 个 Luna 修复 + 2 个 Sol 分别审设计/代码”。不同模块只因真实契约依赖阻塞，不因另一个无关模块或审计队列停工；
- Worker 必须获得明确的文件/模块所有权、验收标准，并被告知不是唯一开发者、不得回滚其他人的修改；
- 并行任务优先按后端领域骨架、RAG 与 Agent、辩论状态机、前端与 3D、测试与文档等无冲突边界拆分；依赖同一契约的任务先由主窗口冻结 DTO/OpenAPI 后再派发；
- Gate 流程调整为：`G0 Main Contract Draft → G0-S Sol Design Challenge（高风险必需）→ G1 Luna Implemented/Self-tested → G1.5 Deterministic Checks → G2 Sol Risk-based Audit → G3 Module Pass`。失败只退回对应 Luna 修复，不冻结其他无依赖模块；
- 所有模块达到 G3 后，主窗口执行 `G4 Cross-module Integration`，统一检查 DTO/OpenAPI、数据库迁移、权限、状态机、Provider、第三方依赖许可证、禁止复制代码证据、3D 素材分发状态、密钥/隐私和前后端事件；私下本机素材不因许可阻塞，但不得误标为可公开分发；再让 Sol 对集成后的高风险不变量做一次集中审计，最后由主窗口运行 `G5 E2E/Real-service Acceptance`，才可称为完整 Demo；
- 主窗口不得把最终通过判断交给子 Agent；Sol 的模块 PASS 是必要条件但不是整站完成证明。主窗口仍要检查合并差异并运行单元、集成、E2E 和本机演示；
- 主窗口负责处理跨模块冲突、补齐遗漏和最终本机演示，不以“子任务分别完成”代替完整网站验收；
- GitHub 只按 4.0.1 的“先契约、后带问题查模块”规则使用。每个 Worker 的任务中必须明确允许观察的问题与禁止继承的领域对象/代码；只能阅读后独立实现，不能复制任何片段；依法使用依赖包时锁定版本并检查许可证；3D 素材私下本机只记录来源/兼容性，公开或交付前再做许可 Gate；
- 可维护性优先：业务核心依赖平台自己的 DTO 和 Provider 接口，外部实现放在 `integrations/` 或 `providers/`，前端不得直接依赖供应商协议；
- 可扩展性优先：Demo 可以 SQLite/本地原始文件/本地向量库，但 repository/service/storage/provider 接口不能在页面或业务规则中写死实现；未来更换 Embedding 模型或向量库时不改前端 API；
- Demo 开发不拆出 Evaluation 专项或报告产品；主窗口仍对必要的功能测试、集成验证和最终审计负责。

## 6. 核心业务对象（C02 已冻结）

- User：教师或学生制作账号；不表示课堂观众；
- DemoCredential：Demo 后端私有0600 Markdown中的用户名、显示名、明文Demo密码、teacher/student角色和学生小组；启动同步为User/CourseMember/GroupMember，删除配置行只停用登录并撤销Session，不物理删历史User；前端/API只拿安全身份目录，绝不拿密码或配置路径；
- Course：课程，包含唯一课程号；Demo 由种子创建 1 条，但仍是数据库实体；
- CourseMember：用户在课程内的身份；Demo 预置 1 名教师和 6 名学生；
- Group：课程内小组；Demo 预置两个三人小组；
- GroupMember：正式结构保留组长、管理员或组员角色；Demo 的组织关系只读，三名成员对本组内容拥有同等编辑/发布权限；
- KnowledgeBase：小组共享 Markdown 资料库的逻辑视图；Demo 一个 Group 天然对应一个资料库，不另建可增删的 `knowledge_bases` 表，只能由本组成员管理；
- KnowledgeDocument：每次上传、网页新增或编辑replacement产生的独立、不可变Markdown记录，归属于一个小组，保存原文件名、存储路径、字符数、索引状态和可选replacement lineage；通过关联表由同组不同Agent草稿各自启用，不做内容去重或原地覆盖；
- AgentVersionDocument：某个 AgentVersion 草稿明确启用哪个组内 KnowledgeDocument 的关联；发布前校验双方属于同一小组；
- KnowledgeSnapshot：发布时只由该 AgentVersion 明确启用且索引成功的 Markdown 固化的不可变、版本化 `RAG.md`、文件关系/副本、文块、Embedding 向量、处理参数、内容哈希和来源元数据；
- Agent：归属于一个小组的文化智能体稳定身份，保存当前description、`metadata_revision`和当前发布版本指针；其他小组永远不可见。只有无发布/无参辩历史时可hard delete；有历史时RESTRICT并返回`agent_history_retained`；
- AgentVersion：由学生主动创建的智能体草稿/已发布版本；草稿保存用于顺序编辑的内部 `revision`，已发布版本绑定独立 `knowledge_snapshot_id`、AvatarProfile 和可空的 VoiceProfile；同一 Agent 在 Demo 中最多一个可编辑草稿；已发布版本不可原地修改；
- AvatarProfile：内置 3D 模板 ID、受限外观参数、默认/聆听表情、表情强度、动作风格和静态头像兜底；课堂动作由系统状态机驱动；
- VoiceProfile：小组可复用的平台音色 ID、外部音色服务标识与上传/授权溯源元数据；不长期保存原始音频；
- SystemAgentProfile：平台预置且对外命名为 `Maya` 的教师文明互鉴报告角色，不属于学生小组、参辩顺序编号或投票；
- DebateRuleSet：版本化辩论赛制；Demo 的 `ordered_multi_agent_rounds_demo_v1` 根据 `participant_order` 和固定两阶段配置动态生成 turn 计划，并定义提问/RAG/校验、课堂互动收尾和 Maya 报告策略；
- Debate：课堂辩论场；
- DebateParticipant：本场创建时固定的具体 `agent_version_id`、`knowledge_snapshot_id`、A-E 字母型 `slot`、数值型 `order_index`、`stance_mode=assigned|open`、可空的 `initial_stance/current_stance`、可选教师说明及 `initial_position_summary/current_position_summary`；
- DebatePositionHistory：记录 Agent 每次保持、精炼、局部让步、重新框定或彻底换边的时间、前后观点摘要、理由、对方论点和 RAG 证据；
- DebateTurn：任一参辩 Agent 的单次英文发言，保存轮次/槽位、回答问题、反驳对象、新论点、本轮总结、下一人问题、可选按需中文译文、RAG 来源、预生成/公开状态、TTS 文件元数据和运行状态；每门课程最近一次已启动辩论的音频文件保留到下一场启动；
- DebatePlaybackState：教师控制的课堂权威播放状态，保存当前 turn、`preparing|ready|playing|paused|waiting_next|completed|stopped`、`mode=live|replay`、播放游标、语速、控制版本和最近操作教师；live和replay都可在相邻turn之间进入`waiting_next`，普通Dock只用start/next/replay；`next_turn_ready`由服务端根据live successor最终内容或replay retained audio/fence派生，不作为数据库列；教师课堂大屏跟随该状态；
- ClassroomInteractionWindow：某场辩论结束后的一次性课堂互动窗口，保存 `closed|open|finalized` 状态、用于二维码的随机入口令牌、开启/结束时间和操作教师；令牌只是找到当前开放表单的入口，不是观众账号或防重会话；
- TranslationBatch：教师手动触发的测试翻译批次，记录输入内容 ID/哈希、目标语言、成功/失败项和状态；不参与辩论主状态机；
- BarrageInsightSnapshot：由一场已结束互动的冻结 BarrageMessage 集合派生的匿名、不可变洞察；保存主要赞同点、主要质疑点、典型问题、代码计算的各主题数量、筛除数量、输入哈希和内部 source message ID 映射；昵称和原始逐条列表不输入 Maya；
- CivilizationMutualLearningReport：一场辩论的文明互鉴报告聚合对象，保存当前成功修订 ID、整体状态和教师可见的修订关系，与参辩 Turn 分开存储；
- CivilizationMutualLearningReportRevision：每次自动生成或手动重新生成形成的不可变修订，保存 `revision_no`、英文原文、可选按需中文译文、输入快照哈希、生成时间/操作者、成功/失败状态和内部错误元数据；教师空间保留历史；新尝试失败不隐藏旧的当前成功修订；
- BarrageMessage：独立弹幕记录，保存辩论 ID、自填昵称、原始弹幕文本、提交顺序和提交时间，供大屏及教师历史逐条原样展示；聚类时只使用文本和内部 ID，不把昵称传入洞察模型或 Maya；不保存 Vote ID 或学生账号；
- Vote：独立匿名投票记录，只保存辩论 ID、被投 Agent ID 和提交时间；不保存昵称、BarrageMessage ID、学生账号或设备标识；对外只返回汇总；
- AuditLog：关键操作和模型调用追踪。

## 7. API 领域划分（C03 已冻结）

- `/auth`：用户名密码登录、当前身份、已登录切换，以及仅 `DEMO_MODE=true + DEMO_QUICK_LOGIN=true` 可用的匿名安全身份目录/免密quick-login；后两者只返回平台身份字段，不返回密码/配置路径；
- `/courses`：Demo 只查询预置课程/成员；课程创建、加入和多教师管理是正式版扩展，不实现假写接口；
- `/courses/{course_id}/groups`：Demo 只查询两个预置小组和只读成员；建组/邀请/角色管理是正式版扩展；
- `/groups/{group_id}/knowledge-documents`：当前小组 Markdown 资料库的列表、上传、网页新增、下载；后端从会话验证组归属，跨组请求按不存在处理；
- `/knowledge-documents/{document_id}/replace`：copy-on-write 编辑并索引新文档，原子替换同组所有当前draft引用、逐个增加revision；任一草稿超限/失败则全部不切换；
- `/agent-versions/{version_id}/knowledge-documents`：为当前草稿明确启用/停用同组文档并查询索引状态；禁止跨组绑定；
- `/agent-versions/{version_id}/rag-preview`：预览草稿合并 `RAG.md`、字符数、分块/索引与测试状态；不创建发布快照；
- `/groups/{group_id}/agents`：当前小组智能体创建和列表；
- `/agents/{agent_id}`：GET详情；PATCH以metadata revision更新description；DELETE只hard-delete从未发布且从未参辩Agent，有历史返回`agent_history_retained`；
- `/agents/{agent_id}/versions`：继续编辑唯一草稿、创建新版本和查询历史；已发布版本没有更新接口；
- `/agent-versions/{version_id}/publish`：权威校验并原子创建不可变 KnowledgeSnapshot、发布版本和切换当前指针；发布是唯一创建正式快照的动作；
- `/agent-versions/{version_id}/chat`：基于人设与知识库的测试对话；
- `/avatar-profiles`：3D 模板和参数配置；
- `/voice-profiles`：本地音频上传并创建音色 ID、查询状态、临时试听和删除音色；
- `/courses/{course_id}/debates`：创建和查询辩论；
- `/debates/{debate_id}/start|next|pause|resume|finish`：普通教师课堂控制；`next` 在 live/replay `waiting_next` 且相邻 successor 已就绪/有retained audio时显式推进；`pause/resume` 是可恢复 Stop/Continue；`finish` 根据是否已有完整 final-ready turn 集合写入 full 或 partial finished，partial 不开放 interaction/Maya/history/replay；
- `/debates/{debate_id}/replay`：教师整场重播，从第一turn开始并逐段进入replay waiting_next；
- `/debates/{debate_id}/operator-reset`：非普通页面的本机/教师故障恢复，具体暴露方式在`.7` Gate中以最小攻击面冻结；
- `/debates/{debate_id}/turns/{turn_id}/replay`：pre-Wave3 后从普通平台 API/前端移除，不再提供教师单回合重播；历史实现只作为迁移前证据；
- `/debates/{debate_id}/translations`：教师按需批量翻译当前已公开英文内容；
- `/debates/{debate_id}/interaction/open`：教师在全部 turn 完成后打开互动收集，返回大屏可渲染的二维码/入口链接；
- `/classroom-interactions/{access_token}`：免登录 GET 只返回页面所需的辩题和参辩 Agent 选项；
- `/classroom-interactions/{access_token}/votes`：免登录 POST，只接收被投 Agent ID，成功返回 `vote_submitted=true`；不接收或保存昵称/弹幕；
- `/classroom-interactions/{access_token}/barrages`：免登录 POST，只接收昵称和弹幕文本，成功返回 `barrage_submitted=true`；不接收或保存投票选项；
- `/debates/{debate_id}/events`：发言状态流；
- `/debates/{debate_id}/interaction`：教师查询当前收集状态、昵称弹幕列表和各 Agent 票数/占比；
- `/debates/{debate_id}/interaction/close`：教师关闭入口并冻结票数/原始弹幕输入，随后先触发匿名弹幕洞察，洞察校验成功后再自动触发 Maya 报告；
- `/debates/{debate_id}/transcript`：英文辩论记录、可选按需中文译文、来源文件，以及仅在该场仍是课程最近已启动辩论时可用的受权播放信息；
- `/debates/{debate_id}/report`：查询 Maya 生成的文明互鉴报告；
- `/debates/{debate_id}/report/generate`：教师触发/重试文明互鉴报告生成；
- `/debates/{debate_id}/report/revisions`：教师查询本场全部报告修订与失败尝试；
- `/debates/{debate_id}/report/revisions/{revision_id}`：教师查看或下载指定成功修订；
- `/debates/{debate_id}/report/download`：始终可下载英文 Markdown；存在教师按需译文时才允许下载对应中文 Markdown；

所有 API 应返回稳定 DTO；外部模型/语音/未来知识检索实现的供应商字段不得直接泄漏到前端业务契约中。

### 7.1 稳定平台 API 与 Provider/Adapter 边界（已确认原则）

前端只调用本平台自己的业务 API，例如：

- `POST /api/v1/agent-versions/{version_id}/chat`：测试文化智能体；
- `POST /api/v1/debates/{debate_id}/start`：启动辩论；
- `GET /api/v1/debates/{debate_id}/transcript`：获取英文原文、可选按需中文译文、来源文件和当前可回放状态；
- `POST /api/v1/voice-profiles`：提交音色样本；
- `GET /api/v1/voice-profiles/{id}`：查询音色准备状态。

前端请求/响应只使用业务语言，例如 `agent_version_id`、`original_text`、`translated_text`、`sources`、`voice_profile_id`、`playback_url`、`playback_state`、`status`，不得出现某家供应商的模型名、SDK 类型、外部任务字段或 API Key。`playback_url` 是平台鉴权地址而不是供应商 URL；仅在该场仍是课程最近已启动辩论、对应音频尚未被下一场启动清理时有效。

后端把第三方能力隔离为内部接口：

- `LLMProvider.generate()`：生成发言；
- `KnowledgeContextProvider.build_draft_index()`：直接读取当前启用的 Markdown，检查 100,000 字符上限、合并草稿 `RAG.md`、分块并建立草稿索引；
- `KnowledgeContextProvider.build_snapshot()`：把当前草稿的 Markdown、文块和向量冻结为版本化知识快照；
- `EmbeddingProvider.embed()`：将知识文块和当前辩论查询转为向量；
- `VectorStore.search()`：在指定 AgentVersion 快照中检索 `top_k` 相关文块；
- `TranslationProvider.translate_batch()`：教师按键触发后，将当时已公开的英文发言和当前报告批量翻译为简体中文；
- `TTSProvider.synthesize()`：把文字合成为语音；
- `VoiceCloneProvider.enroll()`：根据样本创建音色；
- `VoiceCloneProvider.list_or_exists()`：查询外部音色是否仍存在；Qwen-TTS 不提供详情状态时由平台结合创建响应、试听结果和列表结果维护业务状态；
- `VoiceCloneProvider.delete()`：删除外部克隆音色。

Demo 的文本/音色/TTS 实现阿里百炼 Provider；测试翻译单独实现可选 DeepL API Free Provider，只在教师点击时调用。都通过服务端环境配置选择，例如 `LLM_PROVIDER=alibaba_model_studio`、`TRANSLATION_PROVIDER=deepl`。API Key 只放在后端环境变量或 Secret Manager 中。未来增加供应商时，只新增 Provider 实现和配置，不修改前端页面、业务 API、数据库主键或辩论规则。

供应商原始响应可以存入受限审计日志用于排错，但对前端必须转换为统一 DTO。数据库允许保存 `provider_type`、`external_resource_id` 等内部映射字段，但这些字段不能成为前端继续操作的必要参数。

### 7.2 为什么必须这样设计

- 安全：浏览器看不到 API Key，学生无法复制或滥用模型额度；
- 可替换：某供应商涨价、限流、故障或效果不好时，只替换后端 Adapter；
- 可测试：测试环境用 Mock Provider，不消耗真实额度；
- 可协作：前端、后端和 AI 能力开发者围绕固定 OpenAPI 并行工作；
- 可治理：后端统一做费用上限、重试、超时、内容安全、日志和降级；
- 可组合：未来 LLM、完整文件/检索式知识上下文、TTS、音色克隆可以分别使用最合适的实现，不被“一家公司必须包办全部能力”绑死。

### 7.3 Demo v0.1 真实音色克隆与 TTS 方案（已确认）

音色克隆和语音合成是两个不同阶段：

1. 音色注册/克隆（课前执行一次）：学生只通过本地文件选择器上传一段本人英文录音；平台在后端标准化后调用一次 `VoiceCloneProvider.enroll()`，得到一个外部音色 ID，再映射为小组空间可复用的平台 `voice_profile_id`。不提供浏览器现场录音，建立成功后不保留原始或中间音频文件。
2. TTS 合成（辩论中每次发言执行一次）：规则引擎得到最终英文文字，后端用已存在的音色 ID 调用 `TTSProvider.synthesize()`，生成本课程最近一场辩论可重复播放的音频，不重复进行音色注册。

自定义音色是可选增强，不是 Agent 创建/发布/参辩前提。统一解析规则为：`custom VoiceProfile ready → 使用自定义音色`；`未绑定/validating/enrolling/preview_ready/failed/deleted → 使用 FALLBACK_VOICE_PROFILE_ID`。前端始终显示当前实际使用的是自定义还是兜底音色。

统一平台音色状态建议为：`validating` → `enrolling` → `preview_ready` → `ready`，任一阶段可进入 `failed`，最终可进入 `deleted`。Qwen-TTS 的列表接口本身不返回供应商处理状态，因此这些是本平台围绕校验、注册、试听确认和删除建立的稳定业务状态，前端不认识供应商专有字段。

Demo v0.1 使用阿里云百炼北京地域的 `qwen-voice-enrollment` + `qwen3-tts-vc-2026-01-22` 完成真实英文声音复刻和非实时 HTTP TTS。根据 2026-08-26 核对的[百炼声音复刻用户指南](https://help.aliyun.com/zh/model-studio/voice-cloning-user-guide)和[声音复刻 HTTP API 参考](https://help.aliyun.com/zh/model-studio/voice-clone-design-http-api)，Qwen-TTS 声音复刻支持把本地音频作为 Base64 Data URL 放入服务端请求，不要求 OSS、公网 URL 或临时 URL；北京地域优先使用 `{WorkspaceId}.cn-beijing.maas.aliyuncs.com` 业务空间专属域名，具体域名/API 快照在真实联调时再次核对。

#### 音色 ID 生成方案（已确认）

百炼 `qwen-voice-enrollment` 的一次创建请求接收一个 `audio.data` 并返回一个 `output.voice`。Demo 使用一份连续、清晰的 10-20 秒录音：

1. 页面提供一张固定英文朗读卡，学生在本地提前录好并上传一份 10-20 秒文件；同一本人、正常语速、连续朗读、无音乐/其他人声；
2. 推荐安全文案为：`Technology can connect people across cultures, but responsible use requires fairness, privacy, and respect for human choice. In this discussion, I will listen carefully, respond with evidence, and explain what different perspectives can learn from one another.`；文案放入可配置 i18n/业务配置而不是写死在 Provider；
3. 后端解码该文件，只做确定性的音频预处理：去除过长首尾静音、转换为 WAV 16-bit/24kHz/mono、轻量响度统一；不做改变音色的 AI 降噪、变声或声纹识别；
4. 若有效音频超过 20 秒则拒绝并提示学生重新选择，避免平台在不知道句子边界时自动截断人声；最终注册音频必须是一份连续、清晰的 10-20 秒 WAV；
5. 将标准化 WAV 转为 `data:audio/wav;base64,...`，服务端调用北京地域声音复刻接口：`model=qwen-voice-enrollment`、`action=create`、`target_model=qwen3-tts-vc-2026-01-22`、`language=en`，并把准确英文原文作为可选 `text` 参数辅助复刻；`preferred_name` 使用平台生成的不含个人隐私的短标识；
6. 从响应 `output.voice` 取得外部音色 ID，保存为平台内部 `VoiceProfile` 映射；浏览器和前端永远只使用平台 `voice_profile_id`，不直接依赖外部字段；
7. 原始文件和合并文件在注册请求返回后立即从后端删除；随后只用新音色 ID 合成一段未在原样本中出现的固定英文试听句，进入 `preview_ready`；学生确认后变为 `ready`；
8. 若试听不满意，Qwen-TTS 音色不支持更新原 ID：平台删除该外部音色并将平台记录标为 `deleted/rejected`，学生重新上传后创建一个新 ID；
9. 创建/启动辩论时通过列表接口或真实短试听确认外部音色仍可用；官方当前限制 Qwen-TTS 每账号最多 1000 个自定义音色，且一年未用于合成的音色可能被自动清理。若外部 ID 已不存在，平台把其标记为不可用并使用兜底音色。

端到端实现步骤：

1. 小组成员在上传区看到用途与授权提示；选择一段本地文件并点击“上传并创建音色”即表示确认这是本人声音并授权本课程使用。平台记录 `uploaded_by_user_id`、`consent_accepted_at` 和提示文案版本；
2. 本地文件支持 WAV 16bit/MP3/M4A；前端和后端校验文件不超过 10 MB、可解码、有效时长 10-20 秒且非空；标准化注册音频满足至少 24kHz、单声道和无背景音乐/其他人声要求；
3. 后端把文件写入受控临时目录 `data/tmp/voice-enrollment/{request_id}/`，完成确定性转码和 Base64 Data URL 构造后只调用一次 `VoiceCloneProvider.enroll()`；
4. 百炼返回外部 `voice` ID 后，后端保存 `voice_profile_id -> provider/region/model/external_voice_id` 映射、小组归属以及原文件名、文件哈希、上传人、授权时间和创建时间等 provenance 元数据；前端只显示平台 ID 和状态；
5. 无论创建成功、失败还是超时，后端都在请求结束后删除原文件和标准化中间文件；平台不提供原声音样本 URL、下载或历史播放。页面未刷新时可继续持有本地文件选择产生的浏览器 `File` 对象并直接重试；刷新/关闭后重新选择本地文件即可；
6. 平台用固定且不同于录音原文的英文试听文本调用 Qwen3-TTS-VC；试听音频也只是临时文件，播放后或超时后清理；学生确认后 `VoiceProfile` 才进入 `ready` 并可绑定到智能体草稿/版本；不绑定时继续使用兜底音色；
7. 当前发言英文文本校验通过后，下一位的 RAG/LLM 可以在后台超前生成；下一位文字完成后独立调用非实时 HTTP TTS。供应商返回的音频保存到受控目录 `data/courses/{course_id}/current-debate-audio/{debate_id}/{turn_id}.*`；后台文字和音频准备状态不向观众泄露正文；
8. 正式播放时通过单个 `playback.started` 状态同时公开完整英文气泡、平台鉴权 `playback_url` 和 3D speaking 状态；前端使用 0.95x-1.25x `playbackRate` 并保持音高。同步是同一时刻开始，不做逐词高亮或精确口型；
9. 辩论完成、暂停、停止或失败后不按时间自动删除已经生成的该场音频；只要教师没有启动本课程下一场辩论，本场音频就可通过普通教师页面无限次整场重播，并可在页面刷新后继续访问；普通页面不提供按回合单独重播，后端只为恢复/诊断保留必要的精确 turn 定位能力；
10. 教师启动本课程下一场辩论时，页面必须先确认“将删除上一场可回放语音，但保留文字记录”；确认后后端才清理上一场 `current-debate-audio` 文件并启动新场；取消则不清理也不启动。数据库仍永久保留旧场的文本、可选按需译文、来源、`voice_profile_id`、播放时长和生成状态，但确认清理后旧 `playback_url` 随即失效；
11. 小组可以创建多个 VoiceProfile，平台不额外设置数量上限但受供应商账号配额约束；每个 AgentVersion 最多绑定一个自定义音色。组内任一成员都可以查看、试听、绑定和删除；删除前必须确认，也允许删除正在被草稿或已发布版本引用的自定义音色；
12. 系统预置一个全局可用的英文兜底音色，后端以 `FALLBACK_VOICE_PROFILE_ID` 配置。删除自定义音色时，后端调用百炼删除外部音色、将该 VoiceProfile 标记为 `deleted`，并让所有引用它的 Agent 在运行时自动解析为兜底音色；
13. 为保留版本审计，已发布 AgentVersion 中原来的 `voice_profile_id` 记录不被静默改写，但 API 同时返回 `effective_voice_profile_id=FALLBACK_VOICE_PROFILE_ID` 和 `voice_fallback_active=true`；前端显示“原音色已删除，当前使用兜底音色”。已经合成并保留的当前辩论音频不因后来删除音色 ID 而改变。

兜底音色是系统资源，不属于任何小组，Demo 页面不提供删除按钮；所有没有可用自定义音色的 Agent 默认使用它。后端启动时校验 `FALLBACK_VOICE_PROFILE_ID` 可用；编码期无真实配置时使用 Mock fallback，真实 ID 后置接入。

默认验收为两个克隆音色、2 个 Agent × 2 轮 = 4 次发言；按每次目标约 160-185 个英文词且最多 200 词估算，合成文本通常约 3500-5000 个英文字符。参数化多人场的 TTS 量按 `participant_count × 2` 线性增加；当前仍建议首轮账户总预算 100 元。重播直接使用本机现有音频，不重复产生 TTS API 费用；每课程只保留最近一场音频以限制磁盘增长。所有价格均需在实际充值前复核。

此设计的隐私和存储边界是：平台长期保留“这个小组可以使用哪个音色 ID”以及必要的授权/创建元数据；学生原始录音在声音注册请求结束后立即删除；每课程仅保留最近一次已启动辩论的合成语音，直到教师启动下一场。Demo 的上传动作即表示学生授权，但页面仍必须明确显示用途；不得使用未参与上传的第三人、教师、公众人物或历史人物的拟真声音。

### 7.3.1 Demo 按需测试英译中服务（已确认）

- Demo 不自动翻译任何发言或 Maya 报告。教师测试界面的“翻译当前全部内容”按钮通过可选 DeepL API Free Provider，将点击时已经公开的英文发言和当前报告批量翻译为简体中文；
- 2026-08-25 官方文档快照显示 DeepL API Free 的标准上限为每月 500,000 个字符；官方开发者页当前显示可免费获取 API Key，但注册要求和免费额度可能随地区/时间变化，开通时再以账户控制台显示的 `character_limit` 为准；
- DeepL Free API 端点只允许由后端 Provider 配置，请求使用 `source_lang=EN`、`target_lang=ZH-HANS`，密钥放在后端 `DEEPL_API_KEY`，不得出现在前端；
- 后端 `TranslationProvider` 统一返回 `source_language`、`target_language`、逐项 `translated_text/status` 和内部计费字符数；前端不看到 `DeepL`、外部端点或外部错误字段；
- 批次只处理尚未翻译或英文哈希变化的已公开内容；之后产生的新 turn/报告不自动翻译，教师可再次点击补齐；默认两人两轮加一份报告的按需字符量对本地测试较小；
- 翻译按钮及 API 仅课程教师可调用；Demo 学生制作端不提供课堂译文入口。批次部分失败不回滚成功项，也不改变辩论/报告状态；
- 如果 DeepL Free 注册不可用、额度政策变更或访问不稳定，备选是 Microsoft Azure Translator F0；备选只需新增 Provider，不改前端和辩论数据模型。

### 7.4 API Key、`.env` 与 GitHub 部署边界

- 用户后续自行把百炼 Key 放入后端 `.env`；仓库只提交 `.env.example`，真实 `.env` 必须在 `.gitignore` 中；
- 用户如需测试真实中文按需翻译，后续另行申请 DeepL API Free Key 并放入后端 `.env`；百炼与 DeepL 是两个独立凭据，互不复用；缺少 DeepL Key 不阻塞纯英文辩论和报告，只让教师翻译按钮显示“测试翻译服务未配置”；
- Key 只允许后端读取，变量建议为 `DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE_ID`、`DASHSCOPE_REGION`、`DEEPL_API_KEY`、`TRANSLATION_PROVIDER`、`SESSION_SECRET`；不得写进前端源码、浏览器 Local Storage、接口返回、日志或 `NEXT_PUBLIC_*` 环境变量；
- Demo 运行边界已锁定为“本机运行”：当前不搭云主机、不做 GitHub Pages 部署、不为公网访问额外引入 CORS/域名/证书复杂度；
- 为实现真实手机扫码，“本机运行”允许教师电脑通过同一局域网向手机暴露当前网站端口；`CLASSROOM_PUBLIC_BASE_URL` 只保存当前可访问的局域网基址并用于生成二维码，不是 API Key，不改变“不做公网部署”的边界；
- GitHub 用于源码仓库、Issue、版本、Pull Request 和 GitHub Actions 测试/部署，不作为本项目完整运行服务器；
- GitHub Pages 只能发布 HTML/CSS/JavaScript 静态站点，可以承载静态导出的前端，但不能运行 FastAPI、SQLite写入、文件上传、长期 WebSocket、后台任务或本地持久音频；
- GitHub Actions Runner 是按工作流临时创建并在任务结束后销毁的 CI 环境，不能当持续在线后端；
- GitHub Codespaces 可以临时公开转发端口用于短时开发预览，但重启/可见性/成本和持久运行方式不适合作为正式课堂站点；
- 推荐顺序：v0.1 先在本机完整运行和验收；代码可推到 GitHub 并用 Actions 自动测试；仅在以后确实需要互联网演示时，再把整个前后端作为一个 Docker 应用部署到带持久磁盘和 HTTPS/WebSocket 的普通服务器。届时仍可继续使用 SQLite 和本地文件，但必须挂载持久卷并定期备份；
- 若未来把静态前端放 GitHub Pages，则 FastAPI/WebSocket/文件必须另部署到外部服务器，并额外处理 HTTPS、WSS、CORS、跨域 Cookie 和两个域名；这比 Demo 单机部署复杂，不作为首选。

## 8. 编码前合同 Gate 与后置事项

产品 P0 和 C01-C11 技术合同已全部冻结。以下内容分成两类：编码期必须遵守的 G0 合同，以及不阻塞 Mock 骨架但阻塞真实验收的外部配置/素材；不再把已确认问题重复列为“待用户决定”。

### 8.0 Demo 完整实现模块盘点

下表是真正进入编码后必须交付的 18 个模块。相关技术默认值已写入 G0 合同包；实现不得自行改写，也不再把技术选择逐项推回用户。

| ID | 模块 | 前端范围 | 后端/数据范围 | 开发期实现/后置验证 |
| --- | --- | --- | --- | --- |
| M01 | 本机运行骨架 | 统一入口、环境状态和一键启动提示 | Next.js/FastAPI/SQLite/本地文件、Docker、健康检查 | 技术默认已定：`maya-platform/`、Node 24、pnpm 11、Python 3.12、Caddy 8080 单入口、Docker Compose；精确依赖写入 G0 lockfile 契约 |
| M02 | 全局 UI 与中英文 | 导航、布局、表单/状态/错误组件、`zh-CN/en-US` | i18n 资源、统一响应 DTO | G3 PASS；新增 landing-auth 低风险增量已完成 G1.5 和六视口浏览器验收，待下一次低风险 Sol 批审记录：`/` 顶部卡片左右融合、语言切换置顶、三张教学原则卡对齐，无横向溢出且交互目标均≥44px；Visual Draft V2 不变 |
| M03 | 登录与会话 | 统一首页始终显示 Demo 身份卡、免密进入、常驻密码登录、退出；`/login` 兼容回首页 | 私有0600 Markdown账号同步、服务端Session/CSRF、当前用户上下文 | PW3-A G3 PASS；新增 landing-auth 低风险增量只改前端组合：7个身份和密码字段同屏常驻，旧链接保留站内next，认证API/权限/私有账号边界未改；待下一次低风险 Sol 批审记录 |
| M04 | 课程/小组种子 | 一门课、两个三人小组和成员只读页 | `Course/CourseMember/Group/GroupMember` 种子和查询 | 业务数量已冻结；固定测试 ID 与幂等 seed/upsert 规则由主窗口写入 G0 数据合同 |
| M05 | Agent 工作台/版本 | 多 Agent 列表、`AGENT.md`、description内联编辑、继续草稿、创建新版本、发布更新、安全删除/历史 | `Agent/AgentVersion/metadata_revision/revision/KnowledgeSnapshot` 不可变关系、当前版本指针、删除资格 | PW3-B G3 PASS：空description留空、双端当前投影、跨组404、metadata CAS、脏返回提示、安全DELETE与发布/辩论竞态通过；普通归档/恢复入口已移除，历史归档行由用户显式清理 |
| M06 | Markdown RAG | 批量上传、网页新增/编辑、状态、字符统计、RAG预览、测试聊天、冻结下载 | 不可变文档、copy-on-write replacement、全draft原子引用替换、分块/Embedding/索引/召回/快照 | PW3-C G3 PASS：新增不自动启用；COW编辑、多草稿原子替换、100k/索引/文件/DB/CAS回滚、四检查点恢复和历史字节/哈希/辩论冻结不变通过；命名下载通过；真实Embedding后置 |
| M07 | 3D 头脸 | 模板、受限参数、表情/动作预览、大屏多角色 | AvatarProfile 配置与动作状态映射 | G3 PASS（学生构建/单头脸）：3 参数预设、1 兼容 GLB、Three.js r185/Draco、本地状态动作、浏览器 desktop+360；不虚报 3 个独立资产，多角色课堂编排归 M12 |
| M08 | 音色克隆/兜底/TTS | 本地文件上传、状态、试听、绑定/删除、实际音色提示 | VoiceProfile、百炼适配、FFmpeg 预处理、兜底解析、TTS 文件生命周期 | MOCK G3 PASS；`.6` 真实 TTS 安全代码 G2 PASS。真实声音注册 1 次成功；attempt=1/2/3 三次 TTS 均失败，最新为 `tts_audio_invalid`；profile 保持 preview_ready、无 active preview/文件，`FALLBACK_VOICE_PROFILE_ID` 未激活，本 Gate 禁止重试 |
| M09 | 教师 Agent 检查 | 教师首页当前课程/已发布Agent、制作小组、description、人设/RAG/3D/音色/完整版本历史 | 只读发布视图与带Agent/版本后缀下载 | PW3-E G3 PASS：教师双主导航、能力说明、制作小组、只读3D、平台音色状态和冻结下载均完成；教师仍不能查看/编辑学生草稿，旧版仅历史查看 |
| M10 | 辩论创建/参辩顺序 | 点击选 Agent、自动 A-E、英文议题、固定两轮、指定/开放立场 | 固定版本快照、参与者顺序与 `DebateRuleSet` | G3 PASS（Mock）+ 英文议题 follow-up PASS：2-5 个当前发布 Agent 点击顺序、A-E、固定两轮、assigned/open、draft revision、create/start 幂等、当前发布指针 CAS、精确复合 FK、running fence、typed audio swap、0004 均已实现；创建/修改/启动共享 Latin-script 门禁、稳定 422、前端即时提示、共享生成表、Sol High 与 Docker 浏览器通过 |
| M11 | 辩论 RAG/LLM 生成 | 准备/就绪/无证据状态 | 第1轮观点提示、第2轮反驳/提问/观点更新/文明说服、最后一位全班反思问题、结构校验、重试 | WAVE 3 G3 PASS（Mock）：完整前驱、snapshot 检索、typed receipt、used-only 来源、no-match 一般推理与 v2 lexical anchor 已通过。URL destination 不再提供伪 topic token；AI-school→关系资料反例为 no_match，相关正例 matched；v1/真实 Provider 不变。正式 TikTok 内容仍待验收 |
| M12 | 课堂大屏/实时播放 | 多头脸、气泡、来源、语音；普通 Dock 为开始/下一步/整场重播，phase 为 ready/in-progress/waiting/finished，waiting-only Finish | 预生成一位、live/replay 逐步 waiting_next、手动 Reconnect、隐藏 pause/resume 恢复 primitive、full/partial finish、WebSocket、operator reset、音频保留/清理 | WAVE 3 G3 PASS：`.3` 真实浏览器验证仅手动单次 Reconnect、终态无断线/控制器噪音、完整/不完整 Finish、离开/恢复 waiting、两轮四段 retained-catalog Replay、刷新后按需 acquire、localhost/LAN；主窗口 G2 `P0=0/P1=0` |
| M13 | 匿名投票/原始弹幕 | 独立教师互动页、公开 QR/表单、投票与弹幕独立状态、原始弹幕/票数 | 独立 Vote/BarrageMessage API/表、签名窗口、短事务/匿名幂等、冻结汇总 | WAVE 3 G3 PASS：真实匿名页面分别提交 1 票和 1 条原始弹幕，教师页实时显示 100%/原文；关闭后输入快照冻结，不完整 Finish 无入口 |
| M14 | 弹幕洞察/Maya 报告 | 生成状态、匿名主题、当前报告、历史修订和 Markdown 下载 | BarrageInsightPolicy + ReportPolicy、去昵称输入快照、引用/计数验证、失败/再生 | WAVE 3 G3 PASS：真实页面生成 1 条去昵称 insight 和 609 词报告 v1；昵称不进入 Maya，used-only 证据、真实 ID 计数、恢复与失败保留边界通过 |
| M15 | 历史/回放/测试翻译 | 独立历史区、transcript、来源、逐步整场 Replay、按需中英单视图 | 不可变历史、最近一场音频、TranslationBatch/Entry exact-hash cache | WAVE 3 G3 PASS：Mock 翻译单批 4/4，真实页面中文/权威英文单按钮切换且无重复；四段 Replay 恢复 speech/source，partial 下游封锁通过 |
| M16 | 数据库/文件/迁移 | 无独立业务页，只提供清晰存储/清理提示 | SQLAlchemy/SQLite、Alembic、WAL、事务、文件路径、不可变快照 | 0001-0007 fresh/repeat/populated/downgrade/re-upgrade、历史指纹、typed owner/cache fence 和 foreign_key_check=0 通过；用户授权后运行数据已清空，空库重建登录 smoke 通过后再次删除 `data/` |
| M17 | 稳定 API/Provider/密钥 | 只认平台 DTO 和统一错误 | OpenAPI、Repository/Service/Provider、Mock/真实适配、初始化脚本生成并忽略本机 `.env` | WAVE 3 G3 PASS（Mock）：冻结 OpenAPI 69 operations、生成 Client、response、WS 30/18、commands 6/7、private results 5/6、严格 FastAPI/route 与 secret boundary 全通过；真实 Provider 未进入 |
| M18 | 权限/审计/测试/质量门 | 端到端角色流程、禁用/错误反馈 | 每 API 权限矩阵、AuditLog、结构日志、单元/集成/E2E、CI | WAVE 3 G3 PASS：`.3` 最终后端 433/433、前端 28 files/193 tests、Ruff/mypy 109/ESLint/TS/Prettier/Next、迁移/契约/Secret/Docker/真实浏览器通过；`.3` 主窗口 G2 `P0=0/P1=0`，`.2` Mock RAG P2 false-negative acceptance 继续保留 |

### 8.1 编码前实现蓝图（G0 架构方向已冻结）

建议新产品源码目录固定为 `Maya/maya-platform/`，不在任何参考仓库内直接改造。基于本机当前可用环境，Demo 固定 Node 24、pnpm 11、Python 3.12 和 Docker Compose；锁定精确依赖版本并提交 lockfile，不跟随 `latest`。

```text
maya-platform/
├── frontend/                 # Next.js / React / Tailwind / Motion
│   ├── app/                  # login、student、teacher、audience 路由
│   ├── features/             # auth、agents、knowledge、debate、interaction、report
│   ├── components/ui/        # 小型通用组件
│   └── lib/api/generated/    # 由 OpenAPI 生成的 TypeScript 客户端/类型
├── backend/
│   ├── app/core/             # 配置、错误、会话、日志、事务、任务管理
│   ├── app/modules/          # auth、org、agents、knowledge、debates、interaction、reports
│   ├── app/ports/            # LLM/Embedding/Vector/TTS/Voice/Translation/FileStorage
│   ├── app/adapters/         # SQLite、本机文件、百炼、Mock、向量实现
│   ├── migrations/           # Alembic
│   └── tests/
├── contracts/                # OpenAPI 快照、WebSocket 事件 Schema、错误码
├── docs/gates/               # 模块 Gate Packet、Sol 审计编号和证据
├── infra/                    # Caddy 配置、Docker entrypoint
├── data/                     # gitignored；SQLite、Markdown、快照、当前场音频、临时文件
└── docker-compose.yml
```

运行拓扑采用 3 个轻量容器而不是引入 Redis/Celery：

- `gateway`（Caddy）：只暴露一个局域网入口，例如 `http://<teacher-lan-ip>:8080`；`/api` 和 `/ws` 转发 FastAPI，其余转发 Next.js，统一 Cookie/同源和二维码地址；
- `frontend`：Next.js，只保存页面临时状态，不作为权限、版本、播放或 Agent 数据真相；
- `backend`：FastAPI 单进程/单 worker，SQLAlchemy + SQLite WAL，本机持久目录，内置轻量异步任务管理器和 WebSocket Hub；
- 当前不使用 Nginx、PostgreSQL、Redis、Celery、云对象存储或独立向量服务。未来部署到普通服务器时仍使用同一 Docker 拓扑和持久卷。

后端采用“按业务垂直模块 + 少量 ports/adapters”的务实结构，不复制 OpenMAIC 巨型组件，也不照搬完整六边形样板：每个模块拥有自己的 API schema、service、repository 接口和测试；跨供应商能力统一放在 ports/adapters。后端 OpenAPI 是唯一前后端契约，前端类型由 CI 生成/校验，禁止手写两套漂移 DTO。

### 8.2 模块依赖与并行实现顺序

模块不是 18 个同时随意开工，而是先冻结共享契约，再按依赖波次滚动并行：

```text
Wave 0  M01运行骨架 + M03会话 + M04种子 + M16数据库 + M17契约 + M18质量门
   ├── Wave 1A  M05 Agent版本 + M06 RAG + M09教师检查
   ├── Wave 1B  M07 3D + M08音色/TTS（依赖 Provider/File 契约，可与1A并行）
   └── Wave 1C  M02 UI/i18n 基础和页面外壳
                 ↓
Wave 2  M10辩论创建 + M11生成规则 + M12播放大屏
                 ↓
Wave 3  M13课堂互动 + M14弹幕洞察/Maya报告 + M15历史/翻译/回放
                 ↓
Wave 4  G4跨模块集成 → 真服务尖刺 → G5完整本机验收
```

Wave 0 只建立真实但最小的骨架，不先把所有表/空接口一次性铺满。最窄 Mock 竖切仍优先贯穿教师选 Agent → 两轮发言 → 大屏 → 投票/原始弹幕 → 匿名弹幕洞察 → Maya 报告；学生制作、真实 RAG、3D、音色分别在不破坏契约的情况下替换 Mock。每个 Wave 内按 5.13 的 Luna/Sol 风险 Gate 推进。

### 8.3 数据库分域和文件边界（推荐）

SQLite 只保存结构化状态、权限、版本关系、文本/检索元数据和文件清单；Markdown/音频等字节保存到受控文件目录。API Key、会话签名密钥和原始声音样本不得进入数据库。

| 数据域 | 推荐表 | 关键边界 |
| --- | --- | --- |
| 身份/组织 | `users`、`sessions`、`courses`、`course_members`、`groups`、`group_members` | Demo 凭据哈希仍来自后端 YAML；DB User/成员关系是真实权限来源；Session 使用不透明随机 ID |
| Agent/版本 | `agents`、`agent_versions` | Agent 是稳定身份；同一 Agent 最多一个 draft；published version 永久不可变；`current_published_version_id` 指向当前版本 |
| 知识/RAG | `knowledge_documents`、`agent_version_documents`、`knowledge_snapshots`、`snapshot_documents`、`knowledge_chunks` | 文档归属小组；草稿用关联表选择启用文档；发布冻结 snapshot；chunk 保存文本、来源位置、模型/参数和 float32 embedding BLOB |
| 3D/音色 | `voice_profiles`；Avatar 配置作为 `agent_versions.avatar_config_json` | 3D 配置随版本冻结，不单独制造复杂表；VoiceProfile 是可删除外部资源映射，版本保留历史引用并动态解析兜底 |
| 辩论 | `debates`、`debate_participants`、`debate_turns`、`turn_sources`、`position_history`、`playback_states` | 参与者固定版本/快照/槽位；Turn 与真实命中 chunk 结构化关联；播放状态独立于辩论内容 |
| 互动 | `interaction_windows`、`votes`、`barrage_messages`、`barrage_insight_snapshots`、`barrage_insight_items` | 投票和弹幕没有共同提交 ID；关闭后冻结最终票数与原始昵称弹幕列表；洞察项以内部消息 ID 保持可追溯但不向 Maya 暴露昵称 |
| 报告/翻译 | `reports`、`report_revisions`、`translation_batches`、`translations` | Maya 修订不可变；译文由原文 hash 关联，不回写权威英文 |
| 运维/文件 | `jobs`、`stored_files`、`audit_logs` | Job 持久化状态；所有 MD/音频/快照有 hash、size、kind、path、ref 状态；审计日志统一脱敏 |

本地向量实现不再额外安装一个“看起来像生产”的向量数据库。Demo 每个 Agent 最多 100,000 字符，实际文块量很小；推荐通过 `VectorStore` 接口把 float32 Embedding 保存在 `knowledge_chunks.embedding` BLOB，查询时按 `knowledge_snapshot_id` 加载矩阵并用 NumPy 余弦相似度排序。这样是真正的向量 RAG、容易解释和测试，也避免 Chroma/FAISS/SQLite 扩展带来的第二套持久化与版本兼容；正式版只需替换 Adapter。

Embedding 使用百炼 `EmbeddingProvider`，真实模型名在编码前真实尖刺中锁定；Mock 使用确定性本地向量，只验证流程而不声称语义效果。Markdown 按标题/段落分块，目标约 600 Token、硬上限 800、overlap 100；使用独立 `TokenCounter`，具体分数阈值不拍脑袋固定，先用用户 TikTok 材料做命中/无命中对照，再锁定 `min_score`；`top_k=6` 保持当前约定。

### 8.4 状态机和后台任务边界（推荐）

避免把所有阶段塞进一个巨大 `Debate.status`。持久化为五个相互关联但职责不同的状态：

- `Debate.status = draft | running | debate_finished | completed | failed | stopped`；
- `PlaybackState.status = preparing | ready | playing | paused | waiting_next | completed | stopped`；`waiting_next` 仅允许 `mode=live`，保留刚完成的 current turn 并等待教师显式 Next；
- `InteractionWindow.status = closed | open | finalized`；
- `BarrageInsightSnapshot.status = not_started | generating | ready | failed`；
- `Report.status = not_started | generating | ready | failed`。

Playback 另存 `mode=live|replay`，不增加 `replaying` 状态；`turn.ready` 只表示文字、结构化来源和 TTS 音频均已就绪。前端展示的综合阶段由后端 DTO 推导，例如 `debate_finished + interaction.closed` 显示“等待教师打开互动”，`interaction.finalized + insight.generating` 显示“正在整理课堂意见”，只有 `insight.ready` 才能进入 `report.generating`。浏览器不得自行推进状态。WebSocket 统一 envelope：`event_id + event_type + event_version + debate_id + sequence + occurred_at + payload`；每场 `sequence` 单调递增并持久化。重连先 GET 权威快照，再用 `since_sequence` 追赶事件，避免只靠内存消息。

`Debate.completed` 表示参辩流程完成、互动 finalized 且首次洞察/报告尝试已到终态，不代表报告必然成功；`insight.failed` 或 `report.failed` 也允许 Debate 进入 completed，符合“报告失败不影响已完成辩论”。教师之后可重试洞察/报告，Debate 状态保持 completed。Report 聚合分开保存生成中状态、当前成功修订和最新尝试状态，新尝试失败不能隐藏旧成功报告。

Demo 不引入任务队列，但 LLM、Embedding、声音注册、TTS、翻译、弹幕洞察和 Maya 报告都写入 `jobs`。FastAPI 单进程使用受控 `asyncio` TaskManager；启动时把遗留 `running` 任务标记为 `interrupted/failed`，不假装任务仍在执行。已完成文字/音频可按既有规则恢复播放；在外部生成中重启则按生成失败处理，不跨进程续跑。

关键跨数据库/文件操作：

- 发布 Agent：先在同一文件系统临时目录完成 snapshot 文件/索引产物、校验 hash/fsync，并原子移动到最终不可变目录；随后单 DB 事务创建 snapshot/links/chunks、发布版本并切换当前指针。DB 失败只留下不可见 orphan，由持久 file operation/启动清理器回收；绝不提交一个指向尚未移动文件的 published 版本；
- 音色注册：先建 `jobs/voice_profile=enrolling`，外部请求在事务外执行，`finally` 删除原始/中间声音文件，再短事务写成功或失败；通过独立 idempotency key 防重复收费；
- 启动下一场：旧音频先移动到可恢复的 trash/staging 目录，新场启动成功后再删除；若启动失败则恢复旧目录，避免“旧音频删了但新场没启动”；
- 结束互动：一个短事务关闭入口、固定最终票数并以当时全部 `BarrageMessage` 的 ID/顺序作为不可变输入边界；提交后先异步生成并校验 `BarrageInsightSnapshot`，成功后再生成 Maya 报告。洞察或报告失败都不回滚原始互动数据，可针对同一输入重试。

### 8.5 API、权限和错误默认值（推荐）

- 登录采用数据库 `sessions` + HttpOnly/Secure-in-production/SameSite=Lax Cookie，登录/身份切换时旋转随机 Session ID；默认 12 小时有效；关闭 `DEMO_MODE` 后删除快速切换路由；
- 所有写请求做同源 Origin 检查并携带 CSRF token；匿名互动使用随机 32-byte URL-safe access token，不使用教师 Session；
- API 前缀统一 `/api/v1`；错误 envelope 固定 `code/message/details/request_id`，供应商错误只映射成平台错误码；
- 写操作携带 `expected_revision` 或 `expected_control_version`；发布、声音注册、开始/关闭互动等昂贵/关键命令使用独立 `Idempotency-Key`；
- Vote 和 Barrage 各有自己的随机 `client_submission_id` 用于单次网络重试去重，但两个 ID 不关联、不共用，仍满足“投票与弹幕彻底独立”；刷新页面生成新 ID，仍可再次提交；
- WebSocket 和 REST 都从同一 service/state machine 发事件，必须在数据库提交后广播，不允许大屏领先持久状态；
- 最低自动质量门：Backend `ruff + pyright/mypy + pytest + Alembic upgrade smoke`；Frontend `eslint + tsc + vitest`；集成使用 Playwright。CI 不调用真实外部服务，真百炼/手机/3D验收由可重复脚本单独执行；不设为了数字而牺牲进度的全局覆盖率百分比，但所有权限分支、状态转移和失败边界必须有测试。

### 8.6 最后一组 P0 的已确认结论

1. **同组资料复用与编辑**：`KnowledgeDocument` 归属小组；全新资料只进入组库，不自动启用，学生仍明确选择每个 Agent 草稿的启用集合。编辑已有资料采用 copy-on-write，并自动、原子地替换所有引用旧文档的当前未发布草稿、逐个增加 revision；已发布/取代版本、快照和既有辩论绝不跟随；跨组不可见、不可引用；
2. **Agent 安全彻底删除**：移除归档/恢复功能。只有从未发布且从未参辩 Agent 可物理删除；已有发布、快照或辩论历史时稳定返回 `agent_history_retained`，不得级联删除历史；
3. **教师查看历史与下载**：教师可查看所有已发布历史版本的完整 `AGENT.md`、当时 RAG Markdown/文件清单、3D 配置和历史/当前有效音色状态；学生也可下载本组历史快照。`AGENT.md`、合并RAG和来源文件下载名追加清理后的Agent名和版本号；教师永远不能查看学生未发布草稿，也不能在辩论创建页选择历史版；
4. **Demo 时长**：不让教师编辑硬总时长或单回合时长；继续使用固定两轮、80-200 词和 0.95x-1.25x，并只显示预计时长；API 预留可空字段，正式版再设计硬时间规则；
5. **输入长度**：除既有 `AGENT.md ≤ 12,000 字符`、每个 Agent 草稿启用 RAG 合计 `≤ 100,000 字符` 和真实音色服务所需音频限制外，不再给辩题、昵称、弹幕或单个 Markdown HTTP 文件增加产品级字符/字节上限；只要求相应必填文本去除首尾空白后非空。Demo 不专门设计异常超大请求处理，底层服务器/框架的固有限制不作为产品功能；互动 access token 在 finalized 后失效；
6. **弹幕双层数据链**：大屏和教师历史保留每条昵称与原始文本并逐条原样展示，不审核、不删除、不改写；互动结束后，供 Maya 使用的另一条链去除昵称、聚类相近内容并筛除与辩题无关或没有实际语义的内容，输出主要赞同点、主要质疑点、典型问题、真实数量和筛除数量。Maya 只读验证后的匿名洞察，不读原始列表；投票仍匿名且不与昵称关联；
7. **课堂大屏**：采用 OpenMAIC 的视觉语言但不复制组件：顶部议题/轮次/状态，中央 2-5 个头脸，发言者高亮、其他人由系统使用 `listening+attentive` 状态；大屏不显示 speaking/support/listening/attentive 文字，只用高亮、发言光环、波形、表情和动作表达；底部浮动气泡 + 来源标签 + 控制 Dock，右侧可折叠证据面板；辩论结束后同一舞台按“左侧二维码、中间自动慢速滚动全部原始昵称弹幕、右侧实时匿名票数”展示互动，再切 Maya 报告；
8. **3D 素材**：当前仅私下本机查看的 Demo 不做许可核验，也不让许可审计阻塞开发；优先验证至少 2 个、目标 3 个本地 GLB 与 TalkingHead/Blendshape/多角色性能兼容。若未来含素材公开到 GitHub、交付他人、正式课堂使用或公网部署，必须重新核验来源许可并替换不明资产。
9. **Demo账号**：登录页在 `DEMO_MODE + DEMO_QUICK_LOGIN` 下始终显示全部身份并允许免密进入；用户明确接受Demo期间对所有能访问站点的客户端开放，不做localhost/LAN限制。真实账号Markdown可存明文密码，但必须Git/Docker ignored、0600、绝不进入API/日志/Project/Excel；删除行只停用账号和撤销Session，不删历史User；
10. **description**：空值在学生首页/工作台留空；学生可直接内联编辑，成功后立即反映到学生与教师当前页面；历史版本、快照和辩论不改写；
11. **教师课堂控制与逐步Replay**：普通播放 Dock 只显示开始/下一步/整场重播，课堂 phase 为 ready/in-progress/waiting/finished，页头 Finish 只在 live waiting 时显示；普通 UI 不显示 Pause/Continue。Replay 使用保存内容从第一 turn 开始并每段等待 Next，不重新生成，完整终态刷新后由 Replay 点击按需取得一次 controller；异常恢复保留非普通 UI 的 operator reset 和实际被恢复链使用的后端 pause/resume primitive；
12. **真实LLM开关排除**：pre-Wave3包不实现登录页Mock/百炼按钮、切换API或假模式；真实adapter、结构化输出、费用和辩论级冻结留未来独立真实服务Gate/Wave4。

### 8.7 G0 技术合同冻结清单（编码硬门禁）

当前状态：`C01-C12 基线冻结 / CODING GATE OPEN / WAVE 0 + WAVE 1 G3 PASS（Mock范围） / 历史 WAVE 2 Mock G3 PASS / .6 的 M07+M12 浏览器人工 PASS / M10 英文议题门禁 FOLLOW-UP PASS / pre-Wave3 .7 G3 PASS / M08 真实 TTS FAILED-DEFERRED / 完整 Demo 尚未完成`。`g0-2026-08-28.7-pre-wave3-polish` 已完整经过 `G0-S/G1/G1.5/G2/G3`，五个独立 Gate 的 Sol High 终审均为 `P0/P1/P2=0`，共享 0006/OpenAPI g0.7/WS、全量测试、Docker 和六视口浏览器验收已通过。真实 LLM/Embedding/TTS、M13-M15 和公网部署仍未解锁。

| 合同 ID | 必须产出 | 冻结验收条件 | 当前状态 |
| --- | --- | --- | --- |
| C01 | Scope 与页面地图/三端线框 | 学生、教师、大屏、手机、历史页面覆盖 5.11；每个按钮有权限、前置状态、成功/失败去向 | FROZEN（含 Next 增量） |
| C02 | 领域 ERD 与文件布局 | 所有第 6 节对象有主键/外键/唯一/软删除/快照/级联策略；数据库记录与 Markdown/音频文件生命周期一致 | FROZEN（含 0006 增量） |
| C03 | OpenAPI v0.1 | 第 7 节所有实际 Demo 路径有请求/响应/错误/鉴权；不实现正式版假接口；可生成前端类型 | FROZEN（g0.7；53 implemented + 13 placeholders） |
| C04 | API 权限矩阵 | 每个 API 明确 teacher/group-member/other-group/audience/anonymous；跨组 404、同组无权 403 有测试用例 | FROZEN |
| C05 | 状态机 | Debate、Playback、Interaction、BarrageInsight、Report 五个状态域及允许命令/终态/重启恢复无矛盾 | FROZEN（含 waiting_next） |
| C06 | WebSocket 事件 Schema | 第 5.8 节事件全部版本化，定义 payload、sequence、重连快照和事务后广播规则 | FROZEN（含 readiness-change） |
| C07 | 错误/重试/幂等矩阵 | LLM/RAG、Embedding、Voice、TTS attempt=3 一次性诊断、四回合课堂 TTS 后置语义、翻译、洞察、报告、文件/DB 操作一致 | FROZEN（含 attempt=3） |
| C08 | Provider/文件安全合同 | 前端零供应商字段/Key；临时声音必删；音频清理、fallback、Mock/real 切换和审计脱敏可验证 | FROZEN（含 real-TTS 诊断） |
| C09 | 验收数据与 E2E 脚本 | Bowen/KaiKai 两轮主链、跨组越权、版本快照、RAG 命中/无命中、互动双链、Maya、回放均有可重复验收 | FROZEN（含人工验收增量） |
| C10 | 模块 Gate/文件所有权 | M01-M18 依赖、Luna 所有权、Sol 审计层级、Gate Packet 和独立并行条件明确 | FROZEN |
| C11 | 全局冲突审计 | 三路 Sol 设计挑战 + OpenAPI机械检查 + 主窗口跨文件审计通过 | FROZEN / `.6` SOL HIGH PASS |
| C12 | 用户最终总确认 | 功能范围与四类视觉稿已确认；Visual Draft V2 的无衬线字体、紧凑层级、A-E 槽位、大屏纯视觉状态和互动布局冻结为终稿；用户明确允许打开编码门禁 | FROZEN / CODING AUTHORIZED 2026-08-26 19:06 |

状态只能按 `PENDING → DRAFTED → AUDITED → FROZEN` 推进。C01-C12 历史基线与 `.6` 受影响合同保持 `FROZEN`；`.7` pre-Wave3 polish 已完成全部 Gate 并签署 G3。`.6` 的真实 TTS 仍按用户决定 `FAILED-DEFERRED`，因此不得用 `.7` 的 G3 覆盖或虚报真实语音通过。

### P0 产品边界（已全部确认）

- 账号与课堂边界已确认：6 名学生账号只用于小组制作与发布；教师独立检查已发布 Agent 并控制上课演示；课堂运行不需要任何学生制作账号登录或在线；
- 课堂互动边界已确认：全部参辩发言结束后由教师手动打开二维码；手机页免登录，先输入昵称，再独立提交投票和/或弹幕；两类数据不共用提交 ID、不相互绑定；每个功能当前页面成功后各自禁用，刷新后可再次提交；不限观众数、不防重、不做压力测试；
- 空课堂互动已确认：即使没有任何投票和弹幕，教师仍可点击“结束收集并生成报告”；Maya 正常生成报告并明确写“本场无课堂互动数据”；
- 赛制边界已确认：Demo 固定两轮，不考虑第 3-5 轮；第二轮最后一个 Agent 向全班提出开放反思问题；允许通过证据、礼貌回应和真实观点更新进行文明说服，但禁止直接请求投票或操纵性话术；
- 教学真实性已确认：平台不隐藏补写学生 `AGENT.md`、不为无命中 RAG 偷偷联网或借用他组资料、不故意削弱对照；测试和大屏必须显式展示检索/来源因果；
- 用户后续提供 Bowen、KaiKai 围绕 TikTok 算法争议的正式公开资料；资料未到位不阻塞骨架开发，但不能进行正式 RAG 验收。

### 已冻结的 P0 决策

- 固定种子数据为 1 名教师、2 个三人小组、每组 1 个已发布参辩智能体 Bowen/KaiKai，加 1 个平台 Maya 教师报告 Agent；Demo 支持选择 2-5 个 Agent，但固定 2 轮且不显示轮数选择；默认验收为 2 个参辩者、4 次发言和 1 份文明互鉴报告；
- 第一阶段使用可由用户直接增删的 Demo 账号和免密身份选择；真实账号文件为后端私有0600/Git-Docker ignored Markdown，可含明文密码/teacher-student角色/学生小组；数据库/API仍保留正式认证结构，密码与配置路径不出后端；
- Demo 只使用 1 门预置课程，1 个教师账号和 6 个学生制作账号已加入；只提供课程/成员读取，不实现课程创建、删除、搜索或按课程号加入；课堂观众不加入课程成员表；
- Demo 固定两个预置三人小组，成员列表只读；不实现建组、邀请、退组、移除、管理员设置或组长移交；
- 每组三名学生对本组多个 Agent、共享 Markdown 资料库、各草稿 RAG 启用关系、3D、音色、发布、description和无历史Agent安全删除具有同等权限并使用 revision/CAS 防覆盖；不能列出、读取或编辑另一组数据；教师可查看所有已发布历史的完整冻结成果，但不查看/编辑未发布草稿；
- 保留用户名/密码登录并在统一首页常驻显示；`DEMO_MODE=true + DEMO_QUICK_LOGIN=true` 时同一区域始终显示全部Demo身份并允许任何能访问站点的客户端免密进入；用户明确接受Demo安全风险；关闭任一开关后身份目录和quick-login完全不可用；
- Demo 的 RAG 输入只接受 Markdown（`.md`）文件；不支持 PDF/TXT、OCR、多格式解析或格式转换；支持组知识库网页新增与copy-on-write编辑；
- 每个 Agent 当前草稿中全部启用 Markdown 合计最多 100,000 个字符；新增文件导致超限时拒绝整个新增操作，原草稿不变；
- 不检查文件内容是否重复，也不因同名覆盖；每次上传创建独立 `KnowledgeDocument`，相同内容分别计入 100,000 字符上限；
- 单个 Markdown 读取/分块/Embedding/索引失败不影响其他文件；失败文件可以重试或删除/停用，但失败文件仍在当前草稿时不得发布；
- Markdown 编辑创建新的不可变 replacement；索引成功后自动原子更新所有引用旧文档的未发布草稿并增加 revision，任一草稿超限/失败时整体不切换；已发布快照不变；
- 草稿测试聊天使用最新草稿 `AGENT.md` + 草稿 RAG 索引，显示命中/无命中及来源文件；只保留当前测试页面会话，不进入正式课堂辩论记录；
- 创建 Agent/版本必须由学生主动点击：一个小组可创建多个 Agent；首次点击“创建智能体”才创建 Agent + V1.0 草稿；V1.0 发布后必须点击“创建新版本”才克隆 V1.1 草稿，不因新增 Markdown 自动创建；同一草稿可多次修改 RAG，只增加内部 `revision`，不增加版本号；Demo 同一 Agent 最多一个可编辑草稿；已发布版本不可原地改写；
- 组内 `KnowledgeDocument` 可以被同组多个 Agent 草稿明确勾选复用；新建资料不自动启用，但编辑已启用资料会自动更新所有未发布草稿引用。每个AgentVersion发布独立KnowledgeSnapshot；其他小组不能看到或引用任何Agent/MD/RAG；教师只在已发布快照范围内查看完整历史；
- Agent 移除归档/恢复并改为安全彻底删除：只有从未发布且从未参辩时可删除；有历史时拒绝且不破坏版本、快照或辩论。发布更新后教师不能再为新辩论选择旧版本，已创建辩论继续使用其固定版本；
- 发布 AgentVersion 必须同时满足：`AGENT.md` 非空且不超过 12,000 字符；至少 1 个启用 RAG Markdown 已成功索引；总量不超过 100,000 字符；无启用中的失败/未完成文件；3D 头脸已配置；测试聊天和自定义音色不强制。后端返回稳定 `publish_blockers[]`；没有 `ready` 自定义音色时自动使用兜底音色；
- Demo 采用真正的检索式 RAG：直接对 Markdown 分块、Embedding、写入本地向量库，每次发言根据当前辩题、教师指定立场（如有）或当前观点摘要、对方论点和问题召回 `top_k` 相关文块，不把完整 `RAG.md` 直接注入模型；
- 已发布 AgentVersion 永久绑定发布时生成的不可变 KnowledgeSnapshot；知识变化必须发布新版本才影响未来新建辩论，旧版本和旧快照不被静默修改；
- 删除已被发布快照引用的当前 Markdown 时，从工作区和新版本可用集合隐藏，但保留快照中的 Markdown 内容、文块、向量和来源关系，供历史版本/辩论复现及教师查看下载；无引用后才允许未来物理清理；
- Demo 辩论创建页只允许教师选择每个 Agent 的当前已发布版本，不提供历史版本选择器；创建成功立即固定 `agent_version_id + knowledge_snapshot_id`，后续发布 V1.1 不影响本场；历史辩论显示当时使用的版本和来源文件；
- 前端引用标签继续显示原始文件名；学生/教师下载已发布 `AGENT.md`、合并RAG和来源Markdown时，文件名在原始基名后追加Agent名和版本号；
- 学生自由编写/上传 `AGENT.md`，平台不强制任何人设栏目；可提供一键插入且可全部删除的参考大纲；单文件最多 12,000 字符；
- Demo 的 LLM/音色克隆/TTS 统一使用阿里百炼的一个服务端 Key；测试按需英译中可另用一个可选 DeepL API Free Key；两类能力都隔离在可替换 Provider 后面；
- Demo 已选定阿里云百炼北京地域，文本模型为 `qwen3.7-plus-2026-05-26` 非思考模式，真实声音复刻/TTS 为 `qwen-voice-enrollment` + `qwen3-tts-vc-2026-01-22`；
- Demo 角色为 Bowen 与 KaiKai，英文辩题为 `Should the United States ban TikTok's recommendation algorithm?`；
- 教师输入的英文议题必须非空但不设产品级字符数上限；创建/修改/启动遵守 5.5.2 冻结的共享 Latin-script 门禁和稳定 `topic_language_invalid`，不得接受中文/其他脚本后拖到生成阶段才失败，也不得自动翻译议题；
- 参辩 Agent 数量至少 2 个、最多 5 个且不能重复；教师按点击先后选中参辩者，系统自动连续分配 A-E，该字母同时是每轮发言顺序；Demo 使用单一参数化 `ordered_multi_agent_rounds_demo_v1` 按参与者顺序生成固定两轮 turn，不为每种人数建立独立规则；
- A-E 只表示参辩顺序；教师报告角色固定命名为 Maya，Maya 永远最后运行且不参辩、不投票、不增加 3D 头脸；
- 创建辩论草稿时固定参与者的版本/快照；教师在启动前可以主动修改议题、参与者、A-E 顺序和立场模式/说明并重新固定；轮数固定为 2，启动后这些设置全部锁定；
- Demo 同一课程同一时间最多 1 场 `running` 辩论，但可保存多个草稿和历史辩论；
- 启动时校验规则集、参与者数量、版本/快照和 3D，并解析每个 Agent 的有效音色；开发阶段允许 Mock 检查；
- 每名参辩者可使用 `stance_mode=assigned|open`：教师可指定 `support|oppose|neutral`，也可完全不设置立场，让 Agent 基于自身 `AGENT.md`、RAG 和上下文阐述观点；一场不强制同时存在支持方和反对方；默认 TikTok 验收仍为 Bowen 支持、KaiKai 反对；
- 所有参辩 Agent 都可以因他人论点或 RAG 证据精炼观点、局部让步、重新框定或在指定模式下换边；后端始终保存前后观点摘要和 `DebatePositionHistory`，显著变化必须提供理由/证据；
- 调度固定两轮，每轮按 A→B→C→D→E 实际选中顺序执行，总 turn 数为 `participant_count × 2`；默认两人场自然得到 `R1-A→R1-B→R2-A→R2-B`；
- 每次参辩发言都必须实际执行 RAG 检索并总结当前观点；第 1 轮专注“观点 + RAG 证据”，不强制反驳/提问；第 2 轮必须结合 RAG 回应/反驳具体观点、提出问题、评估新证据并更新自己观点，通过证据、礼貌和回应性进行文明说服；无证据时允许 `no_match/general_reasoning`，不得硬编来源；第二轮最后一个 Agent 必须改向全班提出反思问题；禁止直接拉票或操纵性话术；
- 平台系统提示不得隐藏补写学生人设、论据或来源；好的 `AGENT.md` 与相关 RAG 应凭真实输入表现更好，弱输入允许得到泛化、无来源但诚实的结果；
- 最后一个计划 turn 正常完成后进入等待互动状态；教师手动打开二维码后，免登录手机页先要求昵称，再允许分别调用独立投票 API 和独立弹幕 API；辩论若提前失败/停止则不能打开；
- 教师点击“结束收集并生成报告”后，平台冻结最终匿名票数和全部逐条“昵称 + 原文”弹幕；大屏/教师历史继续原样展示全部弹幕，后台仅用去昵称文本聚类相近观点、筛除无关/无实质内容并由真实消息 ID 计算数量；Maya 只读取完整辩论、实际引用的 RAG 证据、最终票数和验证后的匿名洞察，不读原始弹幕；Maya 不宣布胜者、不加入投票；
- 文明互鉴报告英文原文 600-900 词，完成时不自动翻译；网页保存/查看并支持下载英文 Markdown；教师点击“翻译当前全部内容”后可查看/下载测试用中文译文；Demo 不生成 PDF、不做 TTS、不为 Maya 增加 3D 头脸；
- 教师结束互动收集后自动触发报告，同时保留“重新生成报告”按钮；报告失败不影响已完成辩论/互动汇总，只将报告标记为 `failed`；
- 报告重新生成不覆盖旧版本；教师空间保留全部报告修订和失败尝试元数据，默认展示最新成功版本；Demo 学生制作账号和匿名手机表单都不展示报告；
- 辩论规则采用版本化 `DebateRuleSet` 和可替换策略模块，Demo 使用单一参数化 `ordered_multi_agent_rounds_demo_v1`；调度、RAG、校验、Maya 报告与提示词分层，不写死在前端或单一提示词中；正式发布前再认真重做赛制；
- Demo 辩论权威内容使用纯英文，网页支持中文/英文两套静态界面文案；不自动翻译发言/报告，教师可用按钮按需批量翻译当时已公开内容供测试，译文不进入后续辩论上下文、TTS 或报告输入；
- 英文单次发言 80-200 词、建议目标 160-185 词；问题计入总词数；模型结构化响应建议 `max_output_tokens=512`，`speech` 由业务校验器强制不超过 200 词；TTS 语速 0.95x-1.25x；
- 轮次由规则控制，不设置主持人/裁判 Agent；
- 3D 采用模板化选择和参数化调整；
- Demo 目标内置 3 个兼容 TalkingHead 的头脸/头肩模板，学生不能上传自定义 GLB；2-5 人场允许复用模板并通过材质主题、姓名卡和槽位区分；当前私下本机 Demo 不把许可核验设为阻塞项，优先解决模型/Blendshape/多角色兼容；公开分享、交付或正式课堂使用前必须重新核验素材来源许可；
- 3D 只开放模板、肤色/材质、资产支持时的眼睛颜色、默认表情、`low|medium|high` 表情强度和 `calm|active` 头部动作风格，不开放自由捏脸/任意数值；
- `idle/listening/speaking/thinking/nod_yes` 由系统按课堂状态自动驱动；新增独立 `attentive` 聆听表情，非发言者自动使用 `listening + attentive`；学生只选择风格和预览，不编排 turn 动画；
- 单个 3D 模型加载失败时以静态头像/姓名卡兜底并继续辩论；该路径只用于异常防御，不是主验收效果；
- v0.1 使用真实外部声音复刻服务，不使用 Mock 作为主验收；
- 英文样本由学生本人录制；Demo 只上传一段连续、清晰的 10-20 秒本地文件；点击上传/创建音色即表示授权，平台记录上传人和授权时间；
- Demo 音色样本只允许本地文件上传，不提供浏览器麦克风录音；文件可为 WAV 16bit、MP3 或 M4A，页面提示本人声音、纯英文、无音乐/其他人声；
- 后端无论音色创建成功、失败或超时都立即删除原始和中间样本；页面未刷新时可复用浏览器持有的本地 `File` 对象重试，刷新后重新选择本地文件；
- 小组可创建多个 VoiceProfile，平台不另设数量上限但显示供应商配额错误；每个 AgentVersion 最多绑定一个；组内任一成员可创建、试听、绑定和删除，删除前确认，删除后运行时自动使用兜底音色；
- 声音样本只临时保存于后端，以 Base64 调用百炼，无公网/临时样本 URL；请求结束后自动删除原音频，小组长期保留可复用的平台音色 ID 和创建/授权元数据；
- 每门课程保留最近一次已启动辩论的全部已生成语音，直到教师启动下一场才清理；此期间普通教师页面只支持逐步式整场重复播放，不提供按 Agent/轮数单回合播放；更早辩论只保留文字等记录；
- 已发布智能体使用的自定义音色 ID 可直接删除；运行时自动切换到系统 `FALLBACK_VOICE_PROFILE_ID`，前端明确显示兜底状态；
- 自定义音色是可选能力；所有未绑定、未就绪、失败或已删除自定义音色的 Agent 默认使用系统兜底音色，不阻塞 Agent 发布、辩论创建或启动；有 `ready` 自定义音色时优先使用；
- Demo 技术栈采用 Next.js + FastAPI + SQLAlchemy/SQLite + 本机 Markdown 文件 + 本地向量库 + FastAPI WebSocket，不使用 PostgreSQL、Redis、Celery 或云对象存储；
- Demo 计划使用兼容 TalkingHead 的通用/历史风格 3D 头脸和姓名卡，不要求精确历史名人外貌；私下本机验收只要求完成模型/Blendshape/多角色性能验证，暂不做许可核验；真正让 Lincoln 等历史扫描开口列为正式版工作；
- 除 `AGENT.md`、RAG 总字符数和音色服务输入等已冻结规则外，Demo 不给辩题、昵称、弹幕或单个 Markdown 增加产品级大小上限，也不专门处理异常超大请求；必填文本只校验去除首尾空白后非空；
- 百炼 API Key 由用户后续放入后端 `.env`，不得提交到 GitHub 或暴露给前端；
- 互动提交不绑定学生制作账号；投票与弹幕是两个独立功能和数据对象，当前手机页内各自成功后各自禁用，不相互影响；刷新页面后两者都可再次提交；Demo 不签发观众会话或防重；
- 小组共享同一份内容并轮流保存，不做实时协同编辑；
- 弹幕不限速、不做敏感词和人工审核；弹幕与投票各自独立提交和存储，但由教师统一打开或结束整个互动收集窗口；进入报告生成后不重新打开当前收集窗口；
- 课堂实时通信采用 WebSocket；
- 只有当前课程教师账号可以控制开始、下一步、整场重播、测试翻译、打开互动收集和结束收集/触发 Maya；普通播放Dock只显示前三项，Replay也逐段Next。异常operator reset不显示在普通页面且仍需本机/课程教师权限；学生和匿名手机页不能调用课堂控制；
- 后台最多超前准备下一位的 RAG/LLM 和 TTS，文字与语音可分阶段生成；教师大屏在教师点击开始/下一步并进入正式 `playback.started` 时才同时收到该 turn 的完整英文气泡、音频和 3D speaking 状态，不提前泄露预生成内容；匿名手机页不接收播放内容；
- 教师点击开始只播放首个 turn；自然结束后进入等待教师下一步，只有下一位内容 ready 且教师点击“下一步”才公开/播放；Replay从首个已保存turn开始并采用相同逐段Next门禁，不重新生成；普通页面不再提供跳过；
- 网页刷新/短暂断线按后端 `cursor_ms` 恢复；后端进程重启从被中断 turn 开头重播且不重新生成；`failed/stopped` 不可恢复；
- 启动下一场前必须弹出“删除上一场可回放语音但保留文字”的确认；只有确认后才原子地清理旧音频并启动新场，取消时均不执行；
- 单个 LLM/RAG 发言重试 1 次仍失败时终止整场辩论，保留已完成记录，Demo 不从失败回合继续；
- 后端保留的停止 primitive 或本机 operator reset 一旦触发，必须立即停止当前音频/动画并丢弃尚未完成的返回结果，不播放、不生成任何后续发言；普通教师页面不显示 Stop 按钮；
- 真实 TTS 失败已经出现：当前诊断 Gate 只允许新的 attempt=3 最多调用一次且自动重试为 0；普通失败保持 `preview_ready`，timeout/收费不确定进入 `outcome_unknown` 并禁止再调用，不生成静音、不用浏览器朗读、不把 Mock 提示音或文字模式冒充成功。真实四回合课堂中是终止 turn、终止整场还是教师重试，仍须在该课堂 Gate 前另行冻结；
- Demo 仅在本机运行；不实施云部署；将来需要互联网演示时，接受把整个 Docker 应用放到带持久磁盘的普通服务器；
- Demo 不实现 Evaluation 产品模块、评分报告或专项协作流程；
- 前端只依赖平台稳定 API，不直接依赖模型、向量库或音色供应商。

### 已明确的后置接入任务（不阻塞代码骨架，阻塞真实服务最终验收）

- API Key 后置：编码阶段先实现 Provider 接口、Mock Provider、初始化脚本生成并忽略本机 `.env`、缺少密钥时的明确状态和自动化测试；用户之后单独把真实 `DASHSCOPE_API_KEY` 放入本机 `.env`；`DEEPL_API_KEY` 只在需要真实测试按需翻译时配置；不得写入代码、文档、前端或 Git；
- 兜底音色当前状态：配置边界、自动回退逻辑和 Mock 删除回退已通过 G3；真实百炼系统音色已创建并保存为平台内部 profile，但 TTS 技术试听失败，状态仍为 `preview_ready`，因此本机环境尚未设置 `FALLBACK_VOICE_PROFILE_ID`。必须先完成无额外 enroll 的 TTS 诊断/复验，只有 profile `ready` 后才允许激活；
- 真实服务联调状态：百炼基础凭据和真实声音复刻已验证；真实 TTS、文本 LLM、Embedding 和可选 DeepL 尚未通过。Mock 端到端可继续，但不得把声音注册成功扩大声称为真实语音/辩论可用；
- 最终 Demo 核心验收前必须完成：百炼真实 Key 可用性、额度/地域、两名学生音色注册、兜底音色回退、四次辩论文本/TTS、当前场语音重播和密钥不泄漏检查。DeepL 真机按需翻译仅在用户届时配置 Key 时追加验收，不阻塞纯英文核心 Demo。

### 正式版/外部后置议题（不阻塞 Demo 合同或编码）

以下事项明确不在 Demo 内解决，也不再作为当前“待确认”阻塞项；只有范围升级到正式课堂/生产部署时才重新立项：

- 从 SQLite/本机文件/本地向量 Adapter 迁移到生产数据库、对象存储、生产向量库和任务队列；
- 课程创建/加入、小组邀请与角色管理、多教师后台、教师评分、作业截止、课程归档、版本回滚/对比和成果批量导出；
- 生产级账号/SSO、限流、30-60 人并发承诺、反作弊、内容审核、未成年人数据治理、声音冒用防护和学校合规；
- 正式版可编辑总时长/单回合时长、第 3-5 轮或其他赛制、主持/裁判和更精细的暂停恢复；
- 公开分享/交付/正式课堂所需的代码、模型、3D 素材和数据许可审计；
- 更早辩论的语音长期保存或下载；Demo 已冻结为仅网页播放最近一场语音，其他文字/来源/弹幕/票数/报告长期保留；
- DeepL Free 额度、区域或隐私条件变化时切换 Azure Translator F0/其他翻译 Provider；
- 正式生产成本上限、备份恢复、监控告警和公网部署运维。

## 9. 当前风险

- **Wave 3 final + pre-Wave-4 UX/state delta：CLOSED**。终态/superseded/4401/HTTP 401/4403/network/sequence-gap、简化 phase、waiting-only Finish、CAS/重启、partial downstream、两轮 retained Replay、locale-only 控件、localhost/LAN 与 Mock RAG v2/v1 边界均已通过主窗口 G2 与真实浏览器 G3；`.3` 最终 `P0=0 / P1=0`，此前接受的 P2 仅是 Mock Latin 双词门禁与 URL 删除可能保守产生 false negative；任何已知无关资料 `matched` 仍会重新阻断 Gate。
- **运行数据已按授权彻底清空**：`data/`、`backend/data/`、14 场历史、Bowen/KaiKai/Crystal 发布数据、互动/报告/翻译记录和旧备份均已删除且不保留恢复副本。空库 0007/登录 smoke 证明可重建，但下一次 Demo 必须通过正常学生流程或明确 fixture 重新创建 Agent/RAG/发布数据，不能假定旧内容仍存在。
- **私有运行边界已收紧**：最终只保留 0600 的 `.env` 与 `backend/config/demo-accounts/accounts.private.md`。旧 `demo_users.yaml`、个人语音输入和私有快照已删除；任何后续 bootstrap/复制不得重新形成双账号源或把这些文件加入 Git。
- **课堂 LAN origin 仍是环境风险**：`.3` 已证明配置 LAN 和同端口 localhost/127.0.0.1 的 authenticated REST/WS 均可用，且 QR 继续使用配置 LAN；换网络、换 IP 或并行 Compose 项目仍会使二维码/手机访问失效。演示前必须检查唯一 8080 占用者、`.env` LAN origin 和手机可达性；非 loopback 错配继续按 4403 拒绝。
- **Mock 内容质量风险已收窄但未消失**：v2 lexical anchor 已阻断已知 TikTok/爬山/AI-school→关系资料误命中，并从正文匹配中删除 HTTP(S) URL destination；它仍可能保守拒绝只靠同义词、非 Latin 文本或 URL slug 表达相关性的资料。此 false negative 是明确接受的 Mock-only P2，不代表真实翻译、真实 TTS/LLM/Embedding 或正式 TikTok 内容质量；`FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING` 与 M08 `FAILED-DEFERRED` 保持不变。
- **候选可复现性：CLOSED（2026-08-30）**。本地检查点 `d541b65 feat: complete wave 3 manual feedback candidate` 已建立，提交包含 102 个 Wave 3/人工反馈源文件与 Gate，提交后产品工作树干净；未 push、未部署，私有运行资料和运行数据未进入 Git。
- **真实业务竖切边界**：已用既有完成辩论完成互动关闭、匿名 insight 和 Mock report 主流程，并确认匿名入口关闭态；这证明候选链路，不证明真实 Provider、真实模型质量或生产并发。
- **匿名课堂配置风险**：`CLASSROOM_PUBLIC_BASE_URL` 现在已配置，但 Compose 默认值为空；换机器或改 origin 会使打开互动返回 `503 classroom_public_url_unavailable`。二维码和匿名手机页仍依赖该规范 LAN origin；私有 Demo 教师页可使用相同端口的配置 LAN、localhost 或 127.0.0.1，其他地址不得混入。
- **独立复审残余风险：CLOSED for Wave 3**。interaction token/短事务/匿名幂等、Maya 去昵称/证据边界、translation 恢复、Pause/Continue、Finish、Reconnect、Replay、控制权和 RAG v2/v1 均有独立 G2 证据；未来改动仍须重新过 Gate。
- 最大的当前进度误判风险是把 `WAVE_3_G3_PASS（Mock 范围）` 当成“完整真实服务 Demo/正式发布完成”。现有代码覆盖 M13-M15 与最终播放反馈；仍缺真实 TTS/LLM/Embedding、正式内容质量、30–60 人课堂负载、许可/隐私和生产部署验收；
- C01-C12 的 `FROZEN` 表示产品/编码前合同冻结；Wave 0/1/2 的 G3 与 Wave 3 候选证据各自有明确边界，不代表 Wave 4、真实 TTS 或正式发布已可用；
- 原 Wave 0 Docker Desktop `starting` 阻塞已关闭：最终镜像、三服务、8080、认证、迁移、种子和 FFmpeg 已实机通过。剩余运行风险转为可复现性风险：Docker Desktop、Debian/npm 镜像和本机网络仍可能在未来冷构建时波动；课堂演示前必须运行短健康/login smoke，不能把“本机今天跑过”当成永久可用；
- Demo 身份目录风险已从“有时不显示”变为明确的部署安全边界：当前 `accounts.private.md`、稳定绑定、匿名身份目录和免密 quick-login 已通过 G3，但任何能访问 Demo 站点的客户端都能进入教师或学生身份；只允许受信任的私下本机 Demo，局域网课堂或公网前必须关闭 quick-login 并恢复正式认证；
- 用户明确接受 `DEMO_MODE=true + DEMO_QUICK_LOGIN=true` 时任何能访问站点的客户端都能免密成为教师或学生，以及私有配置文件保存 Demo 明文密码。这只适用于受信任的私下 Demo：一旦开放局域网、课堂共享、公网或正式发布，教师接管和明文凭据风险立即变为 P0，必须关闭 quick-login、改强凭据/SSO并重新设计账号管理；
- `.env` 与 `accounts.private.md` 均为 0600；旧 `demo_users.yaml`、SQLite/WAL/SHM、Markdown/快照运行数据和私有输入已经按授权删除。应用重建时会重新创建 0700/0600 数据边界并已有空库 smoke 证据；部署到普通服务器时仍需使用专用非 root 账号并重新核验挂载所有者；
- `sessions` 表只保存 Session/CSRF 哈希、用户、过期时间和撤销时间；当前尚无撤销/过期 Session 的定期清理策略，短期 Demo 不阻塞，但长期登录测试或部署前应增加保留期和清理任务，避免表持续增长；
- 当前任务治理的主要风险不是缺少更多产品确认，而是反复重新询问已冻结决定或让实现反向改需求。Wave 1/2 已由主窗口 + Sol Gate 冻结并实现；后续 Wave 3 或真实 Provider 只把会改变体验、数据留存、权限、互动规则、报告语义或真实成本的事项再次请用户确认；
- 当前合同规模已经达到 18 个实现模块、59 条 API path、68 个 operation、23 个 Mock E2E 和 7 项人工实机验收；即使功能做简化，也不是一两页静态网站。严格禁止复制参考仓库实现代码会提高原创性和可维护性，但会增加实现时间和首轮缺陷概率，必须坚持最窄竖切、分波次 Gate 和早期集成；
- 本机 `/opt/homebrew/bin` 已由用户收紧为 `0755`，真实凭据使用前的 PATH 可写风险已关闭；后续 Homebrew/系统工具升级后仍应复核所有者与权限，不由应用代码修改系统目录；
- 本轮 Ruby/Psych 只读检查额外报告 `/opt/homebrew` 父目录本身为 `0777` 且没有 sticky/ACL。即使 `/opt/homebrew/bin` 是 `0755`，可写父目录仍可能允许目录替换，不能把前述风险视为完全关闭；Wave 2 Mock/代码不因此阻塞。attempt=3 真实调用不得在 Homebrew PATH 下运行：优先只在重建并锁定依赖的 backend Docker 容器内用容器 Python 执行，宿主只调用 root-owned `/usr/local/bin/docker`；若容器内无法完成，则必须停止并请用户/管理员修复 `/opt/homebrew`，不得回退到宿主 `uv/python/ffmpeg`。主窗口未获授权修改系统目录；
- 当前 OpenAPI 已通过 Redocly、独立 SHA、生成 TypeScript Client、69-operation response contract、严格 FastAPI route/schema 与 13 个 comparator 负例；Wave 3 的 13 个占位已全部实现并移除。WebSocket 为 30/18，commands 6/7，private results 5/6，生成 clean-diff 通过；后续 Wave 4 仍不得把 allowlist 变成逃生口；
- 历史已签基线为 `g0-2026-08-27.5`：Debate CAS/复合关系、final-ready RAG/生成、单一浏览器 controller、current-only media ticket、WS private result、snapshot watermark、Range/ETag 和恢复/日志边界均已由 0004、生成 Client、数据库约束、Schema 反例和 E2E 落地；人工验收修复使用 `g0-2026-08-28.6-manual-acceptance-delta`，教师 Next/3D/TTS 安全实现已经通过集中 Sol High G2，但这不覆盖失败的真实 TTS 结果或未完成的人工页面签字；
- C02 身份/组织、Wave 1 Agent/RAG/Voice、Wave 2 Debate/Playback、pre-Wave3 与 Wave 3 已形成 `0001 + 0002 + 0003 + 0004 + 0005 + 0006 + 0007` 迁移链；0007 的 fresh/repeat/populated、downgrade/re-upgrade、完整历史指纹、typed Job/cache fence 和空外键检查均通过。最终运行数据已删除；下次启动从空库升级到 0007，不得改写 0001-0007；
- 视觉基线现已冻结为 Visual Draft V2：全站使用 V2 柔和无衬线栈和紧凑标题/正文层级，不使用 Georgia/Times；A-E 槽位、大屏纯视觉状态和互动三栏布局继续有效。学生端和课堂大屏均已用真实本地 GLB/Three.js 画布验收 desktop+360，多槽复用兼容资产可运行，但教室后排主观可读性仍需用户实地检查；
- 视觉迭代过度风险已通过冻结规则控制：除真实可读性、溢出、无障碍缺陷或用户明确重新打开视觉决策外，不再调整全局字体、标题、字号、字距、配色和视觉气质；RomanticSimulation 仍只影响后台留白/卡片/响应式，不定义平台气质；
- 大屏取消 speaking/listening 状态文字后，真实 3D 的发言光环、头像对比、注视和点头幅度必须在教室后排/投影距离实测，否则纯动作可能过细；原始弹幕自动慢速滚动也需按平均文本长度与投影清晰度调速，并保留悬停暂停和减少动态效果降级；
- `RomanticSimulation` 对运行模型有参考价值，但它的 PostgreSQL/Redis/Worker/恋爱场景与当前 Demo 不同，而且未见自动化测试；直接复制会带入无关复杂度和未验证行为；
- 需求很容易被 3D、语音和多人协作同时拉大，必须先锁定 Demo 的“真功能”和“假实现”；
- 直接改造大型开源平台会带来高理解成本、许可证约束和不必要的部署复杂度；
- 多 Agent 辩论的模型费用和延迟会随参辩人数和完整上下文长度快速增长；Demo 已固定两轮，但 5 人场仍有 10 个发言；
- RAG 质量不只取决于资料总量，还取决于文档质量、分块边界、Embedding 模型、查询构造和 `top_k`；检索查询若只使用宽泛辩题，容易漏掉针对对方新论点的证据；
- Wave 1A 的 256 维确定性 Mock Embedding 是真正落盘和余弦排序的本地向量流程，但只用英文 token feature hashing，不能代表百炼 Embedding 的语义质量；`strict=0.20/relaxed=0.08` 只是可重复测试阈值。用户正式 TikTok Markdown 和真实模型到位前，不得把当前 matched/no_match 结果宣传为最终教学效果；
- 英文议题门禁依赖 Node 24.14.0 冻结生成的 Unicode `Letter && Script_Extensions=Latin` 码点表；Python/TypeScript 运行时只读取生成表，不各自猜测脚本。未来升级 Node/ICU 时必须显式重新生成、审查 diff 并同时发布两端表；CI clean-diff 禁止静默漂移。该门禁是 Demo 的确定性 Latin-script 近似，不是自然语言识别器，不能证明输入语义上真的是英语；
- Wave 1A 的 `knowledge/services.py`、`agent-workspace.tsx` 和全局样式仍较大；Wave 2 已拆为 setup/generation/playback/provider/stage 边界，但 playback service、stage 和对抗测试因状态机/竞态覆盖已经很长。Wave 3 不得继续把互动/报告逻辑堆入这些文件，应通过稳定 DTO/策略/Repository 新模块接入；同时不做无验收收益的全仓重写；
- 主窗口已在真实浏览器登录学生和教师账号，直接检查登录、学生 Agent 工作台、教师页的 desktop/360px、双语、3D 画布、导航、溢出与控制台；用户下一次人工检查重点转为主观视觉/交互感受，而不是弥补自动验收空白；
- 100,000 字符上限必须按统一换行后的 Markdown 实际文本字符数计数，不包含系统来源标记；由于不做重复检测，学生重复上传的内容会重复占用额度并可能降低检索质量；
- 原始弹幕全部带昵称展示会把重复、玩笑或不当文本原样放上大屏，这是用户确认的私下 Demo 边界；但 Maya 不直接读取原始列表，而依赖聚类筛选层。筛选策略若过度会扭曲少数意见，若过松会让无关内容污染报告，因此必须保留内部 message ID 映射、代码计数和 included/filtered 数，并测试“少数批评意见不得因不受欢迎而被过滤”；
- 辩论规则会在正式版继续调整；Demo 虽固定两轮，也不能把人数、A-E 顺序、阶段任务、问题和 Maya 报告逻辑散落写死在页面/提示词，必须依赖版本化 `DebateRuleSet` 和策略模块；
- 参考项目过多会导致目录、领域对象、基础设施和编码风格互相冲突；每个模块必须先有本项目契约，最多带着一个明确问题查看一个主要参考，未证明收益的参考不进入产品仓库；
- 把完整 `Project.md`、全仓代码和重复背景交给每次 Sol High 审计会显著浪费 Token，并让审计结论被无关细节稀释；必须使用风险分层、紧凑 Gate Packet、确定性检查前置和低风险批量签字；
- 为了“显得 Agent 很聪明”而隐藏补 Prompt、联网补 RAG 或故意压低无 RAG 输出，会破坏教学诚信；必须用真实命中、可核对来源和受控对照证明 RAG/Prompt 的作用；
- “此前全部发言”长期会超出模型上下文，需要预留摘要机制，但 Demo 阶段应先保持完整原文以验证需求；
- 实时文本、TTS 和数字人播放之间需要事件状态机，不能只做一个同步 HTTP 请求；
- 音色克隆必须有明确的本人授权、删除机制和防冒用设计；
- 允许直接删除已发布 Agent 引用的音色后，兜底音色成为课堂可用性的必要依赖，必须在启动和创建辩论时校验；
- 每课程只保留最近一场合成语音可限制磁盘增长，但若教师长期不启动下一场，该音频会一直存在；页面需明确当前磁盘占用和“启动下一场将清理上一场语音”的影响；
- 教师大屏是唯一的辩论观看/收听端，需要处理浏览器自动播放限制、页面刷新和断线后状态恢复；扫码手机页只是辩论后互动表单，不参与语音播放或状态追赶；
- **真实 TTS 风险已连续触发**：系统音色注册一次成功，历史两次试听失败；新的 attempt=3 在完成 URL/DNS/下载/完整 WAV/并发唯一 claim 加固后仍以 `tts_audio_invalid` 失败。平台保持 `preview_ready`、无 active preview/preview file、未激活兜底 ID；当前 Gate 的单次额度已用完，禁止重试。离线 Sol High 与官方文档复核又确认两个 P1：现有 safe code 把容器/采样参数/RIFF结构/时长/静音/削波/预览落盘全部折叠，无法定位真实失败断言；adapter 使用 workspace endpoint 且丢弃 `language`，而官方 Qwen-TTS 当前参考使用 shared endpoint 并建议 `language_type=English`。这两项不能直接解释 attempt=3，因为该次已取得可下载 bytes，但下一次真实调用前必须重新冻结 endpoint、`en→English` 映射、内部非敏感 reason 枚举和“解析原始 WAV→必要时本地规范化→质量验收”策略；只保存 byte length、container magic、声道/采样宽度/采样率、帧数/时长和质量指标，不保存音频、文本、URL、external ID、Key 或私有路径，并另行获得合同与费用授权；
- Docker Desktop 的 bind mount 与 SQLite WAL 存在命名空间风险：后端运行时从 macOS 宿主直接打开同一数据库，可能让容器持有已 unlink 的 WAL inode并造成写入不可见/503。当前规定在线检查只走平台 API 或容器内连接；只有后端停止后才能从宿主运行 sqlite3；
- 长生命周期 WebSocket 若持有 SQLAlchemy Session 会耗尽默认连接池，带独立幂等 claim 的写请求最先表现为通用 503。Wave 2 已改为握手/snapshot/每命令/disconnect 短 Session并有 2 连接池/5 socket 回归；后续 Wave 3 实时互动必须复用这一边界，不能重新把 Session 绑定到 socket 生命周期；
- Demo 允许刷新匿名表单后重复提交，因此投票和弹幕不具备反作弊保证；大屏和 Maya 报告不得把票数当作严格的一人一票结果；
- 匿名投票和弹幕是独立写入；虽然 Demo 不做压测，SQLite 仍需使用短事务、WAL/忙等待和 WebSocket 事件在事务提交后发送，否则少量同时扫码也可能出现“database is locked”或大屏统计领先数据库的不一致；
- 按需中文翻译是外部派生测试内容，可能有术语偏差和免费额度变化；界面必须始终保留英文原文，翻译失败不能破坏辩论主流程；
- 本地 Document Agent 含内部配置和特定业务代码，复制前必须清理并确认授权边界；
- 参考仓库源码禁止复制；依法使用的第三方依赖仍需核对许可证并锁定版本。3D 素材许可在私下本机 Demo 暂不设门禁，但公开分享、交付、正式课堂或公网部署前必须恢复核验；
- 除 AGENT.md、RAG 合计和音色输入外，辩题、昵称、弹幕和单个 Markdown 没有产品级上限，这是用户接受的私下 Demo 简化；即使没有恶意请求，过长文本也可能造成移动端布局、日志、SQLite 行大小和 Maya 洞察成本异常，正式课堂前必须恢复合理限制；
- 弹幕聚类/筛选和 Maya 报告仍是生成式模型输出：即使数量由代码计算、输入只含实际证据，模型仍可能错误归类少数意见、过度概括或产生不被证据支持的综合判断；必须用 message ID 追溯、少数意见测试、报告来源展示和人工演示复核控制，不能把“只读真实输入”误认为“必然事实正确”；
- 当前 1 个本地 GLB 已在 Three.js r185 画布、三套参数预设、五种状态和课堂 A/B 多槽复用下通过 desktop+360 浏览器验收；仍没有 2-3 个独立建模资产，也没有真实教室后排/投影主观可读性证据。只能声称“多槽复用兼容资产”，不得把三预设说成三个人物模型；
- SQLite + 文件系统存在跨介质原子性风险；发布快照、启动下一场清理音频等操作必须使用 staging/trash + DB 状态恢复，不能先永久删除文件再尝试写数据库；
- 单进程轻量 TaskManager 适合本机 Demo，但不提供多 worker/进程重启后续跑；Docker/启动命令必须固定 FastAPI 单 worker，并把遗留 running job 显式标为 interrupted/failed；

### 9.1 已关闭/受控的治理风险

- **Wave 2 未经完整 Gate 就声称可演示：CLOSED（2026-08-28）**。M10/M11/M12 分别完成 Luna 实现、自测、G1.5、独立 Sol G2 和主窗口隔离 Docker/真浏览器 G3；设计 PASS、单测 PASS 与运行 PASS 始终分开记录；
- **播放动作/重播/启动异步串场：CLOSED（2026-08-28）**。真实浏览器复现 resume→skip 后旧 pause 污染下一 Turn、整场 replay 停在第一项、Start HTTP/WS 乱序、终态重新 acquire 和 replay/acquire CAS；现以 turn/media/socket/control generation、后端 action/public-prefix fence、controller-ready 门和反例测试关闭；
- **WebSocket 连接池耗尽：CLOSED（2026-08-28）**。不再持有 socket 生命周期 Session；握手、snapshot、命令和 disconnect 均短事务，约束池回归证明 5 个 socket 不阻塞双连接幂等创建；
- **宿主/容器 SQLite WAL 分叉：CONTROLLED（2026-08-28）**。隔离数据已恢复且无丢失；运行容器时禁止宿主直接 sqlite3，检查脚本和人工排障必须遵守“API/容器内在线、后端停机后才宿主离线”的边界；
- **Wave 1A 未经合同就编码：CLOSED（2026-08-27）**。主窗口先提交 `bed2211` Gate Packet，G0-S 两轮修正后 PASS，才派发后端/前端 Luna；M05/M06/M09、契约质量均经独立 Sol G2 与主窗口 G3；
- **运行数据权限过宽：CLOSED（2026-08-27）**。`data/` 和私有目录为 0700，数据库/WAL/SHM/Markdown/快照为 0600，启动重复加固；隔离 Docker 竖切和重启后实测通过；
- **Wave 1A 教师草稿泄漏/伪 journal/伪幂等：CLOSED（2026-08-27）**。Sol 对抗审计实际复现后，已改为 SQL published-only、独立提交 journal、staging/fsync/promote、claim-token lease 与崩溃恢复，并加入运行测试；
- **Project 全局冲突：CLOSED（2026-08-26 预检复核）**。除既有第 0 节权威顺序外，本轮已清理活动展示脚本残留的数字 1/2、C02/C03“待冻结”标题、M16/M17“尚未冻结/编码前出合同”措辞，并复核 A-E、冻结状态、共享工作簿和编码授权边界一致；第 11 节历史记录中的旧视觉讨论仍保留且不具权威性；
- **未冻结就并行编码：CLOSED / GATE OPEN**。产品 P0、C01-C12、视觉和预检均已冻结，用户已明确授权 Wave 0；并行实现仍受文件所有权和模块 Gate 控制；
- **后续再次产生冲突：CONTROLLED**。每次需求变化必须同步第 0/5/8 节并执行关键词扫描、对象/API/状态/验收对照；编码期 CI 将加入 OpenAPI 快照、生成前端类型和契约测试，避免文档与实现静默漂移。

## 10. 推荐下一步

**当前有效顺序（2026-08-30 18:19）**：

1. `.3` G2/G3 已通过；先原位同步唯一共享 Excel，记录 `433/193`、两轮 Replay、localhost/LAN、真实网络单次手动 Reconnect、报告/翻译和 `READY_FOR_WAVE_4`。
2. 停止三容器后永久删除 `data/` 与 `backend/data/`，复核只保留 mode-0600 `.env` 与 `backend/config/demo-accounts/accounts.private.md` 作为私有运行资料；不得把运行数据或私密资料提交。
3. 建立包含开发测试和 Gate 证据的本地完整检查点；再从该检查点生成独立干净发布树，覆盖 GitHub 私库 `bowenx1125/maya-platform`，排除 tests/test 配置、env、账号密码、data、运行记录和历史 Gate 证据。
4. 发布后重新核验远端树只包含运行/维护所需前后端、README、AGENTS、Project.md、合同、Compose/infra、初始化/生成脚本与锁文件；本地开发仓库 origin 不改。
5. Wave 4 仍需独立 G0；建议正式 TikTok Markdown → 单独真实 Embedding → 单独真实结构化 LLM，不同时切换。真实 TTS 继续 `FAILED-DEFERRED`，其他真实服务/负载/部署分别立 Gate。

**已完成的收口（2026-08-30）**：OpenAPI/WS/生成 Client/route/0007 已融合；后端 386、前端 164、生产构建、Docker/浏览器候选和空库登录 smoke 已通过；运行数据与冗余资料已清理。以下 2026-08-29 的 Docker/页面/检查点步骤保留为历史执行清单，不再作为待办。

1. **Docker 收口**：从当前工作树执行一次 `docker compose up -d --build`，确认三容器 healthy，并在 backend 容器内确认 `/health/ready`、Alembic `0007_wave3_interaction_report (head)`、外键为 0，且所有 Provider selector 仍为 Mock；记录构建/启动结果，不使用 `down -v`。
2. **真实页面候选冒烟**：使用同一规范 origin，依次检查统一登录、教师历史页、Wave 3 互动/报告/翻译三块页面和匿名课堂入口；至少验证匿名表单在 open 状态可见、投票与弹幕控件独立、关闭后入口进入不可用态。若页面只渲染空壳或未能取得真实 access token，标记为 NOT READY，不补造成功数据。
3. **证据收口**：记录页面 URL/状态/关键截图或可复述现象、Docker 镜像与迁移状态、控制台错误；将“人工候选 PASS/FAIL”与“自动化机械 PASS”分开。发现 token 泄露、跨权限数据、昵称进入报告、关闭后仍可提交、重启后 Job 串状态等立即停止该 Gate。
4. **检查点与文档**：人工结果明确后再整理未提交 Wave 3 文件，做 `git diff --check`、状态快照和本地提交；同步本文件与唯一共享 Excel 的模块状态、已知未复审范围和人工入口。不得把当前未提交候选与后续 Wave 混入同一无说明提交。
5. **后置工作**：真实 TTS 仍为 `FAILED-DEFERRED`；真实 LLM/Embedding、正式 TikTok RAG 内容、DeepL、投影/局域网和公网部署继续独立立项，任何调用都需要新的合同、费用和权限授权。

以下编号路线是本窗口之前的历史建议，保留用于追踪，不覆盖上面的当前顺序：

1. **Landing/auth 收口（现做、低风险）**：对 7 个当前最新版前端文件补一次低风险 Sol 批审；保持现有 `21 files / 138 tests`、lint/type/build、六视口和安全站内 next 证据；审计通过后建立独立本地检查点。不得与后续 RAG 或 Wave 3 文件合并提交；
2. **Pre-Wave 3 Mock RAG honesty Gate（待授权、先于 Wave 3 G1）**：合同只允许 `M06/M11` 的 Mock 检索策略、typed subquery topic anchor、规则快照/receipt 元数据和反例测试；不接百炼、不改真实 Provider、不重建或改写旧 KnowledgeSnapshot、不重跑旧辩论。必须证明 TikTok→TikTok matched、亲密关系→关系资料 matched、爬山→TikTok/关系 no_match、TikTok→矿物 no_match，且 round 2 的通用前驱文本不能绕过 topic anchor；
3. **Wave 3 G0/G0-S（待授权）**：主窗口冻结 `g0-2026-08-29.3-wave3` Gate Packet、0007 迁移、OpenAPI 13 个占位、WS 事件、权限矩阵和状态机；Sol High 分别审计 M13 的匿名入口/并发，M14 的去昵称/洞察/报告输入完整性，M15 的历史/音频留存/翻译派生内容；任一 P0/P1 未关闭不得进入 G1；
4. **Wave 3 G1 并行实现（只在用户明确授权后）**：Luna Max 以互斥所有权并行完成 M13、M14、M15。M13 独立新建 interaction 模块和手机/大屏 UI；M14 独立新建 insight/report policy、repository、worker 与报告页面；M15 只扩展历史/translation batch，不改播放核心。共享 models/migration/OpenAPI/WS 由主窗口统一融合；任何模块不得把代码继续堆入大型 playback service 或 DebateStage；
5. **Wave 3 G1.5/G2/G3**：先跑迁移 fresh/repeat/populated/downgrade、权限/幂等/竞态、OpenAPI/生成 Client、closed WS、后端/前端全量和 Docker；再由不同 Sol High 审计各模块，主窗口最终用真实浏览器完成教师结束辩论→打开二维码→匿名投票/弹幕→大屏汇总→关闭收集→匿名洞察→Maya 报告→历史/下载/按需翻译的完整 Mock 竖切；
6. **真实 Provider 继续独立**：Wave 3 默认全部 Mock。正式 TikTok Markdown、真实 Embedding、真实 LLM、DeepL 和 TTS 分别建立独立高风险 Gate；不同时切换 LLM 与 Embedding。当前仍只报告 `RAG_PIPELINE_PASS / FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING`，真实 TTS 仍 `FAILED-DEFERRED`；
7. **Wave 3 停止条件**：互动开放前 Debate 未完整结束、投票与弹幕被错误绑定、匿名数据泄露昵称给 Maya、关闭后仍可提交、报告读取未实际引用证据/原始带昵称弹幕、迁移破坏 0001-0006、长 WebSocket 持有数据库 Session、来源不明并发修改、Provider/费用调用或需要改变已冻结产品体验时，停止受影响 Gate并先回合同。

## 11. 工作记录

### 2026-08-30

- 本地开发仓库已建立完整检查点 `a235c29 feat: complete wave 3 pre-wave4 ux state gate`，包含开发测试、合同和 Gate 证据；提交后工作树干净。随后停止并移除三容器，永久删除产品根 `data/` 与 `backend/data/`，复核二者均不存在；只保留 mode-0600 的 `.env` 与 `backend/config/demo-accounts/accounts.private.md`，不读取或上传内容。
- 已从 `a235c29` 生成独立单根干净发布树并覆盖私库 `bowenx1125/maya-platform` 的 main，远端最终 SHA 为 `2fd8078`；发布树共 236 个文件，只保留产品前后端、稳定合同、Compose/infra、bootstrap/fallback 脚本、锁文件、README、AGENTS 和 Project.md。tests/manual-tests、测试配置/依赖、`.github`、历史 Gate、`.env*`、私有账号、data/、运行记录均为 0；该树通过 runtime-only 前后端本地构建和 Docker backend/frontend build，远端 API 复核必需路径完整且仓库仍为 private。本地开发 origin 未修改。
- `.3` pre-Wave-4 UX/state delta 已由三个 Luna Max 互斥实现并由主窗口审计收口：所有普通交互控件只显示当前 locale，返回文案为 debate list，普通 Pause/Continue 已删除；课堂 phase 为 ready/in-progress/waiting/finished，Finish 只在 live waiting 可用；提前 Finish 保留已公开 turn 但封锁 interaction/report/translation/Replay，完整场保留四段 transcript/source。主窗口在 G3 中继续发现并修复终态 acquire 噪音、Replay 首帧误显示 Finished、Replay Waiting 仍显示 Finish、完整页刷新后 Replay 禁用等 P1，最终 `G2 PASS / P0=0 / P1=0`。
- `.3` 最终证据为后端 `433/433`、前端 `28 files / 193 tests`、mypy 109、Ruff/ESLint/TypeScript/Prettier/Next build、OpenAPI/WS/route/0001–0007/secret boundary 全绿。真实浏览器验证双 locale、waiting 离开/返回、工作中 Finish 禁用、early/full Finish、真实后端重启后无后台重试且一次 Reconnect 恢复、localhost 与 LAN REST/WS、两轮 retained Replay、1 票+1 原始弹幕、611 词 Mock 报告和 `5/5` Mock 翻译；真实 Provider 调用为 0。正式签署 `WAVE_3_G3_PASS / READY_FOR_WAVE_4 / WAVE_4 NOT STARTED`。
- 用户在最终人工检查中直接授权 `.3` pre-Wave-4 UX/state delta，并明确无需二次确认：消除所有中英文拼接控件、把返回文案改为 debate list、移除普通 Pause/Continue、以 in-progress/waiting/finished 简化课堂状态、修复 Replay 清 transcript/Next 无发言和每轮终态需手动续控制权、解决 localhost/LAN 反复 4403。主窗口暂停最终检查点/Excel/GitHub 发布，冻结合同后改派多个 Luna Max 实现，自己负责审计、全量和浏览器 G3；`.3` 完成前状态为 `NOT_READY_FOR_WAVE_4`。
- 最终 disconnect/RAG delta 完成独立 G2 与主窗口 G3：未参与实现的审计者结论 `PASS / P0=0 / P1=0 / P2=1 accepted`；主窗口真实浏览器覆盖 network→手动单次 Reconnect、Pause/Continue、superseded、4401/HTTP 401、4403、full/partial Finish、匿名互动、609 词报告、单批翻译切换和四段 Replay。正式签署 `WAVE_3_G3_PASS / READY_TO_DISCUSS_WAVE_4`，但 Wave 4 未启动。
- G3 真实发现并关闭两项教学诚实性/断线解释 P1：亲密关系引用 URL `/5-rules-for-getting-consent/` 的 slug 曾提供伪 `rules` topic token，现 Mock v2 分词前删除 HTTP(S) destination；手动 Reconnect 的 snapshot HTTP 401 曾抢先于 WS 4401 并保留 generic network，现统一为 session-expired、无 Reconnect/通用 alert/Finish 权限。两条精确反例均在重建 Docker 后浏览器复验通过。
- 最终机械证据为后端 `401/401`、前端 `28 files / 182 tests`；另修复 `wave1-g2.test.tsx` 只等身份按钮导致的既有认证状态竞态，并以单文件重复 5 次与全量回归确认稳定。OpenAPI/生成 Client/WS/route、0001–0007、repo boundary/secret、bootstrap、lint/type/build/format checks 均通过；没有真实 Provider 或收费调用。
- G3 证据固定后停止并移除三容器，永久删除产品根 `data/` 与 `backend/data/`，包括本次新场次和所有旧发布/辩论/互动/报告/翻译/音频记录，不保留恢复副本；最终只保留 0600 的 `.env` 与 `backend/config/demo-accounts/accounts.private.md` 私有运行资料。
- 用户确认 `g0-2026-08-30.2-wave3-disconnect-rag-final-delta` 并把当前目标冻结为“推进到 Wave 4 开始前”：修复终态/superseded/4401/4403/network/sequence-gap 的准确 UI 原因且保持仅手动单次 Reconnect；以版本化 Mock lexical topic anchor 收口无关 RAG 误命中；独立 G2 清零 P0/P1 后由主窗口完成 G3。用户同时要求优化为多 subagent 并发，执行采用前端、后端 WS、Mock RAG 三条互斥实现线，主窗口只做合同、共享融合、全量、G3 与发布；实现者不得自签 G2。
- 按用户授权完成 GitHub 私库 `bowenx1125/maya-platform` 的干净覆盖发布：先核对目标为 PRIVATE、默认分支 `main`、且只有一个远端分支引用；从本地 `d541b65` 另建发布目录和独立 Git 根提交，再强制替换远端 `main`。本地完整开发仓库、测试和原 `origin=https://github.com/bowenx1125/maya-teaching-platform.git` 均未改变。
- 干净远端保留 258 个运行/维护源文件（约 12 MB）：前端、后端、0001-0007 迁移、API/WS 合同、Compose/infra、初始化/生成脚本、锁文件、README、AGENTS 和 Project。删除全部 backend/frontend tests、`test_*`、Vitest/pytest 配置与测试依赖、旧 GitHub CI、Gate 历史目录、`.env*`、私有账号 Markdown、`data/`、数据库/日志/缓存和历史运行记录；远端测试文件、环境文件、明文凭据和运行数据扫描均为 0。
- Demo 账号只保留安全生成能力：`bootstrap_local_demo.py` 固定生成 1 名教师、Bowen/KaiKai 两组三人共 7 个身份，并由操作者首次运行时输入或生成共享密码；脚本只在本机创建 Git 忽略、权限 0600 的 `.env` 和 `accounts.private.md`，GitHub 不含任何可用密码。干净发布包通过 `git diff --check`、repo boundary/秘密扫描、pnpm/uv 锁文件重解、前端 ESLint/TypeScript、后端 Ruff/mypy、Compose 解析，以及前后端 Docker 镜像实际重建。
- 最终本地复核发现原产品 Compose 三容器于 14:31 从 `/Users/xubosmell/Desktop/Maya/maya-platform/docker-compose.yml` 被重新创建并生成 3.1 MB 的 SQLite/RAG/音频目录；这些运行资料从未进入发布提交。按用户已经确认的最终清理授权，已停止该三容器并再次彻底删除产品 `data/`；`data/` 与 `backend/data/` 最终均不存在，产品 Git 工作树干净。
- 覆盖发布不改变 Gate 结论：仍为 `READY_FOR_WAVE_3_DELTA_G2 / NOT_READY_FOR_WAVE_4`。源代码可供用户开始人工核验，但最终 Continue 修复仍要由未参与实现的审计者清零 P0/P1，用户再签署 G3；发布动作本身不是审计或验收。
- 按用户确认的顺序完成 Maya 产品仓库、`Project.md`、共享合同、迁移、前后端、测试、运行数据和冗余资料审计。产品 Git 根为 `maya-platform/`；工作开始时有 274 个 tracked 文件、36 个 modified 和 94 个 untracked 条目，其中约 38 项为产品目录内重复的 Project/需求/合同/手工材料/工作簿/历史输出/私有输入，不把父目录当 Git 根。
- 先更新权威合同与 `docs/gates/wave3/GATE_PACKET.md`，再实现人工反馈增量：具体 `PlatformApi` 增加 pause/resume/finish；冻结 OpenAPI、生成 TypeScript、route fixture/CI 同步；播放控制固定 Start/Next/Pause-Continue/Replay，Finish 位于页头；断线不后台重连，只有显式 Reconnect；full Finish 进入 `debate_finished`，partial Finish 诚实进入 `stopped` 并封锁 interaction/report/history/translation/replay；互动/报告/历史/翻译进入独立教师页；翻译只在权威英文与中文测试表示间单视图切换；Replay 使用不可变 turn catalog 恢复 speech/source。
- 主窗口真实浏览器发现 Continue 的运行态缺陷：REST resume 与 started ack 各产生一条不可区分的 `playback.resumed`，客户端收到真正恢复事件时又调用 `pauseAudio(false)` 并回到 ready，导致服务端 playing/浏览器 ready 分叉。修复为：resume REST 只返回 ready，不提前发 resumed；媒体真正开始后只发一条 resumed；客户端映射为 playing 且不暂停/不再次 prepare。新增后端“resumed 仅一次”与前端 ready→resumed→playing 反例。
- 最终自动门禁通过：后端 `386/386`，前端 `27 files / 164 tests`；Ruff format/check、mypy、ESLint、TypeScript、Prettier、Next production build、OpenAPI 69-operation response、Redocly、generated Client、WS events 30/18、commands 6/7、private results 5/6、route comparator 13 个负例、严格 FastAPI schema、0001-0007 三代迁移保留证据、仓库边界与秘密扫描全部 PASS。
- Docker 从当前代码冷重建并健康；真实教师浏览器通过：后端重建断线后页面稳定且只显示一次 Reconnect，点击后恢复权威 paused；Pause 保留 3 条公开发言并跨重启，Continue 回到 playing；不完整 Finish 不显示互动入口，完整目录在 playing 时 Finish 后显示 4 条公开发言与独立互动报告入口；中文测试批 4/4 完成，切换统计为中文标记 `4 → 0` 且只有一个按钮；Replay 为 `mode=replay/status=playing` 并恢复来源；既有完成场的 1 票/1 弹幕、ready insight 与 603 词报告 v1 正常显示。
- 按用户明确授权永久删除产品 `data/` 与 `backend/data/`，包含当时全部 14 场历史、Bowen/KaiKai/Crystal 发布数据、42 个 turns、互动/报告/翻译、Mock 音频和旧备份；同时删除产品目录内重复 Project/需求/合同/手工材料/工作簿/outputs/private-inputs、旧 `demo_users.yaml`、父目录旧 archive/视觉中间工作簿/个人语音输入和失效隔离 Compose 容器。没有保留数据库或个人语音恢复副本。
- 清理后从不存在的 `data/` 再次启动：Alembic 自动到 `0007_wave3_interaction_report`，foreign_key_check=0，精确 `7 users / 1 course / 2 groups / 0 agents / 0 debates / 0 turns / 0 interactions / 0 reports / 0 translations`；教师 Demo 密码登录成功且首页显示 0 published Agents。随后再次停止三容器并删除 smoke 生成的 `data/`。最终私有运行资料只剩 0600 的 `.env` 与 `backend/config/demo-accounts/accounts.private.md`。
- 唯一共享工作簿已原位同步 M12-M18、386/164、OpenAPI/WS/0007、真实浏览器候选、空库 smoke、数据清理和 `READY_FOR_WAVE_3_DELTA_G2 / NOT_READY_FOR_WAVE_4`。两张表完成关键值/公式错误扫描与编辑后视觉渲染，公式错误 0，长文本/状态未截断；根入口仍指向同一 xlsx，输出目录没有第二份工作簿或 inspect 临时文件。
- 已创建本地产品检查点 `d541b65 feat: complete wave 3 manual feedback candidate`，102 个文件覆盖 Wave 3 模块、0007、OpenAPI/WS/生成 Client、Pause/Continue/Finish/Reconnect/Replay、独立页面、CI、测试与 Gate。提交前 repo boundary/秘密扫描通过；提交不含 `.env`、`accounts.private.md`、`data/`、`backend/data/`、个人语音或父目录文档，未 push/PR/部署。
- 检查点建立后永久删除恢复包 `recovery-20260829-204844` 与约 1.1 GB 可再生 `node_modules/.next/.venv/mypy/pytest/ruff/__pycache__`；产品目录由约 1.1 GB 收敛到约 21 MB。源码、根 `docs/`、`manual-tests/`、Project、唯一共享 xlsx 和两个 0600 私有运行文件保留；产品 Git 工作树干净，`main` 相对 `origin/main` 超前 2 个本地提交，未推送。
- 当前状态为 `READY_FOR_WAVE_3_DELTA_G2 / NOT_READY_FOR_WAVE_4`：主窗口候选与全量证据已通过，但最终 Continue 修复不能由实现者自签独立 G2；等待未参与实现的审计者清零 P0/P1，再由用户做最终 G3 人工签收。真实 Provider 调用为 0，M08 仍 `FAILED-DEFERRED`，Mock RAG honesty/正式内容质量未在本轮扩展。

### 2026-08-29

- 因用户确认当前额度不足，本窗口于 15:54 立即停止全部 Agent；未继续实现、测试、Docker 重建、提交或推送。Luna Max 因 403 未执行；Terra xhigh 审计已完成；Terra 兜底在停止前已部分修改 playback backend/schema/router/sql recovery、Reconnect、Replay catalog、Pause/Continue、Finish 初步接线和控制页，并新增/调整了部分测试与独立互动页面文件。该工作树状态不可视为已完成或已验收。
- 尚未完成：独立互动/报告页面最终接线、测试翻译按钮只切公开发言显示、OpenAPI/WS/生成 Client/allowlist 融合、partial stopped 对所有下游的最终 fail-closed 验证、paused+inflight 重启验证、Replay 文字真实浏览器验收、完整前后端回归、Docker 重建、Sol 最终核验、唯一共享 Excel 同步和本地检查点。
- 当前恢复注意：只能从窄范围 diff 分类开始；不得回滚或清理现有改动，不得把旧“三按钮/不可恢复 stop”测试直接视为当前合同，不得把 Terra 兜底称为 Luna 实现；先完成共享合同和状态机核验，再做页面和 Docker 验收。除非新的授权明确允许，不调用真实 Provider、不提交、不推送。
- 用户确认下一轮 UI/播放方案：(1) 断线停止自动刷新，改为手动 Reconnect；(2) 顶部保留“返回辩论列表｜结束辩论｜课堂互动与报告”；(3) Stop 放在 Next 旁，Finish 放顶部；(4) 课堂互动/报告进入独立页面；(5) 测试翻译收敛为按钮，只改变公开发言显示；(6) Replay 必须恢复公开发言文字。用户进一步确认：完整 turn 按正常 Finish，可进入互动/总结/历史/Replay；不完整 Finish 只保留当下已有发言，不进入 Maya、不开放匿名互动、不提供历史和 Replay；Stop 代表可恢复暂停，之后仍可继续下一个 AI 发言和后续互动/总结。该决定待编码前收口两个合同细节：Stop 不得复用现有不可逆 `stopped`，需恢复可持久 pause/resume 语义；不完整 Finish 不删除已生成的不可变 turn，而应以 partial completion 标记限制 UI/interaction/report/history/replay。
- 当前拟定的安全实现解释（待用户最终确认）：Stop/暂停持久保存 playback paused，不取消辩论生成、不关闭未来流程，按钮切换为 Continue/继续；Finish 完整场次写入 full completion，Finish 半场写入 partial completion，保留已有 turn 但禁止 interaction/Maya/history/replay，列表和详情显示 finished/partial。若用户要求半场物理删除旧 turn 或允许半场进入报告，必须另开合同，不在本轮默认实现。
- 用户人工核验反馈（方案待确认，尚未编码）：(1) 课堂 WebSocket 断开时停止自动重连/重复刷新，改为教师按一次“重新连接”且失败后保持当前页面；(2) 辩论页返回列表旁新增一键“结束辩论”并显示 finished，但该语义需先确认是否只允许完整 final-ready 场次终止，因为强制结束未完成辩论会冲突现有 `debate_finished`/interaction 开放前置条件；(3) 将课堂互动与文明互鉴报告移到独立教师页面入口；(4) 将测试翻译收敛为一个按钮，翻译成功后只把公开发言显示为中文，英文仍为权威源；(5) 修复 Replay 清空公开列表后 `replay.started` 无法找到 speech 的根因。执行前按用户指定使用 Terra xhigh 审计、Luna Max 实现、主窗口 Sol 最终核验与融合。
- 本窗口完成用户授权的 Wave 3 高风险窄审收口：独立 Sol 对匿名 token、并发幂等、昵称去除/Maya 输入边界、translation 重启恢复进行审计；发现并修复 M15 复用 entry 恢复误伤和 M14 recovery 缺少 writer lock/CAS 两项 P1，并加入 insight frozen input hash 校验（P2）。修复后窄 G2 `PASS / P0=0 / P1=0`；新增共享 entry 重启恢复与 hash mismatch 测试，Wave 3 相关测试 28 项、后端全量回归、Ruff、mypy 均通过。
- 已从修复后当前工作树重新执行 `docker compose up -d --build`，前后端镜像重建、三容器 healthy，Alembic `0007_wave3_interaction_report (head)`、SQLite foreign_keys=1/WAL、所有 Provider selector=Mock；重载真实浏览器后教师历史、互动/报告/翻译区块和匿名课堂入口可见且控制台无 warning/error。使用既有完成辩论完成“结束互动→Mock insight ready→Mock report ready”，匿名入口随后进入不可用态。当前项目推进到 `Wave 4 前人工核验阶段`，Full Wave 3 G3 仍未签署。
- 为节省后续 Token，已将窄范围读取约束写入 2.1：只读取 Wave 3 相关模块/测试、Docker/Compose、Project 和唯一共享 Excel；不重复扫描参考、私有、历史归档或无关模块，除非证据明确指向。
- 本窗口按用户最新授权完成状态收口：首轮机械验收（后端全量、前端 159 项、生产构建、OpenAPI、WebSocket Schema、仓库边界、0007 往返迁移）已由用户确认通过；当前只进入 Docker 升级与真实页面人工候选检查，不等待独立 Sol 复审，也不把该跳过解释为 Wave 3 G2/G3。只读核对确认三容器 healthy、Alembic `0007_wave3_interaction_report (head)`、`CLASSROOM_PUBLIC_BASE_URL` 已配置且所有 Provider selector 为 Mock；工作树仍有未提交 Wave 3 变更。已将当前边界、风险和下一步同步到本文件；人工结束后再同步唯一共享 Excel和本地检查点。
- 已排查 Codex 切换 Aizex 后旧的“师生共创”任务仍显示 usage 到额：本机默认配置已加载 Aizex，但历史 rollout/线程仍按创建时 Provider 固定（旧任务不会因全局 `model_provider` 改动而迁移）；新建任务并在首次发送前确认 Provider 标识为 Aizex 才能使用新链路。该问题与 Maya 后端运行时 Provider 独立，当前 Maya `.env` 的 LLM/Embedding/TTS/Voice 仍为 Mock，代码也未实现 Aizex 适配器；本轮未调用真实 Provider、未改任何密钥。
- 已复核 Codex 单次请求用量示例：输入 86,441、缓存命中 83,712（96.8%）、输出 560；Project.md 当前约 1,857 行/15,807 词。高输入主要来自持续对话历史、工具输出、系统/技能上下文与项目文档叠加；缓存命中率已较高，但不代表第三方按量余额完全不扣 token。建议按阶段新建短任务，并以 Project.md 做交接，不在同一线程长期累积。
- 用户明确简化 Claude Code 交接：不需要 `CLAUDE.md`、当前 Gate/Git 状态清单或精确模块 Prompt；只需在启动提示中要求 Claude 完整阅读 Project，再只读阅读当前代码库，然后按 Project 继续推进。主窗口已删除“必须先创建CLAUDE.md才能交接”的过时结论；Project与代码库被确认为足够的项目理解上下文；
- 已回答 Mock RAG 的实施级修改方案与 Claude Code 交接边界：修复应在不改变既有256维落盘向量的前提下新增共享、可注入的 `MockLexicalAnchorPolicy`，让草稿聊天和正式辩论在向量阈值前执行同一 topic-anchor fail-closed 门禁，MockLLM本身无需修改；真实 RAG 后续使用语义Embedding/可选hybrid+reranker和真实结构化LLM，新模型只能进入新发布Snapshot；
- 当前产品工作树除 landing/auth 7文件外又出现 `frontend/lib/navigation.ts` 与未跟踪 `docs/gates/wave3/GATE_PACKET.md`；该事实保留为当时工作记录，但不再要求通过额外交接文件解决。Claude按用户提示先读Project并只读代码库后，应自行从当前文件理解实现状态并保留已有改动；本轮未创建CLAUDE.md、未改产品代码或调用Provider；
- 主窗口复核 Mock RAG 完整依赖链并查阅 OpenMAIC、Dify、Haystack、LlamaIndex 的官方实现/文档：当前问题由 Mock feature hashing 候选误命中和 MockLLM固定使用首个 receipt 共同造成；真实 LLM 单独替换不能修复，因为当前 validator 要求存在 receipt 时至少使用一个 evidence ID。成熟方案通常把 sparse/dense/hybrid retrieval、metadata scope、score cutoff和reranker分层，并允许最终零命中，而不是让生成模型替检索器兜底；
- 已冻结并行修改建议：先提交 landing/auth 基线，再从同一提交建立独立 worktree；Mock RAG honesty 窗口只做 provider-neutral RetrievalPolicy/词法anchor和专用后端反例，不碰Wave3/前端/迁移/OpenAPI/真实Provider。项目业务模块划分清楚，RAG内部仍需消除草稿聊天/辩论阈值重复和generation adapter硬编码Mock的局部耦合；本轮只更新Project与解释，没有改产品代码或启动任何Provider调用；
- 用户确认 landing/auth 的 7 个未提交前端文件就是当前最新版；主窗口重新完整阅读 Project 并复验该工作树，ESLint、TypeScript、前端 `21 files / 138 tests`、Next production build 和 `git diff --check` 全部通过。当前不再保留“来源不明/测试失败”的过时结论；增量仍待低风险 Sol 批审和独立本地检查点，未在本轮提交；
- 容器内数据库复核最新 `how to climb the mountain` 完成场：四个 turn 全部误判 matched，Bowen 命中 TikTok 文件、Crystal 命中恋爱关系文件，最高无关分数 0.545。代码审计确认根因是 `mock-sha256-v1` 的 256维 signed feature hashing + 通用查询文本/碰撞 + 0.20/0.08 低阈值，随后 Mock LLM 固定使用第一个 receipt；因此不能靠单纯提高阈值或要求 LLM 自己拒绝修复。已记录推荐的 `mock_lexical_anchor_v2` fail-closed 方案，等待用户授权后单独 Gate 实现；
- 已把 Wave 3 实施前路线整理为 landing/auth 低风险收口 → Mock RAG honesty Gate → Wave 3 G0/G0-S → M13/M14/M15 Luna并行 G1 → 独立 Sol G2 → 主窗口 Docker/浏览器 G3。当前只完成方案与 Project 同步，未创建0007、未修改OpenAPI/WS、未实现M13-M15、未调用真实Provider；
- 已按用户确认完成 `g0-2026-08-29.1-landing-auth-merge` 低风险 UI 增量：`/` 现在把平台介绍与登录模块合并在同一完整矩形卡片内，语言切换独立置于整卡右上方；左栏保留品牌标题、平台说明和环境健康，右栏常驻7个Demo身份、用户名、密码和“登录 Maya”。首页旧登录跳转按钮、`MAYA · WAVE 1A`、`Wave 1A boundaries` 与用户名/密码折叠提示已从可见产品移除；三张教学原则卡继续与主卡同宽对齐；
- `/login` 不再维护第二套页面，只兼容重定向到统一首页并保留 `next`；RouteGuard和退出也统一回到 `/`。`next` 只接受以单个 `/` 开头的站内路径，拒绝协议相对/外部地址；Demo身份目录仍由原后端安全DTO提供，认证API、Session/CSRF、账号文件、权限和数据库均未改变；
- G1.5 确定性检查通过：前端全量 `21 files / 138 tests`、ESLint、TypeScript、Next生产构建、所有本次修改文件Prettier和`git diff --check`均通过；全目录Prettier唯一提示仍是未修改的生成文件`frontend/lib/api/generated/schema.d.ts`，本轮没有格式化或手改生成合同；
- 已重建并重启frontend Docker镜像，backend/frontend/gateway三容器健康。真浏览器检查`1440×900 / 1280×720 / 1024×768 / 768×1024 / 390×844 / 360×800`：7个身份、常驻账号密码、双语切换和`/login?next=/teacher`兼容均通过；所有尺寸横向溢出为0、最小交互高度44px、控制台warning/error为0。该低风险增量由主窗口完成diff审阅和运行验收；因当前执行窗口不可调度子Agent，不伪造Sol签字，`covered_by_sol_audit_id`标记为`PENDING_LOW_RISK_BATCH`，下一次低风险批审后再补正式G3记录；
- 已把产品 Git 根 `/Users/xubosmell/Desktop/Maya/maya-platform` 上传到 GitHub 私有仓库 `bowenx1125/maya-teaching-platform`，远端默认分支为 `main`，本地 `HEAD` 与 `origin/main` 精确一致为 `df77595 docs: refresh local startup guide`；没有上传 Maya 上层目录、Project、共享 Excel、参考素材库、私有音频、真实 `.env`、账号密码文件或运行数据库；
- 上传前复核 273 个 tracked 文件和完整边界：当前产品仓库约 7.1 MiB，最大 tracked 文件为约 3.4 MiB 的私有 Demo GLB；仓库边界检查通过，`.env`、`backend/config/demo-accounts/accounts.private.md`、`data/` 和 `private-inputs` 均被忽略。GitHub 端再次查询这些敏感路径均为不存在，仓库可见性为 `PRIVATE`；
- 首次 HTTPS push 因代理/分块上传返回 400 并保持远端空仓库；没有伪报成功。最终只对该次 push 使用 `http.version=HTTP/1.1 + http.postBuffer=524288000`，未改全局 Git 配置，随后成功建立 `origin/main`；
- README 已从过时的 Wave 0/demo_users.yaml 说明更新为当前标准启动流程：日常启动只需 Docker Desktop + `docker compose up -d`；代码或依赖变化使用 `--build`；新机器先执行 frozen install 和 `pnpm bootstrap:local`，后者只创建被忽略且0600的 `.env` 与 `accounts.private.md`；正常停止使用 `docker compose stop` 保留本地数据；
- 当前 Mock RAG 对照仍可验收检索链而非真实模型文风：Mock Embedding 确实执行分块、256维向量、两档阈值、top_k与 matched/no_match，Mock LLM 根据结构化检索收据生成确定性发言。可以用相同问题比较优质相关 Markdown 与无命中/无关 Markdown的 `retrieval_status / grounding_mode / sources / 具体事实`；但不能据此声称真实 Embedding 语义泛化、百炼 LLM 辩论质量或正式 TikTok 内容已通过。
- 应用户明确确认，本窗口保留旧仓库 `bowenx1125/maya-teaching-platform`，另创建私有仓库 `bowenx1125/maya-platform`（项目描述为 `Maya Platform - private Demo handoff snapshot`）。新仓库从当前产品 Git 历史建立隔离上传副本，并纳入全部未提交代码、`Project.md`、原始需求、开发工作簿、合同/手工测试/历史输出、`.env`、Demo 账号文件、`data/` 与 `backend/data/`（SQLite/WAL/SHM、快照、Markdown、生成音频）以及 `private-inputs/` 个人音频；不纳入独立参考项目和操作系统/依赖/构建缓存。首次 push 的 HTTP 400 已按 HTTP/1.1 + 500MB post buffer 仅对该次命令重试成功；旧仓库 remote 未改写。此私有快照含真实凭据和个人音频，不能公开或转发给未授权人员。

### 2026-08-28

- `g0-2026-08-28.7-pre-wave3-polish` 已完成并签署 `G3 PASS`。PW3-A Auth、PW3-B Agent metadata/delete、PW3-C Knowledge COW、PW3-D 三键/逐步Replay、PW3-E Shell/教师信息架构/响应式均完成 Luna 实现、Sol High 独立终审（全部 `P0=0 / P1=0 / P2=0`）和主窗口融合；
- 共享合同已收束到 OpenAPI g0.7：53个已实现operation、13个后续Wave占位；生成Client、response contract、route semantic、WS 30/18、command 6/7、private result 5/6、0006迁移、Secret/边界扫描和Compose均通过。后端全量321项、前端21文件137项、Ruff/mypy/Prettier/ESLint/TypeScript/Next build均通过；
- Docker冷构建/启动完成，三容器健康；实际SQLite为`0006_pre_wave3_polish (head)`、外键违规0、7个Demo账号绑定生效。匿名登录页稳定显示7个安全身份并可quick-login，账号密码和私有路径未进入前端、日志、Git、Project或Excel；
- 主窗口使用真浏览器完成1440×900、1280×720、1024×768、768×1024、390×844和360×800六视口验收：登录、教师首页、学生首页、知识库和课堂大屏无横向溢出，交互目标均≥44px；学生空description保持空、详情有返回工作区、知识库有新增/COW编辑；教师详情有制作小组/只读3D/平台音色状态；课堂只显示开始/下一步/重播整场并实际渲染2个3D Canvas；
- 启动另一场辩论会按冻结合同要求先确认替换上一场保留语音；本次浏览器验收未替用户删除上一场音频。真实Provider调用0，真实TTS仍`FAILED-DEFERRED`，正式TikTok内容仍`FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING`，M13-M15和真实LLM/Embedding未进入；
- 唯一共享工作簿已原位同步PW3-A–E、0006/OpenAPI/WS、321/137、Docker/六视口、后置风险与下一步；重新导入关键表值准确、公式错误0项，两张表完成编辑后视觉渲染，仍只保留同一份V2 xlsx；
- 用户准确回复“确认执行 pre-Wave3 polish，按 g0-2026-08-28.7 开始。”；主窗口据此将 `.7` 标记为 `FROZEN / G1 AUTHORIZED`，允许按既定 Luna Max 实现、Sol High 独立审计、主窗口共享合同/迁移/融合与最终验收流程开始编码。授权不包含M13-M15、真实LLM/Embedding/TTS、Provider切换、推送或部署；
- 用户完成 `pre-Wave3-polish` 最后五项产品选择：Demo quick-login 对所有能访问站点的客户端开放；只允许物理删除从未发布且从未参辩的 Agent；description 修改立即反映到学生和教师当前视图但不改历史；普通课堂 Dock 固定开始/下一步/整场重播并保留隐藏 operator reset；网页编辑 Markdown 采用 copy-on-write，成功后自动原子替换组内全部引用旧文件的当前未发布草稿，已经发布版本/快照/辩论保持不变，冻结文件下载名附 Agent 名与版本号；
- 主窗口据此建立 `docs/gates/pre-wave3/GATE_PACKET.md`，合同编号 `g0-2026-08-28.7-pre-wave3-polish`，并同步第 0/5/8 节、P0、风险和下一步。首轮 Sol High 指出稳定账号键、删除竞态、description 历史展示、Markdown 多草稿原子切换和Replay API/0006降级五项P1；主窗口全部收紧后，独立复审结论为 `PASS / P0=0 / P1=0 / P2=0`。真实 LLM 登录开关、真实 adapter、结构化输出、费用和辩论级 Provider 冻结完全排除在本包之外；本轮只更新合同与唯一共享工作簿，不修改产品实现、不派发 Luna，仍等待用户最终执行确认；
- 唯一共享工作簿已原位同步 `.7` 的五个模块边界、G0-S PASS、执行待确认和真实LLM排除项；Artifact Tool 对两张表完成值检查、公式错误0项和编辑后视觉渲染，输出目录仍只保留一份V2 xlsx。产品Git仅新增未提交的`docs/gates/pre-wave3/GATE_PACKET.md`，没有产品代码、迁移、OpenAPI、WS、配置或Provider调用；
- 用户提出进入 Wave 3 前最后一组 10 项修改并要求先出完整方案、确认后再交给 Luna Max；主窗口检查附图和当前代码，两个 Explorer 分别完成前后端只读地图，独立 Sol High G0-S 预审结论为 `CHANGES_REQUIRED`。真实根因包括：登录页身份选择只在已有 Session 时加载，所以旧 Cookie 决定“有时出现”；学生单组卡固定落在两列 Grid 的半列；空 description 被前端 `noDescription/defineIdentity` 伪 fallback；当前真实 LLM adapter 根本不存在；现整场 Replay 会自动推进而不是逐回合 Next；
- 本次 pre-Wave 3 草案拆成五个 Gate：`PW3-A Auth/Private Accounts`、`PW3-B Agent/Description/Safe Delete`、`PW3-C Markdown Editor`、`PW3-D Three-button Stepwise Replay`、`PW3-E Teacher/Student Shell + Responsive`。建议只允许从未发布且未参辩 Agent 物理删除；账号私有 Markdown 仅本机、Git ignored/0600、删除行只禁用登录和撤销 Session而保留历史 User；Markdown编辑采用 copy-on-write，不改已发布快照；教师普通操作台只显示开始/Next/整场Replay，但后端保留非普通UI的故障恢复 primitive；Replay 以持久 `mode=replay + waiting_next`、CAS和0006逐段推进；这些仍是待用户确认的草案，尚未授权代码；
- 用户随后明确：如果“真实模型实现、结构化输出、费用和辩论级冻结”属于后续 Wave 3/真实服务工作，本次就不做。因此原第10项登录页 Mock/百炼切换完全 `OUT OF SCOPE`，不做前端按钮、平台接口或假实现；真实 LLM仍保持 fail-closed，留未来独立真实服务 Gate/Wave 4。本轮没有改产品代码、OpenAPI、数据库或共享工作簿，等待其余高风险边界确认后再冻结并派发 Luna；
- 用户要求重新纵览 Wave 2 进展、后续路线、当前人工验收步骤、三项关键对照和三项隐藏风险。主窗口完整重读 Project 并核对当前产品：工作树干净、HEAD `b06ab86`、backend/frontend/gateway 健康、Alembic `0005_wave2_manual_advance (head)`；没有重新运行真实 Provider 或改代码。当前报告继续严格区分：M10/M11/M12 的 Mock 两人两轮候选为 G3 PASS，`.6` 的 M07 可见 3D 与 M12 教师 Next 浏览器人工 PASS，M08 真实 TTS FAILED-DEFERRED，因此整体人工 G3 NOT PASS；用户当前只需做真实教室/投影主观验收，真实语音不在本轮验收内。后续按顺序为：若恢复则先开 TTS 窄 Gate；提供正式 TikTok Markdown 后做 RAG 内容验收；再分别授权真实 LLM/Embedding；Wave 3 才实现 M13 投票弹幕、M14 Maya 报告、M15 历史/按需翻译，最后 Wave 4/G5 集成与真实服务验收；
- 系统再次自动恢复活动 Goal，但没有新的用户输入、TTS 合同、收费授权或外部状态变化；主窗口重新核对 Project、产品干净工作树和三容器健康后，没有把系统续行解释为真实调用授权，也没有继续改 TTS 代码。此前已满足严格重复阻塞阈值，故只恢复 Goal 的 `BLOCKED` 状态，等待用户未来明确恢复，不重复真实调用、不制造虚假完成；
- Goal 被系统恢复 active 后，主窗口仍未把它解释为恢复收费授权，而是完成一次零网络、零 Provider 的 TTS 离线根因审计。独立 Sol High 最终为 `CHANGES_REQUIRED / P0=0 / P1=2 / P2=0`：`tts_audio_invalid` 的主要本地入口是下载后严格 `validate_technical_audio`，但同一码也覆盖 Gate 类型/大小、质量和 preview 存储失败；失败时 `output_bytes=0`、无 metrics/request ID 和结构化安全日志，因此既不能证明供应商音频本身坏，也不能排除合法可播放 WAV 被当前 PCM16/24k/mono/传统 RIFF/质量阈值误拒；
- 同轮仅查阅阿里云官方公开文档，未调用百炼。官方当前 Qwen-TTS API 参考显示北京非实时 endpoint 为 shared `dashscope.aliyuncs.com`、英文建议 `language_type=English`，返回北京 OSS `.wav` URL；现 adapter 则故意使用 workspace `_base_url` 并 `del language`。这两项属于恢复 TTS 前必须消除的官方合同/适配 P1，但不能倒推出 attempt=3 根因，因为该次 safe code 已到达可下载 bytes 后的本地校验阶段；
- 唯一 V2 共享工作簿已原位把上述 P1 同步到 M08 后置验证，保留 `FAILED-DEFERRED` 和不重试边界；Artifact Tool 复核 E14 值准确、公式错误为 0，两张表重新渲染，单独把 M08 行高增至 170px 后新增内容完整可见。输出目录仍只有这一份 xlsx，没有遗留 inspect/临时文件；产品代码、运行配置、`.env`、fallback 和数据库均未修改；
- 连续第三次 Goal 完成度审计仍得到同一不可绕过结论：M07、M12、Sol High、确定性检查、Docker/浏览器和 Project/唯一工作簿均已有权威 PASS 证据；唯一缺失的是“百炼新英文人声可解码且网页可播放”。用户已明确把 TTS 留待之后，旧一次性额度已消费且禁止重试，继续需要新的窄合同、费用授权和外部 Provider 状态变化；当前没有仍获授权且能实质推进真实语音验收的安全动作。因此活动 Goal 按严格三次重复阻塞规则标记为 `BLOCKED`，不改写为完成，也不改变 `.6` 的 `M08 FAILED-DEFERRED / 整体人工 G3 NOT PASS`；用户以后明确恢复 TTS 时再作为新的阻塞审计周期继续；
- 自动续行完成唯一共享工作簿与当前合同的只读一致性复核：两张表仍准确记录 `M07+M12 浏览器人工 PASS / M08 TTS FAILED-DEFERRED / 整体人工 G3 NOT PASS`、后端 247/前端 107 和检查点 `b06ab86`；Artifact Tool 公式错误扫描为 0，两张表重新渲染后无空白、破损或关键内容截断，因此无需为制造新版本而改写工作簿。产品 Git 外的 operator TTS 脚本也以 `--check-only` 复验：当前 selector 为 Mock，命令在打开数据库或网络前安全失败，证明 TTS 后置期间不会误触收费调用；未来只有新合同主动切换 selector，并同时给出 `--allow-real + --confirm-one-real-call` 才可能进入真实分支；
- 用户再次允许继续后，主窗口完成一次无副作用的最终完成度审计，并由独立 `gpt-5.6-sol high` 复核：M07 真实可见 3D 为 `PASS`，M12 教师逐回合 Next 为 `PASS`，确定性检查、Docker/浏览器与文档为 `PASS`；M08 只能拆分为“一次性真实 TTS 诊断已执行并安全收口 `PASS`”和“真实英文声音验收 `DEFERRED`”。在线容器内数据库再次确认 attempt=3 为 `failed/tts_audio_invalid`、request/charged=`1/1`、profile=`preview_ready`、active preview/file=`0/0`，三容器健康、Alembic 0005、产品 HEAD `b06ab86` 且工作树干净；没有第四次 TTS、没有改 `.env`/fallback，也没有误签 `.6` 整体人工 G3；
- 用户允许继续修复并明确 TTS 留待之后；本轮没有第四次 TTS、没有 Voice/LLM/Embedding/Translation 调用、没有修改 `.env` 或 fallback，也没有进入 Wave 3/4；
- 现场中文议题 `如何与人建立亲密关系` 在 round-one A/B 成功后、round-two A 连续两次 `turn_generation_failed`。代码与数据库联合证明根因是创建页/后端只检查非空，Mock round-two 问题又原样嵌入 topic，最终被英文输出 validator 的 CJK 防线拒绝；这不是“没接 LLM”导致的随机失败；
- Sol High G0-S 冻结为创建/修改/启动三层早期门禁：稳定 `422 topic_language_invalid`，details 只含 field/language/script，不回显输入；历史 failed/completed 不迁移，旧非法 draft 可修改成英文后再启动。两个 Luna Max 分别实现后端/合同和前端/i18n/a11y，主窗口融合；
- Sol High G2 两次要求修复跨运行时 Unicode 漂移：Unicode name/NFKD 会误收 Glagolitic 并漏 Latin compatibility letter，Python Unicode 版本又会漏 Node 已分配的 U+A7CB。最终由精确 Node v24.14.0 生成 40 段 `Letter && Script_Extensions=Latin` 共享码点表，Python/TypeScript 均二分查询；CI clean-diff、U+2C2E/U+2C5E 拒绝、U+0149/U+2132/U+A7CB 接受和全表可达性通过，最终 Sol High `PASS / P0=0 / P1=0 / P2=0`；
- 完整事故链反例使用预组+NFD 议题跑过两人两轮 A1/B1/A2/B2，四个 turn 均 `final_ready/public`、round-two A 的问题包含完整 topic、无 `turn_generation_failed`；全量为后端 `247/247`、前端 `13 files / 107 tests`，Ruff CI scope、mypy 80、ESLint、TypeScript、Prettier、Next build、OpenAPI/Redocly/generated/68 response/route 13 negatives/FastAPI semantic/仓库边界均通过；
- 重建 Docker 后三容器健康、Alembic 为 0005。1280×720 真页面中文输入保留并立即显示 inline 错误，`aria-invalid=true`，数据库 Debate 数保持 5；合法 `Should Māori and Café/Ç perspectives shape platform policy?` 成功创建未启动草稿 `15fb9eb2-6c19-49ce-bf44-66eef421e3e4`，0 turn、未开始、未清理旧音频，页面无横向溢出且控制台 warning/error 为 0。历史中文失败场及四个 turn 状态原样保留；
- 已创建本地产品检查点 `b06ab86 fix: reject non-English debate topics early`，22 个文件覆盖后端三层门禁、共享 Unicode 生成表、前端即时提示、OpenAPI/CI/Gate 与事故链反例；提交后产品工作树干净，未 push、未建 PR、未公开或部署；
- 唯一 V2 共享工作簿已原位同步 M10/M17/M18、英文议题 Gate、247/107、Sol High 最终 PASS、Docker/浏览器证据和检查点 `b06ab86`；重新导入关键范围准确，公式错误扫描为 0，两张表最终视觉渲染通过，输出目录仍只有这一份 xlsx；
- 用户明确允许本机教师登录，并决定 TTS 问题留待之后解决；本轮没有再次调用 TTS、没有改 `.env` 或 fallback。真页面复现 V1.0 当前 snapshot 仍显示指向完全相同 URL 的“查看 →”，点击当然没有反馈；这不是后端版本/快照丢失，而是选中态 UX 缺失；
- Luna 仅在教师工作台/i18n/样式/快照测试内修复：从已加载 snapshot/query 推导选中版本；当前发布与历史列表中同一选中 V1.0 都显示非交互“Viewing/正在查看”与 `aria-current=page`，未选历史版本才保留正确 snapshot 链接。focused 3/3、全前端 `13 files / 72 tests`、ESLint、TypeScript、Prettier、Next build 通过，独立 Sol High `PASS`；
- 重建前端 Docker 后，1280×720 教师 Bowen 详情真页面两处 V1.0 均清楚显示“正在查看”，没有同 URL 空链接；两张课堂 Avatar 均 `data-avatar-status=ready`、各 1 个 200×260 Canvas 且肉眼可见完整脸部，页面横向宽度 1280/scrollWidth 1280，教师 Agent/课堂页面控制台 warning/error 均为 0；
- 已创建本地检查点 `41343a3 fix: clarify selected agent snapshot` 与验收续记 `8d4cc7c docs: record manual acceptance continuation`，未 push/PR/部署。正常数据辩论 `9c9f1560-0cb5-4ddc-865c-faf51bf3ba31` 固定 Bowen=A=支持、KaiKai=B=反对和两轮；用户明确授权后接受启动清理确认，仅删除上一场 Mock 可回放音频目录，旧文字/来源/辩论记录保留，新场成为课程 current-audio debate；
- 1280×720 认证浏览器已完整走通 A1/B1/A2/B2：开始只公开 A1；A1/B1/A2 结束均进入持久 `waiting_next`，Next 可用且下一位正文/来源未提前出现；A1 等待点刷新后仍只有 1 条 public；三次 Next 均只公开相邻 successor；A2 暂停/继续通过；B2 自然结束后 4 条 public、Next 禁用、整场重播启用并能回到相同终态。A2 为 Bowen speaking/Kaikai listening，B2 相反，两张 Canvas 始终 ready；
- 文件与权威状态核对：上一场 current-debate Mock 音频目录已不存在，新场目录只有 4 个可解码的 1 秒 Mock WAV，总时长 4 秒；课程 current-audio 指针指向新场，辩论为 `debate_finished`，四个 turn 均 `public/final_ready`。这仍不是真实英文 TTS 语音；
- 已把最终浏览器证据写入 Wave 2 Gate Packet，并创建本地检查点 `fe2c793 docs: record teacher-paced browser acceptance`；未 push、未建 PR、未公开或部署。唯一 V2 共享工作簿已原位同步 M07+M12 浏览器人工 PASS、M08 TTS FAILED-DEFERRED、A1/B1/A2/B2 证据、当前风险与下一步；重新导入关键范围准确、公式错误扫描为 0，两张表视觉渲染通过，输出目录仍只有这一份 xlsx；
- 后续无副作用单轮回放检查发现：用户已开始另一场测试，课程 current-audio 指针正确移走且旧 `9c9f1560...` WAV 已删除，但旧场页面仍把整场和 4 个单轮重播按钮显示为可用，点击后才返回 `audio_not_retained`。这是前端留存门禁和后端多真相源缺陷，不是文件丢失；
- Luna Max 分别实现后端持久留存链和前端指针 UX，Sol High 首轮指出持久/cache 分裂和最终音频响应 TOCTOU 两个 P1；主窗口将响应实现收敛为纯 `(metadata, bytes)` 单读取快照后，Sol High 最终 `PASS`、P0/P1/P2 为 0。回放要求 current course pointer、public/final-ready、active StoredFile、canonical 非 symlink 路径、size/hash和有效 WAV 全部一致；pointer mismatch 在状态写入前拒绝；完整回放全量原子、单轮只校验目标；
- 下一场清理和 journal recovery 现在把旧 debate_audio StoredFile 标为 `deleted`，仍保留历史 turn、文字、来源和 audio_file_id。对本机此前已完成清理但仍标 active 的 3 个旧辩论做一次受控状态对齐：先确认相应目录均不存在，再只把 12 条 debate_audio 状态改为 deleted；当前指针场的 2 条文件继续 active，没有删除任何额外文件；
- 最终验证为后端 `218/218`、前端 `13 files / 77 tests`，focused playback `61 + 30`；Ruff check/format、mypy 78、ESLint、TypeScript、Prettier、Next build、Redocly、生成 Client、route 13 负例、仓库边界和 Compose 均通过。重建后三容器健康、Alembic 仍为 0005；1280×720 旧场真页面显示 1 条“这段语音已不再保留”，4 个单轮和整场按钮全部禁用，横向无溢出且 3D 仍可见；
- 已创建本地检查点 `b675837 fix: align replay with retained audio`，未 push、未建 PR、未公开或部署；本次修复没有创建新辩论，也没有调用 TTS、Voice、LLM、Embedding 或 Translation；
- 唯一 V2 共享工作簿已原位同步回放留存 follow-up、M12/M16/M18、后端 218、前端 77、Sol High 最终 PASS、旧场按钮禁用/解释、12 条旧文件状态对齐和检查点 `b675837`；重新导入关键范围准确、公式错误扫描为 0，两张表视觉渲染通过，输出目录仍只有这一份 xlsx；
- `.6` 人工验收增量已完成 G1/G1.5/G2：3D材质 cardinality、教师逐回合 Next、`waiting_next/next_turn_ready`、同一 controller/media handshake、0005、Provider composition 和 TTS 一次性 durable Gate 均通过独立 Sol High 集中审计，结论 PASS、P0/P1/P2 为 0；该结论只签代码风险，不签真实 TTS 或人工页面 G3；
- 主窗口最终确定性回归通过：后端 `204/204`、前端 `13 files / 71 tests`、Ruff/format、mypy 78 source、ESLint、TypeScript、Prettier、Next build；父/产品 OpenAPI 59 paths/68 operations、55/13 route、68 response、WS events 30/17、commands 6/7、private results 5/6、13 route 负例、生成 clean-diff、仓库/密钥边界和 Compose 均通过；
- 0005 migration 通过 fresh/repeat/populated、0004→0005、downgrade/re-upgrade、完整 Wave/Voice/TTS ledger 指纹、命名约束/索引与空外键检查；重建后的 backend/frontend/gateway 三容器健康，容器内 Alembic 为 `0005_wave2_manual_advance (head)`；
- 3D 旧透明画布根因已修复：单材质 mesh 不再被无条件替换为材质数组，多材质仍保持数组；新增 renderer 反例，自动化和集中审计通过。最新 Next 组合真页面已验证 Bowen/KaiKai 可见头脸和 speaking/listening/idle 状态；真实教室后排投影距离仍待用户主观复验；
- 教师 Next 已落地为后端权威门禁：中间 turn 自然结束/跳过进入 live `waiting_next`，只在 successor final/TTS/audio/fence 全部就绪后派生 `next_turn_ready=true`；教师 REST CAS 成功才移动相邻 successor，前端 native ended 不自动 prepare/play。并发、multitab、迟到 HTTP/WS、stale snapshot、终态、重启和 replay 均有反例；
- 真实 TTS attempt=3 已在锁定 backend Docker 中只调用 1 次且没有 retry/enroll/list/exists/delete，结果为 `failed/tts_audio_invalid`。durable operation request/charged=1，profile 保持 preview_ready，active preview/preview file=0，`.env`/fallback 未改；本次 Gate 明确失败并关闭，禁止再调用。累计真实调用为 Voice enroll 1 成功、TTS 3 失败、LLM/Embedding/Translation 0；
- 当前准确结论为 `WAVE_2_MANUAL_DELTA_G2_PASS / M07+M12_BROWSER_MANUAL_PASS / M08_REAL_TTS_FAILED_DEFERRED / WAVE_2_MANUAL_G3_NOT_PASS`。真实英文 TTS 未成功是剩余阻塞；最终 Next+3D 页面验收已完成，不再列为阻塞。Wave 3/4、M13-M15 仍未进入；
- 已创建本地产品检查点 `b493239 fix: gate teacher-paced wave 2 playback`，包含 `.6` 的 56 个代码/迁移/合同/测试文件；提交后产品工作树干净，未 push、未建 PR、未公开或部署。Project 与唯一 V2 Excel 位于 Maya 根目录并已分别原位更新；
- Wave 2 人工验收 `.6` 增量已完成主窗口合同收口与独立 `gpt-5.6-sol high` G0-S：最终结论 `PASS / G1 AUTHORIZED`，P0/P1 均为 0；合同明确 live `waiting_next`、教师 REST Next、readiness-change 事件、0005、3D可见像素和真实TTS attempt=3 单次诊断，Wave 3/4继续锁定；
- `.6` 机械合同证据通过：父/产品 OpenAPI字节/SHA/生成Client/Redocly/68响应，严格路由55/13及13负例，WS events 30/17、commands 6/7、private results5/6与clean-diff；0005已补合法旧Playback非空行重建与命名索引反例，fresh/repeat/populated/downgrade/re-upgrade/全指纹/Voice ledger/FK均通过；
- 早期 G1 阶段曾完成 TTS 窄实现且当时尚未 G2/真实调用：北京官方HTTP结果主机只做精确内存HTTPS升级；attempt=3以固定UUID5主键原子claim，双独立DB/禁用flock并发证明最多一次provider调用，45项focused测试、Ruff和mypy通过。该历史状态现已被上方 G2 PASS + attempt=3 失败记录取代；
- Wave 2 用户首次正常数据人工课堂测试完成两 Agent/四 turn 生成，但暴露两项课堂阻塞，当前不得签署 3D/语音人工体验通过：新辩论 `3fe78945-57bc-48a9-a613-850cb4ac0d1b` 已 `debate_finished`，Bowen matched、KaiKai no_match，四段均 public；两个参与者都有冻结的 `wave1-default-head` AvatarConfig，但真实浏览器画布 `data-avatar-status=ready`、GLB/Draco HTTP 200、控制台无报错的同时仍完全透明空白。只读代码诊断指向 `AvatarRenderer.applyConfig()` 把原本单个材质无条件替换为材质数组，而当前 GLB 每个 mesh 为单 primitive/单材质，导致 Three.js 无可渲染 group；需建立窄修复 Gate、保留单/多材质形状并补像素/可见几何反例后复测；
- 同场四个 turn 均已有真实落盘、可解码、非静音的 PCM16/24kHz/mono WAV，但每段仅 1 秒、`actual_tts_voice_kind=mock_sentinel`，内容是 MockTTSProvider 的确定性正弦提示音而非英文语音；两个参与者 `effective_voice_profile_id=null/voice_fallback_active=true`，真实百炼 TTS 和真实系统兜底仍未激活。因此“听不到英文发言”是当前 Mock 边界而不是学生音色操作失败；若连1秒提示音也未听到，另查浏览器音量/播放控制，但不得把提示音包装成人声成功；
- Wave 2 人工测试现场诊断 KaiKai V1.0：后端权威状态为 `draft/revision=0/agent_md_char_count=0/enabled_documents=[]`，组资料库中的 `kaikai-unrelated-mineral-notes.md` 已 `ready` 但尚未绑定草稿，因此发布阻塞为 `agent_md_missing + rag_missing`；当前浏览器页面同时已退出登录。学生端“上传 AGENT.md”成功后会直接保存并递增 revision，保存按钮再次变灰属于正常；在编辑器粘贴文字时才需点击保存。RAG 文件上传到组资料库不等于启用，仍需在 Evidence Set 勾选后才清除 `rag_missing`；
- 再次明确人工验收解释：`no_match` 由本地 256 维 Mock Embedding 与 `strict=0.20/relaxed=0.08` 相似度阈值决定，先于且独立于 LLM；当前未连接真实 LLM/Embedding，Mock 只用于证明检索、空来源和一般推理安全路径，不能证明真实语义质量或 Prompt 教学效果；
- 建立独立的 Wave 2 人工验收资料包 `manual-tests/wave2-agent-rag/`：包含 Bowen 优质 `AGENT.md`、基于美国最高法院/国会法案/司法部公开资料整理的 TikTok 相关 RAG、KaiKai 同等完整度控制人设、故意无关且已知可走 no-match 的矿物 RAG、弱 AGENT.md 变体、创建/发布顺序和投影远距离评分表；这些文件明确标记为本机测试资料，不替代正式 TikTok 内容验收；
- 人工验收边界补充：当前确定性 Mock LLM 可以真实验证 snapshot 检索、`matched/no_match`、used-only 来源和一般推理边界，但不会语义理解学生 `AGENT.md`，因此本轮不得用 Mock 输出声称“优质 Prompt 明显优于弱 Prompt”。RAG 对照先保持两份 AGENT.md 完整度相近，仅改变证据相关性；Prompt 质量差异留到真实 LLM 独立 Gate；
- 代码只读检查显示当前大屏桌面发言正文约 16.3px、历史 12.6px、来源 12px、Agent 名称 15.4px、按钮文字 12.5px；既有 1280×720/360×800 结论只证明无溢出，不证明教室后排可读。人工测试必须在 100% 缩放、约 2m/5m/8m 位置检查正文、来源、高亮、聆听动作和控制直觉；未完成人工投影测试前不签课堂视觉通过；
- 完成 Wave 2 M10/M11/M12 的 G1/G1.5/G2/G3：M10 冻结当前发布 AgentVersion/KnowledgeSnapshot/Avatar/effective voice 与两轮 A-E 计划；M11 实现完整前驱上下文、真实 snapshot 检索、typed receipt/used-only 来源、no-match 诚实一般推理、两轮结构 validator/观点历史/attempt 1|2；M12 实现权威 Playback、单一 controller、同源音频、WS snapshot/sequence、控制、恢复、停止和重播；
- 三路 Sol High 最终 `PASS`。G3 中实际发现并关闭 setup 默认 controller 渲染循环、resume/pause/action 跨 Turn 泄漏、公开前驱前缀缺口、full replay 只播第一项、延迟 media/socket/control 回调、Start HTTP/WS 乱序、failed/stopped 终态补权、completed replay controller/CAS 和 WebSocket 长 Session 连接池耗尽；所有问题均补反例，最终 M12 组合审计通过；
- 最终主窗口确定性复验：后端 `161/161`、前端 `12 files / 64 tests`、Ruff/格式/mypy/ESLint/TypeScript/Prettier/Next build；fresh/repeat/populated `0004`、Wave 0/1/Voice 指纹、外键、OpenAPI/Redocly/response/generated Client、54/13 route、29/14 event、5/7 command、5/6 private result、WS clean-diff、13 route 负例、仓库边界、Compose 全通过；
- 隔离 Docker/真实浏览器完成最终 TikTok 候选：Bowen V1.0 支持且 RAG matched/显示 `bowen-evidence.md`，KaiKai V1.1 反对且 no_match/零来源；A1/B1/A2/B2 四段 public，前驱数 0/1/2/3，A2 agent question，B2 回答并提出 audience reflection；四个 Job completed；
- 真页面验证 start、pause、resume、立即 skip、stop、refresh、backend restart、full replay、single replay，重播/恢复不新增 Job；prepared speech/source 未提前公开。1280×720 和 360×800 均无横向溢出，六按钮 44px，3D speaking/listening/idle 生效，控制台无 warning/error；
- WebSocket 改为握手/snapshot/每命令/disconnect 短 Session；2 连接池保持 5 个 socket 时 GET/create idempotency replay 可用。验收时确认 Docker Desktop 宿主直接打开运行中 bind-mounted WAL 会造成 inode 分叉风险，已冻结“API/容器内在线检查，后端停机后才宿主 sqlite3”规则；
- 重建最终前后端镜像；Backend/Frontend/Gateway、FFmpeg 5.1.9 和 8080 健康。正常 Demo 数据库恢复到 `0004`、Debate=0、G3 topic=0、外键为空；隔离目录已完整移到 `~/.Trash/maya-g3-wave2-20260827-21252f3`，可恢复；
- 本地提交为 `21252f3 feat: complete audited wave 2 candidate` 与 `e2bbb07 fix: harden wave 2 classroom playback`；未 push、未建 PR、未公开或云部署。Wave 2 全程 Provider 选择器为 Mock；真实调用新增 0，累计仍 Voice enroll 1 成功、TTS 2 失败、LLM/Embedding/Translation 0；
- 唯一 V2 共享工作簿已原位更新“模块对齐”和“决策与门禁”：M10-M12/M16-M18、WAVE 2 G3 PASS、161/64、54/13、真实调用与下一步全部同步；导出后重新导入值准确，公式错误为 0，两张表视觉复核通过，输出目录仍只有一份 xlsx；
- `WAVE_1A_G3_PASS / WAVE_1B_G3_PASS / WAVE_1C_G3_PASS / WAVE_1_COMPLETE / WAVE_2_G3_PASS`。`RAG_PIPELINE_PASS / FORMAL_TIKTOK_RAG_CONTENT_ACCEPTANCE_PENDING`。M13-M15、Wave 3/4、真实 Provider 和完整 Demo 仍未完成。

### 2026-08-27

- Wave 2 M10/M11/M12 已完成 G0 Main 与三路 Sol High G0-S。首轮审计分别发现 draft CAS/OpenAPI 403/404/409、SQLite 跨 participant/snapshot 关系、幂等/Job/音频 swap 崩溃窗、final-ready 前驱上下文、RAG receipt 与 used evidence、结构化输出/共享修复预算、播放 ack 因果环、多标签 controller、snapshot sequence、turn.ready 来源泄漏、Range/终态清理和同源媒体 URL 等问题；主窗口逐项修订后，数据、生成、播放三路最终均为 `PASS`；
- 合同增量正式冻结为 `g0-2026-08-27.5`：父/产品 OpenAPI 继续 58 paths/67 operations 且字节一致，拆分 VoicePreview/DebatePlaybackResource 避免 Wave 1 回归，新增 browser WS command/private result 闭合 Schema，并把 JSON Schema `pattern` 与响应 header 纳入严格比较；当前代码前路由仍为 40/27，Wave 2 完成目标为 54/13；
- G0-S 确定性合同检查通过：OpenAPI SHA/Redocly/response/generated Client、29/14 WS events、5/7 WS commands、5/6 private results、generator clean-diff、13 个 route 负例、仓库边界和 Prettier 全绿；本阶段没有实现 M10-M12 业务代码、没有调用任何真实 Provider，也没有进入 M13-M15；
- 唯一 V2 共享工作簿已原位同步 Wave 2 G0-S、g0.5 合同、40/27→54/13 目标、WS 三类合同、真实调用边界和下一步；重新导入的值/公式错误扫描为 0，两张工作表完成修改前后视觉复核，根入口继续指向同一文件，输出目录仍只有一个 xlsx；
- 已创建本地 Wave 2 Gate 检查点 `d92bf89 docs: freeze wave 2 implementation gate`；提交后产品工作树干净，未 push、未建 PR、未公开或部署；
- 已正式签署 `WAVE_2_G0_S_PASS / G1_AUTHORIZED`；下一步才由 Luna Max 按 M10/M11/M12 互斥所有权实现，完成 G1/G1.5 后再进入独立 Sol G2 和主窗口 G3；
- 用户授权无人值守完成 Wave 1B/1C，并在二者 G3 后进入 Wave 2；主窗口记录初始 Project SHA 和干净 Git 状态，先提交 Gate 检查点 `784312f`，再按 M07/M08/M02 互斥所有权派发 Luna Max，并由三路 Sol High 分别审计音色安全、前端和跨合同/迁移；
- M08 初审实际复现并关闭五类 P0/P1：跨幂等键重复 delete、Provider 列表分页误判、TTS timeout 异常类型绕过重试、供应商 URL 二次 DNS/请求后才校验、startup 删除仍 active 的临时目录。最终采用 profile CAS + 每 profile 单 delete ledger、完整分页可见性、数值 IP/TLS SNI/peer 预校验、DNS/connect/read 总 deadline 和 flock lease；M08 Sol 最终 `PASS`；
- M02/M07 前端初审关闭未保存发布旧 revision、中文大纲写入业务内容、Avatar 状态按钮无效、参数预设不应用默认值、Civic Observer 中文缺失，以及 mutation error 隐藏整个已加载工作台/重复冲突提示；真实 workbench 集成证明 Locale 不重建 Session/API、不增加请求且不丢 pending File/幂等句柄/本地编辑；前端 Sol 最终 `PASS`；
- 跨合同 Sol 关闭 0003 schema 证据、冻结 Voice 负响应、CI 精确输入/Prettier 和 G1.5 浏览器矩阵缺口；最终严格路由 `40/27`、后端 70、前端 40、全部格式/类型/构建/迁移/OpenAPI/WS/边界检查通过并获 `PASS`；
- 主窗口重建 Docker，用真实浏览器完成登录、学生 Agent 工作台和教师页的 `en-US/zh-CN` 首帧/刷新、1280/360、V2 样式、键盘可达、零溢出/零控制台错误和 Three.js r185 画布验收；
- 隔离 Docker G3 完成 Agent、Mock Voice、Avatar、Markdown RAG、发布、教师安全投影、删除/兜底、跨组 404 和重启恢复；预览 WAV/enrollment temp 均为 0。隔离数据和 HTTP 临时凭据已可恢复地移到废纸篓，正常 `0003` 数据库和三容器恢复健康；
- 真实系统音色注册只成功创建 1 次，源文件未修改、临时副本为 0；真实 TTS 技术试听两次失败后按停止条件终止，平台未激活兜底 ID。供应商侧克隆音色仍存在；费用估算低于 0.03 元，真实 LLM/Embedding/Translation 均未调用；
- 已原位更新唯一 V2 共享工作簿：模块表和“决策与门禁”同步 Wave 1 G3（Mock 范围）、真实音色/TTS 状态、40/27 契约、70/40 测试和 Wave 2 边界；重新导入的值/公式错误扫描为 0，两张表完成视觉渲染复核，根入口仍指向同一文件，未创建第二份基准；
- 已创建最终本地产品检查点 `e86f879 feat: complete wave 1 avatar voice and bilingual shell`；83 个文件覆盖 M02/M07/M08、迁移/Provider/CI/测试/资产声明，工作树干净；未 push、未建 PR、未公开或部署；
- 正式签署 `WAVE_1A_G3_PASS / WAVE_1B_G3_PASS（Mock；真实 TTS 待决） / WAVE_1C_G3_PASS / WAVE_1_COMPLETE（Mock 范围）`；下一步只进入 Wave 2 M10-M12，不进入 Wave 3/4；
- 用户授权开始 Wave 1，并指定本机 Demo 共享密码与数据权限收紧；主窗口只把密码写成 7 条独立 Argon2 哈希，未把明文写入 Project/Git/日志，登录、身份切换、登出和撤销通过。`.env`/凭据/数据库/Markdown/快照为 0600，数据根为 0700，启动加固已进入代码和测试；
- 主窗口先冻结 `docs/gates/wave1/GATE_PACKET.md`，Sol High G0-S 两轮发现并关闭 operation 计数、422、10 万字符复用、并发幂等、文件 saga 和 Mock 向量确定性问题，最终 `PASS`；Gate 检查点为 `bed2211`；
- 两个 Luna Max 按互斥所有权并行实现 Wave 1A 后端与前端，契约 Luna 在路由稳定后更新 33/34 严格比较、CI 和迁移/密钥检查；多个 Sol High 分别做前端、后端、契约 G2，未让实现者自签；
- 前端 G2 经过三轮收敛，修复快速身份切换上下文、stale revision 本地内容保护、学生/教师快照串版、所有 keyed UI mutation 的幂等重试与 V2/i18n 边界；最终前端 6 个文件/22 个测试、Lint/类型/构建通过并获 `PASS`；
- 后端 G2 实际复现教师读取未发布 Agent、伪 journal 无法崩溃恢复、lease/token 未约束 stale worker、reindex 删除旧索引、跨快照关系缺口和运行时 422 不可达；Luna 修复为 SQL published-only、独立提交 upload/publish saga、raw-byte idempotency、原子 reindex、复合 FK/check 和稳定业务错误，最终 28 个测试并获 `PASS`；
- 契约 G2 修复强制跟踪私有凭据时扫描跳过和只测空库迁移的问题；CI 现在同时证明空库重复 head 与带固定 Wave 0 seed 的 `0001 -> 0002 -> head` 保真，严格比较为 33 已实现/34 后续占位，最终 `PASS`；
- 主窗口重跑全部确定性检查、冷构建镜像，并用隔离 Docker 数据完成 8080 学生创建/AGENT.md/Markdown 向量索引/matched+no_match/发布、教师只读快照下载、另一组 404 和重启持久化；应用 SQLite 为 foreign keys on/WAL/busy timeout 5000，外键检查为空；临时验收数据已移动到废纸篓，正常数据库迁移到 0002 且未混入 smoke Agent；
- 浏览器桌面与 360x800 登录页通过无溢出、44px 按钮、标签和控制台检查；最终产品提交为 `d4e5c08 feat: complete wave 1a agent rag workflow`，产品 Git 工作树干净，M05/M06/M09/Wave 1A 正式签署 G3；
- 已原位更新唯一共享工作簿 `outputs/20260826-pre-code-preflight/开发文档-模块对齐-V2唯一共享基准.xlsx`：同步 Wave 1A G3、模块证据、代码检查点、风险与 Wave 1B/1C 路线；公式错误扫描为 0，并完成两张表的导出后复读和视觉渲染检查，未创建第二份基准；
- 该条为 02:33 的历史状态：当时尚未完成 M02、M07/M08、M10-M15 和真实服务；现已由本日上方 Wave 1B/1C G3 记录取代，当前下一主线为 Wave 2 M10-M12。

### 2026-08-26

- 已按用户要求在授权 Wave 1 前复核并解释数据库/账号安全边界：当前 SQLite 只含 Wave 0 的 `users/sessions/courses/course_members/groups/group_members` 与迁移版本；账号密码不入数据库，后端私有 YAML 只保存 Argon2 哈希；登录成功后浏览器使用 HttpOnly Session Cookie，数据库只存 Session/CSRF 哈希，写请求另做同源和 CSRF 校验；
- 已只读核对本机实际状态：`.env` 与 `demo_users.yaml` 为 0600 且被 Git 忽略；SQLite 为 WAL、外键检查为空，当前 7 用户/1 课程/2 小组；2 条 smoke Session 均已撤销。新增记录了 Wave 1 前应收紧 `data/` 0755 与数据库 0644 权限，以及后续补 Session 清理策略的非阻塞风险；
- 用户重启 Docker Desktop 后，主窗口确认 Engine 29.3.1、Compose 5.1.1 和 Desktop `running`；没有修改冻结镜像 digest、健康检查或全局 Docker 凭据；
- 已完成最终 no-cache 镜像验收：前端一次通过；后端第一次只因 Debian 镜像临时 502 下载失败，保持版本不变原样重试后通过，容器内 FFmpeg/ffprobe 精确为 5.1.9；
- 已完成 `docker compose up -d --wait`、8080 前端/后端路径、教师登录、CSRF 恢复、7 身份列表、切换学生、退出失效、Alembic head、精确种子数量、SQLite WAL/外键完整性和 live/ready smoke；M01 正式签署 G3，Wave 0 状态更新为 `G3 PASS / FOUNDATION COMPLETE`，运行签署文档提交为 `f207977 docs: sign off wave 0 runtime`；
- 本轮运行初始化只写入被 Git/Docker 忽略且权限 0600 的 `.env` 与 `backend/config/demo_users.yaml`；真实供应商 Key 仍为空、Provider 仍为 Mock。自动生成密码仅用于 smoke 且不进入项目文档/提交，含一次性明文的任务临时文件已删除；用户人工演示前需自行安全重置；
- 已再次原位更新唯一 V2 共享工作簿：模块表和“决策与门禁”页已同步 `G3 PASS / WAVE 0 COMPLETE`、运行证据、`c4387a2 + f207977`、当前风险和 Wave 1A 路线；值/公式错误扫描为 0，并完成两张表的最终导出后复读和视觉渲染检查；
- 已让现有 `gpt-5.6-sol high` 基础审计 Agent 做一次收尾只读风险复核，结论为 `PASS`、Wave 0 无阻塞风险；复核再次确认不得把基础完成误称完整 Demo，Wave 1A 必须先冻结 M05/M06 共用 DTO/约束/文件事务/权限并做 Sol G0-S，M09 只能消费稳定的发布只读 DTO，不能反向驱动数据模型；
- 已在 `Maya/maya-platform/` 初始化独立产品 Git 并完成 Wave 0 M01/M03/M04/M16/M17/M18 实现；没有在 Maya 根初始化 Git，也没有复制参考仓库代码或纳入私有/大型素材；
- 已创建首个产品检查点提交 `c4387a2 feat: establish audited wave 0 foundation`；提交包含 90 个通过 G2 的产品文件，工作树干净。Git 首次提交使用本机自动推断的姓名/主机邮箱；未来推送到共享远程前应由用户确认仓库级 `user.name/user.email`，不擅自改全局 Git 身份；
- 已原位更新唯一共享工作簿 `outputs/20260826-pre-code-preflight/开发文档-模块对齐-V2唯一共享基准.xlsx`：模块表和“决策与门禁”页同步 G2 PASS/G3 PARTIAL、各模块证据、检查点 `c4387a2`、Docker Desktop 单一阻塞和下一步；完成表值、公式错误扫描与两张表视觉渲染复核，未新建第二份基准；
- 已按约定使用 Luna Max 分模块实现、Sol High 分模块设计/代码审计、主窗口融合：G0-S 最终 `PASS`；两路 G2 初审的迁移/权限/错误/契约/CI/密钥/生成/初始化阻塞全部修复，两路最终窄复审均为 `PASS`；
- 已实现 Session/CSRF/Origin、预置身份切换、教师/学生课程与小组隔离、精确 UUIDv5 seed、SQLite/Alembic、稳定错误 envelope、冻结 OpenAPI/生成 Client、严格 API/WebSocket 契约、Mock-only CI、Secret/仓库边界、一键 0600 本地凭据初始化和 Caddy/Next/FastAPI 三服务骨架；
- 主窗口最终验证通过 pnpm frozen install、Prettier、ESLint、TypeScript、Vitest 3/3、Next build、Ruff、mypy、pytest 14/14、Alembic、seed twice、严格 9-operation 语义、67-operation 响应、29/11 WebSocket 正反例、11 个 route 负例、生成 clean-diff、初始化器安全探针、Secret 扫描和 Compose config；
- 三张冻结基础镜像和首次前后端应用镜像构建成功；Docker 凭据助手无响应时使用任务临时匿名配置完成拉取，没有改全局账号。随后 Docker Desktop 在启动任意容器时卡住，最小 Caddy 也复现；Desktop 重启后持续 `starting`，Mac 锁屏阻止查看 UI，故最终加固镜像重建和三服务健康/登录 smoke 保留为 M01 唯一 G3 阻塞；
- 用户的 `pip install FFmpeg` 只安装 Python 包；主窗口已安装真实宿主机 FFmpeg/FFprobe 9.0.1。后端 Dockerfile 使用精确 Python 镜像 digest、`uv.lock`，并固定/验证 Debian FFmpeg `7:5.1.9-0+deb12u1`；
- 用户于 2026-08-26 19:06 明确授权“开始 Wave 0”，C12 整体标记 `FROZEN`，编码门禁正式打开；授权范围是按冻结合同和 Gate 实现 Wave 0，不代表跳过审计或直接进入后续 Wave；
- 已确认 Docker Desktop 正常运行：Docker Client/Server 29.3.1、Compose 5.1.1；用户通过 `pip install FFmpeg` 安装的是 Python 包而非系统转码器，主窗口随后更新过旧 Homebrew 并完成真实 FFmpeg/FFprobe 9.0.1 安装；Wave 0 后端镜像仍会显式安装 FFmpeg，避免依赖宿主机；
- Wave 0 首轮 Sol High G0-S 返回 `CHANGES_REQUIRED`，主窗口在派发高风险实现前暂停 M03/M16/M17/M18，完成 `g0-2026-08-26.4` 窄合同修正：31 个认证 mutation 全部显式要求 CSRF；`/auth/me` 返回可恢复 token 的 AuthSession；冻结 UUIDv5 namespace/精确 seed IDs/fingerprint 冲突规则；要求完整 WS event payload union/反例；生成客户端唯一归 M17；依赖复审后将 TypeScript 从不兼容的 7/6 调整为 openapi-typescript 支持的 5.9.3，将 ESLint 固定为可执行的 9.39.1、jsdom 固定为兼容 Node 24.14 的 29.0.1，并显式锁定 Vite 8.2.2、testing-library/dom 10.4.1 和镜像 digest；当前等待同一 Sol 最终复审；
- 已按用户授权完成编码前预检清理，但编码门禁继续保持关闭：没有创建 `maya-platform`、没有初始化产品 Git、没有写产品代码或调度实现型 Agent；
- 已清理 `Project.md` 当前生效区的四类状态冲突：展示脚本的数字 1/2 已改回 A/B；第 6/7 节标题分别改为 C02/C03 已冻结；M01-M18 表的最后一列改为开发期实现/后置验证；M16/M17 明确区分“合同已冻结”和“开发期需用迁移、Client、WS Schema、路由测试证明”；
- 已修正代码资产事实：Maya 根目录不是 Git worktree，但 Document Validation Agent 内含两个嵌套 Git 仓库，private 目录含真实 `.env`；Wave 0 必须只在 `maya-platform/` 初始化独立 Git，避免把私有配置和大型参考素材纳入产品仓库；
- 已将 V2 Excel 设为唯一开发共享基准：新文件为 `outputs/20260826-pre-code-preflight/开发文档-模块对齐-V2唯一共享基准.xlsx`，根目录 `开发文档.xlsx` 仅作为指向它的入口；原根目录旧工作簿和锁文件已可恢复归档到 `archive/pre-code-preflight-20260826/`；工作簿两张表已完成值、公式错误和视觉渲染复核；
- 已完成本机启动前复核：Node 24、pnpm 11、Python 3.12、Docker CLI/Compose 可用；Docker Desktop 后台服务尚未启动，Wave 0 当天启动即可；宿主机没有 FFmpeg，后续固定放入 backend Docker 镜像；另发现 `/opt/homebrew/bin` 为 `0777`，已作为真实 Key 接入前的本机安全整改项记录，本轮未修改系统权限；这些是实现准备，不需要重新打开产品决策；
- 用户撤回 V1/数字编号视觉冻结，指定 Visual Draft V2 作为 Demo 唯一视觉终稿：全站恢复 V2 柔和无衬线字体、紧凑标题/正文层级和 A/B/C/D/E 参辩槽位；不使用 Georgia/Times；保留 V2 大屏纯视觉状态、二维码→滚动原始弹幕→实时票数布局；
- 已将可交互视觉稿恢复为 V2 并用真实浏览器复验：教师槽位 A/B，课堂 5 人标签 `A. Bowen Agent` 至 `E. Agent`，手机投票同步字母槽位；1280/736/360 无水平溢出或控制台错误，1280×720 辩论窗口 715px、互动窗口 695px；38px 主标题、15px/1.5 发言正文、全站无 Georgia/Times 均通过计算样式检查；
- 已将 Project 当前权威章节、G0 C01/C02/C06/C09、C11、C12 和 OpenAPI 同步回字母槽位；公开 `slot` 为 `A|B|C|D|E`，内部 `order_index=0..4` 保留确定性排序；合同版本更新为 `g0-2026-08-26.3`；
- 已同步开发共享工作簿 V2 终稿版 `outputs/20260826-c12-visual-v2-final/开发文档-模块对齐-V2视觉终稿.xlsx`，替代刚才的 V1 视觉冻结表；已复核两张表的值、布局和公式错误；当前准确门禁仍为 `VISUAL V2 FROZEN / PENDING EXPLICIT CODING AUTHORIZATION`，尚未创建 `maya-platform` 或开始正式编码；
- 用户完成 C12 视觉最终决定：字体设计、标题、字号、字重、字距和行距全部退回并冻结为 V1 基线；Georgia 只保留在 V1 原有编辑式位置，Agent 名称和普通正文使用 V1 Inter 无衬线栈，Times 不引入；后续除真实缺陷或用户明确重新打开外不再调整全局视觉；
- 已更新可交互视觉稿并保留此前确认的 1-5 顺序、大屏不显示 speaking/support/listening/attentive 文字、互动阶段“二维码 → 中间慢滚原始弹幕 → 实时票数”等非字体改动；真实浏览器复验 1280/736/360 三档无控制台错误和横向溢出，1280×720 辩论窗口 713px、互动窗口 693px；46px 主标题、16px/1.42 发言正文、V1 字重/字距及无 Times 均通过计算样式检查；
- C12 当前准确状态更新为 `VISUAL FROZEN / PENDING EXPLICIT CODING AUTHORIZATION`：视觉已不再需要审阅，但用户尚未明确允许创建 `maya-platform` 和开始 Wave 0，因此正式编码门禁继续关闭；
- 已同步 `C12_VISUAL_REVIEW.md`、`C12_REVIEW.md`、合同目录状态和开发共享工作簿视觉冻结版；视觉稿、项目文档和共享表以同一冻结结论为准；
- 用户提出 Visual Draft V3 最小修订：参辩顺序不再使用 A/B/C/D/E，统一改为阿拉伯数字 1/2/3/4/5，并采用 `1. Bowen Agent`、`2. KaiKai Agent` 显示格式；顺序编号只表示本场及每轮先后，不代表立场；
- 用户撤回 V2 的全局无衬线/缩小字号方向：Georgia 恢复并扩展到品牌、主要标题、Agent 名称、发言正文、报告层级和手机主标题；标题与正文恢复初版尺寸；Times 单独移除；V3 起默认保留初版设计，除用户指出或真实可用性测试发现问题外不再顺手做全局视觉调整；
- 已完成 Visual Draft V3 并用真实浏览器复验：教师顺序槽位为 1/2，课堂 5 人标签为 `1. Bowen Agent` 至 `5. Agent`，手机投票同步数字编号；Georgia 同时用于主要标题和英文发言，Times 不存在；736px/360px 无水平溢出，1280×720 辩论窗口 717px、互动窗口 697px，JavaScript/控制台错误为 0；
- 已把顺序语义同步到 Project 当前契约、G0 C01/C02/C06/C09、C12 和 OpenAPI；合同版本更新为 `g0-2026-08-26.2`，公开 `slot` 改为整数 1-5；OpenAPI 机械复核仍为 58 paths、67 operations、47 schemas、342 次/63 个唯一内部引用、0 缺失引用；
- 已同步开发共享工作簿 V3：`outputs/20260826-c12-visual-v3/开发文档-模块对齐完整版-v3.xlsx` 更新 M02/M10/M12 和“决策与门禁”，保留旧版不覆盖；已完成值、表结构、公式错误和两张工作表视觉渲染检查；
- 用户完成 Visual Draft V1 首轮审阅：整体气质、双场景、主色、学生构建层级、2-5 人布局、互动逻辑和手机独立提交总体接受；教师页信息清晰度仅为“还可以”，要求继续加强；
- 已完成 Visual Draft V2：全站改为 `Inter Variable/Inter/PingFang SC/Noto Sans SC` 柔和无衬线字体并收小标题/正文，删除 Times/Georgia；教师创建页增加“2 selected / Fixed 2 rounds / Maya after interaction”和 `ROUND 1 A→B / ROUND 2 A→B / INTERACTION→Maya` 流程条；
- 已按用户决定删除大屏 speaking/support/listening/attentive 可见文字，只保留发言高亮、光环、波形以及聆听表情/动作；真实状态仍由后端权威播放状态驱动并通过无障碍标签表达；
- 已把课堂互动调整为左侧二维码、中间大面积 Raw Barrage、右侧 Live Vote；全部原始昵称弹幕自动慢速纵向滚动，支持悬停暂停和 `prefers-reduced-motion` 手动滚动降级；
- Visual Draft V2 已用真实浏览器复验：736px 与 360px 无水平溢出，1280×720 下辩论产品窗口高度 717px、互动产品窗口高度 697px；可见状态文字已删除、互动顺序正确、滚动动画启用，JavaScript/控制台错误为 0；当前仍是视觉占位，不代表真实 GLB、RAG、TTS、API 或数据库已经实现；
- 已同步开发共享工作簿 V2：`outputs/20260826-c12-visual-v2/开发文档-模块对齐完整版-v2.xlsx` 更新 M02/M10/M12/M13 和“决策与门禁”，保留旧版不覆盖；已完成工作表值、表结构、公式错误和视觉渲染复核；
- 用户启动 C12 视觉稿审阅，并提出“以 OpenMAIC 为主、RomanticSimulation 为辅”；主窗口确认该方向但按页面分工：OpenMAIC 主导课堂深色舞台、发言者聚焦、气泡/来源和控制 Dock，RomanticSimulation 只辅助后台暖色留白、卡片层级、编辑式标题和移动端重排；不复制任何参考代码、业务领域或恋爱粉橙主色；
- 已完成可交互 Visual Draft V1，覆盖学生 Agent 工作台、教师辩论创建页、课堂大屏、观众手机页；课堂页可切换辩论/互动/Maya报告和2/3/5人布局，手机页可演示投票/弹幕分别成功；视觉源位于当前 Codex 可视化目录，审阅说明写入 `docs/pre-code-contracts/C12_VISUAL_REVIEW.md`；
- Visual Draft V1 已用真实浏览器验证：736px与360px无水平溢出，课堂产品窗口在1280×720目标下高度717px，交互切换和手机两项完成状态正常，JavaScript/控制台错误为0；当前仍是视觉占位，不代表真实GLB、RAG、TTS、API或数据库已经实现；
- 用户确认 C12 功能范围中的职责权限、固定两轮/Maya、辩论后互动、Markdown-only RAG 和最近一场语音留存均无修改，并决定“正式编码前先做一次视觉稿确认”；当前准确结论为“可以提交 C12 审阅”，不是 C12 已完成，视觉稿确认和用户明确授权前编码门禁保持关闭；
- 已完成开发共享工作簿 `outputs/20260826-c12-module-alignment/开发文档-模块对齐完整版.xlsx`：按 M01-M18 拆成基础运行、视觉、登录、组织、Agent/版本、RAG、3D、音色、教师检查、辩论规则/生成/大屏、互动、Maya、历史、数据库、Provider 和质量协作模块，并逐项填写功能、已确认边界和问题/后置验证；另含“决策与门禁”页记录本轮决定和 C12 状态；已完成两张表的值、表结构、错误扫描和视觉渲染检查；
- 已完成 C12 前当前进展/用户检查项/隐性风险复核：再次确认 `maya-platform` 不存在、Maya 根目录不是 Git worktree、当前只有编码前合同包而没有产品源码；新增合同冻结不等于软件完成、合同规模、OpenAPI/WS 机器校验、逻辑 ERD 未落迁移、视觉稿缺失、TTS 延期、无文本上限和 Maya 生成式综合等风险说明；
- 用户新增并冻结“禁止直接复制粘贴参考代码”：只能参考交互、算法、状态机、接口分层和测试思路；Maya 实现必须从本项目合同独立设计；禁止任何代码片段复用，没有例外；
- 已创建 `docs/pre-code-contracts/` 完整 G0 合同包：`README.md`、C01/C02/C04-C10 的 `G0_CONTRACT.md`、C03 `openapi-v0.1.yaml` 和 C11 `C11_GLOBAL_AUDIT.md`；没有创建产品源码；
- 已使用三路 `gpt-5.6-sol high` 只读挑战页面/权限/E2E、ERD/API/Provider、安全状态机/事件/Gate；主窗口吸收了 completed 语义、replay mode、turn.ready、持久事件、旧成功报告保护、snapshot API 和音频并发确认等建议；
- Sol 建议增加 TTS 失败策略，但因用户此前明确“暂不考虑，出现再想”，主窗口未接受该产品扩张；C07 以 `DEFERRED_BY_USER` 冻结，不注入 TTS 失败、不静默降级，真实出现时重新打开该边界；
- OpenAPI v0.1 当前包含 58 paths、67 operations、47 schemas；机械验证通过 YAML 解析、342 次/63 个唯一内部引用且 0 缺失、operationId 0 重复、path 参数 0 缺失、关键路径和关键幂等键 0 缺失；
- C01-C11 已标记 `FROZEN`，C11 结论为 `PASS FOR C12 REVIEW`；当前只待用户 C12 非技术总确认，编码门禁仍关闭；
- 已完成 `Project.md` 编码前全局冲突清理：新增第 0 节唯一权威契约快照和文档优先级；第 11 节明确为历史记录，第 12 节明确为不可直接实现的原始基线，并增加九项“原始目标 → 当前 Demo”替代表；
- 已清理活动章节中的已知冲突：P0 从“待确认”统一改为“已全部确认”；互动统一为教师手动打开；Maya 统一只读匿名聚类洞察；时长字段统一为 Demo 空值；历史数据留存、跨组权限、旧版选择、3D 私下许可边界和 OpenAPI 唯一契约口径已一致；
- 已把 Debate/Playback/Interaction/BarrageInsight/Report 统一为五个状态域，补齐弹幕洞察事件和 `interaction/close → insight → Maya report` 顺序；修正知识 API，使发布成为创建正式 KnowledgeSnapshot 的唯一动作；
- 已建立 C01-C12 G0 技术合同硬门禁：产品 P0 已冻结，但 OpenAPI/ERD/状态机/事件/权限/错误/线框/E2E 等必须实际产出、审计并标记 `FROZEN`，用户完成 C12 总确认前不得创建正式代码或调度实现型 Agent；
- 已纠正弹幕的双层数据链：大屏和教师历史逐条原样展示昵称与弹幕；Maya 不直接读取原始数据，互动关闭后先去昵称、聚类相近观点、筛除无关/无实质内容，并由后端按真实消息 ID 校验归属和计算数量；
- 已新增 `BarrageInsightPolicy/BarrageInsightSnapshot` 边界：洞察保留内部来源映射和 included/filtered 数，少数或批评观点不能因不受欢迎而被筛掉；洞察失败可重试且不影响原始互动数据，Maya 只读取验证后的匿名主题；
- 已确认一个小组可创建多个 Agent，并拥有可复用的组内 Markdown 资料库；每个 Agent 草稿只读取自己明确启用的文件、发布独立不可变 RAG 快照，跨组 Agent/MD/RAG 在后端列表/详情/下载/关联/发布全部隔离；
- 已冻结版本按钮语义：继续编辑唯一草稿、创建新版本、发布更新、归档/取消归档；发布版不可原地修改，新版发布后教师不能为新辩论选择旧版，但教师可查看全部发布历史且已创建辩论继续使用固定旧版；
- 已确认 Demo 不开放教师可编辑硬时长；除既有 AGENT.md/RAG/音频服务边界外，不给辩题、昵称、弹幕或单个 Markdown 增加产品级大小上限；私下本机 Demo 的 3D 素材暂不做许可核验，公开分享/交付/正式课堂前再恢复许可门禁；
- 已完成编码前第一轮全局边界审计，并提出 `maya-platform` 独立源码目录、Next.js/FastAPI/Caddy 单入口、SQLite WAL/本机文件、单进程 TaskManager、OpenAPI 生成前端类型的推荐实现蓝图；本轮仍未创建产品代码；
- 已将 M01-M18 收敛为 Wave 0-4 依赖顺序，避免 18 个模块无契约同时开工；共享会话/数据库/API/质量门先行，Agent/RAG 与 3D/TTS/UI 可并行，之后才进入辩论、互动和 Maya 报告；
- 已给出单 SQLite 的七个逻辑数据域和推荐表，明确 Markdown/音频进文件系统、结构关系/文块/Embedding 进数据库、Key/原声音样本绝不入库；本地向量推荐使用 SQLite embedding BLOB + NumPy 余弦检索，通过 `VectorStore` Adapter 保持可替换；
- 已把 Debate、Playback、Interaction、BarrageInsight、Report 拆成五个独立状态域，定义持久 Job、WebSocket sequence/重连和跨数据库/文件的 staging/trash 事务边界；
- 已完成最后 8 个 P0 的确认并写入 8.6；会话、CSRF、错误 envelope、幂等、独立投票/弹幕提交 ID、测试工具和运行拓扑由主窗口在 G0 合同包中冻结；
- 已盘点用户新下载的 `OpenMAIC-main`、`parallax-main`、`OpenAvatarChat-main`；三个目录均无 `.git` 历史，实际复用前必须补记官方 commit/tag；根许可证分别为 MIT、Apache-2.0、Apache-2.0；
- 已静态阅读 OpenMAIC 0.3.2 的课程生成、Agent Registry、LangGraph Director、PlaybackEngine、ActionEngine、Roundtable/气泡、RAG 类型/词法索引、Qwen 声音注册/TTS 和测试结构；因没有 `node_modules` 本轮未运行其构建/测试；
- 已确认 OpenMAIC 只作为课堂视觉/播放工程参考：借鉴纯 PlaybackView、异步 generation token、Provider-neutral 音色注册、RAG lineage 和测试习惯；不照搬 LLM Director、客户端多 Agent 调度、客户端供应商/Key、公开 persistence token、词法-only 未接线 RAG、声音样本缓存或 2000 行巨型组件；
- 已把未来协作升级为省 Token 的风险分层 Gate：Sol High 主要负责高价值“想”和独立审计，Luna Max 负责“做”；高风险双审、中风险单审、低风险 2-4 个批审；所有模块仍记录 Sol 覆盖，先跑机械检查，再用紧凑 Gate Packet 审计；
- 已将教师报告 Agent 从旧称完整改名为 `Maya`；Maya 不占 A-E 参辩字母槽位、不参辩、不投票、不增加 3D 人物；
- 已确认教师按点击先后选择参辩 Agent，系统自动赋予连续 A/B/C/D/E 槽位，字母顺序就是每轮发言顺序；前端不另做拖拽/字母编辑器；
- 已冻结 Demo 为固定两轮，不考虑第 3-5 轮：第 1 轮为“观点 + RAG 证据”，不强制反驳/提问；第 2 轮为“RAG 回应/反驳 + 提问 + 观点更新 + 文明说服”；整场最后一位向全班提出开放反思问题；允许文明说服，禁止直接拉票或操纵性话术；
- 已冻结教学真实性原则：平台不得隐藏补写学生 `AGENT.md` 或为无命中 RAG 偷偷补证据，也不得故意削弱弱 Agent；通过真实检索状态、来源和受控对照证明好的 Prompt/RAG 产生明显效果；
- 已通过 GitHub 官方仓库做首轮筛查；没有项目达到本项目 80% 需求覆盖，最高的 OpenMAIC 也只约 56%，因此确定自研主架构；OpenMAIC、Parallax、ClassroomLM、agent-roundtable、OpenAvatarChat 和 cultural_debate 只按模块参考；
- 已确认参考控制策略：每个模块先冻结本项目契约，最多使用一个主要参考和一个备选；无明确收益不引入；没有清晰许可证的仓库只读不复制；
- 已冻结未来多 Agent 基础分工：主窗口负责架构草案/契约/融合/最终验收，`gpt-5.6-luna max` 写代码，`gpt-5.6-sol high` 负责高价值思考和独立审计；后续已进一步升级为风险分层 Gate、紧凑 Packet 和低风险批审，全部模块通过后仍由主窗口执行 G4/G5；
- 已确认手机页先输入昵称，再显示彻底独立的投票区和弹幕区；投票不存昵称，弹幕存昵称，两者不共用提交 ID/数据关联，一项成功/失败不影响另一项；
- 已确认零互动时仍可结束收集并生成 Maya 报告，报告明确写“本场无课堂互动数据”；
- 已完成当前目录实际进度审计：尚无新平台源码目录、根 Git 仓库、OpenAPI/ERD/权限矩阵/状态机或新平台测试；`RomanticSimulation` 只能学习局部骨架和运行思路；
- 已增加 M01-M18 完整实现模块矩阵，覆盖前端、后端、RAG、3D、音色/兜底、辩论、大屏、免登录课堂互动、Maya 报告、数据库、权限、Provider、测试与交付；
- 已将课堂观众端收缩为“辩论结束后的免登录互动页”：教师在大屏手动打开二维码，手机页不观看辩论、不播放语音、不接收 WebSocket；
- 已确认投票成功后只锁定投票区，弹幕成功后只锁定弹幕区，两项均完成才显示总体完成；刷新后两项均可再次提交，Demo 不设观众会话、Cookie/设备指纹或防重约束；不限人数，但本阶段不做压力测试或并发性能承诺；
- 已确认后端每收到一份成功提交，立即向教师大屏更新“昵称：弹幕”和各 Agent 票数/占比；不公开昵称与投票的个人映射；
- 已确认 Maya 不在最后一个辩论 turn 结束时生成；教师点击“结束收集并生成报告”后，系统才关闭入口、冻结最终匿名票数和逐条昵称原文弹幕；大屏保留原始数据，但后台去昵称后聚类/筛选并校验计数，Maya 只读匿名洞察；
- 已纠正账号与课堂模型：学生账号只负责本组 Agent/RAG/3D/音色的制作、发布和查看；教师账号独立检查各组已发布成果并在上课时选用、展示和控制；参辩 Agent 运行不依赖创建它的学生登录或在线；
- 已删除“6 名预置学生账号登录后作为课堂观众”的过时设计；互动提交不建立与 `User`、课程成员或小组的映射；
- 已冻结后台超前流水线：当前发言文字校验完成后，可为下一位悄悄执行 RAG/LLM，下一位文字完成后再独立执行 TTS；最多超前一位；教师大屏直到正式播放时才同时收到完整英文气泡、音频和 3D speaking 状态；
- 已确认课堂播放权限分离：启动、暂停、继续、跳过、停止、整场/单回合重播、测试翻译、打开/结束互动收集仅课程教师可操作，后端必须做课程教师角色校验；免登录手机页只可在入口开放时提交表单；
- 已确认正常辩论和 Maya 报告完全以英文运行；教师测试时可点击“翻译当前全部内容”，批量翻译当时已公开发言和当前报告；DeepL Key 是可选后置配置；
- 已确认每门课程保留最近一次已启动辩论的全部已生成语音，直到教师启动下一场才清理；期间支持整场和单回合重播；原始音色样本在声音注册请求结束后立即删除；
- 已确认 Demo 提供暂停、继续、跳过、整场重播、单回合重播、断点继续和立即停止；模型/RAG 失败后的终止仍不可断点恢复；
- 已确认实时控制最后四项全部按建议：教师点击一次开始后自动连续播放；跳过只结束当前剩余播放并保留文字上下文；普通断线按游标恢复、后端重启从当前 turn 开头恢复且不重新生成；启动下一场前必须确认删除上一场可回放语音并保留文字记录；
- 已确认课程和小组范围全部按建议：固定一门预置课程和两个三人小组，不做课程加入/创建或小组成员管理；组内三人具有相同内容权限，教师只读学生成果；保留密码登录，并只在本机 Demo Mode 提供后端一键身份切换；
- 已确认音色只允许本地文件上传；后端在请求后立即删除样本，页面未刷新时可复用本地 `File` 重试；小组可保留多个音色 ID、每个 AgentVersion 最多绑定一个，组内任一成员可创建/试听/绑定/删除并自动兜底；
- 已确认自定义音色使用一段连续、清晰的 10-20 秒本地英文文件；后端标准化后注册一次并用新句子试听；
- 已确认 3D 产品边界为目标内置 3 个兼容头脸/头肩模板且不允许自定义 GLB；学生只调整受限外观/表情/动作风格；系统自动驱动动作；新增 `attentive` 聆听表情，非发言者使用 `listening + attentive`；私下本机 Demo 暂不进行许可核验，当前仍需解决本地素材的 TalkingHead/Blendshape/多角色兼容；
- 当前 C01-C11 已完成，只待 C12 用户总确认；仍没有创建平台正式代码或调度实现型子 Agent。

### 2026-08-25

- 已阅读完整需求文档并整理产品目标、角色、主流程、输入输出和功能模块；
- 已检查本地 `RomanticSimulation` 与 Document Validation Agent 的结构和可复用边界；
- 已比较四种 Demo 实现思路，当前结论为采用“自有业务核心 + 本地运行骨架 + 开源模块参考”的混合路线；
- 已建立本文件，记录跨窗口协作规则、当前状态、初步 Demo 范围、业务对象、API 领域和遗留问题；
- 已冻结默认 Demo 种子：1 名教师、2 个三人小组、每组 1 个智能体；默认验收选择 Bowen/KaiKai，Demo 支持 2-5 个参辩 Agent 并固定 2 轮；
- 已冻结预置身份、知识库文件/大小/引用、规则轮次、3D 方式、匿名投票/弹幕和 WebSocket 等首轮决策；
- 已补充稳定平台 API、Provider/Adapter、音色克隆与 TTS 的职责和推荐流程；
- 已将原始业务需求文档全文并入本文件，作为跨窗口的完整业务上下文；
- 已确认 Demo 纯英文辩论、中文/英文双语界面、英文发言长度/Token/语速范围、真实音色复刻、顺序共享编辑和无审核弹幕+教师开关；
- 已记录未来三人协作背景：发起人先独立完成 Demo，后续再有两人加入；当前不划分工作，也不实现/规划 Evaluation 专项；
- 已确认 Demo 使用阿里云百炼北京地域和 100 元首轮预算；文本固定 Qwen3.7 Plus 非思考模式；
- 为满足无公网/临时样本 URL 的简化要求，语音方案改为 `qwen-voice-enrollment` + `qwen3-tts-vc-2026-01-22`，本地音频直接 Base64 提交；
- 已确认学生上传即表示授权；平台仍展示用途说明并记录上传人/时间；原声音样本仅在创建音色 ID 时临时存在，请求结束后自动删除；
- 已确认 Demo 只显示 3D 头脸、身体延后、长期最多约 10 个模板；已核验 Maya 中存在 `TalkingHead-main` 和 `motion-engine-main`；
- 已调研更新方案：Google GNM 适合未来参数化头脸，NVIDIA Audio2Face 适合正式版高质量动画，Smithsonian CC0 适合历史人物静态扫描，但都不是首个 Demo 的即插即用素材；
- 已补充 Demo 必须页面和 10-15 分钟展示脚本；
- 已确认 Demo 角色为 Bowen/KaiKai，辩题为美国是否应禁止 TikTok 推荐算法，正式公开资料由用户后续提供；
- 已明确音色 ID 只在课前创建一次；课堂每次调用 TTS 使用现有 ID，不重复声音复刻；
- 已确认 `AGENT.md` + 独立 RAG + 平台规则 + 辩论上下文的智能体创建方案；`AGENT.md` 由学生自由编写，不强制栏目，只可选插入参考大纲；
- 已记录主窗口后续编排 Luna worker、复用优秀 GitHub 局部代码、主窗口集成审计的协作原则；
- 已明确 `.env`/API Key 安全和部署边界：当前 Demo 只在本机运行；以后需互联网演示时，再部署整个 Docker 应用到带持久磁盘的普通服务器；
- 已确认 Demo 账号/密码放在后端专用配置文件，密码以带盐哈希保存，真实凭据文件不提交 Git；
- 已根据用户要求删除原“4.1 GitHub 候选项目调研快照”，并将 3D 参考栈顺延为 4.1；
- 用户最终选择检索式 RAG 而不是全文上下文注入：每个 Agent 已处理正文最多 100,000 个英文字符，发布时固化分块/向量/来源快照，每次发言根据辩题、教师指定立场（如有）或当前观点摘要、对方论点和待回答问题检索 `top_k` 文块；
- 已核对阿里云官方信息：`qwen3.7-plus-2026-05-26` 当前为 1M Token 上下文，北京地域价格按 256K 以内和 256K-1M 分档；项目文档已更正原先可能产生误解的 256K 描述；
- 已将早期固定 A/B 参与者设想升级为参数化多人 Demo：教师按点击顺序选择 2-5 个参辩 Agent，系统自动命名为 A-E 并以此作为每轮发言顺序；统一 `ordered_multi_agent_rounds_demo_v1` 按每轮顺序调度，不为不同人数复制规则；Demo 轮数后续已冻结为 2；
- 已将辩论规则保持为可维护/可扩展架构：版本化 `DebateRuleSet`、独立 `DebateStateMachine`、`TurnPolicy`、`RAGService`、`TurnValidator`、`ReportPolicy` 和分阶段提示词；正式发布前再认真重做赛制；
- 已将教师报告角色正式命名为 `Maya`；A/B/C/D/E 专属于参辩 Agent 槽位，Maya 在所有参辩回合、弹幕和投票收集结束后生成 `CivilizationMutualLearningReport`，不参辩、不投票、不增加 3D 头脸；
- 已确认所有参辩 Agent 可以因文明互鉴过程精炼观点、局部让步、重新框定，或在指定立场模式下换边；系统保留初始/当前观点摘要和变化历史，必须记录促成显著变化的其他人论点或 RAG 证据；
- 已确认只有最后一个计划 turn 正常完成后，教师才可手动打开免登录互动表单；投票选项包含全部参辩 Agent；教师结束收集时冻结最终票数和逐条保留昵称的原始弹幕列表；原始列表用于大屏/历史，去昵称后的聚类筛选洞察才用于 Maya；
- 已确认 Maya 只使用完整辩论和所有参辩者在辩论中实际引用的 RAG 证据；弹幕匿名整理为主要赞同点、主要质疑点、典型问题和数量；
- 已确认教师点击“结束收集并生成报告”后自动生成报告，并保留手动重新生成按钮；报告失败不影响辩论/互动汇总完成状态；
- 已确认每次发言都执行 RAG 检索；正常查询和放宽查询都无命中时，不硬编证据、不终止辩论，允许 Agent 用一般常识、价值判断和逻辑分析继续发言，并以 `no_match/general_reasoning`、空来源在界面上明确区分；
- 已确认英文单次发言最多 200 词；当前建议目标 160-185 词，结构化模型响应预算暂设 512 Token，最终由业务校验器执行词数上限；
- 已确认文明互鉴报告的重新生成历史保留在教师空间：每次生成形成不可变修订，教师可查看/下载成功历史；Demo 学生制作端不提供课堂报告入口；
- 已详细补充原始需求对“发布锁定/新版本”的明确规定及其没有说明的知识库变更语义，并形成不可变 `KnowledgeSnapshot` 方案；
- 已确认并冻结发布/RAG 版本语义：V1.0 永久绑定发布时 S1；知识变更需发布 V1.1/S2；删除当前 Markdown 时保留历史快照中的文件内容和索引；Demo 教师只选当前发布版本；辩论创建后固定版本/快照，历史记录显示当时版本与来源；
- 已完成 RAG 文件输入边界收缩：只接受 Markdown；不检测重复，只检查每个 Agent 草稿的 100,000 字符上限；单文件索引失败不影响其他文件但会阻止包含该文件的草稿发布；不设计重新解析，修改知识时上传新 MD；草稿测试聊天只保留当前页面会话；
- 已明确“上传 MD”不等于“发布 Agent”：只有学生点击“创建智能体”才创建 Agent + V1.0 草稿；V1.0 发布后也不会因上传自动出现 V1.1，学生必须点击“创建新版本”；同一草稿可以多次修改 RAG，只增加内部 `revision`，只有明确发布才冻结新快照并影响教师未来新建辩论；
- 已确认 AgentVersion 发布门槛：`AGENT.md`、至少一个成功索引的 RAG Markdown、100,000 字符/失败文件检查和 3D 头脸必须通过；测试聊天与自定义音色不强制；所有没有 `ready` 自定义音色的 Agent 默认使用兜底音色；
- 已确认辩论创建/启动边界：英文议题非空但不限长度；按点击顺序选择 2-5 个参辩 Agent 并自动生成 A-E；Demo 固定 2 轮；设置“指定立场/开放阐述”；创建固定版本快照；启动前可编辑重选、启动后锁定；每课程最多 1 场运行中辩论；启动校验资源并允许 Mock；
- 已冻结多人规则：教师可为每名参辩者指定支持/反对/中立，也可不设置立场让其开放阐述，不强制正反双方同时存在；第二轮提问沿计划顺序，整场最后一位向全班提出反思问题，不向 Maya 提问；
- 已确认严格开发门禁：先逐模块确认全部 Demo 边界，再由主窗口做一次全局纵览并获得用户最终总确认；在此之前不开始正式代码实现；
- 已确认开发阶段由主窗口冻结契约、用 Luna 实现/Sol 独立审计的模块 Gate 滚动并发，并由主窗口统一融合与最终验收，最终集成为完整本机 Demo 网站；
- 已将真实 API Key 与兜底音色列为后置接入任务：编码期先完成 Provider/Mock/环境变量边界，之后单独配置真实密钥和 `FALLBACK_VOICE_PROFILE_ID` 并进行真机验收；未配置前不得声称真实服务验收通过；
- 已确认 `AGENT.md` 不限制栏目/内容结构，最多 12,000 字符；
- 已确认已发布 Agent 引用的学生自定义音色可直接删除，运行时自动切换为系统不可删除的 `FALLBACK_VOICE_PROFILE_ID`；Demo 将用用户本人声音验证这一流程；
- 已确认教师点击停止后立即停止当前音频/动画并丢弃延迟返回结果，不播放或生成后续发言；
- 已确认 Demo 暂不考虑 TTS 失败策略，实际出现时再处理；
- 已确认单个 LLM/RAG 发言重试仍失败时终止整场，保留已完成文字记录，不从中断回合继续；
- 已确认全部计划 turn 完成后进入“等待教师打开互动”，不会自动开放；教师手动打开、手动结束后不可重开；已明确 Demo 不做 Evaluation 功能；
- 当前没有创建平台代码；产品 P0 与 G0 C01-C11 合同包/冲突审计均已完成；只待用户 C12 总确认后打开编码门禁。

## 12. 原始业务需求完整副本

以下内容完整复制自最初收到的业务需求，仅用于保存需求演进背景。**本节不是 Demo 实现清单，开发 Agent 不得直接从本节领取功能。** 当前实现只认第 0/5/8 节和后续 G0 合同；本节保持原文，不用“修改历史”来掩盖后续范围变化。

原始基线与当前 Demo 的主要替代关系：

| 原始基线 | 当前 Demo 权威决定 |
| --- | --- |
| PDF/TXT/文本上传和单篇在线编辑 | RAG 只上传 Markdown；不做 PDF/TXT/OCR/在线知识正文编辑 |
| 教师创建课程、学生搜索加入、建组和成员角色管理 | 1 门课程、2 个三人小组预置且只读；正式结构保留，Demo 不实现写操作 |
| 学生在辩论进行中实时弹幕/投票 | 所有参辩 turn 完成后，教师手动打开免登录二维码互动；大屏在该窗口内实时显示原始弹幕和票数 |
| 教师配置总时长和单次时长 | Demo 不提供硬时长输入；固定 2 轮、80-200 词和 0.95x-1.25x，只显示预计时长 |
| 专属克隆音色作为每个 Agent 的必备输出 | 自定义音色是可选增强；缺失、未就绪或删除时自动使用系统兜底音色 |
| 课堂观众作为学生身份参与 | 观众免登录，只填昵称；投票不保存昵称，弹幕保存并公开昵称；与学生制作账号无关 |
| 30-60 人课堂并发关注 | Demo 不限制人数但不做压力测试或并发承诺；正式版另行验证 |
| 弹幕原文直接作为互动内容 | 大屏/教师历史保留全部昵称原文；Maya 只读取去昵称、聚类筛选并经代码计数的匿名洞察 |
| 课堂全过程和语音留存 | 文字/来源/弹幕/票数/报告长期保留；每课程仅最近一次已启动辩论语音保留到下一场启动，Demo 不提供音频下载 |

---

# 需求文档

文档定位：本文档仅描述业务需求、功能逻辑。技术选型、架构设计、数据库/知识库服务商选择等均由你们设计。

---

## 一、项目背景与目标

本课程希望学生通过亲手构建AI工具的方式，学习并掌握AI应用能力，并通过课堂上的"数字文化辩论"环节完成文化知识内化与教学互动。

**平台定位说明：** 本平台首先是一个面向学生的**学习/教学平台**，核心目的是帮助学生在动手实践的过程中，理解相关AI工具与基础概念的原理和使用方法，而不是追求生产级产品那样的完善度或视觉精美程度。因此在各功能模块的实现上，应优先保证"讲清楚原理、便于学生理解操作背后对应的AI能力"，视觉效果、性能极致化等可作为次要目标（具体示例见四.3）。

**项目目标：**

1. 让学生在实践中掌握知识库构建、智能体（Agent）搭建、3D数字人设计等AI应用相关技能。
2. 以小组协作的方式，完成代表某一"文化角色"的AI智能体（含知识库、人设、3D形象、专属音色）的制作与发布。
3. 在课堂上，教师可调用学生发布的智能体，围绕指定议题在限定时间内进行有背景依据的多轮辩论，实现不同文化观点的呈现与碰撞。
4. 教师拥有统一的后台，可按课程查看学生成果、管理课堂辩论环节。

---

## 二、用户角色

| 角色         | 说明                                                      |
| ---------- | ------------------------------------------------------- |
| 教师         | 课程管理者。创建/管理课程（一门课程可由多位教师共同管理）、后台按课程查看已发布的智能体、设置并主持课堂辩论场 |
| 学生（小组身份）   | 加入课程后，以小组为单位完成知识库构建、智能体搭建、3D形象制作、音色克隆，并提交发布             |
| 学生（课堂观众身份） | 全体学生在辩论场环节以观众身份入场，发送弹幕、参与投票                             |

---

## 三、账号与课程体系

平台的内容组织以"**课程**"为最外层单位：教师创建课程，学生搜索并加入课程后，再在课程范围内进行小组协作与智能体制作。

### 3.1 教师端

- **创建课程：** 教师可新建课程，系统需为每门课程生成对应的**课程号**，供学生查找并加入该课程。
- **多教师协同管理：** 一门课程可设置**多位教师**，多位教师之间拥有**相同的管理权限**（不区分主次），均可对该课程进行完整的管理操作，包括查看课程内小组与已发布智能体、设置课堂辩论场等。
- **课程管理：** 教师可管理其名下已创建/共同管理的课程（如课程基本信息维护，具体字段由技术团队与教师协商确定）。
- **课程内智能体总览：** 教师进入某一课程后，可查看**该课程范围内**已发布的智能体列表（即"教师后台-智能体管理"功能，现以"课程"为维度组织，详见四.6）。

### 3.2 学生端

- **加入课程：** 学生登录账号后，可通过**搜索课程号/课程名称**的方式，查找并加入对应课程。
- **课程内操作：** 学生加入课程后，在该课程范围内进行小组创建/加入、知识库构建、智能体搭建、3D形象制作、音色克隆等操作。

### 3.3 层级关系说明

为便于开发团队理解整体数据结构，平台核心层级关系如下：

- **教师账号** → 创建/共同管理课程（含课程号，可多教师并列管理）→ 在课程下查看已发布智能体、设置课堂辩论场；
- **学生账号** → 搜索并加入课程 → 在课程内创建/加入小组 → 小组共同构建知识库/智能体/3D形象/音色 → 发布智能体（发布范围归属于所在课程）；
- **课堂辩论场** 同样归属于某一具体课程，教师在辩论场设置时，参辩智能体的可选范围为**该课程下**已发布的智能体列表。

---

## 四、功能模块一：文化智能体构建（学生课后作业）

这一模块对应学生加入课程后课后独立完成的作业流程，最终产出为一个可在该课程的课堂辩论场中被调用的"文化智能体"。

**教学说明：** 由于本课程面向学生讲授AI基础知识，建议在知识库构建、智能体搭建、3D形象制作、音色克隆等各环节中，配有简明的说明性引导文字，向学生解释对应环节涉及的AI基础概念（如什么是知识库与RAG、什么是智能体人设、什么是音色克隆等），帮助学生在完成操作步骤的同时，理解每一步操作背后对应的AI原理，而不仅仅是走完流程。

### 4.1 知识库构建

- 学生以小组为单位，创建并维护属于本组的知识库，作为该组"文化智能体"发言内容的知识来源。
- 知识库资料以文本类资料为主。
- 上传方式需支持两种：
  - **批量上传：** 一次性上传多份文本/PDF资料；
  - **单篇编辑上传：** 支持打开一个文本编辑器，直接编写/粘贴单篇内容后上传保存。
- 知识库与智能体应为绑定关系：智能体的发言/问答应能够基于其所属知识库的内容生成（即具备RAG，具体技术实现由技术团队决定）。

### 4.2 智能体搭建

- 学生基于本组知识库创建智能体，需要设定智能体的"人设"信息，如所代表的文化角色、立场观点、语言风格等。
- 人设字段不做平台强制规定，由学生小组自行拟定人设内容（自由文本形式）。平台可在对应填写位置提供提示文案（如"可考虑填写：文化背景、立场观点、语言风格、性格特征等"），作为引导而非强制项。
- 智能体应具备结合知识库内容进行对话/发言的能力。

### 4.3 3D人物形象制作

- 每个智能体需要对应一个3D人物形象，用于在辩论场等场景中进行可视化呈现。
- **制作方式：模板化选择 + 参数化调整**，即平台提供一套预置3D人物模板（含基础模型、动作库、表情库），学生在模板基础上通过参数调整（如外观细节、可选动作/表情组合等）完成本组文化角色的3D形象定制。
- 学生需要能够为该3D形象添加/选择动作（如手势、肢体动作等）与表情，以配合发言时的呈现效果（如说话动作、情绪表达等）。
- 教学定位说明：教师基于本平台的核心目的是让学生通过实际搭建过程，直观理解一些AI技术在文化知识上的应用，如：一个"数字人智能体"所具备的关键AI能力，包括：专属音色（对应4.4音色克隆）、动作与表情表现力，以及基于知识库的知识储备与问答能力（即RAG，对应4.1）。所以基于本平台制作的AI 作品应更侧重于帮助学生建立对上述能力的整体认知，而非追求视觉制作的精细程度。

### 4.4 音色克隆（语音定制）

- 智能体除文字发言外，还需具备**专属语音音色**：学生录制/上传一段本组代表性人物的语音音频样本，通过音色转换（声音克隆）模型学习该音频样本的音色特征。
- **实现方式：** 音色克隆能力可采用外部现成服务实现，无需自建模型，具体供应商与技术方案由技术团队评估选择。
- 音色学习完成后，该智能体后续所有的语音输出（包括课堂辩论场中的实时语音发言），均需采用该学习到的专属音色进行合成播放。
- 所需的样本录制时长、格式等具体规范，随所选外部服务确定，由技术团队评估后转化为学生端的操作提示。

### 4.5 小组协作与发布

- **小组建立方式：** 学生在加入课程后，可在课程内自行创建小组（类似"拉群"），将其他已加入该课程的学生账号邀请加入本组。
- **权限体系：**
  - 创建小组的学生**默认为组长**；
  - 组长身份**可移交**给组内其他成员；
  - 组长/管理员可对组员进行**移除与管理**；
  - 支持**设置多个管理员**，协助组长进行小组管理。
- 组内成员对小组共有内容（知识库、智能体、3D形象、音色等）进行共同编辑。
- 每组人数暂无上限限制。
- **一个小组可以创建并发布多个智能体**，不限制小组仅制作单一智能体。
- 小组完成制作后，可将智能体正式"发布"。发布后的智能体即进入该课程范围内、可被教师在课堂辩论场中选用的状态。
- **版本管理机制：**
  - 智能体采用版本管理。例如小组首次发布对应生成 **V1.0** 版本；发布后该版本进入锁定状态，不可直接编辑。教师在课堂辩论场等场景中调用的，即为该智能体**当前已发布**的版本（如 V1.0）。
  - 小组若需要继续修改，可在已发布版本基础上**新建一个新版本**（如 **V1.1**）进行编辑；新版本编辑期间，V1.0 仍保持已发布状态、可正常被调用，不受影响。
  - 新版本（如 V1.1）编辑完成后，小组再次点击"发布"，该版本即**覆盖**原有的已发布版本，成为新的当前已发布版本（即由 V1.0 更新为 V1.1）。
- 建议保留历史版本记录（如 V1.0、V1.1……），并清晰标识当前生效的已发布版本；具体版本号规则、历史版本存储与查看方式由技术团队设计。

### 4.6 教师后台（智能体管理）

教师进入某一课程后台，应能够：

- 查看该课程内各小组信息；
- 查看该课程内各小组已发布的智能体列表，包含所代表的文化角色、所属小组、发布时间等基本信息；
- 查看单个智能体的详情，包括其人设信息、绑定知识库、3D形象预览、专属音色试听等；
- 基于该列表，为后续课堂辩论场环节挑选参与辩论的智能体。

---

## 五、功能模块二：课堂辩论场

这一模块对应课堂教学环节，教师在某一课程下调用学生已发布的智能体，在限定议题与时长下进行多方辩论，全体学生同步参与互动。

### 5.1 辩论场设置

教师在某一课程下创建一场辩论时，需要能够设置：

- **议题：** 由教师自定义输入的辩论主题文本；
- **时长（两级控制）：**
  - 整场辩论的**总时长**；
  - 每个智能体**单次发言的时长上限**；
    两者均需教师在创建辩论场时进行设定。
- **参辩角色：** 从**该课程下**已发布的智能体列表中勾选参与本场辩论的若干个智能体（例如：该课程共有5个小组发布了5个智能体，教师可从中挑选2-3个进入辩论场，就设定的议题在设定的时长内进行辩论）。**单场辩论场的参辩智能体数量上限为5个。**

### 5.2 课堂互动功能

全体学生（无论是否为参辩智能体的制作小组成员）可通过扫码或其他便捷方式，进入对应辩论场页面，以观众身份参与：

- **弹幕：**

  - 学生可在辩论进行过程中实时发送弹幕消息，弹幕需实时展示在辩论场页面上。

- **投票：**

  - 投票对象为**本场参与辩论的各个智能体**；
  - 投票结果**实时公开展示**（所有参与者可实时看到统计结果的变化）；
  - 投票人身份**保持匿名**，页面上只展示统计结果（如各智能体得票数/占比），不展示具体是谁投给了谁。

### 5.3 辩论场界面展示

- 辩论场需提供一个统一的展示界面，将本场参与辩论的各个智能体所对应的3D形象，同时呈现在同一个画面中。
- 各智能体的发言需以"对话框"形式，按发言轮次依次展示（多方轮流发言的呈现方式），并配合对应3D形象的动作、表情变化与语音播放同步呈现。

### 5.4 发言生成逻辑

- 辩论按"轮次"进行，每一轮由参辩的各个智能体依次发言。
- **关键逻辑：** 每个智能体在生成本轮发言内容时，输入依据不能仅是辩论议题本身，还必须包含此前所有参辩方（包括对方与己方）在之前各轮次中已发表的全部发言内容，作为生成本轮发言的背景上下文。即每一轮的发言都应当是对"此前全部发言"的回应与延续，而不是脱离辩论进程、孤立地重新阐述议题本身的观点。

### 5.5 语音合成与播放

- 每个智能体在辩论场中发言时，除文字对话框展示外，还需**实时生成语音**并播放。
- 语音音色需采用该智能体在4.4节中已完成克隆的专属音色，确保每个文化角色在辩论中"听起来"具有其独特的、稳定的声音特征。
- **同步精度要求：** 语音播放与3D形象口型/动作的同步**不做过高精度要求**，动作、表情与语音在整体节奏上大致同步即可，无需实现精确对口型。

### 5.6 内容引用与来源标注

- 智能体在辩论中生成的发言内容，若其观点或知识依据来自于对其绑定知识库的检索结果（即RAG检索所得），则该部分输出内容必须标注来源出处（例如引用自哪一份具体资料/文档），确保发言内容可追溯、可核查，符合课程对内容严谨性的要求。

---

## 六、总体架构原则（非技术方案，供技术团队参考）

以下为教师方对平台实现方式提出的原则性要求，具体技术选型与架构设计由技术团队负责：

1. **产品形态：** 平台应为网页端产品，教师与学生均通过浏览器访问使用，无需安装客户端。
2. **算力来源：** 平台不自建/自行部署模型算力，而是通过对接第三方模型服务聚合平台（如OpenRouter一类）来获取AI模型调用能力（含文本生成能力）；语音合成/音色克隆能力同样可采用外部现成服务，无需自建。
3. **数据与知识库存储：** 数据库、知识库等基础设施，可考虑采购第三方成熟服务，具体方案由技术团队评估选择。
4. **教学优先原则：** 平台定位为教学/学习工具，各功能模块的技术实现应优先保证"清晰易懂、便于学生理解操作背后的AI原理"；视觉效果、性能极致化等可作为次要目标（例如3D数字人无需制作得精美或炫酷，见四.3）。

---

## 七、语言与国际化要求

- 平台需提供**英文版**，即教师端与学生端的所有界面文案（导航菜单、按钮、提示语、表单字段、系统消息等）均需支持**中文/英文双语切换**。

---

## 八、非功能性需求（建议关注点）

- **课堂并发：** 辩论场环节可能需要支持全班学生（30-60人规模）同时在线、实时发送弹幕与投票，需关注课堂场景下的实时性与稳定性。
- **多角色同步渲染：** 辩论场界面需同时呈现多个（2-3个及以上）3D角色形象，并驱动其对话内容、动作表情与语音播放的展示，需评估相应的性能与流畅度。
- **语音生成实时性：** 每轮发言需要"生成文本 → 合成对应克隆音色的语音 → 播放"，整体链路的响应速度需关注，避免课堂节奏受到明显影响。
- **权限管理：** 需实现"教师（含多教师并列管理） / 学生（小组身份含组长-管理员-组员三级） / 学生（课堂观众身份）"的角色权限体系；教师、学生的操作范围均以"课程"为边界（教师只管理自己所在的课程，学生只在已加入的课程内操作）；小组内组长与管理员拥有组员管理（移除、设置管理员、移交组长）权限。
- **数据留存：** 建议对学生作业成果（知识库、智能体、3D形象、音色样本）以及课堂辩论记录（发言内容、弹幕、投票结果、语音）予以留存，便于教师后续按课程查阅、评分与教学复盘。

---

## 九、需求确认记录

以下问题已由教师方逐一明确，供开发团队作为需求依据：

| 序号  | 事项             | 确认结果                                                                                              |
| --- | -------------- | ------------------------------------------------------------------------------------------------- |
| 1   | 3D形象制作方式       | 模板化选择 + 参数化调整                                                                                     |
| 2   | 知识库资料范围与上传方式   | 文本类为主；支持批量上传与单篇编辑上传两种方式                                                                           |
| 3   | 智能体人设字段        | 不做平台强制规定，由学生自拟，平台仅提供填写提示                                                                          |
| 4   | 辩论时长控制颗粒度      | 需同时控制整场辩论总时长与每个智能体单次发言时长上限                                                                        |
| 5   | 投票规则           | 投票对象为参辩智能体；结果实时公开展示；投票人匿名，仅展示统计结果                                                                 |
| 6   | 弹幕管理           | 不需要人工审核                                                                                           |
| 7   | 账号与小组关系        | 学生可建组（拉群式）；创建者默认为组长，组长可移交，可设多管理员，组长/管理员可移除与管理组员；每组人数不限                                            |
| 8   | 语音与3D口型/动作同步精度 | 不做过高要求，整体节奏大致同步即可                                                                                 |
| 9   | 音色克隆实现方式       | 可采用外部现成服务，无需自建模型                                                                                  |
| 10  | 内容组织方式         | 以"课程"为最外层单位；教师创建课程并生成课程号，学生搜索课程号加入；小组、智能体、辩论场均归属于具体课程                                             |
| 11  | 课程教师设置         | 一门课程可设置多位教师，多位教师权限相同，不分主次                                                                         |
| 12  | 平台语言支持         | 需提供英文版界面（中英双语切换）                                                                                  |
| 13  | 小组与智能体数量关系     | 同一个小组可以创建并发布多个智能体，不限制为单一智能体                                                                       |
| 14  | 智能体发布后的编辑规则    | 采用版本管理（如V1.0、V1.1）：已发布版本锁定不可编辑，教师调用的是当前已发布版本；小组可基于已发布版本新建新版本进行编辑，不影响原版本使用；新版本发布后覆盖原版本，成为新的当前已发布版本 |
| 15  | 辩论场参辩智能体数量上限   | 单场辩论场最多可选择5个智能体参辩                                                                                 |
| 16  | 平台教学定位         | 平台首先是学习/教学工具，核心目标是帮助学生理解AI功能与基础概念，而非追求生产级产品体验；建议在各功能环节配有说明性引导文字                                   |
| 17  | 3D数字人复杂度要求     | 无需制作得精美/炫酷，核心是让学生通过搭建过程理解数字人具备的音色、动作/表情、知识储备（RAG）等AI能力                                            |

如后续教学设计有新的调整或补充需求，建议以本记录表的形式持续更新，作为开发团队的需求依据。
