// Typed client for the MediBot API (backend/medibot/api/app.py). Every call returns data or throws ApiError.
export const API = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response
  try {
    r = await fetch(API + path, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) } })
  } catch {
    throw new ApiError(0, "Can't reach MediBot right now. Check your connection and try again.")
  }
  if (r.status === 429) throw new ApiError(429, 'Too many messages in a minute. Please wait a moment and try again.')
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(r.status, body?.response_text ?? body?.detail?.[0]?.msg ?? 'Something went wrong. Please try again.')
  return body as T
}

// ---------------------------------------------------------------- contracts
export type Quote = {
  platform: string; price_inr: number; mrp_inr?: number | null; price_per_unit_inr?: number | null
  pack_label?: string | null; pack_unit?: string | null; url?: string | null; observed?: string | null
  source?: 'live' | 'cached' | 'snapshot' | string; in_stock?: boolean | null; freshness?: string
  above_nppa_ceiling?: { ceiling_per_unit_inr: number; source: string } | null
}
export type SubstituteRow = {
  product_id: string; brand_name: string; manufacturer?: string | null; active_composition?: string
  composition_identically_verified: boolean; price_per_unit_inr?: number | null; pack_unit?: string | null
  savings_percentage?: number | null; user_advisory: string; partner_price_comparison: Quote[]; tier: 'brand' | 'jan_aushadhi' | string
}
export type Citation = { n: number; title: string; url: string; note?: string | null }

export type Card =
  | { type: 'intercept_banner'; lines: string[]; intercept: boolean; banned: boolean; text: string }
  | { type: 'emergency'; text: string; self_harm: boolean }
  | { type: 'refusal'; text: string }
  | { type: 'stores'; pincode: string | null; stores: { store_code: string; address: string; pincode: string; district: string; state: string }[]; asked_for_pincode: boolean; text: string }
  | { type: 'medicine'; name: string; product_id: string | null; composition: string | null; category: string | null; generic: boolean; info_from: string | null; brand: string | null; text: string }
  | { type: 'info'; text: string; sections: string[]; missing: string[]; grounded: boolean; kind: string }
  | { type: 'interactions'; text: string; kind: string; findings: { kind: string; severity: string; text: string; medicine_a?: string; medicine_b?: string }[] }
  | { type: 'substitutes'; text: string; target_product_id: string | null; rows: SubstituteRow[]; note: string | null }
  | { type: 'prices'; product_id: string; quotes: Quote[]; text: string }
  | { type: 'compare'; names: [string, string]; same_ingredients: boolean; same_strengths: boolean; extra: [string, string[]][]; text: string }
  | { type: 'sources'; text: string; citations: Citation[] }
  | { type: 'clarify'; options: string[]; text: string }
  | { type: 'fallback'; text: string }
  | { type: 'lead'; text: string; source: string }
  | { type: 'disclaimer'; text: string; full: boolean; requires_acknowledgement: boolean }
  | { type: 'quick_replies'; options: string[]; text: string }

export type QueryResponse = {
  session_id: string; turn_id: string; response_text: string; intent: string; cards: Card[]; latency_ms: number
  safety_guard: { is_restricted_schedule_h: boolean; intercept_triggered: boolean; mandated_prompt: string | null; is_banned: boolean; is_diagnosis_detected: boolean; is_emergency: boolean }
  detected_medication: null | { brand_name: string; active_composition: string | null; therapeutic_class: string | null; schedule: string | null; mrp_inr: number | null; product_id: string | null }
  disclaimer: string
}

export type Sheet = {
  product_id: string; name: string; manufacturer: string | null; form: string; composition: string | null
  schedule: string; category: string; requires_prescription: boolean; banned: boolean; mandated_prompt: string | null
  safety_reason: string; therapeutic_class: string | null; habit_forming: boolean | null
  image_url: string | null; image_credit: string | null
  info: null | { text: string; sections: string[]; missing: string[]; citations: Citation[] }
  prices: Quote[]
  substitutes: null | { current_price_per_unit_inr: number | null; pack_unit: string | null; note: string | null; rows: SubstituteRow[] }
  disclaimer: string
}
export type SearchHit = { product_id: string; name: string; composition: string | null; form: string; schedule: string; requires_prescription: boolean; confident: boolean }

