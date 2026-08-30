#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YÖN İŞARETİ TESTİ — güdüm hatayı KAPATIYOR mu, BÜYÜTÜYOR mu (YERDE, pervanesiz)

⛔ NİYE VAR
   Çevirici, dünya çerçevesindeki hız isteğini aracın GÖVDE çerçevesine
   çevirir:
       ileri = vx·cos(yaw) + vy·sin(yaw)
       sag   = Y_ISARET · (−vx·sin(yaw) + vy·cos(yaw))
   `Y_ISARET` yanlışsa yanal kanal AYNALANIR: araç hedefin soluna gitmesi
   gerekirken sağına gider, hata KAPANMAZ BÜYÜR. Bu, ancak kapalı çevrimde
   görülür — ve şimdiye kadar "kesin kanıtı ilk otonom uçuştur" diye
   yazılıydı. Bu araç onu YERDE kapatır.

⛔ NASIL ÇALIŞIR — modelden bağımsız
   Aracı elinle çevirirsin. Güdümün ürettiği çubuklar GÖVDE çerçevesindedir;
   biz onları yaw ile DÜNYA çerçevesine geri döndürürüz. Hedef sabit
   durduğuna göre dünya çerçevesindeki komut yönü, aracı nasıl çevirirsen
   çevir AYNI KALMALIDIR.

   İki hipotez birlikte sınanır:
       H0  işaret DOĞRU   -> (pitch, roll) olduğu gibi döndürülür
       H1  işaret TERS    -> roll'ün işareti çevrilerek döndürülür
   Hangi hipotez dünya yönünü daha TUTARLI veriyorsa doğru olan odur.
   Yanlış hipotezde, aracı Δ kadar çevirdiğinde görünen yön 2Δ kadar
   kayar — dört yönde bakınca ayrım çok belirgin olur.

⛔ KOŞULLARI
   · PERVANELER ÇIKARILI · araç DISARM · panelde OTONOM
   · hedef akışı taze (Talon açık)
   · en az ÜÇ farklı burun yönü (dördü daha iyi)

Kullanım:
    python3 gercek/yon_testi.py              # 90 s toplar
    python3 gercek/yon_testi.py --sure 120
