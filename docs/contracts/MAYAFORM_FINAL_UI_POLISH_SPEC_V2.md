# MayaForm Final UI Polish Spec v2 — 用户最新增量覆盖

2026-10-05；只读设计交接。观察源基线 `feat/mayaform-v14` / `1d92a2fc98e896084fcf441da4d43c04daf0e258`（Components 删除成果已进入此版本）；`docs/PROJECT.md` 可仍由主窗口记录当次实际验收。本文未改仓库、未调用 Provider、未操作浏览器、未构建或部署。

本文件覆盖 `docs/contracts/MAYAFORM_FINAL_UI_POLISH_SPEC.md` 中与用户新决定冲突的条目。未冲突的隐私、功能、暖纸与同事UI保留规则继续有效；v1中其他P1/P2外观提案仍为可选，不借本次决定自动执行。

**执行门槛是用户明确要求：所有功能测试完成，并由主窗口认为实现齐全后，才实施这轮UI。**当前只交规范，不因规范写完、Components已删、或deterministic tests已绿而提前启动改界面。主窗口继续真实Provider/业务链；本文件不是功能齐全/真实端到端已验收的证明。

用户最终命名澄清已经纳入：**Studyform 与 Workform 是同一页，统一叫 Studyform；Voices 放在 Studyform 的 Agents 模块下面。**不再把这个命名当待用户确认事项，不造两页或两套模块。

本次证据均为 **source / test-source**：读当前路由、组件、既有断言。v1的实际桌面观察可作为旧界面参照；浏览器会话隔离未确认后已停用，不导航、不关闭、不调viewport。本文无v2实际可见、mobile或Provider新证据，不能写成v2视觉验收。

## A. 最新设计与信息结构覆盖

### A1. 明确决定与替代关系

| 用户新决定                                         | 被覆盖的v1旧条目                                          | 最终执行要求                                                                                                  | 影响/优先级                        |
| -------------------------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| 删独立Knowledge页面，成熟RAG能力收进Brainform      | v1允许保留旧Knowledge独立主入口                           | 移除旧独立Files/Knowledge展示页，复用其编辑/下载/Markdown控件与入口引导；Brainform仍直接见三列                | 用户明确UI收敛；P0，功能门槛后执行 |
| Files改RAG                                         | 旧KnowledgeLibrary Files heading                          | 嵌入Brainform的文件区只叫RAG，不重复Files/Knowledge标题                                                       | 文案/承载变化；P0                  |
| Knowledge保留edit符号                              | v1仅去装饰建议不保证复用后edit                            | canonical Knowledge的eye、pencil、合法regenerate与title rename分别保留，尤其pencil不能漏                      | 不改can_edit/full projection；P0   |
| 删Knowledge workspace eyebrow与Brainform页面标题   | v1 E1仍保留/轻化pageHeader标题                            | 删除这两项可见文字及空外壳；保留三组RAG/Knowledge/Memory标题                                                  | P0；不删课程选择/错误/内容         |
| sidebar顺序Mayaform/Studyform/Brainform/Chats/Live | v1保留既有导航顺序与旧group Knowledge/Voices destinations | 采用五个主要目的地及该顺序，复用现有role/group routes，不另建产品架构                                         | P0；已有Teacher操作必须仍可达      |
| Workform=Studyform，Voices在Agents下面             | v1 Voices有独立group目的地                                | 同一Studyform里现有Agents模块之后紧接现有VoiceLibrary；不再有Workform另名页                                   | P0；Voice调用仍显式授权            |
| 删除sidebar New，仅RAG块内New                      | v1 Brainform/Chats sidebar New例外                        | 删除AppShell通用sidebar New；RAG New移入RAG heading action；Chats原New移至自身内容/历史区的现有PageAction承载 | P0；不是删除创建功能               |
| 所有标题下解释文字到title tooltip                  | v1默认保留解释常驻                                        | 同一原文迁移到标题现有tooltip机制，标题下不重复解释句                                                         | P0；信息不会被删掉                 |
| 全部tooltip mousehover 1.5s                        | v1即时hover                                               | 统一1500ms鼠标hover延迟；现有与新迁移的提示一并处理；keyboard即时、touch现有可达                              | P0；timers必须清理                 |

保留同事学院首页、品牌双环、暖纸token、现有Svg、compact tile、PageAction、Profile、General Chat、Agent/Team/Maya Team形态。Components删除成果不回退，也不加替代齿轮/setting/status面板。

### A2. 真实路由映射与推荐承载

源码无Studyform/Workform literal或独立route，不能搜索不到就另造页面。当前可复用对象如下：

