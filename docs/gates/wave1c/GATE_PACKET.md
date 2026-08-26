# Wave 1C Gate Packet — M02 Bilingual Interface Shell

Status: `G3 PASS`
Authorized scope: `2026-08-27 Asia/Shanghai`
Module: `M02 full zh-CN / en-US static interface`
Dependencies: frozen C01/C03 visual/copy boundaries and current Wave 1A functional pages
G0-S audit: `/root/wave1c_design_audit`, `gpt-5.6-sol high`, final `PASS` at `2026-08-27 03:23 Asia/Shanghai` after one bounded correction round
G1 implementer: `/root/wave1c_m02_luna`, `gpt-5.6-luna max`
G1.5 main sign-off refreshed: `2026-08-27 05:39 Asia/Shanghai`
Initial product commit: `d4e5c0830344fed6f019f6a77f62f513fd01f2d0`

## 1. Goal and non-goals

Goal:

- provide a shared locale context for `en` and `zh`, persisted in a presentation-only same-origin cookie and restored server-side without a visible language flash;
- switch all platform-owned static navigation, headings, labels, help, validation and status copy on every page implemented through Wave 1B;
- update document language/accessibility metadata and provide an always-reachable language control on login and authenticated shells;
- keep normal Debate/RAG/AGENT.md/report content in English; locale changes presentation copy only;
- preserve frozen Visual Draft V2 typography, spacing, colors and responsive behavior.

Non-goals:

- no machine translation, DeepL call or translated debate/report storage;
- no Wave 2/3 pages or placeholder controls that imply unimplemented features;
- no redesign, new brand font, route/permission changes or backend locale column;
- no translation of filenames, user names, group/Agent names, source excerpts or English teaching evidence.

## 2. Architecture and invariants

- root layout reads a presentation-only `maya_ui_locale` cookie and passes `initialLocale` into one `LocaleProvider`; invalid/missing values become English. Public locale values map exactly `en -> en-US` and `zh -> zh-CN` for `<html lang>`;
- switching synchronously updates Context, the cookie and `document.documentElement.lang`; it does not call `router.refresh()` or remount the application;
- components use the provider/hook; module-level global mutable locale and duplicated page-local dictionaries are forbidden;
- the cookie contains only `en|zh`, `SameSite=Lax`, path `/`, and no account/session data;
- all English and Chinese dictionaries have identical typed keys; missing/blank/copy-pasted fallback entries fail tests;
- stable API error codes are translated through a platform-owned mapping. Unknown safe server messages may display as safe fallback text; supplier/raw errors never enter copy handling;
- changing locale does not refetch/mutate business data, rotate a Session, change CSRF, create idempotency keys or discard unsaved draft text/file handles;
- identity switching/logout cannot leak the previous account's business state; locale intentionally remains a device preference.

Root provider topology is stable and unkeyed: `SessionProvider > LocaleProvider(initialLocale) > pages`. `PlatformApi` remains locale-neutral and has stable object identity across locale changes. Locale changes must not retrigger `/auth/me` or page data-loading effects.

UI state stores stable platform error code/message key/parameters, not already translated strings. Translation occurs during render using the current locale. Current-Wave stable error codes have explicit safe mappings; an unknown platform envelope may use its already-safe `message` fallback, while supplier/raw details are never rendered. Success/notice state follows the same key-at-render rule.

The dictionaries use an exact shared `MessageKey`: Chinese satisfies `Record<MessageKey, string>`. Automated checks compare both key sets, reject trimmed blanks, compare interpolation placeholder sets and reject accidental identical translations except an explicit small allowlist for product/technical terms such as `Maya`, `AGENT.md`, `RAG`, filenames and status tokens where intended.

## 3. UI scope

Pages/components through Wave 1B:

- login and Demo identity switching;
- student home, group workspace, Agent create/detail/version/workbench, knowledge library, avatar editor and voices;
- teacher course/published Agent detail;
- shared loading, empty, permission, error, confirmation and navigation states.

The route coverage inventory includes `/login`, current student/teacher business routes and their shared guards. `/health` is infrastructure-only and `/` is routing shell behavior; neither is counted as a user copy page.

Authenticated navigation exposes only routes implemented in the current Wave. Frozen later labels (Debates/History) are added when their Wave 2 routes exist; M02 must not link users to 404 placeholders.

Language controls show `中文 / English`, have accessible names/focus and work at 360px and desktop. No page may require reload to switch.

## 4. File ownership and decomposition

Luna M02 owner:

- new isolated locale provider/tests;
- `frontend/lib/i18n.ts` split into typed dictionaries/helpers when useful;
- narrow copy-consumer edits under `frontend/components/**` and `frontend/app/**`;
- M02 styles only where required for the language control/responsive shell.

Must not edit backend, generated API, frozen contracts, Project, workbook, Wave 1B provider/3D implementation or redesign V2. Existing 1,000+ line components may be mechanically converted to the locale hook, but new feature logic must not be added to them.

