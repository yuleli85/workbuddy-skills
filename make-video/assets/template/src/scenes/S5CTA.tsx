import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {C, FONT, gradientText} from '../theme';
import {useRise} from '../ui';
import {Icon} from '../icons';

export const S5CTA: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const logoDelay = Math.round(dur * 0.52);
  const creditDelay = Math.round(dur * 0.7);
  const logo = spring({frame: f - logoDelay, fps, config: {damping: 13}});
  const ring = interpolate(f, [logoDelay, logoDelay + 40], [0.6, 1.35], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const ringO = interpolate(f, [logoDelay, logoDelay + 16, logoDelay + 40], [0, 0.7, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const credits = useRise(creditDelay, 22);
  const l1 = useRise(16, 40);
  const l2 = useRise(52, 40);

  return (
    <AbsoluteFill style={{fontFamily: FONT, alignItems: 'center', justifyContent: 'center'}}>
      <div
        style={{
          position: 'absolute',
          top: 300,
          width: '100%',
          textAlign: 'center',
          ...l1,
        }}
      >
        <span style={{fontSize: 92, fontWeight: 900, color: C.ink, letterSpacing: 8}}>
          AI 不是风口
        </span>
      </div>
      <div
        style={{
          position: 'absolute',
          top: 440,
          width: '100%',
          textAlign: 'center',
          ...l2,
        }}
      >
        <span
          style={{
            fontSize: 92,
            fontWeight: 900,
            letterSpacing: 8,
            ...gradientText(C.violet, C.cyan),
          }}
        >
          而是新的基础设施
        </span>
      </div>

      {/* logo */}
      <div
        style={{
          position: 'absolute',
          bottom: 250,
          display: 'flex',
          alignItems: 'center',
          gap: 30,
          opacity: Math.min(1, logo * 1.6),
          transform: `translateY(${(1 - logo) * 50}px) scale(${0.9 + 0.1 * logo})`,
        }}
      >
        <div style={{position: 'relative', width: 120, height: 120}}>
          <div
            style={{
              position: 'absolute',
              inset: -14,
              borderRadius: 38,
              border: `3px solid ${C.cyan}`,
              opacity: ringO,
              transform: `scale(${ring})`,
            }}
          />
          <div
            style={{
              width: 120,
              height: 120,
              borderRadius: 30,
              background: `linear-gradient(135deg, ${C.violet}, ${C.cyan})`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: `0 18px 60px ${C.violet}66`,
            }}
          >
            <Icon name="bolt" size={64} color="#fff" />
          </div>
        </div>
        <span
          style={{
            fontSize: 96,
            fontWeight: 900,
            color: C.ink,
            letterSpacing: 10,
            textShadow: '0 10px 44px rgba(0,0,0,0.55)',
          }}
        >
          AI 落地
        </span>
      </div>

      <div
        style={{
          position: 'absolute',
          bottom: 96,
          width: '100%',
          textAlign: 'center',
          color: C.dim,
          fontSize: 26,
          fontWeight: 500,
          letterSpacing: 3,
          ...credits,
        }}
      >
        配音 · Edge TTS　｜　音乐 · 程序化生成　｜　动画 · Remotion
      </div>
    </AbsoluteFill>
  );
};
