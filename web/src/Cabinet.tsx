// My Cabinet (Phase 15.3): the medicines someone takes every day, kept ONLY in this browser (localStorage).
// Monthly cost and the cheapest identical option come from /api/v1/cabinet/check (nothing stored server-side);
// refill reminders are an .ics file made here; a price drop is today's price vs the one seen at the last check.
// Doses per day and stock are what the user enters - nothing here suggests a dose.
import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowDownRight, ArrowUpRight, BadgeCheck, CalendarPlus, IdCard, Pill, Receipt, RefreshCw, Trash2 } from 'lucide-react'
import { cabinetCheck, type CabinetResult, type SearchHit } from './api'
import { Adder, Qty } from './Bill'
import { Mark } from './brand'
import { t } from './i18n'
import { PharmacistCard } from './PharmacistCard'
import { Button, Chip, Label, Panel, PLATFORM, UNIT, cx, inr } from './ui'

type Med = {
  id: string; product_id: string; name: string; composition: string | null; rx: boolean
  per_day: number; stock: number; stock_date: string            // stock counted on stock_date (YYYY-MM-DD)
  last_ppu?: number | null; prev_ppu?: number | null; last_checked?: string
}
const KEY = 'mb-cabinet'
const uid = () => Math.random().toString(36).slice(2, 10)
const today = () => new Date().toISOString().slice(0, 10)
const load = (): Med[] => { try { return JSON.parse(localStorage.getItem(KEY) ?? '[]') } catch { return [] } }
const DAY = 86_400_000

function runout(m: Med): Date {
  return new Date(new Date(m.stock_date + 'T09:00:00').getTime() + Math.floor(m.stock / m.per_day) * DAY)
}
const daysLeft = (m: Med) => Math.ceil((runout(m).getTime() - Date.now()) / DAY)

