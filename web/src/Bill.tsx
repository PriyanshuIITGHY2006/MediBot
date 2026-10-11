// Bill split (Phase 15.1): build a medicine list, get the cheapest way to buy all of it across pharmacies.
// The planner is exact (backend/medibot/billplan.py); this page only shows what it returns, never re-computes.
import { useEffect, useRef, useState } from 'react'
import { ArrowRight, Camera, IdCard, Check, ClipboardList, ScanText, ShieldCheck, Wand2, ExternalLink, Info, Minus, Plus, Receipt, Repeat2, Search, Sparkles, Store, Trash2, X } from 'lucide-react'
import { api, billApi, readBill, type ReadLine, type BillCart, type BillLine, type BillPlan, type BillResult, type SearchHit } from './api'
import { Mark } from './brand'
import { t } from './i18n'
import { PharmacistCard, type CardLine } from './PharmacistCard'
import { Button, Chip, Freshness, Label, Panel, PLATFORM, cx, inr } from './ui'

type Row = BillLine & { id: string; composition?: string | null; rx?: boolean }
type View = 'best' | 'as_asked' | 'one_stop' | 'jan_aushadhi'

const uid = () => Math.random().toString(36).slice(2, 10)
const KEY = 'mb-bill'
const SAMPLE = 'Dolo 650 x 30\nPan 40 x 15\nTelma 40 x 30\nAugmentin 625 Duo x 10'
const load = (): Row[] => { try { return JSON.parse(localStorage.getItem(KEY) ?? '[]') } catch { return [] } }

