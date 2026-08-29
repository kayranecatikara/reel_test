#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
TALON YAYINCISI — hedef GPS'ini 5 Hz ile drone bilgisayarına yayınlar
================================================================================
TALON BİLGİSAYARINDA çalışır. TEK İŞİ: Talon'un konumunu, GPS güdüm
denklemine girecek biçimde yaymak.

⛔ SERİ PORTU TEK SÜREÇ AÇABİLİR — VE BU BİR TUZAKTIR.
   `talon_arayuz` belgesinde yazılı: "Panel çalışırken başka bir Python
   betiği aynı COM portunu açamaz." Yani yayıncı ile arayüz aynı anda
   telsize bağlanamaz.
   ÇÖZÜM: bu program bir MAVLink DAĞITICISIDIR (hub). Seri portu O açar,
   trafiği yerel bir UDP portuna aynalar. Arayüz artık seri porta değil
   O UDP'ye bağlanır ve HER ŞEY (görev yükleme, RC override, mod
   değiştirme) çalışmaya devam eder.

        [Pixhawk] --SiK--> [seri] --> YAYINCI --+--> udp:14550  (talon_arayuz)
                                                |
                                                +--> udp:47800  (drone bilgisayarı)
                                                     5 Hz hedef paketi

   Arayüzü şöyle başlatın:
        MAV_ENDPOINT=udp:127.0.0.1:14550 ./baslat.sh

⭐ YAYIN BİÇİMİ = YARIŞMA SUNUCUSUNUN BİÇİMİ (haberleşme dokümanı §7.2).
   Böylece drone tarafındaki kod bugün ile yarışma günü arasında HİÇ
   DEĞİŞMEZ; yalnız verinin geldiği adres değişir.

⚠ NİYE 5 Hz: yarışma sunucusu 1-2 Hz veriyor ve o bizim tavanımız değil,
  ONUN sınırı. Denemede daha hızlı veri, GPS güdümünün gerçek yeteneğini
  görmemizi sağlar. Güdüm tarafı her iki hızda da çalışır — `hedef.py`
  paket yaşına bakar, hızına değil.
