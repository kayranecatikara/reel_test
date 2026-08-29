#!/usr/bin/env python3
"""
komut.py — Tek tek komut göndermek için basit araç.

Senaryo çalıştırmadan önce parça parça test etmek, ya da uçuş sırasında
hızlıca müdahale etmek için. Her komut çalışır, sonucu yazar ve çıkar.

Kullanım:
    python -m control.komut durum          # telemetriyi oku (hiçbir şey yapmaz)
    python -m control.komut izle           # sürekli telemetri (Ctrl+C ile çık)
    python -m control.komut arm            # ARM et (motor dönebilir!)
    python -m control.komut disarm         # DISARM et
    python -m control.komut mod fbwa       # uçuş modu değiştir
    python -m control.komut modlar         # kullanılabilir modları listele
    python -m control.komut kalkis         # otonom kalkış (TAKEOFF modu)
    python -m control.komut eve            # RTL — kalkış noktasına dön
    python -m control.komut daire          # LOITER — bulunduğu yerde daire çiz
    python -m control.komut in             # iniş (aşağıdaki nota bakın)
    python -m control.komut dur            # RC override'ları bırak (otopilot devralır)
    python -m control.komut parametre FS_LONG_ACTN      # parametreyi oku
    python -m control.komut parametre FS_LONG_ACTN 1    # parametreyi yaz ve doğrula

Bağlantı ortam değişkeniyle seçilir (Windows):
    set MAV_ENDPOINT=COM3
    set MAV_BAUD=57600
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from control.mav_common import (
    clear_rc_overrides,
    connect_mavlink,
    disarm,
    get_param,
    set_param,
    get_attitude,
    get_battery,
    get_global_position,
    get_gps_status,
    get_mode,
    is_armed,
    arm as mav_arm,
    set_mode,
    PLANE_MODE_NAMES,
    PLANE_MODE_FBWA,
    PLANE_MODE_LOITER,
    PLANE_MODE_MANUAL,
    PLANE_MODE_RTL,
    PLANE_MODE_TAKEOFF,
)

import math

# Ad -> mod numarası (komut satırında kullanılan kısa adlar)
MOD_ADLARI = {ad.lower(): num for num, ad in PLANE_MODE_NAMES.items()}


def _baglan():
    return connect_mavlink()


def cmd_durum(conn):
    """Aracın anlık durumunu okur — hiçbir şey değiştirmez."""
    print("\n--- ARAÇ DURUMU ---")
    armed = is_armed(conn, timeout=3.0)
    print(f"  Arm      : {'ARMLI' if armed else 'disarm' if armed is not None else 'bilinmiyor'}")

    mod = get_mode(conn, timeout=3.0)
    print(f"  Mod      : {mod[1]} ({mod[0]})" if mod else "  Mod      : bilinmiyor")

    pos = get_global_position(conn, timeout=3.0)
    if pos:
        print(f"  Konum    : {pos['lat']:.6f}, {pos['lon']:.6f}")
        print(f"  İrtifa   : {pos['rel_alt']:.1f} m (kalkış noktasına göre)")
        if pos["hdg"] is not None:
            print(f"  Yön      : {pos['hdg']:.0f}°")

    att = get_attitude(conn, timeout=3.0)
    if att:
        print(f"  Yatış    : {math.degrees(att['roll']):.1f}°")
        print(f"  Burun    : {math.degrees(att['pitch']):.1f}°")

    gps = get_gps_status(conn, timeout=3.0)
    if gps:
        print(f"  GPS      : fix={gps['fix_type']}, {gps['satellites']} uydu")

    bat = get_battery(conn, timeout=3.0)
    if bat and bat["voltage"] > 1.0:
        kalan = f", %{bat['remaining']}" if bat["remaining"] is not None else ""
        print(f"  Batarya  : {bat['voltage']:.2f}V{kalan}")
    print()


def cmd_izle(conn):
    """Telemetriyi sürekli yazdırır (Ctrl+C ile çıkılır)."""
    print("Telemetri izleniyor — Ctrl+C ile çıkın\n")
    try:
        while True:
            pos = get_global_position(conn, timeout=1.0)
            att = get_attitude(conn, timeout=0.5)
            mod = get_mode(conn, timeout=0.5)
            armed = is_armed(conn, timeout=0.5)
            parcalar = []
            if mod:
                parcalar.append(f"{mod[1]:<10}")
            parcalar.append("ARMLI " if armed else "disarm")
            if pos:
                parcalar.append(f"irtifa {pos['rel_alt']:6.1f}m")
                if pos["hdg"] is not None:
                    parcalar.append(f"yön {pos['hdg']:3.0f}°")
            if att:
                parcalar.append(f"yatış {math.degrees(att['roll']):5.1f}°")
            print("  " + " | ".join(parcalar), end="\r", flush=True)
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\n\nİzleme durduruldu.")


def cmd_arm(conn):
    """
    Aracı arm eder.

    UYARI: Arm sonrası motor komut bekler. Yerde test ediyorsanız PERVANEYİ
    ÇIKARIN. ArduPlane MANUAL modda throttle 0 iken motoru döndürmez, ama
    yanlış bir throttle komutu her an gelebilir.
    """
    print("\n" + "!" * 60)
    print("  DİKKAT: ARM edilecek. Yerdeyseniz PERVANE ÇIKARILMIŞ olmalı.")
    print("  Herkesin uçaktan uzak olduğundan emin olun.")
    print("!" * 60)

    armed = is_armed(conn, timeout=3.0)
    if armed:
        print("\nAraç zaten ARMLI — bir şey yapılmadı.")
        return

    onay = input("\nDevam edilsin mi? (evet yazın): ").strip().lower()
    if onay != "evet":
        print("İptal edildi.")
        return

    print("\nARM ediliyor...")
    sonuc = mav_arm(conn, force=False, retries=3, retry_interval=2.0)
    if sonuc and sonuc[1] == 0:
        print("ARM BAŞARILI")
        time.sleep(1)
        cmd_durum(conn)
    else:
        print(f"ARM BAŞARISIZ — sonuç: {sonuc}")
        print("Sebep genelde pre-arm kontrolüdür; yukarıdaki araç mesajına bakın.")


def cmd_disarm(conn):
    """Aracı disarm eder."""
    print("\nDISARM ediliyor...")
    clear_rc_overrides(conn)
    sonuc = disarm(conn, force=False, retries=3)
    if sonuc and sonuc[1] == 0:
        print("DISARM BAŞARILI")
    else:
        print(f"DISARM sonucu: {sonuc}")
        print("Havadayken disarm otopilot tarafından reddedilir (doğrusu budur).")


def cmd_mod(conn, args):
    """Uçuş modunu değiştirir."""
    if not args:
        print("Kullanım: python -m control.komut mod <ad>")
        print("Modları görmek için: python -m control.komut modlar")
        return
    ad = args[0].lower()
    if ad not in MOD_ADLARI:
        print(f"Bilinmeyen mod: {ad}")
        print(f"Seçenekler: {', '.join(sorted(MOD_ADLARI))}")
        return
    num = MOD_ADLARI[ad]
    print(f"\nMod değiştiriliyor: {ad.upper()} ({num})")
    if set_mode(conn, num):
        print("Mod değişti.")
    else:
        print("Mod doğrulanamadı — araç reddetmiş olabilir.")


def cmd_modlar(_conn):
    """Kullanılabilir modları listeler."""
    print("\n--- ARDUPLANE UÇUŞ MODLARI ---")
    aciklama = {
        "manual": "Doğrudan kumanda — otopilot karışmaz",
        "stabilize": "Kanatları düz tutar, kumanda ile yönlendirilir",
        "fbwa": "Yatış/burun açısı hedefi — senaryolarda kullanılan mod",
        "fbwb": "FBWA + irtifa koruma",
        "cruise": "Yön ve irtifa kilidi",
        "auto": "Görev planını uygular (waypoint)",
        "rtl": "Kalkış noktasına döner — ACİL DURUMDA BUNU KULLANIN",
        "loiter": "Bulunduğu yerde daire çizer",
        "takeoff": "Otonom kalkış",
        "guided": "Yer istasyonundan hedef nokta ile yönlendirme",
        "circle": "Sabit daire (failsafe modu)",
        "acro": "Akrobasi — açı limiti yok",
    }
    for ad in sorted(MOD_ADLARI):
        if ad in aciklama:
            print(f"  {ad:<12} ({MOD_ADLARI[ad]:>2})  {aciklama[ad]}")
    print()


def cmd_kalkis(conn):
    """Otonom kalkış — TAKEOFF modu."""
    print("\nOtonom kalkış başlatılıyor (TAKEOFF modu)...")
    print("Uçak TKOFF_ALT irtifasına tırmanacak.")
    if not is_armed(conn, timeout=3.0):
        print("UYARI: Araç disarm — önce arm edin.")
        return
    set_mode(conn, PLANE_MODE_TAKEOFF)
    print("TAKEOFF modu verildi. İzlemek için: python -m control.komut izle")


def cmd_eve(conn):
    """RTL — kalkış noktasına dön."""
    print("\nRTL: kalkış noktasına dönülüyor...")
    clear_rc_overrides(conn)
    if set_mode(conn, PLANE_MODE_RTL):
        print("RTL aktif. Uçak eve dönüp orada daire çizecek.")
        print("RTL_AUTOLAND parametresi ayarlıysa otomatik iniş de yapar.")
    else:
        print("RTL doğrulanamadı.")


def cmd_daire(conn):
    """LOITER — bulunduğu yerde daire çiz."""
    print("\nLOITER: bulunduğu yerde daire çiziliyor...")
    clear_rc_overrides(conn)
    if set_mode(conn, PLANE_MODE_LOITER):
        print("LOITER aktif. Uçak burada bekleyecek — düşünmek için zaman kazandırır.")


def cmd_in(conn):
    """İniş — ArduPlane'de sabit kanat inişi hakkında bilgi + RTL."""
    print("""
--- SABİT KANAT İNİŞİ ---

ArduPlane'de multicopter gibi tek tuşla "LAND" modu YOKTUR. İniş için
üç yol var:

  1. RTL (en pratik)
     Uçak kalkış noktasına döner ve orada daire çizer. Aracınızda
     RTL_AUTOLAND=2 ayarlıysa ve bir iniş görevi tanımlıysa otomatik iner.
     Değilse tepenizde bekler, siz devralıp indirirsiniz.

  2. Manuel iniş (en yaygın)
     Vericinizden FBWA veya MANUAL moda alıp kendiniz indirirsiniz.
     İlk uçuşlarda bunu tercih edin.

  3. AUTO görev
     Mission Planner'da DO_LAND_START içeren bir iniş görevi hazırlarsanız
     AUTO modu tam otonom indirir. Hazırlık ister.

Şimdi RTL veriliyor — uçak eve dönecek. Devralmak isterseniz vericinizden
mod değiştirin veya: python -m control.komut mod fbwa
""")
    onay = input("RTL verilsin mi? (evet yazın): ").strip().lower()
    if onay == "evet":
        cmd_eve(conn)
    else:
        print("İptal edildi.")


