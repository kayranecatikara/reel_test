#!/usr/bin/env python3
"""
servo_ortala.py — Servo kolunu düz takmak için çıkışı NÖTRDE (90°) tutar.

İKİ YÖNTEM VAR, HANGİSİNİ KULLANACAĞIN PİNE BAĞLI
---------------------------------------------------
1) BOŞ PİN  (SERVOn_FUNCTION = 0)          ->  varsayılan mod, ÖNERİLEN
   MAV_CMD_DO_SET_SERVO ile pine doğrudan 1500 µs yazılır. Karışım yok,
   kumandadan bağımsız, betik kapansa bile değer pinde kalır. Tam 1500.

2) UÇUŞ PİNİ (Aileron, VTail, ...)         ->  "tut" modu
   Bu pinleri otopilot sürer, doğrudan yazamayız. Kumanda kanallarına
   RCn_TRIM override'ı gönderip çıkışı nötre sabitleriz. Betik çalıştığı
   sürece geçerlidir; Ctrl+C'de kumanda kontrolü geri alır.

   KUMANDA AÇIK OLMALI. Telsiz failsafe'i devredeyken override çıkışı tam
   nötre oturtamıyor: 13 Ağu 2026'da kumanda kapalıyken MAIN1 = 1494,
   MAIN2 = 1507 ölçüldü; kumanda açılınca ikisi de tam 1500 oldu.
   Sapma görürseniz önce kumandanın açık olduğunu doğrulayın.

GAZ KANALINA DOKUNULMAZ
   CH3 bilerek override edilmez. Bu araç yalnızca kumanda yüzeyleri içindir.

KULLANIM
   python -m control.servo_ortala               # boş pinlerin hepsini 1500'e sabitle
   python -m control.servo_ortala 3             # yalnızca MAIN 3
   python -m control.servo_ortala tut           # uçuş pinlerini Ctrl+C'ye kadar nötrde tut
   python -m control.servo_ortala tut 120       # 120 saniye tut
"""

import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymavlink import mavutil

from control.mav_common import (
    clear_rc_overrides,
    connect_mavlink,
    get_param,
    is_armed,
)

NOTR = 1500
GONDERIM_HZ = 20
GAZ_KANALI = 3          # asla override edilmez

_dur = False


def _sig(_s, _f):
    global _dur
    _dur = True


def _cikislari_oku(conn, bekleme=1.5):
    """
    En taze SERVO_OUTPUT_RAW'ı döndürür (birikmiş kuyruğu boşaltarak).

    bekleme=0 ise beklemeden yalnızca kuyrukta hazır olanı süzer — "tut"
    döngüsü her tur zaten kendi hızında dönüyor, orada uyumak istemiyoruz.
    Kuyruk taraması her hâlükârda BİR KEZ çalışmalı; yoksa bekleme=0'da
    hiç okuma yapılmaz.
    """
    son = None
    t0 = time.time()
    while True:
        while True:
            m = conn.recv_match(type="SERVO_OUTPUT_RAW", blocking=False)
            if m is None:
                break
            son = m
        if son is not None or time.time() - t0 >= bekleme:
            return son
        time.sleep(0.02)


def _akisi_hizlandir(conn):
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
        mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW, 100000, 0, 0, 0, 0, 0)


def _satir(s):
    return "  ".join(f"M{n}={getattr(s, f'servo{n}_raw')}" for n in range(1, 9))


# ---------------------------------------------------------------------------
# 1) Boş pinler — DO_SET_SERVO
# ---------------------------------------------------------------------------

