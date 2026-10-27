import React from 'react';
import {
  AbsoluteFill,
  interpolate,
  Sequence,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {C, FONT} from '../theme';
import {GlassCard, useRise} from '../ui';
import {Icon, type IconName} from '../icons';

const STEPS = [
  {n: 1, title: '选对场景', icon: 'target' as IconName, color: C.cyan},
  {n: 2, title: '喂饱数据', icon: 'database' as IconName, color: C.violet},
  {n: 3, title: '嵌入流程', icon: 'flow' as IconName, color: C.amber},
  {n: 4, title: '算清回报', icon: 'chart' as IconName, color: C.green},
];

const Stepper: React.FC<{active: number}> = ({active}) => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <div style={{position: 'absolute', top: 110, width: '100%', display: 'flex', justifyContent: 'center'}}>
      <div style={{display: 'flex', alignItems: 'center'}}>
        {STEPS.map((s, i) => (
          <React.Fragment key={s.n}>
            {i > 0 && (
              <div
                style={{
                  width: 96,
                  height: 4,
                  borderRadius: 2,
                  background: i <= active ? s.color : 'rgba(255,255,255,0.12)',
                }}
              />
            )}
            <div
              style={{
                width: 74,
                height: 74,
                borderRadius: '50%',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 34,
                fontWeight: 800,
                fontFamily: FONT,
                color: i === active ? '#0B1020' : i < active ? '#0B1020' : C.dim,
                background:
                  i === active
                    ? `linear-gradient(135deg, ${s.color}, #fff3)`
                    : i < active
                      ? s.color
                      : 'rgba(255,255,255,0.08)',
                border: `2px solid ${i <= active ? s.color : 'rgba(255,255,255,0.14)'}`,
                boxShadow: i === active ? `0 0 34px ${s.color}77` : 'none',
                transform: `scale(${i === active ? 1 + 0.06 * Math.sin(f / 5) : 1})`,
                transition: 'none',
              }}
            >
              {i < active ? '✓' : s.n}
            </div>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
};

const StepShell: React.FC<{
  index: number;
  children: React.ReactNode;
}> = ({index, children}) => {
  const s = STEPS[index];
  const r = useRise(4, 34);
  return (
    <AbsoluteFill style={{fontFamily: FONT, alignItems: 'center', justifyContent: 'center'}}>
      <Stepper active={index} />
      <GlassCard
        style={{
          width: 1520,
          height: 560,
          marginTop: 120,
          alignItems: 'center',
          padding: 64,
          gap: 64,
          opacity: r.opacity,
          transform: r.transform,
          borderColor: `${s.color}33`,
        }}
      >
        <div
          style={{
            width: 300,
            height: 300,
            borderRadius: 44,
            flexShrink: 0,
            background: `linear-gradient(150deg, ${s.color}2E, rgba(255,255,255,0.04))`,
            border: `1.5px solid ${s.color}55`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 14,
          }}
        >
          <Icon name={s.icon} size={104} color={s.color} />
          <span style={{color: C.sub, fontSize: 26, fontWeight: 700, letterSpacing: 6}}>
            STEP {s.n}
          </span>
        </div>
        <div style={{flex: 1, display: 'flex', flexDirection: 'column', gap: 34}}>
          <div style={{fontSize: 62, fontWeight: 900, color: C.ink, letterSpacing: 3}}>
            {s.title}
          </div>
          {children}
        </div>
      </GlassCard>
    </AbsoluteFill>
  );
};

const pop = (f: number, delay: number, fps: number) =>
  spring({frame: f - delay, fps, config: {damping: 14}});

const Step1: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const pills = ['高频', '高价值', '可评估'];
  return (
    <StepShell index={0}>
      <div style={{display: 'flex', gap: 26}}>
        {pills.map((p, i) => {
          const s = pop(f, 26 + i * 11, fps);
          return (
            <div
              key={p}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 14,
                padding: '22px 40px',
                borderRadius: 20,
                background: `${C.cyan}16`,
                border: `1.5px solid ${C.cyan}55`,
                fontSize: 42,
                fontWeight: 800,
                color: C.ink,
                letterSpacing: 3,
                opacity: Math.min(1, s * 1.5),
                transform: `translateY(${(1 - s) * 40}px) scale(${0.9 + 0.1 * s})`,
              }}
            >
              <span
                style={{
                  width: 40,
                  height: 40,
                  borderRadius: 12,
                  background: C.cyan,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <Icon name="check" size={26} color="#0B1020" width={3.4} />
              </span>
              {p}
            </div>
          );
        })}
      </div>
      <div style={{color: C.sub, fontSize: 34, fontWeight: 600, letterSpacing: 2}}>
        三者缺一不可 —— 这是筛选场景的硬标准
      </div>
    </StepShell>
  );
};

const Step2: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const fill = spring({frame: f - 30, fps, config: {damping: 18, mass: 1.1}});
  const tagR = (d: number) => {
    const s = pop(f, d, fps);
    return {
      opacity: Math.min(1, s * 1.5),
      transform: `translateY(${(1 - s) * 30}px)`,
    };
  };
  return (
    <StepShell index={1}>
      <div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 30,
            color: C.sub,
            fontWeight: 600,
            marginBottom: 12,
            letterSpacing: 2,
          }}
        >
          <span>数据质量</span>
          <span style={{color: C.violet}}>决定 AI 的上限</span>
        </div>
        <div
          style={{
            width: 720,
            height: 30,
            borderRadius: 15,
            background: 'rgba(255,255,255,0.08)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${92 * fill}%`,
              height: '100%',
              borderRadius: 15,
              background: `linear-gradient(90deg, ${C.violet}, ${C.cyan})`,
              boxShadow: `0 0 22px ${C.violet}55`,
            }}
          />
        </div>
      </div>
      <div style={{display: 'flex', gap: 28, alignItems: 'center'}}>
        <div
          style={{
            ...tagR(62),
            padding: '16px 34px',
            borderRadius: 16,
            background: `${C.red}16`,
            border: `1.5px solid ${C.red}55`,
            color: C.red,
            fontSize: 34,
            fontWeight: 700,
            letterSpacing: 2,
          }}
        >
          垃圾进 → 垃圾出
        </div>
        <div
          style={{
            ...tagR(84),
            padding: '16px 34px',
            borderRadius: 16,
            background: `${C.green}16`,
            border: `1.5px solid ${C.green}55`,
            color: C.green,
            fontSize: 34,
            fontWeight: 700,
            letterSpacing: 2,
          }}
        >
          数据干净 → 上限更高
        </div>
      </div>
    </StepShell>
  );
};