| 当前实际路由/组件                                               | 真实内容                                        | 对Studyform的推荐映射                                                         | 边界                                          |
| --------------------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------- |
| `/student` → StudentHome                                        | Welcome、Guide、Members、Profile                | 保持Mayaform Home                                                             | 不把它改成工作台以省一项导航                  |
| `/teacher` → TeacherDashboard                                   | Welcome、Guide、stats、个人/课程Agents、Profile | 保持Teacher Mayaform Home                                                     | Components已经移除，不重画                    |
| `/student/groups/:groupId` → GroupWorkspace                     | 当前group Agents、New Agent、版本/删除          | **Studyform最直接的已有workspace承载**；在Agents后复用VoiceLibrary            | 保留Group/Agent scope，不默认选错误group      |
| `/student/groups/:groupId/voices` → VoiceLibrary                | 上传/consent、rename、preview、confirm、delete  | 同Studyform Voices区的旧链接兼容入口                                          | 不在进入Studyform时自动clone/preview          |
| `/teacher/roster` → RosterWorkspace                             | Members、Groups、Teacher Enter                  | Teacher尚未选定/加入group时复用这个已有选择入口；选定后复用现有GroupWorkspace | Enter可能join，是原显式操作；导航不得偷偷join |
| `/teacher/debates`、`.../new`、control                          | 已有课堂列表/创建/控制                          | 路由和业务保留；五主导航收敛后核对已有HomeGuide/Back/Done链仍可进入           | 不另造Debate新页、不删除已存Debate            |
| `/student/knowledge`、`/teacher/knowledge` → BrainformWorkspace | course/agent/set/job参数、三列canonical工作区   | 保留为Brainform的实际route                                                    | **不能因URL叫knowledge删掉它**                |
| `/student/live` → ClassroomLive                                 | 已有live可用态与文字/舞台                       | sidebar Live仍用原route/可用判断                                              | 不为Teacher新增另一套Live运行器               |

建议主窗口在功能验收后用已有role/group解析生成Studyform href：在group route或Agent route内用现有`routeGroupId/agentScope`对应的group；唯一membership沿现有fallback；Teacher未选定group复用Roster的Groups/Enter。Teacher已进入group时仍以其courseTeacher身份返回Teacher Home，不能退化为普通学生身份。多组场景不得随意取第一组掩盖当前上下文。

这是复用路径的执行提案，不是新Studyform架构。主窗口实施前应把最终Teacher/Student href表写成具体同版本fixture；无需再次问用户Studyform与Workform名称。

五项是主要sidebar顺序。旧独立Knowledge/Voices主项移除；Teacher Accounts/Debates功能不能因导航整理变不可达。优先沿用已有HomeGuide与流程Back链接作为既有入口，不自行增加第六产品模块。若某既定功能确无既有可达入口，先在执行设计里定位缺口，再由主窗口在现有承载里迁移其入口；不能直接删除功能或临时做新dashboard。

## B. Tokens、文字与标题

本轮不用新字体/新palette/新组件库。保留 `.appearance`暖纸tokens、Home学院、原SVG。改动集中在信息承载、标题删减、提示延迟，不自动实施v1里其他颜色/圆角/列数提案。

- Brainform `.pageHeader`删除可见eyebrow与h1。若多课程selector存在，保留这个已有效的selector，其外容器不留下原标题的大padding、border或空高度。只有三组heading负责可见定位。
- 页面/section可访问名字仍存在：可复用已有`PageIntro`或main的accessible name保持Brainform语义，但不是新增可见标题/控件。不要把document里的Markdown `#标题`当页面UI标题一起删除。
- RAG、Knowledge、Memory的heading沿用现有serif/token。Files→RAG仅改源库文件区名称；不把全部下载里的“文件”或用户真实filename统统改名。
- `.section-card-header p`、Brainform `.sectionHeading p`、Team entry heading p等解释句迁移后，删除相应空margin，保留原heading gap。无需做全局border purge。
- 真实状态、empty/error、privacy值、version、成员名、课件正文、字段label都不是装饰解释；仍保持原义。不能用tooltip迁移隐藏错误或让合法操作缺乏实时反馈。

## C. 全局tooltip与PageAction执行设计

### C1. 复用单个UiGuideTooltip，不另建提示体系

源代码入口：`frontend/components/ui-guide-tooltip.tsx`、其module.css、`frontend/lib/ui-guide-copy.ts`、root `frontend/app/layout.tsx`。目前selector是`[data-ui-guide]`，文本来自静态key；pointerover/pointermove即时show，focus/touch/Escape/scroll/blur/resize/DOM变更已有完整行为。

新增逻辑只针对**鼠标hover等待1500ms**，用一个全局延迟值，不能只改CSS animation-delay。推荐最小pending state包含target、原pathname、key/文本标识、pointer anchor、开始时间和timeout handle；现有active状态继续表示真正显示的tooltip。

