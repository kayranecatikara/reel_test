#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
TALON BAĞLANTI TESTİ — "bağlandı mı, uçmaya hazır mı" sorusunu CEVAPLAR
================================================================================
Telemetri takıldıktan ve Talon'a güç verildikten sonra ÇALIŞTIRILACAK İLK ŞEY.
Sorunu KATMANLARA ayırır; hangi katmanda takıldığını söyler:

  1. SERİ PORT   : SiK telsizi görünüyor mu
  2. MAVLINK     : kalp atışı geliyor mu (araç konuşuyor mu)
  3. ARAÇ        : hangi firmware, hangi uçuş kipi, arm engelleri
  4. SENSÖRLER   : GPS fix, uydu, pil, duruş
  5. HAZIR MI    : uçuşa engel var mı

⛔ SERİ PORTU TEK SÜREÇ AÇABİLİR. İki kullanım:
     doğrudan   : --port /dev/ttyUSB0        (yayıncı KAPALIYKEN)
     yayıncıdan : --port udp:127.0.0.1:14550 (yayıncı AÇIKKEN)

Kullanım:
    python3 reel/talon/baglanti_testi.py                    # portu kendi bulur
    python3 reel/talon/baglanti_testi.py --port /dev/ttyUSB0
    python3 reel/talon/baglanti_testi.py --izle             # sürekli izle
