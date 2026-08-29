#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
KALKIŞ AYARI — elle atış (hand-launch) parametrelerini OKU, DEĞERLENDİR, YAZ
================================================================================
⛔⛔ NİYE VAR: bu uçak İKİ KEZ TAM ATIŞ ESNASINDA DÜŞÜRÜLDÜ.
   Atış anı, sabit kanatlı bir İHA'nın en kırılgan anıdır: hız yok, yükseklik
   yok, ve motor henüz devrede değil. Burada yanlış bir parametre, düzeltme
   şansı olmadan uçağı yere indirir.

⛔ TAHMİNLE AYAR YAPILMAZ. Bu araç önce ARACIN GERÇEK DEĞERLERİNİ okur,
   sonra elle atış için bilinen güvenli bantlarla karşılaştırır. Öneri,
   ölçülen değerin üstüne kurulur.

TERİMLER (CLAUDE.md §0.2):
  * ELLE ATIŞ (hand-launch): uçağı elle fırlatarak kalkış. Tekerlek yok,
    pist yok; uçak fırlatıldığı hızla (~7-9 m/s) ve o irtifada (~1.7 m)
    uçmaya başlamak zorundadır.
  * STALL (perdövites): kanadın hücum açısı fazla artınca taşımanın
    ANİDEN kaybolması. Atıştan sonra burun fazla yukarı kalkarsa olur ve
    o irtifada toparlanma şansı YOKTUR.
  * SPOOL-UP: motorun sıfırdan tam devre çıkma süresi. ESC rampası ve
    pervane ataleti yüzünden 0.3-0.8 s sürer. O süre boyunca uçak
    İTKİSİZDİR ve yavaşlayıp alçalır — atış kazalarının klasik sebebi.
  * SLEW (eğim sınırı): gazın saniyede en fazla ne kadar değişebileceği.
    Düşükse motor "geç" gelir; atışta bu ölümcül olabilir.

Kullanım:
    python3 reel/talon/kalkis_ayari.py            # OKU ve DEĞERLENDİR
    python3 reel/talon/kalkis_ayari.py --yaz AD=DEGER [AD=DEGER ...]
