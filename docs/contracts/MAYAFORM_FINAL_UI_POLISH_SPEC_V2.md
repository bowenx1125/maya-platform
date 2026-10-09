# MayaForm Final UI Polish Spec v2 — 当前执行合同

2026-10-05，2026-10-09 按用户访谈更新 Chatform、Team、Brainform 发布和侧栏。本文整合用户最后确认的 UI 覆盖，替代原 v2 的冲突建议。旧 v1 仅作观察参考；真实功能验收、UI 自动化、浏览器与部署分别记录，不互相替代。

## A. 设计原则与最新覆盖

保留同事 `origin/w5/ui/06-home-academy` 的 Mayaform 首页和设计系统：暖纸、极简、SVG、空间感、少点击，不增加 dashboard、badge、设置面板或新的业务流程。Mayaform 首页保留同事设计，仅删除 Components、将原 Guide 导向新目的地，不重画首页。

老师和学生共用相同 Studyform、Brainform 页面结构。不同的是当前身份、可见资料、read/edit 等权限，不是两套布局或创建流程。Studyform 创建管理 Agent 和 Voice；普通 Team 在 Chatform 内创建；教师在 Studyform 发布 Maya Team。

主要侧栏顺序：Mayaform、Studyform、Brainform、Chatform、Live；教师另有 Debates、Accounts。Chats 改名 Chatform，Workform=Studyform。

**复用左侧栏现有 New、Back、Done，New可用时强调色点亮、不可用时dim，Back/Done仅当前需要时出现。**包括 Debates、Brainform/Knowledge、Voices、Chats、Agent 编辑页。复用现有 WorkspaceAction 注册与禁用条件；不在页面内保留重复按钮。这覆盖此前删除 sidebar New、RAG 块内 New、Chats 页面 New 的要求。唯一明确例外：Studyform 的 Voices New 单独在模块右侧；Agent New 使用左栏，Voice创建后的Back/Done仍左栏。Mayaform Voices Guide直接进入Voices新建表单，而非只到列表；打开不自动enroll/计费。

**所有提示即时呈现。**取消1500ms等待，鼠标、键盘和现有触摸路径可用。用户已要求现在推进 UI，旧“先完成真实功能闭环再实施”顺序已替代；未测真实功能仍不得宣称完成。

侧栏选中效果仅液态玻璃背景/指示层在导航项之间移动，文字始终可见，不参与退出/进入动画或共享截图层；保留 reduced-motion，不换动画库。

## B. Tokens、字体与图标

复用当前暖纸颜色、字体、spacing、radius、WorkspaceIcon/PageAction/SVG，不添加组件库或替换同事品牌。页面间相同操作沿用相同图标、尺寸、hover 与 focus-visible。符号操作有准确 aria-label；不改用户 Markdown 正文标题。

标题保持一行，解释不占第二行而在即时提示中呈现。删除 Brainform 的可见 KNOWLEDGE WORKSPACE eyebrow 和 Brainform 页面大标题及空外壳；保留三列 RAG、Knowledge、Memory 的标题、内容和必要课程选择。

## C. 全局组件与左侧操作

保留 AppShell + WorkspaceAction 的现有注册机制。New、Back、Done 按当前页面真实能力注册到左侧栏，保留加载/忙碌/未保存稿/只读权限规则，不把视觉统一解释成所有人都能创建或保存。页面内重复注册或重复操作要移除；无合法操作时不伪造可点击入口。

UiGuideTooltip 仍是唯一提示体系，支持原静态 guide key 和 owner 提供的安全纯文本说明。鼠标进入与键盘 focus 即时显示，touch 保留 tap-toggle；离开、Escape、scroll、route/identity/locale变化、卸载、blur/resize 后正确清理。保留原 aria-describedby IDs 和位置避让。不使用 native title 与 custom tooltip 双重提示，不用 LLM/额外请求生成帮助。

标题下装饰性说明迁移到该标题的提示，删除常驻重复段落与空 margin。错误、empty/loading、隐私、确认所依据的外发事实、字段约束和用户内容继续可见，不因位于标题下面而隐藏。

## D. 页面职责与路由

Mayaform 首页保留同事实现；Guide 指向 Studyform、Brainform、已有 Live/课堂目的地。不要借统一导航改写首页或移除合法 Accounts/Debates 的已有进入链。

Studyform 共用布局/组件，包含现有 Agents、Voices；教师另有 Maya Team 模块，学生没有 Team 模块。老师的个人/课程资源和学生的 group 资源由当前授权 scope 提供，老师不被迫加入 group 才能管理个人 Agent。多 group 不默认拿第一组；复用现有显式选择/Enter，没有读取就自动加入、没有来源就伪造 Voices scope。