1. 鼠标进入新guided target时开始一个1500ms timer。1499ms之前既不显示tooltip，也不把不存在tooltip ID挂到aria-describedby。
2. 同target内pointermove只更新anchor位置；**不反复重启timer**，否则鼠标稍动会永远看不到。target从A→B时取消A并重新计B的1500ms。
3. deadline时再次核对target仍connected、当前route/identity及guide来源没有改变、仍是当前hover target；只显示当前授权浏览器里已有的本地文案。
4. keyboard focus沿现有`pointerInput`判别即时show；立即取消等待中的mouse timer，description绑定实际focused control。不能给keyboard也强等1.5s。
5. touch沿现有tap-toggle/pin/外部tap-dismiss即时show，标题本身是existing可聚焦help target，不能增加问号按钮才能看解释。
6. pending与active都要在pointerout、pointerdown/click按既有语义、Escape、scroll、route change、target被卸载/guide变更、visibility hidden、window blur/resize、pointercancel、cleanup时清理。取消后advanceTimers不出现“幽灵提示”。
7. 旧aria-describedby完整restore，保留已有其他description IDs。更新locale显示正确原文且不偷焦点；跨账号/课程迟到timer不能显示旧内容。
8. 保留已有tooltip位置避开原target/邻近controls/text的计算、pointer-events策略与reduced-motion；只改变出现等待，不能借此改变动作的hover视觉反馈（反馈仍即时）。

静态说明复用`ui-guide-copy` keys；标题的原`description`或安全动态内容可由原React owner传给既有Tooltip最小text seam，统一纯文本和locale。不要根据全DOM任意textContent自动抓“下一段说明”，不要innerHTML，不请求LLM生成help。标题同时已有guide与原description时只产生一个tooltip，原说明作为内容权威，避免两个文本源互相漂移。

### C2. 全局既有tooltip盘点（source）

| 所有者/现有guide                                                                                 | 当前源文件                                             | 本轮处理                                                                     |
| ------------------------------------------------------------------------------------------------ | ------------------------------------------------------ | ---------------------------------------------------------------------------- |
| workspace new/back/done/logout                                                                   | `app-shell.tsx`、`page-action.tsx`、`ui-guide-copy.ts` | sidebar New去掉；剩余现有help统一mouse1500ms；原PageAction语义保留           |
| knowledge.files/edit/download/reindex/hide/importFile                                            | `knowledge-library.tsx`、`markdown-editor.tsx`         | Files help改RAG语境；放进BrainformRAG；group/personal说明不能写错scope       |
| agent.markdown/evidence/voice/publish/ragPreview/snapshot/download/uploadMarkdown/uploadEvidence | `agent-workspace.tsx`                                  | 原guide继续，全部统一mouse1500ms；正文/验收项不移成hiddenhelp                |
| roster.openGroup/deleteAgent                                                                     | `roster-workspace.tsx`、`student-workspace.tsx`        | 原动作与read/join/delete语义保留，delay不触发API                             |
| chat.delete/send/readOnly                                                                        | `agent-chat.tsx`                                       | 同一消息/状态可访问说明保留；mouse1500ms；disabled说明仍能按原路径获得       |
| debate.topic/background/agentOrder/ruleset/rulesetEdit/rulesetSave                               | `debate/setup/debate-setup.tsx`、`ruleset-editor.tsx`  | 原headings无重复解释；不改Ruleset、语言、创建条件                            |
| voice.consent/preview/confirm/delete/uploadSample                                                | `voice-library.tsx`                                    | 移入Studyform后原help继续；consent本身必须显示可勾选原label，不能只hover确认 |
| camera.scene/forward/left/right/backward/turnLeft/turnRight/aerial                               | `stage3d/scholar-scene.tsx`                            | 即使本轮不改舞台UI，也享有全局1500ms；操作不延迟                             |

原生DOM `title`不能保证1.5s且可能与customtooltip重叠，应逐处迁入同一个现有guide。下面是实读到的native title，非SectionCard的`title`prop：

| 文件                              | 原生title用途                                               | 迁移边界                                                             |
| --------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------- |
| `brainform-workspace.tsx`         | RAG view/edit；Knowledge view/edit/regenerate；Memory enter | 用原文的customguide；aria-label与对象名继续，不去掉Knowledge pencil  |
| `teacher-workspace.tsx`           | version pill、AGENT.md/RAG download、RAG filename           | 版本仍version→X互斥，filename仍完整数据；不改变Delete/Download动作   |
| `knowledge-library.tsx`           | 原filename完整说明                                          | 文件本名留在行，长名可访问，不因tooltip删除title后变不可知           |
| `agent-chat.tsx`                  | history Agent/Team名字，disabled send/readOnly状态          | 不读取/输出旧历史；安全fixture验证动态说明；状态不变成新增badge      |
| `debate/setup/ruleset-editor.tsx` | Back                                                        | 复用workspace.back准确文案，不改Back丢/保留语义                      |
| `debate/debate-status.tsx`        | stalled原因含安全round/code                                 | 实际failure短句仍保留；动态safe reason本地text映射，不泄provider正文 |

