import { PRESS_MOTION } from "../../ui/button";
/*
 * Debates Immerse (beta) chrome — A1 candy dock, title pill, yellow QR ticket,
 * V1 票根卷 transcript drawer (incl. Check RAG dress). Tailwind only; ported 1:1 from
 * the retired beta-stage.module.css. No preflight: every border sets a style.
 */

export const BETA_STAGE =
  "fixed inset-0 z-[1] overflow-hidden bg-[#ece8e0] [font-family:var(--font-ui,system-ui)] [&_audio]:hidden";

const DOCK_SHELL =
  "absolute z-[12] top-auto left-1/2 right-auto bottom-[max(22px,env(safe-area-inset-bottom))] [transform:translateX(-50%)] flex flex-row flex-nowrap items-center justify-center gap-2 max-w-[calc(100vw_-_24px)] py-2 px-[10px] border-[2.5px] border-solid border-[#111] rounded-full bg-white shadow-[0_5px_0_#ff4d8d] max-[600px]:left-[max(10px,env(safe-area-inset-left))] max-[600px]:right-[max(10px,env(safe-area-inset-right))] max-[600px]:bottom-[max(12px,env(safe-area-inset-bottom))] max-[600px]:[transform:none] max-[600px]:grid max-[600px]:grid-cols-[repeat(3,1fr)] max-[600px]:gap-[6px] max-[600px]:p-2 max-[600px]:rounded-[22px]";
const DOCK_ORDER =
  "[&_[data-dock=back]]:order-1 [&_[data-dock=interact]]:order-2 [&_[data-dock=advance]]:order-3 [&_[data-dock=end]]:order-4 [&_[data-dock=transcript]]:order-5 [&_[data-dock=replay]]:order-6 [&_[data-dock=replay]]:inline-flex [&_[data-dock=conclude]]:order-7";
const DOCK_BUTTONS =
  "[&_:is(button,a)]:inline-flex [&_:is(button,a)]:items-center [&_:is(button,a)]:justify-center [&_:is(button,a)]:flex-none [&_:is(button,a)]:gap-[7px] [&_:is(button,a)]:w-auto [&_:is(button,a)]:h-auto [&_:is(button,a)]:min-h-[40px] [&_:is(button,a)]:pt-2 [&_:is(button,a)]:pr-4 [&_:is(button,a)]:pb-2 [&_:is(button,a)]:pl-3 [&_:is(button,a)]:border-2 [&_:is(button,a)]:border-solid [&_:is(button,a)]:border-[#111] [&_:is(button,a)]:rounded-full [&_:is(button,a)]:bg-white [&_:is(button,a)]:text-[#111] [&_:is(button,a)]:[font:700_14px/1.2_var(--font-ui,system-ui)] [&_:is(button,a)]:no-underline [&_:is(button,a)]:whitespace-nowrap [&_:is(button,a)]:[box-shadow:none] [&_:is(button,a)]:cursor-pointer [&_:is(button,a)]:[transition:transform_80ms_ease,background_80ms_ease] motion-reduce:[&_:is(button,a)]:[transition:none] [&_.primary-action]:border-[#111] [&_.primary-action]:bg-[#ff4d8d] [&_.primary-action]:text-[#111] [&_.primary-action]:[box-shadow:0_4px_0_#111] [&_.danger-action]:border-[#111] [&_.danger-action]:bg-[#ffe4e4] [&_.danger-action]:text-[#9f1239] [&_.danger-action]:[box-shadow:0_3px_0_#f9a8d4] [&_:is(button,a):hover:not(:disabled)]:bg-[#f1f7ff] [&_:is(button,a):hover:not(:disabled)]:border-[#111] [&_:is(button,a):hover:not(:disabled)]:no-underline [&_:is(button,a):hover:not(:disabled)]:[transform:translate(-1px,-1px)] [&_button[aria-expanded=true]]:bg-[#f1f7ff] [&_button[aria-expanded=true]]:border-[#111] [&_button[aria-expanded=true]]:no-underline [&_button[aria-expanded=true]]:[transform:translate(-1px,-1px)] [&_[data-dock=transcript][aria-expanded=true]]:bg-[#ffe14d] [&_[data-dock=transcript][aria-expanded=true]]:[box-shadow:0_3px_0_#111] [&_[data-dock=transcript][aria-expanded=true]]:[transform:none] [&_[data-dock=transcript][aria-expanded=true]:hover:not(:disabled)]:bg-[#ffe14d] [&_.primary-action:hover:not(:disabled)]:bg-[#ff4d8d] [&_.danger-action:hover:not(:disabled)]:bg-[#fecdd3] [&_:is(button,a):focus-visible]:[outline:2px_solid_#111] [&_:is(button,a):focus-visible]:[outline-offset:3px] [&_button:disabled]:text-[#a8a29e] [&_button:disabled]:border-[#d6d3d1] [&_button:disabled]:bg-[#fafaf9] [&_button:disabled]:[box-shadow:none] [&_button:disabled]:cursor-default [&_button:disabled]:[transform:none] [&_button:disabled]:opacity-100 max-[600px]:[&_:is(button,a)]:flex-col max-[600px]:[&_:is(button,a)]:gap-[2px] max-[600px]:[&_:is(button,a)]:w-auto max-[600px]:[&_:is(button,a)]:min-h-0 max-[600px]:[&_:is(button,a)]:py-2 max-[600px]:[&_:is(button,a)]:px-1 max-[600px]:[&_:is(button,a)]:[font-size:11px] max-[600px]:[&_:is(button,a)]:rounded-[14px] max-[600px]:[&_[data-dock=advance]]:col-[1/-1] max-[600px]:[&_[data-dock=advance]]:flex-row max-[600px]:[&_[data-dock=advance]_:is(button,a)]:flex-row";
