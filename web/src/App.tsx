import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUp, BadgeIndianRupee, Command, FlaskConical, Mic, MicOff, Moon, PanelRight, Pill, RotateCcw, Search, ShieldCheck, Store, Sun, SquarePen } from 'lucide-react'
import { Mark, Wordmark } from './brand'
import { api, type Card, type Citation, type QueryResponse, type SearchHit } from './api'
import { CardView } from './cards'
import { Sheet } from './Sheet'
import { Button, Chip, cx } from './ui'

type Msg = { id: string; role: 'user' | 'bot'; text: string; res?: QueryResponse; error?: string; pending?: boolean; rated?: number }

const EXAMPLES: { icon: typeof Pill; title: string; q: string }[] = [
  { icon: BadgeIndianRupee, title: 'Find a cheaper identical medicine', q: 'Cheaper alternative to Augmentin 625 Duo' },
  { icon: Search, title: 'Compare prices across 5 pharmacies', q: 'Dolo 650 price' },
  { icon: ShieldCheck, title: 'Is it safe in pregnancy?', q: 'Is Crocin safe in pregnancy?' },
  { icon: FlaskConical, title: 'Check two medicines together', q: 'Can I take Saridon and Combiflam together?' },
  { icon: Pill, title: 'Ask in Hinglish', q: 'Pan 40 ka sasta option batao' },
  { icon: Store, title: 'Nearest Jan Aushadhi Kendra', q: 'Jan Aushadhi store near 110001' },
]
const DISCLAIMER = 'MediBot is an informational tool. It does not diagnose medical conditions or prescribe medications. Users must always consult a qualified medical professional before taking any medication.'
const MAX = 1000
const uid = () => Math.random().toString(36).slice(2, 10)
const store = {
  get: (k: string) => { try { return sessionStorage.getItem(k) } catch { return null } },
  set: (k: string, v: string) => { try { sessionStorage.setItem(k, v) } catch { /* private mode */ } },
  del: (k: string) => { try { sessionStorage.removeItem(k) } catch { /* private mode */ } },
}