`<SectionCard title=...>`、`<EmptyCard title=...>`、`<PageIntro title=...>`是React内容prop，不是原生tooltip，不应批量搜索替换。ReportMarkdown中的内容标题也不处理成UIhelp。

### C3. 标题下解释文字盘点（source）

| 位置                                                      | 当前说明                                                         | 迁移方式/保留项                                                                                                                      |
| --------------------------------------------------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Teacher personal Agents SectionCard                       | `personalWorkspaceLede`                                          | title tooltip；Private与显式grant事实不删除，原文不改                                                                                |
| Brainform三个section                                      | `brainformRagIntro/brainformKnowledgeIntro/brainformMemoryIntro` | 每个同名heading help；删除常驻p，三列表本身不隐藏                                                                                    |
| Team New chooser三个entryOption                           | `chatNewAgentHelp/chatNewTeamHelp/chatNewMayaTeamHelp`           | 原可点击标题/option作为guide target，解释移tooltip；三入口仍直接可达                                                                 |
| Team管理heading                                           | `teamVisibilityHelp`                                             | heading tooltip；Team privacy真实radio值仍显示                                                                                       |
| MayaTeam目录heading                                       | `mayaTeamDirectoryHelp`                                          | heading tooltip；成员名与目录empty状态是数据，继续显示                                                                               |
| Team各fieldset legend后说明                               | member选择条件、shared Knowledge说明、chatPrivacyHelp            | 若属legend下解释迁到legend help；合法成员/Leader/visibility条件仍由原验证/disabled/error明确，labels不隐藏                           |
| TeacherKnowledgeSources（旧独立界面使用，需复用后查引用） | `personalRawSourceLede/originalSourcesIntro`                     | 不把旧分类整体复制进三列；仅仍存在的source说明迁入对应RAG heading help                                                               |
| KnowledgeSetWorkspace（当前生产route未引入）              | `agentKnowledgeSetsLede`                                         | 如无活跃用户UI不要为了“全局”再引入它；仍使用的canonical head help迁入现有heading                                                     |
| Provider disclosure SectionCard                           | course scope与Team binding说明                                   | 引导说明可tooltip；准确manifest/supplier/outbound/storage/permission/canonical scope事实继续在原披露内容内可读，不删确认所依据的信息 |
| 新增Studyform Voices模块                                  | 原voiceLibrary已有help，无需另写lede                             | 沿原VoiceLibrary，并统一delay；不额外增加一段新说明                                                                                  |

其他paragraph需按语义盘点：fieldlabel、inline error、loading/success、文件格式约束、失败恢复动作、权限/隐私事实、课程数据、AGENT.md/Knowledge正文、Report分析不是“标题下解释”。不因为靠近h2就移走。若确为说明，沿同标题help迁移，原aria-describedby保留必要关联。必要条件/风险含义不能只靠hover理解。

## D. Studyform、入口引导与旧页兼容

### D1. Studyform内复用Agent和Voices

`GroupWorkspace`已有Agents，是优先复用对象。其原Agents SectionCard不改内容/顺序；后面直接复用现有`VoiceLibrary groupId`。可做最小embedded prop隐藏VoiceLibrary自身重复PageIntro，使单页语义清楚；不是新页面/新component体系。

VoiceLibrary mount只读取已有`voiceProfiles`；enroll、preview、confirm、delete只由原明确动作发生。保留consent版本、uploader ownership、preview确认、有效声音记录、rename、idempotency、Unknown不自动retry与原配置边界。仅移动承载不能改已有TTS/Voice Provider设置，不能触发音频生成。

原Voice route和Agent workbench `manageVoices`、StudentHome VoiceGuide复用同Studyform Voices区的兼容导航。可以用已有route forward/fragment定位原模块；具体URL由root按scope验证后选，不新造`/workform`与`/studyform`backend资源。Teacher进入group沿当前显式membership/Enter；有权read不自动edit。

### D2. 已有入口引导不要丢

需要迁移的实际调用点：

- `student-workspace.tsx` HomeGuide知识入口当前指 `/student/groups/:id/knowledge`，Voice入口指 `/.../voices`。
- `teacher-workspace.tsx` AgentDetail RAG action当前指 `/teacher/groups/:id/knowledge`；Knowledge canonical入口指 `/teacher/knowledge?agent_id=...`，后者保留。
- `agent-workspace.tsx` Knowledge/生成完成跳转已有agent_id/set_id/job_id参数，Voices管理link指旧voice route。
- `app-shell.tsx` 原group Knowledge/Voices目的地及GroupWorkspace activePath mapping。
- legacy group Knowledge route两个page.tsx；legacyvoice route page.tsx。

“删除独立Knowledge页面”是删除其独立可见展示，不是让旧deep link404或把授权资料删除。优先把旧route变成到Brainform正确role/course/group上下文的兼容入口，或等价导向现有Brainform并保留原context。**保留 `/student/knowledge` 与 `/teacher/knowledge`，它们已是真Brainform route。**

