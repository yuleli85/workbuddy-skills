import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {C, FONT} from './theme';

export const glass: React.CSSProperties = {
  background: 'rgba(255,255,255,0.055)',
  border: '1px solid rgba(255,255,255,0.13)',
  borderRadius: 28,
  boxShadow: '0 24px 60px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.09)',
};

export const GlassCard: React.FC<{
  style?: React.CSSProperties;
  children: React.ReactNode;
}> = ({style, children}) => (
  <div style={{...glass, display: 'flex', ...style}}>{children}</div>
);

export const Chip: React.FC<{
  label: string;
  color: string;
  style?: React.CSSProperties;
  dot?: boolean;
}> = ({label, color, style}) => (
  <div
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: 14,
      padding: '16px 34px',
      borderRadius: 999,
      background: `${color}1A`,
      border: `1.5px solid ${color}55`,
      color: C.ink,
      fontFamily: FONT,
      fontSize: 38,
      fontWeight: 600,
      letterSpacing: 2,
      ...style,
    }}
  >
    <span
      style={{
        width: 14,
        height: 14,
        borderRadius: 4,
        background: color,
        boxShadow: `0 0 14px ${color}`,
      }}
    />
    {label}
  </div>
);

export const Kicker: React.FC<{text: string}> = ({text}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = springy(f, 6, fps);
  return (
    <div
      style={{
        position: 'absolute',
        top: 64,
        left: 80,
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        opacity: s,
        transform: `translateY(${(1 - s) * -18}px)`,
        fontFamily: FONT,
      }}
    >
      <span
        style={{
          width: 46,
          height: 46,
          borderRadius: 13,
          background: `linear-gradient(135deg, ${C.violet}, ${C.cyan})`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: '#fff',
          fontSize: 26,
          fontWeight: 800,
        }}
      >
        AI
      </span>
      <span style={{color: C.sub, fontSize: 30, fontWeight: 600, letterSpacing: 6}}>
        {text}
      </span>
    </div>
  );
};

export const springy = (f: number, delay: number, fps: number): number => {
  if (f < delay) {
    return 0;
  }
  const p = Math.min(1, (f - delay) / 14);
  const back = 1.35;
  const c3 = back + 1;
  const x = p - 1;
  return 1 + c3 * x * x * x + back * x * x;
};

export const useRise = (delay: number, dist = 46) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = springy(f, delay, fps);
  return {opacity: Math.min(1, s * 1.6), transform: `translateY(${(1 - s) * dist}px)`};
};

export const SceneTitle: React.FC<{text: React.ReactNode; style?: React.CSSProperties}> = ({
  text,
  style,
}) => {
  const r = useRise(4, 30);
  return (
    <div
      style={{
        fontFamily: FONT,
        fontSize: 72,
        fontWeight: 800,
        color: C.ink,
        letterSpacing: 3,
        textShadow: '0 8px 40px rgba(0,0,0,0.5)',
        ...r,
        ...style,
      }}
    >
      {text}
    </div>
  );
};

export const ProgressBar: React.FC = () => {
  const f = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const p = interpolate(f, [0, durationInFrames], [0, 1]);
  return (
    <div style={{position: 'absolute', bottom: 0, left: 0, right: 0, height: 8}}>
      <div
        style={{
          width: `${p * 100}%`,
          height: '100%',
          background: `linear-gradient(90deg, ${C.violet}, ${C.cyan})`,
          boxShadow: `0 0 18px ${C.cyan}88`,
        }}
      />
    </div>
  );
};
