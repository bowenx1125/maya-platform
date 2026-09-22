import { AgentChat } from "../../../components/agent-chat";
import { AppShell } from "../../../components/app-shell";
import { RouteGuard } from "../../../components/session-provider";

export default function TeacherChatPage() {
  return (
    <RouteGuard role="teacher">
      <AppShell role="teacher">
        <AgentChat />
      </AppShell>
    </RouteGuard>
  );
}
