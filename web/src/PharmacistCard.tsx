// Pharmacist Card (Phase 15.2): the list to show at the counter. Each medicine asked for, side by side with the
// identical option chosen (same Composition ID - never a "similar" one), quantity and the Rx flag. Share by
// WhatsApp, copy, print, or let the pharmacist scan the QR: it holds the list as plain text, so any phone camera
// reads it offline and nothing is uploaded anywhere.
import { useEffect, useMemo, useState } from 'react'
import QRCode from 'qrcode'
import { Check, Copy, MessageCircle, Printer, Repeat2, X } from 'lucide-react'
import { Mark } from './brand'
import { t } from './i18n'
import { Button, cx, inr } from './ui'

export type CardLine = {
  asked: string; asked_composition?: string | null
  chosen: string; same: boolean          // same = the asked product itself (no switch)
  qty: string; rx: boolean; price?: number | null; where?: string | null
}

function plainText(lines: CardLine[], title: string) {
  const rows = lines.map((l, i) => {
    const sw = l.same ? '' : `\n   → ${l.chosen} (${t('Same composition')})`
    return `${i + 1}. ${l.asked}${l.asked_composition ? ` — ${l.asked_composition}` : ''}${l.rx ? ' [Rx]' : ''}${sw}\n   ${t('Qty')}: ${l.qty}${l.price != null ? ` · ${inr(l.price)}` : ''}${l.where ? ` · ${l.where}` : ''}`
  })
  return `${title}\n\n${rows.join('\n')}\n\n${t('Please confirm each identical option before dispensing. Rx = prescription needed.')}\n— ${t('Made with MediBot · informational, not a prescription')}`
}

export function PharmacistCard({ lines, title, total, onClose }: { lines: CardLine[]; title: string; total?: number | null; onClose: () => void }) {
  const text = useMemo(() => plainText(lines, title), [lines, title])
  const [qr, setQr] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    let live = true
    QRCode.toDataURL(text.slice(0, 1800), { errorCorrectionLevel: 'L', margin: 1, width: 360, color: { dark: '#15384b', light: '#ffffff' } })
      .then(u => { if (live) setQr(u) }).catch(() => { if (live) setQr(null) })
    return () => { live = false }
  }, [text])
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    addEventListener('keydown', k); return () => removeEventListener('keydown', k)
  }, [onClose])
  const copy = async () => { try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1600) } catch { /* no clipboard */ } }
  const [date] = useState(() => new Date().toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }))

  return (
    <div className="pharm-overlay fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/30 px-3 py-6 backdrop-blur-[1px] sm:py-10" onClick={onClose}>
      <div className="w-full max-w-[680px] space-y-3 rise" onClick={e => e.stopPropagation()}>
        <div className="no-print flex flex-wrap items-center justify-end gap-2">
          <a href={`https://wa.me/?text=${encodeURIComponent(text)}`} target="_blank" rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-[10px] bg-[#1fa855] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"><MessageCircle className="size-4" />{t('Share on WhatsApp')}</a>
          <Button onClick={copy}>{copied ? <Check className="size-4" /> : <Copy className="size-4" />}{copied ? t('Copied') : t('Copy text')}</Button>
          <Button onClick={() => print()}><Printer className="size-4" />{t('Print')}</Button>
          <Button variant="ghost" onClick={onClose} aria-label={t('Close')} className="bg-sheet"><X className="size-4" /></Button>
        </div>

        <article className="pharm-card overflow-hidden rounded-[18px] border border-line bg-white text-[#17262d] shadow-[var(--shadow-soft)]">
          <header className="flex items-start justify-between gap-4 border-b-2 border-dashed border-[#cdd9d9] px-6 pt-6 pb-5">
            <div className="space-y-1">
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-[#0a7c74]">{t('For your pharmacist')}</div>
              <h2 className="font-serif text-[26px] font-medium leading-tight text-[#15384b]">{title}</h2>
              <div className="num text-[12.5px] text-[#7d8f96]">{date} · {t('{n} medicines', { n: lines.length })}{lines.some(l => !l.same) && <> · <Repeat2 className="inline size-3" /> {t('{n} switched', { n: lines.filter(l => !l.same).length })}</>}{total != null && <> · <span className="font-semibold text-[#15384b]">{inr(total)}</span></>}</div>
            </div>
            <span className="flex items-center gap-1.5"><Mark size={30} /><span className="text-[17px] font-bold tracking-[-0.03em] text-[#15384b]">Medi<span className="text-[#0da99e]">Bot</span></span></span>
          </header>

          <div className="px-6 py-4">
            <div className="hidden grid-cols-[1fr_1fr_auto] gap-4 pb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#7d8f96] sm:grid">
              <span>{t('Asked for')}</span><span>{t('Identical option')}</span><span className="text-right">{t('Qty')}</span>
            </div>
            <ol className="divide-y divide-[#e3eaea]">
              {lines.map((l, i) => (
                <li key={i} className="grid grid-cols-1 gap-x-4 gap-y-1 py-3 sm:grid-cols-[1fr_1fr_auto] sm:items-start">
                  <div className="flex gap-2.5">
                    <span className="num mt-0.5 grid size-5 shrink-0 place-items-center rounded-full bg-[#e7f8f5] text-[11px] font-semibold text-[#0a7c74]">{i + 1}</span>
                    <div className="min-w-0">
                      <div className="text-[15px] font-semibold leading-snug">{l.asked}{l.rx && <span className="ml-1.5 rounded border border-[#b42318] px-1 text-[10.5px] font-bold text-[#b42318]">Rx</span>}</div>
                      {l.asked_composition && <div className="text-[12.5px] text-[#4a5b63]">{l.asked_composition}</div>}
                    </div>
                  </div>
                  <div className={cx('pl-7 text-[14px] sm:pl-0', l.same ? 'text-[#7d8f96]' : '')}>
                    {l.same ? <span>—</span> : <>
                      <div className="font-medium">{l.chosen}</div>
                      <div className="inline-flex items-center gap-1 text-[11.5px] font-medium text-[#0a7c74]"><Check className="size-3" strokeWidth={3} />{t('Same composition')}</div>
                    </>}
                    {l.where && <div className="text-[11.5px] text-[#7d8f96]">{l.where}{l.price != null ? ` · ${inr(l.price)}` : ''}</div>}
                  </div>
                  <div className="num pl-7 text-[14px] font-medium sm:pl-0 sm:text-right">{l.qty}</div>
                </li>
              ))}
            </ol>
          </div>

          <footer className="flex items-end justify-between gap-4 border-t border-[#e3eaea] bg-[#f7f9f8] px-6 py-4">
            <div className="max-w-[360px] space-y-1.5 text-[12px] leading-relaxed text-[#4a5b63]">
              <p>{t('Please confirm each identical option before dispensing. Rx = prescription needed.')}</p>
              <p className="text-[#7d8f96]">{t('Made with MediBot · informational, not a prescription')}</p>
            </div>
            {qr && <figure className="shrink-0 text-center"><img src={qr} alt="" className="size-[104px] rounded-md border border-[#e3eaea] bg-white p-1" />
              <figcaption className="mt-1 text-[10px] text-[#7d8f96]">{t('Scan to get this list as text')}</figcaption></figure>}
          </footer>
        </article>
      </div>
    </div>
  )
}