可以复用前端 route 壳，但不能建立 Teacher 独有的第二种 Studyform。Teacher 进入 group 后仍保留实际 Teacher identity 和正确 Home/Chat/Brainform 目的地。

旧 group Knowledge/Voices 深链继续导向同一 Brainform/Studyform 的正确 role/course/group 对象，不404、不复制资料、不丢 agent_id/set_id/job_id。`/teacher/knowledge` 与 `/student/knowledge` 是真实 Brainform route，不能因名字误删。

Create AI Knowledge 与 New Agent 复用同一创建/编辑流程，不保留第二套表单。Private/Public仅使用这两个标签，不加常驻解释。创建Agent的资料选择统一叫 Brainform，可选已有 RAG 或 Knowledge，同canonical对象引用而非复制；生成的Knowledge进入Knowledge列。Knowledge更新使引用它的Agent后续读取当前版本。最新用户决定：引用该Knowledge的Agent所在Team中，active/paused正式回合提示“老师已更改当前回合的Knowledge，请重新答题”；旧作答不再用于本次评估，旧运行迟到结果不能写回，已完成回合不追溯。更新失败/仅改资产名不触发；沿General Chat自然语言，不加按钮或状态面板。

## E. Brainform 与成熟 RAG

保留 RAG/Knowledge/Memory 三列，同一结构按 read/edit 权限提供对象与操作。旧 Knowledge 的成熟 RAG 编辑、查看、下载、删除和 Markdown 能力完整融入 RAG 列，Files 改 RAG；不再保留独立重复 Knowledge 管理展示。New 使用左侧栏当前 RAG 创建动作。

RAG 完整复用原 Knowledge 的查看/编辑/下载/删除动作，删除沿现有权限及后台 hide/delete 语义，不能只做本地隐藏或物理清除原始证据。Knowledge 主列表使用资产名进入同一 canonical 对象，详情显示当前 actor 可读的引用 Agent，并允许修改；保存后这些 Agent 后续使用更新后的同一资产，不复制。Agent 页进入自身 Knowledge 的入口保留。本条替代仅按 Agent 名进入的旧决定。资产名单击改名保留。Knowledge 保留 eye/pencil/合法 regenerate 和单击改名；Memory 保留进入 Chats 的原符号。canonical 对象、Graph可视化、版本、原生成关系和一次授权 Memory 查询不改。

复用旧 MarkdownEditor/下载原语，但不盲搬其立即上传、清冲突草稿或旧 scope 状态机。Brainform 保留显式保存、CAS、stable ID、dirty draft、rename-only不生成、不计费、失败/迟到任务不清空上一版、身份/课程切换隔离。

保留已有 md/pdf/docx 导入能力，二进制走既有安全转换 API，不当 UTF-8 读取、不新装 OCR；打开/查看/hover 不生成。保留合法 hide/reindex/download 恢复入口，不新增资产质量闸门、Ready/Reviewed/Published badge。

查看、新建或编辑 RAG/Knowledge 后进入独立页面或可深链的完整主内容模式，URL明确对象/模式，左栏Back返回总览。不能在三列下方展开长editorPanel而要求向下滚动；保留当前保存CAS、草稿、权限和身份隔离，不能另造数据副本。

## F. Chatform

保持现有 General Chat 的 history、messages、composer、错误呈现和多目标 @。无选中会话时显示“Click New and start chatting with me!”（中文“点击 New，和我开始聊天吧！”）。左侧 New 打开空白会话，composer 上方是“Chat with”选择器，分组列出 Agents、Teams（含“+ New Team”）和带 Maya Team 标签的 Maya Teams；第一条消息才创建会话，未选对象不创建。教师自己已发布的 Team 只列一次。

“+ New Team”在 Chatform 内用现有 Team 表单勾选成员和 Leader，师生都可创建，保存为个人 Private Team 后成为当前目标；左栏 Back 取消、Done 保存。两种 Team 都保留标签。

会话标题栏有 Public/Private 切换（按钮+aria-pressed）。会话开始后隐私不变，切换会开始新的会话目标；Public 可被课程教师查看，Private 只属于本人且不进入教师统计/报告。

不能按 can_edit 过滤全部可聊天 Team；编辑操作检查 can_edit，Chatform 列表以当前可读/可启动资源为准。保留 busy/unknown/idempotency、完整历史、日期/Delete互斥与迟到结果隔离。Chatform 只有文字，不派发 TTS。

