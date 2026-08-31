#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import time
import os
import re
import json
import requests
import socket
from urllib.parse import urlparse, unquote, quote

# ===================== AYARLAR =====================
RTMP_URL = os.getenv("RTMP_URL") or "rtmp://ssh101.bozztv.com:1935/ssh101"
STREAM_KEY = os.getenv("STREAM_KEY") or "denme"
RTMP_SERVER = f"{RTMP_URL}/{STREAM_KEY}"

M3U_URL = os.getenv("M3U_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/deneme.m3u"
LOGO_URL = os.getenv("LOGO_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/1787712844266.png"

STATE_FILE_NAME = os.getenv("STATE_FILE_NAME", "state_maxdeneme.json")
GITHUB_STEP_SUMMARY = os.getenv("GITHUB_STEP_SUMMARY")

# VLC benzeri User-Agent
STREAM_USER_AGENT = "VLC/3.0.18 LibVLC/3.0.18"

# ===================== YENİ HTTP BAŞLIKLARI =====================
HTTP_HEADERS = f"""User-Agent: {STREAM_USER_AGENT}
Accept: */*
Accept-Encoding: gzip, deflate, br
Accept-Language: tr-TR,tr;q=0.9,en;q=0.8
Connection: keep-alive
Referer: https://s7.gelsistirire.top/
Origin: https://s7.gelsistirire.top
Sec-Fetch-Dest: video
Sec-Fetch-Mode: cors
Sec-Fetch-Site: same-origin
"""

# ===================== AYARLAR SONU =====================

def format_hms(total_seconds):
    total_seconds = int(total_seconds)
    hrs = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"

def test_rtmp_connection():
    try:
        parsed = urlparse(RTMP_URL)
        host = parsed.hostname or "ssh101.bozztv.com"
        port = parsed.port or 1935
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            print(f"✅ RTMP sunucusuna bağlanılabiliyor: {host}:{port}")
            return True
        else:
            print(f"❌ RTMP sunucusuna bağlanılamıyor: {host}:{port} (Hata: {result})")
            return False
    except Exception as e:
        print(f"❌ RTMP bağlantı testi hatası: {e}")
        return False

def get_local_state():
    if os.path.exists(STATE_FILE_NAME):
        try:
            with open(STATE_FILE_NAME, "r", encoding="utf-8") as f:
                data = json.load(f)
                idx = data.get("last_index", 0)
                sec = data.get("last_seconds", 0)
                print(f"✅ Yerel state okundu ({STATE_FILE_NAME}) => İndeks: {idx}, Saniye: {sec}")
                return idx, sec
        except Exception as e:
            print(f"⚠️ Yerel state okuma hatası: {e}")
    else:
        print(f"ℹ️ Yerel state dosyası bulunamadı, 0'dan başlanıyor.")
    return 0, 0

def update_local_state(index, seconds):
    try:
        data = {"last_index": int(index), "last_seconds": int(seconds)}
        with open(STATE_FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 Konum yerel dosyaya kaydedildi => İndeks: {index}, Saniye: {int(seconds)}")
        return True
    except Exception as e:
        print(f"⚠️ Yerel state yazma hatası: {e}")
        return False

def get_m3u_playlist(m3u_url):
    try:
        headers = {'User-Agent': STREAM_USER_AGENT}
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
            if playlist:
                print(f"✅ Playlist'ten {len(playlist)} içerik yüklendi")
                for i, item in enumerate(playlist):
                    print(f"   {i+1}. {item['title']}")
                return playlist
            else:
                print("⚠️ Playlist boş, tek dosya olarak kullanılıyor")
    except Exception as e:
        print(f"⚠️ M3U çekme hatası: {e}")
    return [{"url": m3u_url, "title": os.path.basename(m3u_url)}]

def download_logo():
    try:
        headers = {'User-Agent': STREAM_USER_AGENT}
        response = requests.get(LOGO_URL, headers=headers, timeout=15)
        if response.status_code == 200 and len(response.content) > 0:
            with open('logo.png', 'wb') as f:
                f.write(response.content)
            print("✅ Logo başarıyla indirildi.")
            return True
        else:
            print(f"⚠️ Logo indirilemedi, HTTP: {response.status_code}")
            return False
    except Exception as e:
        print(f"⚠️ Logo indirme hatası: {e}")
        return False

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
            "## 📺 Canlı Yayın Durumu (maxdeneme)\n\n"
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

def run_ffmpeg_stream(command, current_index, film_title, playlist_len, last_seconds):
    print("▶ FFmpeg başlatıldı, 1080p 30fps @ 2000k yayın iletiliyor...")
    
    process = subprocess.Popen(
        command,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1
    )

    last_save_time = time.time()
    last_dashboard_time = time.time()
    current_stream_seconds = last_seconds
    has_error = False

    while True:
        line = process.stderr.readline()
        if not line and process.poll() is not None:
            break

        if "error" in line.lower() or "failed" in line.lower():
            has_error = True
            print(f"⚠️ FFmpeg Hatası: {line.strip()}")

        if "time=" in line:
            time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
            if time_match:
                hrs, mins, secs = time_match.groups()
                played_seconds = int(hrs) * 3600 + int(mins) * 60 + float(secs)
                current_stream_seconds = last_seconds + played_seconds

                now = time.time()

                if now - last_save_time > 30:
                    update_local_state(current_index, current_stream_seconds)
                    last_save_time = now

                if now - last_dashboard_time > 30:
                    print_dashboard(film_title, current_index, playlist_len, current_stream_seconds)
                    write_step_summary(film_title, current_index, playlist_len, current_stream_seconds)
                    last_dashboard_time = now

    return process.returncode, current_stream_seconds, has_error

def start_m3u_stream():
    print("=" * 60)
    print("📺 maxdeneme Canlı Yayın Sistemi Başlatılıyor")
    print("=" * 60)
    print(f"🔧 Kullanılan M3U   : {M3U_URL}")
    print(f"🔧 Kullanılan Logo  : {LOGO_URL}")
    print(f"🔧 State dosyası    : {STATE_FILE_NAME}")
    print(f"🔧 RTMP hedefi      : {RTMP_SERVER}")
    print(f"🔧 User-Agent       : {STREAM_USER_AGENT}")

    if not test_rtmp_connection():
        print("⚠️ RTMP sunucusuna bağlanılamıyor, 30 saniye beklenip tekrar deneniyor...")
        time.sleep(30)

    download_logo()

    current_index, last_seconds = get_local_state()
    retry_count = 0
    failed_urls = set()

    while True:
        if retry_count > 0 and retry_count % 5 == 0:
            test_rtmp_connection()

        playlist = get_m3u_playlist(M3U_URL)
        if not playlist:
            print("⚠️ Playlist alınamadı, 30 saniye bekleniyor...")
            time.sleep(30)
            continue

        if current_index >= len(playlist):
            current_index = 0
            last_seconds = 0
            retry_count = 0
            failed_urls.clear()

        current_item = playlist[current_index]
        target_stream_url = current_item["url"]
        film_title = current_item["title"]

        if target_stream_url in failed_urls:
            print(f"⚠️ URL daha önce başarısız oldu, sıradaki içeriğe geçiliyor...")
            current_index += 1
            last_seconds = 0
            update_local_state(current_index, 0)
            continue

        print("=" * 60)
        print(f"📺 Yayın Başlatılıyor (Deneme: {retry_count + 1}/10)")
        print(f"🎬 Oynatılan İçerik  : {film_title}")
        print(f"⏱️ Başlangıç Saniyesi: {last_seconds}")
        print(f"🚀 Hedef RTMP       : {RTMP_SERVER}")

        # URL'yi parse et
        if "|" in target_stream_url:
            video_url, audio_url = target_stream_url.split("|", 1)
            video_url = video_url.strip()
            audio_url = audio_url.strip()

            print(f"🎥 Video Bağlantısı : {video_url[:80]}...")
            print(f"🔊 Ses Bağlantısı   : {audio_url[:80]}...")

            # ====== YENİ: HTTP başlıklarını ekle ======
            input_args = [
                '-headers', HTTP_HEADERS,  # VLC benzeri başlıklar
                '-reconnect', '1', 
                '-reconnect_streamed', '1', 
                '-reconnect_delay_max', '5',
                '-ss', str(last_seconds),
                '-re',
                '-i', video_url,
                '-headers', HTTP_HEADERS,  # İkinci giriş için de aynı başlıklar
                '-reconnect', '1', 
                '-reconnect_streamed', '1', 
                '-reconnect_delay_max', '5',
                '-ss', str(last_seconds),
                '-re',
                '-i', audio_url
            ]
            audio_map = ['-map', '1:a:0']
            logo_input_index = 2
        else:
            print(f"📡 Kaynak Yayın     : {target_stream_url[:80]}...")
            
            # ====== YENİ: HTTP başlıklarını ekle ======
            input_args = [
                '-headers', HTTP_HEADERS,  # VLC benzeri başlıklar
                '-reconnect', '1', 
                '-reconnect_streamed', '1', 
                '-reconnect_delay_max', '5',
                '-ss', str(last_seconds),
                '-re',
                '-i', target_stream_url
            ]
            audio_map = ['-map', '0:a?']
            logo_input_index = 1

        print_dashboard(film_title, current_index, len(playlist), last_seconds, status="🟡 Başlatılıyor")
        write_step_summary(film_title, current_index, len(playlist), last_seconds, status="🟡 Başlatılıyor")

        has_logo = os.path.exists('logo.png') and os.path.getsize('logo.png') > 0

        if has_logo:
            filter_str = (
                '[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,'
                'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=30[main];'
                f'[{logo_input_index}:v]scale=-2:80[logo];'
                '[main][logo]overlay=55:55[v]'
            )
            logo_input = ['-i', 'logo.png']
        else:
            filter_str = (
                '[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,'
                'pad=1920:1080:(oh-ih)/2:black,fps=30[v]'
            )
            logo_input = []

        # FFmpeg komutu
        command = [
            'ffmpeg',
            '-loglevel', 'warning',
            '-user_agent', STREAM_USER_AGENT,
        ] + input_args + logo_input + [
            '-filter_complex', filter_str,
            '-map', '[v]'
        ] + audio_map + [
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-pix_fmt', 'yuv420p',
            '-r', '30',
            '-b:v', '2000k',
            '-maxrate', '2000k',
            '-bufsize', '4000k',
            '-g', '60',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-f', 'flv',
            RTMP_SERVER
        ]

        return_code, current_stream_seconds, has_error = run_ffmpeg_stream(
            command, current_index, film_title, len(playlist), last_seconds
        )

        if return_code == 0:
            print("✅ İçerik başarıyla tamamlandı, sıradakine geçiliyor.")
            write_step_summary(film_title, current_index, len(playlist), current_stream_seconds, status="✅ Bitti, sıradakine geçiliyor")
            current_index += 1
            last_seconds = 0
            update_local_state(current_index, 0)
            retry_count = 0
            failed_urls.clear()
        else:
            retry_count += 1
            
            if has_error or return_code in [183, 8, 1]:
                print(f"⚠️ Video kaynağında sorun var, URL not alınıyor...")
                failed_urls.add(target_stream_url)
            
            print(f"⚠️ Yayın koptu (Return Code: {return_code}) - Deneme: {retry_count}/10")
            
            if return_code == 183:
                print("⚠️ RTMP bağlantı hatası, sunucu kontrol ediliyor...")
                test_rtmp_connection()
                wait_time = min(120, 5 * (2 ** min(retry_count, 5)))
            else:
                wait_time = min(120, 5 * (1.5 ** min(retry_count, 3)))
            
            write_step_summary(film_title, current_index, len(playlist), current_stream_seconds, 
                             status=f"🔴 Bağlantı koptu (RC: {return_code}), {int(wait_time)}sn sonra tekrar")
            
            last_seconds = current_stream_seconds
            update_local_state(current_index, last_seconds)

            if retry_count >= 10:
                print("❌ Maksimum deneme sayısına ulaşıldı, sıradaki içeriğe geçiliyor...")
                current_index += 1
                last_seconds = 0
                update_local_state(current_index, 0)
                retry_count = 0
                wait_time = 10
            else:
                print(f"⚠️ {int(wait_time)} saniye sonra tekrar bağlanılıyor...")
        
        time.sleep(wait_time if 'wait_time' in locals() else 5)


if __name__ == "__main__":
    try:
        start_m3u_stream()
    except KeyboardInterrupt:
        print("\n🛑 Yayın kullanıcı tarafından durduruldu.")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Beklenmeyen hata: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