export const BETA_DOCK = `${DOCK_SHELL} ${DOCK_ORDER} ${DOCK_BUTTONS}`;
export const BETA_PANEL_ACTIONS = "contents";

/* V1 票根卷: Check RAG pill, segment stubs, dashed receipts. */
const RAG_DRESS =
  "[&_details]:mt-0 [&_details]:p-0 [&_details]:border-0 [&_details]:rounded-none [&_details]:bg-transparent [&_details>summary]:inline-flex [&_details>summary]:items-center [&_details>summary]:gap-[6px] [&_details>summary]:pt-[3px] [&_details>summary]:pr-2 [&_details>summary]:pb-[3px] [&_details>summary]:pl-[7px] [&_details>summary]:border-2 [&_details>summary]:border-solid [&_details>summary]:border-[#111] [&_details>summary]:rounded-full [&_details>summary]:bg-white [&_details>summary]:text-[#111] [&_details>summary]:[font:700_12px/1.3_var(--font-ui,system-ui)] [&_details>summary]:list-none [&_details>summary]:cursor-pointer [&_details>summary]:[&::-webkit-details-marker]:hidden [&_details[open]>summary]:bg-[#ffe14d] [&_details[open]>summary]:[box-shadow:2px_2px_0_#111] [&_details>summary]:before:content-[''] [&_details>summary]:before:w-[15px] [&_details>summary]:before:h-[15px] [&_details>summary]:before:flex-none [&_details>summary]:before:[background:currentColor] [&_details>summary]:before:[mask-image:url(data:image/svg+xml,%3Csvg%20xmlns=%27http://www.w3.org/2000/svg%27%20viewBox=%270%200%2024%2024%27%20fill=%27none%27%20stroke=%27black%27%20stroke-width=%272.4%27%20stroke-linecap=%27round%27%20stroke-linejoin=%27round%27%3E%3Cpath%20d=%27M2%2012s4-7%2010-7%2010%207%2010%207-4%207-10%207S2%2012%202%2012z%27/%3E%3Ccircle%20cx=%2712%27%20cy=%2712%27%20r=%273%27/%3E%3C/svg%3E)] [&_details>summary]:before:[mask-position:center] [&_details>summary]:before:[mask-size:contain] [&_details>summary]:before:[mask-repeat:no-repeat] [&_details>summary>span]:inline-grid [&_details>summary>span]:min-w-[18px] [&_details>summary>span]:h-auto [&_details>summary>span]:m-0 [&_details>summary>span]:px-[7px] [&_details>summary>span]:place-items-center [&_details>summary>span]:border-2 [&_details>summary>span]:border-solid [&_details>summary>span]:border-[#111] [&_details>summary>span]:rounded-full [&_details>summary>span]:bg-[#ffe14d] [&_details>summary>span]:text-[#111] [&_details>summary>span]:[font:800_11px/1.4_var(--font-ui,system-ui)] [&_details>div]:grid [&_details>div]:gap-2 [&_details>div]:mt-2 [&_details_article]:grid [&_details_article]:gap-[6px] [&_details_article]:py-2 [&_details_article]:px-[10px] [&_details_article]:border-2 [&_details_article]:border-solid [&_details_article]:border-[#111] [&_details_article]:rounded-[12px] [&_details_article]:bg-white [&_details_article>p]:m-0 [&_details_article>p]:text-[#111] [&_details_article>p]:[font:500_12.5px/1.45_var(--font-ui,system-ui)] [&_[data-grade]]:justify-self-start [&_[data-grade]]:py-0 [&_[data-grade]]:px-2 [&_[data-grade]]:border-2 [&_[data-grade]]:border-solid [&_[data-grade]]:border-[#111] [&_[data-grade]]:rounded-full [&_[data-grade]]:bg-[#f5f5f4] [&_[data-grade]]:text-[#111] [&_[data-grade]]:[font:800_10.5px/1.5_var(--font-ui,system-ui)] [&_[data-grade=direct]]:bg-[#a3e635] [&_[data-grade=indirect]]:bg-[#67e8f9] [&_details_dl]:grid [&_details_dl]:gap-[3px] [&_details_dl]:m-0 [&_details_dl]:py-[6px] [&_details_dl]:px-2 [&_details_dl]:border-2 [&_details_dl]:border-dashed [&_details_dl]:border-[#111] [&_details_dl]:rounded-[10px] [&_details_dl]:bg-[#fffdf2] [&_details_dl]:[font:500_11px/1.4_var(--font-ui,system-ui)] [&_details_dl>div]:flex [&_details_dl>div]:gap-[6px] [&_details_dl_dt]:min-w-[48px] [&_details_dl_dt]:text-[#111] [&_details_dl_dt]:[font:800_11px/1.4_var(--font-ui,system-ui)] [&_details_dl_dd]:m-0 [&_details_dl_dd]:text-[#111] [&_details_dl_dd]:[font:500_11px/1.4_var(--font-ui,system-ui)] [&_details_dl>div:first-child]:justify-between [&_details_dl>div:first-child]:pb-[3px] [&_details_dl>div:first-child]:border-0 [&_details_dl>div:first-child]:border-b-2 [&_details_dl>div:first-child]:border-dashed [&_details_dl>div:first-child]:border-[#11111144] [&_details_dl>div:first-child>dd]:py-0 [&_details_dl>div:first-child>dd]:px-[6px] [&_details_dl>div:first-child>dd]:border-[1.5px] [&_details_dl>div:first-child>dd]:border-solid [&_details_dl>div:first-child>dd]:border-[#111] [&_details_dl>div:first-child>dd]:rounded-full [&_details_dl>div:first-child>dd]:bg-[#e0f2fe] [&_details_dl>div:first-child>dd]:font-extrabold [&_details_div>span]:text-[#78716c] [&_details_div>span]:[font:600_11.5px/1.4_var(--font-ui,system-ui)] [&_[data-testid=evidence-trace-absent]]:m-0 [&_[data-testid=evidence-trace-absent]]:text-[#78716c] [&_[data-testid=evidence-trace-absent]]:[font:600_11.5px/1.4_var(--font-ui,system-ui)]";