================================================================================
"""
import argparse
import os
import sys
import time

#: (parametre, birim, açıklama, güvenli_alt, güvenli_üst, elle-atış notu)
#: ⚠ Bantlar ArduPlane belgeleri ve elle atış pratiğinden; ARACA ÖZEL
#:   ayar uçuş loguyla doğrulanır. Bant DIŞI = "bak", "kesin yanlış" değil.
PARAMETRELER = [
    ("TKOFF_THR_MINACC", "m/s²",
     "Elle atış ALGILAMA eşiği. Uçağı fırlattığında bu ivmeyi görünce "
     "otopilot 'atıldım' der.",
     10.0, 15.0,
     "⛔ ÇOK YÜKSEK: atış algılanmaz, motor HİÇ çalışmaz → uçak düşer.\n"
     "     ÇOK DÜŞÜK: elde taşırken tetiklenir → pervane elinde döner."),
    ("TKOFF_THR_DELAY", "0.1 s",
     "Atış algılandıktan SONRA motorun başlamasına kadar gecikme.",
     0.0, 4.0,
     "Elin pervaneden uzaklaşsın diye. 2 = 0.2 s tipiktir.\n"
     "     ⛔ ÇOK YÜKSEK: uçak itkisiz kalır, alçalır."),
    ("TKOFF_THR_MAX", "%",
     "Kalkışta çıkılacak EN YÜKSEK gaz.",
     75.0, 100.0,
     "Elle atışta 100 önerilir: hız kazanmak için en kısa süre gerekir."),
    ("TKOFF_THR_MINSPD", "m/s",
     "Motorun başlaması için gereken EN AZ yer hızı.",
     0.0, 4.0,
     "⚠ Elle atışta genelde 0 olmalı; GPS hızı atış anında güvenilmez."),
    ("TKOFF_LVL_ALT", "m",
     "Bu irtifaya kadar kanatlar DÜZ tutulur (dönüş yok).",
     5.0, 25.0,
     "Atıştan hemen sonra dönmeye kalkmak kanat ucunu düşürür."),
    ("TKOFF_LVL_PITCH", "°",
     "İlk tırmanışta hedef DİKİLME açısı.",
     8.0, 15.0,
     "⛔⛔ ATIŞ KAZALARININ EN SIK SEBEBİ. Yüksekse uçak hız kazanmadan\n"
     "     burnunu kaldırır ve STALL eder. Talon için 10-12° güvenli."),
    ("TKOFF_ALT", "m",
     "Görev TAKEOFF öğesinin hedef irtifası.",
     30.0, 120.0, ""),
    # ⛔ ÖZEL DEĞERLENDİRME: 0 = SINIRSIZ ve elle atış için EN İYİSİDİR.
    #   Sayısal bant burada yanıltıcı olurdu (0, "50'den küçük" diye
    #   kötü görünürdü). Aşağıdaki döngüde özel olarak ele alınır.
    ("THR_SLEWRATE", "%/s",
     "Gazın saniyede en fazla ne kadar değişebileceği. 0 = SINIRSIZ.",
     0.0, 0.0,
     "⛔⛔ ATIŞTA KRİTİK. Düşükse motor tam devre GEÇ çıkar ve uçak o\n"
     "     sürede alçalır. 0 = sınırsız (en hızlı). 100 = 1 saniyede tam."),
    # ⚠ ArduPlane 4.7 BAZI PARAMETRELERİ YENİDEN ADLANDIRDI. Eski adlar
    #   okunmuyor ("6 YOK" diye çıktı). İkisi de denenir; hangisi varsa o
    #   raporlanır. (Bu deponun hafızasında yazılı bir tuzak: "param adını
    #   DOĞRULA, varsayma".)
    ("AIRSPEED_MIN", "m/s",
     "En düşük uçuş hızı — stall koruması. (eski ad: ARSPD_FBW_MIN)",
     9.0, 14.0,
     "Atış hızından (~8 m/s) çok yüksekse otopilot hemen burnu indirir."),
    ("ARSPD_FBW_MIN", "m/s", "(eski ad) en düşük uçuş hızı", 9.0, 14.0, ""),
    ("TRIM_THROTTLE", "%",
     "Seyir gazı.", 30.0, 75.0, ""),
    ("AIRSPEED_CRUISE", "m/s",
     "Hedef seyir hızı. (eski ad: TRIM_ARSPD_CM, cm/s idi)",
     12.0, 25.0, ""),
    ("PTCH_LIM_MAX_DEG", "°",
     "En büyük burun YUKARI açısı. (eski ad: LIM_PITCH_MAX, santi-derece)",
     10.0, 25.0,
     "Atış sonrası tırmanışı bu sınırlar."),
    ("PTCH_LIM_MIN_DEG", "°",
     "En büyük burun AŞAĞI açısı. (eski ad: LIM_PITCH_MIN)",
     -35.0, -10.0, ""),
    ("ROLL_LIMIT_DEG", "°",
     "En büyük yatış. (eski ad: LIM_ROLL_CD, santi-derece)",
     30.0, 65.0, ""),
    ("TKOFF_TIMEOUT", "s",
     "Atış algılanmazsa kalkış bu sürede iptal edilir.", 0.0, 60.0, ""),
    ("TKOFF_MODE", "-",
     "Kalkış kipi (0 = klasik).", 0.0, 3.0, ""),
    ("TECS_PITCH_MAX", "°",
     "TECS'in izin verdiği en büyük tırmanma açısı.", 10.0, 25.0,
     "⛔ Atıştan hemen sonraki tırmanışı BU da sınırlar."),
    ("PTCH_TRIM_DEG", "°",
     "Seyirde gövde dikilme ayarı.", -5.0, 5.0, ""),
    ("KFF_RDDRMIX", "-", "Dümen karışımı.", 0.0, 1.0, ""),
    # ⛔ HIZ SENSÖRÜ VAR MI — bu, yukarıdaki hız parametrelerinin ANLAMINI
    #   değiştirir. Pitot yoksa ArduPlane hızı GPS+ivmeden TAHMİN eder
    #   (sentetik hız) ve atış anında o tahmin GÜVENİLMEZDİR.
    ("ARSPD_TYPE", "-", "Hız sensörü tipi (0 = YOK).", 0.0, 20.0,
     "0 ise pitot yoktur; hız TAHMİN edilir."),
    ("ARSPD_USE", "-", "Hız sensörü güdümde KULLANILIYOR mu (1 = evet).",
     0.0, 1.0, ""),
    ("TKOFF_THR_MAX_T", "s", "Kalkışta tam gazın sürdürüleceği en uzun süre.",
     0.0, 30.0, ""),
    ("TECS_CLMB_MAX", "m/s", "TECS'in hedeflediği en yüksek tırmanma hızı.",
     1.0, 8.0, ""),
    ("ARMING_CHECK", "-",
     "Arm öncesi denetimler (bit maskesi).", 0.0, 1e9,
     "⛔ 0 = HİÇBİR DENETİM YOK. Sahada 'arm olmuyor' diye kapatılırsa\n"
     "     bozuk pusula/EKF ile uçulur. 1 = hepsi açık."),
]


def _mav(adres):
    from pymavlink import mavutil
    m = mavutil.mavlink_connection(adres)
    print("  kalp atışı bekleniyor…", end="", flush=True)
    hb = m.wait_heartbeat(timeout=15)
    if hb is None:
        print(" ⛔ YOK")
        return None
    print(" ✔ (sistem %d)" % m.target_system)
    return m


def param_oku(m, adlar, zaman_asimi=12.0):
    """İstenen parametreleri TEK TEK ister. Döner: {ad: değer}

    ⛔ PARAM_REQUEST_LIST KULLANILMAZ: ArduPlane'de ~1300 parametre var ve
       57600 baud'luk telsizde hepsini çekmek DAKİKALAR sürer, üstelik
       telemetri linkini o süre boyunca doldurur.
    """
    sonuc = {}
    kalan = list(adlar)
    for tur in range(3):
        if not kalan:
            break
        for ad in kalan:
            m.mav.param_request_read_send(
                m.target_system, m.target_component, ad.encode(), -1)
            time.sleep(0.02)
        t0 = time.time()
        while time.time() - t0 < zaman_asimi and kalan:
            msg = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=1.0)
            if msg is None:
                continue
            ad = msg.param_id.strip("\x00")
            if ad in kalan:
                sonuc[ad] = float(msg.param_value)
                kalan.remove(ad)
    return sonuc, kalan


def param_yaz(m, ad, deger):
    from pymavlink import mavutil
    m.mav.param_set_send(m.target_system, m.target_component, ad.encode(),
                         float(deger), mavutil.mavlink.MAV_PARAM_TYPE_REAL32)
    t0 = time.time()
    while time.time() - t0 < 6.0:
        msg = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=1.0)
        if msg is not None and msg.param_id.strip("\x00") == ad:
            return True, float(msg.param_value)
    return False, None


def main():
    ap = argparse.ArgumentParser(description="Talon kalkış parametreleri")
    ap.add_argument("--mav", default="udp:127.0.0.1:14550")
    ap.add_argument("--yaz", nargs="*", default=None,
                    help="AD=DEGER ... (yazmadan önce ONAY sorar)")
    a = ap.parse_args()

    print("=" * 74)
    print("  TALON KALKIŞ AYARI — elle atış")
    print("=" * 74)
    print("  MAVLink: %s" % a.mav)
    m = _mav(a.mav)
    if m is None:
        print("\n⛔ araç yok. Önce ./baslat_talon.sh çalışıyor olmalı.")
        return 2

    adlar = [p[0] for p in PARAMETRELER]
    print("  %d parametre okunuyor…" % len(adlar))
    deger, eksik = param_oku(m, adlar)
    print("  ✔ %d okundu%s\n" % (len(deger),
                                 (", %d YOK: %s" % (len(eksik), ", ".join(eksik)))
                                 if eksik else ""))

    print("  %-18s %10s %-8s %s" % ("PARAMETRE", "DEĞER", "BİRİM", "DURUM"))
    print("  " + "-" * 70)
    uyari = []
    for ad, birim, acik, alt, ust, not_ in PARAMETRELER:
        if ad not in deger:
            continue
        v = deger[ad]
        if ad == "THR_SLEWRATE":
            # 0 = sınırsız (elle atış için EN İYİ). 1-149 = yavaş rampa.
            if v == 0:
                durum = "✔ SINIRSIZ (elle atış için en iyi)"
            elif v >= 150:
                durum = "✔"
            else:
                durum = "⚠ rampa %.2f s — atışta ölü zaman" % (100.0 / v)
                uyari.append((ad, v, 0, 0, acik, not_))
            print("  %-18s %10.4g %-8s %s" % (ad, v, birim, durum))
            continue
        if alt <= v <= ust:
            durum = "✔"
        else:
            durum = "⚠ BANT DIŞI (%.4g..%.4g)" % (alt, ust)
            uyari.append((ad, v, alt, ust, acik, not_))
        print("  %-18s %10.4g %-8s %s" % (ad, v, birim, durum))

    if uyari:
        print("\n" + "=" * 74)
        print("  ⚠ BAKILACAKLAR")
        print("=" * 74)
        for ad, v, alt, ust, acik, not_ in uyari:
            print("\n  %s = %.4g   (beklenen %.4g … %.4g)" % (ad, v, alt, ust))
            print("     %s" % acik)
            if not_:
                for satir in not_.split("\n"):
                    print("     %s" % satir)
    else:
        print("\n  ✔ hepsi beklenen bantta")

    # ==================================================================
    #  ⛔⛔ ATIŞ TEŞHİSİ — iki sayı hesaplanır, ikisi de düşüşü açıklar
    # ==================================================================
    print("\n" + "=" * 74)
    print("  ⛔ ATIŞ TEŞHİSİ  (bu uçak İKİ KEZ atışta düşürüldü)")
    print("=" * 74)
    ATIS_HIZI = 8.0      # m/s — iyi bir elle atış
    ATIS_IRTIFA = 1.7    # m   — omuz hizası

    # --- 1) ÖLÜ ZAMAN: atıştan tam itkiye kadar geçen süre ---
    gecikme = deger.get("TKOFF_THR_DELAY", 0) * 0.1
    slew = deger.get("THR_SLEWRATE", 0)
    thr_max = deger.get("TKOFF_THR_MAX", 100)
    rampa = (thr_max / slew) if slew > 0 else 0.0
    olu = gecikme + rampa
    dusus = 0.5 * 9.81 * olu * olu          # itkisiz serbest düşüş üst sınırı
    print("\n  [1] ÖLÜ ZAMAN — atıştan TAM İTKİYE kadar")
    print("      TKOFF_THR_DELAY %.1f s  +  gaz rampası %.2f s  =  %.2f s"
          % (gecikme, rampa, olu))
    if slew > 0:
        print("      (rampa = TKOFF_THR_MAX %.0f%% ÷ THR_SLEWRATE %.0f%%/s)"
              % (thr_max, slew))
    else:
        print("      (THR_SLEWRATE 0 = SINIRSIZ, yazılım rampası yok)")
        print("      ⚠ AMA ESC ve PERVANE ATALETI KALIR: sıfırdan tam devre")
        print("        ~0.3 s. Gerçek ölü zaman ≈ %.2f s. Yazılımla daha"
              % (gecikme + 0.3))
        print("        fazla kısaltılamaz — kalanı ATIŞ HIZINDAN kazanılır.")
    print("      Bu sürede itkisiz düşüş ÜST SINIRI: %.1f m" % dusus)
    print("      Atış irtifası: %.1f m" % ATIS_IRTIFA)
    if olu > 0.4:
        print("      ⛔⛔ %.2f s ÇOK UZUN. Uçak, motor tam devre çıkmadan"
              % olu)
        print("          yere iner. Bu, düşüşlerin BİRİNCİ sebebidir.")
        print("          ÇARE: THR_SLEWRATE = 0  (sınırsız) -> ölü zaman %.2f s"
              % gecikme)
    else:
        print("      ✔ ölü zaman kabul edilebilir")

    # --- 2) ENERJİ AÇIĞI: atış hızı ile gereken hız arasındaki fark ---
    v_min = deger.get("AIRSPEED_MIN", deger.get("ARSPD_FBW_MIN", 0))
    if v_min:
        gerek_h = (v_min ** 2 - ATIS_HIZI ** 2) / (2 * 9.81)
        print("\n  [2] ENERJİ AÇIĞI — atış hızından uçuş hızına")
        print("      Atış  %.0f m/s   ->   AIRSPEED_MIN %.0f m/s" % (ATIS_HIZI, v_min))
        print("      Bu farkı YALNIZ dalarak kapatmak için gereken irtifa:")
        print("        h = (%.0f² − %.0f²) / (2·9.81) = %.1f m" % (v_min, ATIS_HIZI, gerek_h))
        print("      Elde olan irtifa: %.1f m" % ATIS_IRTIFA)
        if gerek_h > ATIS_IRTIFA:
            print("      ⛔⛔ %.1f m EKSİK. Uçak, atıldığı anda uçabilecek"
                  % (gerek_h - ATIS_IRTIFA))
            print("          enerjiye SAHİP DEĞİL. O enerjiyi YALNIZ MOTOR")
            print("          verebilir — ve HEMEN vermek zorundadır.")

    # --- 2b) GEREKEN ATIŞ HIZI ---
    if v_min:
        # Motor hemen gelse bile uçak, itkisiz geçen sürede hız kaybeder.
        # Kabaca: atış hızı, elde olan irtifayı hıza çevirerek AIRSPEED_MIN'e
        # ulaşabilmeli.  v_atis² + 2·g·h  >=  v_min²
        v_gerek = (max(0.0, v_min ** 2 - 2 * 9.81 * ATIS_IRTIFA)) ** 0.5
        print("\n  [2b] GEREKEN ATIŞ HIZI")
        print("      Elde olan %.1f m irtifayı da hıza çevirirsek:" % ATIS_IRTIFA)
        print("        v_atış ≥ √(%.0f² − 2·9.81·%.1f) = %.1f m/s"
              % (v_min, ATIS_IRTIFA, v_gerek))
        print("      ⭐ YANİ EN AZ %.0f m/s ATMALISIN (%.0f km/h)."
              % (v_gerek, v_gerek * 3.6))
        print("        Sakin bir atış ~8 m/s'dir — YETMEZ.")
        print("        SERT at, KOŞARAK at, RÜZGÂRA KARŞI at.")
        print("        ⚠ 4 m/s karşı rüzgâr, 8 m/s'lik atışı 12 m/s yapar —")
        print("          rüzgâra karşı atmak tek başına farkı kapatabilir.")

    # --- 3) İLK TIRMANIŞ AÇISI ---
    lvl = deger.get("TKOFF_LVL_PITCH")
    if lvl is not None:
        print("\n  [3] İLK TIRMANIŞ AÇISI")
        print("      TKOFF_LVL_PITCH = %.0f°  (TKOFF_LVL_ALT %.0f m'ye kadar)"
              % (lvl, deger.get("TKOFF_LVL_ALT", 0)))
        if lvl > 12:
            print("      ⚠ %.0f° YÜKSEK. Uçak %.0f m/s ile atılıyor ama uçuş"
                  % (lvl, ATIS_HIZI))
            print("        hızı %.0f m/s. Hız kazanmadan burun kaldırmak"
                  % (v_min or 15))
            print("        hücum açısını artırır -> STALL. 10-12° güvenli.")

    # --- 4) HIZ SENSÖRÜ ---
    tip, kul = deger.get("ARSPD_TYPE"), deger.get("ARSPD_USE")
    if tip is not None and kul is not None:
        print("\n  [4] HIZ SENSÖRÜ")
        if tip > 0 and kul == 0:
            print("      ⚠ PİTOT VAR (ARSPD_TYPE=%.0f) ama KULLANILMIYOR "
                  "(ARSPD_USE=0)." % tip)
            print("        Otopilot hızı GPS+ivmeden TAHMİN ediyor. Atış")
            print("        anında o tahmin en güvenilmez olduğu andır.")
            print("        ⛔ Körü körüne AÇMA: bozuk bir pitotla ARSPD_USE=1,")
            print("        hiç kullanmamaktan DAHA TEHLİKELİDİR. Önce yerde")
            print("        üfleyerek sensörün makul okuduğunu doğrula.")
        elif tip == 0:
            print("      ⚠ Pitot YOK — hız tamamen tahmin.")
        else:
            print("      ✔ pitot var ve kullanılıyor")

    if a.yaz:
        print("\n" + "=" * 74)
        print("  YAZMA")
        print("=" * 74)
        istekler = []
        for x in a.yaz:
            if "=" not in x:
                print("  ⛔ biçim AD=DEGER olmalı: %r" % x)
                return 2
            ad, d = x.split("=", 1)
            istekler.append((ad.strip().upper(), float(d)))
        for ad, d in istekler:
            eski = deger.get(ad)
            print("  %-18s %s -> %s" % (ad, "%.4g" % eski if eski is not None
                                        else "?", "%.4g" % d))
        c = input("\n  ⛔ ARAÇ PARAMETRESİ DEĞİŞTİRİLECEK. Onaylıyor musun? "
                  "(evet/hayır) ")
        if c.strip().lower() not in ("evet", "e", "yes", "y"):
            print("  vazgeçildi.")
            return 0
        for ad, d in istekler:
            ok, v = param_yaz(m, ad, d)
            print("  %-18s %s" % (ad, ("✔ %.4g" % v) if ok else "⛔ yazılamadı"))
        print("\n  ⚠ Değişiklikler UÇUCU OLABİLİR: kalıcı olması için aracı")
        print("     yeniden başlat ve bu aracı tekrar çalıştırıp DOĞRULA.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
