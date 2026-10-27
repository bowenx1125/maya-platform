import { StatusScreen } from "../components/status-screen";

export default function NotFound() {
  return (
    <StatusScreen
      eyebrow="404"
      title="Page not found"
      action="Home"
      href="/"
      mascot="scroll"
      mood="discreet"
    />
  );
}
