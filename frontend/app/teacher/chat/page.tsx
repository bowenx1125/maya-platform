import { AgentChat } from "../../../components/agent-chat";
import { RouteGuard } from "../../../components/session-provider";

export default function TeacherChatPage() {
  return (
    <RouteGuard role="teacher">
      <AgentChat />
    </RouteGuard>
  );
}
