#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
KUMANDA BULUCU — "kumandayı göremiyorum" sorununu adım adım daraltır
================================================================================
Sorun ÜÇ katmandan birinde olur ve bu araç hangisi olduğunu söyler:

  1. FİZİKSEL   : USB hiç enumerate olmuyor    -> lsusb'de YOK
  2. SÜRÜCÜ/KİP : USB var ama HID joystick yok -> /dev/input/js* YOK
  3. YAZILIM    : cihaz var ama pygame açamıyor

⛔ EN SIK SEBEP (RadioMaster Pocket): kumandada İKİ USB-C portu vardır.
   Alttaki/arkadaki ŞARJ portudur ve VERİ TAŞIMAZ. Bilgisayar bağlantısı
   ÜSTTEKİ porttan yapılır. Şarj portuna takılınca `lsusb`'de HİÇ görünmez.

⛔ İKİNCİ SEBEP: şarj kabloları veri taşımaz. ESP32'yi bağlarken kullandığın
   kablo VERİ kablosudur (çalıştığını biliyoruz) — onu dene.

Kullanım:
    python3 reel/araclar/kumanda_bul.py           # anlık durum
    python3 reel/araclar/kumanda_bul.py --izle    # tak-çıkar izle
================================================================================
"""
import glob
import os
import subprocess
import sys
import time


def _usb():
    try:
        c = subprocess.run(["lsusb"], capture_output=True, text=True, timeout=5)
        return [x for x in c.stdout.splitlines() if x.strip()]
    except Exception:
        return []


def _js():
    return sorted(glob.glob("/dev/input/js*"))


def _hid_adlari():
    try:
        with open("/proc/bus/input/devices") as f:
            return [x.split('"')[1] for x in f if x.startswith("N: Name")]
    except Exception:
        return []


def _pygame():
    try:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        import pygame
        pygame.init()
        try:
            pygame.joystick.quit()
        except Exception:
            pass
        pygame.joystick.init()
        n = pygame.joystick.get_count()
        if n == 0:
            return None, "oyun kolu yok"
        j = pygame.joystick.Joystick(0); j.init()
        return (j.get_name(), j.get_numaxes()), None
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e)


def rapor():
    print("=" * 70)
    print("  KUMANDA BULUCU")
    print("=" * 70)
    usb = _usb()
    js = _js()
    pg, pghata = _pygame()
    radyo = [x for x in usb
             if any(a in x.lower() for a in
                    ("radiomaster", "opentx", "edgetx", "jumper", "stm",
                     "0483", "1209", "c0de", "4f54"))]

    print("\n[1] FİZİKSEL — USB enumerate oldu mu")
    if radyo:
        for x in radyo:
            print("    ✔ %s" % x)
    else:
        print("    ⛔ lsusb'de kumanda YOK  (%d cihaz listeli)" % len(usb))
        print("       → RadioMaster Pocket'ta İKİ USB-C portu var:")
        print("         ALT/ARKA = ŞARJ (veri taşımaz) · ÜST = VERİ")
        print("         Kabloyu ÜSTTEKİ porta tak.")
        print("       → Kablo VERİ kablosu mu? ESP32'de çalışan kabloyu dene.")
        print("       → Kumanda AÇIK mı?")

    print("\n[2] SÜRÜCÜ/KİP — HID oyun kolu oluştu mu")
    if js:
        print("    ✔ %s" % ", ".join(js))
    else:
        print("    ⛔ /dev/input/js* YOK")
        if radyo:
            print("       USB var ama oyun kolu yok → EdgeTX'te USB kipi:")
            print("         SYS → Hardware → USB Mode = Joystick")
            print("       (Storage/Serial ise HID cihazı hiç oluşmaz)")

    print("\n[3] YAZILIM — pygame açabiliyor mu")
    if pg:
        print("    ✔ %s  (%d eksen)" % (pg[0], pg[1]))
    else:
        print("    ⛔ %s" % pghata)

    print("\n" + "-" * 70)
    if pg:
        print("  SONUÇ: ✔ HAZIR — paneli aç, kumanda kendiliğinden yakalanır")
        print("         (hakem 2 s'de bir arıyor; program açıkken takabilirsin)")
    elif js:
        print("  SONUÇ: cihaz var ama pygame açamıyor → izin/paket sorunu")
    elif radyo:
        print("  SONUÇ: ⛔ USB Mode = Joystick yapılmamış (katman 2)")
    else:
        print("  SONUÇ: ⛔ FİZİKSEL bağlantı yok (katman 1) — ÜST porta tak")
    print("-" * 70)
    return bool(pg)


def izle():
    print("Tak-çıkar izleniyor… Ctrl+C ile çık.\n")
    o_usb, o_js = set(_usb()), set(_js())
    print("  başlangıç: %d USB cihaz, %d oyun kolu" % (len(o_usb), len(o_js)))
    try:
        while True:
            time.sleep(1.0)
            y_usb, y_js = set(_usb()), set(_js())
            for x in y_usb - o_usb:
                print("  ➕ USB TAKILDI : %s" % x)
            for x in o_usb - y_usb:
                print("  ➖ USB ÇIKARILDI: %s" % x)
            for x in y_js - o_js:
                print("  ⭐ OYUN KOLU OLUŞTU: %s" % x)
                pg, _ = _pygame()
                if pg:
                    print("     ✔ pygame görüyor: %s (%d eksen)" % pg)
            for x in o_js - y_js:
                print("  ➖ oyun kolu gitti: %s" % x)
            o_usb, o_js = y_usb, y_js
    except KeyboardInterrupt:
        print("\nçıkıldı.")


if __name__ == "__main__":
    if "--izle" in sys.argv:
        rapor(); print(); izle()
    else:
        sys.exit(0 if rapor() else 1)
