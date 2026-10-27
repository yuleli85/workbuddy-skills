import React from 'react';
import {
  AbsoluteFill,
  Audio,
  interpolate,
  Sequence,
  staticFile,
  useVideoConfig,
} from 'remotion';
import {Background} from './Background';
import {Kicker, ProgressBar} from './ui';
import {S1Hook} from './scenes/S1Hook';
import {S2Problem} from './scenes/S2Problem';
import {S3Steps} from './scenes/S3Steps';
import {S4Loop} from './scenes/S4Loop';
import {S5CTA} from './scenes/S5CTA';
import {LEAD_FRAMES, S1, S2, S3, S4, S5, TOTAL} from './timeline';

const Narration: React.FC<{i: number}> = ({i}) => (
  <Sequence from={LEAD_FRAMES}>
    <Audio src={staticFile(`audio/narration_${i + 1}.mp3`)} />
  </Sequence>
);

const Music: React.FC = () => {
  const {durationInFrames} = useVideoConfig();
  return (
    <Sequence from={0} durationInFrames={durationInFrames}>
      <Audio
        loop
        src={staticFile('audio/music.mp3')}
        volume={(f) =>
          interpolate(
            f,
            [0, 45, durationInFrames - 80, durationInFrames - 10],
            [0, 0.17, 0.15, 0],
            {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'},
          )
        }
      />
    </Sequence>
  );
};

export const Main: React.FC = () => {
  return (
    <AbsoluteFill style={{backgroundColor: '#060913'}}>
      <Background />
      <Kicker text="AI 落地指南" />

      <Sequence from={0} durationInFrames={S1}>
        <S1Hook dur={S1} />
        <Narration i={0} />
      </Sequence>
      <Sequence from={S1} durationInFrames={S2}>
        <S2Problem dur={S2} />
        <Narration i={1} />
      </Sequence>
      <Sequence from={S1 + S2} durationInFrames={S3.reduce((a, b) => a + b, 0)}>
        <S3Steps durs={S3} />
        <Narration i={2} />
        <Sequence from={S3[0]}>
          <Narration i={3} />
        </Sequence>
        <Sequence from={S3[0] + S3[1]}>
          <Narration i={4} />
        </Sequence>
        <Sequence from={S3[0] + S3[1] + S3[2]}>
          <Narration i={5} />
        </Sequence>
      </Sequence>
      <Sequence from={S1 + S2 + S3.reduce((a, b) => a + b, 0)} durationInFrames={S4}>
        <S4Loop />
        <Narration i={6} />
      </Sequence>
      <Sequence
        from={S1 + S2 + S3.reduce((a, b) => a + b, 0) + S4}
        durationInFrames={S5}
      >
        <S5CTA dur={S5} />
        <Narration i={7} />
      </Sequence>

      <Music />
      <ProgressBar />
    </AbsoluteFill>
  );
};
