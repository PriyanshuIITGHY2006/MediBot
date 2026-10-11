// One component per API card type (backend/medibot/cards.py). Cards hold facts only; nothing here invents text
// except labels. Safety texts (intercept, emergency, refusal) are shown exactly as the API sends them.
import { AlertTriangle, BadgeCheck, ExternalLink, MapPin, PhoneCall, ShieldAlert, Store } from 'lucide-react'
import type { Card, Citation, Quote, SubstituteRow } from './api'
import { Chip, Freshness, Label, PLATFORM, Panel, UNIT, cx, inr } from './ui'

type Ctx = { citations: Citation[]; onAsk: (q: string) => void; onOpen: (productId: string) => void }

// ---------------------------------------------------------------- safety
export function InterceptBanner({ c }: { c: Extract<Card, { type: 'intercept_banner' }> }) {
  return (
    <div role="alert" className="flex items-center gap-3.5 rounded-[var(--radius-card)] border border-red/40 bg-red-soft px-4 py-3.5">
      <div aria-hidden className="grid size-9 shrink-0 rotate-[-4deg] place-items-center rounded-lg border-2 border-red font-serif text-[22px] font-semibold leading-none text-red">℞</div>
      <div className="space-y-1.5 text-[15px] leading-snug text-ink">
        {c.lines.map((l, i) => <p key={i} className={i === 0 ? 'font-medium' : 'text-ink-2'}>{l}</p>)}
      </div>
    </div>
  )
}

export function EmergencyCard({ c }: { c: Extract<Card, { type: 'emergency' }> }) {
  const lines = c.text.split('\n')
  return (
    <div role="alert" className="rounded-[var(--radius-card)] border-2 border-red bg-red-soft p-4">
      <div className="flex items-center gap-2 font-semibold text-red"><ShieldAlert className="size-5" />{lines[0]}</div>
      <ul className="mt-2 space-y-1 text-[15px]">{lines.slice(1).map((l, i) => <li key={i}>{l.replace(/^•\s*/, '')}</li>)}</ul>
      <div className="mt-3 flex flex-wrap gap-2">
        {(c.self_harm ? [['14416', 'Tele-MANAS 14416'], ['112', 'Emergency 112']] : [['112', 'Call 112'], ['108', 'Ambulance 108']]).map(([n, label]) => (
          <a key={n} href={`tel:${n}`} className="inline-flex items-center gap-2 rounded-lg bg-red px-4 py-2 text-sm font-semibold text-white hover:opacity-90">
            <PhoneCall className="size-4" />{label}
          </a>
        ))}
      </div>
    </div>
  )
}

export function Refusal({ text }: { text: string }) {
  return <Panel tone="amber" className="flex gap-3 bg-amber-soft/60 px-4 py-3"><AlertTriangle className="mt-1 size-4 shrink-0 text-amber" /><p className="say-sm">{text}</p></Panel>
}

// ---------------------------------------------------------------- medicine + info
const SCHEDULE_TONE = (cat?: string | null) =>
  !cat ? 'plain' : cat === 'otc' ? 'green' : cat === 'otc_unverified' ? 'amber' : 'red'
const SCHEDULE_TEXT: Record<string, string> = {
  otc: 'OTC', otc_unverified: 'OTC · unverified', schedule_h: 'Schedule H', schedule_h1: 'Schedule H1',
  schedule_x: 'Schedule X', controlled: 'Controlled', prescription: 'Prescription', banned: 'Banned', unknown: 'Rx by default',
}

export function MedicineCard({ c, ctx }: { c: Extract<Card, { type: 'medicine' }>; ctx: Ctx }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <button disabled={!c.product_id} onClick={() => c.product_id && ctx.onOpen(c.product_id)}
        className="text-left text-[17px] font-semibold tracking-[-0.015em] text-navy hover:underline decoration-teal/40 underline-offset-4 disabled:no-underline">
        {c.name}
      </button>
      {c.category && <Chip tone={SCHEDULE_TONE(c.category)}>{SCHEDULE_TEXT[c.category] ?? c.category}</Chip>}
      <div className="w-full text-sm text-ink-2">{c.generic ? 'Generic medicine name' : c.composition ? <>Contains <span className="text-ink">{c.composition}</span></> : 'Composition not verified'}</div>
      {c.info_from && <div className="w-full text-xs text-amber">Information below is for {c.info_from}, the {c.brand} product with a verified composition.</div>}
    </div>
  )
}

/** Text with [n] citation markers turned into links to the sources list. */
function Cited({ text, citations }: { text: string; citations: Citation[] }) {
  const parts = text.split(/(\[\d+\])/g)
  return <>{parts.map((p, i) => {
    const m = p.match(/^\[(\d+)\]$/)
    if (!m) return <span key={i}>{p}</span>
    const c = citations.find(x => x.n === Number(m[1]))
    return c ? <a key={i} href={c.url} target="_blank" rel="noreferrer" title={c.title}
      className="num mx-0.5 inline-grid min-w-[18px] place-items-center rounded-full bg-pale px-1 align-[2px] font-sans text-[10.5px] font-semibold text-green no-underline hover:bg-teal hover:text-white">{m[1]}</a> : <span key={i}>{p}</span>
  })}</>
}

