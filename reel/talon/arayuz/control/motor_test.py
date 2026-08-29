#!/usr/bin/env python3
"""
motor_test.py — Motoru ARM ETMEDEN, kontrollü şekilde döndürür.

ArduPilot'un DO_MOTOR_TEST komutunu kullanır: belirtilen yüzdede,
belirtilen süre boyunca motoru çalıştırır ve kendiliğinden durdurur.
Arm gerekmez, GPS gerekmez — kapalı ortamda test edilebilir.

KULLANIM
    python -m control.motor_test              # %8, 3 saniye (en düşük)
    python -m control.motor_test 15           # %15, 3 saniye
    python -m control.motor_test 20 5         # %20, 5 saniye
    python -m control.motor_test dur          # çalışan testi durdur

GÜVENLİK — HER SEFERİNDE KONTROL EDİN
    1. PERVANE ÇIKARIK
    2. Motor mengeneye veya gövdeye SAĞLAM sabitlenmiş
    3. Motor kabloları ESC'ye takılı, gergin değil
    4. Kimse motor hizasında değil
    5. Batarya bağlantısı sağlam

Motor sabitlenmemişse test ETMEYİN — pervanesiz bile olsa titreşimle
yerinden fırlayabilir, kabloları çeker.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymavlink import mavutil

from control.mav_common import (
    connect_mavlink,
    get_battery,
    is_armed,
    wait_ack,
)

VARSAYILAN_YUZDE = 8      # ESC'nin dönmeye başladığı tipik alt sınır
VARSAYILAN_SURE = 3.0
EN_YUKSEK_YUZDE = 35      # bu araçla daha fazlası verilmez


def _guvenlik_onayi(yuzde, sure):
    print()
    print("!" * 62)
    print("  MOTOR DÖNDÜRÜLECEK")
    print("!" * 62)
    print(f"  Güç  : %{yuzde}")
    print(f"  Süre : {sure} saniye")
    print()
    print("  ONAYLAMADAN ÖNCE:")
    print("    [ ] Pervane ÇIKARIK")
    print("    [ ] Motor sağlam sabitlenmiş (mengene/gövde)")
    print("    [ ] Motor kabloları takılı, gergin değil")
    print("    [ ] Kimse motor hizasında değil")
    print()
    cevap = input("  Hepsi tamam mı? (evet yazın): ").strip().lower()
    if cevap != "evet":
        print("  İptal edildi.")
        return False
    return True


def _motor_testi(conn, yuzde, sure):
    """DO_MOTOR_TEST gönderir. throttle_type=0 → yüzde."""
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST, 0,
        1,        # param1: motor numarası (sabit kanatta 1 = ana motor)
        0,        # param2: throttle tipi, 0 = yüzde
        yuzde,    # param3: değer
        sure,     # param4: süre (saniye)
        0,        # param5: motor sayısı (0 = tek)
        0, 0,
    )
    return wait_ack(conn, mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST, timeout=4.0)


def _durdur(conn):
    """Süre dolmadan durdurmak için 0 yüzde / 0 süre gönderir."""
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_DO_MOTOR_TEST, 0,
        1, 0, 0, 0, 0, 0, 0,
    )


def main():
    args = [a.lower() for a in sys.argv[1:]]

    conn = connect_mavlink()

    if args and args[0] == "dur":
        _durdur(conn)
        print("Durdurma komutu gönderildi.")
        return 0

    yuzde = int(args[0]) if args else VARSAYILAN_YUZDE
    sure = float(args[1]) if len(args) > 1 else VARSAYILAN_SURE

    if yuzde > EN_YUKSEK_YUZDE:
        print(f"Bu araçla en fazla %{EN_YUKSEK_YUZDE} verilebilir.")
        print("Daha yükseği itki testi demektir; wattmetre ve düzgün bir "
              "test düzeneği ister.")
        return 2

    print("=" * 62)
    print("  MOTOR TESTİ (arm edilmez)")
    print("=" * 62)

    if is_armed(conn, timeout=3.0):
        print("  UYARI: Araç ARMLI. Önce disarm edin:")
        print("     python -m control.komut disarm")
        return 1

    b = get_battery(conn, timeout=4.0)
    if b and b["voltage"] > 1.0:
        print(f"  Batarya: {b['voltage']:.2f} V")
        if b["voltage"] < 19.8:
            print("  UYARI: Batarya düşük (6S için 19.8V kritik sınır)")

    if not _guvenlik_onayi(yuzde, sure):
        return 0

    print()
    print(f"  Motor çalıştırılıyor: %{yuzde}, {sure} sn...")
    sonuc = _motor_testi(conn, yuzde, sure)

    if sonuc is None:
        print("  ACK gelmedi — komut işlenmemiş olabilir.")
        print("  ArduPlane bu komutu desteklemiyorsa alternatif yol gerekir.")
    elif sonuc[1] == mavutil.mavlink.MAV_RESULT_ACCEPTED:
        print("  Komut KABUL EDİLDİ — motor dönüyor olmalı.")
    else:
        adlar = {1: "GEÇICI RED", 2: "REDDEDİLDİ", 3: "DESTEKLENMİYOR",
                 4: "BAŞARISIZ"}
        print(f"  Komut sonucu: {adlar.get(sonuc[1], sonuc[1])}")
        if sonuc[1] == 3:
            print("  Bu ArduPlane sürümü DO_MOTOR_TEST desteklemiyor.")

    # Test süresince araç mesajlarını göster
    t0 = time.time()
    while time.time() - t0 < sure + 2:
        m = conn.recv_match(type="STATUSTEXT", blocking=True, timeout=1)
        if m:
            metin = m.text.decode() if isinstance(m.text, bytes) else m.text
            print(f"    araç: {metin}")

    print()
    print("  Test bitti. Motor durmuş olmalı.")
    print("  Dönmediyse veya durmadıysa BATARYAYI ÇIKARIN.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
