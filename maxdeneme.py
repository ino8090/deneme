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

M3U_URL = os.getenv("M3U_URL") or \
    "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/yerli.m3u"

LOGO_URL = os.getenv("LOGO_URL") or \
    "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/1788318046234.png"

STATE_FILE_NAME = os.getenv(
    "STATE_FILE_NAME",
    "state_fixtv.json"
)

GITHUB_STEP_SUMMARY = os.getenv("GITHUB_STEP_SUMMARY")

# ===================== YAŞ SINIRI İKONLARI =====================

RATING_ICON_URLS = {
    "+7": os.getenv(
        "RATING_ICON_7",
        "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/rating_7.png"
    ),
    "+13": os.getenv(
        "RATING_ICON_13",
        "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/rating_13.png"
    ),
    "+16": os.getenv(
        "RATING_ICON_16",
        "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/rating_16.png"
    ),
    "+18": os.getenv(
        "RATING_ICON_18",
        "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/rating_18.png"
    ),
}

RATING_ICON_DIR = "rating_icons"

STREAM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# ===================== ANLIK STATE =====================

_current_index = 0
_current_seconds = 0
_current_url = ""


# =========================================================
# ZAMAN FORMAT
# =========================================================

def format_hms(total_seconds):
    total_seconds = int(total_seconds)

    hrs = total_seconds // 3600
    mins = (total_seconds % 3600) // 60
    secs = total_seconds % 60

    return f"{hrs:02d}:{mins:02d}:{secs:02d}"


# =========================================================
# FFMPEG DRAWText KAÇIŞ
# =========================================================

def sanitize_text_for_ffmpeg(text):

    if not text:
        return ""

    text = text.replace("\\", "\\\\")
    text = text.replace("'", "'\\\\''")
    text = text.replace(":", "\\:")
    text = text.replace("%", "\\%")

    return text


# =========================================================
# STATE OKU
# =========================================================