================================================================================
"""
import argparse
import glob
import os
import sys
import time

# ArduPlane uçuş kipleri (custom_mode)
KIPLER = {0: "MANUAL", 1: "CIRCLE", 2: "STABILIZE", 3: "TRAINING", 4: "ACRO",
          5: "FBWA", 6: "FBWB", 7: "CRUISE", 8: "AUTOTUNE", 10: "AUTO",
          11: "RTL", 12: "LOITER", 13: "TAKEOFF", 15: "GUIDED", 16: "INIT",
          26: "AUTOLAND"}
FIX = {0: "fix YOK", 1: "fix YOK", 2: "2B fix", 3: "3B fix",
       4: "DGPS", 5: "RTK float", 6: "RTK sabit"}


def _port_bul():
    for a in sorted(glob.glob("/dev/serial/by-id/*")):
        return a
    for a in sorted(glob.glob("/dev/ttyUSB*")) + sorted(glob.glob("/dev/ttyACM*")):
        return a
    return None


def main():
    ap = argparse.ArgumentParser(description="Talon bağlantı ve sağlık testi")
    ap.add_argument("--port", default=os.environ.get("MAV_ENDPOINT", ""))
    ap.add_argument("--baud", type=int, default=int(os.environ.get("MAV_BAUD", 57600)))
    ap.add_argument("--izle", action="store_true", help="sürekli izle")
    ap.add_argument("--sure", type=float, default=12.0, help="dinleme süresi (s)")
    a = ap.parse_args()

    print("=" * 70)
    print("  TALON BAĞLANTI TESTİ")
    print("=" * 70)

    # ---- 1) SERİ PORT ----
    print("\n[1] SERİ PORT")
    port = a.port or _port_bul()
    if not port:
        print("    ⛔ hiçbir seri cihaz yok.")
        print("       · SiK telsizinin USB ucu takılı mı?")
        print("       · ls -l /dev/serial/by-id/   ·   dmesg | tail")
        return 2
    if port.startswith(("udp", "tcp")):
        print("    ✔ %s  (yayıncı üzerinden)" % port)
    else:
        if not os.path.exists(port):
            print("    ⛔ %s yok" % port)
            return 2
        if not os.access(port, os.W_OK):
            print("    ⛔ %s yazılabilir değil" % port)
            print("       sudo usermod -aG dialout $USER   (sonra ÇIK-GİR)")
            return 2
        print("    ✔ %s @ %d baud" % (port, a.baud))

    try:
        from pymavlink import mavutil
    except ImportError:
        print("\n⛔ pymavlink yok:  pip install pymavlink")
        return 2

    # ---- 2) MAVLINK ----
    print("\n[2] MAVLINK — kalp atışı bekleniyor (en fazla %.0f s)…" % a.sure)
    try:
        m = (mavutil.mavlink_connection(port) if port.startswith(("udp", "tcp"))
             else mavutil.mavlink_connection(port, baud=a.baud))
    except Exception as e:
        print("    ⛔ bağlanılamadı: %s" % e)
        return 2

    t0 = time.time()
    hb = None
    while time.time() - t0 < a.sure:
        hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if hb is not None:
            break
    if hb is None:
        print("    ⛔ KALP ATIŞI YOK — araç konuşmuyor.")
        print("       · Talon'a güç verildi mi?")
        print("       · SiK telsizlerinin ışığı yanıp sönüyor mu (eşleşme)?")
        print("       · baud doğru mu? (bu kurulumda 57600)")
        print("       · yayıncı zaten portu açmış olabilir → --port udp:127.0.0.1:14550")
        return 2
    print("    ✔ KALP ATIŞI VAR  (sistem %d, bileşen %d)"
          % (m.target_system, m.target_component))

    # ---- 3-5) veri topla ----
    print("\n[3] ARAÇ ve SENSÖRLER  (%.0f s dinleniyor)…" % min(a.sure, 8))
    veri = {}
    t0 = time.time()
    n = 0
    while time.time() - t0 < min(a.sure, 8):
        msg = m.recv_match(blocking=True, timeout=1.0)
        if msg is None:
            continue
        n += 1
        veri[msg.get_type()] = msg

    def rapor(baslik, satirlar):
        print("\n%s" % baslik)
        for s in satirlar:
            print("    %s" % s)

    h = veri.get("HEARTBEAT")
    armli = bool(h.base_mode & 128) if h else False
    kip = KIPLER.get(getattr(h, "custom_mode", -1), "?%s" % getattr(h, "custom_mode", "?"))
    rapor("    ARAÇ", [
        "uçuş kipi : %s" % kip,
        "arm       : %s" % ("⚠ ARMLI" if armli else "disarm"),
        "MAVLink mesajı: %d tip, %d paket" % (len(veri), n)])

    g = veri.get("GPS_RAW_INT")
    gp = veri.get("GLOBAL_POSITION_INT")
    sat = []
    if g:
        uydu = g.satellites_visible
        sat.append("fix       : %s   uydu: %d %s"
                   % (FIX.get(g.fix_type, "?"), uydu,
                      "✔" if g.fix_type >= 3 and uydu >= 8 else "⛔ YETERSİZ"))
    else:
        sat.append("⛔ GPS_RAW_INT gelmedi")
    if gp:
        sat.append("konum     : %.7f, %.7f" % (gp.lat / 1e7, gp.lon / 1e7))
        sat.append("irtifa    : %.1f m (ev/yerden)   %.1f m (AMSL)"
                   % (gp.relative_alt / 1000.0, gp.alt / 1000.0))
        sat.append("hız       : %.1f m/s"
                   % ((gp.vx ** 2 + gp.vy ** 2) ** 0.5 / 100.0))
        sat.append("yönelme   : %.1f°" % (gp.hdg / 100.0 if gp.hdg != 65535 else -1))
    rapor("    GPS / KONUM", sat)

    b = veri.get("SYS_STATUS")
    if b:
        rapor("    PİL", ["gerilim   : %.2f V" % (b.voltage_battery / 1000.0),
                          "akım      : %.1f A" % (b.current_battery / 100.0
                                                  if b.current_battery >= 0 else -1),
                          "kalan     : %d%%" % b.battery_remaining])
    att = veri.get("ATTITUDE")
    if att:
        import math
        rapor("    DURUŞ", ["yatış %.1f°  dikilme %.1f°  yönelme %.1f°"
                            % (math.degrees(att.roll), math.degrees(att.pitch),
                               math.degrees(att.yaw) % 360)])

    # ---- arm engelleri ----
    engeller = []
    for msg in (veri.get("STATUSTEXT"),):
        if msg is not None:
            engeller.append(msg.text.strip())
    if g and g.fix_type < 3:
        engeller.append("GPS 3B fix yok — ArduPlane arm ETMEZ")
    if g and g.satellites_visible < 6:
        engeller.append("uydu sayısı düşük (%d) — dışarı çıkın" % g.satellites_visible)

    print("\n" + "=" * 70)
    if engeller:
        print("  DURUM: ⚠ BAĞLANTI VAR, uçuşa hazır DEĞİL")
        for e in engeller:
            print("     · %s" % e)
    else:
        print("  DURUM: ✔ BAĞLANTI VAR ve temel sağlık iyi")
    print("=" * 70)
    print("\n  SONRAKİ ADIM:")
    print("     1) Bu testi KAPAT (seri portu bırak)")
    print("     2) ./reel/baslat_talon.sh <port> <drone-ip>")
    print("     3) Tarayıcı: http://localhost:8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
