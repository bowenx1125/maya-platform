import type { components } from "../../lib/api/generated/schema";

export type TranslationBatch = components["schemas"]["TranslationBatch"];
export type TranslationItemSummary =
  components["schemas"]["TranslationItemSummary"];

export type TranslationRequestState = {
  batches: TranslationBatch[];
  loading?: boolean;
  busy?: boolean;
  error?: string | null;
};
