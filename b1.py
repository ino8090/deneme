#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import time
import os
from collections import deque

# ===================== AYARLAR =====================
RTMP_URL = "rtmp://ssh101.bozztv.com:1935/ssh101"
STREAM_KEY = os.getenv("STREAM_KEY") or "b1"
RTMP_SERVER = f"{RTMP_URL}/{STREAM_KEY}"

# Canlı HLS (m3u8) kaynağı
STREAM_URL = os.getenv("STREAM_URL") or "https://cdn.codenet.work/live/streamgo/stremgo123/4864.m3u8"

STREAM_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

MAX_RETRY_DELAY_SECONDS = 60


def start_live_relay():
    print(f"🔧 Kaynak (m3u8)    : {STREAM_URL}")
    print(f"🔧 RTMP hedefi      : {RTMP_SERVER}")

    consecutive_failures = 0
    headers_arg = f"User-Agent: {STREAM_USER_AGENT}\r\n"

    while True:
        print("=" * 60)
        print("📡 Canlı yayın aktarımı başlatılıyor...")
        print(f"🎯 Kaynak : {STREAM_URL}")
        print(f"🎯 Hedef  : {RTMP_SERVER}")
        print("=" * 60)

        command = [
            'ffmpeg',
            '-headers', headers_arg,
            '-reconnect', '1',
            '-reconnect_streamed', '1',
            '-reconnect_delay_max', '5',
            '-i', STREAM_URL,
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
