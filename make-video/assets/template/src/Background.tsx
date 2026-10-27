import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';

const orb = (
  x: number,
  y: number,
  r: number,
  color: string,
  alpha: number,
): React.CSSProperties => ({
  position: 'absolute',
  left: x - r,
  top: y - r,
  width: r * 2,
  height: r * 2,
  borderRadius: '50%',
  background: `radial-gradient(circle closest-side, ${color} 0%, transparent 70%)`,
  opacity: alpha,
});

export const Background: React.FC = () => {
  const f = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const t = f / 30;
  const endGlow = 1 - Math.min(1, Math.max(0, (durationInFrames - f) / 45));

  return (
    <AbsoluteFill style={{backgroundColor: '#060913'}}>
      <AbsoluteFill>
        <div style={orb(420 + 70 * Math.sin(t * 0.11), 260 + 50 * Math.cos(t * 0.09), 520, '#3B2A7A', 0.85)} />
        <div style={orb(1560 + 80 * Math.cos(t * 0.08 + 2), 320 + 60 * Math.sin(t * 0.1 + 1), 560, '#0E4A5E', 0.9)} />
        <div style={orb(1020 + 60 * Math.sin(t * 0.07 + 4), 960 + 40 * Math.cos(t * 0.12 + 3), 620, '#3D1F52', 0.8)} />
        <div style={orb(960, 540, 700, '#101A38', 0.55)} />
      </AbsoluteFill>
      <AbsoluteFill
        style={{
          backgroundImage:
            'linear-gradient(rgba(148,163,220,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,220,0.05) 1px, transparent 1px)',
          backgroundSize: '96px 96px',
          maskImage:
            'radial-gradient(ellipse at center, black 30%, transparent 78%)',
          WebkitMaskImage:
            'radial-gradient(ellipse at center, black 30%, transparent 78%)',
        }}
      />
      <AbsoluteFill
        style={{
          background:
            'radial-gradient(ellipse at center, transparent 52%, rgba(2,4,12,0.62) 100%)',
        }}
      />
      <AbsoluteFill
        style={{
          background: `radial-gradient(ellipse at center, rgba(139,92,246,${0.1 * endGlow}) 0%, transparent 60%)`,
        }}
      />
    </AbsoluteFill>
  );
};
