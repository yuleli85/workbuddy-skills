import type {CSSProperties} from 'react';

export const C = {
  bg: '#060913',
  ink: '#F4F6FF',
  sub: '#9AA3C0',
  dim: '#5A6480',
  violet: '#8B5CF6',
  cyan: '#22D3EE',
  amber: '#FBBF24',
  green: '#34D399',
  pink: '#F472B6',
  red: '#F87171',
};

export const FONT =
  "'PingFang SC','Hiragino Sans GB','Noto Sans SC','Microsoft YaHei',sans-serif";

export const gradientText = (from: string, to: string): CSSProperties => ({
  backgroundImage: `linear-gradient(100deg, ${from}, ${to})`,
  WebkitBackgroundClip: 'text',
  backgroundClip: 'text',
  color: 'transparent',
});
