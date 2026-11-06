# Classroom Quiz · FE 契约（Rework 2026-11-06）

Ticket: `MAYA-QUIZ-REWORK-20261106-01`（编码A = BE；编码B = FE）  
Scope lock: REPORT-CLICK 收窄——手工编辑器即可；**不做双栏 Agent**；旧 chat 测评不动。  
Canonical API detail: [`CLASSROOM_QUIZ_API.md`](./CLASSROOM_QUIZ_API.md) § Rework 2026-11-06.

All paths under `/api/v1`. Mutations need session + `X-CSRF-Token`.

## 一句话

**Done/publish = 发布卷面；Start taking = 对学生开放作答。两者必须分控件分 API。** 老师 pause → start 后，学生可按新 `taking_epoch` 重测。

## DTO 字段（列表/详情均有）

| Field | Type | Meaning for FE |
|---|---|---|
| `status` | `"draft" \| "published"` | 卷面发布态（Done 写 published） |
| `taking_open` | `bool` | 是否开放学生作答 |
| `taking_epoch` | `int` | 当前开放轮次；每次从 closed → open +1 |
| attempt.`taking_epoch` | `int` | 该次提交所属轮次 |

Student list/detail：仅 `status=published` 可见；**能否 Start 以 `taking_open===true` 为准**（不要再用「published 即可答」）。

## 老师控件 → API

| UI | Method Path | Success | Conflict |
|---|---|---|---|
| Done（原 Save） | `POST .../quizzes/{id}/publish` | 200 TeacherQuizDTO；`taking_open` 仍 `false` | 已发布可幂等；连点防重是 FE 锁（W5） |
| 开始评测 | `POST .../quizzes/{id}/start-taking` | 200；`taking_open=true`，`taking_epoch+=1`（若先前 closed） | **409** `quiz_taking_already_open` |
| 暂停评测 | `POST .../quizzes/{id}/pause-taking` | 200；`taking_open=false`（epoch 不变） | **409** `quiz_taking_already_closed` |
| Unpublish（若保留） | `POST .../unpublish` | 强制 `taking_open=false` | published immutable 规则不变 |

仅 `status=published` 时可 start/pause；草稿隐藏或禁用开始/暂停。

## 学生闸

| 条件 | FE | 提交 |
|---|---|---|
| published && `taking_open` | Available → Start → Questionnaire | `POST .../attempts` → 201 |
| published && !`taking_open` | 不可 Start（或显式「评测未开放/已暂停」） | 若绕过 → **409** `quiz_taking_closed` |
| 同 epoch 已交 | Records 可见；不可再交本轮 | **409** `quiz_attempt_exists` |
| 老师 pause→start 新 epoch | 可再次 Start | 新 attempt 带新 `taking_epoch`；旧 attempt 保留 |

## Records（P1）

老师 Quizzes→Records / 行入口：

```
GET /courses/{course_id}/record-attempts?quiz_id={quiz_id}
```

- 有 `quiz_id`：只返回该卷 **quiz 源** attempts（不含 chat）
- 无 `quiz_id`：行为与旧版相同（quiz + chat 混合）
- 学生自己：`GET .../my-record-attempts`（同样可选 `quiz_id`）

DTO 含 `source`、`score_objective`、`grading_status`、`taking_epoch` 等；**禁止假 EmptyCard**——空仅当 API 真返回 `[]`。

## 错误码速查

| Code | HTTP | FE hint |
|---|---|---|
| `quiz_taking_already_open` | 409 | 开始钮：已开放 |
| `quiz_taking_already_closed` | 409 | 暂停钮：已暂停 |
| `quiz_taking_closed` | 409 | 学生提交：评测未开放 |
| `quiz_attempt_exists` | 409 | 本轮已交；等老师重开 |
| `quiz_published_immutable` | 409 | 须 Unpublish 再改题 |

## 非目标（本轮 FE 勿做）

- 双栏 Agent / 上传课件出卷
- 改旧 chat assessment 接口
- 部署 / 合 main（体验官 PASS + 用户批后由部署兵）

## BE tip（对接基线）

见 DONE 报告分支 `t2/quiz-rework-p1p3p4-20261106`；migration `0084_quiz_taking_open_retest`（须与 FE 同发产网）。
