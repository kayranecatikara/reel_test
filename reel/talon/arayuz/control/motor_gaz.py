#!/usr/bin/env python3
"""
motor_gaz.py — Motoru DÜŞÜK ve SINIRLI gazla, kademeli olarak döndürür.

Gaz kanalına (CH3) RC override gönderir. Kapalı ortamda motor yön/çalışma
testi için. İki düzeni de tanır, gerekli ön koşul düzene göre değişir:

    Throttle   (bir çıkışta SERVOn_FUNCTION = 70)  →  ARM ZORUNLU
                arm koruması disarm iken çıkışı 1000 µs'de kilitler
    RCPassThru (SERVOn_FUNCTION = 1)               →  ARM OLMAMALI

Motor MAIN 6'da ve Throttle fonksiyonunda (11 Ağu 2026). Kapalı ortamda
GPS/pusula olmadığı için normal arm geçmez; tezgâh testinde force arm
kullanılır — PERVANE ÇIKARIK olmak şartıyla.

GÜVENLİK — bu araç kasten kısıtlıdır
    · En yüksek PWM 1250 ile SINIRLI (koda gömülü, argümanla aşılamaz)
    · Gaz kademeli artar, ani sıçrama yok
    · Ctrl+C anında gazı keser ve override'ı bırakır
    · Süre dolunca kendiliğinden durur

KULLANIM
    python -m control.motor_gaz              # CH3, 1150'ye kadar, 5 sn tut
    python -m control.motor_gaz 1200         # CH3, 1200'e kadar
    python -m control.motor_gaz 1180 8       # CH3, 1180'e kadar, 8 sn tut
    python -m control.motor_gaz 1200 5 1     # CH1'e gönder (kanal testi)

Üçüncü argüman kanal numarasıdır. ESC'nin sinyal alıp almadığını sınamak
için çalıştığı bilinen bir kanala takıp oradan denemek işe yarar; o kanalın
SERVOn_FUNCTION değeri de 1 (RCPassThru) olmalıdır.

HER SEFERİNDE KONTROL EDİN
    [ ] PERVANE ÇIKARIK
    [ ] Motor mengeneye/gövdeye SAĞLAM sabitli
    [ ] Motor kabloları takılı, gergin değil
    [ ] Kimse motor hizasında değil
    [ ] Batarya elinizin altında (acil durumda ÇEKİN)
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
    get_battery,
    get_param,
    is_armed,
)

GAZ_KESIK = 1000          # ESC'nin "sıfır gaz" beklediği değer
EN_YUKSEK = 1250          # SERT SINIR — argümanla aşılamaz
VARSAYILAN_HEDEF = 1150
VARSAYILAN_TUTMA = 5.0
RAMPA_SURESI = 3.0        # kesikten hedefe kademeli çıkış süresi
ADIM_HZ = 50

_dur = False


def _sig(_s, _f):
    global _dur
    _dur = True


def _gaz(conn, pwm, kanal=3):
    """Yalnızca seçilen kanala PWM gönderir, diğerlerine dokunmaz (0 = override yok)."""
    kanallar = [0] * 8
    kanallar[kanal - 1] = int(pwm)
    conn.mav.rc_channels_override_send(
        conn.target_system, conn.target_component, *kanallar)


def _cikis_oku(conn, kanal=3):
    """Otopilotun o kanalda ürettiği gerçek çıkışı okur (varsa)."""
    son = None
    while True:
        m = conn.recv_match(type="SERVO_OUTPUT_RAW", blocking=False)
        if m is None:
            break
        son = m
    return getattr(son, f"servo{kanal}_raw", None) if son else None


def _kes(conn, kanal=3):
    """Gazı kesip override'ı bırakır — çıkışta her yoldan çağrılır."""
    for _ in range(10):
        _gaz(conn, GAZ_KESIK, kanal)
        time.sleep(0.02)
    clear_rc_overrides(conn)
    time.sleep(0.2)
    clear_rc_overrides(conn)


