#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
KUMANDA KALİBRASYONU — hangi HID ekseni hangi çubuk, ÖLÇEREK bul
================================================================================
⛔ EKSEN SIRASI VARSAYILMAZ. Hangi HID ekseninin hangi kanala denk geldiği
   EdgeTX sürümüne, USB kipine ve modelin kanal sırasına göre DEĞİŞİR.
   Yanlış eşleme "throttle verdim, araç yattı" demektir — ve bu, yerde
   fark edilmezse havada fark edilir.

   Ölçülen kumanda 7 eksen bildiriyor (JUMPER-RC); varsayılan haritamız 8
   eksenli AETR düzenine göreydi. Bu araç gerçek eşlemeyi bulur.

İKİ KİP:
  (varsayılan)  REHBERLİ — sırayla "şu çubuğu oynat" der, hangi eksenin
                oynadığını ölçer ve sonunda yazılacak `export` satırlarını
                basar.
  --canli       HAM — bütün eksenleri canlı basar; kendi gözünle bakmak
                istersen.

⚠ ÇUBUK YÖNÜ DE ÖLÇÜLÜR: eksen ters bağlıysa (ör. gaz yukarı itince değer
  düşüyorsa) `TERS_*` bayrağı üretilir. Yön hatası, panelin çubuğu ters
  göstermesi ve güdümün ters komut vermesi demektir.

Kullanım:
    python3 reel/araclar/kumanda_kalib.py
    python3 reel/araclar/kumanda_kalib.py --canli
