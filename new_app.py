import os
import random
import subprocess
import streamlit as st
import yt_dlp
from langchain_groq import ChatGroq
from imageio_ffmpeg import get_ffmpeg_exe  # pip install imageio-ffmpeg

# === CONFIG ===
GROQ_API_KEY = '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'  # Replace with your key
llm = ChatGroq(
    groq_api_key=GROQ_API_KEY,
    model_name="Llama3-8b-8192"
)

# Folders
BRAINROT_FOLDER = "brainrot_videos"  # Fallback directory
OUTPUT_FOLDER = "outputs"
TRANSCRIPT_PLACEHOLDER = "(Whisper ASR integration pending)"

# Ensure folders exist
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(BRAINROT_FOLDER, exist_ok=True)

# Locate ffmpeg
FFMPEG_CMD = None
try:
    FFMPEG_CMD = get_ffmpeg_exe()
except Exception:
    raise EnvironmentError("ffmpeg not found. Install imageio-ffmpeg or ffmpeg and ensure it's in PATH.")

# Helper: duration
def get_video_duration(path: str) -> float:
    try:
        out = subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', path
        ], stderr=subprocess.DEVNULL).decode().strip()
        return float(out)
    except:
        return 0.0

# Download via yt-dlp
def download_video(url: str, output_path: str):
    opts = {'format': 'mp4[height<=720]', 'outtmpl': output_path}
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

# Generate short script via Groq (metadata only)
def generate_short_script(transcript: str) -> str:
    prompt = f"""
Extract the most interesting 30-second part from this transcript for a YouTube Short:
{transcript}
Respond ONLY with the short script text.
"""
    return llm.predict(prompt).strip()

# Trim video
def trim_video(src: str, dst: str, start: float, duration: float):
    cmd = [FFMPEG_CMD, '-y', '-ss', str(start), '-i', src, '-t', str(duration), '-c:v', 'libx264', '-c:a', 'aac', dst]
    res = subprocess.run(cmd, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode())

# Stack two streams vertically with crop
def stack_videos(top: str, bottom: str, out: str, duration: float):
    # Both: scale to cover then center-crop to 720x640
    fc = (
        "[0:v]scale=720:640:force_original_aspect_ratio=increase,crop=720:640,setsar=1[top];"
        "[1:v]scale=720:640:force_original_aspect_ratio=increase,crop=720:640,setsar=1[bottom];"
        "[top][bottom]vstack=2[v]"
    )
    cmd = [
        FFMPEG_CMD, '-y', '-i', top, '-i', bottom,
        '-filter_complex', fc,
        '-map', '[v]', '-map', '0:a',
        '-c:v', 'libx264', '-c:a', 'aac', out
    ]
    res = subprocess.run(cmd, stderr=subprocess.PIPE)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.decode())

# Streamlit UI
st.set_page_config(page_title="Brainrot Shorts Generator", layout="centered")
st.title("🧠🎬 Brainrot YouTube Short Generator with Custom Brainrot")

main_url = st.text_input("Main YouTube video link:")
brainrot_url = st.text_input("Optional: Brainrot YouTube video link (for custom B-roll):")
if st.button("Generate Short"):
    try:
        # clear outputs
        for f in os.listdir(OUTPUT_FOLDER): os.remove(os.path.join(OUTPUT_FOLDER, f))

        # 1. Download main video
        main_path = os.path.join(OUTPUT_FOLDER, 'main.mp4')
        with st.spinner("Downloading main video..."):
            download_video(main_url, main_path)

        # 2. Download or pick brainrot source
        if brainrot_url:
            br_src = os.path.join(OUTPUT_FOLDER, 'brainrot_src.mp4')
            with st.spinner("Downloading brainrot video..."):
                download_video(brainrot_url, br_src)
        else:
            # fallback to random file in BRAINROT_FOLDER
            candidates = [os.path.join(BRAINROT_FOLDER,f) for f in os.listdir(BRAINROT_FOLDER) if f.endswith('.mp4')]
            if not candidates:
                st.error("No brainrot videos available in folder. Please upload or provide a link.")
                st.stop()
            br_src = random.choice(candidates)

        # 3. Placeholder transcript & script metadata
        transcript = TRANSCRIPT_PLACEHOLDER
        with st.spinner("Generating script metadata via Groq..."):
            script_meta = generate_short_script(transcript)

        # 4. Trim segments
        dur = 30.0
        main_trim = os.path.join(OUTPUT_FOLDER, 'main_trim.mp4')
        with st.spinner("Trimming main video..."):
            trim_video(main_path, main_trim, start=5, duration=dur)

        # brainrot trim random segment
        total_br = get_video_duration(br_src)
        start_br = random.uniform(0, max(0,total_br-dur)) if total_br>dur else 0
        br_trim = os.path.join(OUTPUT_FOLDER, 'br_trim.mp4')
        with st.spinner("Trimming brainrot segment..."):
            trim_video(br_src, br_trim, start=start_br, duration=dur)

        # 5. Stack and produce final
        final_path = os.path.join(OUTPUT_FOLDER, 'short_final.mp4')
        with st.spinner("Composing final short..."):
            stack_videos(main_trim, br_trim, final_path, duration=dur)

        # 6. Display & download
        st.success("✅ Your Short is Ready!")
        st.video(final_path)
        st.download_button("Download Video", data=open(final_path,'rb'), file_name='short_final.mp4')
    except Exception as e:
        st.error(f"Error: {e}")

