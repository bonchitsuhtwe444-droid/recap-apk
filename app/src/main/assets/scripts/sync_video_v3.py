import os
import re
import json
import subprocess

# ============ လမ်းကြောင်းများ ============
WORK_DIR = "/storage/emulated/0/Download/recap_job"
VOICE_DIR = os.path.join(WORK_DIR, "voices")
TRANSCRIPT = "/storage/emulated/0/Download/movie_transcript_zh.srt"
TRANSLATION_FILE = os.path.join(WORK_DIR, "translations.json")

SOURCE_VIDEO = "/storage/emulated/0/Download/1000005976_part2.mp4"
OUTPUT_VIDEO = os.path.join(WORK_DIR, "final_recap_v3.mp4")
SEGMENTS_DIR = os.path.join(WORK_DIR, "segments_v3")
os.makedirs(SEGMENTS_DIR, exist_ok=True)

# ============ Settings ============
FPS = 30
MIN_VIDEO_SPEED = 0.5      # video အနှေးဆုံး 0.5x (2x slow motion)
FREEZE_IF_NEEDED = True    # audio ရှည်ရင် frame freeze ထည့်


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


def get_duration(path):
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except:
        return 0.0


def compute_windows(units, video_duration):
    windows = []
    n = len(units)
    for i, u in enumerate(units):
        if i == 0:
            v_start = 0.0
        else:
            prev = units[i - 1]
            v_start = (prev["end"] + u["start"]) / 2
        if i == n - 1:
            v_end = video_duration
        else:
            nxt = units[i + 1]
            v_end = (u["end"] + nxt["start"]) / 2
        windows.append({
            "video_start": v_start,
            "video_end": v_end,
            "video_dur": v_end - v_start,
        })
    return windows


def make_segment(source, v_start, v_end, audio_path, out_path):
    """
    Video ကို audio duration နဲ့ ကိုက်ညီအောင် ချိန်။
    - Audio တိုရင်: video ကို speed up (မြန်စေ) — ဒါက ပုံမှန်
    - Audio ရှည်ရင်: video ကို slow motion (နှေးစေ) — 0.5x အထိ
      - ဒါထက်ပိုရှည်ရင်: frame freeze ထည့်
    """
    v_dur = v_end - v_start
    a_dur = get_duration(audio_path)

    if a_dur <= 0:
        print(f"  Audio duration 0 — skip")
        return False

    # Video က audio ထက် ရှည်ရင် (audio တို) → video ကို မြန်စေ
    if v_dur > a_dur:
        video_speed = v_dur / a_dur
        if video_speed > 2.0:
            video_speed = 2.0
        # video ကို မြန်စေ → output duration = a_dur
        v_filter = f"setpts=PTS/{video_speed:.4f}"
        out_dur = a_dur
        pad_dur = a_dur
        # freeze မလိုဘူး
        freeze_dur = 0.0

    # Video က audio ထက် တိုရင် (audio ရှည်) → video ကို နှေးစေ + freeze
    else:
        video_speed = v_dur / a_dur  # < 1.0

        if video_speed < MIN_VIDEO_SPEED:
            # 0.5x အောက် နှေးလို့ မရ → 0.5x နဲ့ ထားပြီး ကျန်တာ freeze
            video_speed = MIN_VIDEO_SPEED
            # slow motion အရှည်
            slowed_dur = v_dur / video_speed  # = v_dur * 2
            # ကျန်တာ freeze
            freeze_dur = a_dur - slowed_dur
            if freeze_dur < 0:
                freeze_dur = 0.0
            out_dur = a_dur
            v_filter = f"setpts=PTS/{video_speed:.4f}"
        else:
            # audio duration အတိုင်း နှေးစေ
            out_dur = a_dur
            freeze_dur = 0.0
            v_filter = f"setpts=PTS/{video_speed:.4f}"

    # FFmpeg filter chain
    # - video: slow motion + (freeze ရှိရင်) tpad
    # - audio: မပြောင်း၊ ဒါပေမယ့် out_dur အတိုင်း ဖြတ်
    
    if freeze_dur > 0:
        # slow motion ပြီးရင် နောက်ဆုံး frame ကို freeze_dur ကြာ ဆက်ပြ
        # tpad=stop_mode=clone:stop_duration=X
        v_filter_chain = f"{v_filter},tpad=stop_mode=clone:stop_duration={freeze_dur:.4f}"
    else:
        v_filter_chain = v_filter

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{v_start:.3f}",
        "-t", f"{v_dur:.3f}",
        "-i", source,
        "-i", audio_path,
        "-filter_complex",
        f"[0:v]{v_filter_chain}[v];[1:a]anull[a]",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-r", str(FPS),
        "-t", f"{out_dur:.3f}",
        out_path,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  FFmpeg error: {result.stderr[-400:]}")
        return False
    return True


def concat_segments(segment_files, out_path):
    list_file = os.path.join(SEGMENTS_DIR, "concat_list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for seg in segment_files:
            f.write(f"file '{seg}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Concat error: {result.stderr[-400:]}")
        return False
    return True


def main():
    print("=" * 50)
    print("VIDEO SYNC V3 — Slow Motion + Frame Freeze")
    print("=" * 50)

    if not os.path.exists(SOURCE_VIDEO):
        print(f"❌ Source video မတွေ့ပါ: {SOURCE_VIDEO}")
        return
    if not os.path.exists(TRANSLATION_FILE):
        print(f"❌ translations.json မတွေ့ပါ")
        return

    units = parse_transcript(TRANSCRIPT)
    print(f"Units: {len(units)}")

    with open(TRANSLATION_FILE, "r", encoding="utf-8") as f:
        translations = json.load(f)
    print(f"Translations: {len(translations)}")

    video_dur = get_duration(SOURCE_VIDEO)
    print(f"Video duration: {video_dur:.2f}s")

    windows = compute_windows(units, video_dur)

    segment_files = []
    total = min(len(units), len(translations))
    for i in range(total):
        voice_path = os.path.join(VOICE_DIR, f"voice_{i:04d}.mp3")
        if not os.path.exists(voice_path):
            print(f"[{i}] voice မတွေ့ — skip")
            continue

        seg_path = os.path.join(SEGMENTS_DIR, f"seg_{i:04d}.mp4")
        if os.path.exists(seg_path):
            print(f"[{i}] ရှိပြီးသား — skip")
            segment_files.append(seg_path)
            continue

        w = windows[i]
        v_dur = w["video_dur"]
        a_dur = get_duration(voice_path)
        print(f"[{i}/{total}] v={v_dur:.2f}s a={a_dur:.2f}s", end="")

        ok = make_segment(SOURCE_VIDEO, w["video_start"], w["video_end"], voice_path, seg_path)
        if ok:
            segment_files.append(seg_path)
            print(" ✓")
        else:
            print(" ✗")

    print(f"\nSegments: {len(segment_files)}")

    if not segment_files:
        print("❌ Segment မရှိပါ")
        return

    print("\nပေါင်းစည်းနေပါတယ်...")
    if concat_segments(segment_files, OUTPUT_VIDEO):
        print(f"\n✅ ပြီးပါပြီ!")
        print(f"ရလဒ်: {OUTPUT_VIDEO}")


if __name__ == "__main__":
    main()