当前Brainform支持agent_id/set_id/course_id/job_id，没有initialGroupId；必要的group-context适配只能做最小frontend参数/已有Group GET核验，不可忽略legacygroup而默认到groups[0]。Teacher legacygroup原是`teacherReadOnly`，不能借迁移显示edit或自动join。获取合法course后再定位当前group RAG，迟到结果仍scope-fenced。

## E. Brainform RAG与Knowledge完整复用

### E1. 不整块盲搬KnowledgeLibrary

现有复用事实：

- `KnowledgeLibrary`有edit/download、failed-reindex、hide以及`MarkdownEditor`。**其行里没有独立eye/rendered View**；查看成熟实现来自Brainform `viewRag + ReportMarkdown`与TeacherAgent `AgentDetailRagFile`的Check展开。
- 旧`MarkdownEditor`是provider-neutral File/CAS callback seam，import选择文件会立即调用onCreate/onReplace，accept md/pdf/docx。
- 当前Brainform `importRag`只将UTF-8 Markdown读到草稿，显式Save才上传；saveRag区分rename-only与contentChanged，并保存CAS、dirty drafts、identity/course/operation序列。冲突保留draft。
- 旧Library conflict会关闭editor/清内容，旧替换fixtures以replacement-ID体现copy-on-write；不能盲带回v1.4的stable-resource/保留冲突稿契约。

因此复用成熟**界面与安全原语**，保存业务仍由Brainform owner维护；不复制旧Library整块独立header/只选group/auto-submit/clear-on-conflict状态机覆盖Brainform。

### E2. 最小整合方案

RAG列使用旧成熟row/MarkdownEditor视觉与SVG/edit/download、现有guide逻辑；Files改名RAG；New放RAG heading内部action。View保留Brainform现有eye + ReportMarkdown；download复用既有downloadKnowledge+downloadText，按真实downloaded filename/content生成file，不用当前preview伪造。

现有同页editorPanel可继续承载完整Markdown，不另开Knowledge页或overlay新向导，也不强把长输入压在300px列中。三个区仍直接可见；RAG列负责对象、动作与New。若通过复用MarkdownEditor减少重复字段，需要最小draft adapter：字段变化回写Brainform persisted draft，import先draft而非直接POST，save沿Brainform rename/CAS路径，disabled与cancel由Brainform当前scope控制。一个具体共享需求可抽取内部presentational editor seam；不新建万能文件管理框架。

目前Brainform入口只有`.md`；旧独立库有pdf/docx现成转换能力。此轮不新增转换能力，不以“复用”把Brainform改变成选文件立即保存，也不悄悄删除已存在且通过测试的md/pdf/docx能力。主窗口必须列明现有pdf/docx保留在哪个已授权的existing入口；需要迁入RAG时沿已有安全multipart转换API与准确pending文案，不能将binary当UTF-8，也不能另装OCR。这个format承载取舍由root依据用户已授权既有功能决定，不交付时隐瞒格式功能下降。

### E3. 必须保持的行为

1. Stable资料ID/版本与真实CAS，download先取服务端immutable source，不用过期preview。
2. 仅改名走rename metadata，不index/generation收费；content保存沿真实依赖自动update；New无既定生成关系不全站备课。
3. 保存才发生写操作；打开编辑/查看/hover/focus不会生成或provider调用。
4. 完整Unicode/无总字数限制；非法UTF-8/格式失败保留现有输入。未授权组/文档不因导航合并得到权限。
5. request intent/idempotency不变；unknown不盲自动重发，conflict保留稿并读authoritative版本。
6. scope变化清旧可见对象、迟到读/导入/保存不写新身份页面；多group正确target，不以firstgroup替代。
7. 老库hide/reindex/download等既定合法能力不因隐藏独立page失去入口；不把hide变成物理删除原证据。
8. 旧库ready badge不带入Brainform；真实pending/index failure短句保留，合法恢复仍原语义。
9. canonical Knowledge列仍完整eye + **pencil edit** +合法regenerate；can_read不能推can_edit。引用进入同canonical_id，不fork。
10. RAG/Knowledge/Memory三块保留；Memory自动一次真实message的幂等不改，Graph只展示，原Privacy/attempt投影不改。

## F. Chats New迁移与General Chat

当前AgentChat两处`WorkspaceAction name="new"`只注册sidebar入口；实际New chooser由`setShowNewEntry(true)`打开。主窗口已经确定：**将同一触发迁至Chats自身现有内容/历史区域的PageAction。**这是移动原操作，不新增业务控件。

