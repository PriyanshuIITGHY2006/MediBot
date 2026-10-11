import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUp, BadgeIndianRupee, BookOpen,  Command, MessageCircle, Pill as PillIcon, Receipt, FlaskConical, Mic, MicOff, Moon, PanelLeftClose, PanelRight, PanelRightClose, PanelRightOpen, Pill, RotateCcw, Search, ShieldCheck, Store, Sun, SquarePen } from 'lucide-react'
import { Mark, Wordmark } from './brand'
import { api, type Card, type Citation, type QueryResponse, type SearchHit } from './api'
import { CardView } from './cards'
import { Sheet } from './Sheet'
import { BillPage } from './Bill'
import { CabinetPage } from './Cabinet'
import { WikiPage } from './Wiki'
import { Button, Chip, cx } from './ui'
import { setLang, t, useLang } from './i18n'

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
const DISCLAIMER_HI = 'MediBot केवल जानकारी देने वाला टूल है। यह बीमारी की पहचान (डायग्नोसिस) नहीं करता और दवा नहीं लिखता। कोई भी दवा लेने से पहले हमेशा किसी योग्य डॉक्टर से सलाह लें।'  // = safety/messages_hi.py
const MAX = 1000
const uid = () => Math.random().toString(36).slice(2, 10)
type TabKey = 'chat' | 'bill' | 'cabinet' | 'wiki'
const TABS = [['chat', 'Chat', MessageCircle], ['bill', 'Bill split', Receipt], ['cabinet', 'Cabinet', PillIcon], ['wiki', 'Wiki', BookOpen]] as const
const store = {
  get: (k: string) => { try { return sessionStorage.getItem(k) } catch { return null } },
  set: (k: string, v: string) => { try { sessionStorage.setItem(k, v) } catch { /* private mode */ } },
  del: (k: string) => { try { sessionStorage.removeItem(k) } catch { /* private mode */ } },
}

// ---------------------------------------------------------------- navigation: left sidebar (tablet / desktop), bottom bar (phone)
function NavRail({ tab, onTab, onNew, onSearch, onForget, collapsed, onCollapse }: { tab: TabKey; onTab: (k: TabKey) => void; onNew: () => void; onSearch: () => void; onForget: () => void; collapsed: boolean; onCollapse: () => void }) {
  return (
    <nav aria-label="Sections" className={cx('relative z-10 flex h-full shrink-0 flex-col border-r border-line/70 bg-sheet/60 backdrop-blur transition-[width] duration-300 ease-out max-md:hidden', collapsed ? 'w-[64px]' : 'w-[232px]')}>
      <div className={cx('flex h-14 items-center', collapsed ? 'justify-center' : 'justify-between pr-2 pl-4')}>
        {collapsed ? <button onClick={onCollapse} aria-label="Expand sidebar" title="Expand sidebar" className="rounded-lg p-1 hover:bg-line/50"><Mark size={28} /></button>
          : <><Wordmark /><button onClick={onCollapse} aria-label="Collapse sidebar" title="Collapse sidebar" className="rounded-lg p-1.5 text-ink-3 hover:bg-line/50 hover:text-ink"><PanelLeftClose className="size-4" /></button></>}
      </div>
      <div className="space-y-1 p-2.5">
        <button onClick={onNew} title={t('New chat')} className={cx('flex w-full items-center gap-2.5 rounded-[10px] border border-line bg-sheet px-2.5 py-2 text-[13.5px] font-medium text-navy transition hover:border-teal/50 hover:shadow-[var(--shadow-soft)]', collapsed && 'justify-center px-0')}>
          <SquarePen className="size-4 shrink-0 text-green" />{!collapsed && t('New chat')}
        </button>
        <button onClick={onSearch} title={t('Search medicines') + ' (Ctrl+K)'} className={cx('group flex w-full items-center gap-2.5 rounded-[10px] border border-teal/35 bg-pale/70 px-2.5 py-2 text-[13.5px] font-medium text-navy transition hover:border-teal hover:bg-pale hover:shadow-[var(--shadow-soft)]', collapsed && 'justify-center px-0')}>
          <Search className="size-4 shrink-0 text-green transition group-hover:scale-110" />{!collapsed && <><span className="flex-1 text-left">{t('Search medicines')}</span><kbd className="num inline-flex items-center rounded border border-teal/30 bg-sheet/70 px-1 text-[10.5px] text-ink-3"><Command className="size-2.5" />K</kbd></>}
        </button>
        <div className="h-2" />
        {TABS.map(([k, l, Icon]) => (
          <button key={k} onClick={() => onTab(k)} aria-current={tab === k ? 'page' : undefined} title={t(l)}
            className={cx('group relative flex w-full items-center gap-2.5 rounded-[10px] px-2.5 py-2 text-[14px] transition', collapsed && 'justify-center px-0',
              tab === k ? 'bg-pale font-medium text-navy' : 'text-ink-2 hover:bg-line/45 hover:text-ink')}>
            {tab === k && <span className="absolute top-2 bottom-2 left-0 w-[3px] rounded-full bg-teal" />}
            <Icon className={cx('size-[18px] shrink-0 transition', tab === k ? 'text-green' : 'text-ink-3 group-hover:text-ink-2')} />{!collapsed && <span className="truncate">{t(l)}</span>}
          </button>))}
      </div>
      <div className="mt-auto space-y-2 p-3">
        {!collapsed && <button onClick={onForget} className="w-full px-1 text-left text-[11.5px] text-ink-3 hover:text-red">{t('Forget this session')}</button>}
      </div>
    </nav>
  )
}