================================================================================
"""
import argparse
import json
import os
import socket
import sys
import threading
import time


def _arg():
    a = argparse.ArgumentParser(description="Talon hedef yayıncısı + MAVLink hub")
    a.add_argument("--port", default=os.environ.get("MAV_ENDPOINT", ""),
                   help="Pixhawk seri portu (/dev/ttyUSB0, COM3) ya da udp:...")
    a.add_argument("--baud", type=int,
                   default=int(os.environ.get("MAV_BAUD", 57600)))
    a.add_argument("--hedef", default="255.255.255.255",
                   help="drone bilgisayarının IP'si (varsayılan: yayın)")
    a.add_argument("--hedef-port", type=int, default=47800)
    a.add_argument("--ayna", default="udpout:127.0.0.1:14550",
                   help="talon_arayuz'un bağlanacağı UDP (boş = ayna yok)")
    a.add_argument("--hz", type=float, default=5.0)
    a.add_argument("--takim", type=int,
                   default=int(os.environ.get("DOW_TAKIM_NO", 0)))
    a.add_argument("--sahte", action="store_true",
                   help="Pixhawk yok — daire çizen sahte bir Talon yayınla")
    return a.parse_args()


class Yayinci:
    def __init__(self, a):
        self.a = a
        self.sok = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sok.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.durum = {"enlem": None, "boylam": None, "irtifa_ev": None,
                      "hiz": 0.0, "t": 0.0}
        self.n_yayin = 0
        self.n_mavlink = 0
        self._kilit = threading.Lock()

    # ------------------------------------------------------------------
    def guncelle(self, enlem, boylam, irtifa_ev, hiz):
        with self._kilit:
            self.durum.update(enlem=enlem, boylam=boylam,
                              irtifa_ev=irtifa_ev, hiz=hiz,
                              t=time.monotonic())

    def paket(self):
        with self._kilit:
            d = dict(self.durum)
        if d["enlem"] is None:
            return None
        # `saat_farki`: verinin YAŞI, milisaniye. Sunucu bu alanı böyle
        # kullanıyor; aynı anlamı koruyoruz ki drone tarafı ayırt etmesin.
        yas_ms = int(max(0.0, (time.monotonic() - d["t"])) * 1000.0)
        return {"sunucu_saati": _saat(),
                "hedef_iha_verileri": [{
                    "takim_no": self.a.takim,
                    "enlem": round(d["enlem"], 7),
                    "boylam": round(d["boylam"], 7),
                    "irtifa_ev": round(d["irtifa_ev"], 1),
                    "hiz": round(d["hiz"], 1),
                    "saat_farki": yas_ms}]}

    def yayinla(self):
        p = self.paket()
        if p is None:
            return False
        try:
            self.sok.sendto(json.dumps(p).encode("utf-8"),
                            (self.a.hedef, self.a.hedef_port))
            self.n_yayin += 1
            return True
        except Exception:
            return False


def _saat():
    t = time.localtime()
    return {"saat": t.tm_hour, "dakika": t.tm_min, "saniye": t.tm_sec,
            "milisaniye": int((time.time() % 1.0) * 1000)}


def _sahte_dongu(y):
    """Pixhawk yokken: 40 m irtifada, 200 m yarıçaplı daire çizen Talon."""
    import math
    e0, b0 = 41.10500, 29.02300
    R, V = 200.0, 22.0
    t0 = time.time()
    while True:
        t = time.time() - t0
        w = V / R
        x, yy = R * math.cos(w * t), R * math.sin(w * t)
        # yaklaşık: 1° enlem ~ 111 km, 1° boylam ~ 111 km * cos(enlem)
        e = e0 + (x / 111320.0)
        b = b0 + (yy / (111320.0 * math.cos(math.radians(e0))))
        y.guncelle(e, b, 40.0, V)
        time.sleep(0.05)


def main():
    a = _arg()
    print("=" * 70)
    print("  TALON YAYINCISI — hedef GPS'i %g Hz" % a.hz)
    print("=" * 70)
    y = Yayinci(a)

    if a.sahte:
        print("  KAYNAK    : SAHTE (200 m yarıçaplı daire, 22 m/s, 40 m)")
        threading.Thread(target=_sahte_dongu, args=(y,), daemon=True).start()
    else:
        if not a.port:
            print("⛔ --port verilmedi (Pixhawk seri portu).")
            print("   ls -l /dev/serial/by-id/   ·   Windows: COM3")
            print("   Donanımsız denemek için: --sahte")
            return 2
        try:
            from pymavlink import mavutil
        except ImportError:
            print("⛔ pymavlink yok:  pip install pymavlink")
            return 2
        print("  KAYNAK    : %s @ %d baud" % (a.port, a.baud))
        try:
            m = (mavutil.mavlink_connection(a.port, baud=a.baud)
                 if not a.port.startswith(("udp", "tcp"))
                 else mavutil.mavlink_connection(a.port))
        except Exception as e:
            print("⛔ bağlanılamadı: %s" % e)
            return 2
        ayna = None
        if a.ayna:
            try:
                ayna = mavutil.mavlink_connection(a.ayna, input=False)
                print("  AYNA      : %s  ->  talon_arayuz buraya bağlanır" % a.ayna)
                print("              MAV_ENDPOINT=udp:127.0.0.1:14550 ./baslat.sh")
            except Exception as e:
                print("  AYNA      : ⛔ açılamadı (%s) — yalnız yayın yapılacak" % e)
        threading.Thread(target=_mavlink_dongu, args=(y, m, ayna),
                         daemon=True).start()

    print("  YAYIN     : udp://%s:%d" % (a.hedef, a.hedef_port))
    print("  ⛔ Drone bilgisayarı aynı ağda olmalı. Yayın (broadcast)")
    print("     engelliyse --hedef <drone-ip> ile doğrudan gönder.")
    print("=" * 70)

    periyot = 1.0 / max(0.5, a.hz)
    son_rapor = 0.0
    try:
        while True:
            t0 = time.monotonic()
            y.yayinla()
            if t0 - son_rapor >= 2.0:
                son_rapor = t0
                d = y.durum
                if d["enlem"] is None:
                    print("  ⚠ GPS bekleniyor... (MAVLink paketi: %d)" % y.n_mavlink)
                else:
                    print("  %7.4f, %7.4f  irtifa %5.1f m  hız %4.1f m/s   "
                          "yayın %d  mavlink %d"
                          % (d["enlem"], d["boylam"], d["irtifa_ev"],
                             d["hiz"], y.n_yayin, y.n_mavlink))
            uyku = periyot - (time.monotonic() - t0)
            time.sleep(uyku if uyku > 0 else 0.0)
    except KeyboardInterrupt:
        print("\n  kapandı.")
    return 0


def _mavlink_dongu(y, m, ayna):
    """MAVLink'i oku, hedefi çıkar, aynaya geçir; aynadan geleni araca yolla."""
    ev = {"alt": None}
    while True:
        msg = m.recv_match(blocking=True, timeout=1.0)
        if msg is None:
            continue
        y.n_mavlink += 1
        if ayna is not None:
            try:
                ayna.write(msg.get_msgbuf())
            except Exception:
                pass
        tip = msg.get_type()
        if tip == "GLOBAL_POSITION_INT":
            # ⚠ `relative_alt` EV (kalkış) seviyesine göredir — şartnamenin
            #   `irtifa_ev` alanı da öyle. `alt` ise AMSL'dir; karıştırmak
            #   arazi kotu kadar sistematik hata verir.
            y.guncelle(msg.lat / 1e7, msg.lon / 1e7,
                       msg.relative_alt / 1000.0,
                       (msg.vx ** 2 + msg.vy ** 2) ** 0.5 / 100.0)
        elif tip == "VFR_HUD" and y.durum["enlem"] is not None:
            with y._kilit:
                y.durum["hiz"] = float(msg.groundspeed)
        # aynadan (arayüzden) gelen komutları araca geçir
        if ayna is not None:
            try:
                g = ayna.recv_match(blocking=False)
                if g is not None:
                    m.write(g.get_msgbuf())
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
