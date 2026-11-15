export const DEFAULT_GROUP_NAME = "No Group";

export function isDefaultGroup(name: string): boolean {
  return (
    name.normalize("NFKC").trim().replace(/\s+/g, " ").toLowerCase() ===
    DEFAULT_GROUP_NAME.toLowerCase()
  );
}