def bos_pinleri_ortala(conn, istenen=None):
    fonksiyonlar = {}
    for n in range(1, 9):
        f = get_param(conn, f"SERVO{n}_FUNCTION", timeout=5)
        if f is not None:
            fonksiyonlar[n] = int(f)

    if istenen:
        if fonksiyonlar.get(istenen) not in (0, None):
            print(f"\n  HATA: MAIN {istenen} boş değil "
                  f"(SERVO{istenen}_FUNCTION = {fonksiyonlar.get(istenen)}).")
            print("  Bu pini otopilot sürüyor, doğrudan yazılamaz.")
            print("  Uçuş pinini nötrde tutmak için:  python -m control.servo_ortala tut")
            return 1
        pinler = [istenen]
    else:
        pinler = [n for n, f in fonksiyonlar.items() if f == 0]

    if not pinler:
        print("\n  Boş (fonksiyonsuz) pin yok.")
        print("  Uçuş pinleri için:  python -m control.servo_ortala tut")
        return 1

    _akisi_hizlandir(conn)
    print(f"\n  Boş pinler {NOTR} µs'ye sabitleniyor: "
          + ", ".join(f"MAIN {n}" for n in pinler))

    for n in pinler:
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_SERVO, 0,
            n, NOTR, 0, 0, 0, 0, 0)
        ack = conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=3)
        if ack is None or ack.result != mavutil.mavlink.MAV_RESULT_ACCEPTED:
            print(f"    MAIN {n}: komut reddedildi "
                  f"({'ACK yok' if ack is None else ack.result})")

    time.sleep(1.0)
    s = _cikislari_oku(conn)
    if s:
        print(f"\n  DOĞRULAMA: {_satir(s)}")
        for n in pinler:
            v = getattr(s, f"servo{n}_raw")
            if v != NOTR:
                print(f"    UYARI: MAIN {n} = {v}, {NOTR} bekleniyordu.")

    print("\n  Değer pinde kalır — bu betik kapansa da sürer.")
    print("  Servo kolunu şimdi düz takabilirsiniz.")
    return 0


# ---------------------------------------------------------------------------
# 2) Uçuş pinleri — RC override ile nötrde tut
# ---------------------------------------------------------------------------

def ucus_pinlerini_tut(conn, sure=None):
    if is_armed(conn, timeout=3.0):
        print("\n  HATA: Araç ARMLI. Montaj için önce disarm edin.")
        return 1

    # Hangi RC kanalı hangi eksene bakıyor — varsayılan olduğunu varsaymıyoruz
    print("\n  Kumanda kanalları ve gönderilecek nötr değerler:")
    hedefler = {}
    for ad, param, varsayilan in (("roll", "RCMAP_ROLL", 1),
                                  ("pitch", "RCMAP_PITCH", 2),
                                  ("yaw", "RCMAP_YAW", 4)):
        v = get_param(conn, param, timeout=5)
        kanal = int(v) if v is not None else varsayilan
        if kanal == GAZ_KANALI:
            print(f"    {ad:<6} CH{kanal}  ATLANDI (gaz kanalı)")
            continue
        trim = get_param(conn, f"RC{kanal}_TRIM", timeout=5)
        if trim is None:
            print(f"    {ad:<6} CH{kanal}  RC{kanal}_TRIM okunamadı — atlandı")
            continue
        hedefler[kanal] = int(trim)
        print(f"    {ad:<6} CH{kanal}  ->  {int(trim)} µs")

    if not hedefler:
        print("\n  HATA: Ortalanacak kanal bulunamadı.")
        return 1

    _akisi_hizlandir(conn)

    if sure:
        print(f"\n  {sure:.0f} saniye tutulacak.")
    else:
        print("\n  Ctrl+C'ye basana kadar tutulacak.")
    print("  Servo kolunu şimdi düz takabilirsiniz.\n")

    kanallar = [0] * 8
    for kanal, deger in hedefler.items():
        kanallar[kanal - 1] = deger

    t0 = time.time()
    son_yazim = 0.0
    try:
        while not _dur:
            if sure and time.time() - t0 > sure:
                break
            conn.mav.rc_channels_override_send(
                conn.target_system, conn.target_component, *kanallar)
            if time.time() - son_yazim > 1.0:
                son_yazim = time.time()
                s = _cikislari_oku(conn, bekleme=0.0)
                if s:
                    print(f"    {_satir(s)}")
            time.sleep(1.0 / GONDERIM_HZ)
    finally:
        print("\n  Override bırakılıyor...")
        clear_rc_overrides(conn)
        time.sleep(0.2)
        clear_rc_overrides(conn)

    print("  Kumanda kontrolü geri verildi.")
    return 0


def main():
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""

    print("=" * 62)
    print("  SERVO ORTALAMA  (kumanda yüzeyleri 90°)")
    print("=" * 62)

    conn = connect_mavlink()

    if arg == "tut":
        sure = float(sys.argv[2]) if len(sys.argv) > 2 else None
        return ucus_pinlerini_tut(conn, sure)

    if arg:
        try:
            pin = int(arg)
        except ValueError:
            print(f"\n  Anlaşılmayan argüman: {arg}")
            print(__doc__.split("KULLANIM")[1])
            return 2
        if not 1 <= pin <= 8:
            print("\n  Pin 1-8 arasında olmalı.")
            return 2
        return bos_pinleri_ortala(conn, pin)

    return bos_pinleri_ortala(conn)


if __name__ == "__main__":
    sys.exit(main())
