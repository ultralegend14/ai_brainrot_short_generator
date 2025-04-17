import os
import random
import subprocess
import streamlit as st
import yt_dlp
from langchain_groq import ChatGroq
from imageio_ffmpeg import get_ffmpeg_exe

# === CONFIG ===
GROQ_API_KEY = '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'
llm = ChatGroq(groq_api_key=GROQ_API_KEY, model_name="Llama3-8b-8192")

BRAINROT_FOLDER = "brainrot_videos"
OUTPUT_FOLDER = "outputs"
TRANSCRIPT_PLACEHOLDER = "(Whisper ASR integration pending)"

os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(BRAINROT_FOLDER, exist_ok=True)

FFMPEG_CMD = None
try:
    FFMPEG_CMD = get_ffmpeg_exe()
except Exception:
    raise EnvironmentError("FFmpeg not found. Install imageio-ffmpeg or ensure it's in PATH.")

# === Helpers ===
def get_video_duration(path: str) -> float:
    try:
        out = subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=duration', '-of', 'default=noprint_wrappers=1:nokey=1', path
        ], stderr=subprocess.DEVNULL).decode().strip()
        return float(out)
    except:
        return 0.0

def download_video(url: str, output_path: str):
    opts = {'format': 'mp4[height<=720]', 'outtmpl': output_path}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

def generate_short_script(transcript: str) -> str:
    prompt = f"""
Extract the most interesting 30-second part from this transcript for a YouTube Short:
{transcript}
Respond ONLY with the short script text.
"""
    return llm.predict(prompt).strip()

def trim_video(src: str, dst: str, start: float, duration: float):
    cmd = [FFMPEG_CMD, '-y', '-ss', str(start), '-i', src, '-t', str(duration), '-c:v', 'libx264', '-c:a', 'aac', dst]
    res = subprocess.run(cmd, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode())

def stack_videos(top: str, bottom: str, out: str):
    filter_chain = (
        "[0:v]scale=720:640:force_original_aspect_ratio=increase,crop=720:640,setsar=1[top];"
        "[1:v]scale=720:640:force_original_aspect_ratio=increase,crop=720:640,setsar=1[bottom];"
        "[top][bottom]vstack=2[v]"
    )
    cmd = [
        FFMPEG_CMD, '-y', '-i', top, '-i', bottom,
        '-filter_complex', filter_chain,
        '-map', '[v]', '-map', '0:a?', '-c:v', 'libx264', '-c:a', 'aac', out
    ]
    res = subprocess.run(cmd, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode())

def clean_outputs(final_keep: str = None):
    for f in os.listdir(OUTPUT_FOLDER):
        f_path = os.path.join(OUTPUT_FOLDER, f)
        if final_keep and os.path.abspath(f_path) == os.path.abspath(final_keep):
            continue
        os.remove(f_path)

# === Streamlit UI ===
st.set_page_config(page_title="Brainrot Shorts Generator", layout="centered")
st.title("🧠🎬 Brainrot YouTube Short Generator with Custom Brainrot")

main_url = st.text_input("Main YouTube video link:")
brainrot_url = st.text_input("Optional: Brainrot YouTube video link (for custom B-roll):")

if st.button("Generate Short"):
    try:
        st.info("🧹 Cleaning previous outputs...")
        clean_outputs()

        main_path = os.path.join(OUTPUT_FOLDER, 'main.mp4')
        with st.spinner("Downloading main video..."):
            download_video(main_url, main_path)

        # === Brainrot logic ===
        if brainrot_url:
            br_src = os.path.join(OUTPUT_FOLDER, 'brainrot_src.mp4')
            with st.spinner("Downloading brainrot video..."):
                download_video(brainrot_url, br_src)
        else:
            candidates = [os.path.join(BRAINROT_FOLDER, f) for f in os.listdir(BRAINROT_FOLDER) if f.endswith('.mp4')]
            if not candidates:
                st.error("No brainrot videos available in folder. Please upload or provide a link.")
                st.stop()
            br_src = random.choice(candidates)

        # === Generate Metadata ===
        transcript = TRANSCRIPT_PLACEHOLDER
        with st.spinner("Generating script metadata via Groq..."):
            script_meta = generate_short_script(transcript)

        dur = 30.0  # final video duration

        # === Trim Main Video ===
        main_trim = os.path.join(OUTPUT_FOLDER, 'main_trim.mp4')
        with st.spinner("Trimming main video..."):
            trim_video(main_path, main_trim, start=5, duration=dur)

        # === Random Trim Brainrot Video ===
        total_br = get_video_duration(br_src)
        start_br = random.uniform(0, max(0, total_br - dur)) if total_br > dur else 0
        br_trim = os.path.join(OUTPUT_FOLDER, 'br_trim.mp4')
        with st.spinner(f"Trimming brainrot video (random start: {start_br:.2f}s)..."):
            trim_video(br_src, br_trim, start=start_br, duration=dur)

        # === Stack Both Videos ===
        final_path = os.path.join(OUTPUT_FOLDER, 'short_final.mp4')
        with st.spinner("Composing final short..."):
            stack_videos(main_trim, br_trim, final_path)

        st.success("✅ Your Short is Ready!")
        st.video(final_path)
        st.download_button("Download Video", data=open(final_path, 'rb'), file_name='short_final.mp4')

        with st.spinner("🧹 Cleaning temporary files..."):
            clean_outputs(final_keep=final_path)

    except Exception as e:
        st.error(f"❌ Error: {e}")
