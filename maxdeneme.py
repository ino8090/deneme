#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import time
import os
import re
import json
import requests
from collections import deque

# yt-dlp modülünü otomatik yükleme kontrolü
try:
    import yt_dlp
except ImportError:
    print("📦 'yt-dlp' kütüphanesi eksik, otomatik yükleniyor...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "yt-dlp"])
    import yt_dlp

# ===================== AYARLAR =====================
RTMP_URL = "rtmp://ssh101.bozztv.com:1935/ssh101"
STREAM_KEY = os.getenv("STREAM_KEY") or "maxtv"
RTMP_SERVER = f"{RTMP_URL}/{STREAM_KEY}"

M3U_URL = os.getenv("M3U_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/yerli1.m3u"
LOGO_URL = os.getenv("LOGO_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/file_000000007be48210a068edefa7260629.png"

STATE_FILE_NAME = os.getenv("STATE_FILE_NAME", "state_fixtv.json")
GITHUB_STEP_SUMMARY = os.getenv("GITHUB_STEP_SUMMARY")

STREAM_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
STREAM_REFERER = "https://vidmody.com/"

LOGO_OPACITY = float(os.getenv("LOGO_OPACITY", "0.4"))
TEXT_OPACITY = float(os.getenv("TEXT_OPACITY", "0.5"))
BOLD_FONT_PATH = os.getenv("BOLD_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def format_hms(total_seconds):
    total_seconds = int(total_seconds)
    hrs = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def get_local_state():
    if os.path.exists(STATE_FILE_NAME):
        if os.path.getsize(STATE_FILE_NAME) == 0:
            print(f"⚠️ Yerel state dosyası boş ({STATE_FILE_NAME}), 0'dan başlanıyor.")
            return 0, 0, ""
        try:
            with open(STATE_FILE_NAME, "r", encoding="utf-8") as f:
                data = json.load(f)
                idx = data.get("last_index", 0)
                sec = data.get("last_seconds", 0)
                url = data.get("last_url", "")
                print(f"✅ Yerel state okundu ({STATE_FILE_NAME}) => İndeks: {idx}, Saniye: {sec}")
                return idx, sec, url
        except Exception as e:
            print(f"⚠️ Yerel state okuma hatası: {e}")
    else:
        print(f"ℹ️ Yerel state dosyası bulunamadı, 0'dan başlanıyor.")
    return 0, 0, ""


def update_local_state(index, seconds, url=""):
    try:
        data = {"last_index": int(index), "last_seconds": int(seconds), "last_url": url}
        with open(STATE_FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 Konum yerel dosyaya kaydedildi => İndeks: {index}, Saniye: {int(seconds)}")
    except Exception as e:
        print(f"⚠️ Yerel state yazma hatası: {e}")


def sanitize_url_to_m3u8(url):
    """Sahte .gif, .jpg veya parametreli uzantıları temizleyip zorunlu .m3u8 yapar."""
    if not url:
        return url
    
    # URL üzerindeki sahte .gif uzantısını .m3u8 ile değiştir
    if ".gif" in url:
        url = re.sub(r'\.gif(\?.*)?$', '.m3u8\\1', url)
        url = url.replace('.gif', '.m3u8')
        
    return url


def extract_real_m3u8(url):
    """Web sayfalarından adresi çıkarır ve uzantıyı .m3u8 olarak düzeltir."""
    if ".m3u8" in url.lower() and "vidmody.com/vs/" not in url.lower():
        return sanitize_url_to_m3u8(url), STREAM_USER_AGENT, STREAM_REFERER

    print(f"🔍 yt-dlp ile gerçek .m3u8 adresi ayrıştırılıyor: {url}")
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'user_agent': STREAM_USER_AGENT,
        'referer': STREAM_REFERER,
    }

    extracted_url = url
    ua = STREAM_USER_AGENT
    ref = STREAM_REFERER

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'url' in info:
                extracted_url = info['url']
                http_headers = info.get('http_headers', {})
                ua = http_headers.get('User-Agent', STREAM_USER_AGENT)
                ref = http_headers.get('Referer', STREAM_REFERER)
            elif 'formats' in info and len(info['formats']) > 0:
                best_format = info['formats'][-1]
                extracted_url = best_format['url']
                http_headers = best_format.get('http_headers', {})
                ua = http_headers.get('User-Agent', STREAM_USER_AGENT)
                ref = http_headers.get('Referer', STREAM_REFERER)
    except Exception as e:
        print(f"⚠️ yt-dlp ayrıştırma hatası: {e}. Orijinal URL ile devam ediliyor.")

    # .gif uzantısı .m3u8 olarak düzeltiliyor
    final_url = sanitize_url_to_m3u8(extracted_url)
    print(f"🎯 Dönüştürülen Akış Adresi (.m3u8): {final_url[:80]}...")
    
    return final_url, ua, ref


def get_m3u_playlist(m3u_url):
    try:
        headers = {
            'User-Agent': STREAM_USER_AGENT,
            'Referer': STREAM_REFERER
        }
        response = requests.get(m3u_url, headers=headers, timeout=15)
        if response.status_code == 200:
            lines = response.text.splitlines()
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
        print(f"⚠️ M3U çekme hatası: {e}")
    return [{"url": m3u_url, "title": os.path.basename(m3u_url)}]


def download_logo():
    headers = {'User-Agent': STREAM_USER_AGENT}
    try:
        response = requests.get(LOGO_URL, headers=headers, timeout=15)
        if response.status_code == 200 and len(response.content) > 0:
            with open('logo.png', 'wb') as f:
                f.write(response.content)
            print("✅ 1. Logo başarıyla indirildi.")
    except Exception as e:
        print(f"⚠️ 1. Logo indirme hatası: {e}")


def write_title_file(title):
    try:
        with open('title.txt', 'w', encoding='utf-8') as f:
            f.write(title)
    except Exception as e:
        print(f"⚠️ Başlık dosyası yazma hatası: {e}")


def print_dashboard(title, index, playlist_len, seconds, status="🟢 Yayında"):
    print("┌" + "─" * 58 + "┐")
    print(f"│ 🎬 İçerik         : {title[:36]:<36} │")
    print(f"│ 🔢 Sıra           : {index + 1}/{playlist_len:<32} │")
    print(f"│ ⏱️  Geçen Süre     : {format_hms(seconds):<36} │")
    print(f"│ 📡 Durum          : {status:<36} │")
    print("└" + "─" * 58 + "┘")


def write_step_summary(title, index, playlist_len, seconds, status="🟢 Yayında"):
    if not GITHUB_STEP_SUMMARY:
        return
    try:
        content = (
            "## 📺 Canlı Yayın Durumu (Maxanimasyon)\n\n"
            "| Alan | Değer |\n"
            "|---|---|\n"
            f"| 🎬 Şu an oynayan içerik | {title} |\n"
            f"| 🔢 Playlist sırası | {index + 1} / {playlist_len} |\n"
            f"| ⏱️ Geçen süre | {format_hms(seconds)} (sa:dk:sn) |\n"
            f"| 📡 Durum | {status} |\n"
            f"| 🕒 Son güncelleme | {time.strftime('%Y-%m-%d %H:%M:%S')} |\n"
        )
        with open(GITHUB_STEP_SUMMARY, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception as e:
        print(f"⚠️ Step summary yazma hatası: {e}")


def start_m3u_stream():
    print(f"🔧 Kullanılan M3U   : {M3U_URL}")
    print(f"🔧 Kullanılan Logo 1: {LOGO_URL}")
    print(f"🔧 State dosyası    : {STATE_FILE_NAME}")
    print(f"🔧 RTMP hedefi      : {RTMP_SERVER}")

    download_logo()

    current_index, last_seconds, last_url = get_local_state()

    consecutive_fast_failures = 0
    FAST_FAIL_THRESHOLD_SECONDS = 20
    MAX_RETRY_DELAY_SECONDS = 120

    while True:
        playlist = get_m3u_playlist(M3U_URL)
        if not playlist:
            time.sleep(10)
            continue

        if current_index >= len(playlist):
            current_index = 0
            last_seconds = 0
            last_url = ""

        current_item = playlist[current_index]
        raw_stream_url = current_item["url"]
        film_title = current_item["title"]

        if last_seconds > 0 and last_url and raw_stream_url != last_url:
            print(f"🔄 Bu sıradaki ({current_index + 1}) içeriğin linki değişmiş, video baştan başlatılacak.")
            last_seconds = 0

        last_url = raw_stream_url

        target_stream_url, active_ua, active_ref = extract_real_m3u8(raw_stream_url)

        write_title_file(film_title)

        print("=" * 60)
        print("📺 Maxanimasyon Canlı Aktarım Yayını (1080p 25fps - 2500k) Başlatılıyor")
        print(f"🎬 Oynatılan İçerik  : {film_title}")
        print(f"⏱️ Başlangıç Saniyesi: {last_seconds}")
        print(f"🚀 Hedef RTMP       : {RTMP_SERVER}")

        headers_arg = (
            f"User-Agent: {active_ua}\r\n"
            f"Referer: {active_ref}\r\n"
            "Origin: https://vidmody.com\r\n"
            "Accept: */*\r\n"
        )

        input_options = [
            '-headers', headers_arg,
            '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
            '-allowed_extensions', 'ALL',
            '-err_detect', 'ignore_err',
            '-analyzeduration', '2000000',
            '-probesize', '2000000',
            '-reconnect', '1',
            '-reconnect_at_eof', '1',
            '-reconnect_streamed', '1',
            '-reconnect_delay_max', '2',
            '-rw_timeout', '10000000'
        ]

        if ";" in target_stream_url:
            video_url, audio_url = target_stream_url.split(";", 1)
            video_url = sanitize_url_to_m3u8(video_url.strip())
            audio_url = sanitize_url_to_m3u8(audio_url.strip())

            print(f"🎥 Video Bağlantısı : {video_url}")
            print(f"🔊 Ses Bağlantısı   : {audio_url}")

            input_args = (
                ['-ss', str(last_seconds)] + input_options + ['-i', video_url] +
                ['-ss', str(last_seconds)] + input_options + ['-i', audio_url]
            )
            audio_map = ['-map', '1:a:0?']
            logo1_input_index = 2
        else:
            print(f"📡 Kaynak Yayın     : {target_stream_url}")
            input_args = ['-ss', str(last_seconds)] + input_options + ['-i', target_stream_url]
            audio_map = ['-map', '0:a:0?']
            logo1_input_index = 1

        print("=" * 60)

        print_dashboard(film_title, current_index, len(playlist), last_seconds, status="🟡 Başlatılıyor")
        write_step_summary(film_title, current_index, len(playlist), last_seconds, status="🟡 Başlatılıyor")

        has_logo1 = os.path.exists('logo.png') and os.path.getsize('logo.png') > 0

        title_drawtext = (
            f"drawtext=textfile='title.txt':reload=1:fontfile='{BOLD_FONT_PATH}':"
            f"fontcolor=white@{TEXT_OPACITY}:fontsize=30:"
            f"x=80:y=main_h-th-67"
        )

        if has_logo1:
            logo_inputs = ['-i', 'logo.png']
            filter_str = (
                '[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,'
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=25[main];'
                f'[{logo1_input_index}:v]scale=-2:91,format=rgba,'
                f'colorchannelmixer=aa={LOGO_OPACITY}[logo1];'
                '[main][logo1]overlay=main_w-overlay_w-104:80[tmp];'
                f'[tmp]{title_drawtext}[v]'
            )
        else:
            logo_inputs = []
            filter_str = (
                '[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,'
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=25[main];'
                f'[main]{title_drawtext}[v]'
            )

        command = [
            'ffmpeg'
        ] + input_args + logo_inputs + [
            '-filter_complex', filter_str,
            '-map', '[v]'
        ] + audio_map + [
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-pix_fmt', 'yuv420p',
            '-r', '25',
            '-b:v', '2500k',
            '-maxrate', '2500k',
            '-bufsize', '3000k',
            '-g', '50',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ac', '2',
            '-ar', '44100',
            '-f', 'flv',
            RTMP_SERVER
        ]

        print("▶ FFmpeg başlatıldı, 1080p 25fps @ 2500k yayın iletiliyor...")

        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        last_save_time = time.time()
        last_dashboard_time = time.time()
        current_stream_seconds = last_seconds
        stderr_tail = deque(maxlen=40)

        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break

            if line:
                stderr_tail.append(line.rstrip())

            if "time=" in line:
                time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                if time_match:
                    hrs, mins, secs = time_match.groups()
                    played_seconds = int(hrs) * 3600 + int(mins) * 60 + float(secs)
                    current_stream_seconds = last_seconds + played_seconds

                    now = time.time()

                    if now - last_save_time > 30:
                        update_local_state(current_index, current_stream_seconds, target_stream_url)
                        last_save_time = now

                    if now - last_dashboard_time > 30:
                        print_dashboard(film_title, current_index, len(playlist), current_stream_seconds)
                        write_step_summary(film_title, current_index, len(playlist), current_stream_seconds)
                        last_dashboard_time = now

        if process.returncode == 0:
            print("✅ İçerik bitti, sıradakine geçiliyor.")
            write_step_summary(film_title, current_index, len(playlist), current_stream_seconds, status="✅ Bitti, sıradakine geçiliyor")
            current_index += 1
            last_seconds = 0
            last_url = ""
            update_local_state(current_index, 0, "")
            consecutive_fast_failures = 0
        else:
            print(f"⚠️ Yayın koptu (Return Code: {process.returncode}). Aynı saniyeden tekrar denenecek.")
            if stderr_tail:
                print("🧾 FFmpeg son log satırları:")
                for tail_line in stderr_tail:
                    print(f"   {tail_line}")
            write_step_summary(film_title, current_index, len(playlist), current_stream_seconds, status="🔴 Bağlantı koptu, tekrar denenecek")
            duration_this_attempt = current_stream_seconds - last_seconds
            if duration_this_attempt < FAST_FAIL_THRESHOLD_SECONDS:
                consecutive_fast_failures += 1
            else:
                consecutive_fast_failures = 0
            last_seconds = current_stream_seconds
            last_url = target_stream_url
            update_local_state(current_index, last_seconds, last_url)

        if consecutive_fast_failures > 0:
            retry_delay = min(5 * (2 ** consecutive_fast_failures), MAX_RETRY_DELAY_SECONDS)
        else:
            retry_delay = 5

        print(f"⚠️ {retry_delay} saniye sonra tekrar bağlanılıyor...")
        time.sleep(retry_delay)


if __name__ == "__main__":
    start_m3u_stream()
