import os
import sys
import time
import json
import subprocess
import requests

# ==================== Müşteri ve Yayın Ayarları ====================
M3U_URL = "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/prasss.m3u"
LOGO_URL = "https://raw.githubusercontent.com/ino8090/0101/refs/heads/main/file_000000001218821086dc1a6d6539a2b9.png"
RTMP_URL = "rtmp://ssh101.bozztv.com:1935/ssh101/yesilcam"
STATE_FILE = "state_yesilcam.json"
LOGO_FILE = "logo.png"

# Sunucu engelini (HTTP 403) aşmak için tarayıcı başlıkları
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
REFERER = "https://nextlevelbrandstudio.site/"

# ==================== Yardımcı Fonksiyonlar ====================

def download_logo():
    """Logo dosyasını indirir."""
    if not os.path.exists(LOGO_FILE):
        try:
            res = requests.get(LOGO_URL, timeout=15)
            if res.status_code == 200:
                with open(LOGO_FILE, "wb") as f:
                    f.write(res.content)
                print(f"✅ Logo indirildi ve '{LOGO_FILE}' olarak kaydedildi.")
            else:
                print(f"⚠️ Logo indirilemedi (HTTP {res.status_code}), varsayılan logosuz devam edilecek.")
        except Exception as e:
            print(f"⚠️ Logo indirme hatası: {e}")
    else:
        print(f"✅ Logo mevcut: '{LOGO_FILE}'")

def load_state():
    """Kaldığı yeri (Sıra ve Saniye) kaydedilen JSON dosyasından okur."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"index": 0, "start_time": 0}

def save_state(index, start_time):
    """Mevcut yayın durumunu kaydeder."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"index": index, "start_time": int(start_time)}, f, ensure_ascii=False, indent=2)

def parse_m3u(url):
    """M3U oynatma listesini çekip başlık ve video linklerini ayıklar."""
    print(f"🔧 Kullanılan M3U : {url}")
    playlist = []
    try:
        res = requests.get(url, timeout=15)
        lines = res.text.splitlines()
        current_title = "Bilinmeyen İçerik"
        
        for line in lines:
            line = line.strip()
            if line.startswith("#EXTINF:"):
                parts = line.split(",")
                if len(parts) > 1:
                    current_title = parts[-1].strip()
            elif line and not line.startswith("#"):
                playlist.append({"title": current_title, "url": line})
                current_title = "Bilinmeyen İçerik"
    except Exception as e:
        print(f"❌ M3U listesi çekilemedi: {e}")
    return playlist

def format_seconds(seconds):
    """Saniyeyi HH:MM:SS formatına çevirir."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# ==================== Ana Yayın Döngüsü ====================

def start_stream():
    print(f"🔧 Kullanılan Logo : {LOGO_URL}")
    print(f"🔧 State dosyası : {STATE_FILE}")
    print(f"🔧 RTMP hedefi : {RTMP_URL}\n")
    
    download_logo()
    playlist = parse_m3u(M3U_URL)
    
    if not playlist:
        print("❌ Oynatma listesi boş veya alınamadı! Çıkılıyor.")
        sys.exit(1)

    state = load_state()
    current_idx = state.get("index", 0) % len(playlist)
    start_ss = state.get("start_time", 0)

    while True:
        item = playlist[current_idx]
        title = item["title"]
        stream_url = item["url"]
        total_items = len(playlist)

        print("\n┌──────────────────────────────────────────────────────────┐")
        print(f"│ 🎬 İçerik     : {title[:40]:<40} │")
        print(f"│ 🔢 Sıra       : {current_idx + 1}/{total_items:<38} │")
        print(f"│ ⏱️ Geçen Süre : {format_seconds(start_ss):<40} │")
        print(f"│ 📡 Durum      : 🟡 Başlatılıyor                          │")
        print("└──────────────────────────────────────────────────────────┘")

        # HTTP Header Ayarları (403 Forbidden Engeli Çözümü)
        headers = (
            f"User-Agent: {USER_AGENT}\r\n"
            f"Referer: {REFERER}\r\n"
            f"Origin: {REFERER}\r\n"
        )

        # FFmpeg Komutu Oluşturma
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-re",
            # HLS segment erisim engellerini aşan parametreler:
            "-user_agent", USER_AGENT,
            "-headers", headers,
            "-ss", str(start_ss),
            "-i", stream_url
        ]

        # Logo filtresi ve video işleme
        if os.path.exists(LOGO_FILE):
            cmd.extend([
                "-i", LOGO_FILE,
                "-filter_complex", "[0:v][1:v]overlay=main_w-overlay_w-20:20[v]",
                "-map", "[v]",
                "-map", "0:a?"
            ])

        # Video/Ses Kodek ve RTMP Çıktı Ayarları
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-maxrate", "2500k",
            "-bufsize", "5000k",
            "-pix_fmt", "yuv420p",
            "-g", "50",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-f", "flv",
            RTMP_URL
        ])

        print("▶ FFmpeg başlatıldı...")
        start_exec_time = time.time()

        try:
            # FFmpeg sürecini çalıştır
            process = subprocess.Popen(cmd)
            process.wait()
            ret_code = process.returncode
        except KeyboardInterrupt:
            print("\n🛑 Yayın kullanıcı tarafından durduruldu.")
            save_state(current_idx, start_ss)
            sys.exit(0)

        elapsed = time.time() - start_exec_time
        start_ss += int(elapsed)

        # Yayın koptuysa veya HLS hatası verildiyse
        if ret_code != 0:
            print(f"\n⚠️ Yayın koptu (Return Code: {ret_code}). Aynı saniyeden ({format_seconds(start_ss)}) tekrar denenecek.")
            save_state(current_idx, start_ss)
            print("⚠️ 10 saniye sonra tekrar bağlanılıyor...")
            time.sleep(10)
        else:
            # Video normal bittiyse sonraki videoya geç
            print("\n✅ İçerik tamamlandı. Sonraki videoya geçiliyor.")
            current_idx = (current_idx + 1) % len(playlist)
            start_ss = 0
            save_state(current_idx, start_ss)

if __name__ == "__main__":
    start_stream()
