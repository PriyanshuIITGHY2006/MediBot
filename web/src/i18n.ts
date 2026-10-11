// Interface language (Phase 15.4): English or Hindi. The English string is the key; a missing Hindi entry falls
// back to English, so nothing ever renders blank. Safety texts are NOT here - they come from the API, where the
// Hindi versions are hand-written (backend/medibot/safety/messages_hi.py).
import { useSyncExternalStore } from 'react'

export type Lang = 'en' | 'hi'
const KEY = 'mb-lang'
let lang: Lang = (() => { try { return localStorage.getItem(KEY) === 'hi' ? 'hi' : 'en' } catch { return 'en' } })()
const subs = new Set<() => void>()

export function setLang(l: Lang) {
  lang = l
  try { localStorage.setItem(KEY, l) } catch { /* private mode */ }
  document.documentElement.lang = l === 'hi' ? 'hi' : 'en'
  subs.forEach(f => f())
}
export const getLang = () => lang
export function useLang(): Lang {
  return useSyncExternalStore(f => { subs.add(f); return () => subs.delete(f) }, () => lang)
}

/** t('Jan Aushadhi Kendras near {pin}', { pin }) */
export function t(en: string, vars?: Record<string, string | number>): string {
  let s = (lang === 'hi' && HI[en]) || en
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v))
  return s
}

