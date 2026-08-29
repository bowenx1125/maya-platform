# Wave 2 人工验收资料：Bowen / KaiKai

这是一套本机 Mock Wave 2 的教学对照资料，不是正式 TikTok 课程资料，也不代表平台已经完成真实 LLM、真实 Embedding 或事实核验验收。

## 这套资料要回答什么

1. 学生能否创建、配置和发布两个 Agent；
2. 同一个问题下，相关 RAG 与无命中 RAG 是否在页面上形成清楚差异；
3. 教师能否选择当前发布版本并完成 A1/B1/A2/B2；
4. 投影环境下，学生能否看清当前发言人、正文、RAG 状态和角色聆听状态；
5. 教师能否直觉地使用开始、暂停、继续、跳过、停止和重播。

## 文件选择

### Bowen：高质量组合

- Agent 名称：`Bowen`
- 简介建议：`A civic policy advocate who supports a ban unless the recommendation system is separated from foreign-adversary control.`
- AGENT.md：`bowen/AGENT.md`
- RAG：`bowen/bowen-tiktok-evidence.md`

### KaiKai：RAG 对照组合

- Agent 名称：`KaiKai`
- 简介建议：`A civil-liberties advocate who questions whether a broad ban is proportionate.`
- 第一次发布先用：`kaikai/AGENT-controlled.md`
- RAG：`kaikai/kaikai-unrelated-mineral-notes.md`

`AGENT-controlled.md` 与 Bowen 的写作完整度接近，目的是把主要变量控制为 RAG 质量。不要第一次就用弱 AGENT.md，否则“差异来自 Prompt 还是 RAG”无法判断。

完成 RAG 对照后，可以为 KaiKai 创建 V1.1 草稿，将 AGENT.md 换成 `kaikai/AGENT-weak.md`，继续使用同一份无关 RAG，再观察 Prompt 变化。

## 当前 Mock 的诚实边界

- 可以验证：检索状态、来源文件名、证据片段进入发言、无命中时空来源和一般推理。
- 不可以验证：学生 AGENT.md 的真实理解能力、鲜明角色人格、复杂辩论策略、真实语义 Embedding、真实模型输出质量。
- 当前 Mock 即使收到很弱的 AGENT.md，也会被平台规则强制生成结构正确、80–200 词的英文发言。因此“坏 Prompt 导致不会说话”不是本轮可成立的验收结论；合理预期只是正式 LLM 接入后更缺乏角色特色、论证框架和稳定策略。

## 固定测试问题

草稿测试聊天和教师辩题都使用：

> Should the United States ban TikTok's recommendation algorithm?

测试时不要临时换问题。只有输入一致，页面上的 `matched` / `no_match` 才能形成可解释对照。

## 创建与发布顺序

1. 使用 Bowen 小组账号进入小组工作台，创建 `Bowen`。
2. 上传 `bowen/AGENT.md` 到 AGENT.md 入口；上传 `bowen-tiktok-evidence.md` 到 Evidence/RAG 入口。
3. 确认 RAG 文件被勾选、索引状态为 ready、RAG 预览非空。
4. 选择任一可用 Avatar；音色保留平台兜底；保存草稿。
5. 在测试聊天中输入固定问题，记录 `matched`、grounding 标签和来源文件名。
6. 发布 Bowen V1.0。
7. 使用 KaiKai 小组账号创建 `KaiKai`。
8. 上传 `kaikai/AGENT-controlled.md`；上传并启用 `kaikai-unrelated-mineral-notes.md`。
9. 使用同一个固定问题测试，目标是 `no_match + general_reasoning + sources=[]`。不要在问题后追加“give one reason”等文字；当前 Mock Embedding 对额外词语敏感，追加文字会改变这项确定性对照。
10. 发布 KaiKai V1.0。
11. 教师进入辩论创建页，按 Bowen、KaiKai 的顺序点击，得到 A=Bowen、B=KaiKai。
12. 辩题使用固定问题；Bowen 设为 assigned/support，KaiKai 设为 assigned/oppose；固定两轮。

如果 KaiKai 的无关矿物资料意外显示 matched，不要把它算作通过。记录实际来源和分数相关现象，停止这一项验收；这说明 Mock Embedding 阈值仍可能把无关内容判为相关，需要单独修正测试语料或检索门槛。

## 预期的课堂差异

Bowen：

- 页面显示 RAG 命中；
- 来源至少包含 `bowen-tiktok-evidence.md`；
- 发言应出现该证据文件中的相关语义，而不是只给通用意见。

KaiKai：

- 页面显示未检索到相关知识证据；
- 来源列表为空；
- 发言只能给出一般推理，不应出现虚构文件、研究、百分比或“知识库证明”等措辞。

## 通过标准

- 两个 Agent 都能发布，教师只看到当前发布版本；
- 同题测试中 Bowen 为 matched、KaiKai 为 no_match；
- 观众不看调试信息，也能从来源区域理解谁在使用知识证据；
- KaiKai 无来源时仍能正常说话，但明显更一般、更缺乏可核验事实；
- 四个 turn 完整结束，A2 向 B 提问，B2 向全班提出反思问题；
- 重播不重新生成文字、检索或语音。
