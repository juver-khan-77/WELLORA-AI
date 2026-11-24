"""Wellora streaming chat. Adds POST /api/ai/stream (Server-Sent Events) with full profile context.
Wire it into main.py with two lines, placed BEFORE the app.mount("/", ...) line:
    from stream import router as stream_router
    app.include_router(stream_router)"""
import os, re, json, asyncio
from pathlib import Path
import httpx
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
try:
    from dotenv import load_dotenv; load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

KEY = os.getenv("GEMINI_API_KEY", "")
if KEY == "your_key_here": KEY = ""
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
FALLBACK = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite")  # comma-separated list
router = APIRouter()

EMG = re.compile(r"suicid|self.?harm|kill myself|overdose|can.?t breathe|heart attack|chest pain|आत्महत्या|सांस नहीं|सीने में दर्द", re.I)
MED = re.compile(r"diagnos|prescri|dosage|\bdose\b|tablet|antibiotic|insulin|symptom|pregnan|दवा|दवाई|बीमारी|इलाज|लक्षण|डोज़", re.I)
SAFE = {
    "emg": {"en": "If you may be in danger or having severe symptoms, call 112 (India) now or reach a trusted person. You deserve support.",
            "hi": "अगर आप खतरे में हैं या गंभीर लक्षण हैं, तो अभी 112 पर कॉल करें या किसी भरोसेमंद व्यक्ति से संपर्क करें।"},
    "med": {"en": "I can't diagnose or advise on medicines or symptoms. Please talk to a doctor or pharmacist. I can help with routine habits instead.",
            "hi": "मैं बीमारी, लक्षण या दवा पर सलाह नहीं दे सकता। कृपया डॉक्टर या फ़ार्मासिस्ट से बात करें। मैं रोज़ की आदतों में मदद कर सकता हूँ।"},
    "nokey": {"en": "The AI isn't connected yet. Add GEMINI_API_KEY to backend/.env and restart the server.",
              "hi": "AI अभी जुड़ा नहीं है। backend/.env में GEMINI_API_KEY जोड़ें और सर्वर फिर से चलाएँ।"},
}

class Profile(BaseModel):
    name: str = Field("", max_length=40); bio: str = Field("", max_length=160); sex: str = Field("", max_length=12)
    age: int | None = Field(None, ge=5, le=110); height: float | None = Field(None, ge=50, le=250)
    weight: float | None = Field(None, ge=15, le=300); bmi: float | None = None
    goals: list[str] = []; level: str = Field("", max_length=20); meds: str = Field("", max_length=200)

class Msg(BaseModel):
    role: str; text: str = Field(max_length=800)

class Req(BaseModel):
    message: str = Field(min_length=1, max_length=500); lang: str = "en"; mode: str = "chat"
    profile: Profile = Profile(); history: list[Msg] = []

SYS = ("You are Wellora, a warm, India-first wellness-routine assistant. Reply in the user's language (English, Hindi in Devanagari, or Hinglish). "
       "Be practical and kind, short lines, no markdown headings, max 120 words. Personalise using the profile and use Indian everyday foods (dal, roti, sabzi, curd, fruit). "
       "Never diagnose, prescribe, advise on any medicine or dose, give calorie limits, fasting plans, weight-loss targets or extreme exercise. "
       "If the profile lists medications, never discuss them; at most add one line that a doctor should confirm before changing activity. "
       "For users under 18: no dieting or weight-loss advice; focus on sleep, activity, hydration, balanced meals, posture; be honest that height is mostly genetic. "
       "For BMI in the underweight or obese range, keep exercise gentle and suggest a doctor check-in once.")
WORKOUT = (" MODE: workout. Give one gentle bodyweight session of at most 25 minutes: warm-up, main set (exercise, sets x reps, rest), cool-down. "
           "No equipment, low-impact, match the fitness level, end with 'Stop if anything hurts.' Up to 180 words.")

def sse(o): return f"data: {json.dumps(o, ensure_ascii=False)}\n\n"

async def gen(r: Req):
    lang = r.lang if r.lang in ("en", "hi") else "en"
    if EMG.search(r.message): yield sse({"t": SAFE["emg"][lang]}); yield sse({"done": True}); return
    if r.mode != "workout" and MED.search(r.message): yield sse({"t": SAFE["med"][lang]}); yield sse({"done": True}); return
    if not KEY: yield sse({"t": SAFE["nokey"][lang], "err": "nokey"}); yield sse({"done": True}); return
    p = r.profile
    ctx = (f"Profile: name={p.name or 'friend'}, age={p.age}, sex={p.sex or 'n/a'}, height_cm={p.height}, weight_kg={p.weight}, bmi={p.bmi}, "
           f"goals={', '.join(p.goals[:8]) or 'none'}, fitness_level={p.level or 'beginner'}, bio={p.bio or 'n/a'}, "
           f"medications_reported={'yes (do not discuss)' if p.meds.strip() else 'none'}. Preferred language: {'Hindi' if lang == 'hi' else 'English'}.")
    contents = []
    for m in r.history[-8:]:
        role = "model" if m.role == "a" else "user"
        if not contents and role == "model": continue
        contents.append({"role": role, "parts": [{"text": m.text}]})
    contents.append({"role": "user", "parts": [{"text": r.message}]})
    body = {"systemInstruction": {"parts": [{"text": SYS + (WORKOUT if r.mode == "workout" else "") + "\n" + ctx}]}, "contents": contents,
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": 3000}}
    models = list(dict.fromkeys([MODEL] + [m.strip() for m in FALLBACK.split(",") if m.strip()]))
    detail = ""
    for attempt, model in enumerate(models * 2):  # every model in order, then once more
        if attempt: await asyncio.sleep(min(attempt, 3))
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
        got = False
        try:
            async with httpx.AsyncClient(timeout=40) as c:
                async with c.stream("POST", url, headers={"x-goog-api-key": KEY}, json=body) as res:
                    if res.status_code != 200:
                        raw = (await res.aread()).decode("utf-8", "ignore")
                        try: msg = json.loads(raw)["error"]["message"]
                        except Exception: msg = ""
                        detail = f"{res.status_code}: {msg[:160]}"
                        if res.status_code in (429, 500, 503, 504): continue  # busy: retry / try fallback
                        break
                    async for line in res.aiter_lines():
                        if not line.startswith("data:"): continue
                        try: parts = json.loads(line[5:])["candidates"][0]["content"]["parts"]
                        except Exception: continue
                        t = "".join(x.get("text", "") for x in parts)
                        if t: got = True; yield sse({"t": t})
            if got: yield sse({"done": True}); return
            detail = detail or "empty reply"
        except Exception as e:
            if got: yield sse({"done": True}); return
            detail = type(e).__name__
    yield sse({"err": "ai_unavailable", "detail": detail}); yield sse({"done": True})

@router.post("/api/ai/stream")
async def stream(r: Req):
    return StreamingResponse(gen(r), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