// ---------------------------------------------------------------- endpoints
export const api = {
  start: () => call<{ session_id: string; disclaimer: string; requires_acknowledgement: boolean }>('/api/v1/session/start', { method: 'POST' }),
  ack: (session_id: string) => call<{ disclaimer_acknowledged: boolean }>('/api/v1/session/ack', { method: 'POST', body: JSON.stringify({ session_id }) }),
  query: (session_id: string, user_query: string, language: 'en' | 'hi' = 'en') =>
    call<QueryResponse>('/api/v1/medibot/query', { method: 'POST', body: JSON.stringify({ session_id, user_query, disclaimer_acknowledged: true, language }) }),
  feedback: (session_id: string, turn_id: string, rating: number) =>
    call<{ stored: boolean }>('/api/v1/feedback', { method: 'POST', body: JSON.stringify({ session_id, turn_id, rating }) }),
  search: (q: string) => call<{ results: SearchHit[] }>(`/api/v1/search?q=${encodeURIComponent(q)}&limit=8`),
  medicine: (id: string) => call<Sheet>(`/api/v1/medicine/${encodeURIComponent(id)}`),
  forget: (session_id: string) => call<{ forgotten: boolean }>(`/api/v1/session/${session_id}`, { method: 'DELETE' }),
}

// ---------------------------------------------------------------- bill split (Phase 15.1)
export type BillLine = { name: string; quantity: number; product_id?: string | null }
export type CartLine = {
  item_key: string; label: string; product_id: string; name: string; is_asked_product: boolean; packs: number
  pack_price_inr: number; pack_label: string | null; pack_quantity: number; cost_inr: number; overbuy_units: number
  url: string | null; source: string; observed: string | null
}
export type BillCart = {
  platform: string; subtotal_inr: number; delivery_fee_inr: number; total_inr: number; delivery_fee_known: boolean
  min_order_inr: number | null; free_delivery_above_inr: number | null; lines: CartLine[]
}
export type BillPlan = { total_inr: number; pharmacies: string[]; swaps: number; unplaced: string[]; carts: BillCart[] }
export type BillItemRow = {
  key: string; input: string; quantity: number; status: 'ok' | 'no_price' | 'banned' | 'not_recognised'
  product_id?: string; name?: string; composition?: string | null; form?: string; requires_prescription?: boolean
  confident?: boolean; mandated_prompt?: string | null; note?: string; pharmacies?: string[]; has_alternatives?: boolean
}
export type BillResult = {
  items: BillItemRow[]; best: BillPlan | null; as_asked: BillPlan | null; one_stop: BillPlan | null
  single_pharmacy: { platform: string; total_inr: number }[]
  jan_aushadhi: null | { total_inr: number; complete: boolean; note: string; lines: { item_key: string; label: string; name: string; packs: number; pack_label: string | null; pack_price_inr: number; cost_inr: number }[] }
  savings_inr: number | null; unknown_delivery_terms: string[]; advisory: string; disclaimer: string
}
export const billApi = {
  parse: (text: string) => call<{ lines: (BillLine & { quantity_given: boolean })[] }>('/api/v1/bill/parse', { method: 'POST', body: JSON.stringify({ text }) }),
  plan: (items: BillLine[], allow_alternatives: boolean, max_pharmacies: number | null) =>
    call<BillResult>('/api/v1/bill/plan', { method: 'POST', body: JSON.stringify({ items, allow_alternatives, max_pharmacies }) }),
}
export type ReadLine = { name: string; written: string; quantity: number; quantity_given: boolean; product_id: string | null; composition: string | null; requires_prescription: boolean | null; confident: boolean }
export const readBill = (file: Blob, vision: boolean) =>
  call<{ lines: ReadLine[]; engine: 'tesseract' | 'vision'; note: string | null; stored: false }>(
    `/api/v1/bill/read${vision ? '?vision=1' : ''}`, { method: 'POST', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream' } })

// ---------------------------------------------------------------- my cabinet (Phase 15.3)
export type CabinetRow = {
  product_id: string; status: 'ok' | 'no_price' | 'banned' | 'not_found'; name?: string; composition?: string | null
  per_day?: number; units_per_month?: number; requires_prescription?: boolean; mandated_prompt?: string | null; note?: string
  pack_unit?: string | null; price_per_unit_inr?: number | null; cheapest_platform?: string | null; observed?: string | null
  monthly_inr?: number | null
  best_alternative?: null | { product_id: string; brand_name: string; manufacturer?: string | null; tier: string; price_per_unit_inr: number; monthly_inr: number; savings_percentage?: number | null }
}
export type CabinetResult = {
  items: CabinetRow[]; monthly_inr: number; monthly_best_inr: number; monthly_savings_inr: number; complete: boolean
  interactions: { kind: string; medicine_a: string; medicine_b: string; severity: string; text: string; citations: { title: string; url: string }[] }[]
  interaction_advice: string; advisory: string; disclaimer: string
}
export const cabinetCheck = (items: { product_id: string; per_day: number }[]) =>
  call<CabinetResult>('/api/v1/cabinet/check', { method: 'POST', body: JSON.stringify({ items }) })
