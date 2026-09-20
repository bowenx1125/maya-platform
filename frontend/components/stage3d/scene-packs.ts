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
    label: "主院落",
    splatUrl: "/stage/courtyard-360.spz",
    panoramaUrl: "/stage/courtyard-equirect.png",
    depthUrl: "/stage/courtyard-equirect-depth.png",
  },
  {
    id: "photo",
    label: "照片重建",
    splatUrl: "/stage/courtyard-photo-transformed.spz",
  },
  {
    id: "procedural",
    label: "程序庭院",
    splatUrl: "/stage/courtyard-procedural.spz",
  },
  {
    id: "prototype",
    label: "原型世界",
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
