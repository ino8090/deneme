#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import time
import os
import re
import io
import json
import threading
import requests
from collections import deque

# ===================== AYARLAR =====================
RTMP_URL = "rtmp://ssh101.bozztv.com:1935/ssh101"
STREAM_KEY = os.getenv("STREAM_KEY") or "maxtv"
RTMP_SERVER = f"{RTMP_URL}/{STREAM_KEY}"

M3U_URL = os.getenv("M3U_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/yerli1.m3u"
LOGO_URL = os.getenv("LOGO_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/file_000000007be48210a068edefa7260629.png"

STATE_FILE_NAME = os.getenv("STATE_FILE_NAME", "maxtv.json")
GITHUB_STEP_SUMMARY = os.getenv("GITHUB_STEP_SUMMARY")

STREAM_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
STREAM_REFERER = "https://vidmody.com/"

# Logo ve yazı opaklık ayarları (0.0 - 1.0 arası)
LOGO_OPACITY = float(os.getenv("LOGO_OPACITY", "0.4"))
TEXT_OPACITY = float(os.getenv("TEXT_OPACITY", "0.5"))
BOLD_FONT_PATH = os.getenv("BOLD_FONT_PATH", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def format_hms(total_seconds):
    """Saniyeyi SS:DD:SS formatına çevirir."""
    total_seconds = int(total_seconds)
    hrs = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def get_local_state():
    """Yerel state dosyasından son durumu okur (indeks, saniye, linkin URL'si, içerik adı)."""
    if os.path.exists(STATE_FILE_NAME):
        if os.path.getsize(STATE_FILE_NAME) == 0:
            print(f"⚠️ Yerel state dosyası boş ({STATE_FILE_NAME}), 0'dan başlanıyor.")
            return 0, 0, "", ""
        try:
            with open(STATE_FILE_NAME, "r", encoding="utf-8") as f:
                data = json.load(f)
                idx = data.get("last_index", 0)
                sec = data.get("last_seconds", 0)
                url = data.get("last_url", "")
                title = data.get("last_title", "")
                print(f"✅ Yerel state okundu ({STATE_FILE_NAME}) => İndeks: {idx}, Saniye: {sec}")
                return idx, sec, url, title
        except Exception as e:
            print(f"⚠️ Yerel state okuma hatası: {e}")
    else:
        print(f"ℹ️ Yerel state dosyası bulunamadı, 0'dan başlanıyor.")
    return 0, 0, "", ""


def update_local_state(index, seconds, url="", title=""):
    """Son konumu (indeks, saniye), linkin URL'sini ve içerik adını yerel state dosyasına kaydeder."""
    try:
        data = {"last_index": int(index), "last_seconds": int(seconds), "last_url": url, "last_title": title}
        with open(STATE_FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 Konum yerel dosyaya kaydedildi => İndeks: {index}, Saniye: {int(seconds)}")
    except Exception as e:
        print(f"⚠️ Yerel state yazma hatası: {e}")


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
    """Şu an oynayan içeriğin adını, drawtext filtresinin okuyacağı dosyaya yazar."""
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


# ===================== KALICI RTMP YAYINCISI =====================
class RtmpPublisher:
    """
    Tek bir kalıcı FFmpeg süreci. MPEG-TS verisini stdin'den alır ve
    RTMP'ye -c copy ile gönderir. Filmler arası geçişte bu süreç ve
    RTMP bağlantısı KAPANMAZ; sadece veri akışı devam eder.
    """

    def __init__(self, rtmp_target):
        self.rtmp_target = rtmp_target
        self.process = None
        self.start_time = 0.0
        self.stderr_tail = deque(maxlen=40)

    def is_alive(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        self.stop()
        command = [
            'ffmpeg', '-hide_banner', '-nostats',
            '-fflags', '+genpts+discardcorrupt',
            '-analyzeduration', '1000000',
            '-probesize', '1000000',
            '-re',
            '-f', 'mpegts', '-i', 'pipe:0',
            '-c', 'copy',
            '-flvflags', 'no_duration_filesize',
            '-f', 'flv',
            self.rtmp_target
        ]
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            bufsize=0
        )
        self.start_time = time.time()
        self.stderr_tail.clear()
        threading.Thread(target=self._drain_stderr, args=(self.process,), daemon=True).start()
        print(f"🔌 Kalıcı RTMP bağlantısı açıldı: {self.rtmp_target}")

    def _drain_stderr(self, proc):
        try:
            for raw in io.TextIOWrapper(proc.stderr, encoding='utf-8', errors='replace'):
                self.stderr_tail.append(raw.rstrip())
        except Exception:
            pass

    def ts_offset(self):
        """Yeni film için zaman damgası ofseti: yayıncı açıldığından beri geçen süre.
        Böylece RTMP tarafında zaman damgaları hiç geri sarmaz/sıfırlanmaz."""
        return max(0.0, time.time() - self.start_time)

    def write(self, data):
        self.process.stdin.write(data)

    def stop(self):
        if self.process is None:
            return
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        self.process = None


def pump_encoder_to_publisher(encoder, publisher, failed_event):
    """Film kodlayıcının stdout'unu kalıcı yayıncıya aktarır. Kodlayıcı bitince
    yayıncının stdin'i KAPATILMAZ."""
    try:
        while True:
            data = encoder.stdout.read(65536)
            if not data:
                break
            publisher.write(data)
    except Exception as e:
        print(f"⚠️ Yayıncıya yazma hatası: {e}")
        failed_event.set()
        try:
            encoder.kill()
        except Exception:
            pass


def start_m3u_stream():
    print(f"🔧 Kullanılan M3U   : {M3U_URL}")
    print(f"🔧 Kullanılan Logo 1: {LOGO_URL}")
    print(f"🔧 State dosyası    : {STATE_FILE_NAME}")
    print(f"🔧 RTMP hedefi      : {RTMP_SERVER}")

    download_logo()

    current_index, last_seconds, last_url, last_title = get_local_state()

    consecutive_fast_failures = 0
    FAST_FAIL_THRESHOLD_SECONDS = 20
    MAX_RETRY_DELAY_SECONDS = 120

    publisher = RtmpPublisher(RTMP_SERVER)

    try:
        while True:
            playlist = get_m3u_playlist(M3U_URL)
            if not playlist:
                time.sleep(10)
                continue

            if current_index >= len(playlist):
                current_index = 0
                last_seconds = 0
                last_url = ""
                last_title = ""

            current_item = playlist[current_index]
            target_stream_url = current_item["url"]
            film_title = current_item["title"]

            # Link değişse bile kaldığı yerden devam; yalnızca film adı değişirse baştan başla
            if last_seconds > 0 and last_title and film_title != last_title:
                print(f"🔄 Bu sıradaki ({current_index + 1}) içeriğin adı değişmiş, video baştan başlatılacak.")
                print(f"   Eski ad: {last_title}")
                print(f"   Yeni ad: {film_title}")
                last_seconds = 0
            elif last_seconds > 0 and last_url and target_stream_url != last_url:
                print(f"🔗 Link değişmiş ama içerik adı aynı, {last_seconds} sn'den devam edilecek.")

            last_url = target_stream_url
            last_title = film_title

            write_title_file(film_title)

            print("=" * 60)
            print("📺 Maxanimasyon Canlı Aktarım Yayını (1080p 25fps - 2500k) Başlatılıyor")
            print(f"🎬 Oynatılan İçerik  : {film_title}")
            print(f"⏱️ Başlangıç Saniyesi: {last_seconds}")
            print(f"🚀 Hedef RTMP       : {RTMP_SERVER}")

            headers_arg = (
                f"User-Agent: {STREAM_USER_AGENT}\r\n"
                f"Referer: https://vidmody.com/\r\n"
                f"Origin: https://vidmody.com\r\n"
            )

            # FFmpeg kilitlenmesini engelleyen hızlı bağlantı ve atlama ayarları
            input_options = [
                '-headers', headers_arg,
                '-protocol_whitelist', 'file,http,https,tcp,tls,crypto',
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
                video_url = video_url.strip()
                audio_url = audio_url.strip()

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

            # Kalıcı RTMP yayıncısı kapalıysa (ilk açılış ya da kopma) yeniden aç
            if not publisher.is_alive():
                publisher.start()

            ts_offset = publisher.ts_offset()

            # Kodlayıcı: RTMP'ye DEĞİL, stdout'a MPEG-TS yazar (pipe:1)
            command = [
                'ffmpeg', '-nostdin'
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
                '-output_ts_offset', f'{ts_offset:.3f}',
                '-mpegts_flags', '+resend_headers',
                '-f', 'mpegts',
                'pipe:1'
            ]

            print("▶ FFmpeg başlatıldı, 1080p 25fps @ 2500k yayın kalıcı RTMP bağlantısına iletiliyor...")

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )

            publisher_failed = threading.Event()
            pump_thread = threading.Thread(
                target=pump_encoder_to_publisher,
                args=(process, publisher, publisher_failed),
                daemon=True
            )
            pump_thread.start()

            last_save_time = time.time()
            last_dashboard_time = time.time()
            current_stream_seconds = last_seconds
            stderr_tail = deque(maxlen=40)
            first_time_value = None

            # \r ile biten ilerleme satırlarını da satır olarak okumak için
            stderr_text = io.TextIOWrapper(process.stderr, encoding='utf-8', errors='replace')

            while True:
                line = stderr_text.readline()
                if not line and process.poll() is not None:
                    break
                if not line:
                    continue

                stderr_tail.append(line.rstrip())

                if "time=" in line:
                    time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                    if time_match:
                        hrs, mins, secs = time_match.groups()
                        t_val = int(hrs) * 3600 + int(mins) * 60 + float(secs)
                        # output_ts_offset time= değerine yansıyabilir; ilk değeri baz alıp farkı kullan
                        if first_time_value is None:
                            first_time_value = t_val
                        played_seconds = max(0.0, t_val - first_time_value)
                        current_stream_seconds = last_seconds + played_seconds

                        now = time.time()

                        if now - last_save_time > 30:
                            update_local_state(current_index, current_stream_seconds, target_stream_url, film_title)
                            last_save_time = now

                        if now - last_dashboard_time > 30:
                            print_dashboard(film_title, current_index, len(playlist), current_stream_seconds)
                            write_step_summary(film_title, current_index, len(playlist), current_stream_seconds)
                            last_dashboard_time = now

            process.wait()
            pump_thread.join(timeout=10)

            if publisher_failed.is_set() or not publisher.is_alive():
                print("⚠️ Kalıcı RTMP bağlantısı koptu, yeniden açılacak.")
                if publisher.stderr_tail:
                    print("🧾 RTMP yayıncı son log satırları:")
                    for tail_line in publisher.stderr_tail:
                        print(f"   {tail_line}")
                publisher.stop()
                write_step_summary(film_title, current_index, len(playlist), current_stream_seconds, status="🔴 RTMP koptu, tekrar bağlanılacak")
                consecutive_fast_failures += 1
                last_seconds = current_stream_seconds
                update_local_state(current_index, last_seconds, target_stream_url, film_title)
                retry_delay = min(5 * (2 ** consecutive_fast_failures), MAX_RETRY_DELAY_SECONDS)
                print(f"⚠️ {retry_delay} saniye sonra tekrar bağlanılıyor...")
                time.sleep(retry_delay)
                continue

            if process.returncode == 0:
                print("✅ İçerik bitti, sıradakine geçiliyor (RTMP bağlantısı açık kalıyor).")
                write_step_summary(film_title, current_index, len(playlist), current_stream_seconds, status="✅ Bitti, sıradakine geçiliyor")
                current_index += 1
                last_seconds = 0
                last_url = ""
                last_title = ""
                update_local_state(current_index, 0, "", "")
                consecutive_fast_failures = 0
                # Başarılı geçişte bekleme yok: bağlantı açık, hemen sıradaki film
                continue
            else:
                print(f"⚠️ Kaynak akışı koptu (Return Code: {process.returncode}). Aynı saniyeden tekrar denenecek.")
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
                last_title = film_title
                update_local_state(current_index, last_seconds, last_url, last_title)

            if consecutive_fast_failures > 0:
                retry_delay = min(5 * (2 ** consecutive_fast_failures), MAX_RETRY_DELAY_SECONDS)
            else:
                retry_delay = 5

            print(f"⚠️ {retry_delay} saniye sonra tekrar bağlanılıyor...")
            time.sleep(retry_delay)
    finally:
        publisher.stop()


if __name__ == "__main__":
    start_m3u_stream()