不添加 Assessment dashboard、状态卡、进度面板、Pause/Continue/Abandon/Restart按钮组、专用输入框或特殊 Maya Team 布局。后台状态不改变通用聊天产品。

## G. Team / Maya Team

复用现有 Team 表单、成员/Leader/Shared Knowledge、visibility、版本和保存幂等实现，不复制第二套表单或新增配置向导。普通 Team 在 Chatform 内联创建；教师在 Studyform 的 Maya Team 模块用左栏 New 新建、Done 以 Public 发布，列表只显示自己可编辑的个人 Public Team。

教师自己的 Public Team 自动进入 Maya Team，学生在 Chatform New 中看到带 Maya Team 标签的条目，选择后以 Private/Public 开始聊天；学生不重新配置成员、Leader或Knowledge。团队成员 own + shared 检索、当前 actor 权限和正式任务 grant 不因布局移动而变化。

## H. Teacher 与维护边界

Components 所有用户 UI 删除成果保持，注册工具/Provider配置在维护层，不增加替代齿轮、Key/Check/mode/status入口。老师/学生界面一致不意味着继承创建者身份、Teacher工具或读取别人 Private Chat。

用户已删除 Brainform 的 External data disclosure 入口。部署方用 `PROVIDER_STANDING_CONSENT` 一次性授权非 Demo 实例的外部 AI 发送；Teacher 的保存或明确生成/重生成表达当前精确外发意图，不再要求另外打开页面确认。Knowledge 生成中显示转圈，完成后出现进入按钮；查看为只读，左栏 New 进入编辑、Done 发布。未开启部署方授权时，精确 Provider 外发依据和教师确认仍在 `/teacher/provider-approvals/chats` 直达页，不把授权事实藏入tooltip，不改账本、env、工具注册或后台权限。Teacher统计/报告仍在普通Chatform会话完成，不新增Memory/Insights页面。

## I. Mobile、Keyboard 与可访问性

三列桌面布局与小屏自然纵排保留，无横向溢出；侧栏操作小屏仍可达。标题提示可keyboard focus，动作有label；保留 Escape、touch、reduced-motion、原focus恢复，不禁zoom/paste。Voices嵌入不重复page h1/IDs，Agents到Voices的DOM顺序与视觉顺序一致。

## J. 禁止事项

- 不重画 Mayaform 首页；不自行新增业务模块、页面面板或badge。
- 不做 Teacher/Student 两套 Studyform/Brainform。
- 不在内容区留下 New/Back/Done 的重复控制。
- 不复制 canonical Knowledge 或把错误group/身份作为默认。
- 不丢 Knowledge pencil、RAG下载、PDF/DOCX、Team创建或既有课堂入口。
- 不弱化 CAS、隐私、read/edit、幂等、计费和迟到隔离。
- 不恢复1500ms或让只有鼠标能访问帮助。
- 不把界面脚手架、Mock或源码推断当真实功能完成。

## K. 实施与验收

单前端 writer（Luna/max），独立 Sol 只读复核，主窗口维护文档、集成与部署；同一文件不多人写。前端冻结后独立测试，不对不断变化的中途diff宣称PASS。

- [ ] Teacher/Student主导航五项（教师另有Debates、Accounts）、顺序准确，身份/group/course正确。
- [ ] Studyform结构相同，Agent/Voice创建管理可达，教师Maya Team发布可达，Voices复用原合法scope。
- [ ] 同事Mayaform首页除Components及Guide链接外保持，其他入口无丢失。
- [ ] New/Back/Done在左侧栏，所有页面无重复内容区按钮，busy/read-only正确。
- [ ] Brainform无大标题/eyebrow，RAG/Knowledge/Memory三列，Knowledge pencil保留。
- [ ] RAG edit/view/download/delete、独立查看编辑、资产名进入Knowledge并显示授权使用者、rename-only、CAS冲突保稿、md/pdf/docx、hide/reindex均可用。
- [ ] Chatform New选择器列出Agent/Team/Maya Team和+ New Team，首条消息建会话，Public/Private切换开新会话，不增加测评控件。
- [ ] tooltip即时，mouse/focus/touch/离开/scroll/nav/Escape/locale切换正确。
- [ ] 标题说明迁移，真正错误/empty/隐私/外发依据继续可见。
- [ ] 全前端测试、types/lint/format、generated boundary通过；权限/调用次数负断言不删除。
- [ ] 独立同版本Sol复核，桌面与375/390/768浏览器实见，记录实际未测范围。
- [ ] 已授权Maya定向部署后健康检查及截图，其他容器/env不变；无UI触发Provider调用。