const Step3: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const nodes = ['需求', 'AI 处理', '人工确认', '交付'];
  const colors = [C.sub, C.violet, C.cyan, C.green];
  return (
    <StepShell index={2}>
      <div style={{display: 'flex', alignItems: 'center', gap: 18}}>
        {nodes.map((n, i) => {
          const s = pop(f, 26 + i * 12, fps);
          const glow = i === 1 ? 1 + 0.035 * Math.sin(f / 5) : 1;
          return (
            <React.Fragment key={n}>
              {i > 0 && (
                <div style={{opacity: pop(f, 22 + i * 12, fps) * 0.9}}>
                  <Icon name="arrow" size={34} color={C.dim} width={2.6} />
                </div>
              )}
              <div
                style={{
                  padding: '24px 34px',
                  borderRadius: 18,
                  background:
                    i === 1
                      ? `linear-gradient(135deg, ${C.violet}33, ${C.violet}11)`
                      : 'rgba(255,255,255,0.06)',
                  border: `1.5px solid ${i === 1 ? C.violet : 'rgba(255,255,255,0.14)'}`,
                  fontSize: 36,
                  fontWeight: 800,
                  color: i === 1 ? '#fff' : C.ink,
                  letterSpacing: 2,
                  boxShadow: i === 1 ? `0 0 34px ${C.violet}55` : 'none',
                  opacity: Math.min(1, s * 1.5),
                  transform: `translateY(${(1 - s) * 36}px) scale(${glow})`,
                }}
              >
                {n}
              </div>
            </React.Fragment>
          );
        })}
      </div>
      <div style={{color: C.sub, fontSize: 34, fontWeight: 600, letterSpacing: 2}}>
        让 AI 长在业务流程里，而不是做一个孤立的演示品
      </div>
    </StepShell>
  );
};

const Step4: React.FC = () => {
  const f = useCurrentFrame();
  const {fps} = useVideoConfig();
  const metrics = [
    {label: '效率', dir: 'up' as const, color: C.green, w: 0.82},
    {label: '成本', dir: 'down' as const, color: C.cyan, w: 0.66},
    {label: '质量', dir: 'up' as const, color: C.violet, w: 0.9},
  ];
  return (
    <StepShell index={3}>
      <div style={{display: 'flex', gap: 30}}>
        {metrics.map((m, i) => {
          const s = spring({frame: f - (26 + i * 11), fps, config: {damping: 16}});
          return (
            <div
              key={m.label}
              style={{
                width: 240,
                padding: '26px 0 30px',
                borderRadius: 22,
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid rgba(255,255,255,0.12)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 12,
                opacity: Math.min(1, s * 1.5),
                transform: `translateY(${(1 - s) * 40}px)`,
              }}
            >
              <span style={{fontSize: 36, fontWeight: 800, color: C.ink, letterSpacing: 3}}>
                {m.label}
              </span>
              <Icon name={m.dir === 'up' ? 'chart' : 'down'} size={44} color={m.color} />
              <div
                style={{
                  width: 170,
                  height: 16,
                  borderRadius: 8,
                  background: 'rgba(255,255,255,0.08)',
                  overflow: 'hidden',
                }}
              >
                <div
                  style={{
                    width: `${m.w * s * 100}%`,
                    height: '100%',
                    borderRadius: 8,
                    background: m.color,
                    boxShadow: `0 0 16px ${m.color}66`,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
      <div style={{color: C.sub, fontSize: 34, fontWeight: 600, letterSpacing: 2}}>
        效率提升、成本下降、质量可控 —— 用数字说话
      </div>
    </StepShell>
  );
};

const STEP_COMPONENTS = [Step1, Step2, Step3, Step4];

export const S3Steps: React.FC<{durs: number[]}> = ({durs}) => {
  let cum = 0;
  return (
    <>
      {STEP_COMPONENTS.map((Cmp, i) => {
        const from = cum;
        cum += durs[i];
        return (
          <Sequence key={i} from={from} durationInFrames={durs[i]}>
            <StepFade dur={durs[i]}>
              <Cmp />
            </StepFade>
          </Sequence>
        );
      })}
    </>
  );
};

const StepFade: React.FC<{dur: number; children: React.ReactNode}> = ({dur, children}) => {
  const f = useCurrentFrame();
  const opacity = interpolate(f, [0, 8, dur - 10, dur - 1], [0, 1, 1, 0.25], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return <AbsoluteFill style={{opacity}}>{children}</AbsoluteFill>;
};
