import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {C, FONT} from '../theme';
import {GlassCard, SceneTitle, springy, useRise} from '../ui';
import {Icon, type IconName} from '../icons';

const NODES: {
  label: string;
  icon: IconName;
  color: string;
  x: number;
  y: number;
}[] = [
  {label: '场景', icon: 'target', color: C.cyan, x: 960, y: 285},
  {label: '数据', icon: 'database', color: C.violet, x: 1260, y: 585},
  {label: '流程', icon: 'flow', color: C.amber, x: 960, y: 885},
  {label: '回报', icon: 'chart', color: C.green, x: 660, y: 585},
];

export const S4Loop: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const R = 300;
  const CY = 585;
  const CIRC = 2 * Math.PI * R;
  const draw = interpolate(f, [16, 92], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const centerS = spring({frame: f - 100, fps, config: {damping: 12}});
  const pulse = 1 + 0.035 * Math.sin(f / 6);

  return (
    <AbsoluteFill style={{fontFamily: FONT, alignItems: 'center'}}>
      <SceneTitle
        text={
          <>
            四环相扣 · <span style={{color: C.cyan}}>形成闭环</span>
          </>
        }
        style={{position: 'absolute', top: 96}}
      />

      <svg
        width={1920}
        height={1080}
        style={{position: 'absolute', inset: 0, pointerEvents: 'none'}}
      >
        {/* main ring draws in */}
        <circle
          cx={960}
          cy={CY}
          r={R}
          fill="none"
          stroke="rgba(148,163,220,0.35)"
          strokeWidth={5}
          strokeLinecap="round"
          strokeDasharray={CIRC}
          strokeDashoffset={CIRC * (1 - draw)}
          transform={`rotate(-90 960 ${CY})`}
        />
        {/* flowing dashed ring */}
        <g style={{transformOrigin: `960px ${CY}px`, transform: `rotate(${f * 0.55}deg)`}}>
          <circle
            cx={960}
            cy={CY}
            r={R}
            fill="none"
            stroke={`${C.cyan}66`}
            strokeWidth={9}
            strokeLinecap="round"
            strokeDasharray="26 200"
          />
          <circle
            cx={960}
            cy={CY}
            r={R}
            fill="none"
            stroke={`${C.violet}55`}
            strokeWidth={9}
            strokeLinecap="round"
            strokeDasharray="26 200"
            strokeDashoffset={113}
          />
        </g>
      </svg>

      {/* center hub */}
      <div
        style={{
          position: 'absolute',
          left: 960,
          top: CY,
          transform: `translate(-50%,-50%) scale(${(0.7 + 0.3 * centerS) * pulse})`,
          opacity: Math.min(1, centerS * 1.6),
        }}
      >
        <div
          style={{
            width: 260,
            height: 260,
            borderRadius: '50%',
            background: `radial-gradient(circle at 35% 30%, ${C.violet}55, ${C.violet}18 60%, rgba(255,255,255,0.03))`,
            border: '2px solid rgba(255,255,255,0.22)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 6,
            boxShadow: `0 0 90px ${C.violet}55, inset 0 0 40px ${C.cyan}22`,
          }}
        >
          <Icon name="bolt" size={54} color={C.cyan} />
          <span style={{fontSize: 42, fontWeight: 900, color: C.ink, letterSpacing: 4}}>
            AI 生产力
          </span>
        </div>
      </div>

      {/* nodes */}
      {NODES.map((n, i) => {
        const s = spring({frame: f - (28 + i * 16), fps, config: {damping: 14}});
        return (
          <div
            key={n.label}
            style={{
              position: 'absolute',
              left: n.x,
              top: n.y,
              transform: `translate(-50%,-50%) translateY(${(1 - s) * 44}px) scale(${0.85 + 0.15 * s})`,
              opacity: Math.min(1, s * 1.6),
            }}
          >
            <GlassCard
              style={{
                width: 190,
                height: 190,
                borderRadius: '50%',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
                borderColor: `${n.color}55`,
                boxShadow: `0 0 44px ${n.color}33`,
              }}
            >
              <Icon name={n.icon} size={52} color={n.color} />
              <span style={{fontSize: 36, fontWeight: 800, color: C.ink, letterSpacing: 3}}>
                {n.label}
              </span>
            </GlassCard>
          </div>
        );
      })}
    </AbsoluteFill>
  );
};