// ---------------------------------------------------------------- add a medicine (search-as-you-type)
export function Adder({ onAdd }: { onAdd: (h: SearchHit) => void }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [i, setI] = useState(0)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return }
    const t = setTimeout(() => api.search(q).then(r => { setHits(r.results); setI(0) }).catch(() => setHits([])), 160)
    return () => clearTimeout(t)
  }, [q])
  const pick = (h: SearchHit) => { onAdd(h); setQ(''); setHits([]) }
  return (
    <div className="relative">
      <div className="flex items-center gap-2 rounded-[12px] border border-line bg-sheet px-3 transition focus-within:border-teal/60">
        <Search className="size-4 text-ink-3" />
        <input value={q} onChange={e => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
          aria-label="Add a medicine" placeholder={t('Add a medicine — brand or generic')}
          onKeyDown={e => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setI(x => Math.min(x + 1, hits.length - 1)) }
            if (e.key === 'ArrowUp') { e.preventDefault(); setI(x => Math.max(x - 1, 0)) }
            if (e.key === 'Enter' && hits[i]) { e.preventDefault(); pick(hits[i]) }
            if (e.key === 'Escape') setOpen(false)
          }}
          className="h-11 flex-1 bg-transparent text-[15px] outline-none focus-visible:outline-none placeholder:text-ink-3" />
      </div>
      {open && hits.length > 0 && (
        <ul className="absolute inset-x-0 top-12 z-20 max-h-72 overflow-y-auto rounded-[12px] border border-line-2 bg-sheet py-1 shadow-[var(--shadow-soft)] rise">
          {hits.map((h, k) => (
            <li key={h.product_id}>
              <button onMouseDown={e => e.preventDefault()} onMouseEnter={() => setI(k)} onClick={() => pick(h)}
                className={cx('flex w-full items-center gap-3 px-3 py-2 text-left', k === i && 'bg-line/50')}>
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{h.name}</div>
                  <div className="truncate text-xs text-ink-3">{h.composition ?? t('composition not verified')}</div></div>
                <Chip tone={h.requires_prescription ? 'red' : 'green'}>{h.schedule}</Chip>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function Qty({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  const set = (n: number) => onChange(Math.max(1, Math.min(1000, Math.round(n) || 1)))
  return (
    <div className="flex items-center rounded-[10px] border border-line">
      <button aria-label="Fewer" onClick={() => set(value - 1)} className="grid size-8 place-items-center text-ink-3 hover:text-ink"><Minus className="size-3.5" /></button>
      <input value={value} inputMode="numeric" aria-label="Quantity" onChange={e => set(Number(e.target.value.replace(/\D/g, '')))}
        className="num w-10 bg-transparent text-center text-[14px] outline-none focus-visible:outline-none" />
      <button aria-label="More" onClick={() => set(value + 1)} className="grid size-8 place-items-center text-ink-3 hover:text-ink"><Plus className="size-3.5" /></button>
    </div>
  )
}

// ---------------------------------------------------------------- scan a bill / prescription (OCR)
type Proposed = ReadLine & { keep: boolean }

function Scan({ onAdd, onClose }: { onAdd: (rows: Row[]) => void; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [ai, setAi] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [got, setGot] = useState<{ lines: Proposed[]; engine: string; note: string | null } | null>(null)
  const input = useRef<HTMLInputElement>(null)
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview) }, [preview])

  const read = async (f: File, vision: boolean) => {
    setBusy(true); setErr(null)
    try {
      const r = await readBill(f, vision)
      setGot({ ...r, lines: r.lines.map(l => ({ ...l, keep: true })) })
    } catch (e) { setErr((e as Error).message); setGot(null) } finally { setBusy(false) }
  }
  const choose = (f: File | undefined) => {
    if (!f) return
    setFile(f); setPreview(URL.createObjectURL(f)); setGot(null)
    read(f, ai)
  }
  const set = (i: number, p: Partial<Proposed>) => setGot(g => g && { ...g, lines: g.lines.map((l, k) => k === i ? { ...l, ...p } : l) })
  const kept = got?.lines.filter(l => l.keep) ?? []
  const unmatched = got?.lines.filter(l => !l.product_id).length ?? 0

  return (
    <Panel className="overflow-hidden rise">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
        <div className="flex items-center gap-2 text-[14px] font-medium text-navy"><ScanText className="size-4 text-green" />{t('Scan a bill or prescription')}</div>
        <button onClick={onClose} aria-label="Close scanner" className="text-ink-3 hover:text-ink"><X className="size-4" /></button>
      </div>
      <div className="space-y-3 p-3.5">
        <input ref={input} type="file" accept="image/*" capture="environment" className="hidden" onChange={e => { choose(e.target.files?.[0]); e.target.value = '' }} />
        {!file ? (
          <button onClick={() => input.current?.click()}
            className="flex w-full flex-col items-center gap-2 rounded-[12px] border border-dashed border-line-2 px-4 py-7 text-center transition hover:border-teal/60 hover:bg-pale/40"
            onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); choose(e.dataTransfer.files?.[0]) }}>
            <span className="grid size-10 place-items-center rounded-full bg-pale text-green"><Camera className="size-5" /></span>
            <span className="text-[14px] font-medium text-navy">{t("Take a photo or choose one")}</span>
            <span className="text-[12px] text-ink-3">{t("Pharmacy bill or prescription · JPG / PNG, up to 8 MB")}</span>
          </button>
        ) : (
          <div className="flex gap-3">
            {preview && <img src={preview} alt="Your photo" className="h-24 w-20 shrink-0 rounded-[8px] border border-line object-cover" />}
            <div className="min-w-0 flex-1 space-y-1.5 text-[13px]">
              <div className="truncate font-medium">{file.name}</div>
              {busy ? <div className="flex items-center gap-2 text-ink-3"><Mark size={18} thinking />{ai ? t('Reading with AI…') : t('Reading on this server…')}</div>
                : got && <div className="text-ink-3">{t('Read by {who} · {n} found', { who: t(got.engine === 'vision' ? 'AI reader' : 'on-device OCR'), n: got.lines.length })}</div>}
              <button onClick={() => input.current?.click()} className="text-green hover:underline">{t("Use another photo")}</button>
            </div>
          </div>
        )}

        <label className="flex cursor-pointer items-start justify-between gap-3 rounded-[10px] bg-line/40 p-2.5">
          <span><span className="flex items-center gap-1.5 text-[13px] font-medium"><Wand2 className="size-3.5" />{t('Read handwriting with AI')}</span>
            <span className="block text-[11.5px] text-ink-3">{ai ? t('The photo is sent to an AI service to be read. Not stored by MediBot.') : t('Off: the photo is read on our server only and never stored.')}</span></span>
          <button role="switch" aria-checked={ai} onClick={() => { const v = !ai; setAi(v); if (file && v) read(file, true) }}
            className={cx('relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition', ai ? 'bg-teal' : 'bg-line-2')}>
            <span className={cx('absolute top-0.5 size-4 rounded-full bg-white shadow transition-all', ai ? 'left-[18px]' : 'left-0.5')} />
          </button>
        </label>

        {err && <p className="text-[13px] text-red">{err}</p>}
        {got?.note && <p className="text-[12.5px] text-amber">{got.note}</p>}

        {got && got.lines.length > 0 && (
          <div className="space-y-2">
            <Label>{t("Check what we read")}</Label>
            <ul className="divide-y divide-line rounded-[10px] border border-line">
              {got.lines.map((l, i) => (
                <li key={i} className={cx('flex items-center gap-2.5 px-2.5 py-2', !l.keep && 'opacity-45')}>
                  <button role="checkbox" aria-checked={l.keep} aria-label={`Include ${l.name}`} onClick={() => set(i, { keep: !l.keep })}
                    className={cx('grid size-5 shrink-0 place-items-center rounded-[6px] border transition', l.keep ? 'border-teal bg-teal text-white' : 'border-line-2')}>
                    {l.keep && <Check className="size-3.5" strokeWidth={3} />}</button>
                  <div className="min-w-0 flex-1">
                    {l.product_id ? <div className="truncate text-[13.5px] font-medium">{l.name}</div>
                      : <input value={l.name} onChange={e => set(i, { name: e.target.value })} aria-label="Medicine name"
                          className="w-full rounded-[6px] border border-amber/40 bg-amber-soft px-1.5 py-0.5 text-[13.5px] outline-none" />}
                    <div className="truncate text-[11.5px] text-ink-3">
                      {l.product_id ? <>read “{l.written}”{l.requires_prescription && <span className="ml-1 font-semibold text-red">Rx</span>}</> : <span className="text-amber">{t('not sure which medicine — fix the name')}</span>}
                    </div>
                  </div>
                  <div className="text-right">
                    <Qty value={l.quantity} onChange={n => set(i, { quantity: n, quantity_given: true })} />
                    {!l.quantity_given && <div className="mt-0.5 text-[10.5px] text-amber">{t('qty not on page')}</div>}
                  </div>
                </li>))}
            </ul>
            {got.engine === 'tesseract' && unmatched > 0 && !ai && (
              <button onClick={() => { setAi(true); if (file) read(file, true) }} className="inline-flex items-center gap-1 text-[12.5px] text-green hover:underline"><Wand2 className="size-3.5" />{t('Some names unclear? Try the AI reader')}</button>)}
            <div className="flex items-center justify-between gap-2 pt-1">
              <span className="flex items-center gap-1 text-[11.5px] text-ink-3"><ShieldCheck className="size-3.5" />{t("Photo not stored")}</span>
              <Button variant="primary" disabled={!kept.length} onClick={() => onAdd(kept.map(l => ({ id: uid(), name: l.name, quantity: l.quantity, product_id: l.product_id, composition: l.composition, rx: !!l.requires_prescription })))}>
                {t('Add {n} to list', { n: kept.length })}</Button>
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}

// ---------------------------------------------------------------- results
function CartCard({ cart, i }: { cart: BillCart; i: number }) {
  return (
    <Panel className="overflow-hidden rise" >
      <div className="flex items-center justify-between gap-3 border-b border-line bg-paper/60 px-4 py-3" style={{ animationDelay: `${i * 60}ms` }}>
        <div className="flex items-center gap-2.5">
          <span className="num grid size-7 place-items-center rounded-full bg-navy text-[12px] font-semibold text-sheet dark:bg-teal dark:text-paper">{i + 1}</span>
          <div><div className="text-[15px] font-semibold text-navy">{PLATFORM[cart.platform] ?? cart.platform}</div>
            <div className="text-[12px] text-ink-3">{t('{n} item(s) in this order', { n: cart.lines.length })}</div></div>
        </div>
        <div className="num text-[17px] font-semibold text-navy">{inr(cart.total_inr)}</div>
      </div>
      <ul className="divide-y divide-line">
        {cart.lines.map(l => (
          <li key={l.item_key} className="px-4 py-3">
            <div className="flex items-baseline gap-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[14.5px] font-medium">{l.name}</span>
                  {!l.is_asked_product && <Chip tone="green" title={`Same composition as ${l.label}`}><Repeat2 className="size-3" />{t('identical alternative')}</Chip>}
                </div>
                {!l.is_asked_product && <div className="text-[12px] text-ink-3">{t('instead of {x}', { x: l.label })}</div>}
              </div>
              <span className="leader" />
              <span className="num text-[14.5px] font-medium">{inr(l.cost_inr)}</span>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-3">
              <span className="num">{l.packs} × {inr(l.pack_price_inr)}{l.pack_label ? ` · ${l.pack_label}` : ''}</span>
              {l.overbuy_units > 0 && <span className="num text-amber">{t('+{n} extra (whole packs)', { n: l.overbuy_units })}</span>}
              <Freshness q={l} />
              {l.url && <a href={l.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 text-green hover:underline">{t('open')}<ExternalLink className="size-3" /></a>}
            </div>
          </li>
        ))}
      </ul>
      <div className="space-y-1 border-t border-line px-4 py-3 text-[13px]">
        <div className="flex"><span className="text-ink-2">{t("Medicines")}</span><span className="leader" /><span className="num">{inr(cart.subtotal_inr)}</span></div>
        <div className="flex"><span className="text-ink-2">{t("Delivery")}</span><span className="leader" />
          <span className={cx('num', !cart.delivery_fee_known && 'text-amber')}>{cart.delivery_fee_known ? (cart.delivery_fee_inr ? inr(cart.delivery_fee_inr) : t('free')) : t('not known')}</span></div>
      </div>
    </Panel>
  )
}

function Option({ active, onClick, title, total, sub, accent }: { active: boolean; onClick: () => void; title: string; total: number | null | undefined; sub: string; accent?: boolean }) {
  return (
    <button onClick={onClick} disabled={total == null}
      className={cx('min-w-0 rounded-[12px] border p-3 text-left transition disabled:opacity-40',
        active ? 'border-teal bg-pale/60 shadow-[var(--shadow-soft)]' : 'border-line bg-sheet hover:border-line-2')}>
      <div className={cx('flex items-center gap-1 text-[12px] font-medium', accent ? 'text-green' : 'text-ink-3')}>{accent && <Sparkles className="size-3" />}{t(title)}</div>
      <div className="num mt-0.5 text-[18px] font-semibold text-navy">{total == null ? '—' : inr(total)}</div>
      <div className="truncate text-[11.5px] text-ink-3">{t(sub)}</div>
    </button>
  )
}

function Results({ r }: { r: BillResult }) {
  const [view, setView] = useState<View>('best')
  const [card, setCard] = useState(false)
  const item = (k: string) => r.items.find(i => i.key === k)
  const plans: Record<Exclude<View, 'jan_aushadhi'>, BillPlan | null> = { best: r.best, as_asked: r.as_asked, one_stop: r.one_stop }
  const p = view === 'jan_aushadhi' ? null : plans[view]
  const label = (k: string) => r.items.find(i => i.key === k)?.name ?? k
  const rx = r.items.filter(i => i.mandated_prompt && i.status !== 'banned')
  const bad = r.items.filter(i => i.status !== 'ok')
  const names = (pl: BillPlan | null) => pl ? pl.pharmacies.map(x => PLATFORM[x] ?? x).join(' + ') : 'not possible'
  return (
    <div className="space-y-5">
      <div className="flex gap-3.5 rise">
        <Mark size={30} className="mt-1" />
        <div className="min-w-0 space-y-1">
          {r.best && r.savings_inr != null && r.savings_inr > 0.5 ? <>
            <p className="say">{t('Order this way and pay {total} — {save} less than buying the same brands at their cheapest.', { total: inr(r.best.total_inr), save: inr(r.savings_inr) })}</p>
            {r.best.swaps > 0 && <p className="say-sm text-ink-2">{t('{n} item(s) use an identical alternative (same ingredients, strengths and form). Confirm any switch with your doctor or pharmacist.', { n: r.best.swaps })}</p>}
          </> : r.best ? <p className="say">{t('The cheapest way to buy this list is {total} from {where}.', { total: inr(r.best.total_inr), where: names(r.best) })}</p>
            : <p className="say">{t("We couldn't price this list from any pharmacy yet.")}</p>}
        </div>
      </div>

      {rx.length > 0 && (
        <Panel tone="red" className="p-3.5 text-[13.5px]">
          <div className="mb-1 font-semibold text-red">{t("Prescription needed")}</div>
          <p className="text-ink-2">{rx.map(i => i.name).join(', ')} — {rx[0].mandated_prompt}</p>
          {rx[0].mandated_prompt && t(rx[0].mandated_prompt) !== rx[0].mandated_prompt && <p className="mt-1 text-ink-2">{t(rx[0].mandated_prompt)}</p>}
        </Panel>
      )}
      {bad.length > 0 && (
        <Panel tone="amber" className="space-y-1 p-3.5 text-[13.5px]">
          {bad.map(i => <div key={i.key}><span className="font-medium">{i.name ?? i.input}</span> <span className="text-ink-2">— {
            i.status === 'banned' ? (i.note ?? t('banned in India; not included')) : i.status === 'no_price' ? t('no current price from a delivering pharmacy') : t('not recognised; try picking it from search')}</span></div>)}
        </Panel>
      )}

      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Option active={view === 'best'} onClick={() => setView('best')} title="Cheapest split" total={r.best?.total_inr} sub={names(r.best)} accent />
        <Option active={view === 'as_asked'} onClick={() => setView('as_asked')} title="Same brands" total={r.as_asked?.total_inr} sub={names(r.as_asked)} />
        <Option active={view === 'one_stop'} onClick={() => setView('one_stop')} title="One pharmacy" total={r.one_stop?.total_inr} sub={r.one_stop ? names(r.one_stop) : 'none has every item'} />
        <Option active={view === 'jan_aushadhi'} onClick={() => setView('jan_aushadhi')} title="Jan Aushadhi" total={r.jan_aushadhi?.total_inr} sub={r.jan_aushadhi ? (r.jan_aushadhi.complete ? 'walk-in, whole list' : 'walk-in, part of list') : 'not available'} />
      </div>

      <div className="flex justify-end">
        <Button variant="primary" disabled={!(view === 'jan_aushadhi' ? r.jan_aushadhi?.lines.length : p?.carts.length)} onClick={() => setCard(true)}><IdCard className="size-4" />{t('Show to pharmacist')}</Button>
      </div>
      {card && <PharmacistCard onClose={() => setCard(false)} title={t('Medicine list')}
        total={view === 'jan_aushadhi' ? r.jan_aushadhi?.total_inr : p?.total_inr}
        lines={view === 'jan_aushadhi'
          ? (r.jan_aushadhi?.lines ?? []).map((l): CardLine => {
              const it = item(l.item_key)
              return { asked: l.label, asked_composition: it?.composition, chosen: l.name.replace(/^Jan Aushadhi: /, ''), same: false,
                qty: `${l.packs} × ${l.pack_label ?? t('pack')}`, rx: !!it?.requires_prescription, price: l.cost_inr, where: t('Jan Aushadhi Kendra') }
            })
          : (p?.carts ?? []).flatMap(c => c.lines.map((l): CardLine => {
              const it = item(l.item_key)
              return { asked: l.label, asked_composition: it?.composition, chosen: l.name, same: l.is_asked_product,
                qty: `${l.packs} × ${l.pack_label ?? t('pack')}`, rx: !!it?.requires_prescription, price: l.cost_inr, where: PLATFORM[c.platform] ?? c.platform }
            }))} />}

      {p && <div className="space-y-3">
        {p.carts.map((c, i) => <CartCard key={c.platform} cart={c} i={i} />)}
        {p.unplaced.length > 0 && <p className="text-[13px] text-amber">{t('Not in this plan:')} {p.unplaced.map(label).join(', ')}</p>}
        {view === 'one_stop' && r.single_pharmacy.length > 1 && (
          <Panel className="p-3.5"><Label>{t("Everything from one pharmacy")}</Label>
            <div className="mt-2 space-y-1 text-[13.5px]">{r.single_pharmacy.map(s => (
              <div key={s.platform} className="flex"><span>{PLATFORM[s.platform] ?? s.platform}</span><span className="leader" /><span className="num">{inr(s.total_inr)}</span></div>))}</div>
          </Panel>)}
      </div>}

      {view === 'jan_aushadhi' && r.jan_aushadhi && (
        <Panel className="overflow-hidden rise">
          <div className="flex items-center justify-between border-b border-line bg-paper/60 px-4 py-3">
            <div className="flex items-center gap-2.5"><Store className="size-5 text-green" /><div><div className="text-[15px] font-semibold text-navy">{t('Jan Aushadhi Kendra')}</div><div className="text-[12px] text-ink-3">{t(r.jan_aushadhi.note)}</div></div></div>
            <div className="num text-[17px] font-semibold text-navy">{inr(r.jan_aushadhi.total_inr)}</div>
          </div>
          <ul className="divide-y divide-line">{r.jan_aushadhi.lines.map(l => (
            <li key={l.item_key} className="px-4 py-3">
              <div className="flex items-baseline gap-2"><span className="text-[14.5px] font-medium">{l.name}</span><span className="leader" /><span className="num text-[14.5px] font-medium">{inr(l.cost_inr)}</span></div>
              <div className="num mt-1 text-[12px] text-ink-3">{t('instead of {x}', { x: l.label })} · {l.packs} × {inr(l.pack_price_inr)}{l.pack_label ? ` · ${l.pack_label}` : ''}</div>
            </li>))}</ul>
          {!r.jan_aushadhi.complete && <p className="border-t border-line px-4 py-2.5 text-[12.5px] text-amber">{t("Some items on your list have no Jan Aushadhi equivalent.")}</p>}
        </Panel>
      )}

      <div className="flex gap-2 rounded-[12px] bg-line/40 p-3 text-[12px] text-ink-2">
        <Info className="mt-0.5 size-3.5 shrink-0" />
        <div className="space-y-1">
          {r.unknown_delivery_terms.length > 0 && <p>{t("Delivery fees and minimum orders for {list} aren't known to us, so totals exclude them. Check at checkout.", { list: r.unknown_delivery_terms.map(x => PLATFORM[x] ?? x).join(', ') })}</p>}
          <p>{t('Prices are per pack, rounded up to whole packs.')} {t(r.advisory)}</p>
          <p className="text-ink-3">{t(r.disclaimer)}</p>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- page
export function BillPage({ onOpen }: { onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<Row[]>(load)
  const [paste, setPaste] = useState(false)
  const [scan, setScan] = useState(false)
  const [text, setText] = useState('')
  const [alts, setAlts] = useState(true)
  const [maxPh, setMaxPh] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [res, setRes] = useState<BillResult | null>(null)
  const [runs, setRuns] = useState(0)
  const top = useRef<HTMLDivElement>(null)

  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(rows)) } catch { /* private mode */ } }, [rows])

  const add = (h: SearchHit) => setRows(r => r.some(x => x.product_id === h.product_id) ? r
    : [...r, { id: uid(), name: h.name, product_id: h.product_id, quantity: 10, composition: h.composition, rx: h.requires_prescription }])
  const upd = (id: string, p: Partial<Row>) => setRows(r => r.map(x => x.id === id ? { ...x, ...p } : x))
  const importText = async (t: string) => {
    setErr(null); setBusy(true)
    try {
      const { lines } = await billApi.parse(t)
      setRows(r => [...r, ...lines.map(l => ({ id: uid(), name: l.name, quantity: l.quantity, product_id: null }))].slice(0, 25))
      setPaste(false); setText('')
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  const run = async () => {
    if (!rows.length) return
    setBusy(true); setErr(null)
    try {
      const r = await billApi.plan(rows.map(({ name, quantity, product_id }) => ({ name, quantity, product_id })), alts, maxPh)
      setRes(r); setRuns(n => n + 1)
      // pin picker-less rows to what the server resolved, so the next run is exact
      setRows(rs => rs.map((x, i) => { const it = r.items[i]; return !x.product_id && it?.product_id ? { ...x, product_id: it.product_id, name: it.name ?? x.name, composition: it.composition, rx: it.requires_prescription } : x }))
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="flex-1 overflow-y-auto" ref={top}>
      <div className="mx-auto grid max-w-[1120px] grid-cols-1 gap-8 px-4 sm:px-5 pt-8 pb-14 lg:grid-cols-[400px_1fr]">
        {/* the list */}
        <section className="min-w-0 space-y-4 lg:sticky lg:top-6 lg:self-start">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-green"><Receipt className="size-4" /><Label>{t('Bill split')}</Label></div>
            <h1 className="display text-[30px] leading-tight text-navy">{t("Your medicine list")}</h1>
            <p className="say-sm text-ink-2">{t("Add what you need and how many. We'll find the cheapest way to buy all of it.")}</p>
          </div>

          {scan ? (
            <Scan onClose={() => setScan(false)} onAdd={rs => {
              setRows(r => { const have = new Set(r.map(x => x.product_id).filter(Boolean)); return [...r, ...rs.filter(x => !x.product_id || !have.has(x.product_id))].slice(0, 25) })
              setScan(false)
            }} />
          ) : paste ? (
            <Panel className="space-y-2 p-3">
              <textarea autoFocus rows={6} value={text} onChange={e => setText(e.target.value)} maxLength={3000}
                placeholder={t('One medicine per line, e.g.') + '\n' + SAMPLE}
                className="w-full resize-none bg-transparent text-[14.5px] leading-relaxed outline-none focus-visible:outline-none placeholder:text-ink-3" />
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setPaste(false)}>{t("Cancel")}</Button>
                <Button variant="primary" disabled={text.trim().length < 2 || busy} onClick={() => importText(text)}>{t("Add to list")}</Button>
              </div>
            </Panel>
          ) : (
            <div className="space-y-2">
              <Adder onAdd={add} />
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <button onClick={() => setScan(true)} className="inline-flex items-center gap-1.5 text-[13px] font-medium text-green hover:underline"><Camera className="size-3.5" />{t('Scan a bill or prescription')}</button>
                <button onClick={() => setPaste(true)} className="inline-flex items-center gap-1.5 text-[13px] text-ink-3 hover:text-ink"><ClipboardList className="size-3.5" />{t('Paste a list')}</button>
              </div>
            </div>
          )}

          {rows.length > 0 ? (
            <Panel className="divide-y divide-line">
              {rows.map(r => (
                <div key={r.id} className="flex items-center gap-3 px-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <button onClick={() => r.product_id && onOpen(r.product_id)} disabled={!r.product_id}
                      className="block max-w-full truncate text-left text-[14.5px] font-medium enabled:hover:text-green">{r.name}</button>
                    <div className="flex items-center gap-1.5 text-[12px] text-ink-3">
                      {r.rx && <span className="font-semibold text-red">Rx</span>}
                      <span className="truncate">{r.composition ?? (r.product_id ? t('composition not verified') : t('will be matched when you run'))}</span>
                    </div>
                  </div>
                  <Qty value={r.quantity} onChange={n => upd(r.id, { quantity: n })} />
                  <button aria-label={`Remove ${r.name}`} onClick={() => setRows(x => x.filter(y => y.id !== r.id))} className="text-ink-3 hover:text-red"><Trash2 className="size-4" /></button>
                </div>
              ))}
              <div className="px-3 py-2 text-[11.5px] text-ink-3">{t("Quantity = tablets / capsules / ml you need")}</div>
            </Panel>
          ) : !paste && !scan && (
            <button onClick={() => importText(SAMPLE)} className="flex w-full items-center gap-3 rounded-[var(--radius-card)] border border-dashed border-line-2 p-4 text-left transition hover:border-teal/60 hover:bg-pale/40">
              <span className="grid size-8 place-items-center rounded-[10px] bg-pale text-green"><Sparkles className="size-4" /></span>
              <span><span className="block text-[14px] font-medium text-navy">{t("Try a sample list")}</span><span className="block text-[12.5px] text-ink-3">Dolo 650, Pan 40, Telma 40, Augmentin 625 Duo</span></span>
            </button>
          )}

          <div className="space-y-3 rounded-[var(--radius-card)] border border-line bg-sheet p-3.5">
            <label className="flex cursor-pointer items-start justify-between gap-3">
              <span><span className="block text-[13.5px] font-medium">{t("Allow identical alternatives")}</span><span className="block text-[12px] text-ink-3">{t("Same ingredients, strength and form — a different brand")}</span></span>
              <button role="switch" aria-checked={alts} onClick={() => setAlts(a => !a)}
                className={cx('relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition', alts ? 'bg-teal' : 'bg-line-2')}>
                <span className={cx('absolute top-0.5 size-4 rounded-full bg-white shadow transition-all', alts ? 'left-[18px]' : 'left-0.5')} />
              </button>
            </label>
            <div>
              <div className="mb-1.5 text-[13.5px] font-medium">{t("Most pharmacies to order from")}</div>
              <div className="grid grid-cols-4 gap-1 rounded-[10px] bg-line/50 p-1">
                {[null, 1, 2, 3].map(n => (
                  <button key={String(n)} onClick={() => setMaxPh(n)}
                    className={cx('num rounded-[7px] py-1 text-[13px] transition', maxPh === n ? 'bg-sheet font-medium text-navy shadow-sm' : 'text-ink-3 hover:text-ink')}>{n ?? t('Any')}</button>))}
              </div>
            </div>
          </div>

          {err && <p className="flex items-center gap-1.5 text-[13px] text-red"><X className="size-3.5" />{err}</p>}
          <button onClick={run} disabled={!rows.length || busy}
            className="flex w-full items-center justify-center gap-2 rounded-[12px] bg-navy py-3 text-[15px] font-semibold text-white transition hover:bg-navy/90 disabled:bg-line-2 disabled:text-ink-3 dark:bg-teal dark:text-paper">
            {busy ? t('Checking prices…') : <>{t('Find the cheapest way')}<ArrowRight className="size-4" /></>}
          </button>
        </section>

        {/* the answer */}
        <section className="min-w-0">
          {busy && !res ? (
            <div className="flex gap-3.5 pt-2"><Mark size={30} thinking /><p className="pt-1 text-[14px] text-ink-3">{t('Checking live prices at five pharmacies and every identical alternative…')}</p></div>
          ) : res ? <div className={cx(busy && 'opacity-50 transition-opacity')}><Results key={runs} r={res} /></div> : (
            <div className="grid h-full min-h-[340px] place-items-center rounded-[var(--radius-card)] border border-dashed border-line text-center">
              <div className="max-w-xs space-y-2 p-6">
                <Receipt className="mx-auto size-8 text-line-2" />
                <p className="say-sm text-ink-2">{t('Your plan appears here: which pharmacy to order each medicine from, packs to buy, and what you save.')}</p>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
