export type StageScenePack = {
  id: string;
  label: string;
  splatUrl: string;
  panoramaUrl?: string;
  depthUrl?: string;
};

/** Local development packs; generated media stays outside version control. */
export const STAGE_SCENE_PACKS: readonly StageScenePack[] = [
  {
    id: "courtyard",
    label: "Main courtyard",
    splatUrl: "/stage/courtyard-360.spz",
    panoramaUrl: "/stage/courtyard-equirect.png",
    depthUrl: "/stage/courtyard-equirect-depth.png",
  },
  {
    id: "early-courtyard",
    label: "Early courtyard",
    splatUrl: "/stage/courtyard-normalized.sog",
  },
  {
    id: "photo",
    label: "Photo reconstruction",
    splatUrl: "/stage/courtyard-photo-transformed.spz",
  },
  {
    id: "procedural",
    label: "Procedural courtyard",
    splatUrl: "/stage/courtyard-procedural.spz",
  },
  {
    id: "prototype",
    label: "Prototype world",
    splatUrl: "/stage/prototype-world.spz",
  },
];

export function stageScenePack(id: string | null | undefined): StageScenePack {
  return (
    STAGE_SCENE_PACKS.find((pack) => pack.id === id) ?? STAGE_SCENE_PACKS[0]
  );
}

export function requestedStageScenePack(): StageScenePack {
  if (typeof window === "undefined") return STAGE_SCENE_PACKS[0];
  return stageScenePack(
    new URLSearchParams(window.location.search).get("scene"),
  );
}
