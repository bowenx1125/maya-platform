import { AgentChat } from "../../../components/agent-chat";
import { AppShell } from "../../../components/app-shell";
import { RouteGuard } from "../../../components/session-provider";

export default function StudentChatPage() {
  return (
    <RouteGuard role="student">
      <AppShell role="student">
        <AgentChat />
      </AppShell>
    </RouteGuard>
  );
}
