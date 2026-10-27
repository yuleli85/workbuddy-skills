import {FPS, NARR, SCENE_LEAD, SCENE_TAIL} from './durations';

export const sceneDur = (sec: number): number =>
  Math.ceil((SCENE_LEAD + sec + SCENE_TAIL) * FPS);

export const S1 = sceneDur(NARR[0]);
export const S2 = sceneDur(NARR[1]);
export const S3 = NARR.slice(2, 6).map(sceneDur);
export const S4 = sceneDur(NARR[6]);
export const S5 = sceneDur(NARR[7]);
export const TOTAL = S1 + S2 + S3.reduce((a, b) => a + b, 0) + S4 + S5;
export const LEAD_FRAMES = Math.round(SCENE_LEAD * FPS);