================================================================================
"""
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


def _ac():
    import pygame
    pygame.init()
    try:
        pygame.joystick.quit()
    except Exception:
        pass
    pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("⛔ oyun kolu yok. Önce:  python3 reel/araclar/kumanda_bul.py")
        raise SystemExit(1)
    j = pygame.joystick.Joystick(0)
    j.init()
    return pygame, j


def _oku(pygame, j):
    pygame.event.pump()
    return [j.get_axis(i) for i in range(j.get_numaxes())]


def canli():
    pygame, j = _ac()
    n = j.get_numaxes()
    print("  %s — %d eksen. Ctrl+C ile çık.\n" % (j.get_name(), n))
    print("  " + "".join("eks%-6d" % i for i in range(n)))
    try:
        while True:
            v = _oku(pygame, j)
            print("\r  " + "".join("%+6.2f  " % x for x in v), end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n")


def rehberli():
    pygame, j = _ac()
    n = j.get_numaxes()
    print("=" * 70)
    print("  KUMANDA KALİBRASYONU — %s (%d eksen)" % (j.get_name(), n))
    print("=" * 70)
    print("\n  ⛔ PERVANELER SÖKÜLÜ olsun. Drone kapalı olabilir; bu test")
    print("     yalnız kumandanın USB çıktısını okur, RF'e hiçbir şey gitmez.\n")

    def olc(n_ornek=15):
        ort = [0.0] * n
        for _ in range(n_ornek):
            v = _oku(pygame, j)
            for i in range(n):
                ort[i] += v[i] / n_ornek
            time.sleep(0.02)
        return ort

    print("  ⛔ TABAN HER ADIMDA YENİDEN ALINIR — ve bu bir tasarım kararıdır:")
    print("     GAZ çubuğu kendiliğinden ORTALANMAZ. Yukarı ittikten sonra")
    print("     orada kalır; tek bir başlangıç tabanıyla kıyaslarsak o kalıcı")
    print("     fark SONRAKİ BÜTÜN ölçümleri bastırır ve her eksen 'gaz'")
    print("     gibi görünür. (İlk sürümde tam bu oldu: pitch ve roll da")
    print("     eksen 2 çıktı.) Bu yüzden her adım İKİ AŞAMALIDIR:")
    print("       (a) çubuklar duruyor  -> taban ölç")
    print("       (b) SADECE isteneni oynat ve TUT -> tekrar ölç\n")

    sonuc = {}
    ADIMLAR = [
        ("THROTTLE", "GAZ çubuğunu (sol dikey) TAM YUKARI it"),
        ("PITCH", "SAĞ çubuğu TAM İLERİ (yukarı) it"),
        ("ROLL", "SAĞ çubuğu TAM SAĞA it"),
        ("YAW", "SOL çubuğu TAM SAĞA it"),
        ("ARM", "ARM anahtarını (AUX1) çevir"),
        ("KIP", "OTONOM İZİN anahtarını çevir  (yoksa boş Enter = ATLA)"),
    ]
    for ad, yonerge in ADIMLAR:
        c = input("  ▸ %-46s  [Enter=başla, a=atla] " % ad)
        if c.strip().lower() == "a":
            print("     atlandı")
            continue
        taban = olc()                      # (a) O ANKİ hâl
        input("     %-52s → Enter " % (yonerge + ", TUT"))
        hedef = olc()                      # (b) oynatılmış hâl
        fark = [hedef[i] - taban[i] for i in range(n)]
        eks = max(range(n), key=lambda i: abs(fark[i]))
        buyuk = abs(fark[eks])
        if buyuk < 0.15:
            print("     ⚠ hiçbir eksen anlamlı oynamadı (en çok %.2f) — atlandı"
                  % buyuk)
            continue
        ikinci = sorted((abs(f) for f in fark), reverse=True)[1] if n > 1 else 0.0
        net = "" if buyuk > 2.5 * max(ikinci, 1e-6) else "  ⚠ BELİRSİZ"
        ters = fark[eks] < 0
        sonuc[ad] = (eks, ters)
        print("     eksen %d  değişim %+.2f%s%s   (ikinci en büyük %.2f)"
              % (eks, fark[eks], "  (TERS)" if ters else "", net, ikinci))
        if net:
            print("        → iki eksen birden oynadı. Yalnız isteneni oynat.")
        input("     çubuğu BIRAK / anahtarı geri al, sonra Enter ")

    print("\n" + "=" * 70)
    print("  SONUÇ — bu satırları `reel/baslat_drone.sh` içine ekle")
    print("=" * 70)
    if not sonuc:
        print("  ⛔ hiçbir eksen ölçülemedi.")
        return
    ADI = {"THROTTLE": "THR", "PITCH": "PITCH", "ROLL": "ROLL",
           "YAW": "YAW", "ARM": "ARM", "KIP": "KIP"}
    kullanilan = {}
    print()
    for ad, (eks, ters) in sonuc.items():
        print("export DOW_KMD_EKS_%s=%d" % (ADI[ad], eks))
        kullanilan.setdefault(eks, []).append(ad)
    if "KIP" not in sonuc:
        print("export DOW_KMD_EKS_KIP=-1      # anahtar YOK -> izin PANELDEN")
    for ad, (eks, ters) in sonuc.items():
        if ters and ad in ("THROTTLE", "PITCH", "ROLL", "YAW"):
            print("export DOW_KMD_TERS_%-5s=1" % ADI[ad])
    # ⛔ ARM ÖLÇÜLMEDİYSE BU BİR HATADIR, uyarı değil.
    #   YAŞANDI (2026-08-29): ARM adımında anahtar çevrilmedi, sonraki
    #   adımda çevrildi ve ARM ekseni "otonom izni" diye raporlandı.
    #   Olduğu gibi alınsaydı arm ile otonom izni AYNI anahtara binerdi.
    if "ARM" not in sonuc:
        print("\n  ⛔⛔ ARM ÖLÇÜLEMEDİ — bu çıktı KULLANILAMAZ.")
        print("     ARM emniyet-kritiktir ve TAHMİN EDİLEMEZ. Ayrıca bir")
        print("     sonraki adımda anahtarı çevirdiysen o adım YANLIŞ")
        print("     eksene atanmıştır (bizde tam bu oldu).")
        print("     Tekrar çalıştır; ARM adımında anahtarı GERÇEKTEN çevir.")
    if "KIP" in sonuc and "ARM" in sonuc and sonuc["KIP"][0] == sonuc["ARM"][0]:
        print("\n  ⛔⛔ OTONOM İZNİ ile ARM AYNI EKSENDE (%d).\n"
              "     Bu kabul edilemez: arm ettiğin anda otonoma da izin\n"
              "     vermiş olursun. İzin için AYRI bir anahtar ata ya da\n"
              "     DOW_KMD_EKS_KIP=-1 bırak (izin panelden gelir)."
              % sonuc["ARM"][0])
        sonuc.pop("KIP")
    cak = {e: a for e, a in kullanilan.items() if len(a) > 1}
    if cak:
        print("\n  ⛔ ÇAKIŞMA — aynı eksene birden çok işlev düştü:")
        for e, a in cak.items():
            print("     eksen %d  ->  %s" % (e, ", ".join(a)))
        print("     Ölçüm sırasında birden fazla çubuk oynamış olabilir;")
        print("     tekrar çalıştır ve her adımda YALNIZ isteneni oynat.")
    else:
        print("\n  ✔ çakışma yok — eşleme tutarlı")
    print("\n  Sonra paneli yeniden başlat; kumanda çubukları doğru eksene oturur.")


if __name__ == "__main__":
    (canli if "--canli" in sys.argv else rehberli)()
