# MayaForm v1.4 Tool and assessment resource authorization

Adopted user correction, 2026-10-03. This supersedes conflicting two-class Tool
clauses and blanket Team-type editing bans. It is a product contract, not evidence
of implemented or accepted behavior. All prior non-conflicting safeguards remain.

二、最重要的修正：按工具与资源权限判断，不按 Team 类型一刀切

删除以下绝对表述及对应的无条件拒绝逻辑：

“学生自建 Team 一律不能创建、修改或重算 Assessment / Boundary。”
“普通学生 Agent 即使拥有相关工具，也永远不能写任何评估资源。”
“只有叫 Maya Team 的模式才能使用 Assessment 工具。”

改为：

一次操作能否执行，需要同时满足：

1. 该 Tool 已由维护层注册；
2. 当前 Agent 的本次运行合法具备该 Tool；
3. 当前执行上下文对目标资源具有该操作所需的权限；
4. 涉及正式测评时，符合该目标资源所属 attempt 的明确生命周期约定。

Tool 可用性、资源权限、测评状态是不同维度。

不要仅根据：

- student 身份；
- custom_team 类型；
- published_team 标签；
- Agent / Team 创建者；
- Agent 的显示名字；
  就直接决定某条 Assessment 是否可以被修改。

对于当前 Maya Team 正式测评记录：
学生自建 Agent 即使有 edit_assessment，也没有这些记录的 edit 权限，
所以修改会被拒绝。

拒绝原因是“无权编辑该目标资源”，
不是“学生不准拥有这个 Tool”或“Custom Team 不支持评估”。

将来维护层注册、提供了相应工具，并对某类练习资源明确授予编辑权，
学生自建 Agent / Team 应能够通过相同机制操作，
不需要重写通用工具运行器。

本期不因此增加学生练习系统、权限分享面板或新的评估编辑产品。
只是把底层模型做对，不把未来能力用 Team 类型写死。

三、注册权与三类工具保持不变

所有 Tool 只能由维护层开发、注册、升级、移除。

老师和学生都不能：

- 上传或注册 Python Tool；
- 配置任意 SQL、Shell 或 MCP；
- 修改工具实现；
- 自行提升工具权限。

老师编写的是 Agent.md、Agent/Team 配置与 Knowledge，
不是注册工具代码。

Tool 分类仍然是：

Public：
教师和学生共有的通用资源能力。

Student：
面向个人学习、本人测评与个人学习记录的能力。

Teacher：
面向合法课程管理、跨学生 Public 数据查询、聚合与报告的能力。

正常角色集合：
Student：Public + Student。
Teacher：Public + Teacher。

但类别可用不等于每一个具体操作都无条件成功。
当前 Agent / invocation 是否具有具体工具，
以及工具能操作哪个资源，必须分别检查。

保留实际已确认的确定性挂载方式；
不为了判断 Agent.md “像不像某种角色”新增 Planner、AI 审批、
隐藏语义白名单或复杂手工配置面板。

不新增第四类 Internal Workflow Tools。
内部评估执行的受限授权属于资源与执行上下文，
不是重新建立一套特殊工具分类。

四、统一用 Read / Edit 等资源权限表达

主要复用这些操作语义：

- read；
- edit；
- append；
- create；
- download；
- aggregate；
- publish。

只在实际需要时使用，不为每个角色复制同义 Tool。

例如：
read_assessment：检查目标 Assessment 的 read 权限。
edit_assessment：检查目标 Assessment 的 edit 权限。
read_learning_boundary：检查目标 Boundary 的 read 权限。
update_learning_boundary：检查目标 Boundary 的 edit 权限。

新建记录时检查目标容器的 create / append 权限，
不能因为记录还不存在，就绕开父级 attempt / conversation 授权。

如果现有工具名称不同，可以保留现有名称并统一语义，
不要为改名字制造大面积迁移或第二套实现。

必须区分：
“能读自己的正式评估”
与
“能修改自己的正式评估”。

本人是评估对象，不自动等于本人及其所有 Agent 都有 edit 权限。

同理：
老师能读课程 Public 评估，也不自动等于老师能任意改分。

五、当前正式 Assessment / Boundary 的权限归属

