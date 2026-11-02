# 39 · Loading (C chosen 2026-11-02, implemented)

`overview.png` puts today's small card next to three schemes; `scheme-A/B/C.png`
show each one animating (three frames), in a page's content area, in a small panel
and on a phone. All are real frontend renders.

- A · Stage Show: the sign-in stage, big; the cast hops in turn, a speech bubble
  says Loading…, a candy stripe rolls.
- B · Handheld: a pink game console whose screen runs the cast across.
- C · Card Flip: the sign-in character cards flip one by one; dots follow.

`src/page.demo.tsx` is the mockup page (copy to
`frontend/app/loading-proposals/page.demo.tsx`, run `next dev`, then
`node src/shoot.js <out-dir>`).

**Chosen: C.** `LoadingCard` (`frontend/components/ui.tsx`) is the only loading
look: whole-page waits use `LoadingPage` (the cards on the cyan stripes), a page's
content area gets the framed striped panel, small panels get small cards (sizes
follow the card's own container width), the Live cabinet shows them bare on its
screen. Reduced motion leaves every card face up and still.
