import type { PlatformApi, RecordAttemptDto } from "./platform";
import {
  PlatformApiError,
  readErrorPayload,
  responseDownloadFilename,
} from "./platform";
import { tm } from "../i18n";
import { exportQuizAttemptsPath, quizAttemptPath } from "../quiz-urls";

export type QuizStatus = "draft" | "published";
export type QuizItemType = "single" | "multiple" | "short_text" | "long_text";

export interface QuizChoice {
  id: string;
  label: string;
}

export interface QuizAnswerKey {
  choice_ids?: string[] | null;
  rubric?: string | null;
}

export type QuizGradingMode = "ai" | "manual";

export interface QuizItemGrading {
  mode: QuizGradingMode;
  score_min?: number;
  score_max?: number;
  rules?: string;
}

export interface QuizItemTeacher {
  id: string;
  type: QuizItemType;
  required?: boolean;
  prompt: string;
  choices: QuizChoice[];
  answer?: QuizAnswerKey | null;
  points?: number;
  /** Absent ≡ manual (compat with older quizzes). */
  grading?: QuizItemGrading | null;
}

export interface QuizSettings {
  shuffle_questions?: boolean;
  shuffle_choices?: boolean;
  allow_skip?: boolean;
  time_limit_sec?: number | null;
}

export interface QuizSummaryDTO {
  show_results?: boolean;
  id: string;
  course_id: string;
  group_id?: string | null;
  title: string;
  status: QuizStatus;
  schema_version: number;
  content_revision: number;
  attempt_count?: number;
  /** Teacher opened taking; missing/false => students cannot Start. */
  taking_open?: boolean;
  /** Current taking round; increments each closed→open. */
  taking_epoch?: number;
  /** Teacher view: active current-epoch exemptions. */
  exemption_count?: number;
  exemption_deadline_latest?: string | null;
  /** Per-viewer: the student's active deadline, if any. */
  exempt_until?: string | null;
  /** Per-viewer: published and (open or exempt) and not already submitted. */
  can_take_now?: boolean;
  scheduled_start_at?: string | null;
  scheduled_end_at?: string | null;
  created_by_user_id: string;
  published_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TeacherQuizDTO extends QuizSummaryDTO {
  settings: QuizSettings;
  locale?: string;
  items: QuizItemTeacher[];
}

export type QuizGradingStatusValue = "complete" | "pending" | "mixed";

/** One item of the frozen paper an attempt answered, with the response. */
export interface QuizAttemptItem {
  id: string;
  type: QuizItemType | "unknown";
  required?: boolean;
  prompt: string;
  choices: QuizChoice[];
  points: number;
  response_choice_ids?: string[] | null;
  response_text?: string | null;
  correct?: boolean | null;
  points_awarded?: number | null;
  graded: boolean;
  feedback?: string | null;
  /** Teacher view only; a student's detail never carries the key. */
  answer?: QuizAnswerKey | null;
  /** Present after the AI worker writes a score; omit/null while pending. */
  ai_score?: number | null;
  /** Teacher view: the teacher turned AI grading on for this item. */
  ai_grading?: boolean;
}

export interface QuizAttemptDetail {
  show_results?: boolean;
  view: "teacher" | "student";
  id: string;
  quiz_id: string;
  course_id: string;
  user_id: string;
  student_name: string;
  title: string;
  content_revision: number;
  taking_epoch: number;
  status: "submitted";
  grading_status: QuizGradingStatusValue | null;
  score_objective: number | null;
  score_max_objective: number | null;
  score_manual: number | null;
  score_max_manual: number | null;
  /** Optional aggregate of AI item scores when the API sends it. */
  score_ai?: number | null;
  points_awarded: number | null;
  points_total: number | null;
  submitted_at: string;
  graded_at?: string | null;
  items: QuizAttemptItem[];
}

export interface QuizItemGrade {
  item_id: string;
  points_awarded: number;
  feedback?: string;
}

export interface QuizExemptionDTO {
  id: string;
  student_id: string;
  username: string;
  display_name: string;
  deadline_at: string;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface QuizExemptionStudentDTO {
  student_id: string;
  username: string;
  display_name: string;
  submitted: boolean;
  exempt_until?: string | null;
}

export interface QuizExemptionsDTO {
  taking_epoch: number;
  exemptions: QuizExemptionDTO[];
  students: QuizExemptionStudentDTO[];
}

export interface PutQuizExemptionsRequest {
  student_ids: string[];
  deadline_at: string;
}

export interface PutQuizResultsRequest {
  show_results: boolean;
}

export interface PutQuizScheduleRequest {
  start_at: string | null;
  end_at: string | null;
}

export interface CreateQuizRequest {
  title: string;
  group_id?: string | null;
  settings?: QuizSettings | null;
  items?: QuizItemTeacher[];
  locale?: string;
}

export interface PatchQuizRequest {
  title?: string | null;
  group_id?: string | null;
  settings?: QuizSettings | null;
  items?: QuizItemTeacher[] | null;
  locale?: string | null;
}

// The backend sends errors top-level ({code, message, details, request_id}),
// the same shape PlatformApi reads; without the code the teacher pages lost
// their English copy and showed the raw JSON body instead.
function toPlatformApiError(
  status: number,
  bodyText: string,
): PlatformApiError {
  let body: unknown;
  try {
    body = bodyText ? JSON.parse(bodyText) : undefined;
  } catch {
    body = undefined;
  }
  const payload = readErrorPayload(body);
  return new PlatformApiError(
    status,
    payload?.message ?? tm("httpError", { status }),
    payload,
  );
}

export class QuizApi {
  constructor(private readonly platformApi: PlatformApi) {}

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const response = await fetch(path, {
      method,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": this.platformApi.getCsrfToken() ?? "",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) {
      throw toPlatformApiError(response.status, await response.text());
    }
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  private async requestBlob(
    method: string,
    path: string,
    fallbackFilename: string,
  ): Promise<{ blob: Blob; filename: string }> {
    const response = await fetch(path, {
      method,
      credentials: "include",
      headers: {
        "X-CSRF-Token": this.platformApi.getCsrfToken() ?? "",
      },
    });
    if (!response.ok) {
      throw toPlatformApiError(response.status, await response.text());
    }
    const blob = await response.blob();
    return {
      blob,
      filename: responseDownloadFilename(response, fallbackFilename),
    };
  }

  listQuizzes(courseId: string): Promise<QuizSummaryDTO[]> {
    return this.request<QuizSummaryDTO[]>(
      "GET",
      `/api/v1/courses/${courseId}/quizzes`,
    );
  }

  createQuiz(
    courseId: string,
    payload: CreateQuizRequest,
  ): Promise<TeacherQuizDTO> {
    return this.request<TeacherQuizDTO>(
      "POST",
      `/api/v1/courses/${courseId}/quizzes`,
      payload,
    );
  }

  getQuiz(courseId: string, quizId: string): Promise<TeacherQuizDTO> {
    return this.request<TeacherQuizDTO>(
      "GET",
      `/api/v1/courses/${courseId}/quizzes/${quizId}`,
    );
  }

  patchQuiz(
    courseId: string,
    quizId: string,
    payload: PatchQuizRequest,
  ): Promise<TeacherQuizDTO> {
    return this.request<TeacherQuizDTO>(
      "PATCH",
      `/api/v1/courses/${courseId}/quizzes/${quizId}`,
      payload,
    );
  }

  publishQuiz(courseId: string, quizId: string): Promise<TeacherQuizDTO> {
    return this.request<TeacherQuizDTO>(
      "POST",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/publish`,
    );
  }

  /** Teacher only: deletes the quiz for good, with every attempt on it. */
  deleteQuiz(courseId: string, quizId: string): Promise<void> {
    return this.request<void>(
      "DELETE",
      `/api/v1/courses/${courseId}/quizzes/${quizId}`,
    );
  }

  unpublishQuiz(courseId: string, quizId: string): Promise<TeacherQuizDTO> {
    return this.request<TeacherQuizDTO>(
      "POST",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/unpublish`,
    );
  }

  listCourseRecordAttempts(
    courseId: string,
    opts?: { quizId?: string },
  ): Promise<RecordAttemptDto[]> {
    const qs = opts?.quizId
      ? `?quiz_id=${encodeURIComponent(opts.quizId)}`
      : "";
    return this.request(
      "GET",
      `/api/v1/courses/${courseId}/record-attempts${qs}`,
    );
  }

  startTaking(courseId: string, quizId: string): Promise<TeacherQuizDTO> {
    return this.request<TeacherQuizDTO>(
      "POST",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/start-taking`,
    );
  }

  pauseTaking(courseId: string, quizId: string): Promise<TeacherQuizDTO> {
    return this.request<TeacherQuizDTO>(
      "POST",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/pause-taking`,
    );
  }

  exportAttempts(
    courseId: string,
    quizId: string,
  ): Promise<{ blob: Blob; filename: string }> {
    return this.requestBlob(
      "GET",
      `/api/v1/${exportQuizAttemptsPath(courseId, quizId)}`,
      `quiz-${quizId.slice(0, 8)}-attempts.zip`,
    );
  }

  getAttempt(
    courseId: string,
    quizId: string,
    attemptId: string,
  ): Promise<QuizAttemptDetail> {
    return this.request<QuizAttemptDetail>(
      "GET",
      `/api/v1/${quizAttemptPath(courseId, quizId, attemptId)}`,
    );
  }

  /** Teacher only: hides the attempt from Records, counts and export. */
  hideAttempt(
    courseId: string,
    quizId: string,
    attemptId: string,
  ): Promise<void> {
    return this.request<void>(
      "DELETE",
      `/api/v1/${quizAttemptPath(courseId, quizId, attemptId)}`,
    );
  }

  listExemptions(courseId: string, quizId: string): Promise<QuizExemptionsDTO> {
    return this.request<QuizExemptionsDTO>(
      "GET",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/exemptions`,
    );
  }

  putExemptions(
    courseId: string,
    quizId: string,
    payload: PutQuizExemptionsRequest,
  ): Promise<QuizExemptionsDTO> {
    return this.request<QuizExemptionsDTO>(
      "PUT",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/exemptions`,
      payload,
    );
  }

  deleteExemption(
    courseId: string,
    quizId: string,
    studentId: string,
  ): Promise<void> {
    return this.request<void>(
      "DELETE",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/exemptions/${studentId}`,
    );
  }

  clearExemptions(courseId: string, quizId: string): Promise<void> {
    return this.request<void>(
      "DELETE",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/exemptions`,
    );
  }

  setResultsVisible(
    courseId: string,
    quizId: string,
    show: boolean,
  ): Promise<QuizSummaryDTO> {
    return this.request<QuizSummaryDTO>(
      "PUT",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/results`,
      { show_results: show } satisfies PutQuizResultsRequest,
    );
  }

  putSchedule(
    courseId: string,
    quizId: string,
    payload: PutQuizScheduleRequest,
  ): Promise<TeacherQuizDTO> {
    return this.request<TeacherQuizDTO>(
      "PUT",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/schedule`,
      payload,
    );
  }

  /** Teacher only: hand grades for text items; choice items keep the key. */
  gradeAttempt(
    courseId: string,
    quizId: string,
    attemptId: string,
    grades: QuizItemGrade[],
  ): Promise<QuizAttemptDetail> {
    return this.request<QuizAttemptDetail>(
      "PUT",
      `/api/v1/${quizAttemptPath(courseId, quizId, attemptId)}/grades`,
      { grades },
    );
  }
}