- AppShell sidebar不再render/registerNew；AgentChat loading态保留真实disabled行为但页面控件留原内容位置，不闪可用。
- PageAction仍触发同一个TeamEntryFlow，busy/teamBusy/showNewEntry的禁用条件不弱化。
- New Agent、Create/edit Team、MayaTeam三个原选项与cancel/back都直接可达；fresh New确实建立新上下文，不把旧history或activeattempt清空。
- GeneralChat原history/composer/message/error、自然语言attempt生命周期保留；不增Assessment按钮、statecard或专用input。
- 即使sidebarNew删掉，用户必须能从Team/MayaTeam消息页重新进入同chooser；不能用只切Agent的select替代三kind入口。
- history date/Delete互斥、hover/focus/touch保持。全局tooltip1.5s只影响说明等待，不能延迟send/Delete hover样式或Chat响应。

## G. Team/MayaTeam与解释迁移

原entryOption的title与点击区域不动，仅把下面的三句help迁同一个可聚焦target tooltip。Team management/Maya directory heading下help按C3迁移；Members/Leader/Shared Knowledge真实label/controls、selected version、合法条件/inline errors保留，不造stepper或Team dashboard。

MayaTeam继续配置为Team而用同一General Chat；无published team的empty句保持常驻反馈，它不是解释性lede，不隐藏成tooltip。Privacy选项及所选成员是真实数据，不能隐藏到help。

所有Team source目标与正式attempt grants继续后台核验。只移动说明/入口，不改变Teacher/Public/Student tools、专有evaluator授权或按名字猜角色。

## H. Teacher与维护边界

Components在1d92a2f已删除且v1独立审计通过；本轮不得回退demo-composition组件/CSS/测试或新增替代panel。

Teacher role/course permission、Roster Enter、原合法Disclosure、私密资源投影保持。Studyform不是授予新权限的新角色。读取Voices与Brainform来源的group-context必须是当前合法membership/目标资源；Teacher不可统计Private Chat/Assessment/Memory。

Tooltip迁移只处理说明呈现，不能把精确资料外发内容/实际确认依据删掉，或把Teacher生成恢复变成内容Review/Confirm。任何本轮UI动作不能主动改变APIKey/模式/Provider策略、账本、注册工具或env。

## I. Keyboard、touch、mobile

1. 1500ms仅mousehover；keyboard focus即时help，touch原tap-toggle；不新问号control、不禁止zoom/paste。
2. Heading迁help后保持可聚焦且有semantic heading。已有guide=SectionCard自动tabIndex0模式可复用；目标只为实际有说明的标题，不给每段正文加tabstop。
3. `aria-describedby`指向实际可用tooltip，focus实际control的描述正确，原ID保留；Escape不触发母form提交或清稿。
4. 三列窄屏仍原自然纵排，RAG内部New与列表edit/view/download触达，tooltip clamp在viewport内，不挡邻近控件/文字。软键盘下原editor/Send可读；这些须后续真实mobile补验。
5. Studyform Agents→Voices顺序适用于DOM/focus顺序；嵌入VoiceLibrary不多一个screenreader页面h1或duplicateIDs。
6. 关闭pane或cancelStage回原合法触发，scope换了不focus旧对象；delay timer不在navigation后显示旧private提示。
7. Reduced-motion保持existing短入场规则；不把1.5s解释成animation-duration，动作feedback即时。

## J. 禁止回退与反模式

- 不在功能测试仍pending时实施UI；不把spec交付叫用户功能已齐全。
- 不把Workform再造单独页面；不用AI猜Studyform对应Teacher角色；真实route复用，不新授权层。
- 不删真Brainform `/teacher/knowledge`或`/student/knowledge`，不删Knowledge canonical内容/资产表。
- 不整块嵌套旧Library独立header/Files/Knowledge页，不盲回auto-submit、clear-on-conflict或wronggroup。
- 不只删sidebarNew导致Team/MayaTeam/FreshChat不可达；不删除Agent/Voice区既有创建动作来机械执行“只RAGNew”字面。
- 不漏Knowledge pencil，不把必需edit/view塞more。
- 不仅CSS隐藏说明还让重复nativeTitle即时弹出；不让pointermove重启1500ms；不把keyboard/touch延迟。
- 不偷grab全DOM文本、用LLM生成tooltip、HTML注入或增加API请求。
- 不将真实error/empty/consent/permission facts与实际内容当titlelede隐藏；不减弱披露和Privacy。
- 不恢复Components UI/Provider模式入口，不改注册/策略/账本/env，不新增替代badge/settingspanel。
- 不顺手执行v1其他可选P1/P2外观方案，不重画学院成果。

## K. 文件所有权、功能门槛与可复现验收

### K1. 单写者所有权表（主窗口批准执行后）

本表是职责划分，不是开始代码工作的指令。所有共享源文件须等待功能同版本freeze；一个UI implementation writer负责整个前端切片，避免导航/tooltip/i18n/BF由多人同时改。独立Sol只读审计，主窗口负责合同/PROJECT与正式Provider/部署。

