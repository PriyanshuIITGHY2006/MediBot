"""Fixed safety texts. These are never generated or rewritten by an LLM."""
from __future__ import annotations

MANDATED_PROMPT = "This medication requires a valid prescription. Please consult your doctor."

DISCLAIMER = ("MediBot is an informational tool. It does not diagnose medical conditions or prescribe medications. "
              "Users must always consult a qualified medical professional before taking any medication.")
SHORT_DISCLAIMER = "Not medical advice — please consult a doctor or pharmacist before taking any medicine."

EMERGENCY = (
    "This could be a medical emergency. Please get help right now:\n"
    "• Call 112 (national emergency) or 108 (ambulance)\n"
    "• Go to the nearest hospital emergency department\n"
    "• Poisoning or overdose: call 112 / 108 immediately and keep the medicine pack with you\n"
    "MediBot cannot help with emergencies."
)
SELF_HARM = (
    "I'm really sorry you're feeling this way. You don't have to go through it alone.\n"
    "• Tele-MANAS (free, 24×7): 14416 or 1-800-891-4416\n"
    "• Emergency: 112\n"
    "If you are in immediate danger, please call 112 now or go to the nearest hospital."
)
DIAGNOSIS_REFUSAL = (
    "I can't diagnose conditions — symptoms like these can have many different causes, and only a doctor who "
    "examines you can tell what is going on. Please consult a doctor, especially if the symptoms are severe, "
    "getting worse or lasting more than a few days. If you have danger signs (trouble breathing, chest pain, "
    "confusion, fainting, very high fever), call 112 or go to the nearest hospital."
)
PRESCRIBING_REFUSAL = (
    "I can't recommend a medicine or a dose for you — that depends on your health, other medicines and the exact "
    "problem, so it needs a doctor or pharmacist. I can give general information about a specific "
    "medicine, compare prices, or find identical cheaper alternatives for a medicine your doctor has prescribed."
)
DOSING_REFUSAL = (
    "I can't advise on doses. Please follow your doctor's prescription or the instructions on the pack, "
    "and ask your pharmacist if you're unsure — doses depend on age, weight and other conditions."
)
RX_SEEKING_REFUSAL = ("Prescription medicines can only be bought with a valid prescription from a registered doctor. "
                      "I can't help you get them without one.")
MISUSE_REFUSAL = ("I can't help with using medicines to get high or in ways they aren't prescribed — it can be very "
                  "dangerous. If you're struggling with substance use, Tele-MANAS (14416) offers free, confidential help.")


def banned_notice(ref: str) -> str:
    return (f"This medicine/combination is prohibited for sale in India ({ref}). It should not be used. "
            "Please consult your doctor for a safe alternative.")

FALLBACK_ERROR = ("Sorry, something went wrong on our side and I couldn't answer that safely. Please try again. "
                  "If your question is about a prescription medicine, please consult your doctor or pharmacist. "
                  "In an emergency, call 112 or 108.")
