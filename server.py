from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel
from typing import Optional, List
from pathlib import Path
import os
import uuid
import json
import re
import logging
from openai import AsyncOpenAI

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

mongo_url = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
try:
    client = AsyncIOMotorClient(mongo_url)
    db = client[os.environ.get('DB_NAME', 'pocket_protector')]
except Exception as _e:
    logger.warning(f"MongoDB client init deferred: {_e}")
    client = None
    db = None

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

app = FastAPI()
api_router = APIRouter(prefix="/api")


# --- Health & readiness endpoints (additive; required for Kubernetes probes) ---
@app.get("/")
async def root_health():
    return {"status": "ok", "service": "pocket-protector"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@api_router.get("/health")
async def api_health():
    return {"status": "ok"}

SYSTEM_MESSAGE = """You are "Nerd Sleeve" — a calm BEHAVIORAL RELIABILITY reader. You assess how reliably a communication conveys what it appears to convey.

Low behavioral reliability means the communication shows patterns of urgency without context, vague identity, unverifiable claims, or pressure that may obscure clarity. You do NOT determine truth, intent, or consequence.

CRITICAL TONE RULES — non-negotiable:
- NEVER assign intent: do not say "trying to", "designed to deceive", "attempting to manipulate"
- NEVER claim truth or falsehood: do not say "this is a scam", "this is fake", "this is legitimate"
- NEVER state consequences: do not say "you will lose money", "this will harm you"
- USE reliability framing: "appears", "may", "shows signs of", "suggests", "lacks"
- DO describe what IS present in neutral transferable terms

Behavioral reliability signals (observe, do not judge):
- Urgency framing: time pressure without supporting context ("now", "expires", "act fast")
- Vague specifics: generic references without concrete or personal detail
- Action-without-context: request to act (click, pay, respond) without clear reason or verification
- Pressure layering: multiple urgency or emotional signals stacked together
- Tone mismatch: formal request in impersonal phrasing, or informal framing around serious asks
- Missing verification path: no way to confirm sender, organization, or claim
- Sensitivity requests: asks for credentials, personal data, or payment

Scoring (behavioral reliability degradation — pattern density, not threat level):
- 5-30: High behavioral reliability — few or no unusual patterns
- 31-55: Moderate concern — one or two mildly unusual patterns present
- 56-75: Reduced reliability — multiple clear patterns present
- 76-95: Low behavioral reliability — strong concentration of pressure and vague patterns

Red flag phrasing (neutral, pattern-based):
  AVOID → USE
  "Scammer behavior" → "Urgency framing without supporting context"
  "Person is manipulating you" → "Emotional pressure combined with vague details"
  "Trying to steal" → "Request for sensitive information without a verification path"
  "Phishing attempt" → "Generic greeting paired with a time-sensitive action request"

Q.I. line phrasing (calm, neutral, decision-focused):
  AVOID → USE
  "This is a scam" → "This communication leans on pressure more than clarity."
  "They want your money" → "Several elements here feel scripted rather than specific."
  "Don't trust this" → "This asks for action without giving you something concrete."
  "Person is lying" → "Some details here appear constructed rather than direct."

Return ONLY this exact JSON. No markdown. No code blocks. No extra text:
{
  "suspicion_score": <integer between 5 and 95>,
  "red_flags": [<3-5 neutral pattern observations, 5-15 words each, describe what IS present, never intent>],
  "qi_line": "<one calm sentence about decision/action risk, 10-20 words, never assigns intent or truth>"
}"""

IMAGE_SYSTEM_MESSAGE = """You are "Nerd Sleeve" — a dual-lens reliability analyst. You assess TWO independent reliability dimensions and report each separately. You do NOT determine truth, intent, identity, or consequence.

CRITICAL TONE RULES — non-negotiable for BOTH layers:
- NEVER assign intent or identity: do not say "trying to", "this person", "they are"
- NEVER claim absolute truth: do not say "this IS fake", "this IS AI", "this IS real"
- USE reliability framing: "appears", "may", "shows signs of", "suggests", "lacks"
- DO report observable signals in neutral, transferable terms

════════════════════════════════════════
LENS 1 — BEHAVIORAL RELIABILITY (text content)
════════════════════════════════════════
Extract all visible text from the image. Assess behavioral reliability: how clearly and reliably the communication conveys what it appears to convey.

Signals to observe:
- Urgency framing: time pressure without context ("expires", "act now", "immediately")
- Vague specifics: generic references without concrete or personal detail
- Action-without-context: request to act without clear reason or verification path
- Pressure layering: multiple urgency signals stacked together
- Tone mismatch: formal ask in impersonal phrasing, or vice versa
- Missing verification: no way to confirm sender or claim
- Sensitivity requests: credentials, personal data, payment

Behavioral reliability scoring:
- 5-30: High reliability — few or no unusual patterns in text
- 31-55: Moderate concern — some patterns present
- 56-75: Reduced reliability — multiple patterns
- 76-95: Low reliability — strong, stacked patterns

BEHAVIORAL SCORE: Report this as "text_suspicion_score" in your JSON.
This score is for TEXT SIGNALS ONLY. Do not blend image quality into this number.

Q.I. LINE RULE — write based on which lens dominates:
- If text_suspicion_score > 30: focus on decision/action risk
  Example: "This message leans on urgency and lacks clear verification."
  Example: "Several elements appear constructed rather than specific."
- If text_suspicion_score <= 30 AND image reliability is Moderate or Elevated: focus on representation
  Example: "This image appears stylized, which may affect how accurately it represents real-world appearance."
  Example: "Some visual elements suggest stylization rather than direct capture."
- If text_suspicion_score > 30 AND image reliability is Moderate or Elevated: combine both
  Example: "This message and image together show signs of reduced reliability."
  Example: "Both communication patterns and visual characteristics suggest construction over capture."

════════════════════════════════════════
LENS 2 — REPRESENTATION RELIABILITY (visual quality)
════════════════════════════════════════
Assess how accurately the image reflects real-world photographic capture. A low representation reliability score means visual characteristics diverge from natural photography — not that it is definitely AI or fake.

Visual signals to observe:
- Skin / surfaces: smooth beyond typical photographic texture, lacking natural grain or variation
- Eyes / facial detail: fine detail appears uniform or inconsistent with natural capture
- Hands / structure: geometry shows signs of inconsistency with natural photography
- Lighting: appears uniform in ways that may suggest stylization rather than real-world capture
- Edges / blending: boundaries suggest rendering rather than optical capture
- Textures: surfaces appear processed or smoothed rather than photographed
- Background / environment: perspective or depth may show inconsistencies

Representation reliability scoring:
- "Low" concern (score 0-30): Visual characteristics appear consistent with natural photography
- "Moderate" concern (score 31-60): Some characteristics suggest processing or stylization
- "Elevated" concern (score 61-100): Multiple characteristics suggest significant construction or generation

Neutral phrasing for observations:
  AVOID → USE
  "This is AI-generated" → "Several characteristics appear more consistent with generated imagery"
  "This person is fake" → "Facial detail appears smoothed beyond typical photographic capture"
  "This image is manipulated" → "Lighting and texture suggest stylization rather than capture"

Return ONLY this exact JSON. No markdown. No code blocks. No extra text:
{
  "text_suspicion_score": <integer 5-95, TEXT SIGNALS ONLY, do not include image quality>,
  "red_flags": [<3-5 neutral behavioral pattern observations from text content, 5-15 words each>],
  "qi_line": "<one calm sentence, 10-20 words, focused on whichever lens shows more signal>",
  "image_authenticity": {
    "confidence_level": "<Low|Moderate|Elevated>",
    "score": <integer 0-100, VISUAL QUALITY ONLY>,
    "observations": [<2-4 neutral representation observations, present tense, 5-15 words each>]
  }
}"""


def compute_final_score(text_score: int, auth_score: int) -> int:
    """
    Reliability weighting engine.

    Text (behavioral reliability) is the PRIMARY driver.
    Image (representation reliability) is a SECONDARY modifier with strict caps.

    Rules:
    - Image-only signals stay within "Looks Normal" band (0–49) — yellow tones visible, no label change
    - If no significant text signals (text_score <= 30): image adds at most +30, final capped at 49
    - If moderate text signals (31–55): image adds at most +12
    - If strong text signals (>55): image adds at most +8 (minor accent only)
    """
    if auth_score <= 30:
        image_adj = 0
    elif text_score <= 30:
        # Image-only: moderate awareness bump, hard cap keeps it in "Looks Normal" band
        image_adj = min(30, int(auth_score * 0.35))
    elif text_score <= 55:
        # Both present, moderate text: image amplifies within band
        image_adj = min(12, int(auth_score / 8))
    else:
        # Strong text dominant: image is minor accent
        image_adj = min(8, int(auth_score / 12))

    raw = text_score + image_adj

    # Hard cap: representation-only signals cannot change primary label beyond "Looks Normal"
    if text_score <= 30:
        raw = min(49, raw)   # keeps color in green→yellow zone; label stays "Looks Normal"

    return max(5, min(95, raw))


def get_risk_info(score: int) -> tuple:
    """
    3-label system aligned with the continuous gradient.
    - 0–49:  "Looks Normal"         (green → yellow gradient, labels unchanged)
    - 50–74: "Something Feels Off"  (yellow → orange gradient, awareness)
    - 75–95: "High Risk"            (orange → red gradient)
    """
    if score < 50:
        return "Looks Normal", "green"
    elif score < 75:
        return "Something Feels Off", "yellow"
    else:
        return "High Risk", "red"


def get_nerd_whisper(score: int) -> str:
    if score < 31:
        return "All quiet on the line."
    elif score < 50:
        return "Something's stirring."
    elif score < 75:
        return "That flag's climbing."
    else:
        return "Yeah, that didn't raise itself."


def parse_llm_response(text: str) -> Optional[dict]:
    if not text:
        return None
    # Try direct JSON parse
    try:
        return json.loads(text.strip())
    except Exception:
        pass
    # Try to extract JSON block from response
    json_match = re.search(r'\{[^{}]*"suspicion_score"[^{}]*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except Exception:
            pass
    # Broader extraction
    json_match = re.search(r'\{.*\}', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except Exception:
            pass
    return None


class AnalyzeRequest(BaseModel):
    text: Optional[str] = None
    image_base64: Optional[str] = None


class ImageAuthenticity(BaseModel):
    confidence_level: str   # "Low" | "Moderate" | "Elevated"
    score: int              # 0-100 internal signal strength
    observations: List[str] # 2-4 observational notes


class AnalysisResult(BaseModel):
    suspicion_score: int
    realism_score: int
    risk_level: str
    risk_color: str
    red_flags: List[str]
    qi_line: str
    nerd_sleeve_whisper: str
    image_authenticity: Optional[ImageAuthenticity] = None


@api_router.get("/")
async def root():
    return {"message": "Pocket Protector API — nothing you submit is stored."}


@api_router.post("/analyze", response_model=AnalysisResult)
async def analyze_content(request: AnalyzeRequest):
    if not request.text and not request.image_base64:
        raise HTTPException(status_code=400, detail="Either text or image_base64 is required")

    is_image = bool(request.image_base64)
    system_msg = IMAGE_SYSTEM_MESSAGE if is_image else SYSTEM_MESSAGE

    try:
    if is_image:
        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Analyze this image. Assess behavioral reliability and representation reliability."
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{request.image_base64}"
                        }
                    }
                ]
            }
        ]
    else:
        messages = [
            {"role": "system", "content": system_msg},
            {
                "role": "user",
                "content": f"Analyze this content for deception patterns:\n\n{request.text}"
            }
        ]

    response = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.2,
    )

    response_text = response.choices[0].message.content or ""
    parsed = parse_llm_response(response_text)

