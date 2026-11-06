import type { PlatformApi } from "./platform";
import { PlatformApiError } from "./platform";

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

export interface QuizItemTeacher {
  id: string;
  type: QuizItemType;
  required?: boolean;
  prompt: string;
  choices: QuizChoice[];
  answer?: QuizAnswerKey | null;
  points?: number;
}

export interface QuizSettings {
  shuffle_questions?: boolean;
  shuffle_choices?: boolean;
  allow_skip?: boolean;
  time_limit_sec?: number | null;
}

export interface QuizSummaryDTO {
  id: string;
  course_id: string;
  group_id?: string | null;
  title: string;
  status: QuizStatus;
  schema_version: number;
  content_revision: number;
  attempt_count?: number;
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

interface ErrorBody {
  detail?:
    | {
        code?: string;
        message?: string;
        details?: Record<string, unknown>;
        request_id?: string;
      }
    | string;
}

function toPlatformApiError(
  status: number,
  bodyText: string,
): PlatformApiError {
  let body: ErrorBody | undefined;
  try {
    body = bodyText ? (JSON.parse(bodyText) as ErrorBody) : undefined;
  } catch {
    body = undefined;
  }
  const detail = body?.detail;
  if (typeof detail === "string") {
    return new PlatformApiError(status, detail);
  }
  if (detail && typeof detail === "object") {
    return new PlatformApiError(status, detail.message ?? "Request failed", {
      code: detail.code,
      details: detail.details,
      request_id: detail.request_id,
    });
  }
  return new PlatformApiError(status, bodyText || "Request failed");
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

  unpublishQuiz(courseId: string, quizId: string): Promise<TeacherQuizDTO> {
    return this.request<TeacherQuizDTO>(
      "POST",
      `/api/v1/courses/${courseId}/quizzes/${quizId}/unpublish`,
    );
  }
}
