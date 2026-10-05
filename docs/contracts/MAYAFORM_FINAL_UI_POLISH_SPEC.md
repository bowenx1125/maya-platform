# MayaForm Final UI Polish Spec

最新执行以 [v2覆盖规范](MAYAFORM_FINAL_UI_POLISH_SPEC_V2.md) 为准：用户已批准现在实施 UI；所有提示即时显示，取消1500ms等待。以下保留原始设计观察，不覆盖新决定。

只读规范，2026-10-05；基线 `feat/mayaform-v14` / `d170a96b98a6e8ecaedc0959a86c386a3725e624`。供主工程窗口执行，本文未修改仓库、提交、重构、构建、启动服务或调用 Provider。

## 适用范围与证据

本规范首先服从用户 2026-10-05 最新决定：**融合并保留同事 MayaForm UI 成果；不自行增加界面东西；删除 Components 所有用户可见 UI，配置全部由维护层管理。**其次服从 `AGENTS.md`、`docs/PROJECT.md`、`docs/contracts/MAYAFORM_V14_BRAINFORM_ASSESSMENT.md` 最后的 Chats UI boundary，以及后续 Tool/resource contract 的 Public/Student/Teacher 权限规则。

优先级：P0 = 最新明确产品边界或阻断；P1 = 后续可选的一致性与可用性提案；P2 = 后续有条件优化，若会扩大改动或改流程则暂缓。P0 不等于所有问题均是紧急安全漏洞。

证据标记：

- **实见**：尝试新建 hidden In-app Browser session ID 2 的 Tab，通过公开 cua API 在 localhost:8080 导航/查看；桌面截图为1280×720。工具返回Tab ID 1，但根窗口后续观察到导航串扰，**浏览器会话隔离未确认，已停止全部browser操作**。此前可见界面仍是实际观察；不能将导航差异、焦点丢失、disclosure路由变化归因代码缺陷。
- **source**：已读取当前源代码，指出确切选择器/位置；不把 CSS 推断当成浏览器缺陷。
- **test-source**：读取现有断言，仅说明现有保护，不代表本轮运行通过。
- **未实测**：缺少本轮实际可见验证，应由主工程窗口补验。

本轮安全实见：`/` 学院登录稳定画面与一次 Tab 焦点；`/teacher` Welcome、Guide、Components、个人/课程 Agent tiles、Profile；`/teacher/roster` Members/Groups；一个合成 Agent 的 `/teacher/agents/...` 工作台；`/teacher/knowledge` 三栏、短暂 Loading、安全的已有 Knowledge generation failure、合成 RAG 查看与未修改编辑；`/teacher/chat` 的 New chooser、Team 空白表单、Maya Team 无可用条目空状态。

浏览器 GET Chats 会自动恢复浏览器持有的旧选中记录。本轮随即打开 New chooser，不再读取、摘录或保存其旧历史，旧内容不用于本规范。未发送 Chat；未进入 Memory；未点击 Regenerate/Save/Delete/Share/Check/Provider确认；未改身份、账号、课程、密码、头像、API Key 或 Provider Mode。

移动端 viewport 能力为 browser 级，未确认与主工程窗口完全隔离，因此**没有调整 viewport**；没有关闭可能共享的Tab。学生正式视图、真正的 Team 消息、账号/课程切换、Graph、IME、200%缩放、屏幕阅读器、系统 reduced-motion、真实手机软键盘均未实测。截图证据保留在本轮 cua tool 可见输出中，没有导出含私密历史的图片。不能将本规范标成这些范围的视觉验收。

实际使用的技能：`ui-ux-pro-max/SKILL.md`、`references/quick-reference.md`、`references/pro-rules.md`；检索 focus not obscured、touch target size、icon button accessible label，核对 Web 与 native 单位区别。Next.js stack 查询返回 Server Actions 架构建议，与只做 polish 的范围不符，**不采纳**。`web-design-guidelines/SKILL.md` 要求的最新官方规则已读：<https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md>。仅采纳与焦点、语义、长文本、可见错误和 reduced-motion 有关的规则，不借通用指南改变现有 API/路由/授权。

本文 A–K 中除 Components 明确删除项外，所有建议均是待用户后续选定的工程提案，不能据本Spec自动修改外观、删现有Published/Role等标签或添加新界面。

## A. 设计原则