const HI: Record<string, string> = {
  // ---------------------------------------------------------------- fixed API texts (same wording as safety/messages_hi.py)
  'Active composition is identical (same ingredients, strengths and form). Please confirm the switch with your doctor or pharmacist before changing medicines.':
    'कंपोज़िशन बिल्कुल एक जैसी है (वही तत्व, वही मात्रा और वही रूप)। दवा बदलने से पहले कृपया अपने डॉक्टर या फ़ार्मासिस्ट से पुष्टि करें।',
  'MediBot is an informational tool. It does not diagnose medical conditions or prescribe medications. Users must always consult a qualified medical professional before taking any medication.':
    'MediBot केवल जानकारी देने वाला टूल है। यह बीमारी की पहचान (डायग्नोसिस) नहीं करता और दवा नहीं लिखता। कोई भी दवा लेने से पहले हमेशा किसी योग्य डॉक्टर से सलाह लें।',
  'Not medical advice — please consult a doctor or pharmacist before taking any medicine.': 'यह चिकित्सा सलाह नहीं है — कोई भी दवा लेने से पहले डॉक्टर या फ़ार्मासिस्ट से पूछें।',
  'This medication requires a valid prescription. Please consult your doctor.': 'इस दवा के लिए डॉक्टर का वैध पर्चा (प्रिस्क्रिप्शन) ज़रूरी है। कृपया अपने डॉक्टर से सलाह लें।',
  // ---------------------------------------------------------------- onboarding + chat
  'Pay less for the exact same medicine.': 'वही दवा, कम दाम में।',
  'Live prices from five Indian pharmacies, identical-composition alternatives including Jan Aushadhi, and medicine information you can check against its sources.':
    'पाँच भारतीय फ़ार्मेसियों के लाइव दाम, जन औषधि समेत बिल्कुल एक जैसी कंपोज़िशन वाले विकल्प, और दवा की ऐसी जानकारी जिसे आप उसके स्रोत से जाँच सकें।',
  'MediBot can': 'MediBot कर सकता है',
  "MediBot won't": 'MediBot नहीं करेगा',
  'Compare prices per tablet': 'प्रति टैबलेट दाम की तुलना',
  'Find identical cheaper options': 'वैसे ही सस्ते विकल्प ढूँढना',
  'Explain uses, side effects and interactions, with sources': 'उपयोग, साइड इफ़ेक्ट और इंटरैक्शन समझाना, स्रोत के साथ',
  'Find Jan Aushadhi Kendras': 'जन औषधि केंद्र ढूँढना',
  'Diagnose a condition': 'बीमारी की पहचान करना',
  'Recommend a medicine or a dose': 'दवा या खुराक बताना',
  'Help buy prescription medicines without a prescription': 'बिना पर्चे के प्रिस्क्रिप्शन दवा दिलाना',
  'Emergency: call': 'इमरजेंसी: कॉल करें',
  'or': 'या',
  'Conversations are anonymous and no message text is stored.': 'बातचीत गुमनाम रहती है और कोई संदेश सेव नहीं होता।',
  'Starting…': 'शुरू हो रहा है…',
  'I understand — start': 'मैं समझ गया — शुरू करें',
  'Which medicine can I help you with?': 'किस दवा के बारे में मदद करूँ?',
  'Type a brand, a generic name or a question — in English, Hindi or Hinglish. Typos are fine.':
    'ब्रांड, जेनेरिक नाम या सवाल लिखें — अंग्रेज़ी, हिंदी या हिंग्लिश में। स्पेलिंग की गलती चलेगी।',
  'Find a cheaper identical medicine': 'वैसी ही सस्ती दवा ढूँढें',
  'Compare prices across 5 pharmacies': '5 फ़ार्मेसियों में दाम मिलाएँ',
  'Is it safe in pregnancy?': 'क्या प्रेगनेंसी में सुरक्षित है?',
  'Check two medicines together': 'दो दवाएँ साथ में जाँचें',
  'Ask in Hinglish': 'हिंग्लिश में पूछें',
  'Nearest Jan Aushadhi Kendra': 'नज़दीकी जन औषधि केंद्र',
  'Reading your message, checking prices and sources…': 'आपका संदेश पढ़ रहा हूँ, दाम और स्रोत जाँच रहा हूँ…',
  'Retry': 'फिर से कोशिश करें',
  'Helpful?': 'मददगार?',
  'Thanks for rating ({r}/5)': 'रेटिंग के लिए धन्यवाद ({r}/5)',
  'Informational · not medical advice': 'केवल जानकारी · चिकित्सा सलाह नहीं',
  'Search': 'खोजें',
  'Chat': 'चैट', 'New chat': 'नई चैट', 'Wiki': 'विकी', 'Search medicines': 'दवा खोजें', 'Forget this session': 'यह सेशन भूल जाएँ',
  'Bill split': 'बिल बचत',
  'Cabinet': 'मेरी दवाएँ',
  'Ask about {name}, or another medicine…': '{name} या किसी और दवा के बारे में पूछें…',
  'e.g. Augmentin 625 ka sasta option?': 'जैसे: Augmentin 625 का सस्ता विकल्प?',
  'Not medical advice. Confirm any medicine change with your doctor or pharmacist. Emergency:':
    'यह चिकित्सा सलाह नहीं है। दवा बदलने से पहले डॉक्टर या फ़ार्मासिस्ट से पुष्टि करें। इमरजेंसी:',
  'Search any medicine — brand or generic': 'कोई भी दवा खोजें — ब्रांड या जेनेरिक',
  'No match yet — keep typing, or ask in the chat.': 'अभी कुछ नहीं मिला — लिखते रहें, या चैट में पूछें।',
  'composition not verified': 'कंपोज़िशन सत्यापित नहीं',
  'Composition not verified': 'कंपोज़िशन सत्यापित नहीं',
  // ---------------------------------------------------------------- cards
  'Call 112': '112 पर कॉल करें', 'Ambulance 108': 'एम्बुलेंस 108', 'Emergency 112': 'इमरजेंसी 112',
  'Generic medicine name': 'जेनेरिक दवा का नाम',
  'Contains': 'इसमें है',
  'Sources': 'स्रोत',
  'No recent price on record for this pack.': 'इस पैक का कोई हाल का दाम नहीं मिला।',
  'lowest': 'सबसे कम',
  'pack': 'पैक',
  'out of stock': 'स्टॉक में नहीं',
  'open': 'खोलें',
  'Current price': 'मौजूदा दाम',
  'compared per {u}': 'प्रति {u} तुलना',
  'Note:': 'नोट:',
  'Interaction check': 'इंटरैक्शन जाँच',
  'Same ingredient': 'एक ही घटक',
  'Major': 'गंभीर', 'Moderate': 'मध्यम', 'Minor': 'हल्का', 'Unknown': 'अज्ञात',
  'Please ask your doctor or pharmacist before taking these together.': 'इन्हें साथ लेने से पहले कृपया डॉक्टर या फ़ार्मासिस्ट से पूछें।',
  'Jan Aushadhi Kendras near {pin}': '{pin} के पास जन औषधि केंद्र',
  'Directions': 'रास्ता देखें',
  'Did you mean': 'क्या आपका मतलब था',
  'Prices': 'दाम',
  'tablet': 'टैबलेट',
  'checked recently': 'हाल ही में जाँचा',
  'live now': 'अभी लाइव',
  // ---------------------------------------------------------------- sheet
  'Overview': 'जानकारी', 'Substitutes': 'विकल्प', 'Interactions': 'इंटरैक्शन',
  'Live medicine sheet': 'दवा की जानकारी',
  'Habit forming': 'आदत डालने वाली',
  'Ask about a medicine. Its composition, prices across five pharmacies and identical cheaper options appear here.':
    'किसी दवा के बारे में पूछें। उसकी कंपोज़िशन, पाँच फ़ार्मेसियों के दाम और वैसे ही सस्ते विकल्प यहाँ दिखेंगे।',
  'Loading live prices…': 'लाइव दाम लोड हो रहे हैं…',
  'No verified information for this product.': 'इस दवा की कोई सत्यापित जानकारी नहीं है।',
  'Banned products get no alternatives.': 'प्रतिबंधित दवाओं के विकल्प नहीं दिखाए जाते।',
  'No identical alternative with a known price.': 'ज्ञात दाम वाला कोई समान विकल्प नहीं मिला।',
  "Prices are read from each pharmacy's product page (live, or checked within 6 h) or a dated record. Compare per unit; delivery fees are not included.":
    'दाम हर फ़ार्मेसी के प्रोडक्ट पेज से लिए जाते हैं (लाइव, या पिछले 6 घंटे में जाँचे गए) या तारीख़ वाले रिकॉर्ड से। प्रति यूनिट तुलना करें; डिलीवरी फ़ीस शामिल नहीं है।',
  'Check with another medicine': 'किसी और दवा के साथ जाँचें',
  'Check': 'जाँचें',
  'e.g. Crocin, alcohol, warfarin': 'जैसे Crocin, शराब, warfarin',
  'Checked against 208,000+ graded drug pairs (DDInter) and US drug labels. Always confirm with your pharmacist.':
    '2,08,000+ दवा-जोड़ों (DDInter) और अमेरिकी दवा लेबल से जाँचा गया। हमेशा अपने फ़ार्मासिस्ट से पुष्टि करें।',
  // ---------------------------------------------------------------- bill split
  'Your medicine list': 'आपकी दवाओं की सूची',
  "Add what you need and how many. We'll find the cheapest way to buy all of it.": 'जो चाहिए और कितना, जोड़ें। हम सब ख़रीदने का सबसे सस्ता तरीक़ा ढूँढेंगे।',
  'Add a medicine — brand or generic': 'दवा जोड़ें — ब्रांड या जेनेरिक',
  'Scan a bill or prescription': 'बिल या पर्चा स्कैन करें',
  'Paste a list': 'सूची पेस्ट करें',
  'Cancel': 'रद्द करें',
  'Add to list': 'सूची में जोड़ें',
  'One medicine per line, e.g.': 'हर लाइन में एक दवा, जैसे',
  'Quantity = tablets / capsules / ml you need': 'मात्रा = जितनी टैबलेट / कैप्सूल / ml चाहिए',
  'will be matched when you run': 'चलाने पर मिलाया जाएगा',
  'Try a sample list': 'नमूना सूची आज़माएँ',
  'Allow identical alternatives': 'समान विकल्प चलेंगे',
  'Same ingredients, strength and form — a different brand': 'वही तत्व, वही मात्रा और वही रूप — अलग ब्रांड',
  'Most pharmacies to order from': 'ज़्यादा से ज़्यादा कितनी फ़ार्मेसी से मँगाएँ',
  'Any': 'कोई भी',
  'Checking prices…': 'दाम जाँच रहे हैं…',
  'Find the cheapest way': 'सबसे सस्ता तरीक़ा ढूँढें',
  'Checking live prices at five pharmacies and every identical alternative…': 'पाँच फ़ार्मेसियों और हर समान विकल्प के लाइव दाम जाँच रहे हैं…',
  'Your plan appears here: which pharmacy to order each medicine from, packs to buy, and what you save.':
    'आपका प्लान यहाँ दिखेगा: कौन सी दवा किस फ़ार्मेसी से मँगाएँ, कितने पैक लें, और कितनी बचत होगी।',
  'Cheapest split': 'सबसे सस्ता बँटवारा', 'Same brands': 'वही ब्रांड', 'One pharmacy': 'एक फ़ार्मेसी', 'Jan Aushadhi': 'जन औषधि',
  'not possible': 'संभव नहीं', 'none has every item': 'किसी के पास सब नहीं', 'walk-in, whole list': 'दुकान पर, पूरी सूची',
  'walk-in, part of list': 'दुकान पर, सूची का हिस्सा', 'not available': 'उपलब्ध नहीं',
  'Order this way and pay {total} — {save} less than buying the same brands at their cheapest.':
    'ऐसे मँगाएँ और {total} दें — वही ब्रांड सबसे सस्ते में लेने से {save} कम।',
  'The cheapest way to buy this list is {total} from {where}.': 'यह सूची ख़रीदने का सबसे सस्ता तरीक़ा {where} से {total} है।',
  "We couldn't price this list from any pharmacy yet.": 'अभी किसी फ़ार्मेसी से इस सूची का दाम नहीं मिल पाया।',
  '{n} item(s) use an identical alternative (same ingredients, strengths and form). Confirm any switch with your doctor or pharmacist.':
    '{n} दवा(ओं) के लिए समान विकल्प लिया गया है (वही तत्व, मात्रा और रूप)। बदलने से पहले डॉक्टर या फ़ार्मासिस्ट से पुष्टि करें।',
  'Prescription needed': 'पर्चा ज़रूरी है',
  'banned in India; not included': 'भारत में प्रतिबंधित; शामिल नहीं',
  'no current price from a delivering pharmacy': 'किसी डिलीवरी फ़ार्मेसी पर अभी दाम नहीं',
  'not recognised; try picking it from search': 'पहचान नहीं हुई; खोज से चुनें',
  '{n} item(s) in this order': 'इस ऑर्डर में {n} दवा(एँ)',
  'identical alternative': 'समान विकल्प',
  'instead of {x}': '{x} की जगह',
  '+{n} extra (whole packs)': '+{n} ज़्यादा (पूरे पैक)',
  'Medicines': 'दवाएँ', 'Delivery': 'डिलीवरी', 'free': 'मुफ़्त', 'not known': 'पता नहीं',
  'Not in this plan:': 'इस प्लान में नहीं:',
  'Everything from one pharmacy': 'सब कुछ एक फ़ार्मेसी से',
  'Jan Aushadhi Kendra': 'जन औषधि केंद्र',
  'Walk-in at a Jan Aushadhi Kendra, at MRP. No delivery.': 'जन औषधि केंद्र पर जाकर, MRP पर। डिलीवरी नहीं।',
  'Some items on your list have no Jan Aushadhi equivalent.': 'सूची की कुछ दवाओं का जन औषधि विकल्प नहीं है।',
  "Delivery fees and minimum orders for {list} aren't known to us, so totals exclude them. Check at checkout.":
    '{list} की डिलीवरी फ़ीस और न्यूनतम ऑर्डर हमें पता नहीं, इसलिए कुल में शामिल नहीं। चेकआउट पर देख लें।',
  'Prices are per pack, rounded up to whole packs.': 'दाम प्रति पैक हैं, पूरे पैक तक बढ़ाकर।',
  'Show to pharmacist': 'फ़ार्मासिस्ट को दिखाएँ',
  // ---------------------------------------------------------------- scan
  'Take a photo or choose one': 'फ़ोटो लें या चुनें',
  'Pharmacy bill or prescription · JPG / PNG, up to 8 MB': 'फ़ार्मेसी बिल या पर्चा · JPG / PNG, 8 MB तक',
  'Reading with AI…': 'AI से पढ़ रहे हैं…', 'Reading on this server…': 'सर्वर पर पढ़ रहे हैं…',
  'Read by {who} · {n} found': '{who} ने पढ़ा · {n} मिलीं', 'AI reader': 'AI रीडर', 'on-device OCR': 'सर्वर OCR',
  'Use another photo': 'दूसरी फ़ोटो लें',
  'Read handwriting with AI': 'हाथ की लिखावट AI से पढ़ें',
  'The photo is sent to an AI service to be read. Not stored by MediBot.': 'फ़ोटो पढ़ने के लिए AI सेवा को भेजी जाती है। MediBot इसे सेव नहीं करता।',
  'Off: the photo is read on our server only and never stored.': 'बंद: फ़ोटो सिर्फ़ हमारे सर्वर पर पढ़ी जाती है और कभी सेव नहीं होती।',
  'Check what we read': 'जाँचें हमने क्या पढ़ा',
  'not sure which medicine — fix the name': 'कौन सी दवा है, पक्का नहीं — नाम ठीक करें',
  'qty not on page': 'मात्रा पेज पर नहीं',
  'Some names unclear? Try the AI reader': 'कुछ नाम साफ़ नहीं? AI रीडर आज़माएँ',
  'Photo not stored': 'फ़ोटो सेव नहीं होती',
  'Add {n} to list': '{n} सूची में जोड़ें',
  // ---------------------------------------------------------------- pharmacist card
  '{n} medicines': '{n} दवाएँ', '{n} switched': '{n} बदली गईं',
  'For your pharmacist': 'आपके फ़ार्मासिस्ट के लिए',
  'Medicine list': 'दवाओं की सूची',
  'Asked for': 'माँगी गई', 'Identical option': 'समान विकल्प', 'Qty': 'मात्रा', 'Price': 'दाम',
  'Same composition': 'वही कंपोज़िशन',
  'Please confirm each identical option before dispensing. Rx = prescription needed.':
    'देने से पहले हर समान विकल्प की पुष्टि करें। Rx = पर्चा ज़रूरी।',
  'Scan to get this list as text': 'यह सूची टेक्स्ट में पाने के लिए स्कैन करें',
  'Share on WhatsApp': 'WhatsApp पर भेजें', 'Print': 'प्रिंट करें', 'Close': 'बंद करें', 'Copy text': 'टेक्स्ट कॉपी करें', 'Copied': 'कॉपी हो गया',
  'Made with MediBot · informational, not a prescription': 'MediBot से बना · केवल जानकारी, यह पर्चा नहीं है',
  // ---------------------------------------------------------------- cabinet
  'My medicine cabinet': 'मेरी दवाओं की अलमारी',
  'Medicines you take regularly. Saved only on this device.': 'जो दवाएँ आप नियमित लेते हैं। सिर्फ़ इसी डिवाइस पर सेव।',
  'per day': 'प्रति दिन', 'in hand': 'पास में', 'Runs out': 'ख़त्म होगी', 'today': 'आज', 'in {n} days': '{n} दिन में',
  'Monthly cost': 'महीने का ख़र्च', 'cheapest identical': 'सबसे सस्ता समान', 'you could save': 'बचत हो सकती है',
  'Refill reminders': 'रिफ़िल रिमाइंडर', 'Add to calendar': 'कैलेंडर में जोड़ें',
  'Price dropped': 'दाम घटा', 'Price went up': 'दाम बढ़ा',
  'Check prices': 'दाम जाँचें', 'Checking…': 'जाँच रहे हैं…',
  'No interactions found between these medicines in our sources.': 'हमारे स्रोतों में इन दवाओं के बीच कोई इंटरैक्शन नहीं मिला।',
  'Your cabinet is empty': 'आपकी अलमारी ख़ाली है',
  'Add the medicines you take every day to track cost, refills and interactions.': 'रोज़ की दवाएँ जोड़ें — ख़र्च, रिफ़िल और इंटरैक्शन पर नज़र रखें।',
  'Plan a monthly bill': 'महीने का बिल प्लान करें',
  'Remove': 'हटाएँ',
  'last checked {d}': 'आख़िरी जाँच {d}',
  'Doses per day and stock are what you enter — MediBot never suggests a dose.': 'रोज़ की खुराक और स्टॉक आप भरते हैं — MediBot कभी खुराक नहीं बताता।',
}