/* V1 票根卷: the whole drawer is an enlarged A1 ticket, tilted 0.6°. */
export const BETA_TRANSCRIPT_DRAWER = `absolute z-10 top-[max(20px,env(safe-area-inset-top))] right-[max(22px,env(safe-area-inset-right))] bottom-[max(104px,calc(env(safe-area-inset-bottom)_+_82px))] w-[min(430px,40vw)] overflow-hidden border-[2.5px] border-solid border-[#111] rounded-[18px] bg-white shadow-[6px_7px_0_#ff4d8d] [transform:rotate(.6deg)] text-[#111] [&[hidden]]:hidden max-[600px]:top-[62px] max-[600px]:right-[10px] max-[600px]:left-[10px] max-[600px]:bottom-[max(220px,calc(env(safe-area-inset-bottom)_+_208px))] max-[600px]:w-auto max-[600px]:[transform:none] ${RAG_DRESS}`;

export const BETA_TURN_PROGRESS =
  "inline-flex items-center ml-auto py-[2px] px-[10px] border-2 border-solid border-[#111] rounded-full bg-[#ffe14d] text-[#111] [font:800_13px/1.4_var(--font-ui,system-ui)] tabular-nums shadow-[2px_2px_0_#111] data-[connected=false]:text-[#963c34] data-[connected=false]:bg-[#f8e1dd]";

const DOTS =
  "[background:radial-gradient(#11111114_1.2px,transparent_1.4px)_0_0/14px_14px,#fffdf5]";

