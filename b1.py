#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import time
import os
import re
from collections import deque
import requests

# ===================== AYARLAR =====================
RTMP_URL = "rtmp://ssh101.bozztv.com:1935/ssh101"
STREAM_KEY = os.getenv("STREAM_KEY") or "b1"
RTMP_SERVER = f"{RTMP_URL}/{STREAM_KEY}"

# Web sayfası veya doğrudan m3u8 adresi
PAGE_URL = os.getenv("STREAM_URL") or "https://betvinotv29.live/channel?id=zirve"

STREAM_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
MAX_RETRY_DELAY_SECONDS = 60


def extract_m3u8(page_url):
    """Sayfa kaynağından asıl .m3u8 akış adresini ayıklar."""
    if page_url.endswith(".m3u8"):
        return page_url

    headers = {
        "User-Agent": STREAM_USER_AGENT,
        "Referer": page_url
    }
    try:
        response = requests.get(page_url, headers=headers, timeout=10)
        # HTML içindeki .m3u8 bağlantılarını ara
        matches = re.findall(r'https?://[^\s\'"]+\.m3u8[^\s\'"]*', response.text)
        if matches:
            found_url = matches[0]
            print(f"✅ Çözümlenen Yayın Bağlantısı: {found_url}")
            return found_url
    except Exception as e:
        print(f"⚠️ Link ayıklama hatası: {e}")

    print("⚠️ Otomatik m3u8 bulunamadı, doğrudan verilen URL kullanılacak.")
    return page_url


def start_live_relay():
    consecutive_failures = 0

    while True:
        print("\n🔍 Yayın adresi kontrol ediliyor...")
        stream_target = extract_m3u8(PAGE_URL)

        # Sunucu engeline takılmamak için Header yapılandırması
        headers_arg = f"User-Agent: {STREAM_USER_AGENT}\r\nReferer: {PAGE_URL}\r\n"

        print("=" * 60)
        print("📡 Canlı yayın aktarımı başlatılıyor...")
        print(f"🎯 Kaynak : {stream_target}")
        print(f"🎯 Hedef  : {RTMP_SERVER}")
        print("=" * 60)

        command = [
            'ffmpeg',
            '-headers', headers_arg,
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_delay_max', '5',
            '-i', stream_target,
            '-filter_complex',
            '[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,'
            'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=25[v]',
            '-map', '[v]',
            '-map', '0:a?',
            '-c:v', 'libx264',
            '-preset', 'veryfast',
            '-pix_fmt', 'yuv420p',
            '-r', '25',
            '-b:v', '3500k',
            '-maxrate', '3500k',
            '-bufsize', '4000k',
            '-g', '60',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-ar', '44100',
            '-f', 'flv',
            RTMP_SERVER
        ]

        start_time = time.time()
        stderr_tail = deque(maxlen=40)

        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break
            if line:
                stderr_tail.append(line.rstrip())

        elapsed = time.time() - start_time

        if process.returncode == 0:
            print("ℹ️ FFmpeg normal şekilde sona erdi, tekrar başlatılıyor...")
            consecutive_failures = 0
        else:
            print(f"⚠️ Yayın koptu (Return Code: {process.returncode}).")
            if stderr_tail:
                print("🧾 FFmpeg son log satırları:")
                for tail_line in stderr_tail:
                    print(f"   {tail_line}")
            if elapsed < 20:
                consecutive_failures += 1
            else:
                consecutive_failures = 0

        retry_delay = min(5 * (2 ** consecutive_failures), MAX_RETRY_DELAY_SECONDS) if consecutive_failures else 5
        print(f"⚠️ {retry_delay} saniye sonra tekrar bağlanılıyor...")
        time.sleep(retry_delay)


if __name__ == "__main__":
    start_live_relay()
