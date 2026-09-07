import type { components } from "../../lib/api/generated/schema";

export type TeacherInteraction = components["schemas"]["TeacherInteraction"];
export type PublicInteractionForm =
  components["schemas"]["PublicInteractionForm"];
export type VoteAggregate = components["schemas"]["VoteAggregate"];
export type BarrageMessage = components["schemas"]["BarrageMessage"];

export type InteractionParticipant = {
  id: string;
  slot: "A" | "B" | "C" | "D" | "E";
  name: string;
};

export type TeacherInteractionPanelProps = {
  debateId: string;
  interaction: TeacherInteraction;
  participants: InteractionParticipant[];
  busy?: boolean;
  error?: string | null;
  onOpen?: () => void;
  onClose?: () => void;
};

export type AudienceInteractionApi = {
  getForm: (accessToken: string) => Promise<PublicInteractionForm>;
  submitVote: (
    accessToken: string,
    payload: { participant_id: string; client_submission_id: string },
  ) => Promise<{ vote_submitted: true }>;
  submitBarrage: (
    accessToken: string,
    payload: {
      nickname: string;
      raw_text: string;
      turn_id?: string;
      client_submission_id: string;
    },
  ) => Promise<{ barrage_submitted: true }>;
};
