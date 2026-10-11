// The MediBot mark and wordmark, from the brand SVGs (public/brand/). Inline so the navy outline follows the theme
// (in the source files the navy disappears on dark backgrounds) and so the cross can pulse while MediBot thinks.
import { useId } from 'react'
import { cx } from './ui'

export function Mark({ size = 28, thinking = false, className }: { size?: number; thinking?: boolean; className?: string }) {
  const gid = useId().replace(/:/g, '')
  return (
    <svg width={size} height={size} viewBox="0 0 232 232" fill="none" aria-hidden className={cx('shrink-0', className)}>
      <defs>
        <linearGradient id={gid} x1="45" y1="30" x2="180" y2="170" gradientUnits="userSpaceOnUse">
          <stop stopColor="#19C6B4" /><stop offset="1" stopColor="#0DA99E" />
        </linearGradient>
      </defs>
      <g transform="translate(24 24)">
        <path d="M42 10H142C164.1 10 182 27.9 182 50V118C182 140.1 164.1 158 142 158H87L53 184V158H42C19.9 158 2 140.1 2 118V50C2 27.9 19.9 10 42 10Z"
          className="stroke-navy" strokeWidth="12" strokeLinejoin="round" />
        <circle cx="92" cy="84" r="42" className="fill-pale" />
        <path className={cx(thinking && 'mb-pulse')} fill={`url(#${gid})`}
          d="M82 58C82 55.8 83.8 54 86 54H98C100.2 54 102 55.8 102 58V74H118C120.2 74 122 75.8 122 78V90C122 92.2 120.2 94 118 94H102V110C102 112.2 100.2 114 98 114H86C83.8 114 82 112.2 82 110V94H66C63.8 94 62 92.2 62 90V78C62 75.8 63.8 74 66 74H82V58Z" />
        <circle cx="151" cy="31" r="9" className={cx('fill-mint stroke-sheet', thinking && 'mb-dot')} strokeWidth="5" />
      </g>
    </svg>
  )
}

export function Wordmark({ size = 'md', underline = false }: { size?: 'md' | 'lg'; underline?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2">
      <Mark size={size === 'lg' ? 44 : 28} />
      <span className="flex flex-col">
        <span className={cx('font-bold leading-none tracking-[-0.03em] text-navy', size === 'lg' ? 'text-[28px]' : 'text-[18px]')}>
          Medi<span className="text-teal">Bot</span>
        </span>
        {underline && <span className="mt-1.5 flex items-center gap-1"><span className="h-[3px] w-24 rounded-full bg-pale" /><span className="size-[5px] rounded-full bg-teal mb-dot" /></span>}
      </span>
    </span>
  )
}
