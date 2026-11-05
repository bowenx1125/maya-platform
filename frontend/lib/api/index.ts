export * from "./platform";
// quiz.ts redefines QuizChoice / QuizItemType (same shapes as platform's
// student quiz types). Star-export would collide at next build; omit those
// two and keep teacher QuizApi + DTOs.
export {
  QuizApi,
  type QuizStatus,
  type QuizAnswerKey,
  type QuizItemTeacher,
  type QuizSettings,
  type QuizSummaryDTO,
  type TeacherQuizDTO,
  type CreateQuizRequest,
  type PatchQuizRequest,
} from "./quiz";