1. **保留学院与暖纸成果。** 登录学院插画、四位人物、原品牌双环、Home 欢迎区/金色分隔/Guide、侧栏结构、现有 Avatar、已有视觉动画是本轮基底。不能另做视觉主题、重画同事页面、引入图标包或组件库。
2. **删减先于添加。** 一个内容区用一种分隔方式：留白、浅底、细分隔线、外边框择一为主；避免外大卡、内卡、标题底线、行框同时叠加。修整现有 class，不建立新 Card/Panel/Badge/Toolbar 系统。
3. **沿已有左边线排版。** AppShell 的 main gutter、Home 左对齐、页面已有内容布局保持。统一间距与文字层级；不因每页不同重新设计导航。
4. **业务动作不改语义。** PageAction 继续页面里的 New/Back/Done；Brainform、Chats 保留既有侧栏 New 例外。普通提交与风险动作可保留短文字；重复行级 edit/view/download/enter 使用已有 SVG。不能为了全部图标化降低理解。
5. **信息状态自然呈现。** 真实 loading/失败短句保留。Assessment 只通过普通 Chat 自然语言，后台 state 不变成卡片、dashboard、进度面板或 Pause/Continue/Abandon/Restart 按钮组。
6. **隐私和权限由真实资源决定。** 减边框不隐藏 Private/Public 意义；Teacher Tools 不新增绑定面板。Teacher 查询仅允许范围的 Public 证据；任何 UI 不能暗示教师可以看 Private 数量、内容或 Memory。
7. **不以设计掩盖真实失败。** 错误保持 safe code 对应的用户解释与既有恢复动作，不自动重试；unknown 不伪装未发送。没有数据与没有权限是不同语义，沿用现有提示。

## B. Tokens、间距、圆角、字体、图标

现有主 token 源为 `frontend/components/workspace-appearance.module.css:.appearance`。`frontend/app/globals.css: :root` 的登录/品牌 token 继续保留；`WorkspaceAppearance` 只包已登录 workspace，这是同事已有的边界。不要把登录重新染成 workspace，也不要全局清洗所有历史 CSS。

| 项目        | 后续提案目标，复用现有                                                                                                                                                                                                                                                                                                                    | 依据/优先级/功能影响                        |
| ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| 颜色        | workspace 用 `--paper:#f6f5f2`、`--surface/--panel:#fdfaf3`、`--surface-subtle:#f7f6f3`、`--surface-hover:#eeece6`、`--ink:#282722`、`--muted:#6b685f`、`--line:#e4e1d9`、`--accent:#76591f`、`--accent-fill:#d3a74a`、`--accent-soft:#f6ecd3`。仅将本轮触及的 Brainform/Chat 硬编码近似色替换为已有 token。品牌紫/金、学院插画原色保留。 | source；P1；仅显示，不改状态和主题。        |
| 间距        | 大区间用现有 `--workspace-gap` 桌面32/窄屏24；区内用 `--section-content-gap` 24，表单字段16，短信息8，图标间8。局部当前20/14/3不全部机械替换，只处理同类项差异。                                                                                                                                                                          | source+实见；P1；不改变 DOM/流程。          |
| 页面 gutter | `app-shell.module.css:.main` 现有48px顶部、clamp(24px,4vw,64px)左右；900/480断点现有24/16px左右保持。图文段落不无限拉宽。                                                                                                                                                                                                                 | source；P1，移动未实测；不新增布局。        |
| 圆角        | 已有外区20px、内区16/14px、控件10px为主；Chat 浮动 composer22px及 send圆形保留。减少圆角盒数量比把全部圆角改成一个值更有效。                                                                                                                                                                                                              | source+实见；P1；无功能影响。               |
| 字体        | UI 用 `--font-ui`；标题/学院用现有 `--display-serif`。Brainform `.pageHeader h1/.panelHeader h2/.sectionHeading h2` 当前 Georgia/Times New Roman 与 Home/Profile 不同，改为 `var(--display-serif)`，不新增字体文件。                                                                                                                      | source+实见；P1；仅排版。                   |
| 字号        | 正文/输入16px，行名称16px/600，按钮14px/500，辅助13–14px，日期/少量计数12px，section heading20–22px/serif，页面标题沿现有clamp。避免标题大小和字重都升高。已有中文自然换行，不加 blanket nowrap。                                                                                                                                         | source+实见；P1；不改文字内容。             |
| 行距        | 阅读1.6–1.7，UI1.45–1.5，短标题1.2–1.35。数值/日期沿用 tabular-nums。长文件名/用户内容 `min-width:0`+`overflow-wrap:anywhere`。                                                                                                                                                                                                           | source；P1；不截断数据。                    |
| 图标        | 继续 `quiet-icons.tsx` 和 `workspace-icon.tsx` 的24 viewBox outline；行级16px、导航20px、PageAction16px。相邻常用动作统一1.75 stroke；保留 brand mark。Close/Check 当前2、nav1.65是source差异，P2仅在同层实见不协调时改，不全库重写。                                                                                                     | source；P2；无新增库/语义。                 |
| hit area    | 桌面常用图标至少现有28px；手指操作目标44×44px为本产品舒适度目标。**Web WCAG AA 最低24 CSS px或合法间距例外，不把44px称作Web强制标准。** `icon-action`28px、Brainform44px、Send40px存在差异，可在粗指针media仅扩大hit区。                                                                                                                  | source；P1移动补验；不添加文字按钮。        |
| hover/focus | 背景/颜色160ms，focus-visible沿现有 `--accent` 2–3px+2–3px offset；不改变元素外部尺寸。保留 reduced-motion。                                                                                                                                                                                                                              | source+登录Tab实见；P1；点击/键盘行为不变。 |

