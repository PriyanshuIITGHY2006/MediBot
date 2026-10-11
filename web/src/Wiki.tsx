// MediBot Wiki: how it works, the safety rules, the data and the API, inside the app. Every number here comes
// from docs/ (DATABASE.md, SAFETY_POLICY.md, PRICES.md, HEALTH.md, EVAL.md) and the eval scorecard.
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { BadgeCheck, BookOpen, Camera, ExternalLink, IdCard, Languages, MessageCircle, Pill, Receipt, Search, ShieldAlert, ShieldCheck } from 'lucide-react'
import { API } from './api'
import { Mark } from './brand'
import { t } from './i18n'
import { Chip, Label, cx } from './ui'

const SECTIONS = [
  ['overview', 'What MediBot is'], ['flow', 'How an answer is made'], ['features', 'Features'], ['safety', 'Safety rules'],
  ['alternatives', 'Identical alternatives'], ['prices', 'Prices'], ['health', 'Health information'], ['data', 'Data'],
  ['quality', 'Quality & evaluation'], ['privacy', 'Privacy'], ['api', 'API'], ['faq', 'FAQ'],
] as const
const DOCS = (API || '') + '/docs'

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} data-wiki className="scroll-mt-6 space-y-3.5 border-b border-line/70 pb-10">
      <h2 className="display text-[26px] leading-tight text-navy">{title}</h2>
      <div className="say-sm space-y-3 text-ink-2">{children}</div>
    </section>
  )
}