当前正式评估资源由老师发布的 Maya Team 在真实测评回合内产生。

默认授权应表达为：

1. 被评估学生：
   有本人数据的读取权，返回内容受测评阶段约束。
   不自动获得正式 Assessment / Boundary 的编辑权。

2. 学生其他 Agent / 自建 Team：
   可以通过已具备的读取工具读取本人合法视图。
   即使具备写工具，也没有当前这些正式结果的 edit 权限。

3. 正式回合的合法 Assessment evaluator：
   通过服务器建立的受限执行授权，
   在当前 attempt 和指定答案范围内写 Assessment。

4. 正式回合的合法 Boundary summarizer：
   通过服务器建立的受限执行授权，
   根据本回合已有合法证据写 Boundary。
   此权限不自动包含修改 Assessment 或原始答案。

5. 教师：
   可按课程权限读取和汇总允许的 Public 记录。
   不因教师身份自动获得私人学生数据或任意评估编辑权。

默认配方中 Jade 承担 Assessment evaluator，
Kaikai 承担 Boundary summarizer，
但授权绑定稳定成员身份、AgentVersion 和发布配置，
不能硬编码 Jade / Kaikai 等显示名字。

Bowen 可以请求评估、安排流程，
不因此直接获得填写分数或改写 Boundary 的权限。

Maya 可以处理授权课程 Knowledge，
不因此直接获得学生评估记录的编辑权。

六、执行授权不是继承教师身份，也不能由模型伪造

正式评估任务的写权限应由服务器依据真实关系建立并验证，例如：

- 当前参与学生；
- 当前课程；
- 正式 attempt；
- 已发布且仍有效的 Team 版本；
- 被授权的执行成员；
- 当前题目、Rubric、已保存答案；
- 允许的资源与操作；
- 有效的任务身份和状态。

这不是把老师的全部权限交给 Agent，
也不是让学生获得教师角色。

Agent.md、用户消息和 Tool 参数不能自行设置：

- actor；
- evaluator 身份；
- 权限级别；
- 正式来源；
- 任意 attempt 归属；
- Teacher 角色；
- 已通过确认的授权凭据。

同一个教师创建的 Agent：
在正式测评任务中可能有针对指定记录的受限执行授权；
被学生拉进另一个普通 Team 时，不会自动带走这些授权。

同一个 Tool 可以复用，
但不能把一个执行任务的授权缓存并泄漏给另一个任务。

Published Maya Team provenance 继续记录，
但 provenance 是来源事实，不是“看到这个标签就放行”的密码。
来源字段由服务器产生，不接受模型伪造。

七、正式测评生命周期是资源写权限的明确条件

当前正式 Assessment / Boundary：

- 未开始正式 attempt：没有本回合的评估写授权；
- active attempt：合法执行成员可以按目标资源权限写入；
- paused attempt：暂停新的评估写入，恢复后重新核验；
- completed / abandoned / withdrawn：不接受新的或迟到的结果修改。

这只约束正式测评资源，不是一条全平台的“学生不能写评估”规则。

暂停或撤回后到达的 Provider 回包，
必要的收费收据仍按真实状态保存；
但不能因此继续修改已经无权写入的 Assessment / Boundary。

完成回合前应一致地处理需要保存的最终结果；
不能先宣布完成，再用无边界后台任务继续改分。

Assessment 的 edit 是新增修订版本，不物理抹除旧判断。
Boundary 更新必须关联真实证据和版本。
原始回答仍由服务器先保存，重答追加记录，不覆盖旧答案。

八、按最新进度确认 Private、放弃与重做

这三项修正是已确认产品要求，继续完成，不要恢复旧行为：

1. Private 会话也可以完整开始、进行和完成正式测评。
   Private 影响教师能否查看和统计，不影响学生能否参加测评。
   Private 的内容、结果和数量不进入教师查询与课程汇报。

2. “放弃本回合”：
   最新用户决定为不保留被放弃回合的学习记录；数据处置及 Tool/Prompt 优化列为后续，当前保留实现不能算本项通过；
   将当前回合记为 abandoned，而不是 completed；
   恢复该会话的正常讨论；
   不自动创建新回合。

