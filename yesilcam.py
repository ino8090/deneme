#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import re
import logging
import subprocess
import requests

# ===================== AYARLAR =====================
RTMP_URL = os.getenv("RTMP_URL", "rtmp://ssh101.bozztv.com:1935/ssh101")
STREAM_KEY = os.getenv("STREAM_KEY", "0212tv")
DESTINATION_RTMP = f"{RTMP_URL.rstrip('/')}/{STREAM_KEY}"

M3U_URL = os.getenv("M3U_URL", "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/prasss.m3u")
LOGO_URL = os.getenv("LOGO_URL", "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/1790197529120.png")

STATE_FILE = os.getenv("STATE_FILE_NAME", "state_yesilcam.json")
PIPE_PATH = "/tmp/playout_pipe.nut"
TITLE_FILE = "title.txt"
LOGO_FILE = "logo.png"

LOGO_OPACITY = float(os.getenv("LOGO_OPACITY", "1.0"))
TEXT_OPACITY = float(os.getenv("TEXT_OPACITY", "1.0"))
BOLD_FONT_PATH = os.getenv("BOLD_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ===================== STATE (DURUM) YÖNETİMİ =====================
def load_state():
    """Önceki yayından kalan film indeksini ve kaldığı saniyeyi yükler."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                index = data.get("index", 0)
                seek_time = data.get("seek_time", 0)
                
                mins, secs = divmod(int(seek_time), 60)
                hrs, mins = divmod(mins, 60)
                time_fmt = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
                
                logging.info(f"💾 Kayıtlı durum yüklendi: Film Indeksi={index}, Kaldığı Süre={time_fmt} ({int(seek_time)} sn)")
                return index, seek_time
        except Exception as e:
            logging.error(f"⚠️ State dosyası okunurken hata oluştu: {e}")
    return 0, 0


def save_state(index, seek_time):
    """Mevcut index ve saniyeyi diskte kaydeder."""
    try:
        data = {
            "index": index,
            "seek_time": int(seek_time),
            "updated_at": time.time()
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"⚠️ State kaydedilemedi: {e}")


# ===================== YARDIMCI FONKSİYONLAR =====================
def create_named_pipe():
    if os.path.exists(PIPE_PATH):
        os.remove(PIPE_PATH)
    os.mkfifo(PIPE_PATH)
    logging.info(f"✅ Named Pipe (FIFO) oluşturuldu: {PIPE_PATH}")


def download_logo():
    try:
        res = requests.get(LOGO_URL, timeout=10)
        if res.status_code == 200 and len(res.content) > 0:
            with open(LOGO_FILE, 'wb') as f:
                f.write(res.content)
            logging.info("✅ Kanal logosu başarıyla indirildi.")
    except Exception as e:
        logging.error(f"⚠️ Logo indirme hatası: {e}")


def update_title_file(title_text):
    try:
        with open(TITLE_FILE, "w", encoding="utf-8") as f:
            f.write(title_text)
        logging.info(f"📝 Yayın başlığı güncellendi: {title_text}")
    except Exception as e:
        logging.error(f"⚠️ Başlık dosyası yazma hatası: {e}")


def parse_m3u(url):
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            lines = res.text.splitlines()
            playlist = []
            pending_title = None
            for raw_line in lines:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith('#EXTINF'):
                    match = re.search(r',(.+)$', line)
                    pending_title = match.group(1).strip() if match else None
                elif not line.startswith('#') and line.startswith('http'):
                    title = pending_title or os.path.basename(line.split('?')[0])
                    playlist.append({"url": line, "title": title})
                    pending_title = None
            return playlist
    except Exception as e:
        logging.error(f"⚠️ M3U indirilirken hata: {e}")
    return []


# ===================== PLAYOUT MOTORU =====================
def start_master_encoder():
    """Master Encoder: RTMP Bağlantısını açar ve kesintisiz katman yayını yapar."""
    has_logo = os.path.exists(LOGO_FILE) and os.path.getsize(LOGO_FILE) > 0

    title_drawtext = (
        f"drawtext=textfile='{TITLE_FILE}':reload=1:fontfile='{BOLD_FONT_PATH}':"
        f"fontcolor=white@{TEXT_OPACITY}:fontsize=25:"
        f"x=80:y=main_h-th-55"
    )

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning"]
    cmd.extend(["-re", "-i", PIPE_PATH])

    if has_logo:
        cmd.extend(["-i", LOGO_FILE])
        filter_complex = (
            f"[1:v]scale=-2:87,format=rgba,colorchannelmixer=aa={LOGO_OPACITY}[logo];"
            f"[0:v][logo]overlay=75:55[tmp];"
            f"[tmp]{title_drawtext}[v]"
        )
    else:
        filter_complex = f"[0:v]{title_drawtext}[v]"

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-b:v", "2500k",
        "-maxrate", "2500k",
        "-bufsize", "5000k",
        "-pix_fmt", "yuv420p",
        "-g", "50",
        "-r", "25",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",
        "-f", "flv",
        DESTINATION_RTMP
    ])

    logging.info("🚀 Master RTMP Yayın Hattı Açılıyor...")
    return subprocess.Popen(cmd)


def feed_video_to_pipe(video_url, current_index, seek_time=0):
    """
    Slave Feeder: Videoları boru hattına standart 1080p 25fps olarak besler.
    Kaldığı saniyeyi (-ss) atlar, anlık dakikayı loglara basar ve durumu kaydeder.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]

    if seek_time > 0:
        mins, secs = divmod(int(seek_time), 60)
        hrs, mins = divmod(mins, 60)
        time_fmt = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
        logging.info(f"⏩ Film {time_fmt} süresinden ({int(seek_time)}. saniye) başlatılıyor...")
        cmd.extend(["-ss", str(seek_time)])

    cmd.extend([
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", video_url,
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=25",
        "-c:v", "mpeg4",
        "-b:v", "8000k",
        "-c:a", "pcm_s16le",
        "-ar", "44100",
        "-ac", "2",
        "-f", "nut",
        "-y",
        PIPE_PATH
    ])

    proc = subprocess.Popen(cmd)
    start_timestamp = time.time() - seek_time

    try:
        while proc.poll() is None:
            time.sleep(10)
            elapsed = time.time() - start_timestamp
            
            # Saniyeyi Dakika/Saat cinsinden loglama formatına çeviriyoruz
            mins, secs = divmod(int(elapsed), 60)
            hrs, mins = divmod(mins, 60)
            
            if hrs > 0:
                time_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"
            else:
                time_str = f"{mins:02d}:{secs:02d}"
                
            logging.info(f"⏳ Oynatılıyor -> Dakika: {time_str} (Toplam: {int(elapsed)} sn)")
            save_state(current_index, elapsed)

    except Exception as e:
        logging.error(f"⚠️ Video aktarımında hata: {e}")
        proc.kill()

    proc.wait()
    save_state(current_index + 1, 0)
    logging.info("✅ Videonun beslemesi tamamlandı.")


def main():
    download_logo()
    create_named_pipe()
    update_title_file("Yeşilçam TV Canlı Yayın")

    current_index, seek_time = load_state()

    master_process = start_master_encoder()
    time.sleep(2)

    try:
        while True:
            playlist = parse_m3u(M3U_URL)
            if not playlist:
                logging.warning("M3U listesi boş veya çekilemedi! 10 saniye bekleniyor...")
                time.sleep(10)
                continue

            if current_index >= len(playlist):
                current_index = 0
                seek_time = 0

            current_item = playlist[current_index]
            target_url = current_item["url"]
            film_title = current_item["title"]

            update_title_file(film_title)
            logging.info(f"📺 [Sıra: {current_index + 1}/{len(playlist)}] Film: {film_title}")

            feed_video_to_pipe(target_url, current_index, seek_time)

            current_index += 1
            seek_time = 0

    except KeyboardInterrupt:
        logging.info("Yayın durduruluyor...")
    finally:
        if master_process:
            master_process.terminate()
        if os.path.exists(PIPE_PATH):
            os.remove(PIPE_PATH)


if __name__ == "__main__":
    main()