不新设一套平行 token；`workspace-theme.module.css` 管结构，`workspace-appearance.module.css` 管已登录主题，业务模块只留必要布局。删掉本次触及 selector 的重复/近似声明；不顺手重构整份3409行 globals。

## C. 全局组件与通用状态

### C1 — P0：彻底移除用户可见 Components

**现状/依据：实见 + source。** Teacher Home 下方可见 Components、Set API Key、Check、Embedding/Debate LLM/TTS/Voice/Maya Report mode及Ready。`teacher-workspace.tsx` 导入并render `DemoCompositionBadge`；`demo-composition.tsx` 同时拉取配置、提供变更/Check/credential dialog。

**为什么：** 用户明确决定这些由维护层管理；仅藏标题或用CSS隐藏仍留下用户交互与读取配置。

**执行：** 从 Teacher Home 移除 import/render；无剩余调用时删除 `demo-composition.tsx` 与专用 `.module.css`，清理专有UI测试和仅服务于该component的import/fixture。不能将其换成齿轮、collapse、setting页面、状态条、API Key图标或“高级设置”入口。profile里的avatar/password是已有账号功能，继续保留。

**功能影响：** 用户不再设置API Key、切Provider Mode、检查组件；这是最新授权的功能入口删除。**底层 API、服务端权限、env 配置、provider注册、账本、运行与必要披露授权不删。** TeacherDashboard mount 不再调用 `providerSettings/updateProviderSettings/checkProvider/demoStatus`（若 demoStatus 还在 SessionProvider 为别的用途保留，验证指明准确来源，不能伪称全站零请求）。不把删除旧UI测试的数量说成全套测试无变化。

### C2 — P1：现有区块去掉一层边框

**现状/依据：实见 Home/Accounts/Agent/BF + source。** `.section-card`之外有 `.list-row/.agent-tile/.persona/.avatar/.fieldsets`，边框重复。

**执行：** 页面级 section 的原边框可保留；同一区内列表行优先透明border/浅底或只行分隔。例外：可编辑输入边界、选择态、dialogs、Chat composer必须清楚。范围精确到页面 class，不全局删掉 `.section-card` 以免Debate/Voice受损。

**功能影响：** CSS，不改节点/入口/权限。不能把分隔全部抹掉而使行级动作与对象对应关系不明。

### C3 — P1：已有 Loading/Empty/Error 保持所在位置

**现状/依据：实见 BF短暂Loading、Agent Loading avatar、MayaTeam empty、Knowledge安全failure；source `ui.tsx` 已有role=status/alert与本地化。**

**执行：** `.loading-card/.empty-card/.notice` 若已经放在 `.section-card`内，减掉内border/background或大min-height，保留短文和既有动作；首次整页loading可保持原academy-loader。更新同一列表时沿用 roster `load(false)` 的已保留内容，不整页替换。`.notice`允许窄屏换行，按钮保持可聚焦，不用新的toast代替。

**功能影响：** 不改等待/错误语义，不新建恢复动作、不触发Provider。生成旧成品仍可见；无旧成品不伪造可用。

### C4 — P1：同类动作保持一致

**现状/依据：source `page-action.tsx/.module.css`、`workspace-actions.tsx` 与 `teacher-agent-detail.module.css:.actions .action`。** PageAction已解决 grid stretch；Agent detail旧action末尾将min-height设为0，与全局28/44px图标不一致。

**执行：** 使用现有 PageAction 规则的 `justify-self:start/align-self:flex-start`；单个现有primary action不能因grid stretch铺满整页。现有row action hit area在粗指针上保持44px。不新写Toolbar。

**功能影响：** 表单归属、disabled路由按钮、unsaved guard保持；Brainform/Chats sidebar New不迁移。

## D. 页面：首页、登录、Agent、Profile

### D1 — P1：Home Agent tiles保留成果，减掉拥挤

**现状/依据：实见 `/teacher`。** `.agent-tile-grid`在桌面显示多列，个人Agent的较长visibility说明与姓名挤在窄tile里；有两行英文名字。课程tile已是同事原紧凑展现。

**执行文件：** `globals.css:.agent-tile-grid/.agent-tile/.agent-tile-name/.agent-tile-group/.agent-tile-author`、`teacher-workspace.tsx:PersonalAgentTile/PublishedAgentTile`。