function ics(meds: Med[]): string {
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+/, '')
  const esc = (s: string) => s.replace(/[\\,;]/g, m => '\\' + m).replace(/\n/g, '\\n')
  const ev = meds.map(m => {
    const d = new Date(Math.max(runout(m).getTime() - 3 * DAY, Date.now() + DAY))
    const ymd = d.toISOString().slice(0, 10).replace(/-/g, '')
    return ['BEGIN:VEVENT', `UID:${m.id}-${ymd}@medibot`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${ymd}`,
      `SUMMARY:${esc(`Refill ${m.name}`)}`,
      `DESCRIPTION:${esc(`${m.name} runs out around ${runout(m).toDateString()} (${m.stock} left on ${m.stock_date}, ${m.per_day} a day). Reminder from MediBot - informational, not medical advice.`)}`,
      'BEGIN:VALARM', 'ACTION:DISPLAY', `DESCRIPTION:${esc(`Refill ${m.name}`)}`, 'TRIGGER:PT9H', 'END:VALARM', 'END:VEVENT'].join('\r\n')
  })
  return ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//MediBot//Cabinet//EN', 'CALSCALE:GREGORIAN', ...ev, 'END:VCALENDAR'].join('\r\n')
}
function download(name: string, body: string, type: string) {
  const u = URL.createObjectURL(new Blob([body], { type }))
  const a = Object.assign(document.createElement('a'), { href: u, download: name })
  a.click(); setTimeout(() => URL.revokeObjectURL(u), 1000)
}

export function CabinetPage({ onOpen, onPlan }: { onOpen: (id: string) => void; onPlan: (lines: { name: string; product_id: string; quantity: number }[]) => void }) {
  const [meds, setMeds] = useState<Med[]>(load)
  const [res, setRes] = useState<CabinetResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [card, setCard] = useState(false)
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(meds)) } catch { /* private mode */ } }, [meds])

  const add = (h: SearchHit) => setMeds(m => m.some(x => x.product_id === h.product_id) ? m
    : [...m, { id: uid(), product_id: h.product_id, name: h.name, composition: h.composition, rx: h.requires_prescription, per_day: 1, stock: 30, stock_date: today() }])
  const upd = (id: string, p: Partial<Med>) => setMeds(m => m.map(x => x.id === id ? { ...x, ...p } : x))
  const check = async (list = meds) => {
    if (!list.length) return
    setBusy(true); setErr(null)
    try {
      const r = await cabinetCheck(list.map(m => ({ product_id: m.product_id, per_day: m.per_day })))
      setRes(r)
      // remember today's price; the previous one stays for the drop / rise flag
      setMeds(ms => ms.map(m => {
        const row = r.items.find(x => x.product_id === m.product_id)
        const ppu = row?.price_per_unit_inr
        return ppu ? { ...m, prev_ppu: m.last_ppu ?? null, last_ppu: ppu, last_checked: today() } : m
      }))
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const row = (pid: string) => res?.items.find(x => x.product_id === pid)
  const sev = (s: string) => s === 'Major' || s === 'duplicate' ? 'red' : s === 'Moderate' ? 'amber' : 'plain'

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-[860px] space-y-6 px-4 pt-8 pb-14 sm:px-5">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-green"><Pill className="size-4" /><Label>{t('Cabinet')}</Label></div>
          <h1 className="display text-[30px] leading-tight text-navy">{t('My medicine cabinet')}</h1>
          <p className="say-sm text-ink-2">{t('Medicines you take regularly. Saved only on this device.')}</p>
        </div>

        <Adder onAdd={add} />

        {!meds.length ? (
          <div className="grid place-items-center rounded-[var(--radius-card)] border border-dashed border-line px-6 py-12 text-center">
            <Pill className="mb-2 size-8 text-line-2" />
            <p className="font-medium text-navy">{t('Your cabinet is empty')}</p>
            <p className="say-sm max-w-sm text-ink-3">{t('Add the medicines you take every day to track cost, refills and interactions.')}</p>
          </div>
        ) : <>
          {res && res.monthly_inr > 0 && (
            <div className="grid grid-cols-3 gap-2 sm:gap-3 rise">
              <Panel className="p-3 sm:p-4"><div className="text-[11.5px] sm:text-[12px] text-ink-3">{t('Monthly cost')}</div><div className="num text-[19px] sm:text-[24px] font-semibold text-navy">{inr(res.monthly_inr, 0)}</div></Panel>
              <Panel className="p-3 sm:p-4"><div className="text-[11.5px] sm:text-[12px] text-ink-3">{t('cheapest identical')}</div><div className="num text-[19px] sm:text-[24px] font-semibold text-navy">{inr(res.monthly_best_inr, 0)}</div></Panel>
              <Panel tone="green" className="bg-pale/50 p-3 sm:p-4"><div className="text-[11.5px] sm:text-[12px] text-green">{t('you could save')}</div><div className="num text-[19px] sm:text-[24px] font-semibold text-green">{inr(res.monthly_savings_inr, 0)}<span className="text-[13px] font-normal">/mo</span></div></Panel>
            </div>
          )}

          <Panel className="divide-y divide-line">
            {meds.map(m => {
              const r = row(m.product_id)
              const left = daysLeft(m)
              const drift = m.prev_ppu && m.last_ppu ? (m.last_ppu - m.prev_ppu) / m.prev_ppu : 0
              return (
                <div key={m.id} className="space-y-2.5 p-4">
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <button onClick={() => onOpen(m.product_id)} className="text-left text-[15.5px] font-semibold text-navy hover:underline decoration-teal/40 underline-offset-4">{m.name}</button>
                      <div className="flex flex-wrap items-center gap-1.5 text-[12.5px] text-ink-3">
                        {m.rx && <span className="font-semibold text-red">Rx</span>}<span className="truncate">{m.composition ?? t('composition not verified')}</span>
                      </div>
                    </div>
                    <button aria-label={t('Remove')} onClick={() => setMeds(x => x.filter(y => y.id !== m.id))} className="text-ink-3 hover:text-red"><Trash2 className="size-4" /></button>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-[13px]">
                    <label className="flex items-center gap-2"><span className="text-ink-2">{t('per day')}</span><Qty value={m.per_day} onChange={n => upd(m.id, { per_day: n })} /></label>
                    <label className="flex items-center gap-2"><span className="text-ink-2">{t('in hand')}</span><Qty value={m.stock} onChange={n => upd(m.id, { stock: n, stock_date: today() })} /></label>
                    <span className={cx('num', left <= 3 ? 'font-semibold text-red' : left <= 7 ? 'text-amber' : 'text-ink-2')}>
                      {t('Runs out')}: {left <= 0 ? t('today') : t('in {n} days', { n: left })} · {runout(m).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}
                    </span>
                  </div>
                  {r && r.status === 'ok' && (
                    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-[10px] bg-line/35 px-3 py-2 text-[13px]">
                      <span className="num"><span className="font-semibold">{inr(r.monthly_inr)}</span><span className="text-ink-3">/mo · {inr(r.price_per_unit_inr)}/{t(UNIT[r.pack_unit ?? 'unit'] ?? 'unit')}{r.cheapest_platform ? ` · ${PLATFORM[r.cheapest_platform] ?? r.cheapest_platform}` : ''}</span></span>
                      {Math.abs(drift) >= 0.03 && <Chip tone={drift < 0 ? 'green' : 'amber'}>{drift < 0 ? <ArrowDownRight className="size-3" /> : <ArrowUpRight className="size-3" />}{t(drift < 0 ? 'Price dropped' : 'Price went up')} {Math.round(Math.abs(drift) * 100)}%</Chip>}
                      {r.best_alternative && (
                        <span className="flex items-center gap-1 text-green"><BadgeCheck className="size-3.5" />
                          <button className="hover:underline" onClick={() => !r.best_alternative!.product_id.startsWith('ja_') && onOpen(r.best_alternative!.product_id)}>{r.best_alternative.brand_name.replace(/^Jan Aushadhi: /, 'Jan Aushadhi · ')}</button>
                          <span className="num">{inr(r.best_alternative.monthly_inr)}/mo</span>
                          {r.best_alternative.savings_percentage ? <span className="num font-medium">−{Math.round(r.best_alternative.savings_percentage)}%</span> : null}
                        </span>)}
                    </div>)}
                  {r && r.status !== 'ok' && <p className="text-[12.5px] text-amber">{r.note ?? (r.status === 'no_price' ? t('no current price from a delivering pharmacy') : r.status)}</p>}
                </div>)
            })}
          </Panel>

          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => check()} disabled={busy}><RefreshCw className={cx('size-4', busy && 'animate-spin')} />{busy ? t('Checking…') : t('Check prices')}</Button>
            <Button onClick={() => download('medibot-refills.ics', ics(meds), 'text/calendar')}><CalendarPlus className="size-4" />{t('Add to calendar')}</Button>
            <Button onClick={() => onPlan(meds.map(m => ({ name: m.name, product_id: m.product_id, quantity: Math.min(1000, m.per_day * 30) })))}><Receipt className="size-4" />{t('Plan a monthly bill')}</Button>
            <Button onClick={() => setCard(true)}><IdCard className="size-4" />{t('Show to pharmacist')}</Button>
          </div>
          {err && <p className="text-[13px] text-red">{err}</p>}
          {meds.some(m => m.last_checked) && <p className="text-[11.5px] text-ink-3">{t('last checked {d}', { d: meds.map(m => m.last_checked).filter(Boolean).sort().pop() ?? '' })}</p>}

          {res && meds.length >= 2 && (
            <Panel tone={res.interactions.some(f => sev(f.severity) === 'red') ? 'red' : res.interactions.length ? 'amber' : 'green'} className="space-y-2.5 p-4 rise">
              <div className="flex items-center gap-2"><AlertTriangle className="size-4 text-amber" /><Label>{t('Interaction check')}</Label></div>
              {res.interactions.length ? <>
                {res.interactions.map((f, i) => (
                  <div key={i} className="flex items-start gap-2.5 text-[13.5px]">
                    <span className="shrink-0 pt-0.5"><Chip tone={sev(f.severity) as 'red' | 'amber' | 'plain'}>{f.severity === 'duplicate' ? t('Same ingredient') : t(f.severity)}</Chip></span>
                    <p className="leading-snug">{f.text}</p>
                  </div>))}
                <p className="text-[12.5px] text-ink-2">{t(res.interaction_advice)}</p>
              </> : <p className="text-[13.5px] text-ink-2">{t('No interactions found between these medicines in our sources.')}</p>}
            </Panel>
          )}

          <div className="flex gap-2.5 rounded-[12px] bg-line/40 p-3 text-[12px] text-ink-2">
            <Mark size={18} className="mt-0.5" />
            <div className="space-y-1"><p>{t('Doses per day and stock are what you enter — MediBot never suggests a dose.')}</p><p>{res && t(res.advisory)}</p><p className="text-ink-3">{res && t(res.disclaimer)}</p></div>
          </div>
        </>}
      </div>
      {card && <PharmacistCard title={t('Medicine list')} onClose={() => setCard(false)} total={res?.monthly_inr}
        lines={meds.map(m => {
          const r = row(m.product_id)
          return { asked: m.name, asked_composition: m.composition, chosen: m.name, same: true, rx: m.rx,
            qty: `${m.per_day * 30} / 30 d`, price: r?.monthly_inr ?? null, where: r?.cheapest_platform ? PLATFORM[r.cheapest_platform] ?? r.cheapest_platform : null }
        })} />}
    </div>
  )
}
