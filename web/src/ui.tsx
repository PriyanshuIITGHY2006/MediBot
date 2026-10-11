// Restyled primitives (Phase 13): hairlines not shadows, one icon set (lucide), tabular numbers for money.
import type { ReactNode } from 'react'

export const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ')

export const inr = (v: number | null | undefined, digits = 2) =>
  v == null ? '—' : '₹' + v.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export const PLATFORM: Record<string, string> = {
  '1mg': 'Tata 1mg', apollo: 'Apollo Pharmacy', netmeds: 'Netmeds', pharmeasy: 'PharmEasy', truemeds: 'Truemeds',
  jan_aushadhi: 'Jan Aushadhi Kendra',
}
export const UNIT: Record<string, string> = { unit: 'tablet', ml: 'ml', g: 'g' }

export function Button({ children, variant = 'quiet', className, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'quiet' | 'ghost' }) {
  return (
    <button
      {...p}
      className={cx(
        'inline-flex items-center gap-1.5 rounded-[10px] px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed',
        variant === 'primary' && 'bg-navy text-sheet hover:bg-navy/90 dark:text-paper',
        variant === 'quiet' && 'border border-line bg-sheet text-ink-2 hover:border-line-2 hover:text-ink',
        variant === 'ghost' && 'text-ink-3 hover:text-ink hover:bg-line/60',
        className,
      )}
    >{children}</button>
  )
}

export function Chip({ children, onClick, tone = 'plain', title }: { children: ReactNode; onClick?: () => void; tone?: 'plain' | 'green' | 'amber' | 'red'; title?: string }) {
  const cls = cx(
    'inline-flex items-center gap-1 rounded-full border px-2.5 py-[3px] text-[12px] font-medium whitespace-nowrap',
    tone === 'plain' && 'border-line text-ink-2',
    tone === 'green' && 'border-green/30 bg-green-soft text-green',
    tone === 'amber' && 'border-amber/30 bg-amber-soft text-amber',
    tone === 'red' && 'border-red/30 bg-red-soft text-red',
    onClick && 'cursor-pointer hover:border-line-2 hover:text-ink',
  )
  return onClick ? <button className={cls} onClick={onClick} title={title}>{children}</button> : <span className={cls} title={title}>{children}</span>
}

export function Panel({ children, className, tone }: { children: ReactNode; className?: string; tone?: 'red' | 'amber' | 'green' }) {
  return (
    <div className={cx('rounded-[var(--radius-card)] border bg-sheet', tone === 'red' ? 'border-red/35' : tone === 'amber' ? 'border-amber/35' : tone === 'green' ? 'border-green/30' : 'border-line', className)}>
      {children}
    </div>
  )
}

export function Label({ children }: { children: ReactNode }) {
  return <div className="text-[11px] font-semibold uppercase tracking-[0.09em] text-ink-3">{children}</div>
}

export function Freshness({ q }: { q: { source?: string; observed?: string | null; freshness?: string } }) {
  const live = q.source === 'live' || q.source === 'cached'
  const text = q.freshness ?? (q.source === 'live' ? 'live now' : q.source === 'cached' ? 'checked recently' : `as of ${q.observed ?? 'earlier'}`)
  return <span className={cx('num text-[11px]', live ? 'text-green' : 'text-amber')}>{live ? '● ' : '○ '}{text}</span>
}