**建议：** 保留原tile结构、排列、author、version→X interaction；减少tile innerborder视觉强度。仅个人tile的现有布局允许更宽自适应列或局部padding减少，让完整visibility说明能自然换行；不将私密/授权说明删除，不统一强迫单行。course tiles如当前舒适则不改列数。长名仍可访问完整名称，不改数据/排序。

**功能影响：** 纯CSS，版本删除规则与权限保持。不添加搜索/筛选/统计卡。

### D2 — P1：Agent工作台primary action不铺满整页

**现状/依据：实见合成Agent。** `teacher-workspace.tsx`已发布Agent显示全宽黄色“Create a new draft”，之后Knowledge Sets链接又独占一行，视觉权重大于AGENT.md内容。

**执行：** 在原位置让该existing action `justify-self:start; width:fit-content; max-width:100%`；文字/行为保持；关联Knowledge链接同样使用现有短action字号/hover。必要时用当前容器排版，而不添加新actionbar或重新分组流程。

**功能影响：** 创建草稿的API/流程不变；新按钮不增加。

### D3 — P1：Agent阅读层减内框

**现状/依据：实见 + `teacher-agent-detail.module.css:.persona/.avatar/.file/.fileActions/.fileBody/.versions`。** AGENT.md外卡与内灰卡、Profile外卡与avatar框并列，RAG文件再有header/body分隔。

**执行：** AGENT.md内阅读层取消边框/box background，保留16px或减少为0的padding；头像canvas继续有必要高度但不用第二层装饰框；RAG文件仅保留必要分隔。`.personaCard/.profile min-height:650px`是source，桌面是否需要650取决于原3D展示；不得为了统一将头像改成静态图或删除AvatarCanvas。窄屏min-height只在补验确有大量空白后减。

**功能影响：** Avatar/voice/RAG/download/版本数据原样；不改Agent.md内容或其hidden author rules。

### D4 — P2：Profile维持同事两半一张纸

**依据：实见 + `globals.css:.account-settings-grid/.profile-panel/.password-panel/.avatar-picker`。** 目前已用金线分两栏，无两套内卡，是保留范例；不要重做。

**建议：** 保持Avatar八枚、自动保存与Password独立Save；label字号与输入间距对齐B；错误附近、saving/saved状态沿现有；若列宽变化，移动现有金线到纵向分隔而非添加卡片。没有改变头像和密码来验收。

**功能影响：** 账号行为保持。隐藏API Key区不连带移除Profile。

### D5 — P2：登录学院画面保留

**依据：实见 `/` 稳定截图 + 一次Tab可见紫色focus；`app/page.tsx`、`session-provider.tsx:LoginForm`、`globals.css:academy-*`。** 不做新landing、换配色、删人物、替换金色细线或把Demo身份改成新chooser。

**建议：** 只修实测出现的mobile溢出/焦点遮挡；当前desktop无需重画。username/password已有autocomplete与label，不可禁止paste；`name`缺少是source小项，若在同文件已获编辑范围可补语义属性，P2，不改登录逻辑或输入值。loading intro遵守既有reduce-motion实现，未实测的分支先验证。

## E. Brainform

**产品保留：** 一个页面直接见RAG/Knowledge/Memory；left New总是只新增Markdown RAG；file name直接edit、eye查看；Knowledge canonical同对象；title行内rename；Graph read-only；Memory进入正确Chat且单次自动消息；不加Ready/Reviewed/Published/Outdated标签、Knowledge New或资产分类页。

### E1 — P1：降低标题与三块容器的边框数量

**依据：实见 + `brainform-workspace.module.css:.pageHeader/.section/.sectionHeading/.count`。** 现状标题像第四张卡，三栏各有outline+标题底线+圆形计数。

**建议：** 保持三栏grid：`.pageHeader`去掉border/shadow/填色/额外圆角，仅保留标题与已有coursePicker；`.section`保留一层轻底或outline，`.sectionHeading`分隔弱化。count留数值但去掉圆圈背景/边框，让其自然与heading对齐，不能把Memory数量改成教师能看Private统计。intro文字保持原词，视觉13–14px/ muted。不把三个区改成按钮落地卡。

**功能影响：** CSS与已有count表示，数据请求、权限、内容始终可见不变。

### E2 — P1：长文件名与三个图标不争一条窄线

**依据：实见合成RAG名三行；source `.row/.rowCopy/.titleButton/.actions`。** 当前宽度被常驻44px眼/笔占用。

**建议：** 列宽不足时rowCopy占完整首行、原actions在同row第二行右对齐；桌面空间足时原一行保留。`.row`的text child `min-width:0`，长文件名自然换行，名称16px/600，辅助13px；不隐藏名称、不添加more菜单，edit/view仍常驻。actions gap由3对齐8，但应同时检查实际可用列宽。