def get_local_state():

    if os.path.exists(STATE_FILE_NAME):

        try:

            with open(
                STATE_FILE_NAME,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            idx = data.get("last_index", 0)
            sec = data.get("last_seconds", 0)
            url = data.get("last_url", "")

            print(
                f"✅ State okundu => "
                f"İndeks: {idx}, "
                f"Saniye: {sec}, "
                f"URL: {url[:40]}..."
            )

            return idx, sec, url

        except Exception as e:

            print(f"⚠️ State okuma hatası: {e}")

    else:

        print(
            f"ℹ️ {STATE_FILE_NAME} bulunamadı. "
            f"0'dan başlanıyor."
        )

    return 0, 0, ""


# =========================================================
# STATE KAYDET
# =========================================================

def update_local_state(index, seconds, url=""):

    try:

        data = {
            "last_index": int(index),
            "last_seconds": int(seconds),
            "last_url": url
        }

        with open(
            STATE_FILE_NAME,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                ensure_ascii=False,
                indent=2
            )

        print(
            f"💾 State kaydedildi => "
            f"İndeks: {index}, "
            f"Saniye: {int(seconds)}"
        )

    except Exception as e:

        print(f"⚠️ State yazma hatası: {e}")


# =========================================================
# SİNYAL YAKALAMA
# =========================================================

def handle_exit(signum, frame):

    global _current_index
    global _current_seconds
    global _current_url

    print(
        f"\n⚠️ Sonlandırma sinyali alındı ({signum})."
    )

    print(
        f"💾 Son konum kaydediliyor => "
        f"İndeks: {_current_index}, "
        f"Saniye: {int(_current_seconds)}"
    )

    update_local_state(
        _current_index,
        _current_seconds,
        _current_url
    )

    sys.exit(0)


signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


# =========================================================
# M3U OKU
# =========================================================

def get_m3u_playlist(m3u_url):

    try:

        headers = {
            "User-Agent": STREAM_USER_AGENT
        }

        response = requests.get(
            m3u_url,
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:

            print(
                f"⚠️ M3U HTTP hatası: "
                f"{response.status_code}"
            )

            return []

        lines = response.text.splitlines()

        playlist = []

        pending_title = None
        pending_rating = None

        for raw_line in lines:

            line = raw_line.strip()

            if not line:
                continue

            # ---------------------------------------------
            # EXTINF
            # ---------------------------------------------

            if line.startswith("#EXTINF"):

                match = re.search(
                    r",(.+)$",
                    line
                )

                pending_title = (
                    match.group(1).strip()
                    if match
                    else None
                )

                rating_match = re.search(
                    r'tvg-rating="([^"]*)"',
                    line
                )

                pending_rating = (
                    rating_match.group(1).strip()
                    if rating_match
                    else None
                )

            # ---------------------------------------------
            # URL
            # ---------------------------------------------

            elif (
                not line.startswith("#")
                and line.startswith("http")
            ):

                title = (
                    pending_title
                    or os.path.basename(
                        line.split("?")[0]
                    )
                )

                playlist.append({
                    "url": line,
                    "title": title,
                    "rating": pending_rating
                })

                pending_title = None
                pending_rating = None

        print(
            f"✅ M3U okundu: "
            f"{len(playlist)} içerik"
        )

        return playlist

    except Exception as e:

        print(
            f"⚠️ M3U çekme hatası: {e}"
        )

        return []


# =========================================================
# LOGO İNDİR
# =========================================================

def download_logo():

    headers = {
        "User-Agent": STREAM_USER_AGENT
    }

    try:

        response = requests.get(
            LOGO_URL,
            headers=headers,
            timeout=15
        )

        if (
            response.status_code == 200
            and len(response.content) > 0
        ):

            with open(
                "logo.png",
                "wb"
            ) as f:

                f.write(response.content)

            print("✅ Logo indirildi.")

        else:

            print(
                "⚠️ Logo indirilemedi."
            )

    except Exception as e:

        print(
            f"⚠️ Logo indirme hatası: {e}"
        )


# =========================================================
# RATING İKONLARINI İNDİR
# =========================================================

def download_rating_icons():

    os.makedirs(
        RATING_ICON_DIR,
        exist_ok=True
    )

    headers = {
        "User-Agent": STREAM_USER_AGENT
    }

    for rating, url in RATING_ICON_URLS.items():

        filename = os.path.join(
            RATING_ICON_DIR,
            f"{rating.replace('+', '')}.png"
        )

        if (
            os.path.exists(filename)
            and os.path.getsize(filename) > 0
        ):
            continue

        try:

            response = requests.get(
                url,
                headers=headers,
                timeout=15
            )

            if (
                response.status_code == 200
                and len(response.content) > 0
            ):

                with open(
                    filename,
                    "wb"
                ) as f:

                    f.write(response.content)

                print(
                    f"✅ {rating} ikonu indirildi."
                )

        except Exception as e:

            print(
                f"⚠️ {rating} ikonu hatası: {e}"
            )


# =========================================================
# RATING PATH
# =========================================================

def get_rating_icon_path(rating):

    if not rating:
        return None

    filename = os.path.join(
        RATING_ICON_DIR,
        f"{rating.replace('+', '')}.png"
    )

    if (
        os.path.exists(filename)
        and os.path.getsize(filename) > 0
    ):

        return filename

    return None


# =========================================================
# DASHBOARD
# =========================================================

def print_dashboard(
    title,
    index,
    playlist_len,
    seconds,
    status="🟢 Yayında"
):

    print(
        "┌" + "─" * 58 + "┐"
    )

    print(
        f"│ 🎬 İçerik         : "
        f"{title[:36]:<36} │"
    )

    print(
        f"│ 🔢 Sıra           : "
        f"{index + 1}/{playlist_len:<32} │"
    )

    print(
        f"│ ⏱️  Geçen Süre     : "
        f"{format_hms(seconds):<36} │"
    )

    print(
        f"│ 📡 Durum          : "
        f"{status:<36} │"
    )

    print(
        "└" + "─" * 58 + "┘"
    )


# =========================================================
# GITHUB SUMMARY
# =========================================================

def write_step_summary(
    title,
    index,
    playlist_len,
    seconds,
    status="🟢 Yayında"
):

    if not GITHUB_STEP_SUMMARY:
        return

    try:

        content = (
            "## 📺 Canlı Yayın Durumu (FixTV)\n\n"
            "| Alan | Değer |\n"
            "|---|---|\n"
            f"| 🎬 İçerik | {title} |\n"
            f"| 🔢 Playlist sırası | "
            f"{index + 1} / {playlist_len} |\n"
            f"| ⏱️ Geçen süre | "
            f"{format_hms(seconds)} |\n"
            f"| 📡 Durum | {status} |\n"
            f"| 🕒 Güncelleme | "
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} |\n"
        )

        with open(
            GITHUB_STEP_SUMMARY,
            "w",
            encoding="utf-8"
        ) as f:

            f.write(content)

    except Exception as e:

        print(
            f"⚠️ Summary yazma hatası: {e}"
        )


# =========================================================
# ANA YAYIN SİSTEMİ
# =========================================================

def start_m3u_stream():

    global _current_index
    global _current_seconds
    global _current_url

    print("=" * 60)
    print("📺 FixTV Yayın Sistemi")
    print("=" * 60)

    print(
        f"🔧 M3U    : {M3U_URL}"
    )

    print(
        f"🔧 Logo   : {LOGO_URL}"
    )

    print(
        f"🔧 State  : {STATE_FILE_NAME}"
    )

    print(
        f"🔧 RTMP   : {RTMP_SERVER}"
    )

    print("=" * 60)

    download_logo()
    download_rating_icons()

    current_index, last_seconds, last_url = \
        get_local_state()

    while True:

        # -------------------------------------------------
        # M3U YENİDEN OKU
        # -------------------------------------------------

        playlist = get_m3u_playlist(
            M3U_URL
        )

        if not playlist:

            print(
                "⚠️ Playlist boş. "
                "10 saniye sonra tekrar denenecek."
            )

            time.sleep(10)
            continue

        # -------------------------------------------------
        # LİSTE SONUNA GELDİYSE
        # -------------------------------------------------

        if current_index >= len(playlist):

            current_index = 0
            last_seconds = 0
            last_url = ""

        # -------------------------------------------------
        # AKTİF İÇERİK
        # -------------------------------------------------

        current_item = playlist[
            current_index
        ]

        target_stream_url = current_item[
            "url"
        ]

        film_title = current_item[
            "title"
        ]

        # -------------------------------------------------
        # URL DEĞİŞMİŞ Mİ?
        # -------------------------------------------------

        if (
            last_url
            and target_stream_url != last_url
        ):

            print(
                "\n🔄 Kaynak URL değişmiş."
            )

            print(
                f"Eski: {last_url[:60]}..."
            )

            print(
                f"Yeni: {target_stream_url[:60]}..."
            )

            print(
                "⏱️ Başlangıç zamanı 0'a "
                "çekiliyor."
            )

            last_seconds = 0

        last_url = target_stream_url

        _current_index = current_index
        _current_seconds = last_seconds
        _current_url = target_stream_url

        print("=" * 60)

        print(
            "📺 FixTV Canlı Aktarım"
        )

        print(
            "🎥 1080p / 25 FPS / 2000 kbps"
        )

        print(
            f"🎬 İçerik: {film_title}"
        )

        print(
            f"⏱️ Başlangıç: "
            f"{format_hms(last_seconds)}"
        )

        print(
            f"🚀 RTMP: {RTMP_SERVER}"
        )

        # =================================================
        # URL AYIRMA
        # =================================================

        headers_arg = (
            f"User-Agent: "
            f"{STREAM_USER_AGENT}\r\n"
        )

        if ";" in target_stream_url:

            video_url, audio_url = \
                target_stream_url.split(
                    ";",
                    1
                )

            video_url = video_url.strip()
            audio_url = audio_url.strip()

            print(
                "🔀 ÇİFT KAYNAK ALGILANDI"
            )

            print(
                f"🎥 Video: "
                f"{video_url[:100]}..."
            )

            print(
                f"🔊 Ses  : "
                f"{audio_url[:100]}..."
            )

            # =================================================
            # ÇİFT KAYNAK
            #
            # Video = 0
            # Ses   = 1
            #
            # İKİSİ DE AYNI last_seconds'TAN BAŞLIYOR
            # =================================================

            input_args = [

                "-ss",
                str(last_seconds),

                "-re",

                "-headers",
                headers_arg,

                "-reconnect",
                "1",

                "-reconnect_streamed",
                "1",

                "-reconnect_delay_max",
                "5",

                "-i",
                video_url,

                "-ss",
                str(last_seconds),

                "-re",

                "-headers",
                headers_arg,

                "-reconnect",
                "1",

                "-reconnect_streamed",
                "1",

                "-reconnect_delay_max",
                "5",

                "-i",
                audio_url
            ]

            audio_map = [
                "-map",
                "1:a:0?"
            ]

            base_input_count = 2

        else:

            print(
                "📡 TEK KAYNAK ALGILANDI"
            )

            print(
                f"📡 Kaynak: "
                f"{target_stream_url[:100]}..."
            )

            input_args = [

                "-ss",
                str(last_seconds),

                "-re",

                "-headers",
                headers_arg,

                "-reconnect",
                "1",

                "-reconnect_streamed",
                "1",

                "-reconnect_delay_max",
                "5",

                "-i",
                target_stream_url
            ]

            audio_map = [
                "-map",
                "0:a:0?"
            ]

            base_input_count = 1

        # =================================================
        # ASSETLER
        # =================================================

        has_logo = (
            os.path.exists("logo.png")
            and os.path.getsize("logo.png") > 0
        )

        film_rating = current_item.get(
            "rating"
        )

        rating_icon_path = \
            get_rating_icon_path(
                film_rating
            )

        has_rating_icon = (
            rating_icon_path is not None
        )

        safe_title = \
            sanitize_text_for_ffmpeg(
                film_title
            )

        # =================================================
        # VIDEO FILTER
        # =================================================

        filters = [

            "[0:v]"
            "scale=1920:1080:"
            "force_original_aspect_ratio=decrease,"
            "pad=1920:1080:"
            "(ow-iw)/2:"
            "(oh-ih)/2:black,"
            "fps=25"
            "[main]"
        ]

        last_label = "main"

        next_input_index = base_input_count

        # =================================================
        # LOGO
        # =================================================

        if has_logo:

            logo_input_index = \
                next_input_index

            next_input_index += 1

            filters.append(
                f"[{logo_input_index}:v]"
                "scale=-2:102,"
                "format=rgba,"
                "colorchannelmixer=aa=0.5"
                "[logo]"
            )

            filters.append(
                f"[{last_label}]"
                "[logo]"
                "overlay="
                "main_w-overlay_w-129:82"
                "[afterlogo]"
            )

            last_label = "afterlogo"

        # =================================================
        # RATING ICON
        # =================================================

        if has_rating_icon:

            rating_input_index = \
                next_input_index

            next_input_index += 1

            filters.append(
                f"[{rating_input_index}:v]"
                "scale=-2:90,"
                "format=rgba,"
                "colorchannelmixer=aa=1.0"
                "[ratingicon]"
            )

            filters.append(
                f"[{last_label}]"
                "[ratingicon]"
                "overlay=40:40"
                "[afterrating]"
            )

            last_label = "afterrating"

        # =================================================
        # YAZI
        # =================================================

        font_path = (
            "/usr/share/fonts/truetype/"
            "dejavu/"
            "DejaVuSans-Bold.ttf"
        )

        if os.path.exists(font_path):

            drawtext = (
                f"drawtext="
                f"fontfile='{font_path}':"
                f"text='{safe_title}':"
                f"x=100:"
                f"y=h-91:"
                f"fontsize=30:"
                f"fontcolor=white@0.5"
            )

        else:

            drawtext = (
                f"drawtext="
                f"text='{safe_title}':"
                f"x=100:"
                f"y=h-91:"
                f"fontsize=30:"
                f"fontcolor=white@0.5"
            )

        filters.append(
            f"[{last_label}]"
            f"{drawtext}"
            "[v]"
        )

        filter_str = ";".join(
            filters
        )

        # =================================================
        # EXTRA INPUTLAR
        # =================================================

        extra_inputs = []

        next_input_index = base_input_count

        if has_logo:

            extra_inputs.extend([
                "-i",
                "logo.png"
            ])

            next_input_index += 1

        if has_rating_icon:

            extra_inputs.extend([
                "-i",
                rating_icon_path
            ])

        # =================================================
        # FFMPEG KOMUTU
        # =================================================

        command = [

            "ffmpeg",

            "-hide_banner",

            "-loglevel",
            "info"

        ] + input_args + extra_inputs + [

            # ---------------------------------------------
            # VIDEO FILTER
            # ---------------------------------------------

            "-filter_complex",
            filter_str,

            # ---------------------------------------------
            # VIDEO
            # ---------------------------------------------

            "-map",
            "[v]"

        ] + audio_map + [

            # =================================================
            # SES SENKRONU
            # =================================================
            #
            # Kaynaktaki sesin görüntünün arkasında
            # kalmasını azaltmak için:
            #
            # - async=1
            # - first_pts=0
            #
            # kullanıyoruz.
            #
            # 1000 gibi agresif bir async değeri
            # kullanılmıyor.
            # =================================================

            "-af",
            "aresample=async=1:first_pts=0",

            # ---------------------------------------------
            # VIDEO CODEC
            # ---------------------------------------------

            "-c:v",
            "libx264",

            "-preset",
            "veryfast",

            "-pix_fmt",
            "yuv420p",

            "-r",
            "25",

            "-b:v",
            "2000k",

            "-maxrate",
            "2000k",

            "-bufsize",
            "4000k",

            "-g",
            "50",

            # ---------------------------------------------
            # AUDIO CODEC
            # ---------------------------------------------

            "-c:a",
            "aac",

            "-b:a",
            "128k",

            "-ar",
            "44100",

            "-ac",
            "2",

            # ---------------------------------------------
            # TIMESTAMP
            # ---------------------------------------------

            "-fflags",
            "+genpts+discardcorrupt",

            "-avoid_negative_ts",
            "make_zero",

            # ---------------------------------------------
            # FLV / RTMP
            # ---------------------------------------------

            "-f",
            "flv",

            RTMP_SERVER
        ]

        print("=" * 60)

        print(
            "▶ FFmpeg başlatılıyor..."
        )

        print(
            "🎥 Video + 🔊 Ses "
            "aynı başlangıç noktasından açılıyor."
        )

        print(
            "⏱️ Başlangıç: "
            f"{format_hms(last_seconds)}"
        )

        print("=" * 60)

        # =================================================
        # FFMPEG BAŞLAT
        # =================================================

        process = subprocess.Popen(

            command,

            stderr=subprocess.PIPE,

            universal_newlines=True,

            bufsize=1
        )

        last_save_time = time.time()
        last_dashboard_time = time.time()

        current_stream_seconds = \
            last_seconds

        stderr_tail = []

        # =================================================
        # FFMPEG LOG
        # =================================================

        while True:

            line = process.stderr.readline()

            if (
                not line
                and process.poll() is not None
            ):
                break

            if line:

                stderr_tail.append(line)

                if len(stderr_tail) > 40:

                    stderr_tail.pop(0)

            # -------------------------------------------------
            # FFmpeg TIME
            # -------------------------------------------------

            if "time=" in line:

                time_match = re.search(
                    r"time=(\d+):(\d+):(\d+)\.(\d+)",
                    line
                )

                if time_match:

                    hrs = int(
                        time_match.group(1)
                    )

                    mins = int(
                        time_match.group(2)
                    )

                    secs = int(
                        time_match.group(3)
                    )

                    fraction = int(
                        time_match.group(4)
                    )

                    played_seconds = (
                        hrs * 3600
                        + mins * 60
                        + secs
                        + fraction / (
                            10 **
                            len(
                                time_match.group(4)
                            )
                        )
                    )

                    current_stream_seconds = (
                        last_seconds
                        + played_seconds
                    )

                    _current_index = \
                        current_index

                    _current_seconds = \
                        current_stream_seconds

                    _current_url = \
                        target_stream_url

                    now = time.time()

                    # -------------------------------------------------
                    # STATE
                    # -------------------------------------------------

                    if (
                        now - last_save_time
                        > 3
                    ):

                        update_local_state(
                            current_index,
                            current_stream_seconds,
                            target_stream_url
                        )

                        last_save_time = now

                    # -------------------------------------------------
                    # DASHBOARD
                    # -------------------------------------------------

                    if (
                        now - last_dashboard_time
                        > 30
                    ):

                        print_dashboard(
                            film_title,
                            current_index,
                            len(playlist),
                            current_stream_seconds
                        )

                        write_step_summary(
                            film_title,
                            current_index,
                            len(playlist),
                            current_stream_seconds
                        )

                        last_dashboard_time = now

        # =================================================
        # FFMPEG SONUCU
        # =================================================

        return_code = process.returncode

        if return_code == 0:

            print(
                "✅ İçerik tamamen bitti."
            )

            print(
                "➡️ Sıradaki içeriğe geçiliyor."
            )

            write_step_summary(
                film_title,
                current_index,
                len(playlist),
                current_stream_seconds,
                status=(
                    "✅ Bitti, "
                    "sıradakine geçiliyor"
                )
            )

            current_index += 1

            last_seconds = 0

            last_url = ""

            _current_index = \
                current_index

            _current_seconds = 0

            _current_url = ""

            update_local_state(
                current_index,
                0,
                ""
            )

        else:

            print(
                f"⚠️ Yayın koptu. "
                f"Return Code: {return_code}"
            )

            print(
                "🔄 Aynı konumdan tekrar "
                "başlatılacak."
            )

            write_step_summary(
                film_title,
                current_index,
                len(playlist),
                current_stream_seconds,
                status=(
                    "🔴 Bağlantı koptu, "
                    "aynı yerden tekrar denenecek"
                )
            )

            last_seconds = \
                current_stream_seconds

            _current_index = \
                current_index

            _current_seconds = \
                last_seconds

            _current_url = \
                target_stream_url

            update_local_state(
                current_index,
                last_seconds,
                target_stream_url
            )

        print(
            "⏳ 5 saniye sonra yeniden "
            "bağlanılıyor..."
        )

        time.sleep(5)


# =========================================================
# BAŞLAT
# =========================================================

if __name__ == "__main__":

    start_m3u_stream()
