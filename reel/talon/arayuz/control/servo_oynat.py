#!/usr/bin/env python3
"""
servo_oynat.py — Tek bir servoyu süpürerek sağlamlığını test eder.

Servonun takılıp takılmadığını, dişlisinin atlayıp atlamadığını, uç
noktalara oturup oturmadığını anlamak için. Uçağın hiçbir yerine monte
olmasına gerek yok; servoyu elinize alıp dinleyerek de izleyebilirsiniz.

Kullanım:
    python -m control.servo_oynat            # CH1'i tam açıyla süpürür
    python -m control.servo_oynat 2          # CH2'yi süpürür
    python -m control.servo_oynat 1 hizli    # hızlı süpürme (0.8 sn uçtan uca)
    python -m control.servo_oynat 1 dar      # dar açıyla (nazik test)
    python -m control.servo_oynat 1 adim     # kademeli: uçlarda bekler
    python -m control.servo_oynat 1 notr     # KOL TAKMA: merkezde sabit tutar

Süpürme aralığı KARTTAN okunur (RCn_MIN / RCn_TRIM / RCn_MAX), sabit
varsayılmaz — aksi halde servo kapasitesinin altında sürülür.

Durdurmak için Ctrl+C — override bırakılır, servo serbest kalır.

NEYE BAKACAKSINIZ
-----------------
  Sağlam servo : akıcı hareket, sabit hız, uçlarda net durur, sessiz
  Şüpheli      : takılma, sıçrama, "grrr" sesi, bir bölgede hiç dönmeme,
                 uca gelince zorlanma sesi, ısınma

Servo uçlara vurup zorlanıyorsa "dar" modunu kullanın — mekanik sınırlara
dayanmak sağlam bir servoyu da bozar.
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
    get_mode,
    get_param,
    set_mode,
    PLANE_MODE_MANUAL,
)

ADIM_HZ = 50            # gönderim hızı
SUPURME_SURESI = 2.5    # bir uçtan diğerine geçiş süresi (saniye)
HIZLI_SURESI = 0.8      # "hizli" modunda


def _kanal_sinirlari(conn, kanal):
    """
    Kanalın GERÇEK sınırlarını karttan okur (RC kalibrasyonundan).

    Sabit bir PWM aralığı varsaymak yanlış olur: bu kartta RC1 aralığı
    1026-2004, yani 1150-1850 göndermek servoyu %70 kapasitede sürer ve
    "servo dar açıyla dönüyor" izlenimi verir.
    """
    alt = get_param(conn, f"RC{kanal}_MIN", timeout=4)
    ust = get_param(conn, f"RC{kanal}_MAX", timeout=4)
    orta = get_param(conn, f"RC{kanal}_TRIM", timeout=4)
    if alt is None or ust is None:
        print(f"  UYARI: RC{kanal}_MIN/MAX okunamadı, varsayılan kullanılıyor")
        return 1100, 1900, 1500
    if orta is None:
        orta = (alt + ust) / 2
    return int(alt), int(ust), int(orta)

_dur = False


def _sig(_s, _f):
    global _dur
    _dur = True


def _gonder(conn, kanal, pwm):
    """Yalnızca istenen kanalı override eder, diğerlerine dokunmaz (0)."""
    kanallar = [0] * 8
    kanallar[kanal - 1] = int(pwm)
    conn.mav.rc_channels_override_send(
        conn.target_system, conn.target_component, *kanallar)


def _supur(conn, kanal, bas, son, sure):
    """bas → son arası PWM'i yumuşakça gezdirir."""
    adim = max(1, int(sure * ADIM_HZ))
    for i in range(adim + 1):
        if _dur:
            return
        pwm = bas + (son - bas) * i / adim
        _gonder(conn, kanal, pwm)
        time.sleep(1.0 / ADIM_HZ)