"""
import argparse
import json
import math
import sys
import time
import urllib.request

PANEL = "http://127.0.0.1:8810/api/durum"
KOVA = 45.0          # derece — burun yönü kovalarının genişliği
EN_AZ_KOVA = 3       # bu kadar farklı yön görmeden hüküm kurulmaz
EN_AZ_BUYUKLUK = 0.08   # bundan küçük çubuk yön taşımaz, atılır


def _al(url, zaman=3.0):
    with urllib.request.urlopen(url, timeout=zaman) as r:
        return json.load(r)


def _yon_farki(a, b):
    """İki açı arasındaki en kısa fark, derece, [-180, 180]."""
    return (a - b + 180.0) % 360.0 - 180.0


def _dairesel(acilar):
    """Açı kümesinin ortalama yönü ve TOPLANMA gücü R (0..1).

    R = 1  -> hepsi tıpatıp aynı yönde
    R = 0  -> tamamen dağınık
    """
    if not acilar:
        return None, 0.0
    sx = sum(math.cos(math.radians(a)) for a in acilar)
    sy = sum(math.sin(math.radians(a)) for a in acilar)
    n = float(len(acilar))
    R = math.hypot(sx, sy) / n
    return math.degrees(math.atan2(sy, sx)) % 360.0, R


def _dunya_yonu(pitch, roll, yaw_deg):
    """Gövde çubuklarını dünya çerçevesine döndür; kerteriz döndür (0=kuzey)."""
    y = math.radians(yaw_deg)
    kuzey = pitch * math.cos(y) - roll * math.sin(y)
    dogu = pitch * math.sin(y) + roll * math.cos(y)
    return math.degrees(math.atan2(dogu, kuzey)) % 360.0


def main():
    a = argparse.ArgumentParser(description="Yön işareti testi (yerde)")
    a.add_argument("--sure", type=float, default=90.0, help="toplama süresi (s)")
    a.add_argument("--panel", default=PANEL)
    a = a.parse_args()

    print("=" * 70)
    print("  YÖN İŞARETİ TESTİ — pervanesiz, DISARM, panelde OTONOM")
    print("=" * 70)
    print("  ⛔ PERVANELER ÇIKARILI olduğunu doğrula.")
    print("  Aracı elinde tut ve YAVAŞÇA çevir: her yönde ~10 s bekle,")
    print("  en az DÖRT yön göster (kuzey, doğu, güney, batı gibi).")
    print()

    # ---- OTONOM'a geçilmesini bekle ----
    t0 = time.time()
    while True:
        try:
            d = _al(a.panel)
        except Exception as e:
            print("  ⛔ panele ulaşılamıyor (%s) — drone_yki çalışıyor mu?" % e)
            return 2
        k = d.get("komut") or {}
        if k.get("kaynak") == "OTONOM":
            break
        if time.time() - t0 > 180:
            print("  ⛔ 3 dakikadır OTONOM'a geçilmedi. Panelde OTONOM'a bas.")
            return 2
        print("\r  OTONOM bekleniyor…  kaynak=%-8s sebep=%-14s" %
              (k.get("kaynak"), k.get("sebep")), end="")
        sys.stdout.flush()
        time.sleep(0.5)
    print("\r  ✔ OTONOM etkin — toplama başlıyor (%g s)\n" % a.sure)

    ornek = []          # (yaw, pitch, roll, hedef_kerterizi)
    doyum = 0
    kucuk = 0
    t0 = time.time()
    son_yaz = 0.0
    while time.time() - t0 < a.sure:
        try:
            d = _al(a.panel)
        except Exception:
            time.sleep(0.3)
            continue
        k = d.get("komut") or {}
        if k.get("kaynak") != "OTONOM":
            print("  ⚠ OTONOM düştü (sebep: %s) — panelde tekrar OTONOM'a bas"
                  % k.get("sebep"))
            time.sleep(1.0)
            continue
        cub = k.get("komut") or []
        du = d.get("durus") or {}
        if len(cub) < 4 or du.get("yaw") is None:
            time.sleep(0.3)
            continue
        _, pitch, roll, _ = cub[0], cub[1], cub[2], cub[3]
        yaw = float(du["yaw"])
        buyukluk = math.hypot(pitch, roll)
        if abs(pitch) >= 0.999 or abs(roll) >= 0.999:
            doyum += 1
        if buyukluk < EN_AZ_BUYUKLUK:
            kucuk += 1
            time.sleep(0.3)
            continue

        # hedefin kerterizi (aracın kendi konumundan) — yalnız bilgi için
        hk = d.get("hedef_ham_konum")
        ko = d.get("konum") or {}
        hedef_kert = None
        if hk:
            dn = hk["kuzey"] - (ko.get("kuzey") or 0.0)
            de = hk["dogu"] - (ko.get("dogu") or 0.0)
            if math.hypot(dn, de) > 0.5:
                hedef_kert = math.degrees(math.atan2(de, dn)) % 360.0
        ornek.append((yaw, pitch, roll, hedef_kert))

        if time.time() - son_yaz > 2.0:
            son_yaz = time.time()
            print("  %4.0f s  burun %6.1f°   çubuk P%+.2f R%+.2f   "
                  "dünya yönü H0 %5.1f°%s"
                  % (time.time() - t0, yaw, pitch, roll,
                     _dunya_yonu(pitch, roll, yaw),
                     ("   hedef %5.1f°" % hedef_kert) if hedef_kert else ""))
        time.sleep(0.3)

    # ---- değerlendirme ----
    print()
    print("=" * 70)
    if len(ornek) < 10:
        print("  ⛔ YETERLİ ÖRNEK YOK (%d). Güdüm çubuk üretmiyor olabilir:" % len(ornek))
        print("     · hedef akışı taze mi (panelde 'GPS akışı VAR')")
        print("     · köken kuruldu mu")
        print("     · araç hedefe çok yakınsa komut sıfıra yakın kalır")
        return 1

    # burun yönüne göre kovala
    kovalar = {}
    for yaw, p, r, hk in ornek:
        kovalar.setdefault(int((yaw % 360.0) // KOVA), []).append((yaw, p, r, hk))

    print("  BURUN YÖNÜ KOVALARI  (%d örnek, %d farklı yön)"
          % (len(ornek), len(kovalar)))
    print()
    print("   burun aralığı    n    H0 dünya yönü    H1 dünya yönü   hedef")
    print("  " + "-" * 66)
    h0_ort, h1_ort = [], []
    for kv in sorted(kovalar):
        grup = kovalar[kv]
        b0 = [_dunya_yonu(p, r, y) for y, p, r, _ in grup]
        b1 = [_dunya_yonu(p, -r, y) for y, p, r, _ in grup]
        m0, _ = _dairesel(b0)
        m1, _ = _dairesel(b1)
        hks = [h for _, _, _, h in grup if h is not None]
        mh, _ = _dairesel(hks) if hks else (None, 0)
        h0_ort.append(m0)
        h1_ort.append(m1)
        print("   %3d-%3d°       %4d      %6.1f°         %6.1f°       %s"
              % (kv * KOVA, (kv + 1) * KOVA, len(grup), m0, m1,
                 ("%6.1f°" % mh) if mh is not None else "   —"))

    _, R0 = _dairesel(h0_ort)
    _, R1 = _dairesel(h1_ort)
    print()
    print("  TOPLANMA GÜCÜ (1.00 = kusursuz tutarlı, 0 = dağınık)")
    print("     H0  işaret DOĞRU  : R = %.3f" % R0)
    print("     H1  işaret TERS   : R = %.3f" % R1)
    print()
    if doyum:
        print("  ⚠ %d örnekte çubuk DOYUMDA (±1.00) — açı bilgisi kırpılmış" % doyum)
    if kucuk:
        print("  ℹ %d örnek çok küçük çubuk olduğu için atlandı" % kucuk)

    print()
    if len(kovalar) < EN_AZ_KOVA:
        print("  ⛔ HÜKÜM KURULMADI — yalnız %d farklı burun yönü var, en az %d"
              " gerekir.\n     Aracı daha geniş çevirip tekrarla." % (len(kovalar), EN_AZ_KOVA))
        return 1
    fark = R0 - R1
    if fark > 0.15:
        print("  ✔✔ SONUÇ: YÖN İŞARETİ DOĞRU  (DOW_CEV_Y_ISARET=+1.0)")
        print("     Dünya çerçevesindeki komut yönü, aracı çevirmene rağmen")
        print("     sabit kaldı. Güdüm hatayı KAPATIYOR.")
    elif fark < -0.15:
        print("  ⛔⛔ SONUÇ: YÖN İŞARETİ TERS — UÇURMA.")
        print("     Yanal kanal aynalanmış; araç hedeften KAÇAR.")
        print("     Çare:  DOW_CEV_Y_ISARET=-1.0 ./baslat_drone.sh --gorsel")
        print("     Sonra bu testi TEKRARLA; R değerleri yer değiştirmeli.")
    else:
        print("  ⚠ AYIRT EDİLEMEDİ (R farkı %.3f, eşik 0.15)." % fark)
        print("     Sebebi genelde: çubuklar doyumda, ya da burun yönleri")
        print("     birbirine çok yakın. Aracı DÖRT belirgin yöne çevirip")
        print("     her yönde 10 s bekleyerek tekrarla.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
