#!/usr/bin/env python3
"""
preflight.py — Uçuş öncesi bağlantı ve sistem kontrolü.

Senaryo çalıştırmadan ÖNCE bunu çalıştırın. Uçağı arm etmez, motoru
döndürmez; yalnızca okur ve rapor eder.

Kullanım:
    # SITL
    python -m control.preflight

    # Gerçek uçak (SiK telsiz — panel KAPALI olmalı, port tek süreçlik)
    set MAV_ENDPOINT=COM3 & set MAV_BAUD=57600 & python -m control.preflight

Çıkış kodu 0 = uçuşa uygun, 1 = engelleyici sorun var.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control.mav_common import (
    connect_mavlink,
    get_attitude,
    get_battery,
    get_global_position,
    get_gps_status,
    get_mode,
    get_param,
    is_armed,
    GCS_SOURCE_SYSTEM,
)

OK = "  [OK]  "
UYARI = " [UYARI]"
HATA = " [HATA] "


class Rapor:
    """Kontrol sonuçlarını toplar; engelleyici hata var mı bilir."""

    def __init__(self):
        self.engelleyici = 0
        self.uyari = 0

    def ok(self, mesaj):
        print(f"{OK} {mesaj}")

    def uyar(self, mesaj):
        self.uyari += 1
        print(f"{UYARI} {mesaj}")

    def hata(self, mesaj):
        self.engelleyici += 1
        print(f"{HATA} {mesaj}")


def kontrol_baglanti(rapor):
    """MAVLink bağlantısı kurar; başarısızsa hiçbir kontrol anlamlı değildir."""
    hedef = os.environ.get("MAV_ENDPOINT", "udp:127.0.0.1:14542 (varsayılan)")
    print(f"\n--- BAĞLANTI --- ({hedef})")
    try:
        conn = connect_mavlink(heartbeat_timeout=15.0)
    except Exception as exc:
        rapor.hata(f"Bağlantı kurulamadı: {exc}")
        return None
    rapor.ok(f"Heartbeat alındı — sistem {conn.target_system}")
    return conn


def kontrol_sysid(conn, rapor):
    """
    GCS sistem ID kontrolü — RC override'ın ÇALIŞMASI buna bağlıdır.

    ArduPilot RC override paketlerini yalnızca bu parametreyle eşleşen
    kaynaktan kabul eder. Eşleşmezse kod sorunsuz çalışıyor görünür ama
    uçak hiçbir komutu dinlemez.

    Parametrenin adı firmware sürümüne göre değişir: yeni sürümlerde
    MAV_GCS_SYSID, eskilerde SYSID_MYGCS. İkisi de denenir.
    """
    print("\n--- RC OVERRIDE İZNİ ---")
    for ad in ("MAV_GCS_SYSID", "SYSID_MYGCS"):
        deger = get_param(conn, ad, timeout=4.0)
        if deger is None:
            continue
        if int(deger) == GCS_SOURCE_SYSTEM:
            rapor.ok(f"{ad} = {int(deger)} (bağlantımızla eşleşiyor)")
        else:
            rapor.hata(
                f"{ad} = {int(deger)} ama biz {GCS_SOURCE_SYSTEM} ile "
                f"bağlanıyoruz. RC override YOK SAYILIR. Düzeltmek için "
                f"araçta {ad}={GCS_SOURCE_SYSTEM} yapın."
            )
        return
    rapor.uyar("GCS sistem ID parametresi okunamadı (MAV_GCS_SYSID / "
               "SYSID_MYGCS) — RC override çalışmayabilir")


def kontrol_gps(rapor, conn):
    """3D fix olmadan otonom kalkış (TAKEOFF modu) reddedilir."""
    print("\n--- GPS ---")
    gps = get_gps_status(conn, timeout=5.0)
    if gps is None:
        rapor.hata("GPS_RAW_INT mesajı gelmiyor")
        return
    fix = gps["fix_type"]
    sat = gps["satellites"]
    if fix >= 3:
        rapor.ok(f"3D fix (fix_type={fix}, {sat} uydu, HDOP={gps['hdop']})")
        if sat < 8:
            rapor.uyar(f"Uydu sayısı düşük ({sat}) — 8+ önerilir")
    elif sat == 0:
        rapor.hata(f"3D fix YOK (fix_type={fix}, {sat} uydu) — otonom kalkış "
                   "reddedilecek. Bina içindeyseniz normaldir: GPS anteni "
                   "gökyüzünü görmeli. Dışarıda 1-3 dakika bekleyin.")
    else:
        rapor.hata(f"3D fix YOK (fix_type={fix}, {sat} uydu) — otonom kalkış "
                   "reddedilecek. Uydu sayısı artıyor, biraz daha bekleyin.")


def kontrol_telemetri(rapor, conn):
    """
    ATTITUDE akışı — pusula tabanlı dönüşün (turn_by) hayat damarı.

    Bu mesaj gelmezse run_plane_scenario'nun kare deseni dönüşleri
    zaman aşımına düşer ve uçak sürekli yatışta kalır.
    """
    print("\n--- TELEMETRİ AKIŞI ---")
    t0 = time.time()
    sayac = 0
    while time.time() - t0 < 3.0:
        if get_attitude(conn, timeout=0.5) is not None:
            sayac += 1
    hiz = sayac / 3.0
    if hiz >= 4.0:
        rapor.ok(f"ATTITUDE akışı {hiz:.1f} Hz")
    elif hiz > 0:
        rapor.uyar(f"ATTITUDE akışı yavaş ({hiz:.1f} Hz) — dönüşler "
                   "gecikmeli tepki verebilir, 10 Hz hedefleyin")
    else:
        rapor.hata("ATTITUDE mesajı HİÇ gelmiyor — pusula tabanlı "
                   "dönüşler çalışmaz")


def kontrol_batarya(rapor, conn):
    print("\n--- BATARYA ---")
    bat = get_battery(conn, timeout=5.0)
    if bat is None:
        rapor.uyar("SYS_STATUS okunamadı — batarya durumu bilinmiyor")
        return
    v = bat["voltage"]
    kalan = bat["remaining"]
    if v < 1.0:
        rapor.uyar(f"Batarya voltajı okunmuyor ({v:.1f}V) — güç modülü bağlı "
                   "değilse normaldir (yalnızca USB ile beslenirken böyledir)")
        return
    rapor.ok(f"Voltaj {v:.2f}V" + (f", kalan %{kalan}" if kalan is not None else ""))
    if kalan is not None and kalan < 30:
        rapor.uyar(f"Batarya düşük (%{kalan})")


def kontrol_durum(rapor, conn):
    print("\n--- ARAÇ DURUMU ---")
    armed = is_armed(conn, timeout=3.0)
    if armed is None:
        rapor.uyar("Arm durumu okunamadı")
    elif armed:
        rapor.uyar("Araç ZATEN ARMLI — motor dönebilir, pervaneden uzak durun")
    else:
        rapor.ok("Araç disarm (güvenli)")

    mod = get_mode(conn, timeout=3.0)
    if mod:
        rapor.ok(f"Aktif mod: {mod[1]} ({mod[0]})")
    else:
        rapor.uyar("Uçuş modu okunamadı")

    pos = get_global_position(conn, timeout=3.0)
    if pos:
        rapor.ok(f"Konum: {pos['lat']:.6f}, {pos['lon']:.6f} — "
                 f"göreli irtifa {pos['rel_alt']:.1f}m")
    else:
        rapor.uyar("GLOBAL_POSITION_INT okunamadı")


def kontrol_force_arm(rapor):
    """Force arm gerçek uçuşta pre-arm kontrollerini atlar — hatırlat."""
    print("\n--- GÜVENLİK AYARI ---")
    izin = os.environ.get("MAV_ALLOW_FORCE_ARM", "1")
    if izin in ("0", "false", "no"):
        rapor.ok("Force arm KAPALI — pre-arm kontrolleri işleyecek")
    else:
        rapor.uyar(
            "Force arm AÇIK — pre-arm kontrolleri ATLANACAK. Gerçek uçuşta "
            "MAV_ALLOW_FORCE_ARM=0 kullanmanız önerilir."
        )


def main():
    print("=" * 60)
    print("  UÇUŞ ÖNCESİ KONTROL")
    print("=" * 60)

    rapor = Rapor()
    conn = kontrol_baglanti(rapor)
    if conn is None:
        print("\nBağlantı yok — diğer kontroller atlandı.")
        print("=" * 60)
        return 1

    kontrol_durum(rapor, conn)
    kontrol_sysid(conn, rapor)
    kontrol_gps(rapor, conn)
    kontrol_telemetri(rapor, conn)
    kontrol_batarya(rapor, conn)
    kontrol_force_arm(rapor)

    print("\n" + "=" * 60)
    if rapor.engelleyici:
        print(f"  SONUÇ: {rapor.engelleyici} ENGELLEYİCİ SORUN, "
              f"{rapor.uyari} uyarı — UÇMAYIN")
        print("=" * 60)
        return 1
    print(f"  SONUÇ: Engelleyici sorun yok ({rapor.uyari} uyarı)")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