3. “放弃本回合并重做”：
   按上述最新处置结束旧回合；
   再创建新的 attempt；
   整个动作幂等，不重复创建，也不再要求第二次多余确认。

4. “暂停 / 停止”：
   保留原回合和当前进度；
   后续只能续接原回合，不暗中清空或重开。

5. 未结束时只说“重新开始”：
   不自动替用户放弃；
   明确给出继续原回合或明确放弃后重做的路径。

6. Chat 撤回：
   继续按最新撤回合同处理关联 attempt，
   不能留下无法续接或重新开始的死状态；
   不能把撤回记成测评完成，也不能自动另开回合。

九、Memory 与个人学习读取统一复用安全视图

学生所有合法 Agent 可以读取本人学习数据，
但都必须复用同一套服务端授权视图，
不能 Memory Tool 返回一份更宽的数据。

对正在进行或暂停、尚未结束的正式回合：

- 可读本人已提交的原始答案；
- 可读题目记录和当前进度；
- 不给实时评分、对错、Boundary 判断、答案、Rubric 或提示。

换 Agent、@成员、从 Brainform Memory 进入、
请求下载或要求汇总，都不能绕过同一目标记录的读取约定。

已完成或明确放弃后，按约定开放个人反馈与解释，
仍不开放无权读取的整份题库或他人数据。

上述限制只作用于相关测评数据与测评上下文，
不把普通非测评聊天全局锁住。

普通记忆与学习记录分清；
RAG / Knowledge 更新不清空 Memory，
也不重写以前发生过的答案或测评结果。

十、工具设计继续精简、复用、可扩展

优先检查当前已经存在的注册表、工具和服务，再做最小调整。

文档类能力可以复用：

- 列表；
- 搜索；
- 读取；
- 编辑合法 Markdown；
- 生成受控下载入口。

RAG 和 canonical Knowledge 共用必要的权限、版本、
渲染、来源与下载服务，不为 student / teacher 各写一套。

不要做一个可以修改任何数据库对象的万能 edit_resource。
文档编辑工具不得借泛化参数修改 Assessment、权限或账本。

Assessment / Boundary 保留清楚的 read / edit 接口。
是否向某次 Agent 执行提供工具，
与目标记录是否具有 read / edit 权限分别验证。

个人学习查询优先通过少量明确视图返回答案、进度和已开放结果。
教师统计复用聚合服务，不为每个数字建一个 Tool。
报告下载复用受控文件下载，不再复制一套下载系统。

原始消息保存、ACL 检查、账本、幂等键、任务租约等后台设施，
不注册为模型可随意操作的工具。

不增加教师/学生工具注册或权限配置页面。

十一、下载也是独立权限，不能成为答案或私密资料旁路

临时下载入口只针对当前用户具有 download 权限的文件或产物。
Agent 能在 Team 中检索一段资料，不自动等于用户能下载完整原件。

实际下载时重新检查身份、版本、有效期、当前权限与撤回状态。
不能把长期公开存储链接或服务器文件路径直接返回给模型。

学生版 Knowledge / 学习记录下载遵守相同安全视图，
不能在网页隐藏 Rubric，却在 Markdown 文件里完整导出。

不存在 read_other_student_private_chat，
也不存在通过导出、Memory 或报告实现同等越权的替代路径。

十二、权限失败要解释并允许继续，不永久锁死对话

工具不可用、资源无 read/edit 权限、回合已暂停或结束，
应返回结构化且不泄漏无权资源详情的结果。

例如：

- 当前没有这个工具；
- 当前记录不可访问；
- 当前只有读取权，没有编辑权；
- 当前回合已暂停，需要先继续；
- 当前回合已结束，可以查看记录或开始新回合。

不要因一次非法编辑：

- 永久锁住 Conversation；
- 丢弃已提交答案；
- 自动放弃或重开测评；
- 自动创建一份冒充正式结果的替代记录；
- 显示虚构成功。

后续合法作答、查询、暂停/继续和正常交流应仍可进行。

继续保留严格的身份、资源权限、版本、事务、
幂等、并发、证据和计费完整性。

不要因此新增职责 Planner、内容审核、固定题数、
隐藏字数/轮数限制或按 Agent 名字触发的后台规则。