def main():
    global _dur

    hedef = int(sys.argv[1]) if len(sys.argv) > 1 else VARSAYILAN_HEDEF
    tutma = float(sys.argv[2]) if len(sys.argv) > 2 else VARSAYILAN_TUTMA
    kanal = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    if hedef > EN_YUKSEK:
        print(f"Bu araç en fazla {EN_YUKSEK} PWM verir (istenen: {hedef}).")
        print("Daha yükseği itki testidir; wattmetre ve düzgün düzenek ister.")
        return 2
    if hedef < GAZ_KESIK:
        hedef = GAZ_KESIK

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    print("=" * 62)
    print("  MOTOR GAZ TESTİ")
    print("=" * 62)

    conn = connect_mavlink()

    # GÖNDERDİĞİMİZ RC KANALI ile İZLEDİĞİMİZ ÇIKIŞ AYNI ŞEY DEĞİL:
    #   · RCPassThru (SERVOn_FUNCTION=1)  : çıkış n, RC n'i birebir yansıtır → aynı
    #   · Throttle   (SERVOn_FUNCTION=70) : RC CH3 → otopilot → 70 atanmış çıkış
    # (11 Ağu 2026: motor MAIN 6'ya alındı, SERVO6_FUNCTION 1 → 70 yapıldı.
    #  RCPassThru'da CH6 = VrB düğmesi motoru sürüyordu, arm koruması da yoktu.)
    motor_pini = None
    for n in range(1, 9):
        f = get_param(conn, f"SERVO{n}_FUNCTION", timeout=5)
        if f is not None and int(f) == 70:
            motor_pini = n
            break

    kendi_fonk = get_param(conn, f"SERVO{kanal}_FUNCTION", timeout=6)
    passthru = kendi_fonk is not None and int(kendi_fonk) == 1

    if motor_pini is not None:
        izleme_pini = motor_pini
        print(f"\n  Motor çıkışı : MAIN {motor_pini} (Throttle)")
        print(f"  Gaz kanalı   : CH{kanal}")
        if not is_armed(conn, timeout=3.0):
            print("\n  HATA: Araç DISARM.")
            print("  Throttle fonksiyonunda arm koruması çıkışı 1000 µs'de")
            print("  kilitler — motor dönmez. Önce arm edin.")
            return 1
    elif passthru:
        izleme_pini = kanal
        print(f"\n  Mod: RCPassThru (CH{kanal} → MAIN {kanal})")
        if is_armed(conn, timeout=3.0):
            print("\n  UYARI: Araç ARMLI. RCPassThru'da arm gerekmez — disarm edin.")
            return 1
    else:
        print(f"\n  HATA: Motor çıkışı bulunamadı.")
        print(f"  Ne 70 (Throttle) atanmış bir çıkış var, ne de "
              f"SERVO{kanal}_FUNCTION = 1.")
        print("  Motorun bağlı olduğu pine SERVOn_FUNCTION = 70 atayın.")
        return 1

    b = get_battery(conn, timeout=4.0)
    if b and b["voltage"] > 1.0:
        print(f"\n  Batarya: {b['voltage']:.2f} V ({b['voltage'] / 6:.2f} V/hücre)")
        if b["voltage"] < 19.8:
            print("  UYARI: Batarya kritik sınırda (6S için 19.8 V)")

    print(f"\n  Kanal     : CH{kanal}")
    print(f"  Hedef gaz : {hedef} PWM   (kesik = {GAZ_KESIK}, sert sınır = {EN_YUKSEK})")
    print(f"  Rampa     : {RAMPA_SURESI} sn içinde kademeli")
    print(f"  Tutma     : {tutma} sn")
    print()
    print("  " + "!" * 58)
    print("  [ ] PERVANE ÇIKARIK")
    print("  [ ] Motor SAĞLAM sabitlenmiş")
    print("  [ ] Kimse motor hizasında değil")
    print("  [ ] Batarya elinizin altında")
    print("  " + "!" * 58)

    if input("\n  Hepsi tamam mı? (evet yazın): ").strip().lower() != "evet":
        print("  İptal edildi.")
        return 0

    keepalive = GCSKeepalive(conn, interval=0.2)
    keepalive.start()

    # ESC'ye giden gerçek çıkışı izleyebilmek için akışı hızlandır
    from pymavlink import mavutil as _mv
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        _mv.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
        _mv.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW, 100000, 0, 0, 0, 0, 0)
    time.sleep(0.5)

    try:
        # Önce kesik değerde tut — ESC sinyali görsün, arm bipini yapsın
        print("\n  Gaz kesik konumda, ESC hazırlanıyor (2 sn)...")
        t0 = time.time()
        while time.time() - t0 < 2.0 and not _dur:
            _gaz(conn, GAZ_KESIK, kanal)
            time.sleep(1.0 / ADIM_HZ)

        # Kademeli çıkış
        print(f"  Gaz kademeli artıyor: {GAZ_KESIK} -> {hedef}")
        adim = int(RAMPA_SURESI * ADIM_HZ)
        for i in range(adim + 1):
            if _dur:
                break
            pwm = GAZ_KESIK + (hedef - GAZ_KESIK) * i / adim
            _gaz(conn, pwm, kanal)
            if i % (ADIM_HZ // 2) == 0:
                cikis = _cikis_oku(conn, izleme_pini)
                print(f"    gönderilen {int(pwm)} PWM   ->   ESC'ye giden "
                      f"{cikis if cikis is not None else '?'}")
            time.sleep(1.0 / ADIM_HZ)

        # Hedefte tut
        if not _dur:
            print(f"  {hedef} PWM'de tutuluyor ({tutma} sn) — MOTORU İZLEYİN")
            t0 = time.time()
            son_yazim = 0
            while time.time() - t0 < tutma and not _dur:
                _gaz(conn, hedef, kanal)
                if time.time() - son_yazim > 1.0:
                    son_yazim = time.time()
                    cikis = _cikis_oku(conn, izleme_pini)
                    print(f"    ESC'ye giden: "
                          f"{cikis if cikis is not None else '?'}")
                time.sleep(1.0 / ADIM_HZ)
    finally:
        print("\n  Gaz kesiliyor...")
        _kes(conn, kanal)
        keepalive.stop()

    print("  Test bitti, motor durmuş olmalı.")
    print("  Durmadıysa BATARYAYI ÇEKİN.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
