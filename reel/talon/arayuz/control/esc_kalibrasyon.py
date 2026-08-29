#!/usr/bin/env python3
"""
esc_kalibrasyon.py — ESC'ye gaz aralığını öğretir.

ESC, hangi PWM değerinin "sıfır gaz", hangisinin "tam gaz" olduğunu bilmek
zorundadır. Fabrika ayarı sizin sisteminizle uyuşmuyorsa ESC arming
sekansını tamamlamaz: sürekli uyarı bipi çalar ve motor hiç dönmez.

MOTOR PİNİ
----------
ESC MAIN 6'dadır (17 Ağu 2026: SERVO6_FUNCTION = 70 Throttle). Bu dosya
eskiden MAIN 3'e sabitlenmişti; MAIN 3 fiziksel olarak ölü çıktı ve motor
MAIN 6'ya taşındı. Pin artık ESC_PIN ortam değişkeniyle verilebilir.

NEDEN ARALIK ÖNEMLİ
-------------------
Uçuşta ArduPlane gaz kanalına SERVOn_MIN ile SERVOn_MAX arasında değer
gönderir (bu kartta MAIN 6 için 1000-2000). ESC'ye daha dar bir aralık
öğretilirse, uçuşta gelen MIN değeri ESC için sıfır gaz olmaz ve MOTOR
GAZ KESİKKEN DÖNMEYE BAŞLAR. Kalibrasyon, otopilotun gerçekte
göndereceği aralıkla yapılmalıdır.

ÖN KOŞUL
    SERVO6_FUNCTION = 1 (RCPassThru) — kalibrasyon süresince GEÇİCİ.
    Bittiğinde MUTLAKA 70'e (Throttle) geri alın: arm koruması ona bağlı.

GÜVENLİK
    [ ] PERVANE ÇIKARIK — bazı ESC'ler kalibrasyonda motoru kısa süre döndürür
    [ ] Motor sağlam sabitlenmiş
    [ ] Batarya elinizin altında

KULLANIM
    python -m control.esc_kalibrasyon              # 2000 / 1000 (ESC standardı)
    ESC_PIN=3 python -m control.esc_kalibrasyon    # başka pini kalibre et

Varsayılan 2000/1000'dir: çoğu ESC kalibrasyon için bu aralığı bekler ve
daha darını geçerli saymaz. MAIN 6 zaten 1000/2000 olduğu için uyuşuyor.
"""

import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control.mav_common import (
    GCSKeepalive,
    clear_rc_overrides,
    connect_mavlink,
    get_param,
)

ADIM_HZ = 50
_dur = False


def _sig(_s, _f):
    global _dur
    _dur = True


def _gaz(conn, pwm, kanal=6):
    """
    ESC'ye PWM gönderir.

    KANAL = PİN olmalı. Kalibrasyon RCPassThru (SERVOn_FUNCTION = 1) ile
    yapılır; RCPassThru'da MAIN n çıkışı RC n GİRİŞİNİ aynalar. Yani MAIN 6'yı
    sürmek için kanal 6 override edilir, kanal 3 değil. (Bu dosya eskiden
    kanal 3'e sabitti; motor MAIN 3'teyken doğruydu, MAIN 6'ya taşınınca
    ölü pini sürmeye başlamıştı.)
    """
    kanallar = [0] * 8
    kanallar[kanal - 1] = int(pwm)
    conn.mav.rc_channels_override_send(
        conn.target_system, conn.target_component, *kanallar)


def _tut(conn, pwm, sure, kanal=6):
    """Belirtilen PWM'i sabit tutar (ESC'nin görmesi için sürekli gönderilir)."""
    t0 = time.time()
    while time.time() - t0 < sure and not _dur:
        _gaz(conn, pwm, kanal)
        time.sleep(1.0 / ADIM_HZ)


