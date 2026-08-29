#!/usr/bin/env python3
"""
servo_test.py — Komutlarınızın gerçekten kumanda yüzeylerine gittiğini
kanıtlar. Uçağı hiç kaldırmadan, motor bağlı olmadan, kapalı ortamda.

NE YAPAR
--------
RC override gönderir ve otopilotun ürettiği servo PWM çıkışlarını okur.
Üç şeyi ayrı ayrı gösterir:

  1. Gönderdiğimiz komut          (bizim RC override paketimiz)
  2. Pixhawk'ın ALDIĞI değer      (RC_CHANNELS — paket ulaştı mı?)
  3. Servo çıkışı                 (SERVO_OUTPUT_RAW — otopilot ne yaptı?)

Üçü de uyumluysa uçuş kontrol zinciri sağlamdır. 2. adım değişmiyorsa
paketler ulaşmıyordur (SYSID uyuşmazlığı); 3. adım değişmiyorsa otopilot
komutu yok sayıyordur (mod, safety switch veya kanal eşlemesi).

GÜVENLİK
--------
Throttle bilerek en düşük değerde tutulur ve araç arm EDİLMEZ. Yine de
pervane takılıysa çıkarın — bu bir alışkanlık meselesi.

Kullanım (Windows — panel KAPALIYKEN, seri portu tek süreç açabilir):
    set MAV_ENDPOINT=COM3
    set MAV_BAUD=57600
    python -m control.servo_test
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymavlink import mavutil

from control.mav_common import (
    GCSKeepalive,
    clear_rc_overrides,
    connect_mavlink,
    get_mode,
    is_armed,
    set_mode,
    PLANE_MODE_MANUAL,
)

OLCUM_SURESI = 3.0     # her adım için komut gönderme + ölçüm süresi


def _hizli_akis(conn, hz=10):
    """
    SERVO_OUTPUT_RAW ve RC_CHANNELS akışlarını hızlandırır.

    Varsayılan hız çok düşüktür; hızlandırmadan okursanız kuyrukta bekleyen
    BAYAT değerleri görür ve "komut işlemiyor" sanırsınız.
    """
    aralik = int(1e6 / hz)
    for mid in (mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW,
                mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS):
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            mid, aralik, 0, 0, 0, 0, 0)
        time.sleep(0.1)


def _adim(conn, etiket, roll=0, pitch=0, yaw=0):
    """Bir komutu sürekli gönderir ve sonucu ölçer."""
    ch1 = int(1500 + roll / 2)
    ch2 = int(1500 + pitch / 2)
    ch4 = int(1500 + yaw / 2)

    srv = rc = None
    t0 = time.time()
    while time.time() - t0 < OLCUM_SURESI:
        conn.mav.rc_channels_override_send(
            conn.target_system, conn.target_component,
            ch1, ch2, 1000, ch4, 0, 0, 0, 0)
        # Kuyruğu boşalt, en TAZE mesajı sakla
        m = conn.recv_match(type=["SERVO_OUTPUT_RAW", "RC_CHANNELS"],
                            blocking=False)
        while m:
            if m.get_type() == "SERVO_OUTPUT_RAW":
                srv = m
            else:
                rc = m
            m = conn.recv_match(type=["SERVO_OUTPUT_RAW", "RC_CHANNELS"],
                                blocking=False)
        time.sleep(0.05)

    print(f"\n  {etiket}")
    print(f"    gönderdiğimiz : CH1={ch1}  CH2={ch2}  CH4={ch4}")
    if rc:
        print(f"    Pixhawk aldı  : RC1={rc.chan1_raw}  RC2={rc.chan2_raw}  "
              f"RC4={rc.chan4_raw}")
    else:
        print("    Pixhawk aldı  : RC_CHANNELS gelmiyor")
    if srv:
        print(f"    servo çıkışı  : S1={srv.servo1_raw}  S2={srv.servo2_raw}  "
              f"S4={srv.servo4_raw}")
    else:
        print("    servo çıkışı  : SERVO_OUTPUT_RAW gelmiyor")
    return rc, srv


def main():
    print("=" * 62)
    print("  SERVO ÇIKIŞ TESTİ — komutlar kumanda yüzeylerine gidiyor mu?")
    print("=" * 62)
    print("  Araç ARM EDİLMEZ, gaz en düşükte tutulur.")

    conn = connect_mavlink()

    armed = is_armed(conn, timeout=3.0)
    if armed:
        print("\n  UYARI: Araç ARMLI. Pervane takılıysa DERHAL uzaklaşın.")

    keepalive = GCSKeepalive(conn, interval=0.2)
    keepalive.start()

    mod = get_mode(conn, timeout=3.0)
    print(f"\n  Mevcut mod: {mod[1] if mod else 'bilinmiyor'}")
    print("  MANUAL moda alınıyor (override doğrudan yüzeylere işlesin)...")
    set_mode(conn, PLANE_MODE_MANUAL)
    time.sleep(1.0)

    _hizli_akis(conn)
    time.sleep(1.0)

    sonuclar = []
    sonuclar.append(_adim(conn, "NÖTR", roll=0))
    sonuclar.append(_adim(conn, "SAĞA yatış  (roll=+600)", roll=600))
    sonuclar.append(_adim(conn, "SOLA yatış  (roll=-600)", roll=-600))
    sonuclar.append(_adim(conn, "BURUN yukarı (pitch=+600)", pitch=600))
    sonuclar.append(_adim(conn, "BURUN aşağı  (pitch=-600)", pitch=-600))
    sonuclar.append(_adim(conn, "SAĞA yön    (yaw=+600)", yaw=600))

    clear_rc_overrides(conn)
    time.sleep(0.3)
    clear_rc_overrides(conn)
    keepalive.stop()

    # --- Değerlendirme ---
    print("\n" + "=" * 62)
    rc_degerler = {r.chan1_raw for r, _ in sonuclar if r}
    srv_degerler = {s.servo1_raw for _, s in sonuclar if s}

    if len(rc_degerler) < 2:
        print("  SONUÇ: Pixhawk komutları ALMIYOR.")
        print("    - GCS sistem ID'si 255 mi? (preflight söyler)")
        print("    - Köprü/bağlantı doğru cihaza mı bakıyor?")
    elif len(srv_degerler) < 2:
        print("  SONUÇ: Komutlar ULAŞIYOR ama servo çıkışı DEĞİŞMİYOR.")
        print("    - Pixhawk'ın güvenlik anahtarına (safety switch) basıldı mı?")
        print("    - Uçuş modu MANUAL/FBWA mı?")
        print("    - Servo kanal eşlemesi (RCMAP/SERVOn_FUNCTION) doğru mu?")
    else:
        print("  SONUÇ: ZİNCİR SAĞLAM.")
        print("  Komutlarınız Pixhawk'a ulaşıyor ve servo çıkışlarına işliyor.")
        print("  Servolar takılıysa kumanda yüzeyleri hareket ediyor demektir.")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