**功能影响：** 同一个文件与按钮，点击映射不改；不截断原文件名/Markdown。

### E3 — P1：View/Edit显示后读者能找到现有区域

**依据：实见；查看/编辑追加于三块下方，首屏底部只露标题/Filename，正文更下方。source `brainform-workspace.tsx` editorPanel。**

**建议：** 继续同页editorPanel，不改dialog或新route；打开后将焦点移到现有panel heading/字段并让其出现在视口，Close后回原触发按钮。实施前核对已有焦点逻辑避免重复抢焦点；不对加载中/自动刷新focus。Panel title不再重复使用厚外框，正文读宽约65–75ch，表格/code自己的overflow容器保留。

**功能影响：** 小范围focus/scroll可用性修正，不提交资料，不增点击、不丢稿；Save/Close和既有防丢机制保留。

### E4 — P1：loading/error沿原行，语义完整

**依据：实见Knowledge已有generation failure；source `.rowStatus/.generationNote`、role=alert/status。** 失败短句目前不是badge，这是正确方向。

**建议：** 保留旧文档和该行短说明；realGenerating只spinner+既有文案；失败的可用恢复入口沿本来授权，不用大警告卡包整列。不能将disabled regenerate视觉误改成enabled。现有disabled无配置按钮不伪造可用tooltip。raw safe code的本地化在已有i18n路径补时，仅用准确已知原因，不新增每条approve动作。

**功能影响：** 授权与收费恢复不改。d170已修复旧100k导入/teacherreview文字，**不是本轮未修finding**。

### E5 — P2：Graph只做阅读表现

**依据：source `brainform-workspace.tsx:KnowledgeMarkdown/parseKnowledgeGraph`、CSS `.graphFigure/.graphScroll/.graphSvg`，未实测。** SVG有role=img/aria-labelledby；当前min-width560px用于局部横向scroll。

**建议：** 沿现有outline/字体tokens降低graph额外框；手机仅graph局部可横滑，不让全页overflow。保留安全原文/failure fallback，不新增drag/zoom/图编辑toolbar、隐藏推理展示或新的Graph管理页。

## F. Chats

**强制边界：** Agent、Team、Maya Team用已存在的General Chat、history、messages、composer、error；测评开始/作答/查询/暂停/继续/放弃/放弃重做全自然语言。暂停仍可向普通composer输入，不先resume才查记录。不得加状态卡、专用input或控制按钮组。

### F1 — P1：保留浮动composer，修现有长输入可读性

**依据：source `agent-chat.module.css:344-360`。** textarea被28px height/max-height、overflow:hidden、nowrap限制；本轮没有输入长文，不能声称已实测丢字。

**建议：** 不改浮动圆角shell、独立Send、原位置；让原textarea长文自然换行并有有限的可滚动高度，空输入保持轻薄。同样在现有Send可用态、Enter/Shift+Enter/IME分支验证，不新增editor/专用Assessment输入。若坚持原单行设计，至少保证横向caret可见和粘贴多行可读；不静默删换行。

**功能影响：** 仅呈现草稿；请求内容、Enter行为、恢复文本/id、私密history不变。该项需主窗口安全新Chat补验后定稿。

### F2 — P1：Chat外壳轻化，历史行保护保留

**依据：source `.layout/.sidebar/.historyRow/.conversation/.messages/.composer`；本轮新chooser实见。**

**建议：** 只减少外layout shadow或第二层outline，不拆General Chat布局；sidebar轻底+一条divider、message正文16px/1.7、user bubble原浅金。history Date/Delete互斥、hover/focus-visible、hover:none可触达已在source实现，不能改为hover-only，不做常驻Delete。无需读取旧私密history来测样式；用新安全fixture/新测试conversation。

**功能影响：** 历史选中和删除语义、fresh New与回包隔离保持。

### F3 — P1：tool/state失败复用普通消息

**依据：test-source `brainform-memory-assessment.test.tsx`已有pause后普通composer与不渲染state codes/buttons断言；本轮不运行Provider。**

**建议：** 保留已存在localized message/error role；若有unsafe/raw内部state/UUID进浏览器，按既有投影修，不引入debug badge。unknown recovery/status check属于已存在发送恢复，不变成Assessment Continue按钮。Maya Team保持普通消息呈现，不创建Dashboard、课程进度条或会员个人卡。

**功能影响：** 后台attempt/privacy/dedup不改；不多一个收费动作。

## G. Team 与 Maya Team

### G1 — P1：只减现有chooser/表单嵌套框

**依据：实见 New三入口、Team表单 + source `.entryFlow/.entryOptions/.entryOption/.teamForm/fieldset`。** 外圆角card内部又有三张卡；Team表单visibility/members/sharedknowledge各fieldset有大框。