def main():
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    print("=" * 64)
    print("  ESC KALİBRASYONU")
    print("=" * 64)

    conn = connect_mavlink()

    # Motor MAIN 6'da (SERVO6_FUNCTION = 70). Farklı pin gerekirse ESC_PIN ile.
    pin = int(os.environ.get("ESC_PIN", "6"))
    print(f"\n  Kalibre edilecek çıkış: MAIN {pin}")

    fonk = get_param(conn, f"SERVO{pin}_FUNCTION", timeout=6)
    if fonk is None or int(fonk) != 1:
        print(f"\n  HATA: SERVO{pin}_FUNCTION = {fonk}, olması gereken 1 (RCPassThru).")
        if fonk is not None and int(fonk) == 70:
            print("        Şu an 70 (Throttle). Kalibrasyon için GEÇİCİ olarak 1")
            print("        yapın, bittiğinde MUTLAKA 70'e geri alın — arm koruması")
            print("        (disarm iken çıkışın MIN'de kilitlenmesi) ona bağlı.")
        return 1

    # Varsayılan 2000/1000 — çoğu ESC kalibrasyonda bu aralığı bekler.
    ust = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    alt = int(sys.argv[2]) if len(sys.argv) > 2 else 1000

    s_min = get_param(conn, f"SERVO{pin}_MIN", timeout=6)
    s_max = get_param(conn, f"SERVO{pin}_MAX", timeout=6)

    print(f"\n  ESC'ye öğretilecek aralık : {alt} – {ust}")
    print(f"  Kartın şu anki gaz aralığı: {int(s_min or 0)} – {int(s_max or 0)}")
    if s_min is not None and int(s_min) != alt:
        print()
        print(f"  ! UYARI: Bu kalibrasyondan sonra SERVO{pin}_MIN/MAX değerlerini")
        print(f"    {alt}/{ust} yapmak GEREKİR. Aksi halde uçuşta otopilotun")
        print(f"    gönderdiği {int(s_min)} değeri ESC için sıfır gaz olmaz ve")
        print("    MOTOR GAZ KESİKKEN DÖNER. Kalibrasyon sonrası ayarlanacak.")
    print()
    print("  " + "!" * 60)
    print("  [ ] PERVANE ÇIKARIK")
    print("  [ ] Motor sağlam sabitlenmiş")
    print("  [ ] Batarya ŞU AN ÇIKARIK olmalı")
    print("  " + "!" * 60)

    if input("\n  Hazır mısınız? (evet yazın): ").strip().lower() != "evet":
        print("  İptal edildi.")
        return 0

    keepalive = GCSKeepalive(conn, interval=0.2)
    keepalive.start()

    try:
        # --- 1. ADIM: MAX gönder, batarya takılsın ---
        print()
        print("-" * 64)
        print(f"  1. ADIM — Gaz MAKSİMUMDA ({ust}) tutuluyor.")
        print("-" * 64)
        print("  ŞİMDİ BATARYAYI TAKIN.")
        print("  ESC bip çalacak (üst sınırı kaydediyor).")
        print()
        # Batarya takılana kadar MAX'ta tut — kullanıcı Enter'a basana dek
        import threading
        beklemede = {"devam": True}

        def bekle_enter():
            input("  Bataryayı taktıktan ve bipi duyduktan sonra ENTER'a basın...")
            beklemede["devam"] = False

        th = threading.Thread(target=bekle_enter, daemon=True)
        th.start()
        while beklemede["devam"] and not _dur:
            _gaz(conn, ust, pin)
            time.sleep(1.0 / ADIM_HZ)

        if _dur:
            raise KeyboardInterrupt

        # --- 2. ADIM: MIN'e in ---
        # ESC'lerin çoğu max'ı 2-3 saniye görmek ister; Enter'dan sonra
        # bir süre daha max'ta kalıp öyle iniyoruz.
        print()
        print("  Üst sınır kaydı için 3 saniye daha bekleniyor...")
        _tut(conn, ust, 3.0, pin)

        print()
        print("-" * 64)
        print(f"  2. ADIM — Gaz MİNİMUMA ({alt}) indiriliyor.")
        print("-" * 64)
        print("  ESC tekrar bip çalacak (alt sınırı kaydediyor).")
        print("  8 saniye minimumda tutuluyor...")
        _tut(conn, alt, 8.0, pin)

        print()
        print("  Kalibrasyon tamamlandı.")
        print("  ESC artık normal çalışma modunda, gaz kesik konumda.")
        print()
        print("  Motoru denemek için (bu pencereden çıkmadan, ayrı terminalde):")
        print("     python -m control.motor_gaz 1200")

        # Gaz kesikte bekle — ESC arming yapsın
        print()
        print("  Gaz kesik tutuluyor, çıkmak için Ctrl+C...")
        _tut(conn, alt, 3600, pin)

    except KeyboardInterrupt:
        pass
    finally:
        print("\n  Gaz kesiliyor...")
        for _ in range(10):
            _gaz(conn, alt, pin)
            time.sleep(0.02)
        clear_rc_overrides(conn)
        time.sleep(0.2)
        clear_rc_overrides(conn)
        keepalive.stop()

    print("  Bitti. Motor dönmüyorsa BATARYAYI ÇEKİN.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
