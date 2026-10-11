"""Fixed safety texts in Hindi (Phase 15.4). Written by hand, never generated or rewritten by an LLM - the same
rule as messages.py. Helpline numbers and section references are kept exactly as in the English texts.

The mandated prompt is always ALSO shown in English, verbatim (the problem statement requires that exact sentence);
the Hindi line is shown under it.
"""
from __future__ import annotations

import re

from medibot.safety import messages as en

MANDATED_PROMPT = "इस दवा के लिए डॉक्टर का वैध पर्चा (प्रिस्क्रिप्शन) ज़रूरी है। कृपया अपने डॉक्टर से सलाह लें।"

DISCLAIMER = ("MediBot केवल जानकारी देने वाला टूल है। यह बीमारी की पहचान (डायग्नोसिस) नहीं करता और दवा नहीं लिखता। "
              "कोई भी दवा लेने से पहले हमेशा किसी योग्य डॉक्टर से सलाह लें।")
SHORT_DISCLAIMER = "यह चिकित्सा सलाह नहीं है — कोई भी दवा लेने से पहले डॉक्टर या फ़ार्मासिस्ट से पूछें।"

EMERGENCY = (
    "यह मेडिकल इमरजेंसी हो सकती है। कृपया अभी मदद लें:\n"
    "• 112 (राष्ट्रीय इमरजेंसी) या 108 (एम्बुलेंस) पर कॉल करें\n"
    "• नज़दीकी अस्पताल के इमरजेंसी विभाग में जाएँ\n"
    "• ज़हर या ओवरडोज़: तुरंत 112 / 108 पर कॉल करें और दवा का पैकेट साथ रखें\n"
    "MediBot इमरजेंसी में मदद नहीं कर सकता।"
)
SELF_HARM = (
    "मुझे बहुत दुख है कि आप ऐसा महसूस कर रहे हैं। आपको यह अकेले नहीं झेलना है।\n"
    "• Tele-MANAS (मुफ़्त, 24×7): 14416 या 1-800-891-4416\n"
    "• इमरजेंसी: 112\n"
    "अगर आप तुरंत ख़तरे में हैं, तो कृपया अभी 112 पर कॉल करें या नज़दीकी अस्पताल जाएँ।"
)
DIAGNOSIS_REFUSAL = (
    "मैं बीमारी की पहचान नहीं कर सकता — ऐसे लक्षणों के कई अलग कारण हो सकते हैं, और सिर्फ़ डॉक्टर जाँच करके बता सकते हैं "
    "कि क्या हो रहा है। कृपया डॉक्टर से मिलें, ख़ासकर अगर लक्षण गंभीर हों, बढ़ रहे हों या कुछ दिनों से ज़्यादा रहें। "
    "ख़तरे के संकेत हों (साँस लेने में तकलीफ़, सीने में दर्द, उलझन, बेहोशी, बहुत तेज़ बुख़ार) तो 112 पर कॉल करें या "
    "नज़दीकी अस्पताल जाएँ।"
)
PRESCRIBING_REFUSAL = (
    "मैं आपके लिए कोई दवा या उसकी खुराक नहीं बता सकता — यह आपकी सेहत, दूसरी दवाओं और असली समस्या पर निर्भर करता है, "
    "इसलिए इसके लिए डॉक्टर या फ़ार्मासिस्ट चाहिए। मैं किसी दवा की सामान्य जानकारी दे सकता हूँ, दाम मिला सकता हूँ, "
    "या डॉक्टर की लिखी दवा का वैसा ही (समान कंपोज़िशन वाला) सस्ता विकल्प ढूँढ सकता हूँ।"
)
DOSING_REFUSAL = (
    "मैं खुराक के बारे में सलाह नहीं दे सकता। कृपया डॉक्टर के पर्चे या पैकेट पर लिखे निर्देश मानें, और शक हो तो अपने "
    "फ़ार्मासिस्ट से पूछें — खुराक उम्र, वज़न और दूसरी बीमारियों पर निर्भर करती है।"
)
RX_SEEKING_REFUSAL = ("प्रिस्क्रिप्शन वाली दवाएँ सिर्फ़ रजिस्टर्ड डॉक्टर के वैध पर्चे से ही ख़रीदी जा सकती हैं। "
                      "बिना पर्चे के मैं इन्हें दिलाने में मदद नहीं कर सकता।")
MISUSE_REFUSAL = ("दवाओं का नशे के लिए या बिना पर्चे के तरीक़े से इस्तेमाल करने में मैं मदद नहीं कर सकता — यह बहुत "
                  "ख़तरनाक हो सकता है। अगर आप नशे की समस्या से जूझ रहे हैं, तो Tele-MANAS (14416) पर मुफ़्त और "
                  "गोपनीय मदद मिलती है।")
FALLBACK_ERROR = ("माफ़ कीजिए, हमारी तरफ़ कुछ गड़बड़ हुई और मैं सुरक्षित जवाब नहीं दे पाया। कृपया फिर से कोशिश करें। "
                  "अगर सवाल प्रिस्क्रिप्शन वाली दवा के बारे में है, तो डॉक्टर या फ़ार्मासिस्ट से पूछें। "
                  "इमरजेंसी में 112 या 108 पर कॉल करें।")
ADVISORY = ("कंपोज़िशन बिल्कुल एक जैसी है (वही तत्व, वही मात्रा और वही रूप)। दवा बदलने से पहले कृपया अपने डॉक्टर या "
            "फ़ार्मासिस्ट से पुष्टि करें।")


def banned_notice(ref: str) -> str:
    return (f"यह दवा/कॉम्बिनेशन भारत में बिक्री के लिए प्रतिबंधित है ({ref})। इसका इस्तेमाल नहीं करना चाहिए। "
            "सुरक्षित विकल्प के लिए कृपया अपने डॉक्टर से सलाह लें।")


# English fixed text -> Hindi fixed text. Used whole-text or line by line (multi-line texts are split on \n).
FIXED = {
    en.MANDATED_PROMPT: MANDATED_PROMPT, en.DISCLAIMER: DISCLAIMER, en.SHORT_DISCLAIMER: SHORT_DISCLAIMER,
    en.EMERGENCY: EMERGENCY, en.SELF_HARM: SELF_HARM, en.DIAGNOSIS_REFUSAL: DIAGNOSIS_REFUSAL,
    en.PRESCRIBING_REFUSAL: PRESCRIBING_REFUSAL, en.DOSING_REFUSAL: DOSING_REFUSAL,
    en.RX_SEEKING_REFUSAL: RX_SEEKING_REFUSAL, en.MISUSE_REFUSAL: MISUSE_REFUSAL, en.FALLBACK_ERROR: FALLBACK_ERROR,
}
for _e, _h in list(FIXED.items()):
    if "\n" in _e:
        for _el, _hl in zip(_e.split("\n"), _h.split("\n")):
            FIXED.setdefault(_el, _hl)

_BANNED = re.compile(r"^This medicine/combination is prohibited for sale in India \((.+?)\)\. It should not be used\. "
                     r"Please consult your doctor for a safe alternative\.$")


def fixed(text: str) -> str | None:
    """The hand-written Hindi for a fixed safety text, or None if this is not one."""
    if text in FIXED:
        return FIXED[text]
    m = _BANNED.match(text)
    return banned_notice(m.group(1)) if m else None


def is_safety_text(text: str) -> bool:
    return fixed(text) is not None
