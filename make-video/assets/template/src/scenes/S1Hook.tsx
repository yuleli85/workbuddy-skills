import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {C, FONT, gradientText} from '../theme';
import {GlassCard, useRise} from '../ui';
import {Icon} from '../icons';

const DemoBars: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const hs = [46, 82, 60, 112, 140];
  return (
    <div style={{display: 'flex', alignItems: 'flex-end', gap: 20, height: 150}}>
      {hs.map((h, i) => {
        const s = spring({frame: f - (58 + i * 6), fps, config: {damping: 12}});
        return (
          <div
            key={i}
            style={{
              width: 46,
              height: h * s,
              borderRadius: '10px 10px 4px 4px',
              background: `linear-gradient(180deg, ${C.cyan}, ${C.violet})`,
              opacity: 0.35 + 0.65 * s,
            }}
          />
        );
      })}
    </div>
  );
};

const FailLine: React.FC = () => {
  const f = useCurrentFrame();
  const draw = interpolate(f, [102, 146], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <svg width={440} height={150} viewBox="0 0 440 150">
      <polyline
        points="8,26 105,58 190,52 285,108 430,140"
        fill="none"
        stroke={C.red}
        strokeWidth={5}
        strokeLinecap="round"
        strokeDasharray="620"
        strokeDashoffset={620 * (1 - draw)}
      />
      <path
        d="M408 128 l22 12 -14 20"
        fill="none"
        stroke={C.red}
        strokeWidth={5}
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={draw > 0.92 ? draw : 0}
      />
    </svg>
  );
};

export const S1Hook: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const qDelay = Math.round(dur * 0.6);
  const q = spring({frame: f - qDelay, fps, config: {damping: 13, mass: 0.8}});
  const under = interpolate(f, [qDelay + 14, qDelay + 34], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const left = useRise(38, 60);
  const right = useRise(88, 60);

  return (
    <AbsoluteFill style={{fontFamily: FONT}}>
      {/* demo card */}
      <GlassCard
        style={{
          position: 'absolute',
          left: 300,
          top: 300,
          width: 600,
          height: 400,
          flexDirection: 'column',
          padding: 36,
          opacity: left.opacity,
          transform: `${left.transform} rotate(-1.2deg)`,
          borderColor: `${C.cyan}44`,
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', gap: 16}}>
          <Icon name="sparkle" size={40} color={C.cyan} />
          <span style={{color: C.ink, fontSize: 40, fontWeight: 700, letterSpacing: 2}}>
            演示时 · 惊艳全场
          </span>
        </div>
        <div
          style={{
            flex: 1,
            marginTop: 24,
            borderRadius: 18,
            background: 'rgba(255,255,255,0.05)',
            border: '1px solid rgba(255,255,255,0.1)',
            display: 'flex',
            flexDirection: 'column',
            padding: 20,
          }}
        >
          <div style={{display: 'flex', gap: 8}}>
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                style={{width: 12, height: 12, borderRadius: 6, background: C.dim}}
              />
            ))}
          </div>
          <div style={{flex: 1, display: 'flex', alignItems: 'flex-end'}}>
            <DemoBars />
          </div>
        </div>
      </GlassCard>

      {/* production card */}
      <GlassCard
        style={{
          position: 'absolute',
          right: 300,
          top: 300,
          width: 600,
          height: 400,
          flexDirection: 'column',
          padding: 36,
          opacity: right.opacity,
          transform: `${right.transform} rotate(1.2deg)`,
          borderColor: `${C.red}33`,
        }}
      >
        <div style={{display: 'flex', alignItems: 'center', gap: 16}}>
          <Icon name="down" size={40} color={C.red} />
          <span style={{color: C.sub, fontSize: 40, fontWeight: 700, letterSpacing: 2}}>
            上线后 · 无人问津
          </span>
        </div>
        <div
          style={{
            flex: 1,
            marginTop: 24,
            borderRadius: 18,
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <FailLine />
        </div>
      </GlassCard>

      {/* question */}
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'flex-end'}}>
        <div
          style={{
            marginBottom: 96,
            textAlign: 'center',
            opacity: Math.min(1, q * 1.8),
            transform: `scale(${0.7 + 0.3 * q})`,
          }}
        >
          <div
            style={{
              fontSize: 108,
              fontWeight: 900,
              letterSpacing: 6,
              ...gradientText(C.violet, C.cyan),
            }}
          >
            差在哪儿？
          </div>
          <div
            style={{
              marginTop: 18,
              height: 8,
              width: 420,
              borderRadius: 4,
              background: `linear-gradient(90deg, ${C.violet}, ${C.cyan})`,
              transform: `scaleX(${under})`,
              transformOrigin: 'center',
              margin: '18px auto 0',
              boxShadow: `0 0 24px ${C.cyan}66`,
            }}
          />
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