**建议：** 保留New现有三入口及原说明，减少entryOption边框并沿现有hover浅底；原fieldset保留语义/legend，改成无框分组+间距或一条分隔。Team name/Members/Leader/Shared Knowledge的已有控件、disabled逻辑与privacy说明都保留。不要新绘Team tab、stepper、instruction文件、拖拽选成员或模态向导。

**功能影响：** 选成员、唯一Leader、共享Knowledge真实ID与创建/编辑流程不变。

### G2 — P1：Back/Cancel与primary动作样式一致

**依据：实见 Team/MayaTeam＋source `team-entry-flow.tsx`不同inline-button/primary-button/PageAction使用。**

**建议：** 在现有位置用现有PageAction/已存在primary-action外观对齐；不用按钮名字推测功能改变。Create Team与Start Chat是实质提交，短文字保留，不改无名图标。Cancel/Back保持原stage，焦点返回触发项；无dialog则不新增focus trap。

**功能影响：** 不改最少选择条件、visibility、API时机，不提交当前空表单。

### G3 — P2：MayaTeam empty保持简短

**依据：实见“No published course Teams are available.”** 当前空状态位于原entryFlow内；保留一个短句+原Back/Cancel，不再套EmptyCard，不为无数据添加Create/Refresh/Teacher入口。不将“no published teams”误改成“没有课程/你没有权限”。已配置后的普通TeamChat视觉只source-reviewed，主窗口补安全新会话验证。

## H. Teacher Workspace 与维护边界

### H1 — P1：Accounts行紧凑但保留对象对应

**依据：实见Members，每人独立大card与外section两层；source `workspace-theme.module.css:.surface :global(.account-row/.list-row)`、`roster-workspace.tsx`。**

**建议：** 保留原Members/Groups和已有actions；row改轻底/单分隔、padding16，avatar/姓名/状态/组名按既有DOM清楚排列。状态active/deactivated有实际账号语义可保留，不能套用Brainform无资产标签禁令删除。Edit/Restore/Reset是不同风险动作不全部换无上下文X；已有Enter箭头可对齐44px hit区，不改成新join流程。

**功能影响：** CourseTeacher进入Group可能触发join API，**本轮未点击**；保留真实membership、teacher role、read/edit。不能因视觉缩短移除密码重置或restore等既定功能。

### H2 — P0：Components移除不能侵蚀披露与授权

**依据：最新用户指令 + source。** Provider配置维护与必要外发披露是两件事。删除Components所有用户UI，不删除已有 `provider-data-call-*` / `provider-chat-approvals` 中合法授权用途的条款；也不把它们扩成Teacher审批学生每条message或内容Review。

老师内容无需Review/Confirm才生成/使用；授权披露确实缺失时沿原最少合法恢复。不得给工具添加dashboard、binding UI或Teacher Private统计。工具维护仅在已有维护层进行，不为本轮新增admin页面。

### H3 — P1：账号/课程切换视觉稳定性只补验

**依据：source `AppShell` agentScope、`AccountSettings key(user.id:identityGeneration)`、Brainform key/scope fencing、`chat-identity-isolation.test.tsx`。未实测切账号/切课程。**

**建议：** 延用当前scope隔离；切换时当前上下文变了立即撤掉旧姓名/数据/selection，等待新合法结果，main/已有selector尺寸稳定。不得动画把旧Private内容滑到新账号里，也不新加身份badge/课程header。用独立测试fixture验证延迟回包不覆盖；shared live会话不得靠logout来验证。

**功能影响：** 不改session/ACL/列表含义。视觉稳定目标不压过数据隔离。

## I. 移动端、键盘与Accessibility

本节全部未完成真实mobile验收；源码仅能说明已有断点。不得标“375px通过”。