/** Class map handed to SpeechStream (its `styles` prop). */
export const BETA_STREAM_STYLES: Record<string, string> = {
  streamCard:
    "flex flex-col h-full min-h-0 p-0 after:content-[''] after:flex-none after:h-[14px] after:border-0 after:border-t-[2.5px] after:border-solid after:border-[#111] after:[background:radial-gradient(circle_at_7px_14px,#111_0_5px,transparent_5.5px)_0_0/14px_14px,#ffe14d]",
  streamHeader:
    "flex flex-none items-center gap-2 py-[10px] px-[14px] bg-[#ffe14d] border-0 border-b-[2.5px] border-solid border-[#111] [&_h2]:flex [&_h2]:items-center [&_h2]:flex-wrap [&_h2]:gap-2 [&_h2]:m-0 [&_h2]:[font:800_16px/1.3_var(--font-display,var(--font-ui,system-ui))]",
  streamState:
    "py-[1px] px-2 border-2 border-solid border-[#111] rounded-full bg-[#e3fbe9] text-[#166534] [font:800_11px/1.4_var(--font-ui,system-ui)] lowercase",
  streamCount:
    "ml-auto py-[2px] px-[10px] border-2 border-solid border-[#111] rounded-full bg-[#ffe14d] [font:800_13px/1.4_var(--font-ui,system-ui)] shadow-[2px_2px_0_#111]",
  streamList:
    `grid flex-1 content-start gap-[14px] min-h-0 pt-[14px] px-[14px] pb-4 overflow-y-auto overscroll-contain ${DOTS}`,
  streamItem:
    "relative grid gap-[7px] min-w-0 py-[10px] pr-3 pl-[18px] bg-white border-[2.5px] border-solid border-[#111] rounded-[14px] [--c:#ffe14d] data-[tone=1]:[--c:#67e8f9] data-[tone=2]:[--c:#a3e635] shadow-[4px_4px_0_var(--c)] before:content-[''] before:absolute before:left-[5px] before:top-[10px] before:bottom-[10px] before:border-0 before:border-l-[2.5px] before:border-dashed before:border-[#111] even:[transform:rotate(-.6deg)] data-[live]:shadow-[4px_4px_0_#ff4d8d] data-[live]:[outline:3px_solid_#ff4d8d] data-[live]:[outline-offset:2px]",
  streamItemTop: "flex flex-wrap items-center gap-2",
  streamWho:
    "py-[1px] px-[9px] border-2 border-solid border-[#111] rounded-full [background:var(--c)] whitespace-nowrap [font:800_12px/1.4_var(--font-ui,system-ui)]",
  streamMeta: "text-[#57534e] [font:700_11px/1.4_var(--font-ui,system-ui)]",
  streamParagraphs: "grid gap-[7px]",
  streamSpeech:
    "m-0 [font:500_14px/1.5_var(--font-ui,system-ui)] whitespace-pre-wrap [overflow-wrap:anywhere]",
  streamEmpty: `flex-1 m-0 pt-[14px] px-[14px] text-[#57534e] [font:600_14px/1.5_var(--font-ui,system-ui)] ${DOTS}`,
  streamReplayAll:
    "min-w-[44px] min-h-[44px] border border-solid [border-color:var(--line)] rounded-[10px] [color:var(--accent)] [background:var(--surface)] cursor-pointer",
  streamSources:
    "m-0 text-[#57534e] [font:500_11.5px/1.4_var(--font-ui,system-ui)] [&_ul]:m-0 [&_ul]:pl-4",
  streamSourcesLabel: "text-[#111] font-bold",
  caret:
    "inline-block w-2 h-[15px] ml-[3px] bg-[#ff4d8d] align-[-2px]",
};

const CARD =
  "flex flex-wrap items-center gap-3 p-4 border border-solid [border-color:var(--line)] rounded-[14px] [background:var(--surface)] [font-size:14px]";
export const BETA_CONNECTION_OVERLAY = `absolute z-[13] top-5 left-5 max-w-[min(420px,calc(100%_-_48px))] ${CARD}`;
export const BETA_FAILURE_CARD = CARD;
export const BETA_PROVIDER_GATE_CARD = `relative z-[13] ${CARD} [&_ul]:m-0 [&_ul]:pl-4`;
export const BETA_RECONNECT_BUTTON =
  `min-h-[44px] border-[3px] border-[#111] rounded-[10px] [color:var(--accent)] [background:var(--accent-soft)] py-2 px-4 cursor-pointer ${PRESS_MOTION}`;