except Exception as e:
    logger.error(f"LLM analysis error: {e}")
    parsed = None
        parsed = parse_llm_response(response_text)

    except Exception as e:
        logger.error(f"LLM analysis error: {e}")
        parsed = None

    if not parsed or ('suspicion_score' not in parsed and 'text_suspicion_score' not in parsed):
        parsed = {
            "suspicion_score": 35,
            "red_flags": [
                "Analysis returned an unexpected format",
                "Pattern recognition scan incomplete",
                "Consider reviewing this content manually"
            ],
            "qi_line": "Something interrupted a clean read — a second look wouldn't hurt."
        }

    # Extract raw scores
    if is_image:
        # For images: LLM returns text_suspicion_score separately from image authenticity
        text_score = max(5, min(95, int(
            parsed.get('text_suspicion_score') or parsed.get('suspicion_score', 35)
        )))
    else:
        text_score = max(5, min(95, int(parsed.get('suspicion_score', 35))))

    red_flags = parsed.get('red_flags', [])
    red_flags = [str(f) for f in red_flags][:5]
    while len(red_flags) < 3:
        red_flags.append("Pattern scan returned limited signals")

    qi_line = str(parsed.get('qi_line', "Take a breath and a second look before reacting."))

    # Build image_authenticity and compute final weighted score
    image_authenticity = None
    auth_score_raw = 0

    if is_image and parsed.get('image_authenticity'):
        raw_auth = parsed['image_authenticity']
        try:
            auth_level = str(raw_auth.get('confidence_level', 'Low'))
            if auth_level not in ('Low', 'Moderate', 'Elevated'):
                auth_level = 'Low'
            auth_score_raw = max(0, min(100, int(raw_auth.get('score', 10))))
            auth_obs = [str(o) for o in raw_auth.get('observations', [])][:4]
            if not auth_obs:
                auth_obs = ["Visual characteristics appear consistent with natural capture"]
            image_authenticity = ImageAuthenticity(
                confidence_level=auth_level,
                score=auth_score_raw,
                observations=auth_obs
            )
        except Exception as e:
            logger.warning(f"Failed to parse image_authenticity: {e}")

    # Apply reliability weighting: Python controls the math, not the LLM
    if is_image:
        score = compute_final_score(text_score, auth_score_raw)
        logger.info(
            f"Reliability scores — text: {text_score}, image: {auth_score_raw}, "
            f"final: {score}"
        )
    else:
        score = text_score

    risk_level, risk_color = get_risk_info(score)
    nerd_whisper = get_nerd_whisper(score)

    return AnalysisResult(
        suspicion_score=score,
        realism_score=100 - score,
        risk_level=risk_level,
        risk_color=risk_color,
        red_flags=red_flags,
        qi_line=qi_line,
        nerd_sleeve_whisper=nerd_whisper,
        image_authenticity=image_authenticity
    )


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    if client is not None:
        client.close()
