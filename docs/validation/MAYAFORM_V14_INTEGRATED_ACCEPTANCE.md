# MayaForm v1.4 integrated acceptance matrix

Requirements adopted on 2026-10-03. All BF, AT and RS items below are NOT_RUN
for the integrated resume revision until their concrete test/browser evidence
is added. Historical PASS in the S01–S22 matrix is dated evidence only; lost
temporary audit reports are an explicit evidence gap. A focused or Fake PASS
does not imply browser, real Provider, GitHub or Docker acceptance.

Input fingerprint: [resume inputs](mayaform-v14-resume-inputs.json). Product
contract: [Brainform and assessment](../contracts/MAYAFORM_V14_BRAINFORM_ASSESSMENT.md).

### Brainform（BF）

| ID   | 可复现的通过条件                                                                                                            |
| ---- | --------------------------------------------------------------------------------------------------------------------------- |
| BF01 | 一次打开 Brainform 即可看到 RAG/Knowledge/Memory 内容；无三层分类入口；手机同页自然排列                                     |
| BF02 | Brainform 所有上下文侧栏 New 都只新增 Markdown RAG；Chats 三种 New 不受影响                                                 |
| BF03 | 文件名/编辑图标直达编辑，查看图标直达渲染；编辑/查看/进入符号与键盘焦点可访问                                               |
| BF04 | Markdown 上传、编辑、回读及失败保稿可用；已授权合并的 PDF/Word 转 Markdown 保留权限、隔离和原始资料关系                     |
| BF05 | 一 Agent 一当前 Knowledge 入口，Graph/Questions/Notes 等同文档分节渲染；任意合法标题可保存                                  |
| BF06 | Knowledge/Agent/Team 不产生互相独立的内容副本；旧 Set/Asset/Question 引用与历史保持可追溯                                   |
| BF07 | 引用其他 Agent 文档时跳同一 canonical ID；read-only 不出现可成功 edit 的旁路，Private 不泄漏                                |
| BF08 | 无派生知识的 Agent 不展示；生成中显示真实 loading；身份切换/撤权后列表不留旧内容                                            |
| BF09 | 修改已绑定 RAG 自动触发对应任务；无依赖的上传、单纯改名、页面刷新不触发生成                                                 |
| BF10 | 多个引用方只更新同一文档一次；重复事件/双击同一动作不重复收费或生成版本；后续新一次手动刷新可再生成                         |
| BF11 | RAG 自动更新和手动 ↻ 都能覆盖已人工编辑的 current；被覆盖的旧版本与来源不丢                                                 |
| BF12 | 旧任务迟到不覆盖新 RAG/新生成代次；生成中人工编辑的版本保留历史且不恢复“永不覆盖”门槛                                       |
| BF13 | 重生成失败旧完整文档可读，首轮/部分成功准确显示；成功自动刷新，不永远 loading 或伪报完成                                    |
| BF14 | Markdown/Graph 安全渲染；图解析失败局部降级，不拒整个正文；学生无权的课程 Rubric/答案不下发；本人合法知识不被角色一刀切隐藏 |
| BF15 | Memory 进入正确 Agent/Team/身份/课程，自动消息仅一次；刷新/后退/迟到响应不重复发或串会话                                    |
| BF16 | Memory 回答来自授权记录；无记录如实说明；Private 不被教师看到，RAG 更新不删除/改写学习记忆                                  |
| BF17 | 授权 Source receipt 与文档版本关联正确；可选无效引用不冒充已验证，也不无理由拒收正文                                        |
| BF18 | 旧 Single、自有 RAG + Team Knowledge、原公开/私密边界、旧文件与证据 ID 在迁移/回滚测试中保持                                |

### 测评回合（AT）

| ID   | 可复现的通过条件                                                                                              |
| ---- | ------------------------------------------------------------------------------------------------------------- |
| AT01 | 测评 attempt 与消息/run 区分；同活动同用户并发 New 只建立一个未结束回合，不限制其他活动                       |
| AT02 | 暂停、刷新、关闭再开、停止输出、故障恢复不清空答案；普通 Chat 自然语言继续同一 attempt，查询/放弃不先恢复评分 |
| AT03 | 未结束回合要求重做时不直接重置；明确放弃并重做一次完成“旧回合结束保留＋新回合创建”                            |
| AT04 | 完成与放弃是开启新回合的两种路径；每次新回合新 ID；放弃不删除答案、不算完整完成                               |
| AT05 | Private 未结束回合从 Public 新入口进入时不变公开、不复制私人记忆，正确回到原回合                              |
| AT06 | 直接、间接索要答案/提示/讲解/对错/薄弱点均不给；学生后续合法作答仍能正常进行                                  |
| AT07 | 跑题请求不执行，简短引导；夹带合法回答时原文保留且正确分类，不错误提交全部文本为答案                          |
| AT08 | 本回合作答记录/进度可查，不展示答案/Rubric/实时评分，不新增作答或推进题目                                     |
| AT09 | @任一成员、多目标、Memory 自动查询、工具结果、SSE 文字及来源预览均不绕过本回合的无提示规则                    |
| AT10 | 完成/放弃后可正常解释和交流；新回合仍无提示；前次解释历史不被伪造成首次独立作答                               |
| AT11 | 更新 RAG/重生成 Knowledge 不重置 attempt，不替换已问题目/Rubric，旧 Assessment 保留真实版本                   |
| AT12 | Raw answer append-only，评估 edit 留版本；不能伪造 actor/evaluator/正式来源；学生自定义练习不冒充正式诊断     |
| AT13 | 普通 Agent/非测评 Team 不被强制禁聊或强制问固定题；四个 Agent 更名后教学协议不变                              |
| AT14 | 既有 hinted/重答历史不删除、不改标签；新测评无主动提示路径，内部评估与学生发言上下文分开                      |
| AT15 | 教师统计准确区分人、回合、完成、放弃、暂停及重做；Private 和无权数据不计入                                    |
| AT16 | 状态转换有持久化、幂等与并发证据；拒绝非法转换沿用普通消息/错误给清楚下一步，不增加测评卡片或按钮组           |