def cmd_dur(conn):
    """RC override'ları bırakır — otopilot kontrolü devralır."""
    print("\nRC override'lar bırakılıyor...")
    clear_rc_overrides(conn)
    time.sleep(0.5)
    clear_rc_overrides(conn)
    print("Bırakıldı. Otopilot/verici kontrolü devraldı.")


def cmd_parametre(conn, args):
    """
    Araçtaki bir parametreyi okur, değer verilirse yazar ve geri okuyup doğrular.

    Uçuş güvenliği parametrelerini sahada elle düzeltmek için. Mission Planner
    olmadan da FS_LONG_ACTN, FENCE_RADIUS gibi değerler değiştirilebilsin diye
    eklendi.

    Yazma işlemi DOĞRULANIR: set_param sonrası değer geri okunur ve
    eşleşmiyorsa hata verir. Sessizce yazılmamış bir güvenlik parametresi,
    yazılmadığını bilmemekten daha tehlikelidir.
    """
    if not args:
        print("Kullanım: python -m control.komut parametre AD [DEGER]")
        return 2

    ad = args[0].upper()
    mevcut = get_param(conn, ad, timeout=6.0)
    if mevcut is None:
        print(f"{ad}: OKUNAMADI (araç bu parametreyi bilmiyor olabilir)")
        return 1
    print(f"{ad} = {mevcut}")

    if len(args) < 2:
        return 0

    try:
        hedef = float(args[1])
    except ValueError:
        print(f"Geçersiz değer: {args[1]}")
        return 2

    if abs(mevcut - hedef) < 1e-6:
        print(f"Zaten {hedef} — değişiklik yapılmadı.")
        return 0

    print(f"{ad}: {mevcut} -> {hedef} yazılıyor...")
    set_param(conn, ad, hedef)
    time.sleep(0.5)
    yeni = get_param(conn, ad, timeout=6.0)
    if yeni is None:
        print(f"UYARI: {ad} yazıldı ama geri okunamadı — doğrulanamadı!")
        return 1
    if abs(yeni - hedef) < 1e-6:
        print(f"OK: {ad} = {yeni} (doğrulandı)")
        print("Not: kalıcı olması için araç bu değeri kendi EEPROM'una yazar; "
              "yeniden başlatıp bir daha okumak iyi bir alışkanlıktır.")
        return 0
    print(f"HATA: {ad} = {yeni}, beklenen {hedef} — YAZILMADI")
    return 1


KOMUTLAR = {
    "durum": cmd_durum,
    "izle": cmd_izle,
    "arm": cmd_arm,
    "disarm": cmd_disarm,
    "modlar": cmd_modlar,
    "kalkis": cmd_kalkis,
    "eve": cmd_eve,
    "rtl": cmd_eve,
    "daire": cmd_daire,
    "loiter": cmd_daire,
    "in": cmd_in,
    "dur": cmd_dur,
}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0

    ad = sys.argv[1].lower()
    args = sys.argv[2:]

    if ad == "mod":
        conn = _baglan()
        cmd_mod(conn, args)
        return 0

    if ad in ("parametre", "param"):
        conn = _baglan()
        return cmd_parametre(conn, args)

    if ad not in KOMUTLAR:
        print(f"Bilinmeyen komut: {ad}")
        print(f"Seçenekler: {', '.join(KOMUTLAR)}, mod, parametre")
        return 2

    # modlar komutu bağlantı gerektirmez
    if ad == "modlar":
        cmd_modlar(None)
        return 0

    conn = _baglan()
    KOMUTLAR[ad](conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