| 检查/修整                  | 精确位置                                                                        | 优先级与依据                   | 功能影响                                                                       |
| -------------------------- | ------------------------------------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------ |
| 320/375/390/768宽度和横屏  | AppShell 900/480、BF900/640、Chat680、Agent780、Profile600                      | P1；source断点存在，未实测     | 不重新造移动导航；现有grid自然堆叠。                                           |
| 首屏导航高度               | `.sidebar/.navigation/.account`                                                 | P1；source小屏2列nav+account   | 若实测占满屏，先减gap/padding，保留links/logout；不新增drawer/hamburger。      |
| 手机长名+actions           | BF `.row/.actions`、Team `.entryMember`、Accounts `.account-row`                | P1；source+desktop长名实见     | 原行自然wrap，控件不得截出屏。                                                 |
| mobile输入字体             | Chat `#chat-message`特异性高于`.composer textarea`；Profile input               | P1；source，未实测             | 保持至少16px手机输入避免浏览器自动zoom，不能disable用户zoom。                  |
| 软键盘与composer           | Chat `.conversation height:max(600px,75dvh)`、`.composer`、AppShell `.chatMain` | P1；source潜在高度风险，未实测 | 安全区/键盘下Send与caret可见，最后消息可滚至可见；不改Chat成固定bottom新架构。 |
| 图标触达                   | globals `.icon-action`28；BF44；send40；Agent `.actions .action`minheight0      | P1；source                     | 粗指针沿已有媒体扩大target44px，图形仍16–20；不称28px天然AA失败。              |
| Focus环不裁切              | `.layout overflow:hidden`、BF/Agent各action、fieldset radio                     | P1；source+登录Tab实见         | 现有焦点环保持，clip容器边缘实际验证；不用outline:none掩盖。                   |
| 打开/关闭原编辑区域的focus | BF editorPanel与Teamstage                                                       | P1；BF首屏实见+source          | 移到原heading/field；结束回触发对象；不新modal。                               |
| 正文长链接/code/table      | `ReportMarkdown`、BF graphScroll/graphSvg、Chat sources                         | P1；source                     | 局部overflow，页面无横向溢出；不截内容。                                       |
| Reduced-motion             | appearance/theme/AppShell/Chat已存在规则，academy实现需补实测                   | P1；source                     | 不新animation；用户选择reduce时无lift/长intro/闪烁。                           |
| 表单label/error            | Login/Account/Team已有label、ui ErrorNotice role=alert                          | P2；source                     | 原form failed retain drafts/inline定位；不给每个表单新error dashboard。        |
| 图标可访问名字             | BFaria-label与SVGaria-hidden、WorkspaceIconfocusable=false                      | P1回归；source+AX实见          | 保留names与disabled；同名action加入对象名，不能把tooltip当唯一标签。           |
| 页面main语义               | AppShell已有 `main#workspace-content tabindex=-1`，未见skip link                | P2 source检查项                | 优先复用现有main route focus，不在本轮新增导航入口。                           |

必须以实际配色测正文4.5:1/大字及有意义控件3:1；本轮未测contrast，不声称muted不合格。disabled不只靠颜色，语义disabled继续；Private/Public/Leader不只靠颜色。键盘需Tab/ShiftTab/Enter/Space/Escape；非hover设备可见必要动作。主工程窗口可用安全本地fixture或已确认隔离的Tab测，不读旧private历史。

## J. 禁止的反模式

- 不将移除Components改成隐藏settings/gear/collapse或新admin入口，不删除backend/env/API/注册来迎合外观。
- 不另建组件系统、token主题、图标库，不对同事学院图重画。
- 不把Brainform三块变成三张进入分类的按钮；不新增Knowledge New/AddQuestion/Memory编辑器。
- 不将Graph做拖拽/布局编辑，不显示模型隐藏推理。
- 不恢复Ready/Reviewed/Outdated/Published资产badge；真实账号active、已有privacy/版本语义另论。
- 不给Assessment造状态card/输入/进度面板/控制按钮，不将MayaTeam变另一套聊天layout。
- 不靠改名Maya/Jade等推断权限/模式，不注册Teacher Private读取或统计。
- 不因“少按钮”删除既定下载/解绑/删除兼容入口或把常用edit/view收进more。
- 不把所有短提交文字换无名图标；SVG需accessible name，decorative SVG隐藏于AX。
- 不将手机click强制成hover；不去掉focus-ring；不禁zoom/粘贴。
- 不用固定字数、hidden truncation、tiny字体/大min-height压出“干净”。
- 不改Provider请求/自动重试/unknown recovery，不以新badge声称Provider已Ready或生成完成。
- 不把本轮source review/test-source当真实浏览器/Provider/mobile验收，不重复报告d170已修旧100k/teacherreview文案。

## K. 验收Checklist与执行顺序

**本轮只执行用户明确的 Components 删除；本文其余 P1/P2 均是后续可选提案，不是当前改动要求，不自动实施。**同事现有设计优先保留。这些source/实见观察只供主窗口后续工程参考；若用户授权后再择最小CSS集，不重画整页。

### K0 — P0 Components删除独立验收

- [ ] Teacher Home DOM/AX/截图均没有Components/Set API Key/Check/五mode/Ready strip/dialog/hidden管理入口。
- [ ] 从真实TeacherDashboard mount的测试明确断言无providerSettings/updateProviderSettings/checkProvider配置UI请求；不是只测一个空替身component。
- [ ] 全repo引用搜索确认demo-composition用户组件无剩余import/render；底层平台API和backend/env/permissions/Provider ledger不变。
- [ ] Home Welcome学院人物、stats、Guide、Agent tiles、Profile保留；TeacherRoster/Agent/RAG/Brainform/Chats/Team/MayaTeam合法披露路径保留。
- [ ] 清理专有测试按删除数量如实记录；保留或补入实际Home“不显示也不取配置”的负断言。
- [ ] 同版本diff/source review+前端类型/lint/必要tests+Browser截图；前端更新需要按root既定授权/部署边界进行，不借验收触发provider。