export const BETA_NOTICES =
  "absolute z-auto top-[max(72px,calc(env(safe-area-inset-top)_+_52px))] right-auto bottom-auto left-[max(22px,env(safe-area-inset-left))] grid gap-3 max-w-[min(560px,58vw)] max-h-[calc(100dvh_-_140px_-_env(safe-area-inset-top)_-_env(safe-area-inset-bottom))] overflow-y-auto overscroll-contain pointer-events-none [&>*]:pointer-events-auto max-[600px]:top-[max(12px,env(safe-area-inset-top))] max-[600px]:left-[max(10px,env(safe-area-inset-left))] max-[600px]:right-[max(10px,env(safe-area-inset-right))] max-[600px]:max-w-none";

/** A1 title: top-left white pill capsule. */
export const BETA_TOPIC =
  "absolute z-[4] top-[max(20px,env(safe-area-inset-top))] left-[max(22px,env(safe-area-inset-left))] w-fit max-w-[min(560px,58vw)] m-0 py-2 px-[14px] border-[2.5px] border-solid border-[#111] rounded-[14px] bg-white shadow-[4px_5px_0_#111] text-[#111] [font-family:var(--font-bricolage,var(--font-display,var(--font-ui,system-ui)))] [font-size:clamp(0.95rem,1.4vw,1.0625rem)] font-extrabold tracking-[-0.01em] leading-[1.3] [overflow-wrap:anywhere] max-[600px]:left-[max(10px,env(safe-area-inset-left))] max-[600px]:right-[max(10px,env(safe-area-inset-right))] max-[600px]:top-[max(12px,env(safe-area-inset-top))] max-[600px]:max-w-none max-[600px]:py-2 max-[600px]:px-3 max-[600px]:[font-size:14px]";

export const BETA_END_PROMPT =
  "absolute z-20 top-1/2 left-1/2 grid gap-4 w-[min(420px,calc(100%_-_48px))] p-5 border border-solid [border-color:var(--line)] rounded-[16px] bg-[rgba(255,255,255,0.98)] shadow-[0_16px_48px_rgba(35,28,18,0.18)] [transform:translate(-50%,-50%)] [&_p]:m-0 [&_p]:[font-size:16px] [&_p]:leading-[1.5]";
export const BETA_END_PROMPT_ACTIONS = "flex justify-end gap-2";

/** A1 yellow ticket QR — bottom-left above the candy dock. */
export const BETA_JOIN_CARD =
  "absolute z-[9] top-auto right-auto bottom-[max(110px,calc(env(safe-area-inset-bottom)_+_88px))] left-[max(22px,env(safe-area-inset-left))] grid items-stretch justify-items-stretch w-[min(200px,calc(100%_-_44px))] [transform:rotate(-1deg)] gap-0 p-0 overflow-hidden border-[2.5px] border-solid border-[#111] rounded-[18px] bg-white shadow-[5px_6px_0_#67e8f9] max-[600px]:left-[10px] max-[600px]:right-[10px] max-[600px]:bottom-[max(110px,calc(env(safe-area-inset-bottom)_+_96px))] max-[600px]:w-auto max-[600px]:[transform:none]";
export const BETA_JOIN_STICK =
  "flex items-center justify-between gap-2 py-2 px-3 border-0 border-b-[2.5px] border-solid border-[#111] bg-[#ffe14d] text-[#111] [font:800_13px/1.2_var(--font-ui,system-ui)] [&_em]:flex-none [&_em]:py-px [&_em]:px-2 [&_em]:border-2 [&_em]:border-solid [&_em]:border-[#111] [&_em]:rounded-full [&_em]:bg-white [&_em]:[font:800_11px/1.2_var(--font-ui,system-ui)] [&_em]:not-italic";
export const BETA_JOIN_BODY =
  "grid justify-items-center gap-2 p-[14px] [&_svg]:block [&_svg]:w-[140px]! [&_svg]:h-auto! [&_svg]:border-[2.5px] [&_svg]:border-solid [&_svg]:border-[#111] [&_svg]:rounded-[10px] [&_svg]:bg-white [&_strong]:absolute [&_strong]:w-px [&_strong]:h-px [&_strong]:overflow-hidden [&_strong]:[clip:rect(0,0,0,0)] [&_strong]:whitespace-nowrap [&_code]:block [&_code]:max-w-[160px] [&_code]:text-[#4b5563] [&_code]:[font:500_10px/1.35_var(--font-ui,system-ui)] [&_code]:text-center [&_code]:break-all";