Reference question: how to keep interface locale as a presentation concern without affecting provider/business data.

Allowed principles: typed equal-key dictionaries, context/hooks, local preference persistence, document language metadata and accessibility tests.

Forbidden reuse: any reference UI/component/copy/test source. All copy and implementation are original to Maya.

## 5. Deterministic acceptance

- typed dictionary equality and no blank values for both locales;
- every rendered platform-owned static string on implemented routes has an English and Chinese result;
- initial English, switch to Chinese, reload restore, corrupt storage fallback, switch back and `<html lang>` tests;
- SSR/browser test proves a saved Chinese cookie produces a Chinese first frame and `zh-CN` before hydration with no hydration warning or English flash;
- locale switch during an unsaved AGENT.md edit, selected documents, pending `File`, revision-conflict state and retry/idempotency handle loses no local data and makes no API mutation;
- API object, Session, CSRF and idempotency-key identity remain unchanged; `me/version/agent/knowledge/ragPreview` and mutation call counts do not increase;
- login, quick identity switch, logout and role guard still pass in both locales;
- user/Agent/group/source names and English RAG answers remain byte-identical across locale changes;
- all controls remain labeled/focusable; 360px and desktop no horizontal overflow;
- frontend lint, TypeScript, full Vitest, production build and existing Wave 0/1A tests pass;
- repository boundary and generated contract clean-diff pass; no backend/OpenAPI/WS change is expected from M02.

G1.5 adds a real-browser matrix for login, student shell/workbench and teacher page at desktop and 360px: restored first-frame locale, no hydration/console error, `scrollWidth <= clientWidth`, keyboard-reachable language control, frozen V2 computed-style sentinels and navigation hrefs limited to currently implemented routes (no Wave 2/3 paths).

## 6. Stop conditions

Stop if M02 would require:

- changing API/DB/session/permission behavior;
- translating AI content or calling an external translation service;
- linking to Wave 2/3 functionality before implementation;
- redesigning frozen V2 or overwriting unsaved business state;
- copying any reference source fragment.

## 7. Gate sequence and audit tier

`G0 Main draft -> G0-S Sol High compact design check -> G1 Luna Max -> G1.5 deterministic checks -> G2 Sol High low-risk batch audit -> G3 main sign-off`

M02 is low risk while presentation-only. Any session/data/permission side effect upgrades the affected part to high risk.

## 8. G0-S live evidence

- first review required a server-visible locale cookie, stable Session/API provider topology, key-at-render error/notice state, executable dictionary equality and real-browser first-frame/responsive checks;
- main added those boundaries without backend/API/content translation scope. The same reviewer returned `PASS`; no implementation file changed during G0-S.

## 9. G1/G1.5 live evidence

- one server-visible presentation cookie restores `en-US/zh-CN` on the first frame; provider topology remains unkeyed and locale-neutral;
- existing pages plus new Avatar/Voice static interface copy use typed English/Chinese keys; language change preserves business content and does not add Wave 2/3 links;
- frontend Prettier, ESLint, TypeScript, 10 Vitest files/40 tests and production build pass; dictionary keys/placeholders/allowed identical terms are covered. A real SessionProvider + Agent workbench integration proves locale toggles preserve the PlatformApi instance, Session/CSRF, request counts, retry/idempotency handles, controlled AGENT.md, selected documents, pending File, revision-conflict state and all business bytes;
- the rebuilt Docker application completes the G1.5 browser matrix for login, student Agent workbench and teacher pages at 1280px and 360px: `en-US/zh-CN` server first frame and reload are stable, no hydration/console warning appears, `scrollWidth === clientWidth`, native enabled controls remain at `tabIndex=0`, V2 Inter/background/title-size sentinels remain intact, and navigation contains only implemented Wave 1 routes. Switching to Chinese preserves unsaved English AGENT.md, the selected Avatar preset and `speaking` preview state;
- direct same-origin SSR evidence with the presentation cookie returns `<html lang="zh-CN">` and Chinese login copy without the English title; jsdom canvas notices are not used as visual evidence.

## 10. G2 live evidence

- the final frontend and cross-contract Sol High audits independently returned `PASS` after the publish-dirty, English-outline, Avatar state/preset, Civic Observer label, mutation-error and duplicate-conflict corrections;
- the real workbench integration and rebuilt Docker browser matrix prove presentation-only locale behavior without Session/API/data mutation or hidden local state loss;
- no translation provider, real model, voice supplier or Wave 2/3 route was invoked or added by M02.

## 11. G3 main sign-off

- `WAVE_1C_G3_PASS`: rebuilt Docker login, student workbench and teacher pages pass desktop/360px SSR locale, refresh, hydration/console, overflow, native keyboard-focusability, V2 style-sentinel and route-link checks;
- switching locale preserves unsaved English AGENT.md, Avatar preset/state and the integration-tested Session/API/CSRF/retry identities. No business text, RAG, supplier call or persistence mutation is translated by M02.