function BottomNav({ tab, onTab }: { tab: TabKey; onTab: (k: TabKey) => void }) {
  return (
    <nav aria-label="Sections" className="grid shrink-0 grid-cols-4 border-t border-line/70 bg-sheet/90 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
      {TABS.map(([k, l, Icon]) => (
        <button key={k} onClick={() => onTab(k)} aria-current={tab === k ? 'page' : undefined}
          className={cx('flex flex-col items-center gap-0.5 py-2 text-[11px] transition', tab === k ? 'font-medium text-green' : 'text-ink-3')}>
          <span className={cx('grid h-7 w-12 place-items-center rounded-full transition', tab === k && 'bg-pale')}><Icon className="size-[18px]" /></span>{t(l)}
        </button>))}
    </nav>
  )
}

// ---------------------------------------------------------------- start-page backdrop
function Aurora() {
  return <div className="aurora" aria-hidden><div className="aurora-blob b1" /><div className="aurora-blob b2" /></div>
}

// ---------------------------------------------------------------- onboarding (14.1)
function Onboarding({ onAccept, busy, error }: { onAccept: () => void; busy: boolean; error: string | null }) {
  const lang = useLang()
  return (
    <div className="relative grid min-h-full place-items-center px-5 py-12">
      <Aurora />
      <div className="stagger relative z-10 w-full max-w-[540px] space-y-8">
        <div className="flex items-start justify-between"><Wordmark size="lg" underline />
          <button onClick={() => setLang(lang === 'hi' ? 'en' : 'hi')} className="rounded-full border border-line px-3 py-1 text-[13px] text-ink-2 hover:border-teal/50">{lang === 'hi' ? 'English' : 'हिंदी'}</button></div>
        <div className="space-y-3">
          <h1 className="display text-[40px] leading-[1.08] text-navy">{t("Pay less for the exact same medicine.")}</h1>
          <p className="say text-ink-2">{t("Live prices from five Indian pharmacies, identical-composition alternatives including Jan Aushadhi, and medicine information you can check against its sources.")}</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="lift rounded-[var(--radius-card)] border border-line bg-sheet/90 p-4 backdrop-blur hover:border-teal/40 hover:shadow-[var(--shadow-soft)]">
            <div className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-green"><ShieldCheck className="size-4" />{t('MediBot can')}</div>
            <ul className="space-y-1.5 text-[14px] text-ink-2"><li>{t("Compare prices per tablet")}</li><li>{t("Find identical cheaper options")}</li><li>{t("Explain uses, side effects and interactions, with sources")}</li><li>{t("Find Jan Aushadhi Kendras")}</li></ul>
          </div>
          <div className="lift rounded-[var(--radius-card)] border border-line bg-sheet/90 p-4 backdrop-blur hover:border-red/30 hover:shadow-[var(--shadow-soft)]">
            <div className="mb-2 text-[13px] font-semibold text-red">{t("MediBot won't")}</div>
            <ul className="space-y-1.5 text-[14px] text-ink-2"><li>{t("Diagnose a condition")}</li><li>{t("Recommend a medicine or a dose")}</li><li>{t("Help buy prescription medicines without a prescription")}</li></ul>
          </div>
        </div>
        <div className="rounded-[var(--radius-card)] border border-navy/25 bg-pale/60 p-4 backdrop-blur dark:bg-pale/40">
          <p className="say-sm text-ink">{DISCLAIMER}</p>
          {lang === 'hi' && <p className="say-sm mt-1.5 text-ink-2">{DISCLAIMER_HI}</p>}
          <p className="mt-2 text-[12px] text-ink-3">{t('Emergency: call')} <a className="font-semibold text-red" href="tel:112">112</a> {t('or')} <a className="font-semibold text-red" href="tel:108">108</a>. {t('Conversations are anonymous and no message text is stored.')}</p>
        </div>
        {error && <p className="text-sm text-red">{error}</p>}
        <button onClick={onAccept} disabled={busy}
          className="cta-shine w-full rounded-[12px] bg-navy py-3 text-[15px] font-semibold text-white shadow-[var(--shadow-soft)] transition hover:-translate-y-px hover:bg-navy/90 active:translate-y-0 disabled:opacity-50 dark:bg-teal dark:text-paper">
          {busy ? t('Starting…') : t('I understand — start')}
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
          <input autoFocus value={q} onChange={e => setQ(e.target.value)} placeholder={t('Search any medicine — brand or generic')}
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
                  <div className="truncate text-xs text-ink-3">{h.composition ?? t('composition not verified')}</div></div>
                <Chip tone={h.requires_prescription ? 'red' : 'green'}>{h.schedule}</Chip>
              </button>
            </li>
          ))}
          {q.trim().length >= 2 && !hits.length && <li className="px-3 py-3 text-sm text-ink-3">{t("No match yet — keep typing, or ask in the chat.")}</li>}
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
      <p className="pt-1 text-[14px] text-ink-3">{t("Reading your message, checking prices and sources…")}</p>
    </div>)
  if (m.error) return (
    <div className="flex gap-3.5"><Mark size={30} />
      <div className="flex flex-wrap items-center gap-2 pt-1 text-[14px] text-red">{m.error}<Button variant="quiet" onClick={() => onRetry(m)}><RotateCcw className="size-3.5" />{t('Retry')}</Button></div>
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
            {m.rated ? <span>{t('Thanks for rating ({r}/5)', { r: m.rated })}</span> : <>{t('Helpful?')}{[1, 2, 3, 4, 5].map(r => (
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
  const lang = useLang()
  const [session, setSession] = useState<string | null>(() => store.get('mb-session'))
  const [acked, setAcked] = useState(() => store.get('mb-ack') === '1')
  const [busy, setBusy] = useState(false)
  const [bootErr, setBootErr] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [focus, setFocus] = useState<string | null>(null)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [side, setSide] = useState(() => { try { return localStorage.getItem('mb-side') !== '0' } catch { return true } })
  const [navMini, setNavMini] = useState(() => { try { return localStorage.getItem('mb-nav') === 'mini' } catch { return false } })
  const toggleNav = () => setNavMini(v => { try { localStorage.setItem('mb-nav', v ? 'full' : 'mini') } catch { /* */ } return !v })
  const goTab = (k: TabKey) => { setTab(k); setSheetOpen(false) }
  const [panelW, setPanelW] = useState(() => { try { return Math.min(720, Math.max(320, Number(localStorage.getItem('mb-panel-w')) || 440)) } catch { return 440 } })
  const [dragging, setDragging] = useState(false)
  const startDrag = (e: React.PointerEvent) => {
    e.preventDefault(); setDragging(true)
    const move = (ev: PointerEvent) => setPanelW(Math.round(Math.min(720, Math.min(innerWidth * 0.6, Math.max(320, innerWidth - ev.clientX)))))
    const up = () => { setDragging(false); removeEventListener('pointermove', move); removeEventListener('pointerup', up)
      setPanelW(w => { try { localStorage.setItem('mb-panel-w', String(w)) } catch { /* */ } return w }) }
    addEventListener('pointermove', move); addEventListener('pointerup', up)
  }
  const toggleSide = useCallback(() => setSide(v => { try { localStorage.setItem('mb-side', v ? '0' : '1') } catch { /* */ } return !v }), [])
  const [palette, setPalette] = useState(false)
  const [tab, setTab] = useState<TabKey>(() => { const v = store.get('mb-tab'); return v === 'bill' || v === 'cabinet' || v === 'wiki' ? v : 'chat' })
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'))
  const [listening, setListening] = useState(false)
  const rec = useRef<SR | null>(null)
  const end = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { document.documentElement.classList.toggle('dark', dark); try { localStorage.setItem('mb-theme', dark ? 'dark' : 'light') } catch { /* */ } }, [dark])
  useEffect(() => { store.set('mb-tab', tab) }, [tab])
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [msgs])
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setPalette(p => !p) }
      if ((e.metaKey || e.ctrlKey) && e.key === '\\') { e.preventDefault(); toggleSide() }
    }
    addEventListener('keydown', k); return () => removeEventListener('keydown', k)
  }, [toggleSide])

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
      const res = await api.query(session, q, lang)
      setMsgs(m => m.map(x => x.id === botId ? { ...x, pending: false, res } : x))
      const pid = res.detected_medication?.product_id
      if (pid) { setFocus(pid); setSide(true) }   // a medicine in the answer -> the panel slides in
    } catch (e) {
      setMsgs(m => m.map(x => x.id === botId ? { ...x, pending: false, error: (e as Error).message } : x))
    }
  }, [session, lang])

  const rate = async (m: Msg, r: number) => {
    setMsgs(ms => ms.map(x => x.id === m.id ? { ...x, rated: r } : x))
    if (session && m.res?.turn_id) api.feedback(session, m.res.turn_id, r).catch(() => { /* rating is best-effort */ })
  }
  const open = (id: string) => { setFocus(id); setSheetOpen(true); setSide(true) }
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
    <div className="relative flex h-full">
      {tab === 'chat' && !msgs.length && <Aurora />}
      <NavRail tab={tab} onTab={goTab} onNew={() => { setMsgs([]); setFocus(null); setTab('chat') }} onSearch={() => setPalette(true)} onForget={reset} collapsed={navMini} onCollapse={toggleNav} />
      <div className="relative z-10 flex min-w-0 flex-1 flex-col">
      <header className="flex h-14 shrink-0 items-center justify-between gap-2 px-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <span className="md:hidden"><Mark size={28} /></span>
          <span className="truncate text-[15px] font-semibold text-navy md:hidden">{t(TABS.find(x => x[0] === tab)![1])}</span>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="quiet" onClick={() => setPalette(true)} aria-label="Search medicines" className="text-ink-2 md:hidden"><Search className="size-3.5" /><span className="hidden sm:inline">{t('Search')}</span><kbd className="num hidden items-center text-[11px] text-ink-3 sm:inline-flex"><Command className="size-3" />K</kbd></Button>
          {focus && tab === 'chat' && <Button variant="ghost" className="lg:hidden" onClick={() => setSheetOpen(true)} aria-label="Open medicine sheet"><PanelRight className="size-4" /></Button>}
          {tab === 'chat' && focus && !side && <Button variant="ghost" className="max-lg:hidden" onClick={toggleSide} aria-label="Show medicine panel" title="Show panel (Ctrl+\\)"><PanelRightOpen className="size-4" /></Button>}
          <Button variant="ghost" onClick={() => setLang(lang === 'hi' ? 'en' : 'hi')} aria-label={lang === 'hi' ? 'Switch to English' : 'हिंदी में देखें'} title={lang === 'hi' ? 'English' : 'हिंदी'}><span className="text-[13px] font-semibold">{lang === 'hi' ? 'EN' : 'हिं'}</span></Button>
          <Button variant="ghost" onClick={() => setDark(d => !d)} aria-label="Toggle dark mode">{dark ? <Sun className="size-4" /> : <Moon className="size-4" />}</Button>
          <Button variant="ghost" className="md:hidden" onClick={() => { setMsgs([]); setFocus(null); setTab('chat') }} aria-label="New chat" title="New chat"><SquarePen className="size-4" /></Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {tab === 'bill' && <BillPage onOpen={open} />}
        {tab === 'wiki' && <WikiPage />}
        {tab === 'cabinet' && <CabinetPage onOpen={open} onPlan={lines => {
          try { localStorage.setItem('mb-bill', JSON.stringify(lines.map(l => ({ ...l, id: uid() })))) } catch { /* private mode */ }
          setTab('bill'); setSheetOpen(false)
        }} />}
        <main className={cx('flex min-w-0 flex-1 flex-col', tab !== 'chat' && 'hidden')}>
          <div className="flex-1 overflow-y-auto" aria-live="polite">
            <div className="mx-auto max-w-[720px] space-y-7 px-5 pt-8 pb-10">
              {!msgs.length && (
                <div className="relative space-y-8 pt-[9vh]">
                  <div className="stagger relative z-10 space-y-3">
                    <Mark size={44} className="float" />
                    <h1 className="display text-[34px] leading-tight text-navy">{t("Which medicine can I help you with?")}</h1>
                    <p className="say text-ink-2">{t("Type a brand, a generic name or a question — in English, Hindi or Hinglish. Typos are fine.")}</p>
                  </div>
                  <div className="stagger relative z-10 grid gap-2.5 sm:grid-cols-2">
                    {EXAMPLES.map(({ icon: Icon, title, q }) => (
                      <button key={q} onClick={() => send(q)}
                        className="lift group flex items-start gap-3 rounded-[var(--radius-card)] border border-line bg-sheet/90 p-3.5 text-left backdrop-blur hover:border-teal/50 hover:shadow-[var(--shadow-soft)]">
                        <span className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-pale text-green transition group-hover:scale-110 group-hover:bg-teal group-hover:text-white"><Icon className="size-4" /></span>
                        <span className="min-w-0"><span className="block text-[14px] font-medium text-navy">{t(title)}</span><span className="block truncate text-[13px] text-ink-3">“{q}”</span></span>
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
            <div className="mx-auto flex max-w-[720px] items-end gap-2 rounded-[22px] border border-line bg-sheet px-4 py-2.5 shadow-[var(--shadow-soft)] transition focus-within:border-teal/60">
              <textarea ref={box} rows={1} value={input} maxLength={MAX} aria-label="Message MediBot"
                placeholder={lastFocusName ? t('Ask about {name}, or another medicine…', { name: lastFocusName }) : t('e.g. Augmentin 625 ka sasta option?')}
                onChange={e => { setInput(e.target.value); e.target.style.height = 'auto'; e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px' }}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input) } }}
                className="max-h-40 min-h-6 flex-1 resize-none bg-transparent py-1.5 text-[15.5px] leading-relaxed outline-none focus-visible:outline-none placeholder:text-ink-3" />
              {input.length > MAX * 0.8 && <span className="num pb-1.5 text-[11px] text-ink-3">{input.length}/{MAX}</span>}
              {SpeechCtor && <Button type="button" variant="ghost" onClick={mic} aria-label={listening ? 'Stop voice input' : 'Voice input'} className={cx(listening && 'text-red')}>{listening ? <MicOff className="size-4" /> : <Mic className="size-4" />}</Button>}
              <button type="submit" disabled={!input.trim()} aria-label="Send" className="grid size-9 shrink-0 place-items-center rounded-full bg-navy text-white transition hover:bg-navy/90 disabled:bg-line-2 disabled:text-ink-3 dark:bg-teal dark:text-paper"><ArrowUp className="size-[18px]" strokeWidth={2.4} /></button>
            </div>
            <p className="mx-auto mt-2 max-w-[720px] text-center text-[11.5px] text-ink-3">{t('Not medical advice. Confirm any medicine change with your doctor or pharmacist. Emergency:')} <a href="tel:112" className="text-red">112</a></p>
          </form>
        </main>

        <aside style={{ '--pw': panelW + 'px' } as React.CSSProperties}
          className={cx('relative shrink-0 border-l border-line bg-sheet lg:overflow-hidden', !dragging && 'lg:transition-[width,opacity] lg:duration-300 lg:ease-out',
          tab === 'chat' && (!side || !focus) ? 'lg:w-0 lg:border-l-0 lg:opacity-0' : 'lg:w-[var(--pw)]',
          tab !== 'chat' && (sheetOpen ? 'lg:fixed lg:inset-y-0 lg:right-0 lg:z-40 lg:shadow-[var(--shadow-soft)] rise' : 'lg:hidden'),
          'max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-40 max-lg:h-[82vh] max-lg:w-full max-lg:rounded-t-2xl max-lg:border-t max-lg:border-l-0 max-lg:transition-transform',
          sheetOpen ? 'max-lg:translate-y-0' : 'max-lg:translate-y-full')}>
          {tab === 'chat' && focus && side && (
            <div className="group absolute inset-y-0 left-0 z-10 w-2 -translate-x-1/2 cursor-col-resize max-lg:hidden" onPointerDown={startDrag}
              onDoubleClick={() => { setPanelW(440); try { localStorage.setItem('mb-panel-w', '440') } catch { /* */ } }} title="Drag to resize · double-click to reset">
              <span className={cx('absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full transition', dragging ? 'bg-teal' : 'bg-transparent group-hover:bg-teal/60')} />
            </div>)}
          {tab === 'chat' && focus && side && (
            <button onClick={toggleSide} aria-label="Hide medicine panel" title="Hide panel (Ctrl+\\)"
              className="absolute top-3.5 right-3 z-20 grid size-8 place-items-center rounded-[9px] text-ink-3 transition hover:bg-line/60 hover:text-ink max-lg:hidden">
              <PanelRightClose className="size-4" />
            </button>)}
          <div className="h-full lg:w-[var(--pw)]"><Sheet productId={focus} onClose={() => setSheetOpen(false)} onAsk={q => { setSheetOpen(false); send(q) }} onOpen={open} /></div>
        </aside>
        {sheetOpen && <div className={cx('fixed inset-0 z-30 bg-ink/20', tab === 'chat' && 'lg:hidden')} onClick={() => setSheetOpen(false)} />}
      </div>
      <BottomNav tab={tab} onTab={goTab} />
      </div>

      <Palette open={palette} onClose={() => setPalette(false)} onPick={h => { setPalette(false); open(h.product_id) }} />
    </div>
  )
}