export function InfoCard({ c, ctx }: { c: Extract<Card, { type: 'info' }>; ctx: Ctx }) {
  const blocks = c.text.split('\n').filter(Boolean)
  return (
    <div className="say space-y-2.5">
      {blocks.map((b, i) => {
        const head = b.match(/^([A-Z][A-Za-z ]{2,24}):\s*(.*)$/)
        if (b.startsWith('• ')) return <p key={i} className="pl-4 -indent-3"><span className="text-ink-3">• </span><Cited text={b.slice(2)} citations={ctx.citations} /></p>
        if (head && !head[2]) return <div key={i} className="pt-1 font-sans"><Label>{head[1]}</Label></div>
        if (head) return <p key={i}><span className="font-sans text-[13px] font-semibold uppercase tracking-[0.06em] text-ink-3">{head[1]} </span><Cited text={head[2]} citations={ctx.citations} /></p>
        return <p key={i} className={b.startsWith("I don't have") ? 'text-ink-3 text-sm' : ''}><Cited text={b} citations={ctx.citations} /></p>
      })}
    </div>
  )
}

export function Sources({ c }: { c: Extract<Card, { type: 'sources' }> }) {
  return (
    <details className="group text-xs text-ink-3">
      <summary className="cursor-pointer select-none list-none hover:text-ink-2">Sources ({c.citations.length}) <span className="group-open:hidden">▸</span><span className="hidden group-open:inline">▾</span></summary>
      <ol className="mt-1.5 space-y-1">
        {c.citations.map(s => (
          <li key={s.n} className="flex gap-2"><span className="num">{s.n}</span>
            <a href={s.url} target="_blank" rel="noreferrer" className="hover:text-ink underline-offset-2 hover:underline">{s.title}{s.note ? ` — ${s.note}` : ''}</a></li>
        ))}
      </ol>
    </details>
  )
}

