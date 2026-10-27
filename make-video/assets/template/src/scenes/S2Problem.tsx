import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {C, FONT} from '../theme';
import {GlassCard, SceneTitle, useRise} from '../ui';
import {Icon} from '../icons';

const NodeCard: React.FC<{
  x: React.CSSProperties['left'];
  delay: number;
  icon: React.ComponentProps<typeof Icon>['name'];
  title: string;
  sub: string;
  subColor: string;
  flip?: boolean;
}> = ({x, delay, icon, title, sub, subColor, flip}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame: f - delay, fps, config: {damping: 15}});
  return (
    <GlassCard
      style={{
        position: 'absolute',
        left: x,
        top: 300,
        width: 460,
        height: 330,
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 18,
        opacity: Math.min(1, s * 1.5),
        transform: `translateY(${(1 - s) * 60}px) scale(${0.92 + 0.08 * s})`,
      }}
    >
      <div
        style={{
          width: 110,
          height: 110,
          borderRadius: 28,
          background: 'rgba(255,255,255,0.07)',
          border: '1px solid rgba(255,255,255,0.12)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transform: flip ? 'scaleX(-1)' : undefined,
        }}
      >
        <Icon name={icon} size={62} color={C.cyan} />
      </div>
      <div style={{fontSize: 44, fontWeight: 800, color: C.ink, letterSpacing: 2}}>
        {title}
      </div>
      <div style={{fontSize: 30, fontWeight: 600, color: subColor, letterSpacing: 2}}>
        {sub}
      </div>
    </GlassCard>
  );
};

const draw_fade = (ff: number) =>
  ff < 150
    ? 1
    : interpolate(ff, [150, 172], [1, 0.3], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      });

export const S2Problem: React.FC<{dur: number}> = ({dur}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const lineIn = interpolate(f, [88, 96], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const shakeT = f - 148;
  const shake =
    shakeT > 0 && shakeT < 22 ? Math.sin(shakeT * 2.4) * 7 * (1 - shakeT / 22) : 0;
  const bang = spring({frame: f - 150, fps, config: {damping: 11}});
  const chips = [
    {label: '场景', color: C.cyan},
    {label: '数据', color: C.violet},
    {label: '流程', color: C.amber},
    {label: '回报', color: C.green},
  ];
  const chipsRise = useRise(Math.round(dur * 0.54), 40);
  const captionRise = useRise(Math.round(dur * 0.48), 26);

  return (
    <AbsoluteFill style={{fontFamily: FONT, alignItems: 'center'}}>
      <SceneTitle
        text={
          <>
            AI 落地{' '}
            <span style={{color: C.amber, display: 'inline-block'}}>≠</span> 调个
            API
          </>
        }
        style={{position: 'absolute', top: 130}}
      />

      <NodeCard
        x={230}
        delay={48}
        icon="plug"
        title="大模型 API"
        sub="✓ 演示能跑"
        subColor={C.green}
      />
      <NodeCard
        x={1230}
        delay={68}
        icon="building"
        title="业务系统"
        sub="✗ 上线就翻车"
        subColor={C.red}
        flip
      />

      {/* connector */}
      <svg
        width={1920}
        height={1080}
        style={{position: 'absolute', left: 0, top: 0, pointerEvents: 'none'}}
      >
        <g transform={`translate(${shake},0)`}>
          <line
            x1={700}
            y1={465}
            x2={1220}
            y2={465}
            stroke={C.sub}
            strokeWidth={5}
            strokeDasharray="14 12"
            strokeDashoffset={-f * 1.4}
            opacity={lineIn * (draw_fade(f))}
          />
          <g
            transform={`translate(960,465) scale(${bang})`}
            opacity={bang > 0.05 ? 1 : 0}
          >
            <circle r={44} fill={`${C.red}22`} stroke={C.red} strokeWidth={3} />
            <path
              d="M-16 -16 L16 16 M16 -16 L-16 16"
              stroke={C.red}
              strokeWidth={6}
              strokeLinecap="round"
            />
          </g>
        </g>
      </svg>

      {/* challenges */}
      <div
        style={{
          position: 'absolute',
          bottom: 210,
          ...captionRise,
          color: C.sub,
          fontSize: 38,
          fontWeight: 600,
          letterSpacing: 4,
          width: '100%',
          textAlign: 'center',
        }}
      >
        真正的挑战，藏在这四件事里
      </div>
      <div
        style={{
          position: 'absolute',
          bottom: 92,
          width: '100%',
          display: 'flex',
          justifyContent: 'center',
          gap: 34,
          opacity: chipsRise.opacity,
          transform: chipsRise.transform,
        }}
      >
        {chips.map((c, i) => {
          const s = spring({
            frame: f - (Math.round(dur * 0.56) + i * 10),
            fps,
            config: {damping: 14},
          });
          return (
            <div
              key={c.label}
              style={{
                padding: '20px 52px',
                borderRadius: 22,
                background: `${c.color}1A`,
                border: `1.5px solid ${c.color}55`,
                fontSize: 44,
                fontWeight: 800,
                color: C.ink,
                letterSpacing: 4,
                opacity: Math.min(1, s * 1.5),
                transform: `translateY(${(1 - s) * 46}px)`,
                boxShadow: `0 12px 40px ${c.color}22`,
              }}
            >
              {c.label}
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