| 所有者职责                          | 精确文件                                                                                                                                                                                                                    | 可改内容                                                                                  | 不动内容                                           |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------- |
| UI writer：Brainform/RAG            | `frontend/components/knowledge/brainform-workspace.tsx`、其`.module.css`                                                                                                                                                    | title/eyebrow去掉；RAG New、edit/view/download与editor复用；helptargets；必要groupcontext | source/grant/attempt/provider业务不可泛改          |
| 同一UI writer：成熟库/editor复用    | `knowledge-library.tsx`、`markdown-editor.tsx`、`knowledge/index.ts`、`library-cards.module.css`                                                                                                                            | 移除独立presentation/提供具体embedded/editorseam，复用现有File/CAS/downloader             | 不把旧scope/clearconflict/autoPOST复制回BF         |
| 同一UI writer：导航/Studyform       | `app-shell.tsx`、其module.css、`student-workspace.tsx`、`voice/voice-library.tsx`、其module.css                                                                                                                             | 五主要目的地顺序、Studyform name、移sidebarNew、Agents后嵌Voices、已有guide更新           | role/membership/Live规则、voice调用授权不改        |
| 同一UI writer：原操作迁移           | `agent-chat.tsx`、其module.css、`chats/team-entry-flow.tsx`、`page-action.tsx`、`workspace-actions.tsx`                                                                                                                     | 移原Chat New、help挂接；若无注册用例再小范围清理dead registration                         | General Chat/messages/attempt/unknown状态机不重构  |
| 同一UI writer：全局tooltip          | `ui-guide-tooltip.tsx`、其module.css、`ui.tsx`、`lib/ui-guide-copy.ts`                                                                                                                                                      | 1500msmouse timer、description text seam与headingfocus；保留position/cleanup              | 不再写第二Tooltip组件，actions不延迟               |
| 同一UI writer：nativeTitle/说明盘点 | C2/C3列出的`teacher-workspace.tsx/agent-workspace.tsx/roster-workspace.tsx/debate/setup/.../debate-status.tsx/stage3d/scholar-scene.tsx/provider/provider-chat-approvals.tsx`                                               | 仅guide/data text属性、title/lede迁移                                                     | 全部功能与调用内容原样                             |
| 同一UI writer：route兼容            | `app/student/groups/[group_id]/knowledge/page.tsx`、`app/teacher/groups/[group_id]/knowledge/page.tsx`、`app/student/groups/[group_id]/voices/page.tsx`、`app/student/knowledge/page.tsx`、`app/teacher/knowledge/page.tsx` | 导向同Brainform/Studyform原role/groupcontext，必要query适配                               | 不新建backendroute，不绕guard                      |
| 同一UI writer：i18n                 | `frontend/lib/i18n.ts`                                                                                                                                                                                                      | Files→RAG、Workspace→Studyform品牌名与原说明help搬移                                      | 不恢复旧100k/teacherreview文案，不翻译用户资料     |
| 同一UI writer：tests                | 下表现有tests，优先原用例就地更新/扩展                                                                                                                                                                                      | 更新被用户取代的sidebar/tooltip即时出现断言，保留功能负断言                               | 不删除CAS/scope/privacy/charge/idempotency测试求绿 |
| root                                | `docs/contracts/MAYAFORM_FINAL_UI_POLISH_SPEC.md`及v1.4最后UIboundary、`docs/PROJECT.md`、必要README/manual                                                                                                                 | 收录新用户override、精确href表、前置功能验收事实、UI实施/未验记录                         | 不把只读spec/test-source当真实成功                 |
| independent Sol                     | 同版本完整diff、冻结SHA、focused运行及可见证据                                                                                                                                                                              | 无repo写入；报告PASS/发现/未测                                                            | 不参与共同写i18n/BF/tooltip，不操纵共享Tab         |

### K2. 前置功能gate

- [ ] root已完成用户所指全部功能测试，认为实现齐全，精确列出覆盖目标/版本/仍未测范围；不是只看555 unit绿色。
- [ ] 当前Provider、合成Brainform生成/更新、Team/Assessment自然语言完整链、Teacher允许Public查询与Private拒绝等本次功能目标分别有当前证据；具体范围沿root当前验收矩阵，不因UI增加无关额外Provider调用。
- [ ] 底层实际调用账本、unknown不重发、完整内容/accepted结果、scope/privacy/grants等所需功能检查已收口。
- [ ] 实际功能冻结版本与UIwriter读到版本一致；root告知开始UI后才改；设计产物先可继续整理，不触发实现。

### K3. 可复现deterministic验收方案（实施后）

