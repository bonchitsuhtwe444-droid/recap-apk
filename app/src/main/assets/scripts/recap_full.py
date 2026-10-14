import os
import re
import json
import time
import asyncio
import requests
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"))
API_KEY = os.getenv("GEMINI_API_KEY")

WORK_DIR = "/storage/emulated/0/Download/recap_job"
TRANSCRIPT = "/storage/emulated/0/Download/movie_transcript_zh.srt"
VOICE_DIR = os.path.join(WORK_DIR, "voices")
TRANSLATION_FILE = os.path.join(WORK_DIR, "translations.json")

os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(VOICE_DIR, exist_ok=True)

MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.8-flash",
]

BATCH_SIZE = 20  # တစ်ခါ batch ၂၀ ခု
VOICE = "my-MM-NilarNeural"  # အမျိုးသမီးအသံ (ThihaNeural = အမျိုးသား)


def parse_transcript(path):
    pattern = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
    )
    units = []
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        m = pattern.match(lines[i].strip())
        if m:
            h1, m1, s1, ms1 = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
            h2, m2, s2, ms2 = int(m.group(5)), int(m.group(6)), int(m.group(7)), int(m.group(8))
            start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
            end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
            if i + 1 < len(lines):
                text = lines[i + 1].strip()
                if text:
                    units.append({"start": start, "end": end, "zh": text})
        i += 1
    return units


def translate_batch(texts, model, start_index):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={API_KEY}"

    prompt = f"""You are a professional Chinese to Burmese translator for movie recaps.
Translate each numbered line into natural spoken Burmese.
Rules:
- Keep the same number for each line (start from {start_index + 1}).
- Do NOT summarize, shorten, or merge lines.
- Each line must keep its own content.
- Use natural spoken Burmese, not formal written style.
- Do not add explanation.

Lines:
"""
    for i, t in enumerate(texts):
        prompt += f"{start_index + i + 1}. {t}\n"

    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    for attempt in range(5):
        try:
            r = requests.post(url, json=payload, timeout=180)
        except Exception as e:
            print(f"  Network error: {e}")
            time.sleep(15)
            continue

        if r.status_code == 200:
            result = r.json()
            if "candidates" in result:
                return result["candidates"][0]["content"]["parts"][0]["text"]
            time.sleep(15)
            continue

        if r.status_code in (503, 429):
            wait = 20 if r.status_code == 503 else 40
            print(f"  HTTP {r.status_code} — {wait}s စောင့် ({attempt + 1}/5)...")
            time.sleep(wait)
            continue

        raise Exception(f"Gemini HTTP {r.status_code}: {r.text[:300]}")

    raise Exception("Server အလုပ်ရှုပ်နေတယ် — ခဏနေမှ ပြန်စမ်းပါ")


def find_working_model():
    print("အလုပ်လုပ်တဲ့ model ရှာနေပါတယ်...")
    for model in MODELS:
        try:
            test = translate_batch(["你好"], model, 0)
            if test:
                print(f"✅ {model}")
                return model
        except Exception as e:
            print(f"❌ {model}: {str(e)[:80]}")
            continue
    return None


async def tts_one(text, out_path):
    import edge_tts
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(out_path)


def make_voice(text, out_path):
    asyncio.run(tts_one(text, out_path))


def main():
    if not API_KEY:
        print("ERROR: GEMINI_API_KEY မတွေ့ပါ")
        return

    # ၁။ Transcript ဖတ်
    units = parse_transcript(TRANSCRIPT)
    print(f"Units: {len(units)}")

    if not units:
        print("Units မတွေ့ပါ")
        return

    # ၂။ ရှိပြီးသား translations.json ရှိလား စစ်
    if os.path.exists(TRANSLATION_FILE):
        print(f"ရှိပြီးသား translation ကို ဖတ်နေပါတယ်...")
        with open(TRANSLATION_FILE, "r", encoding="utf-8") as f:
            translations = json.load(f)
        print(f"ရှိပြီးသား: {len(translations)} ကြောင်း")
    else:
        translations = []

    # ၃။ Model ရှာ
    if not translations:
        model = find_working_model()
        if not model:
            print("ဘယ် model မှ အလုပ်မလုပ်ပါ")
            return

        # ၄။ Batch လိုက် ဘာသာပြန်
        total = len(units)
        for start in range(0, total, BATCH_SIZE):
            end = min(start + BATCH_SIZE, total)
            batch_units = units[start:end]
            batch_texts = [u["zh"] for u in batch_units]

            print(f"\n[{start + 1}-{end}/{total}] ဘာသာပြန်နေပါတယ်...")

            try:
                result = translate_batch(batch_texts, model, start)
            except Exception as e:
                print(f"  Error: {e}")
                print(f"  ဒီ batch ကို ကျော်သွားမယ်")
                translations.extend(["[MISSING]"] * len(batch_units))
                continue

            # ဘာသာပြန်ချက်ကို line တစ်ခုချင်း ခွဲ
            lines = re.findall(r"^\d+\.\s*(.+)$", result, re.MULTILINE)

            if len(lines) != len(batch_units):
                print(f"  ⚠️ ကိုက်မကိုက်: {len(lines)} vs {len(batch_units)}")
                # လိုအပ်ရင် [MISSING] နဲ့ ဖြည့်
                while len(lines) < len(batch_units):
                    lines.append("[MISSING]")
                lines = lines[:len(batch_units)]

            translations.extend(lines)

            # Save after each batch
            with open(TRANSLATION_FILE, "w", encoding="utf-8") as f:
                json.dump(translations, f, ensure_ascii=False, indent=2)

            print(f"  ✅ {len(translations)}/{total} သိမ်းပြီး")

            time.sleep(3)

        print(f"\n✅ ဘာသာပြန်ချက် အားလုံး ပြီးပါပြီ — {TRANSLATION_FILE}")

    # ၅။ တစ်ခုချင်း မြန်မာအသံ ထုတ်
    print(f"\nမြန်မာအသံ ထုတ်နေပါတယ် ({len(translations)} ခု)...")
    for i, (unit, my_text) in enumerate(zip(units, translations)):
        out = os.path.join(VOICE_DIR, f"voice_{i:04d}.mp3")
        if os.path.exists(out):
            continue
        if my_text == "[MISSING]":
            print(f"[{i}] SKIP (missing)")
            continue
        print(f"[{i}/{len(units)}] {my_text[:40]}...")
        try:
            make_voice(my_text, out)
        except Exception as e:
            print(f"  TTS error: {e}")

    print(f"\n✅ အားလုံး ပြီးပါပြီ!")
    print(f"ဖိုင်တွေ: {VOICE_DIR}")


if __name__ == "__main__":
    main()
