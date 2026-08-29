#!/usr/bin/env python3
"""
zorla_arm.py — TEZGÂH TESTİ için force arm / disarm.

NEDEN GEREKLİ
    Motor MAIN 6'da ve Throttle (SERVO6_FUNCTION = 70) fonksiyonunda.
    Bu fonksiyonda arm koruması vardır: araç DISARM iken çıkış
    SERVO6_MIN'de (1000 µs) kilitlenir, motor hiç dönmez. Yani kapalı
    ortamda motoru sınamak için arm şart.

    Kapalı ortamda GPS ve pusula yok, normal arm pre-arm kontrollerine
    takılır. force arm (magic 2989) bu kontrolleri ATLAR.

    UÇUŞTA KULLANILMAZ. Bu araç yalnızca tezgâh/atölye testi içindir.

ÖN KOŞULLAR — arm başarılı olsa bile motor dönmeyebilir
    · Uçuş modu MANUAL olmalı. RTL/AUTO'da otopilot gazı kendi yönetir;
      telsiz ya da batarya failsafe'i moda RTL yaptıysa motor dönmez.
      (VrA düğmesi MANUAL konumunda + kumanda AÇIK.)
    · Batarya bağlı ve BATT_LOW_VOLT'un (21.0 V) üstünde olmalı; altındaysa
      batarya failsafe'i tekrar RTL'e atar.

KULLANIM
    python -m control.zorla_arm            # force arm
    python -m control.zorla_arm disarm     # disarm

PERVANE TAKILIYSA: kimse pervane düzleminde durmasın, uçak sabitli olsun.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymavlink import mavutil

from control.mav_common import (
    arm,
    connect_mavlink,
    disarm,
    get_battery,
    get_param,
    is_armed,
)


def _durum_yaz(conn, baslik):
    hb = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
    mod = mavutil.mode_string_v10(hb) if hb else "?"
    print(f"  {baslik}: mod={mod}  {'ARMLI' if is_armed(conn, timeout=3) else 'disarm'}")
    return mod


def main():
    istek = sys.argv[1].lower() if len(sys.argv) > 1 else "arm"
    if istek not in ("arm", "disarm"):
        print("Kullanım: python -m control.zorla_arm [arm|disarm]")
        return 2

    print("=" * 58)
    print(f"  TEZGÂH {istek.upper()}  (force)")
    print("=" * 58)

    conn = connect_mavlink()
    print()
    mod = _durum_yaz(conn, "önce")

    if istek == "disarm":
        disarm(conn, force=True)
        time.sleep(1.0)
        _durum_yaz(conn, "sonra")
        return 0

    # --- arm yolu: motoru döndürmeyi engelleyecek durumları önden söyle ---
    b = get_battery(conn, timeout=4.0)
    if b and b["voltage"] < 1.0:
        print("\n  UYARI: Batarya okunmuyor (0 V) — bağlı değil.")
        print("  ESC güç almadan motor dönmez.")
    elif b:
        dusuk = get_param(conn, "BATT_LOW_VOLT", timeout=4) or 0
        print(f"\n  Batarya: {b['voltage']:.2f} V")
        if b["voltage"] < dusuk:
            # Eşiğin altında olmak tek başına gazı kesmez — kesen, failsafe
            # EYLEMİDİR. Tezgâh testinde BATT_FS_LOW_ACT geçici olarak 0
            # yapılıyor; o hâlde "gaz kesilir" demek yanıltıcı olurdu.
            eylem = get_param(conn, "BATT_FS_LOW_ACT", timeout=4) or 0
            if int(eylem) == 0:
                print(f"  Not: BATT_LOW_VOLT ({dusuk}) altında ama "
                      "BATT_FS_LOW_ACT = 0 — failsafe eylemi kapalı.")
                print("  TESTTEN SONRA 1'E GERİ ALIN.")
            else:
                print(f"  UYARI: BATT_LOW_VOLT ({dusuk}) altında ve "
                      f"BATT_FS_LOW_ACT = {int(eylem)} — arm eder etmez "
                      "failsafe modu RTL'e atar, motor dönmez.")

    if mod != "MANUAL":
        print(f"\n  UYARI: Mod {mod}. Motor testi için MANUAL gerekir.")
        print("  Kumandayı açıp VrA'yı MANUAL konumuna alın.")

    sonuc = arm(conn, force=True)
    time.sleep(1.5)
    print()
    _durum_yaz(conn, "sonra")

    if not is_armed(conn, timeout=3):
        print(f"\n  ARM OLMADI (sonuç: {sonuc})")
        return 1

    print("\n  ARM oldu. Motor testi için:")
    print("      python -m control.motor_gaz 1200 5")
    print("  Bitince disarm etmeyi unutmayın:")
    print("      python -m control.zorla_arm disarm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
