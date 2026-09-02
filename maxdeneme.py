#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import time
import os
import re
import json
import signal
import requests

# ===================== AYARLAR =====================
RTMP_URL = "rtmp://ssh101.bozztv.com:1935/ssh101"
STREAM_KEY = os.getenv("STREAM_KEY") or "fixtv"
RTMP_SERVER = f"{RTMP_URL}/{STREAM_KEY}"

M3U_URL = os.getenv("M3U_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/yerli.m3u"
LOGO_URL = os.getenv("LOGO_URL") or "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/1788318046234.png"

STATE_FILE_NAME = os.getenv("STATE_FILE_NAME", "state_fixtv.json")
GITHUB_STEP_SUMMARY = os.getenv("GITHUB_STEP_SUMMARY")

# Yaş sınırı (rating) ikonları: m3u'daki tvg-rating değeri ile eşleşen görsel URL'leri.
# Kendi ikonlarını hazırlayıp GitHub'a yükledikten sonra bu linkleri güncelle,
# ya da GitHub Actions'ta env olarak RATING_ICON_7 / RATING_ICON_13 vb. tanımla.
RATING_ICON_URLS = {
    "+7":  os.getenv("RATING_ICON_7",  "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/rating_7.png"),
    "+13": os.getenv("RATING_ICON_13", "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/rating_13.png"),
    "+16": os.getenv("RATING_ICON_16", "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/rating_16.png"),
    "+18": os.getenv("RATING_ICON_18", "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/rating_18.png"),
}
RATING_ICON_DIR = "rating_icons"

STREAM_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Sinyal yakalayıcının kullanacağı anlık konum bilgisi (global)
_current_index = 0
_current_seconds = 0


def format_hms(total_seconds):
    """Saniyeyi SS:DD:SS formatına çevirir."""
    total_seconds = int(total_seconds)
    hrs = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


def sanitize_text_for_ffmpeg(text):
    """FFmpeg drawtext filtresinde hata vermemesi için özel karakterleri kaçırır."""
    if not text:
        return ""
    text = text.replace('\\', '\\\\')
    text = text.replace("'", "'\\\\''")
    text = text.replace(':', '\\:')
    text = text.replace('%', '\\%')
    return text


def get_local_state():
    """Yerel state_fixtv.json dosyasından son durumu okur."""
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
    """Son konumu yerel state_fixtv.json dosyasına kaydeder."""
    try:
        data = {"last_index": int(index), "last_seconds": int(seconds)}
        with open(STATE_FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 Konum yerel dosyaya kaydedildi => İndeks: {index}, Saniye: {int(seconds)}")
    except Exception as e:
        print(f"⚠️ Yerel state yazma hatası: {e}")


def handle_exit(signum, frame):
    """Workflow iptal edildiğinde (SIGINT/SIGTERM) anlık konumu acilen kaydeder."""
    print(f"\n⚠️ İptal/sonlandırma sinyali alındı ({signum}). "
          f"Son konum kaydediliyor => İndeks: {_current_index}, Saniye: {int(_current_seconds)}")
    update_local_state(_current_index, _current_seconds)
    sys.exit(0)


signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


def get_m3u_playlist(m3u_url):
    try:
        headers = {'User-Agent': STREAM_USER_AGENT}
        response = requests.get(m3u_url, headers=headers, timeout=15)
        if response.status_code == 200:
            lines = response.text.splitlines()
            playlist = []
            pending_title = None
            pending_rating = None
            for raw_line in lines:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith('#EXTINF'):
                    match = re.search(r',(.+)$', line)
                    pending_title = match.group(1).strip() if match else None
                    rating_match = re.search(r'tvg-rating="([^"]*)"', line)
                    pending_rating = rating_match.group(1).strip() if rating_match else None
                elif not line.startswith('#') and line.startswith('http'):
                    title = pending_title or os.path.basename(line.split('?')[0])
                    playlist.append({"url": line, "title": title, "rating": pending_rating})
                    pending_title = None
                    pending_rating = None
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
            print("✅ Logo başarıyla indirildi.")
    except Exception as e:
        print(f"⚠️ Logo indirme hatası: {e}")


def download_rating_icons():
    """Her yaş sınırı ikonunu bir kez indirir (rating_icons/ klasörüne)."""
    os.makedirs(RATING_ICON_DIR, exist_ok=True)
    headers = {'User-Agent': STREAM_USER_AGENT}
    for rating, url in RATING_ICON_URLS.items():
        filename = os.path.join(RATING_ICON_DIR, f"{rating.replace('+', '')}.png")
        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            continue
        try:
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 200 and len(response.content) > 0:
                with open(filename, 'wb') as f:
                    f.write(response.content)
                print(f"✅ {rating} ikonu indirildi.")
            else:
                print(f"⚠️ {rating} ikonu indirilemedi (HTTP {response.status_code}).")
        except Exception as e:
            print(f"⚠️ {rating} ikonu indirme hatası: {e}")


def get_rating_icon_path(rating):
    """Verilen rating değeri için lokal ikon dosya yolunu döndürür (yoksa None)."""
    if not rating:
        return None
    filename = os.path.join(RATING_ICON_DIR, f"{rating.replace('+', '')}.png")
    if os.path.exists(filename) and os.path.getsize(filename) > 0:
        return filename
    return None


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
            "## 📺 Canlı Yayın Durumu (FixTV)\n\n"
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
    global _current_index, _current_seconds

    print(f"🔧 Kullanılan M3U   : {M3U_URL}")
    print(f"🔧 Kullanılan Logo  : {LOGO_URL}")
    print(f"🔧 State dosyası    : {STATE_FILE_NAME}")
    print(f"🔧 RTMP hedefi      : {RTMP_SERVER}")

    download_logo()
    download_rating_icons()

    current_index, last_seconds = get_local_state()
    _current_index, _current_seconds = current_index, last_seconds

    while True:
        playlist = get_m3u_playlist(M3U_URL)
        if not playlist:
            time.sleep(10)
            continue

        if current_index >= len(playlist):
            current_index = 0
            last_seconds = 0

        _current_index = current_index
        _current_seconds = last_seconds

        current_item = playlist[current_index]
        target_stream_url = current_item["url"]
        film_title = current_item["title"]

        print("=" * 60)
        print("📺 FixTV Canlı Aktarım Yayını (1080p 30fps - 2000k) Başlatılıyor")
        print(f"🎬 Oynatılan İçerik  : {film_title}")
        print(f"⏱️ Başlangıç Saniyesi: {last_seconds}")
        print(f"🚀 Hedef RTMP       : {RTMP_SERVER}")

        headers_arg = f"User-Agent: {STREAM_USER_AGENT}\r\n"

        if ";" in target_stream_url:
            video_url, audio_url = target_stream_url.split(";", 1)
            video_url = video_url.strip()
            audio_url = audio_url.strip()

            print(f"🎥 Video Bağlantısı : {video_url}")
            print(f"🔊 Ses Bağlantısı   : {audio_url}")

            input_args = [
                '-headers', headers_arg,
                '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
                '-ss', str(last_seconds),
                '-re',
                '-i', video_url,
                '-headers', headers_arg,
                '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
                '-ss', str(last_seconds),
                '-re',
                '-i', audio_url
            ]
            audio_map = ['-map', '1:a:0']
            base_input_count = 2
        else:
            print(f"📡 Kaynak Yayın     : {target_stream_url}")
            input_args = [
                '-headers', headers_arg,
                '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
                '-ss', str(last_seconds),
                '-re',
                '-i', target_stream_url
            ]
            audio_map = ['-map', '0:a:0?']
            base_input_count = 1

        print("=" * 60)

        print_dashboard(film_title, current_index, len(playlist), last_seconds, status="🟡 Başlatılıyor")
        write_step_summary(film_title, current_index, len(playlist), last_seconds, status="🟡 Başlatılıyor")

        has_logo = os.path.exists('logo.png') and os.path.getsize('logo.png') > 0

        film_rating = current_item.get("rating")
        rating_icon_path = get_rating_icon_path(film_rating)
        has_rating_icon = rating_icon_path is not None
        if film_rating and not has_rating_icon:
            print(f"⚠️ '{film_rating}' için ikon bulunamadı, rozet gösterilmeyecek.")
        elif has_rating_icon:
            print(f"🔞 Yaş sınırı rozeti uygulanıyor: {film_rating}")

        safe_title = sanitize_text_for_ffmpeg(film_title)

        # --- YAZI, LOGO VE ROZET STİL AYARLARI ---
        text_color = "white@0.5"
        logo_alpha = "0.5"          # <--- LOGO OPAKLIĞI (0.0 - 1.0 arası)
        rating_icon_alpha = "1.0"   # <--- ROZET OPAKLIĞI (0.0 - 1.0 arası, 1.0 = tam opak)
        rating_icon_height = 90     # <--- YAŞ SINIRI ROZETİNİN YÜKSEKLİĞİ (piksel)
        rating_icon_x = 40          # <--- ROZETİN SOLDAN UZAKLIĞI
        rating_icon_y = 40          # <--- ROZETİN YUKARIDAN UZAKLIĞI

        # Ubuntu sunucularında varsayılan bulunan kalın ve temiz yazı tipi yolu:
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

        if os.path.exists(font_path):
            drawtext_filter = (
                f"drawtext=fontfile='{font_path}':text='{safe_title}':x=103:y=h-94:fontsize=33:"
                f"fontcolor={text_color}[v]"
            )
        else:
            drawtext_filter = (
                f"drawtext=text='{safe_title}':x=103:y=h-94:fontsize=33:"
                f"fontcolor={text_color}[v]"
            )

        # Ekstra girişleri (logo, yaş sınırı rozeti) sırayla ekle ve index'lerini hesapla
        extra_inputs = []
        next_index = base_input_count
        logo_input_index = None
        rating_input_index = None

        if has_logo:
            extra_inputs += ['-i', 'logo.png']
            logo_input_index = next_index
            next_index += 1

        if has_rating_icon:
            extra_inputs += ['-i', rating_icon_path]
            rating_input_index = next_index
            next_index += 1

        filters = [
            '[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,'
            'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=30[main]'
        ]
        last_label = 'main'

        if has_logo:
            filters.append(
                f'[{logo_input_index}:v]scale=-2:102,format=rgba,colorchannelmixer=aa={logo_alpha}[logo]'
            )
            filters.append(f'[{last_label}][logo]overlay=main_w-overlay_w-129:90[afterlogo]')
            last_label = 'afterlogo'

        if has_rating_icon:
            filters.append(
                f'[{rating_input_index}:v]scale=-2:{rating_icon_height},format=rgba,'
                f'colorchannelmixer=aa={rating_icon_alpha}[ratingicon]'
            )
            filters.append(
                f'[{last_label}][ratingicon]overlay={rating_icon_x}:{rating_icon_y}[afterrating]'
            )
            last_label = 'afterrating'

        filters.append(f'[{last_label}]{drawtext_filter}')
        filter_str = ';'.join(filters)
        logo_inputs = extra_inputs

        command = [
            'ffmpeg'
        ] + input_args + logo_inputs + [
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

        print("▶ FFmpeg başlatıldı, 1080p 30fps @ 2000k yayın iletiliyor...")

        process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        last_save_time = time.time()
        last_dashboard_time = time.time()
        current_stream_seconds = last_seconds

        stderr_tail = []  # Hata anında göstermek için son satırları biriktirir

        while True:
            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break

            if line:
                stderr_tail.append(line)
                if len(stderr_tail) > 40:
                    stderr_tail.pop(0)

            if "time=" in line:
                time_match = re.search(r'time=(\d+):(\d+):(\d+\.\d+)', line)
                if time_match:
                    hrs, mins, secs = time_match.groups()
                    played_seconds = int(hrs) * 3600 + int(mins) * 60 + float(secs)
                    current_stream_seconds = last_seconds + played_seconds

                    # Sinyal yakalayıcının kullanacağı anlık konumu güncelle
                    _current_index = current_index
                    _current_seconds = current_stream_seconds

                    now = time.time()

                    # Kaydetme sıklığı 30 sn'den 3 sn'ye düşürüldü
                    if now - last_save_time > 3:
                        update_local_state(current_index, current_stream_seconds)
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
            _current_index = current_index
            _current_seconds = 0
            update_local_state(current_index, 0)
        else:
            print(f"⚠️ Yayın koptu (Return Code: {process.returncode}). Aynı saniyeden tekrar denenecek.")
            print("----- FFmpeg son çıktısı (debug) -----")
            print("".join(stderr_tail))
            print("---------------------------------------")
            write_step_summary(film_title, current_index, len(playlist), current_stream_seconds, status="🔴 Bağlantı koptu, tekrar denenecek")
            last_seconds = current_stream_seconds
            _current_index = current_index
            _current_seconds = last_seconds
            update_local_state(current_index, last_seconds)

        print("⚠️ 5 saniye sonra tekrar bağlanılıyor...")
        time.sleep(5)


if __name__ == "__main__":
    start_m3u_stream()