function Table({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto rounded-[12px] border border-line bg-sheet font-sans">
      <table className="w-full text-left text-[13.5px]">
        <thead className="bg-paper/70 text-[11.5px] uppercase tracking-[0.06em] text-ink-3"><tr>{head.map(h => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr></thead>
        <tbody className="divide-y divide-line">{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="px-3 py-2 align-top text-ink">{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

function Stat({ n, label }: { n: string; label: string }) {
  return <div className="lift rounded-[12px] border border-line bg-sheet p-3.5 font-sans"><div className="num text-[22px] font-semibold text-navy">{n}</div><div className="text-[12.5px] text-ink-3">{label}</div></div>
}

/** Message → reader → safety kernel → facts → output check → reply. Colours follow the theme tokens. */
function FlowDiagram() {
  const steps = [
    ['Your message', 'any language, typos ok'], ['Reader', 'finds medicines, intent'], ['Safety kernel', 'Rx · banned · emergency'],
    ['Facts', 'catalog · prices · sources'], ['Output check', 'no dose, no diagnosis'], ['Reply', 'cards + citations'],
  ]
  return (
    <div className="overflow-x-auto rounded-[14px] border border-line bg-sheet p-4">
      <svg viewBox="0 0 960 150" className="min-w-[640px] font-sans" role="img" aria-label="How a message becomes an answer">
        <defs><marker id="wa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" className="fill-ink-3" /></marker></defs>
        {steps.map(([a, b], i) => {
          const x = 8 + i * 160, safety = i === 2 || i === 4
          return (
            <g key={a}>
              <rect x={x} y={34} width={136} height={70} rx={12} className={safety ? 'fill-red-soft stroke-red/40' : i === 5 ? 'fill-pale stroke-teal/50' : 'fill-paper stroke-line-2'} strokeWidth={1.2} />
              <text x={x + 68} y={64} textAnchor="middle" className={cx('text-[14px] font-semibold', safety ? 'fill-red' : 'fill-navy')}>{a}</text>
              <text x={x + 68} y={84} textAnchor="middle" className="fill-ink-3 text-[11px]">{b}</text>
              {i < steps.length - 1 && <line x1={x + 138} y1={69} x2={x + 158} y2={69} className="stroke-ink-3" strokeWidth={1.4} markerEnd="url(#wa)" />}
            </g>
          )
        })}
        <text x={8 + 2 * 160 + 68} y={128} textAnchor="middle" className="fill-ink-3 text-[11px]">mandated prompt shown first, verbatim</text>
        <text x={8 + 5 * 160 + 68} y={128} textAnchor="middle" className="fill-ink-3 text-[11px]">optional Hindi display</text>
      </svg>
    </div>
  )
}

export function WikiPage() {
  const [active, setActive] = useState<string>('overview')
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const root = box.current
    if (!root) return
    const io = new IntersectionObserver(es => {
      const vis = es.filter(e => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
      if (vis[0]) setActive(vis[0].target.id)
    }, { root, rootMargin: '0px 0px -70% 0px' })
    root.querySelectorAll('[data-wiki]').forEach(s => io.observe(s))
    return () => io.disconnect()
  }, [])
  const go = (id: string) => box.current?.querySelector('#' + id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

  return (
    <div ref={box} className="flex-1 overflow-y-auto">
      <div className="mx-auto grid max-w-[1120px] grid-cols-1 gap-10 px-4 pt-8 pb-16 sm:px-6 lg:grid-cols-[210px_1fr]">
        <aside className="max-lg:hidden">
          <nav className="sticky top-6 space-y-0.5" aria-label="Wiki sections">
            <div className="mb-3 flex items-center gap-2 text-green"><BookOpen className="size-4" /><Label>{t('Wiki')}</Label></div>
            {SECTIONS.map(([id, title]) => (
              <button key={id} onClick={() => go(id)} className={cx('relative block w-full rounded-[8px] px-3 py-1.5 text-left text-[13.5px] transition',
                active === id ? 'bg-pale font-medium text-navy' : 'text-ink-3 hover:bg-line/40 hover:text-ink')}>
                {active === id && <span className="absolute top-1.5 bottom-1.5 left-0 w-[3px] rounded-full bg-teal" />}{title}
              </button>))}
          </nav>
        </aside>

        <article className="min-w-0 space-y-10">
          <header className="stagger space-y-3">
            <Mark size={40} className="float" />
            <h1 className="display text-[36px] leading-[1.1] text-navy">MediBot Wiki</h1>
            <p className="say text-ink-2">How MediBot finds cheaper identical medicines, keeps you safe, and where every fact comes from.</p>
            <div className="flex flex-wrap gap-1.5"><Chip tone="green">570,968 products</Chip><Chip tone="green">5 pharmacies</Chip><Chip tone="green">80 / 80 on the offline rubric</Chip><Chip>English · हिंदी</Chip></div>
          </header>

          <Section id="overview" title="What MediBot is">
            <p>MediBot is an informational pharmacy assistant for India. Ask about any medicine (brand or generic, in English, Hindi or Hinglish, typos are fine) and it shows <b className="text-ink">live prices from five pharmacies</b>, <b className="text-ink">identical-composition alternatives</b> including Jan Aushadhi generics, and <b className="text-ink">medicine information copied from cited sources</b>.</p>
            <div className="grid gap-3 font-sans sm:grid-cols-2">
              <div className="rounded-[12px] border border-green/30 bg-green-soft/50 p-3.5"><div className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold text-green"><ShieldCheck className="size-4" />It will</div>
                <ul className="space-y-1 text-[13.5px] text-ink-2"><li>Compare prices per tablet / ml</li><li>Find identical cheaper options</li><li>Explain uses, side effects, interactions — with sources</li><li>Plan the cheapest way to buy a whole list</li></ul></div>
              <div className="rounded-[12px] border border-red/30 bg-red-soft/50 p-3.5"><div className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold text-red"><ShieldAlert className="size-4" />It never</div>
                <ul className="space-y-1 text-[13.5px] text-ink-2"><li>Diagnoses a condition</li><li>Recommends a medicine or a dose</li><li>Helps buy prescription medicines without a prescription</li><li>Writes medical text with an AI model</li></ul></div>
            </div>
          </Section>

          <Section id="flow" title="How an answer is made">
            <FlowDiagram />
            <p>The <b className="text-ink">reader</b> works out which medicines you mean (spelling fixes, Hinglish, follow-ups like "the 500 one"). The <b className="text-ink">safety kernel</b> decides first, before any fact is fetched: prescription medicines get the mandated prompt, banned ones a legal notice, emergencies the helplines. Then <b className="text-ink">facts</b> come from the catalog, live prices and the evidence index. An <b className="text-ink">output check</b> replaces any card that would read as a dose or a diagnosis with a fixed refusal. An AI model may help read your message and write a short lead-in, but never the medical facts.</p>
          </Section>

          <Section id="features" title="Features">
            <div className="grid gap-3 font-sans sm:grid-cols-2">
              {([[MessageCircle, 'Chat', 'Ask anything about a medicine; answers arrive as cards (prices, alternatives, information, interactions, stores).'],
                [Search, 'Search + medicine sheet', '⌘K finds any of 570k products; the side panel shows composition, prices at five pharmacies, alternatives and an interaction check.'],
                [Receipt, 'Bill split', 'Give a list and quantities; an exact planner finds the cheapest way across pharmacies in whole packs, vs same brands, one pharmacy, and Jan Aushadhi.'],
                [Camera, 'Scan a bill or prescription', 'Photo → medicine list. Read on the server (Tesseract) and never stored; an opt-in AI reader handles handwriting. Misread strengths are never auto-matched.'],
                [Pill, 'My cabinet', 'Your regular medicines, saved only on your device: monthly cost, refill dates and calendar reminders, price-drop flags, interactions across all of them.'],
                [IdCard, 'Pharmacist card', 'Asked-for vs identical option side by side, quantities and Rx flags — share on WhatsApp, print, or let the pharmacist scan a QR (plain text, offline).'],
                [Languages, 'Hindi', 'The whole interface and the answers in Hindi. Safety texts are hand-written Hindi; a translated line that changes any number is kept in English.'],
              ] as const).map(([Icon, h, d]) => (
                <div key={h} className="lift flex gap-3 rounded-[12px] border border-line bg-sheet p-3.5 hover:border-teal/40 hover:shadow-[var(--shadow-soft)]">
                  <span className="grid size-9 shrink-0 place-items-center rounded-[10px] bg-pale text-green"><Icon className="size-[18px]" /></span>
                  <div><div className="text-[14.5px] font-semibold text-navy">{h}</div><p className="text-[13px] leading-relaxed text-ink-2">{d}</p></div>
                </div>))}
            </div>
          </Section>

          <Section id="safety" title="Safety rules">
            <p><b className="text-ink">Deny by default.</b> A product is OTC only if every ingredient is explicitly allowed for its route and strength. Everything else needs a prescription, and MediBot shows this sentence first, word for word:</p>
            <blockquote className="rounded-[12px] border-l-4 border-red bg-red-soft/60 px-4 py-3 font-sans text-[14.5px] font-medium text-ink">This medication requires a valid prescription. Please consult your doctor.</blockquote>
            <Table head={['Category', 'Meaning', 'Basis']} rows={[
              [<Chip key="c" tone="red">Banned</Chip>, 'An in-force Section 26A prohibition (exact ingredient set, release, form, strength)', 'CDSCO 2021 list, Gazette 2023 (14 FDCs), 2024 (156 FDCs)'],
              [<Chip key="c" tone="red">Controlled / X</Chip>, 'Narcotic / psychotropic, Schedule X', 'NDPS Act 1985; Drugs Rules Sch. X'],
              [<Chip key="c" tone="red">Schedule H1</Chip>, '46 entries', 'Drugs Rules Sch. H1'],
              [<Chip key="c" tone="red">Schedule H</Chip>, '536 entries incl. antibiotics, hormones', 'Drugs Rules Sch. H'],
              [<Chip key="c" tone="amber">Prescription</Chip>, 'Not provably OTC: injectables, habit-forming, steroids, cough syrups, above OTC strength', 'Deny-by-default rules'],
              [<Chip key="c" tone="green">OTC</Chip>, 'Every ingredient allowed for this route and strength', 'Sourced OTC allowlist'],
            ]} />
            <ul className="list-disc space-y-1 pl-5">
              <li><b className="text-ink">Emergencies</b> (overdose, chest pain, self-harm) get 112 / 108 / Tele-MANAS 14416 before anything else.</li>
              <li><b className="text-ink">No diagnosis, no prescribing, no doses</b> — fixed refusals, checked again on the way out.</li>
              <li><b className="text-ink">Banned medicines</b> get a legal notice and no alternatives.</li>
              <li>Safety texts are fixed sentences, never written or rewritten by an AI model.</li>
            </ul>
          </Section>

          <Section id="alternatives" title="Identical alternatives">
            <p>An alternative is shown only if it has the same <b className="text-ink">Composition ID</b>: the same ingredients, the same strengths, the same dosage form and the same release type. "Similar" medicines are never suggested. Every alternative carries a <BadgeCheck className="inline size-4 text-green" /> verified mark and the advice to confirm the switch with a doctor or pharmacist.</p>
            <p>Savings are compared <b className="text-ink">per tablet / ml / g</b>, never per pack. Jan Aushadhi generics (2,439 products, at MRP) appear as a walk-in option.</p>
          </Section>

          <Section id="prices" title="Prices">
            <Table head={['Order', 'Source', 'Label']} rows={[
              ['1', 'Cache of a live check younger than 6 h', '● checked recently'],
              ['2', 'Live product page — Tata 1mg, Apollo, Netmeds, PharmEasy, Truemeds (reply waits ≤ 2.5 s)', '● live now'],
              ['3', 'Dated record from the datasets', '○ as of <date>'],
            ]} />
            <p>Only product pages allowed by each site's robots.txt are fetched — never search, cart or API pages — at most one request per second per site, with an identifying user agent. Prices above the government ceiling (NPPA, NLEM 2022) are flagged.</p>
          </Section>

          <Section id="health" title="Health information">
            <p>Every sentence of a health answer is <b className="text-ink">copied from a retrieved, cited passage</b> — nothing is generated. Sources: medicine monographs (MID dataset), US FDA labels (DailyMed, never dosage sections), SIDER side-effect frequencies, verbatim official labels, and a curated FAQ (Jan Aushadhi, schedules, antibiotics, NPPA, Tele-MANAS…). Interactions come from DDInter (208,446 graded pairs). When nothing reliable is found, MediBot says so and points you to the leaflet or a pharmacist.</p>
          </Section>

          <Section id="data" title="Data">
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
              <Stat n="570,968" label="product listings" /><Stat n="37,785" label="exact compositions" /><Stat n="942,833" label="price observations" />
              <Stat n="208,446" label="interaction pairs" /><Stat n="21,286" label="Jan Aushadhi Kendras" /><Stat n="4,664" label="ingredients with schedules" />
            </div>
            <p>Built from 26 public sources (Kaggle catalogs of 1mg, Apollo, Netmeds, PharmEasy; MID; SIDER; DDInter; Jan Aushadhi; CDSCO / Gazette notifications; NPPA ceiling prices), each listed with its licence in the project's source register. Some sources are non-commercial (CC BY-NC-SA, SIDER, DDInter) — fine for this prototype, to be replaced for commercial use.</p>
          </Section>

          <Section id="quality" title="Quality & evaluation">
            <p>An evaluation set of <b className="text-ink">631 cases (653 turns)</b> was built before the bot: hand-labelled policy medicines, "without prescription" requests, typos and Hinglish, diagnosis / dosing bait, emergencies, 20 prompt-injection attempts, and multi-turn conversations.</p>
            <Table head={['Measure', 'Result']} rows={[
              ['Restricted-drug block rate', '100%'], ['OTC false positives', '1.0%'], ['Disclaimer shown', '100%'],
              ['Average saving with identical alternatives', '76.9%'], ['Questions resolved', '98.5%'], ['Multi-turn context kept', '100%'],
              ['Diagnosis / dosing violations', '0'], ['Uncited health answers', '0'], ['Score (measurable offline)', '80 / 80'],
            ]} />
          </Section>

          <Section id="privacy" title="Privacy">
            <ul className="list-disc space-y-1 pl-5">
              <li>Sessions are anonymous. <b className="text-ink">No message text is stored</b> — only counts (intent, intercepted, latency) for quality metrics.</li>
              <li>"Forget this session" deletes everything tied to it.</li>
              <li>Bill / prescription photos are <b className="text-ink">never stored</b>; the AI reader is opt-in and says so.</li>
              <li>Your cabinet and bill list live <b className="text-ink">only in your browser</b>.</li>
              <li>Phone numbers, emails, Aadhaar and PAN are removed before any text reaches an AI model.</li>
            </ul>
          </Section>

          <Section id="api" title="API">
            <p>Everything the app does is available over a JSON API. Interactive docs: <a href={DOCS} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 font-sans font-medium text-green hover:underline">/docs<ExternalLink className="size-3" /></a>.</p>
            <Table head={['Method', 'Path', 'What it does']} rows={[
              ['POST', '/api/v1/medibot/query', 'Ask a question → safety guard, detected medicine, cards, alternatives (language: en / hi)'],
              ['POST', '/api/v1/session/start · /session/ack', 'Anonymous session + disclaimer acknowledgement'],
              ['GET', '/api/v1/search', 'Medicine search (⌘K)'],
              ['GET', '/api/v1/medicine/{id}', 'Medicine sheet: composition, prices, alternatives, info'],
              ['POST', '/api/v1/bill/plan · /bill/parse · /bill/read', 'Cheapest split for a list · parse pasted text · read a photo'],
              ['POST', '/api/v1/cabinet/check', 'Monthly cost, cheapest identical option, interactions'],
              ['POST', '/api/v1/feedback', '1–5 rating for an answer'],
              ['DELETE', '/api/v1/session/{id}', 'Forget a session'],
            ].map(([m, p, d]) => [<span key="m" className="num rounded bg-line/50 px-1.5 py-0.5 text-[11.5px] font-semibold text-ink-2">{m}</span>, <code key="p" className="text-[12.5px] text-navy">{p}</code>, d])} />
          </Section>

          <Section id="faq" title="FAQ">
            {([
              ['Is a cheaper alternative really the same medicine?', 'Only alternatives with the same Composition ID are shown: same ingredients, strengths, form and release. Brands can differ in fillers or coatings, so confirm any switch with your doctor or pharmacist.'],
              ['Why does MediBot ask for a prescription for common medicines like pantoprazole?', 'Because Indian law lists them in Schedule H. MediBot follows the law, even when shops often sell them without one.'],
              ['Can MediBot tell me how much to take?', 'No. Doses depend on your age, weight and health — follow your prescription or the pack, and ask your pharmacist.'],
              ['Are the prices exact?', 'They are the pharmacy\'s own product-page prices, live or checked within 6 hours, or a dated record. Delivery fees are not included.'],
              ['What happens in an emergency?', 'MediBot shows 112 / 108 (and Tele-MANAS 14416) first. It cannot help with emergencies itself.'],
            ] as const).map(([q, a]) => (
              <details key={q} className="group rounded-[12px] border border-line bg-sheet px-4 py-3 font-sans">
                <summary className="cursor-pointer list-none text-[14.5px] font-medium text-navy">{q}<span className="float-right text-ink-3 transition group-open:rotate-45">+</span></summary>
                <p className="mt-2 text-[13.5px] leading-relaxed text-ink-2">{a}</p>
              </details>))}
          </Section>

          <p className="rounded-[12px] border border-navy/25 bg-pale/50 p-4 font-sans text-[12.5px] text-ink-2">MediBot is an informational tool. It does not diagnose medical conditions or prescribe medications. Users must always consult a qualified medical professional before taking any medication. Emergency: <a href="tel:112" className="font-semibold text-red">112</a> / <a href="tel:108" className="font-semibold text-red">108</a>.</p>
        </article>
      </div>
    </div>
  )
}
