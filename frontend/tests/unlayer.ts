/**
 * The legacy CSS modules sit inside `@layer legacy { … }` (PR0) so Tailwind
 * utilities win over them; jsdom's CSSOM cannot read a layer block, so tests
 * that inspect a module's rules read what is inside it.
 */
export function unlayer(css: string): string {
  const match = /^\s*@layer legacy\s*\{/m.exec(css);
  if (!match) return css;
  const end = css.lastIndexOf("}");
  return css.slice(match.index + match[0].length, end);
}
