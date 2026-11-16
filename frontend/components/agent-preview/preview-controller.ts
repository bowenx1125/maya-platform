export type PreviewReply = {
  answer: string;
  audio_base64?: string | null;
  audio_content_type?: string | null;
};
export type PreviewState = {
  question: string;
  answer: string;
  playing: boolean;
};

/** Epochs fence both HTTP completion and media events after replacement/Close. */
export class PreviewController {
  private epoch = 0;
  private audio: HTMLAudioElement | null = null;
  private closed = false;
  constructor(
    private readonly update: (state: PreviewState) => void,
    private readonly createAudio = (url: string) => new Audio(url),
  ) {}
  private stop() {
    if (!this.audio) return;
    this.audio.onplaying =
      this.audio.onpause =
      this.audio.onended =
      this.audio.onerror =
      this.audio.onwaiting =
      this.audio.onstalled =
        null;
    this.audio.pause();
    this.audio.removeAttribute("src");
    this.audio.load();
    this.audio = null;
  }
  close() {
    this.closed = true;
    this.epoch++;
    this.stop();
    this.update({ question: "", answer: "", playing: false });
  }
  async ask(question: string, request: () => Promise<PreviewReply>) {
    if (this.closed) return;
    const epoch = ++this.epoch;
    this.stop();
    this.update({ question, answer: "", playing: false });
    let reply: PreviewReply;
    try {
      reply = await request();
    } catch {
      if (this.epoch === epoch && !this.closed)
        this.update({
          question,
          answer: "The preview could not be generated.",
          playing: false,
        });
      return;
    }
    const current = () => this.epoch === epoch && !this.closed;
    if (!current()) return;
    const state = { question, answer: reply.answer, playing: false };
    this.update(state);
    if (!reply.audio_base64 || reply.audio_content_type !== "audio/wav") return;
    const audio = this.createAudio(
      `data:audio/wav;base64,${reply.audio_base64}`,
    );
    this.audio = audio;
    audio.onplaying = () => {
      if (current() && this.audio === audio)
        this.update({ ...state, playing: true });
    };
    const stopped = () => {
      if (current()) this.update(state);
    };
    audio.onpause = audio.onwaiting = audio.onstalled = stopped;
    audio.onended = audio.onerror = () => {
      stopped();
      if (this.audio === audio) this.stop();
    };
    try {
      await audio.play();
    } catch {
      stopped();
    }
  }
}