def main():
    global _dur

    kanal = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    mod = sys.argv[2].lower() if len(sys.argv) > 2 else "genis"

    if not 1 <= kanal <= 8:
        print("Kanal 1-8 arasında olmalı.")
        return 2

    if kanal == 3:
        print("\n" + "!" * 60)
        print("  DİKKAT: CH3 gaz kanalıdır. ESC bağlıysa MOTOR DÖNEBİLİR.")
        print("  Pervane takılıysa DURUN.")
        print("!" * 60)
        if input("\nDevam edilsin mi? (evet yazın): ").strip().lower() != "evet":
            print("İptal edildi.")
            return 0

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    print("=" * 58)
    print(f"  SERVO TESTİ — CH{kanal}   (mod: {mod})")
    print("=" * 58)

    conn = connect_mavlink()
    keepalive = GCSKeepalive(conn, interval=0.2)
    keepalive.start()

    tam_alt, tam_ust, MERKEZ = _kanal_sinirlari(conn, kanal)
    if mod == "dar":
        # Merkez çevresinde %30 — mekanik sınırlara dayanmayan nazik test
        alt = int(MERKEZ - (MERKEZ - tam_alt) * 0.3)
        ust = int(MERKEZ + (tam_ust - MERKEZ) * 0.3)
    else:
        alt, ust = tam_alt, tam_ust
    sure = HIZLI_SURESI if mod == "hizli" else SUPURME_SURESI

    print(f"  Kanal sınırları (karttan): {tam_alt} – {MERKEZ} – {tam_ust}")
    print(f"  Kullanılan aralık        : {alt} – {ust}")
    print(f"  Uçtan uca süre           : {sure} sn")

    hiz = get_param(conn, "SERVO_RATE", timeout=4)
    if hiz is not None:
        print(f"  Servo çıkış frekansı     : {int(hiz)} Hz", end="")
        print("   ← düşük; dijital servoda kesikli hareket yapar"
              if hiz <= 50 else "")

    m = get_mode(conn, timeout=3.0)
    print(f"  Mod: {m[1] if m else 'bilinmiyor'} → MANUAL'e alınıyor")
    set_mode(conn, PLANE_MODE_MANUAL)
    time.sleep(0.5)

    print("\n  Merkeze getiriliyor...")
    for _ in range(int(1.5 * ADIM_HZ)):
        if _dur:
            break
        _gonder(conn, kanal, MERKEZ)
        time.sleep(1.0 / ADIM_HZ)

    if mod == "notr":
        # KOL TAKMA MODU — servo merkezde sabit tutulur.
        # Kolu bu haldeyken takın: kumanda yüzeyi tam ortadayken kol
        # dişliye otursun. Yanlış açıyla takılan kol, servonun bir yöne
        # çok diğer yöne az hareket etmesine yol açar.
        print()
        print("  " + "=" * 54)
        print(f"  SERVO MERKEZDE TUTULUYOR ({MERKEZ} µs)")
        print("  " + "=" * 54)
        print("  Şimdi servo kolunu takın:")
        print("    1. Kolu dişliden çıkarın")
        print("    2. Kumanda yüzeyini elle tam ORTAYA getirin")
        print("    3. Kolu, yüzey ortadayken oturacak açıda takın")
        print("    4. Vidasını sıkın")
        print()
        print("  Bittiğinde Ctrl+C ile çıkın.\n")
        try:
            while not _dur:
                _gonder(conn, kanal, MERKEZ)
                time.sleep(1.0 / ADIM_HZ)
        except KeyboardInterrupt:
            pass
        print("\n  Merkezleme bitti, servo serbest bırakılıyor...")
        clear_rc_overrides(conn)
        time.sleep(0.3)
        clear_rc_overrides(conn)
        keepalive.stop()
        return 0

    print("  Süpürme başlıyor — durdurmak için Ctrl+C\n")

    tur = 0
    try:
        while not _dur:
            tur += 1
            if mod == "adim":
                # Kademeli: uçlarda ve merkezde bekler — oturma kontrolü
                for hedef, ad in ((alt, "ALT uç"), (MERKEZ, "merkez"),
                                  (ust, "ÜST uç"), (MERKEZ, "merkez")):
                    if _dur:
                        break
                    print(f"  Tur {tur}: {ad} ({hedef})")
                    _supur(conn, kanal, MERKEZ, hedef, 1.0)
                    t0 = time.time()
                    while time.time() - t0 < 1.5 and not _dur:
                        _gonder(conn, kanal, hedef)
                        time.sleep(1.0 / ADIM_HZ)
            else:
                print(f"  Tur {tur}: {alt} → {ust} → {alt}")
                _supur(conn, kanal, alt, ust, sure)
                _supur(conn, kanal, ust, alt, sure)
    except KeyboardInterrupt:
        pass

    print("\n  Durduruluyor, servo serbest bırakılıyor...")
    clear_rc_overrides(conn)
    time.sleep(0.3)
    clear_rc_overrides(conn)
    keepalive.stop()
    print(f"  Bitti — {tur} tur yapıldı.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