| 场景                           | 复现方法与应观察结果                                                                                                                                                             | 现有测试承载                                                                       |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 五nav/TeacherStudent/group解析 | fixture覆盖student/teacher/teacher-inside-group/两组/迟到Agent lookup；main目的地序正，Studyform同真实group，Teacher Home与Roster既定进入保留；sidebar无New/独立Knowledge/Voices | `pw3-e-shell.test.tsx`、`shell-group-scope.test.tsx`                               |
| RAG New与三列                  | render真实Brainform；无visibleBrainformtitle/eyebrow；RAG/Knowledge/Memory同时见；New只在RAGheader；New不创建Knowledge/Chat                                                      | `brainform-workspace.test.tsx`                                                     |
| MD草稿与no side effect         | import合成Unicode .md，API create/replace/send计数0；Save后准确一次；非法UTF-8/非md留原draft；late import不盖新draft                                                             | `brainform-workspace.test.tsx`、`knowledge-editor.test.tsx`                        |
| 已有edit/CAS/rename            | 先download servercontent，改名只rename且replace/index/generate0；正文save使用正确document/hash/revision；conflict仍保留稿；第二次明确save新intent                                | `brainform-workspace.test.tsx`、`knowledge-library.test.tsx`                       |
| View/download一致              | eye展示现有safeReportMarkdown；download取同IDauthoritative content/filename；不调用LLM；read-only无pencil/hide/reindex；canonical Knowledge能edit者保留pencil                    | 同上+`report-markdown.test.tsx`                                                    |
| 旧route/guide                  | legacy groupKnowledge/voices进入正确role/course/group的BF/Studyform；group2不落group1；TeacherReadOnly不出现edit；HomeGuide/AgentRAG/ManageVoices深链继续                        | 新最小route测试+原Home/Agentflow tests                                             |
| Studyform嵌Voice               | GroupWorkspace render原Agents后VoiceLibrary；mount仅GETvoiceProfiles，无enroll/preview/confirm；原consent和idempotencyflow仍有效                                                 | `home-profile.test.tsx`、原workspace/voice tests                                   |
| Chat New迁移                   | AppShell无New；Chat自身原PageAction可开三个chooser；原busydisabled；history/Team下可New；新session不清activeattempt                                                              | `workspace.test.tsx`、`team-chat.test.tsx`、`brainform-memory-assessment.test.tsx` |
| hover1500                      | fakeTimers：pointerover1499ms无tooltip/tooltipdescribedby；第1500ms显示；同target move不重计；A1490ms→B后A不显示、B独立1500ms                                                    | `ui-guide-tooltip.test.tsx`                                                        |
| timer取消                      | pending时分别pointerleave/navigation/DOMremove/guidechange/scroll/blur/visibility/Escape/cleanup，再advance5000ms无tooltip；active同样清理                                       | 同上原清理用例保留+pending分支                                                     |
| keyboard/touch                 | 无advanceTimers，Tabfocus即时help；mousepending转keyboard即时且取消旧timer；touchpin/再次tap/外tap关闭；原descriptionIDsrestore                                                  | 同上现有keyboard/touch用例                                                         |
| globalhelp盘点                 | nativeDOM title逐例迁guide；所有说明同text没有重叠nativepopup；statickeylocale/安全动态内容正确                                                                                  | 同上+原组件tests                                                                   |
| 不回退Components               | TeacherDashboard保留精确disclosure链接，无Components/Key/Check/modes/四配置API调用                                                                                               | `workspace.test.tsx`原负断言                                                       |

修改既有断言时明记被用户替代：`retains registered sidebar actions for Brainform and General Chats` → 无sidebarNew但对应block/PageAction可达；即时pointerhelp →1499/1500边界。原CAS、readOnly、scope、privacy、request-count断言继续。不要把旧库“conflict清编辑”测试机械保留到新的BF流而破坏保留draft，应按v1.4权威规则更新同一行为正反例。

按改动跑全frontend tests/types/lint/Prettier；仍只前端与文档时不为此重跑无关Provider或改backendcontracts。如确需backend改动，先报告scope改变并按AGENTS相应gate，不以polish名义越过功能冻结。

### K4. 功能gate后实际Browser验收，不由本次subagent执行

用主窗口已确认隔离的安全新会话/fixture，桌面与375/390/768小屏实见：三列/纵排、RAGNew位置、title/eyebrow消失、Knowledgepencil、StudyformAgents下Voices、Chats自身New可开三kind；所有tooltip停留不足1.5s无提示、满1.5s出、moving/out/scroll/nav不留ghost，keyboard即时/touch可达。截图只用合成资料，不读旧Privatechat。

界面打开/hover/focus/GETdownload是否零收费，以实际账本或测试API spy分类验证；预先隔离必要保存/生成的已授权行为，不能因“验UI”再自动跑一套Provider链。新UI验收结果必须区分deterministic、source、实际desktop/mobile与Provider。

根窗口接到此文件可继续功能验收；**不能因本文完整就开始UI**。达到用户门槛并完成具体href/格式承载方案后，root安排单UIwriter执行，独立Sol同版复核。没有待用户确认的Studyform/Workform命名问题；当前实施仍未开始。
