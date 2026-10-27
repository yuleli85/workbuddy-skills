import React from 'react';
import {Composition} from 'remotion';
import {Main} from './Main';
import {TOTAL} from './timeline';
import {FPS} from './durations';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="AiLanding"
      component={Main}
      durationInFrames={TOTAL}
      fps={FPS}
      width={1920}
      height={1080}
    />
  );
};
