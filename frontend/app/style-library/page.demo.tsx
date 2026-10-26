"use client";

import { useState } from "react";

import { MASCOT_IDS, MascotFigure } from "../../components/academy/mascots";
import { Notice } from "../../components/ui";
import {
  AgentCard,
  AgentsEmpty,
  AGENT_GRID_CLASS,
  NewButton,
} from "../../components/ui/agent-card";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "../../components/ui/card";
import { GuideDialog, GuideHud } from "../../components/ui/guide-dialog";
import { Input } from "../../components/ui/input";

const TOKENS = [
  ["main", "bg-main"],
  ["sidebar", "bg-sidebar"],
  ["studyform", "bg-studyform"],
  ["brainform", "bg-brainform"],
  ["chatform", "bg-chatform"],
  ["ok", "bg-ok"],
  ["warn", "bg-warn"],
  ["err", "bg-err"],
  ["private", "bg-private"],
] as const;

/** Demo only (page.demo.tsx): the Arcade style library for PR0. */
export default function StyleLibrary() {
  const [notices, setNotices] = useState<number[]>([]);
  return (
    <main className="min-h-screen bg-arc-bg p-8 font-body text-ink max-[680px]:p-4">
      <h1 className="m-0 mb-6 font-display text-4xl font-extrabold">
        Arcade style library
      </h1>

      <section className="mb-10 grid gap-3">
        <h2 className="m-0 font-display text-2xl font-extrabold">Tokens</h2>
        <div className="flex flex-wrap gap-3">
          {TOKENS.map(([name, bg]) => (
            <span key={name} className="grid gap-1 text-xs font-bold">
              <span
                className={`size-16 rounded-arc border-[3px] border-border shadow-arc-s ${bg}`}
              />
              {name}
            </span>
          ))}
        </div>
        <p className="m-0 font-display text-3xl font-extrabold">
          Bricolage 800 display
        </p>
        <p className="m-0 text-base">
          Lexend 400 body · <b>700 bold</b>
        </p>
      </section>

      <section className="mb-10 grid gap-3">
        <h2 className="m-0 font-display text-2xl font-extrabold">
          Buttons, badge, input
        </h2>
        <div className="flex flex-wrap items-center gap-3">
          <Button>Default</Button>
          <Button variant="neutral">Neutral</Button>
          <Button variant="reverse">Reverse</Button>
          <NewButton href="#" label="New" />
          <Badge>Badge</Badge>
          <Input className="w-56" placeholder="Name" />
          <Input className="w-56" aria-invalid="true" defaultValue="Invalid" />
        </div>
      </section>

      <section className="mb-10 grid gap-3">
        <h2 className="m-0 font-display text-2xl font-extrabold">
          Agent cards
        </h2>
        <ul className={AGENT_GRID_CLASS}>
          <AgentCard
            id="a"
            name="Laozi"
            href="#"
            label="V1.0"
            pending={false}
            visibility="public"
            visibilityLabel="Public"
            mascot="wave"
            footer="Last edited by: Bowen"
            deleteLabel="Delete"
            onDelete={() => undefined}
          />
          <AgentCard
            id="b"
            name="Comparative Study of Confucian Ethics and Aristocratic Virtue"
            href="#"
            label="V1.3"
            pending={false}
            visibility="private"
            visibilityLabel="Private"
            mascot="wreath"
            footer="Last edited by: Maya"
            deleteLabel="Delete"
          />
          <AgentCard
            id="c"
            name="Rename me"
            href="#"
            label="V2.1"
            pending={false}
            visibility="private"
            visibilityLabel="Private"
            mascot="scroll"
            footer="Last edited by: Kai"
            deleteLabel="Delete"
            onDelete={() => undefined}
            rename={{ fieldLabel: "Name", onRename: async () => true }}
          />
        </ul>
        <h3 className="m-0 font-display text-xl font-extrabold">Empty state</h3>
        <AgentsEmpty title="No Agents yet." newHref="#" newLabel="New" />
      </section>

      <section className="mb-10 grid gap-3">
        <h2 className="m-0 font-display text-2xl font-extrabold">Mascots</h2>
        <div className="flex gap-4">
          {MASCOT_IDS.map((id) => (
            <Card key={id} className="w-36">
              <CardHeader>
                <CardTitle>{id}</CardTitle>
              </CardHeader>
              <CardContent>
                <MascotFigure id={id} className="h-24 w-auto" />
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className="mb-10 grid gap-3">
        <h2 className="m-0 font-display text-2xl font-extrabold">
          Guide dialog
        </h2>
        <GuideDialog
          modal={false}
          titleId="demo-guide-title"
          bodyId="demo-guide-body"
          title="The New button"
          body="Each page keeps its New button up here, next to the page title."
          hud={<GuideHud total={9} index={2} label="3 of 9" />}
          actions={
            <>
              <Button variant="neutral" size="sm">
                Back
              </Button>
              <Button size="sm">Next</Button>
            </>
          }
        />
      </section>

      <section className="mb-10 grid gap-3">
        <h2 className="m-0 font-display text-2xl font-extrabold">
          Notice tray
        </h2>
        <Notice inline tone="error">
          Inline error notice.
        </Notice>
        <Notice inline tone="success" title="Done">
          Inline success notice.
        </Notice>
        <div>
          <Button
            onClick={() => setNotices((list) => [...list, list.length + 1])}
          >
            Add tray notice
          </Button>
        </div>
        {notices.map((n) => (
          <Notice
            key={n}
            tone={n % 2 ? "error" : "warning"}
            onClose={() => setNotices((list) => list.filter((x) => x !== n))}
          >
            Tray notice {n}
          </Notice>
        ))}
      </section>
    </main>
  );
}