// ---------------------------------------------------------------- onboarding (14.1)
function Onboarding({ onAccept, busy, error }: { onAccept: () => void; busy: boolean; error: string | null }) {
  return (
    <div className="grid min-h-full place-items-center px-5 py-12">
      <div className="w-full max-w-[540px] space-y-8 rise">
        <Wordmark size="lg" underline />
        <div className="space-y-3">
          <h1 className="display text-[40px] leading-[1.08] text-navy">Pay less for the exact same medicine.</h1>
          <p className="say text-ink-2">Live prices from five Indian pharmacies, identical-composition alternatives including Jan Aushadhi, and medicine information you can check against its sources.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-[var(--radius-card)] border border-line bg-sheet p-4">
            <div className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-green"><ShieldCheck className="size-4" />MediBot can</div>
            <ul className="space-y-1.5 text-[14px] text-ink-2"><li>Compare prices per tablet</li><li>Find identical cheaper options</li><li>Explain uses, side effects and interactions, with sources</li><li>Find Jan Aushadhi Kendras</li></ul>
          </div>
          <div className="rounded-[var(--radius-card)] border border-line bg-sheet p-4">
            <div className="mb-2 text-[13px] font-semibold text-red">MediBot won't</div>
            <ul className="space-y-1.5 text-[14px] text-ink-2"><li>Diagnose a condition</li><li>Recommend a medicine or a dose</li><li>Help buy prescription medicines without a prescription</li></ul>
          </div>
        </div>
        <div className="rounded-[var(--radius-card)] border border-navy/25 bg-pale/50 p-4 dark:bg-pale/40">
          <p className="say-sm text-ink">{DISCLAIMER}</p>
          <p className="mt-2 text-[12px] text-ink-3">Emergency: call <a className="font-semibold text-red" href="tel:112">112</a> or <a className="font-semibold text-red" href="tel:108">108</a>. Conversations are anonymous and no message text is stored.</p>
        </div>
        {error && <p className="text-sm text-red">{error}</p>}
        <button onClick={onAccept} disabled={busy}
          className="w-full rounded-[12px] bg-navy py-3 text-[15px] font-semibold text-white transition hover:bg-navy/90 disabled:opacity-50 dark:bg-teal dark:text-paper">
          {busy ? 'Starting…' : 'I understand — start'}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- ⌘K (14.4)
function Palette({ open, onClose, onPick }: { open: boolean; onClose: () => void; onPick: (h: SearchHit) => void }) {
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchHit[]>([])
  const [i, setI] = useState(0)
  useEffect(() => { if (!open) { setQ(''); setHits([]) } }, [open])
  useEffect(() => {
    if (q.trim().length < 2) { setHits([]); return }
    const t = setTimeout(() => api.search(q).then(r => { setHits(r.results); setI(0) }).catch(() => setHits([])), 160)
    return () => clearTimeout(t)
  }, [q])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/20 px-4 pt-[12vh] backdrop-blur-[1px]" onClick={onClose}>
      <div role="dialog" aria-label="Search medicines" className="w-full max-w-xl overflow-hidden rounded-xl border border-line-2 bg-sheet rise" onClick={e => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Search className="size-4 text-ink-3" />
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder="Search any medicine — brand or generic"
            onKeyDown={e => {
              if (e.key === 'Escape') onClose()
              if (e.key === 'ArrowDown') { e.preventDefault(); setI(x => Math.min(x + 1, hits.length - 1)) }
              if (e.key === 'ArrowUp') { e.preventDefault(); setI(x => Math.max(x - 1, 0)) }
              if (e.key === 'Enter' && hits[i]) onPick(hits[i])
            }}
            className="h-12 flex-1 bg-transparent text-[15px] outline-none focus-visible:outline-none placeholder:text-ink-3" />
          <kbd className="num rounded border border-line px-1.5 text-[11px] text-ink-3">esc</kbd>
        </div>
        <ul className="max-h-80 overflow-y-auto py-1">
          {hits.map((h, k) => (
            <li key={h.product_id}>
              <button onMouseEnter={() => setI(k)} onClick={() => onPick(h)}
                className={cx('flex w-full items-center gap-3 px-3 py-2 text-left', k === i && 'bg-line/50')}>
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{h.name}</div>
                  <div className="truncate text-xs text-ink-3">{h.composition ?? 'composition not verified'}</div></div>
                <Chip tone={h.requires_prescription ? 'red' : 'green'}>{h.schedule}</Chip>
              </button>
            </li>
          ))}
          {q.trim().length >= 2 && !hits.length && <li className="px-3 py-3 text-sm text-ink-3">No match yet — keep typing, or ask in the chat.</li>}
        </ul>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- voice (Web Speech API, when the browser has it)
type SR = { lang: string; interimResults: boolean; onresult: (e: { results: { 0: { transcript: string } }[] }) => void; onend: () => void; start: () => void; stop: () => void }
const SpeechCtor = (globalThis as unknown as { SpeechRecognition?: new () => SR; webkitSpeechRecognition?: new () => SR }).SpeechRecognition
  ?? (globalThis as unknown as { webkitSpeechRecognition?: new () => SR }).webkitSpeechRecognition

// ---------------------------------------------------------------- reply
function Reply({ m, onAsk, onOpen, onRate, onRetry }: { m: Msg; onAsk: (q: string) => void; onOpen: (id: string) => void; onRate: (m: Msg, r: number) => void; onRetry: (m: Msg) => void }) {
  if (m.pending) return (
    <div className="flex gap-3.5" aria-label="MediBot is checking">
      <Mark size={30} thinking />
      <p className="pt-1 text-[14px] text-ink-3">Reading your message, checking prices and sources…</p>
    </div>)
  if (m.error) return (
    <div className="flex gap-3.5"><Mark size={30} />
      <div className="flex flex-wrap items-center gap-2 pt-1 text-[14px] text-red">{m.error}<Button variant="quiet" onClick={() => onRetry(m)}><RotateCcw className="size-3.5" />Retry</Button></div>
    </div>)
  const cards = m.res?.cards ?? []
  const citations: Citation[] = cards.flatMap(c => c.type === 'sources' ? c.citations : [])
  const ctx = { citations, onAsk, onOpen }
  const body = cards.filter(c => c.type !== 'disclaimer' && c.type !== 'quick_replies')
  const disc = cards.find(c => c.type === 'disclaimer') as Extract<Card, { type: 'disclaimer' }> | undefined
  const qr = cards.find(c => c.type === 'quick_replies')
  return (
    <div className="flex gap-3.5 rise">
      <Mark size={30} className="mt-0.5" />
      <div className="min-w-0 flex-1 space-y-3.5">
      {body.map((c, i) => <CardView key={i} card={c} ctx={ctx} />)}
      {qr && <CardView card={qr} ctx={ctx} />}
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        {disc ? <p className="max-w-md text-[11px] text-ink-3">{disc.text}</p> : <span />}
        {m.res?.turn_id && (
          <div className="flex items-center gap-1 text-[11px] text-ink-3" aria-label="Rate this answer">
            {m.rated ? <span>Thanks for rating ({m.rated}/5)</span> : <>Helpful?{[1, 2, 3, 4, 5].map(r => (
              <button key={r} onClick={() => onRate(m, r)} aria-label={`${r} out of 5`} className="num grid size-6 place-items-center rounded-full border border-line text-[11px] hover:border-teal hover:bg-pale hover:text-green">{r}</button>))}</>}
          </div>
        )}
      </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- app
export default function App() {
  const [session, setSession] = useState<string | null>(() => store.get('mb-session'))
  const [acked, setAcked] = useState(() => store.get('mb-ack') === '1')
  const [busy, setBusy] = useState(false)
  const [bootErr, setBootErr] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [focus, setFocus] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [palette, setPalette] = useState(false)
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const [listening, setListening] = useState(false)
  const rec = useRef<SR | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { document.documentElement.classList.toggle('dark', dark); try { localStorage.setItem('mb-theme', dark ? 'dark' : 'light') } catch { /* */ } }, [dark])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [msgs])
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(p => !p) } }
    addEventListener('keydown', k); return () => removeEventListener('keydown', k)
  }, [])

  const accept = async () => {
    setBusy(true); setBootErr(null)
    try {
      const s = await api.start()
      await api.ack(s.session_id)
      store.set('mb-session', s.session_id); store.set('mb-ack', '1')
      setSession(s.session_id); setAcked(true)
    } catch (e) { setBootErr((e as Error).message) } finally { setBusy(false) }
  }

  const send = useCallback(async (text: string, replaceId?: string) => {
    const q = text.trim().slice(0, MAX)
    if (!q || !session) return
    const botId = replaceId ?? uid()
    setMsgs(m => replaceId
      ? m.map(x => x.id === replaceId ? { ...x, pending: true, error: undefined } : x)
      : [...m, { id: uid(), role: 'user', text: q }, { id: botId, role: 'bot', text: q, pending: true }])
    setInput('')
    try {
      const res = await api.query(session, q)
      setMsgs(m => m.map(x => x.id === botId ? { ...x, pending: false, res } : x))
      const pid = res.detected_medication?.product_id
      if (pid) setFocus(pid)
    } catch (e) {
      setMsgs(m => m.map(x => x.id === botId ? { ...x, pending: false, error: (e as Error).message } : x))
    }
  }, [session])

  const rate = async (m: Msg, r: number) => {
    setMsgs(ms => ms.map(x => x.id === m.id ? { ...x, rated: r } : x))
    if (session && m.res?.turn_id) api.feedback(session, m.res.turn_id, r).catch(() => { /* rating is best-effort */ })
  }
  const open = (id: string) => { setFocus(id); setSheetOpen(true) }
  const reset = async () => {
    if (session) api.forget(session).catch(() => { /* */ })
    store.del('mb-session'); store.del('mb-ack')
    setMsgs([]); setFocus(null); setSession(null); setAcked(false)
  }
  const mic = () => {
    if (!SpeechCtor) return
    if (listening) { rec.current?.stop(); return }
    const r = new SpeechCtor(); r.lang = 'en-IN'; r.interimResults = false
    r.onresult = e => setInput(x => (x ? x + ' ' : '') + e.results[0][0].transcript)
    r.onend = () => setListening(false)
    rec.current = r; setListening(true); r.start()
  }
  const lastFocusName = useMemo(() => [...msgs].reverse().find(m => m.res?.detected_medication)?.res?.detected_medication?.brand_name, [msgs])

  if (!acked || !session) return <Onboarding onAccept={accept} busy={busy} error={bootErr} />

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-line/70 bg-paper/80 px-4 backdrop-blur">
        <div className="flex items-center gap-3"><Wordmark /><span className="hidden rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-3 sm:inline">Informational · not medical advice</span></div>
        <div className="flex items-center gap-1">
          <Button variant="quiet" onClick={() => setPalette(true)} aria-label="Search medicines" className="text-ink-2"><Search className="size-3.5" /><span className="hidden sm:inline">Search</span><kbd className="num hidden items-center text-[11px] text-ink-3 sm:inline-flex"><Command className="size-3" />K</kbd></Button>
          {focus && <Button variant="ghost" className="lg:hidden" onClick={() => setSheetOpen(true)} aria-label="Open medicine sheet"><PanelRight className="size-4" /></Button>}
          <Button variant="ghost" onClick={() => setDark(d => !d)} aria-label="Toggle dark mode">{dark ? <Sun className="size-4" /> : <Moon className="size-4" />}</Button>
          <Button variant="ghost" onClick={reset} aria-label="New chat and forget this session" title="New chat — forgets this session"><SquarePen className="size-4" /></Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="flex-1 overflow-y-auto" aria-live="polite">
            <div className="mx-auto max-w-[720px] space-y-7 px-5 pt-8 pb-10">
              {!msgs.length && (
                <div className="space-y-8 pt-[9vh] rise">
                  <div className="space-y-3">
                    <Mark size={44} />
                    <h1 className="display text-[34px] leading-tight text-navy">Which medicine can I help you with?</h1>
                    <p className="say text-ink-2">Type a brand, a generic name or a question — in English, Hindi or Hinglish. Typos are fine.</p>
                  </div>
                  <div className="grid gap-2.5 sm:grid-cols-2">
                    {EXAMPLES.map(({ icon: Icon, title, q }) => (
                      <button key={q} onClick={() => send(q)}
                        className="group flex items-start gap-3 rounded-[var(--radius-card)] border border-line bg-sheet p-3.5 text-left transition hover:border-teal/50 hover:shadow-[var(--shadow-soft)]">
                        <span className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-pale text-green"><Icon className="size-4" /></span>
                        <span className="min-w-0"><span className="block text-[14px] font-medium text-navy">{title}</span><span className="block truncate text-[13px] text-ink-3">“{q}”</span></span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {msgs.map(m => m.role === 'user'
                ? <div key={m.id} className="flex justify-end rise"><p className="max-w-[80%] whitespace-pre-wrap rounded-[18px] rounded-br-[6px] bg-pale px-4 py-2.5 text-[15px] leading-relaxed text-navy dark:text-ink">{m.text}</p></div>
                : <Reply key={m.id} m={m} onAsk={send} onOpen={open} onRate={rate} onRetry={x => send(x.text, x.id)} />)}
              <div ref={end} />
            </div>
          </div>

          <form className="relative px-4 pb-3" onSubmit={e => { e.preventDefault(); send(input) }}>
            <div className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-gradient-to-t from-paper to-transparent" />
            <div className="mx-auto flex max-w-[720px] items-end gap-2 rounded-[22px] border border-line bg-sheet px-4 py-2.5 shadow-[var(--shadow-soft)] transition focus-within:border-teal/60">
              <textarea ref={box} rows={1} value={input} maxLength={MAX} aria-label="Message MediBot"
                placeholder={lastFocusName ? `Ask about ${lastFocusName}, or another medicine…` : 'e.g. Augmentin 625 ka sasta option?'}
                onChange={e => { setInput(e.target.value); e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px' }}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
                className="max-h-40 min-h-6 flex-1 resize-none bg-transparent py-1.5 text-[15.5px] leading-relaxed outline-none focus-visible:outline-none placeholder:text-ink-3" />
              {input.length > MAX * 0.8 && <span className="num pb-1.5 text-[11px] text-ink-3">{input.length}/{MAX}</span>}
              {SpeechCtor && <Button type="button" variant="ghost" onClick={mic} aria-label={listening ? 'Stop voice input' : 'Voice input'} className={cx(listening && 'text-red')}>{listening ? <MicOff className="size-4" /> : <Mic className="size-4" />}</Button>}
              <button type="submit" disabled={!input.trim()} aria-label="Send" className="grid size-9 shrink-0 place-items-center rounded-full bg-navy text-white transition hover:bg-navy/90 disabled:bg-line-2 disabled:text-ink-3 dark:bg-teal dark:text-paper"><ArrowUp className="size-[18px]" strokeWidth={2.4} /></button>
            </div>
            <p className="mx-auto mt-2 max-w-[720px] text-center text-[11.5px] text-ink-3">Not medical advice. Confirm any medicine change with your doctor or pharmacist. Emergency: <a href="tel:112" className="text-red">112</a></p>
          </form>
        </main>

        <aside className={cx('w-[440px] shrink-0 border-l border-line bg-sheet',
          'max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-40 max-lg:h-[82vh] max-lg:w-full max-lg:rounded-t-2xl max-lg:border-t max-lg:border-l-0 max-lg:transition-transform',
          sheetOpen ? 'max-lg:translate-y-0' : 'max-lg:translate-y-full')}>
          <Sheet productId={focus} onClose={() => setSheetOpen(false)} onAsk={q => { setSheetOpen(false); send(q) }} onOpen={open} />
        </aside>
        {sheetOpen && <div className="fixed inset-0 z-30 bg-ink/20 lg:hidden" onClick={() => setSheetOpen(false)} />}
      </div>

      <Palette open={palette} onClose={() => setPalette(false)} onPick={h => { setPalette(false); open(h.product_id) }} />
    </div>
  )
}