// ---------------------------------------------------------------- money
export function Receipt({ quotes, unit }: { quotes: Quote[]; unit?: string | null }) {
  if (!quotes.length) return <p className="text-sm text-ink-3">No recent price on record for this pack.</p>
  const best = Math.min(...quotes.map(q => q.price_per_unit_inr ?? Infinity))
  return (
    <ul className="space-y-1.5">
      {quotes.map((q, i) => (
        <li key={q.platform + i} className="text-sm">
          <div className="flex items-baseline">
            <span className="text-ink">{PLATFORM[q.platform] ?? q.platform}</span>
            {q.price_per_unit_inr === best && quotes.length > 1 && <span className="ml-2"><Chip tone="green">lowest</Chip></span>}
            <span className="leader" />
            <span className="num font-medium">{inr(q.price_inr)}</span>
          </div>
          <div className="flex flex-wrap items-center gap-x-2 text-[11px] text-ink-3">
            <span>{q.pack_label ?? 'pack'}</span>
            {q.price_per_unit_inr != null && <span className="num">{inr(q.price_per_unit_inr)}/{UNIT[q.pack_unit ?? unit ?? 'unit'] ?? 'unit'}</span>}
            {q.mrp_inr != null && q.mrp_inr > q.price_inr && <span className="num line-through">{inr(q.mrp_inr)}</span>}
            <Freshness q={q} />
            {q.in_stock === false && <span className="text-red">out of stock</span>}
            {q.url && <a href={q.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 hover:text-ink">open <ExternalLink className="size-3" /></a>}
          </div>
          {q.above_nppa_ceiling && <p className="mt-0.5 text-[11px] text-red">Above the government ceiling price of {inr(q.above_nppa_ceiling.ceiling_per_unit_inr)}/unit ({q.above_nppa_ceiling.source})</p>}
        </li>
      ))}
    </ul>
  )
}

export function SubstituteList({ rows, current, unit, note, onOpen }: { rows: SubstituteRow[]; current?: number | null; unit?: string | null; note?: string | null; onOpen: (id: string) => void }) {
  const u = UNIT[unit ?? 'unit'] ?? 'unit'
  return (
    <div className="space-y-2">
      {current != null && <p className="text-xs text-ink-3">Current price <span className="num text-ink-2">{inr(current)}/{u}</span> · compared per {u}</p>}
      <ul className="divide-y divide-line rounded-[var(--radius-card)] border border-line bg-sheet">
        {rows.map(r => (
          <li key={r.product_id} className="flex items-center gap-3 px-3 py-2.5">
            <BadgeCheck aria-label="identical composition verified" className="size-4 shrink-0 text-green" />
            <div className="min-w-0 flex-1">
              <button onClick={() => !r.product_id.startsWith('ja_') && onOpen(r.product_id)} className="truncate text-left text-sm font-medium hover:underline underline-offset-4 decoration-line-2">
                {r.tier === 'jan_aushadhi' ? r.brand_name.replace(/^Jan Aushadhi: /, '') : r.brand_name}
              </button>
              <div className="truncate text-[11px] text-ink-3">{r.tier === 'jan_aushadhi' ? 'Jan Aushadhi Kendra · Govt. of India' : r.manufacturer}</div>
            </div>
            <div className="text-right">
              <div className="num text-sm">{inr(r.price_per_unit_inr)}<span className="text-ink-3">/{u}</span></div>
              {r.savings_percentage != null && r.savings_percentage > 0 && <div className="num text-xs font-medium text-green">−{Math.round(r.savings_percentage)}%</div>}
            </div>
          </li>
        ))}
      </ul>
      {note && <p className="text-xs text-ink-3">Note: {note}.</p>}
      {rows[0] && <p className="text-xs text-ink-2">{rows[0].user_advisory}</p>}
    </div>
  )
}

// ---------------------------------------------------------------- other facts
function Interactions({ c }: { c: Extract<Card, { type: 'interactions' }> }) {
  if (c.kind === 'known_partners' || !c.findings.length) return <p className="text-[15px] leading-relaxed whitespace-pre-line">{c.text}</p>
  const tone = (s: string) => s === 'Major' || s === 'duplicate' ? 'red' : s === 'Moderate' ? 'amber' : 'plain'
  return (
    <div className="space-y-2">
      <Label>Interaction check</Label>
      {c.findings.map((f, i) => (
        <div key={i} className="flex items-start gap-2.5 text-sm">
          <span className="shrink-0 pt-0.5"><Chip tone={tone(f.severity) as 'red' | 'amber' | 'plain'}>{f.severity === 'duplicate' ? 'Same ingredient' : f.severity}</Chip></span>
          <p className="leading-snug">{f.text}</p>
        </div>
      ))}
      <p className="text-xs text-ink-2">Please ask your doctor or pharmacist before taking these together.</p>
    </div>
  )
}

function Stores({ c }: { c: Extract<Card, { type: 'stores' }> }) {
  if (!c.stores.length) return <p className="text-[15px]">{c.text}</p>
  return (
    <div className="space-y-2">
      <Label>Jan Aushadhi Kendras near {c.pincode}</Label>
      <ul className="space-y-2">{c.stores.map(s => (
        <li key={s.store_code} className="flex gap-2.5 text-sm">
          <Store className="mt-0.5 size-4 shrink-0 text-green" />
          <div><div>{s.address}</div><div className="text-[11px] text-ink-3">{s.district}, {s.state} · {s.pincode}</div>
            <a className="inline-flex items-center gap-1 text-[11px] text-green hover:underline" target="_blank" rel="noreferrer"
              href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`Jan Aushadhi Kendra ${s.address} ${s.pincode}`)}`}><MapPin className="size-3" />Directions</a></div>
        </li>))}</ul>
    </div>
  )
}

function Compare({ c }: { c: Extract<Card, { type: 'compare' }> }) {
  return (
    <Panel className="px-3 py-2 text-sm">
      {c.same_ingredients ? <p><BadgeCheck className="mr-1 inline size-4 text-green" />{c.names[0]} and {c.names[1]} have the same active ingredients{c.same_strengths ? '.' : ' (strengths differ).'}</p>
        : c.extra.map(([name, ings]) => <p key={name}><span className="font-medium">{name}</span> also contains {ings.join(', ')}.</p>)}
    </Panel>
  )
}

// ---------------------------------------------------------------- dispatcher
export function CardView({ card, ctx }: { card: Card; ctx: Ctx }) {
  switch (card.type) {
    case 'intercept_banner': return <InterceptBanner c={card} />
    case 'emergency': return <EmergencyCard c={card} />
    case 'refusal': return <Refusal text={card.text} />
    case 'medicine': return <MedicineCard c={card} ctx={ctx} />
    case 'info': return <InfoCard c={card} ctx={ctx} />
    case 'sources': return <Sources c={card} />
    case 'substitutes': return card.rows.length
      ? <SubstituteList rows={card.rows} note={card.note} unit={card.rows[0]?.pack_unit} onOpen={ctx.onOpen} />
      : <p className="text-sm text-ink-2">{card.note ? `Note: ${card.note}.` : card.text}</p>
    case 'prices': return <div className="space-y-1.5"><Label>Prices</Label><Receipt quotes={card.quotes} /></div>
    case 'interactions': return <Interactions c={card} />
    case 'stores': return <Stores c={card} />
    case 'compare': return <Compare c={card} />
    case 'clarify': return (
      <div className="flex flex-wrap items-center gap-1.5 text-sm"><span className="text-ink-2">Did you mean</span>
        {card.options.map(o => <Chip key={o} onClick={() => ctx.onAsk(o)}>{o}</Chip>)}</div>)
    case 'lead': return <p className="say">{card.text}</p>
    case 'fallback': return <p className="say text-ink-2">{card.text}</p>
    case 'disclaimer': return <p className={cx('text-[11px] text-ink-3', card.full && 'border-t border-line pt-2')}>{card.text}</p>
    case 'quick_replies': return (
      <div className="flex flex-wrap gap-1.5">{card.options.map(o => <Chip key={o} onClick={() => ctx.onAsk(o)}>{o}</Chip>)}</div>)
    default: return null
  }
}
