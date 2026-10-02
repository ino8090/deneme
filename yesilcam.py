#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import re
import logging
import subprocess
from datetime import datetime, timedelta
import requests

# ===================== AYARLAR =====================
RTMP_URL = os.getenv("RTMP_URL", "rtmp://ssh101.bozztv.com:1935/ssh101")
STREAM_KEY = os.getenv("STREAM_KEY", "0212tv")
DESTINATION_RTMP = f"{RTMP_URL.rstrip('/')}/{STREAM_KEY}"

M3U_URL = os.getenv("M3U_URL", "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/prasss.m3u")
LOGO_URL = os.getenv("LOGO_URL", "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/1790197529120.png")

PIPE_PATH = "/tmp/playout_pipe.nut"
TITLE_FILE = "title.txt"
LOGO_FILE = "logo.png"

DEFAULT_FILM_DURATION_MINUTES = 100 

LOGO_OPACITY = float(os.getenv("LOGO_OPACITY", "1.0"))
TEXT_OPACITY = float(os.getenv("TEXT_OPACITY", "1.0"))
BOLD_FONT_PATH = os.getenv("BOLD_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


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


# ===================== SIRALI DİNAMİK EPG / SAAT ÇİZELGESİ =====================
def build_daily_schedule(playlist):
    if not playlist:
        return []

    now = datetime.now()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    current_pointer = start_of_day

    schedule = []
    film_index = 0

    while current_pointer.day == now.day:
        film = playlist[film_index % len(playlist)]
        duration = timedelta(minutes=DEFAULT_FILM_DURATION_MINUTES)
        end_pointer = current_pointer + duration

        schedule.append({
            "title": film["title"],
            "url": film["url"],
            "start_time": current_pointer,
            "end_time": end_pointer
        })

        current_pointer = end_pointer
        film_index += 1

    return schedule


def print_schedule_log(schedule):
    """Günün 24 saatlik yayın akışını log ekranına şık bir tablo olarak basar."""
    now = datetime.now()
    logging.info("=" * 60)
    logging.info(f"📅 GÜNLÜK YAYIN AKIŞI ÇİZELGESİ ({now.strftime('%d.%m.%Y')})")
    logging.info("=" * 60)
    
    for idx, item in enumerate(schedule, start=1):
        start_str = item["start_time"].strftime("%H:%M")
        end_str = item["end_time"].strftime("%H:%M")
        
        # Şu an yayında olan filmi işaretle
        is_current = item["start_time"] <= now < item["end_time"]
        status_icon = "▶ [ŞU AN YAYINDA]" if is_current else " "
        
        logging.info(f"{idx:02d}. [{start_str} - {end_str}] {item['title']} {status_icon}")
        
    logging.info("=" * 60)


def get_current_program(schedule):
    now = datetime.now()

    for item in schedule:
        if item["start_time"] <= now < item["end_time"]:
            seek_seconds = (now - item["start_time"]).total_seconds()
            return item, seek_seconds

    return None, 0


# ===================== PLAYOUT MOTORU =====================
def start_master_encoder():
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


def feed_video_to_pipe(film_title, video_url, seek_seconds=0):
    """Slave Feeder: Filmi ve anlık geçen dakikayı detaylı loglar."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]

    if seek_seconds > 0:
        mins, secs = divmod(int(seek_seconds), 60)
        hrs, mins = divmod(mins, 60)
        time_fmt = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
        logging.info(f"⏩ Senkronizasyon: '{film_title}' filmi {time_fmt} ({int(seek_seconds)}. sn) noktasından başlatılıyor.")
        cmd.extend(["-ss", str(seek_seconds)])

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
    start_timestamp = time.time() - seek_seconds

    try:
        while proc.poll() is None:
            time.sleep(10)
            elapsed = time.time() - start_timestamp
            
            mins, secs = divmod(int(elapsed), 60)
            hrs, mins = divmod(mins, 60)
            time_str = f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"
            
            logging.info(f"🎬 [YAYINDA] {film_title} | Oynatılan Saniye: {time_str} ({int(elapsed)} sn)")

    except Exception as e:
        logging.error(f"⚠️ Video aktarımında hata: {e}")
        proc.kill()

    proc.wait()
    logging.info(f"✅ '{film_title}' filminin yayını tamamlandı.")


def main():
    download_logo()
    create_named_pipe()
    update_title_file("Yeşilçam TV Canlı Yayın")

    master_process = start_master_encoder()
    time.sleep(2)

    try:
        while True:
            playlist = parse_m3u(M3U_URL)
            if not playlist:
                logging.warning("⚠️ M3U listesi boş! 10 saniye bekleniyor...")
                time.sleep(10)
                continue

            # Yayın Akışını Oluştur
            schedule = build_daily_schedule(playlist)
            
            # Tüm Yayın Akışını Log Ekranında Göster
            print_schedule_log(schedule)

            current_prog, seek_seconds = get_current_program(schedule)

            if not current_prog:
                logging.warning("⚠️ Şu an oynatılacak program bulunamadı. 10 saniye bekleniyor...")
                time.sleep(10)
                continue

            film_title = current_prog["title"]
            target_url = current_prog["url"]

            start_str = current_prog["start_time"].strftime("%H:%M")
            end_str = current_prog["end_time"].strftime("%H:%M")

            update_title_file(film_title)
            logging.info(f"📺 [ŞU ANKİ PROGRAM] {film_title} (Saat: {start_str} - {end_str})")

            # Videoyu boruya gönder
            feed_video_to_pipe(film_title, target_url, seek_seconds)

            time.sleep(1)

    except KeyboardInterrupt:
        logging.info("Yayın durduruluyor...")
    finally:
        if master_process:
            master_process.terminate()
        if os.path.exists(PIPE_PATH):
            os.remove(PIPE_PATH)


if __name__ == "__main__":
    main()
