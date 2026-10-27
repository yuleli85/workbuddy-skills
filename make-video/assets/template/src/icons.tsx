import React from 'react';

export type IconName =
  | 'target'
  | 'database'
  | 'flow'
  | 'chart'
  | 'sparkle'
  | 'plug'
  | 'building'
  | 'check'
  | 'cross'
  | 'bolt'
  | 'arrow'
  | 'down';

const paths: Record<IconName, React.ReactNode> = {
  target: (
    <>
      <circle cx="12" cy="12" r="8.2" />
      <circle cx="12" cy="12" r="4.4" />
      <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5.5" rx="7" ry="2.7" />
      <path d="M5 5.5v6.4c0 1.5 3.1 2.7 7 2.7s7-1.2 7-2.7V5.5" />
      <path d="M5 11.9v6.4c0 1.5 3.1 2.7 7 2.7s7-1.2 7-2.7v-6.4" />
    </>
  ),
  flow: (
    <>
      <rect x="2.6" y="9" width="5.2" height="6" rx="1.6" />
      <rect x="16.2" y="3" width="5.2" height="6" rx="1.6" />
      <rect x="16.2" y="15" width="5.2" height="6" rx="1.6" />
      <path d="M7.8 12h3.4m0 0V6a2 2 0 0 1 2-2h3m-5.4 8v6a2 2 0 0 0 2 2h3" />
    </>
  ),
  chart: (
    <>
      <path d="M3.5 4v16h17" />
      <path d="M6.5 16.5l4.2-5.2 3 2.6 5.3-6.9" />
      <path d="M15.8 6.8h3.4v3.4" />
    </>
  ),
  sparkle: (
    <>
      <path d="M12 3.2l1.9 5.4 5.4 1.9-5.4 1.9L12 17.8l-1.9-5.4-5.4-1.9 5.4-1.9z" />
      <path d="M18.6 15.4l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" strokeWidth="1.6" />
    </>
  ),
  plug: (
    <>
      <path d="M9 2.8v5M15 2.8v5" />
      <path d="M7 7.8h10v3.4a5 5 0 0 1-5 5 5 5 0 0 1-5-5z" />
      <path d="M12 16.2v5" />
    </>
  ),
  building: (
    <>
      <rect x="4.5" y="3.5" width="9" height="17" rx="1.2" />
      <path d="M13.5 9.5h6v11h-6" />
      <path d="M7.5 7.5h3M7.5 11h3M7.5 14.5h3M16.5 12.5h.01M16.5 16h.01" />
    </>
  ),
  check: <path d="M4.5 12.6l5 5L19.5 6.4" />,
  cross: <path d="M6 6l12 12M18 6L6 18" />,
  bolt: <path d="M13.2 2.4L4.6 13.6h6L9.4 21.6 19 10.2h-6.2z" />,
  arrow: (
    <>
      <path d="M4 12h15" />
      <path d="M13.5 6.5L19.5 12l-6 5.5" />
    </>
  ),
  down: (
    <>
      <path d="M12 4v15" />
      <path d="M6.5 13.5L12 19.5l5.5-6" />
    </>
  ),
};

export const Icon: React.FC<{
  name: IconName;
  size?: number;
  color?: string;
  width?: number;
  style?: React.CSSProperties;
}> = ({name, size = 48, color = 'currentColor', width = 2.2, style}) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="none"
    stroke={color}
    strokeWidth={width}
    strokeLinecap="round"
    strokeLinejoin="round"
    style={style}
  >
    {paths[name]}
  </svg>
);