### 恢复、集成与交付（RS）

| ID   | 可复现的通过条件                                                                                                                      |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------- |
| RS01 | 实际 HEAD、文件归属、无运行中/残留任务状态已核查；保留其他授权改动，没有恢复后仅只读汇报并再次主动等待                                |
| RS02 | 实际迁移文件、声明 head、OpenAPI、生成类型与路由完全一致；旧 Chat/证据有数据升级和失败恢复验证，未提交草稿不被假称部署过              |
| RS03 | 丢失临时审计报告明确标证据缺口；新全检/复审绑定当前代码树，隔离环境不导入共享树代码；没有拼接不同版本的 PASS                          |
| RS04 | 真实 Team 执行路径实际走 Agno 公开协调接口，不能仅调用多次单 Agent 冒充；Own＋Shared 均可检索且私有成员资料不串用                     |
| RS05 | 暂停运行能从持久状态用新实例继续；SSE 重连不会冒充继续，也不重复模型调用或已完成 Tool 写入                                            |
| RS06 | Fake 贯通验证每次实际请求的精确字节/账本/stage，未发送释放、未知不重发、缺 usage 保正文和迟到隔离；真实烟测另外记录                   |
| RS07 | Public/Student/Teacher registry 在真实 runtime 生效；学生获得 Public+Student，教师获得 Public+Teacher；read/edit/append 逐资源校验    |
| RS08 | Chat 删除/撤回有正常可解释响应，原证据不因级联而丢失，教师汇总/旧报告/下载及时失效，不出现 FK 500 或永久悬空 attempt                  |
| RS09 | 外发授权不把教师材料阅读权转给学生、不让教师读取 Private Chat；缺授权有恢复路径，未无依据增加逐条确认操作                             |
| RS10 | Chats 始终仅文字输出；未将旧 TTS 描述重新变成需求，其他授权 Voice/Debate 工作没有被清除或误提交                                       |
| RS11 | 最终端到端覆盖 Markdown→Knowledge 生成→教师改 RAG 自动更新→Maya Team 测评→暂停续接/放弃重做→Kaikai 报告；Private 与 Public 两条均验证 |
| RS12 | GitHub、SQLite 备份与可恢复性、实际 Maya Docker 升级、健康与授权真实测试各有独立事实结果；未执行/受阻清楚标注，未称全部上线           |

## Latest Tool and target-resource authorization obligations

The [adopted permission correction](../contracts/MAYAFORM_V14_TOOL_RESOURCE_AUTHORIZATION.md)
replaces the prior two-class registry and blanket Custom Team write bans. The
following 18 allow/deny requirements are NOT_RUN for the integrated revision.
Private participation, plain abandon and target-based safe reads apply throughout.

至少覆盖：

1. Agent 没有相应 Tool 时不能伪造调用成功。
2. Agent 具备 Tool，不代表对任意目标记录具有 read/edit 权限。
3. 学生自建 Agent 即使有 edit_assessment，
   也不能修改当前 Maya Team 的正式 Assessment，因为没有 edit 授权。
4. 对一个明确授权可编辑的合成练习资源，
   同一 Tool 不应只因调用方属于 custom_team 就无条件拒绝。
   此项只验证通用授权机制，不要求新增学生练习产品。
5. 本人可读正式结果，不自动意味着本人或其所有 Agent可编辑。
6. 合法 evaluator 在 active 正式回合可写指定 Assessment；
   非授权成员、其他回合和其他学生目标均被拒绝。
7. 合法 summarizer 只能更新获授权 Boundary，
   不能借此修改 Assessment 或原始答案。
8. 发布标签、成员名字和模型提供的 evaluator/provenance
   都不能替代服务器授权。
9. 同一教师创建的 Agent 在普通自建 Team 中
   不会继承正式评估任务的写授权。
10. 正式回合未开始、暂停、完成、放弃或撤回后，
    不接受新的或迟到的评估结果写入。
11. Private 会话能够完整参加测评，
    但其内容和数量不进入教师统计。
12. “放弃”仅结束旧回合并恢复讨论；
    “放弃并重做”才创建新回合。
13. 重复开始/放弃/重做请求不会创建重复 attempt。
14. Memory、普通学习查询、@和下载
    对同一未结束回合使用相同的安全读取范围。
15. Assessment 修订留版本，原始答案追加保存，
    Boundary 可追溯且不接受伪造来源。
16. 教师读取课程 Public 结果不自动获得 edit 权限，
    Private 无绕过入口。
17. 无权限下载、链接转给无权账号或撤回后下载均被拒绝。
18. 一次 Tool 权限失败后，Chat 和后续合法流程仍可继续。

Both authorized success and unauthorized rejection must be demonstrated; a
student-only rejection probe is insufficient. No additional practice product is
required by the synthetic editable-resource test.