### K1 — 后续可选P1视觉修整，本轮不实施

- [ ] 1280/1440 desktop同一页面左边线、title/action一致；没有全宽孤立primary action；现有Home不重画。
- [ ] BF三块同时直接可见；标题减壳/计数减圆框后仍清楚；长名+常驻eye/pen/refresh不互挤。
- [ ] 普通PageAction与Brainform/Chats sidebar New例外正确；未增加按钮/页面。
- [ ] 现有RAG/Knowledge View/Edit还是同对象、同页，focus/Close回原触发、unsaved防丢保留；Graph只读。
- [ ] Chat仍General Chat/floating composer/history，三kind同样；长草稿不藏caret/多行；IME和Send逻辑不变。
- [ ] Team form改边框后legend/checkbox/radio/唯一Leader/privacy作用不变；MayaTeam空状态无新的创建入口。
- [ ] Accounts行紧凑但对象与动作明确；Avatar八枚/Password表单保留。
- [ ] Loading/error为真实state，旧内容保留，ARIA status/alert不重复朗读。失败不会触发自动生成/Provider。

### K2 — 后续补验范围，当前未验收

- [ ] 320/375/390/768 portrait与landscape，safe area、软键盘、200% zoom，无全页水平overflow；只允许graph/table/code自己的局部scroll。
- [ ] keyboard Tab/ShiftTab/Enter/Space/Escape与focus-visible无遮挡；hover leave/nav/scroll/blur清tooltip，history date/X互斥且touch可达。
- [ ] reduced-motion实际开关、contrast数值、screenreadernames/role/顺序；短/长中英文名/空数据/慢数据/安全错误各一例。
- [ ] account/course切换用isolated fixture验证scope fence，不用共享Teacher cookie登出/改账户制造竞争。
- [ ] 测评pause/query/abandon在普通composer仍可送自然语句；无专用state/button/dashboard；真实Provider必须由root已有明确授权范围另验。

交付记录应分别列：只读source review、实际桌面visible evidence、deterministic tests、本轮未实测范围、真实Provider。最终标题不能写“全部UI已验收”而移动/切换/IME仍未执行。

## 同版本 Components 删除独立审计 — 2026-10-05 15:42 JST

**PASS（source + 独立focused test）；没有新增browser验收。** 基线仍d170a96；12路径与 `/private/tmp/mayaform-components-removal-source-manifest.json` 一致，manifest SHA-256 `0b8b7eaeb4c4b39777d7b46f54695a80c1b9b4619f1015f62e357eddc19f58ed`。globals/appearance/TeacherDashboard/workspace test四SHA均与实现者freeze逐项匹配，三个专有component/CSS/test文件已删除。

- Production `DemoCompositionBadge/demo-composition/demo-mode` 无剩余引用。TeacherDashboard只删一行import与一行render，Welcome人物、stats、Guide、Agent tiles、Profile和准确provider disclosure link保持。
- globals只移除demo-mode专有规则；appearance仅从共享selector移除demo-mode项，`role-pill/current-label/dirty-label/status-good`等原样保留，未重画同事UI。
- AppShell、Brainform、AgentChat、TeamEntryFlow、AccountSettings、学院、ProviderDisclosure、backend、contracts、frontend API层均无diff。原provider API方法、维护配置与权限继续存在。
- 测试删除2个component专有+3个web控制用例，增加1个实际AppShell+TeacherDashboard负断言，净减4。新用例保留exact `/teacher/provider-approvals/chats?course_id=course` disclosure入口，并断言无Components/Key/Check/modes及demoStatus/providerSettings/updateProviderSettings/checkProvider四API零调用。
- 独立运行 `frontend/tests/workspace.test.tsx`：1文件、25/25 PASS，4.62秒（15:41:49 JST）；diff whitespace检查PASS。实现者报告完整74文件555 PASS/1原skip、types/lint0 errors/4原warnings/Prettier PASS；本审计未重复完整套件，明确区分。
- README/REAL_PROVIDER_SETUP/MANUAL_VERIFICATION更新为维护层配置，ADR008显式标旧web控制为历史决定；PROJECT的部署/账本事实由根窗口提供，本审计不将其冒称独立实时Provider验证。

本切片无阻断finding。最终frontend部署后用户可见无Components与原页面保留的实际截图仍由主窗口完成；本subagent已经停止所有browser操作，不触发收费调用。其他P1/P2提案未实施。
