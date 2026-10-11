// Live Medicine Sheet (Phase 14.3): the medicine the conversation is about, always one glance away.
import { useEffect, useState } from 'react'
import { BadgeCheck, Loader2, X } from 'lucide-react'
import { api, type Sheet as SheetT } from './api'
import { InterceptBanner, Receipt, SubstituteList } from './cards'
import { Button, Chip, Label, cx } from './ui'
import { Mark } from './brand'
import { t } from './i18n'

const TABS = ['Overview', 'Substitutes', 'Prices', 'Interactions'] as const
type Tab = typeof TABS[number]

export function Sheet({ productId, onClose, onAsk, onOpen }: { productId: string | null; onClose: () => void; onAsk: (q: string) => void; onOpen: (id: string) => void }) {
  const [data, setData] = useState<SheetT | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('Overview')
  const [other, setOther] = useState('')

  useEffect(() => {
    if (!productId) return
    let live = true
    setData(null); setErr(null)
    api.medicine(productId).then(d => live && setData(d)).catch(e => live && setErr(e.message))
    return () => { live = false }
  }, [productId])

  if (!productId) return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center text-sm text-ink-3">
      <Mark size={40} className="opacity-80" />
      <p className="say-sm max-w-[280px] text-ink-3">{t('Ask about a medicine. Its composition, prices across five pharmacies and identical cheaper options appear here.')}</p>
    </div>
  )

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-line px-5 pt-5 pb-3 lg:pr-12">
        {data ? (
          <div className="min-w-0 space-y-1">
            <Label>{t("Live medicine sheet")}</Label>
            <h2 className="text-[19px] font-semibold leading-tight tracking-[-0.015em] text-navy">{data.name}</h2>
            <p className="text-sm text-ink-2">{data.composition ?? t('Composition not verified')}</p>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Chip tone={data.banned || data.requires_prescription ? 'red' : data.category === 'otc' ? 'green' : 'amber'}>{data.schedule}</Chip>
              {data.therapeutic_class && <Chip>{data.therapeutic_class}</Chip>}
              {data.habit_forming && <Chip tone="amber">{t('Habit forming')}</Chip>}
              {data.manufacturer && <Chip>{data.manufacturer}</Chip>}
            </div>
          </div>
        ) : <div className="h-20 flex-1 animate-pulse rounded-lg bg-line/40" />}
        <Button variant="ghost" aria-label="Close sheet" onClick={onClose} className="lg:hidden"><X className="size-4" /></Button>
      </div>

      <div role="tablist" className="flex gap-1 border-b border-line px-4">
        {TABS.map(tb => (
          <button key={tb} role="tab" aria-selected={tab === tb} onClick={() => setTab(tb)}
            className={cx('-mb-px border-b-2 px-2.5 py-2.5 text-[13.5px] font-medium', tab === tb ? 'border-teal text-navy' : 'border-transparent text-ink-3 hover:text-ink-2')}>{t(tb)}</button>
        ))}
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {err && <p className="text-sm text-red">{err}</p>}
        {!data && !err && <div className="flex items-center gap-2 text-sm text-ink-3"><Loader2 className="size-4 animate-spin" />{t("Loading live prices…")}</div>}
        {data?.mandated_prompt && <InterceptBanner c={{ type: 'intercept_banner', lines: [data.mandated_prompt], intercept: true, banned: data.banned, text: data.mandated_prompt }} />}

        {data && tab === 'Overview' && (
          <div className="space-y-4">
            {data.image_url && (
              <figure className="flex items-center gap-3">
                <img src={data.image_url} alt={data.name} loading="lazy" referrerPolicy="no-referrer"
                  onError={e => { const f = (e.currentTarget.closest('figure') as HTMLElement | null); if (f) f.style.display = 'none' }}
                  className="size-20 rounded-lg border border-line bg-white object-contain" />
                <figcaption className="text-[11px] text-ink-3">{data.image_credit}</figcaption>
              </figure>
            )}
            {data.info ? (
              <div className="say-sm space-y-2.5">
                {data.info.text.split('\n').filter(l => l && !l.startsWith('Sources')).map((l, i) => <p key={i}>{l.replace(/\s*\[\d+\]/g, '')}</p>)}
                <ol className="space-y-0.5 pt-1 text-[11px] text-ink-3">
                  {data.info.citations.map(c => <li key={c.n}><a href={c.url} target="_blank" rel="noreferrer" className="hover:underline">[{c.n}] {c.title}{c.note ? ` — ${c.note}` : ''}</a></li>)}
                </ol>
              </div>
            ) : <p className="text-sm text-ink-3">{t('No verified information for this product.')}</p>}
          </div>
        )}

        {data && tab === 'Substitutes' && (data.substitutes?.rows.length
          ? <SubstituteList rows={data.substitutes.rows} current={data.substitutes.current_price_per_unit_inr} unit={data.substitutes.pack_unit} note={data.substitutes.note} onOpen={onOpen} />
          : <p className="text-sm text-ink-3">{data.banned ? t('Banned products get no alternatives.') : data.substitutes?.note ? `${t('Note:')} ${data.substitutes.note}.` : t('No identical alternative with a known price.')}</p>)}

        {data && tab === 'Prices' && (
          <div className="space-y-2">
            <Receipt quotes={data.prices} unit={data.substitutes?.pack_unit} />
            <p className="text-[11px] text-ink-3">{t("Prices are read from each pharmacy's product page (live, or checked within 6 h) or a dated record. Compare per unit; delivery fees are not included.")}</p>
          </div>
        )}

        {data && tab === 'Interactions' && (
          <form className="space-y-2" onSubmit={e => { e.preventDefault(); if (other.trim()) { onAsk(`Can I take ${data.name} and ${other.trim()} together?`); setOther('') } }}>
            <Label>{t("Check with another medicine")}</Label>
            <div className="flex gap-2">
              <input value={other} onChange={e => setOther(e.target.value)} placeholder={t('e.g. Crocin, alcohol, warfarin')}
                className="min-w-0 flex-1 rounded-lg border border-line bg-paper px-3 py-1.5 text-sm outline-none focus:border-line-2" />
              <Button type="submit" variant="primary">{t('Check')}</Button>
            </div>
            <p className="text-[11px] text-ink-3">{t('Checked against 208,000+ graded drug pairs (DDInter) and US drug labels. Always confirm with your pharmacist.')}</p>
          </form>
        )}

        {data && <p className="flex items-start gap-1.5 border-t border-line pt-3 text-[11px] text-ink-3"><BadgeCheck className="size-3.5 shrink-0" />{t(data.disclaimer)}</p>}
      </div>
    </div>
  )
}
