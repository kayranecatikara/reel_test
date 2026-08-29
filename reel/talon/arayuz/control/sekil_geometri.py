#!/usr/bin/env python3
"""
sekil_geometri.py — Kare / daire / elips şekillerinin GPS waypoint'lerini üretir.

Bu modülde MAVLink YOKTUR ve olmamalıdır. Sebep: aynı hesabı iki yer kullanıyor —
arayüz sunucusu (3B panelde planlanan şekli çizmek için, araca hiç dokunmadan) ve
görev yükleyici (aynı noktaları araca göndermek için). Matematik tek yerde
durursa paneldeki önizleme ile uçağın gerçekte uçtuğu şekil ayrışamaz.

MAVLink'siz olduğu için masada, araç olmadan test edilebilir:

    python -m control.sekil_geometri --test
    python -m control.sekil_geometri --sekil elips --olcu 170 --olcu2 110


ŞEKİL BOYUTUNU NEDEN SERBESTÇE SEÇEMİYORSUNUZ
---------------------------------------------
1. Dönüş yarıçapı fizikseldir: R = v² / (g·tanθ). Bu uçak 20 m/s'te 40° yatışla
   en dar 49 m yarıçapla döner. Daha dar bir şekil çizilemez — uçak dönüşü
   tamamlayamadan bir sonraki kenara geçer ve şekil daireye çöker.
2. ArduPilot bir waypoint'e "kabul yarıçapı" kadar yaklaşınca vardım sayar.
   Noktalar bundan sık dizilirse birkaçı aynı anda geçilmiş sayılır.
3. FENCE_RADIUS / FENCE_ALT_MAX aşılırsa uçak kendiliğinden RTL'e geçer.

dogrula() bu üç sınırı da araçtan okunan gerçek parametrelerle uygular.


KABUL YARIÇAPI HAKKINDA (ArduPlane'e özgü, kaynaktan doğrulandı)
----------------------------------------------------------------
ArduPlane derlemesinde NAV_WAYPOINT'in param2 alanı O NOKTAYA ÖZEL kabul
yarıçapıdır (metre, 0-255):

    AP_Mission.cpp:1092   uint16_t acp = packet.param2;   // low p1'e saklanır
    commands_logic.cpp:674  if (cmd_acceptance_distance > 0) → WP_RADIUS ve
                            açı ölçeklemesi TAMAMEN devre dışı kalır

Bu yüzden her şekil noktasına kendi kabul yarıçapını yazıyoruz. Aracın
WP_RADIUS parametresini geçici olarak değiştirmek de bir çözüm olurdu ama
kalıcı yan etki riski taşır (süreç çökerse araçta bozuk değer kalır — servo
test panelindeki SERVOn_FUNCTION geri yükleme derdinin aynısı). param2 hiçbir
kalıcı iz bırakmıyor.
"""

import argparse
import json
import math
import sys

# 1 derece enlem kaç metre (WGS-84 ekvator yarıçapından). Elipsoit yerine küre
# kabulü: bu proje 300 m'lik bir güvenlik çemberi içinde çalışıyor, o ölçekte
# WGS-84'e göre sapma 2 metrenin altında — GPS hatası (~2 m) ve kabul yarıçapı
# (15-25 m) yanında ölçülemez. Haversine'e geçmeye gerek yok.
DERECE_METRE = math.pi * 6378137.0 / 180.0      # 111319.49

YERCEKIMI = 9.80665

# Dönüş yarıçapı hesabına bırakılan hız payı. Uçakta pitot yok (ARSPD_USE=0),
# hava hızı sentetik. Kuyruk rüzgârında YER hızı artar ve dönüş yarıçapı hızın
# KARESİYLE büyür: 20 m/s yerine 24 m/s → yarıçap 1.44 katına çıkar.
RUZGAR_PAYI = 1.20

# Şeklin tasarlandığı yatış açısı. Otopilot ROLL_LIMIT_DEG'e kadar yatabilir ama
# sürekli limitte uçmak ne konforlu ne de güvenli — 30° gerçekçi bir çalışma açısı.
TASARIM_YATIS = 30.0

# "Uçulamaz" kararında kullanılacak yatış TAVANI.
#
# Sınırı doğrudan ROLL_LIMIT_DEG'den almak yanlış sonuç veriyor: SITL'de bu
# parametre 65° ve o açıda formül 23 m'lik bir dönüş yarıçapı üretiyor, yani
# 25 m'lik bir daire "uçulabilir" görünüyor. Oysa 65° yatış 1/cos65 = 2.37 g
# demek; sabit kanat bir uçak bunu SÜREKLİ taşıyamaz, üstelik bu uçakta pitot
# yok (ARSPD_USE=0) ve stall payı ölçülemiyor. Kartın parametresi ne derse
# desin, şekil planlarken 45°'nin ötesini gerçekçi saymıyoruz.
YATIS_TAVAN = 45.0

# Poligon noktaları arası hedeflenen mesafe (metre). L1 kontrolcüsünün ileri
# bakış mesafesi bu uçakta ~86 m (NAVL1_PERIOD=18, v=20); ondan belirgin küçük
# seçmek yolu yumuşak tutar, çok küçük seçmek gereksiz öğe üretir.
ARALIK_HEDEF = 60.0

POLIGON_MIN_NOKTA = 8
POLIGON_MAX_NOKTA = 32

# Kabul yarıçapı aralığın kaçta kaçı olsun. Çift tetiklenme sınırı
# aralik > 2·kabul; 3'e bölmek %50 pay bırakır.
KABUL_BOLEN = 3.0
KABUL_MIN = 5
KABUL_MAX = 60

# Dairenin 3B panelde çizilirken kaç örnekle temsil edileceği (göreve gitmez).
DAIRE_CIZIM_ORNEK = 72

# Uçağın "havada" sayıldığı irtifa — run_plane_scenario ile aynı eşik.
HAVADA_IRTIFA = 15.0


# Araçtan okunamayan parametreler için düşülecek değerler. Bu uçağın gerçek
# mav.parm değerleri; sunucu araca bağlanamadığında bile panel çalışsın diye.
ARAC_VARSAYILAN = {
    "WP_RADIUS": 60.0,
    "WP_LOITER_RAD": 90.0,
    "AIRSPEED_CRUISE": 20.0,
    "ROLL_LIMIT_DEG": 40.0,
    "FENCE_RADIUS": 300.0,
    "FENCE_ALT_MAX": 100.0,
    "FENCE_MARGIN": 20.0,
    "TKOFF_ALT": 50.0,
    # İniş paterni bu ikisinden üretilir. Kasten AUTOLAND modunun kendi
    # parametreleri kullanılıyor: göreve gömülen iniş ile AUTOLAND butonunun
    # uçtuğu iniş AYNI patern olsun. İki ayrı sayı tutulsaydı pilot birini
    # düzeltip diğerini unutur ve iki buton farklı yerlere inerdi.
    "AUTOLAND_WP_ALT": 55.0,
    "AUTOLAND_WP_DIST": 400.0,
}

# Süzülme açısı sınırları (derece). Motorsuz alçalma açısı; foam bir uçak
# flapssız yaklaşık 6-8° iner. Dik yaklaşma hız fazlasıyla piste çakılmak,
# çok yatık yaklaşma ise uzun ve rüzgâra açık bir final demek.
INIS_ACI_DIK = 12.0
INIS_ACI_UYARI = 8.0
INIS_ACI_YATIK = 3.0

SEKILLER = ("kare", "daire", "elips")


# ---------------------------------------------------------------------------
# Koordinat dönüşümü
# ---------------------------------------------------------------------------

def olcek(merkez_lat):
    """
    (metre/derece_enlem, metre/derece_boylam) — MERKEZ enlemine göre.

    Ölçek bir şekil için BİR KEZ hesaplanıp bütün noktalarda aynı kullanılmalı.
    Her noktanın kendi enlemiyle ölçeklenirse çember kapanmaz, kare kare olmaz.
    """
    return DERECE_METRE, DERECE_METRE * math.cos(math.radians(merkez_lat))


def metre_ofset(lat0, lon0, dogu_m, kuzey_m, olcekler=None):
    """(lat0, lon0) noktasından doğuya/kuzeye metre kaydırıp koordinat verir."""
    mlat, mlon = olcekler or olcek(lat0)
    return lat0 + kuzey_m / mlat, lon0 + dogu_m / mlon


def mesafe_m(lat1, lon1, lat2, lon2):
    """İki koordinat arası yatay mesafe (metre)."""
    mlat, mlon = olcek((lat1 + lat2) * 0.5)
    return math.hypot((lat2 - lat1) * mlat, (lon2 - lon1) * mlon)


def _dondur(dogu, kuzey, yon_derece):
    """
    Yerel düzlemde döndürür. yon_derece = şeklin +kuzey ekseninin pusula yönü.

    Kalkış yönü seçilemiyor (aşağıya bak), bu yüzden şekli uçağın burnuna
    hizalayabilmek işe yarıyor: kalkıştan hemen sonra 180° dönmek zorunda kalmaz.
    """
    a = math.radians(yon_derece)
    return (dogu * math.cos(a) + kuzey * math.sin(a),
            -dogu * math.sin(a) + kuzey * math.cos(a))


# ---------------------------------------------------------------------------
# Uçuş fiziği
# ---------------------------------------------------------------------------

def donus_yaricapi(hiz_ms, yatis_derece):
    """R = v² / (g·tanθ) — verilen hız ve yatışta dönüş yarıçapı (metre)."""
    yatis = math.radians(max(1.0, min(70.0, yatis_derece)))
    return (hiz_ms ** 2) / (YERCEKIMI * math.tan(yatis))


def elips_cevresi(a_m, b_m):
    """Ramanujan'ın ikinci yaklaşımı — hata milyonda bir mertebesinde."""
    if a_m + b_m <= 0:
        return 0.0
    h = ((a_m - b_m) / (a_m + b_m)) ** 2
    return math.pi * (a_m + b_m) * (1 + 3 * h / (10 + math.sqrt(4 - 3 * h)))


def elips_min_egrilik(a_m, b_m):
    """
    Elipsin en keskin yerindeki eğrilik yarıçapı = kısa² / uzun.

    UZUN eksenin UCUNDA çıkar. Bu ayrım kritik: a=200, b=60 elipsinin "en dar
    yarıçapı 60 m" sanılır, oysa gerçek eğrilik 3600/200 = 18 m'dir ve hiçbir
    uçak bunu dönemez. Yalnızca b'ye bakan bir denetim bunu kaçırır.
    """
    kucuk, buyuk = min(a_m, b_m), max(a_m, b_m)
    return (kucuk ** 2) / buyuk if buyuk > 0 else 0.0


def kabul_yaricapi(aralik_m):
    """Poligon noktalarına yazılacak kabul yarıçapı (tam sayı metre)."""
    return int(max(KABUL_MIN, min(KABUL_MAX, aralik_m / KABUL_BOLEN)))


def poligon_nokta_sayisi(cevre_m):
    """Çevreye göre kaç waypoint kullanılacağı."""
    kaba = int(round(cevre_m / ARALIK_HEDEF))
    return max(POLIGON_MIN_NOKTA, min(POLIGON_MAX_NOKTA, kaba))


# ---------------------------------------------------------------------------
# Şekil noktaları — yerel metre düzleminde (dogu, kuzey)
# ---------------------------------------------------------------------------

def _kare_yerel(kenar_m, yon_derece):
    y = kenar_m / 2.0
    return [_dondur(d, k, yon_derece)
            for d, k in ((-y, +y), (+y, +y), (+y, -y), (-y, -y))]


def _elips_yerel(a_m, b_m, adet, yon_derece, ornek=720):
    """
    Elips noktalarını YAY UZUNLUĞUNA göre eşit dağıtır.

    Basit t = 2πi/N dağıtımı yanlıştır: nokta yoğunluğu eğri boyunca
    sqrt(a²sin²t + b²cos²t) ile değişir, en sık noktalar uzun eksenin
    uçlarında (aralık ≈ b) toplanır. Oysa eğrilik tam orada en yüksektir ve
    kabul yarıçapı kuralı tam orada ihlal edilir. a=170, b=110, N=16 için
    aralık 43-67 m arasında gezinir; ortalaması iyi görünür ama dar uç kuralı
    çiğner. Yay uzunluğu dağıtımı aralığı her yerde cevre/N'e eşitler.
    """
    ts = [2 * math.pi * i / ornek for i in range(ornek + 1)]
    xs = [a_m * math.cos(t) for t in ts]
    ys = [b_m * math.sin(t) for t in ts]

    kumulatif = [0.0]
    for i in range(1, len(ts)):
        kumulatif.append(kumulatif[-1]
                         + math.hypot(xs[i] - xs[i - 1], ys[i] - ys[i - 1]))
    toplam = kumulatif[-1]

    noktalar = []
    for i in range(adet):
        hedef = toplam * i / adet
        j = 1
        while j < len(kumulatif) and kumulatif[j] < hedef:
            j += 1
        j = min(j, len(kumulatif) - 1)
        dilim = kumulatif[j] - kumulatif[j - 1]
        oran = 0.0 if dilim <= 0 else (hedef - kumulatif[j - 1]) / dilim
        t = ts[j - 1] + (ts[j] - ts[j - 1]) * oran
        noktalar.append(_dondur(a_m * math.cos(t), b_m * math.sin(t),
                                yon_derece))
    return noktalar


def _daire_yerel(yaricap_m, adet):
    return [(yaricap_m * math.sin(2 * math.pi * i / adet),
             yaricap_m * math.cos(2 * math.pi * i / adet))
            for i in range(adet)]


def _yerelden_koordinata(yerel, merkez_lat, merkez_lon, irtifa_m):
    olcekler = olcek(merkez_lat)
    noktalar = []
    for dogu, kuzey in yerel:
        lat, lon = metre_ofset(merkez_lat, merkez_lon, dogu, kuzey, olcekler)
        noktalar.append({"lat": lat, "lon": lon, "irtifa": irtifa_m})
    return noktalar


# ---------------------------------------------------------------------------
# Plan üretimi — tek giriş noktası
# ---------------------------------------------------------------------------

def inis_plani(ev_lat, ev_lon, inis_yon, arac, ekle=None, iz_uret=True):
    """
    Kalkış noktasına iniş paterni üretir.

    AUTOLAND modunun (mode_autoland.cpp) geometrisinin göreve yazılabilir
    sadeleştirmesi. AUTOLAND uçarken kalkışta yakaladığı yönü kullanır; görev
    öğeleri ise yüklenirken sabitlenmek zorunda, bu yüzden yön DIŞARIDAN verilir
    — pilot rüzgâra göre seçer.

    Patern iki adımdır:
        1. Yaklaşma başlangıcında (eve `mesafe` kadar uzakta, iniş yönünün
           TERSİNDE) daire çizerek yaklaşma irtifasına alçal.
        2. Oradan eve düz süzülerek in.

    NAV_LOITER_TO_ALT irtifaya ulaştıktan sonra bırakmaz; verify_loiter_heading
    uçağın burnu SONRAKİ noktaya (eve) dönene kadar bekletir
    (commands_logic.cpp verify_loiter_to_alt). Yani daireden çıkış zaten
    hizalıdır, ayrı bir "base leg" öğesi yazmaya gerek yok.

    ekle(seviye, metin) verilirse denetim uyarıları oraya yazılır.

    iz_uret=False yalnızca SAYILARI ve denetimi ister, 58 noktalık çizim izini
    üretmez. Arayüzün uçuş öncesi "iniş hazır mı" göstergesi bunu saniyede
    birkaç kez çağırıyor; çizim izi orada boşuna iş.
    """
    def uyar(seviye, metin):
        if ekle is not None:
            ekle(seviye, metin)

    yaklasma_irtifa = float(arac["AUTOLAND_WP_ALT"])
    mesafe = float(arac["AUTOLAND_WP_DIST"])

    # AUTOLAND ile birebir aynı formül: min(mesafe/3, WP_LOITER_RAD).
    yaricap = min(mesafe / 3.0, abs(arac["WP_LOITER_RAD"]))

    olcekler = olcek(ev_lat)
    # Yaklaşma başlangıcı: evden iniş yönünün TERSİNE `mesafe` kadar. Uçak
    # oradan eve doğru uçarken pusulası `inis_yon`'u gösterir.
    b = math.radians(inis_yon + 180.0)
    bas_lat, bas_lon = metre_ofset(ev_lat, ev_lon,
                                   mesafe * math.sin(b), mesafe * math.cos(b),
                                   olcekler)

    # 3B panelin çizeceği iz: alçalma dairesi + final süzülüşü.
    iz = []
    for i in (range(37) if iz_uret else ()):
        a = math.radians(i * 10.0)
        iz.append({"lat": bas_lat + (yaricap * math.cos(a)) / olcekler[0],
                   "lon": bas_lon + (yaricap * math.sin(a)) / olcekler[1],
                   "irtifa": yaklasma_irtifa})
    for i in (range(21) if iz_uret else ()):
        t = i / 20.0
        iz.append({"lat": bas_lat + (ev_lat - bas_lat) * t,
                   "lon": bas_lon + (ev_lon - bas_lon) * t,
                   "irtifa": yaklasma_irtifa * (1.0 - t)})

    # SÜZÜLME AÇISI DAİRE MERKEZİNDEN HESAPLANMAZ.
    #
    # Uçak alçalma dairesinden TEĞET çıkar; NAV_LAND başladığında eve uzaklığı
    # daire merkezinin uzaklığından küçüktür ve gerçek süzülme merkeze göre
    # hesaplanandan DİKTİR. 19 Ağu 2026 SITL uçuşunda ölçüldü:
    #
    #   merkez 350 m, daire 80 m, irtifa 55 m
    #     merkeze göre        8.9°
    #     otopilotun yazdığı 10.0°   ("Landing glide slope 10.0 degrees")
    #     yakın kenar (D−r)  11.5°
    #
    # Denetim güvenli yönde yanılmalı, o yüzden YAKIN KENAR kullanılıyor:
    # gerçekten uçulandan biraz dik çıkar, asla daha yatık göstermez.
    inis_mesafe = max(1.0, mesafe - yaricap)
    aci = math.degrees(math.atan2(yaklasma_irtifa, inis_mesafe))
    aci_nominal = (math.degrees(math.atan2(yaklasma_irtifa, mesafe))
                   if mesafe > 0 else 90.0)

    # AYNI PARAMETRELER, İKİ FARKLI AYAK İZİ.
    #
    # Göreve gömülü iniş (bizim yazdığımız): alçalma dairesi doğrudan yaklaşma
    #   noktasında -> eve en uzak = mesafe + yarıçap
    # AUTOLAND modu (🛬 butonu, batarya failsafe): daire merkezini yaklaşma
    #   noktasından DİK olarak yarıçap kadar kaydırıyor (base leg,
    #   mode_autoland.cpp) -> merkez sqrt(mesafe² + r²), en uzak + r
    #
    # Fark 250/83 m'de ~14 metre. Küçük ama çit denetimi BÜYÜK olana göre
    # yapılmalı: panel görev sayısını denetleyip 🛬 butonunu açık bırakırsa,
    # buton çitin dışına çıkan bir paterni uçurur.
    #
    # loiter_radius() irtifayla EAS2TAS² kadar büyüyor (AP_L1_Control.cpp);
    # 100 m'de bu %1, göz ardı ediliyor.
    gorev_uzakligi = mesafe + yaricap
    mod_uzakligi = math.hypot(mesafe, yaricap) + yaricap
    en_uzak = max(gorev_uzakligi, mod_uzakligi)

    # --- Denetimler ---
    kullanilabilir = arac["FENCE_RADIUS"] - arac["FENCE_MARGIN"]
    if en_uzak > kullanilabilir:
        uyar("engel",
             f"İniş paterni kalkış yerinden {en_uzak:.0f} m uzağa çıkıyor "
             f"(yaklaşma {mesafe:.0f} m, daire {yaricap:.0f} m) ama güvenlik "
             f"çemberi {arac['FENCE_RADIUS']:.0f} m (pay {arac['FENCE_MARGIN']:.0f} m). "
             f"Uçak çemberi aşınca RTL'e geçip inişi yarıda bırakır. "
             f"AUTOLAND_WP_DIST'i küçültün ya da FENCE_RADIUS'u büyütün.")
    elif en_uzak > kullanilabilir * 0.9:
        uyar("uyari", f"İniş paterni güvenlik çemberinin kenarına yakın "
                      f"({en_uzak:.0f} / {kullanilabilir:.0f} m).")

    if aci > INIS_ACI_DIK:
        uyar("engel", f"Süzülme açısı en kötü halde {aci:.1f}° — çok dik. "
                      f"{yaklasma_irtifa:.0f} m irtifadan {inis_mesafe:.0f} m'de "
                      f"inilmez; AUTOLAND_WP_ALT'ı düşürün ya da "
                      f"AUTOLAND_WP_DIST'i büyütün.")
    elif aci > INIS_ACI_UYARI:
        uyar("uyari", f"Süzülme açısı {aci:.1f}° — diklik sınırında "
                      f"(6-8° tercih edilir).")
    elif aci < INIS_ACI_YATIK:
        uyar("uyari", f"Süzülme açısı {aci:.1f}° — çok yatık, final uzun sürer "
                      f"ve rüzgâra açık kalır.")

    if yaklasma_irtifa > arac["FENCE_ALT_MAX"] - arac["FENCE_MARGIN"]:
        uyar("engel", f"Yaklaşma irtifası {yaklasma_irtifa:.0f} m — irtifa "
                      f"tavanı {arac['FENCE_ALT_MAX']:.0f} m (pay "
                      f"{arac['FENCE_MARGIN']:.0f} m) aşılıyor.")

    return {
        "yon": float(inis_yon) % 360.0,
        "yaklasma_irtifa": yaklasma_irtifa,
        "mesafe": mesafe,
        "loiter_yaricap": round(yaricap, 1),
        "baslangic": {"lat": bas_lat, "lon": bas_lon,
                      "irtifa": yaklasma_irtifa},
        "ev": {"lat": ev_lat, "lon": ev_lon, "irtifa": 0.0},
        "iz": iz,
        "suzulme_acisi": round(aci, 1),            # yakın kenar — denetim bunu kullanır
        "suzulme_acisi_nominal": round(aci_nominal, 1),
        "inis_mesafe": round(inis_mesafe, 1),
        "gorev_uzakligi": round(gorev_uzakligi, 1),   # göreve gömülü iniş
        "mod_uzakligi": round(mod_uzakligi, 1),       # AUTOLAND modu (🛬 butonu)
        "ev_uzakligi_max": round(en_uzak, 1),
    }


def _arac_oku(esikler):
    """
    Araçtan okunan eşikleri normalize eder; okunamayanı varsayılana düşürür.

    Hangi değerlerin varsayılandan geldiğini de döndürür — arayüz "araç
    okunamadı, varsayılanla planlandı" diyebilsin. Sessizce varsayılana düşmek
    sahada yanlış güven verir.
    """
    arac = {}
    varsayilan_kullanildi = []
    for ad, vars_deger in ARAC_VARSAYILAN.items():
        deger = (esikler or {}).get(ad)
        try:
            arac[ad] = float(deger)
            if arac[ad] <= 0 and ad != "FENCE_MARGIN":
                raise ValueError
        except (TypeError, ValueError):
            arac[ad] = vars_deger
            varsayilan_kullanildi.append(ad)
    return arac, varsayilan_kullanildi


def plan_uret(sekil, merkez_lat, merkez_lon, irtifa_m, tur=1,
              olcu_m=None, olcu2_m=None, yon_derece=0.0,
              ev_lat=None, ev_lon=None, esikler=None,
              inis=False, inis_yon=0.0):
    """
    Şekil parametrelerinden tam bir uçuş planı üretir.

    olcu_m'nin anlamı şekle göre değişir:
        kare  → kenar uzunluğu
        daire → yarıçap
        elips → uzun yarı eksen (olcu2_m = kısa yarı eksen)

    Dönen sözlükte iki ayrı nokta listesi vardır ve bu ayrım bilinçlidir:
        "iz"              → 3B panelin ÇİZECEĞİ yol (daire için 72 örnek)
        "gorev_noktalari" → araca GİDECEK öğeler (daire için tek loiter öğesi)
    Daire gerçek bir LOITER_TURNS komutuyla uçuluyor; panelde onu tek nokta
    olarak göstermek yanlış olurdu, göreve 72 waypoint yollamak ise daha yanlış.
    """
    arac, varsayilan_kullanildi = _arac_oku(esikler)
    uyarilar = []

    def ekle(seviye, metin):
        uyarilar.append({"seviye": seviye, "metin": metin})

    hiz = arac["AIRSPEED_CRUISE"]
    yatis_limit = min(arac["ROLL_LIMIT_DEG"], YATIS_TAVAN)
    r_limit = donus_yaricapi(hiz, yatis_limit)
    r_tasarim = donus_yaricapi(hiz * RUZGAR_PAYI, TASARIM_YATIS)

    olcumler = {
        "donus_yaricapi_limit": round(r_limit, 1),
        "donus_yaricapi_tasarim": round(r_tasarim, 1),
        "yatis_limit": round(yatis_limit, 1),
    }

    # --- Şekle göre nokta üretimi -----------------------------------------
    if sekil == "kare":
        kenar = float(olcu_m or 0)
        yerel = _kare_yerel(kenar, yon_derece)
        iz = _yerelden_koordinata(yerel, merkez_lat, merkez_lon, irtifa_m)
        kabul = kabul_yaricapi(kenar)
        gorev = [dict(n, tip="wp", kabul=kabul) for n in iz]
        yontem = "poligon"
        olcumler.update(cevre=round(kenar * 4, 1), aralik=round(kenar, 1),
                        kabul_yaricapi=kabul, min_egrilik=round(kenar / 2, 1))

    elif sekil == "elips":
        a = float(olcu_m or 0)
        b = float(olcu2_m) if olcu2_m else a * 0.65
        if b > a:
            a, b = b, a
            ekle("uyari", "Kısa eksen uzun eksenden büyüktü — yer değiştirdiler.")
        cevre = elips_cevresi(a, b)
        adet = poligon_nokta_sayisi(cevre)
        aralik = cevre / adet if adet else 0.0
        kabul = kabul_yaricapi(aralik)
        yerel = _elips_yerel(a, b, adet, yon_derece)
        iz = _yerelden_koordinata(yerel, merkez_lat, merkez_lon, irtifa_m)
        gorev = [dict(n, tip="wp", kabul=kabul) for n in iz]
        yontem = "poligon"
        olcumler.update(cevre=round(cevre, 1), nokta=adet,
                        aralik=round(aralik, 1), kabul_yaricapi=kabul,
                        min_egrilik=round(elips_min_egrilik(a, b), 1),
                        a=round(a, 1), b=round(b, 1))

    elif sekil == "daire":
        yaricap = float(olcu_m or 0)
        iz = _yerelden_koordinata(_daire_yerel(yaricap, DAIRE_CIZIM_ORNEK),
                                  merkez_lat, merkez_lon, irtifa_m)
        gorev = [{"tip": "loiter_turns", "lat": merkez_lat, "lon": merkez_lon,
                  "irtifa": irtifa_m, "yaricap": yaricap, "tur": int(tur)}]
        yontem = "loiter_turns"
        olcumler.update(cevre=round(2 * math.pi * yaricap, 1),
                        min_egrilik=round(yaricap, 1))
    else:
        raise ValueError(f"bilinmeyen şekil: {sekil}")

    # --- Denetimler --------------------------------------------------------
    _denetle_donus(sekil, olcumler, r_limit, r_tasarim, hiz, yatis_limit, ekle)
    _denetle_cit(iz, gorev, ev_lat, ev_lon, arac, ekle, olcumler)
    _denetle_irtifa(irtifa_m, arac, ekle)
    _denetle_daire_ozel(sekil, gorev, arac, ekle)

    # tur = 0 SONSUZ demek. "or 1" ile yazmak 0'ı sessizce 1'e çevirir; bu hata
    # bir kez yapıldı ve testte yakalandı — kasten uzun yazılıyor.
    tur_sayisi = 1 if tur is None else int(tur)
    if not (0 <= tur_sayisi <= 255):
        ekle("engel", f"Tur sayısı {tur_sayisi} — 0 (sonsuz) ile 255 arasında "
                      f"olmalı.")

    # --- Görev sonu inişi ---------------------------------------------------
    # Şekil denetimlerinden SONRA üretiliyor ki iniş uyarıları da aynı
    # uyarilar listesine düşsün ve engel bayrağını tetikleyebilsin.
    inis_plan = None
    if inis:
        if ev_lat is None or ev_lon is None:
            ekle("engel", "Otomatik iniş istendi ama kalkış noktası bilinmiyor "
                          "— GPS fix olmadan iniş paterni kurulamaz.")
        else:
            inis_plan = inis_plani(ev_lat, ev_lon, inis_yon, arac, ekle)
            olcumler["inis_suzulme_acisi"] = inis_plan["suzulme_acisi"]
            olcumler["inis_uzakligi"] = inis_plan["ev_uzakligi_max"]

    # Uçuş süresi tahmini — sahada batarya planlaması için.
    if hiz > 0 and olcumler.get("cevre"):
        tur_sure = olcumler["cevre"] / hiz
        olcumler["tur_suresi_s"] = round(tur_sure, 1)
        olcumler["toplam_sure_s"] = (None if tur_sayisi == 0
                                     else round(tur_sure * tur_sayisi, 1))

    return {
        "sekil": sekil,
        "yontem": yontem,
        "iz": iz,
        "gorev_noktalari": gorev,
        "merkez": {"lat": merkez_lat, "lon": merkez_lon},
        "irtifa": irtifa_m,
        "tur": tur_sayisi,
        "olcumler": olcumler,
        "inis": inis_plan,
        "uyarilar": uyarilar,
        "engel": any(u["seviye"] == "engel" for u in uyarilar),
        "arac": arac,
        "varsayilan_kullanildi": varsayilan_kullanildi,
    }


def _denetle_donus(sekil, olcumler, r_limit, r_tasarim, hiz, yatis_limit, ekle):
    """Uçak bu şekli fiziksel olarak dönebiliyor mu."""
    egrilik = olcumler.get("min_egrilik", 0.0)

    if sekil == "kare":
        # 90°'lik köşe: kenarın yarısı dönüş yarıçapından küçükse köşe kaybolur.
        if egrilik < r_limit:
            ekle("engel", f"Kenar çok kısa — 90° köşe için kenarın yarısı "
                          f"({egrilik:.0f} m) dönüş yarıçapından ({r_limit:.0f} m) "
                          f"büyük olmalı. En az {r_limit * 2:.0f} m kenar gerekir.")
        elif egrilik < r_tasarim:
            ekle("uyari", f"Kenar sınırda — köşeler belirgin yuvarlanacak. "
                          f"Rüzgârsız günde bile {r_tasarim * 2:.0f} m kenar "
                          f"daha temiz bir kare verir.")
    else:
        ad = "Yarıçap" if sekil == "daire" else "Elipsin en dar kıvrımı"
        if egrilik < r_limit:
            ekle("engel", f"UÇULAMAZ — {ad.lower()} {egrilik:.0f} m. Uçak "
                          f"{hiz:.0f} m/s'te {yatis_limit:.0f}° yatışla en fazla "
                          f"{r_limit:.0f} m yarıçapla döner."
                          + (f" Kısa ekseni büyütün." if sekil == "elips" else ""))
        elif egrilik < r_tasarim:
            ekle("uyari", f"{ad} {egrilik:.0f} m — rüzgârda yer hızı artarsa "
                          f"gereken yatış {TASARIM_YATIS:.0f}°'yi aşar. "
                          f"Önerilen en küçük {r_tasarim:.0f} m.")


def _denetle_cit(iz, gorev, ev_lat, ev_lon, arac, ekle, olcumler):
    """Şekil güvenlik çemberinin içinde kalıyor mu."""
    if ev_lat is None or ev_lon is None:
        ekle("uyari", "Kalkış noktası bilinmiyor — güvenlik çemberi denetlenemedi.")
        return
    fence_r = arac["FENCE_RADIUS"]
    pay = arac["FENCE_MARGIN"]
    kullanilabilir = fence_r - pay

    en_uzak = 0.0
    for n in iz:
        en_uzak = max(en_uzak, mesafe_m(ev_lat, ev_lon, n["lat"], n["lon"]))
    for n in gorev:
        if n.get("tip") == "loiter_turns":
            en_uzak = max(en_uzak,
                          mesafe_m(ev_lat, ev_lon, n["lat"], n["lon"])
                          + n.get("yaricap", 0.0))
    olcumler["ev_uzakligi_max"] = round(en_uzak, 1)

    if en_uzak > kullanilabilir:
        ekle("engel", f"Şeklin en uzak noktası kalkış yerine {en_uzak:.0f} m — "
                      f"güvenlik çemberi {fence_r:.0f} m (pay {pay:.0f} m). "
                      f"Uçak sınırı aşınca kendiliğinden RTL'e geçer.")
    elif en_uzak > kullanilabilir * 0.9:
        ekle("uyari", f"Şekil güvenlik çemberinin kenarına yakın "
                      f"({en_uzak:.0f} / {kullanilabilir:.0f} m).")


def _denetle_irtifa(irtifa_m, arac, ekle):
    fence_alt = arac["FENCE_ALT_MAX"]
    pay = arac["FENCE_MARGIN"]
    tkoff = arac["TKOFF_ALT"]

    if irtifa_m > fence_alt - pay:
        ekle("engel", f"İrtifa {irtifa_m:.0f} m — tavan {fence_alt:.0f} m, "
                      f"pay {pay:.0f} m. En fazla {fence_alt - pay:.0f} m "
                      f"verebilirsiniz, aşarsa uçak RTL'e geçer.")
    elif irtifa_m > fence_alt - 2 * pay:
        ekle("uyari", f"İrtifa {irtifa_m:.0f} m, tavan payına yakın "
                      f"(tavan {fence_alt:.0f} m).")
    if irtifa_m < 30:
        ekle("engel", f"İrtifa {irtifa_m:.0f} m — otonom şekil için çok alçak. "
                      f"En az 30 m, tercihen 60 m ve üstü.")
    elif irtifa_m < tkoff:
        ekle("uyari", f"İrtifa {irtifa_m:.0f} m, kalkış irtifasının "
                      f"({tkoff:.0f} m) altında — uçak şekle alçalarak girer.")


def _denetle_daire_ozel(sekil, gorev, arac, ekle):
    """
    LOITER_TURNS param3 tamsayı metredir ve 255'i aşarsa 10 m'ye yuvarlanır.

    Ayrıca param3 = 0 gönderilirse ArduPlane kullanıcının yarıçapını sessizce
    yok sayıp WP_LOITER_RAD'ı (bu uçakta 90 m) kullanır — asla 0 göndermeyin.
    """
    if sekil != "daire" or not gorev:
        return
    r = gorev[0].get("yaricap", 0.0)
    if r <= 0:
        ekle("engel", "Daire yarıçapı sıfır olamaz — araç bunu görmezden gelip "
                      f"WP_LOITER_RAD ({arac['WP_LOITER_RAD']:.0f} m) kullanır.")
    elif r > 255:
        ekle("uyari", f"Yarıçap {r:.0f} m — 255 m'yi aştığı için araç 10 m'ye "
                      f"yuvarlayarak saklar, gerçek yarıçap birkaç metre sapabilir.")


# ---------------------------------------------------------------------------
# CLI — masada test
# ---------------------------------------------------------------------------

def _testler():
    """Araç olmadan çalışan öz denetim. Çıkış kodu 0 = hepsi geçti."""
    hata = []

    def kontrol(ad, kosul, ayrinti=""):
        print(f"{'  [OK]  ' if kosul else ' [HATA] '} {ad}"
              + (f" — {ayrinti}" if ayrinti else ""))
        if not kosul:
            hata.append(ad)

    lat0, lon0 = 37.6193, -122.3816      # SITL varsayılanı (KSFO)
    E = dict(ARAC_VARSAYILAN)

    # --- Koordinat matematiği ---
    lat, lon = metre_ofset(lat0, lon0, 100.0, 0.0)
    d = mesafe_m(lat0, lon0, lat, lon)
    kontrol("100 m doğuya kayma", abs(d - 100.0) < 0.5, f"{d:.2f} m")

    lat, lon = metre_ofset(lat0, lon0, 0.0, 250.0)
    d = mesafe_m(lat0, lon0, lat, lon)
    kontrol("250 m kuzeye kayma", abs(d - 250.0) < 0.5, f"{d:.2f} m")

    # --- Kare ---
    p = plan_uret("kare", lat0, lon0, 60.0, tur=3, olcu_m=200.0,
                  ev_lat=lat0, ev_lon=lon0, esikler=E)
    iz = p["iz"]
    kenarlar = [mesafe_m(iz[i]["lat"], iz[i]["lon"],
                         iz[(i + 1) % 4]["lat"], iz[(i + 1) % 4]["lon"])
                for i in range(4)]
    kontrol("kare kenarları eşit ve 200 m",
            all(abs(x - 200.0) < 1.0 for x in kenarlar),
            ", ".join(f"{x:.1f}" for x in kenarlar))
    kontrol("200 m kare / 60 m irtifa temiz geçiyor", not p["engel"],
            "; ".join(u["metin"] for u in p["uyarilar"]) or "uyarı yok")
    kontrol("kare noktalarına kabul yarıçapı yazılmış",
            all(n.get("kabul", 0) > 0 for n in p["gorev_noktalari"]),
            f"kabul = {p['olcumler']['kabul_yaricapi']} m")

    # Döndürme kenar uzunluğunu bozmamalı
    p45 = plan_uret("kare", lat0, lon0, 60.0, olcu_m=200.0, yon_derece=45.0,
                    ev_lat=lat0, ev_lon=lon0, esikler=E)
    k45 = mesafe_m(p45["iz"][0]["lat"], p45["iz"][0]["lon"],
                   p45["iz"][1]["lat"], p45["iz"][1]["lon"])
    kontrol("45° döndürülmüş kare kenarı korunuyor", abs(k45 - 200.0) < 1.0,
            f"{k45:.1f} m")

    # --- Elips ---
    p = plan_uret("elips", lat0, lon0, 60.0, tur=3, olcu_m=170.0, olcu2_m=110.0,
                  ev_lat=lat0, ev_lon=lon0, esikler=E)
    iz = p["iz"]
    n = len(iz)
    ar = [mesafe_m(iz[i]["lat"], iz[i]["lon"],
                   iz[(i + 1) % n]["lat"], iz[(i + 1) % n]["lon"])
          for i in range(n)]
    yayilma = (max(ar) - min(ar)) / (sum(ar) / len(ar))
    kontrol("elips nokta aralıkları eşit (%10 içinde)", yayilma < 0.10,
            f"{n} nokta, sapma %{yayilma * 100:.1f}")

    uzak = max(mesafe_m(lat0, lon0, q["lat"], q["lon"]) for q in iz)
    yakin = min(mesafe_m(lat0, lon0, q["lat"], q["lon"]) for q in iz)
    kontrol("elips uzun ekseni 170 m", abs(uzak - 170.0) < 3.0, f"{uzak:.1f} m")
    kontrol("elips kısa ekseni 110 m", abs(yakin - 110.0) < 3.0, f"{yakin:.1f} m")
    kontrol("elips aralığı kabul yarıçapının 2 katından büyük",
            min(ar) > 2 * p["olcumler"]["kabul_yaricapi"],
            f"aralık {min(ar):.0f} m, kabul {p['olcumler']['kabul_yaricapi']} m")
    kontrol("170x110 elips temiz geçiyor", not p["engel"],
            "; ".join(u["metin"] for u in p["uyarilar"]) or "uyarı yok")

    # Sivri elips: b²/a kuralı yakalamalı (b'ye bakan denetim kaçırırdı)
    p = plan_uret("elips", lat0, lon0, 60.0, olcu_m=200.0, olcu2_m=60.0,
                  ev_lat=lat0, ev_lon=lon0, esikler=E)
    kontrol("200x60 elips (eğrilik 18 m) engelleniyor", p["engel"],
            f"min eğrilik {p['olcumler']['min_egrilik']} m")

    # --- Daire ---
    p = plan_uret("daire", lat0, lon0, 60.0, tur=3, olcu_m=120.0,
                  ev_lat=lat0, ev_lon=lon0, esikler=E)
    g = p["gorev_noktalari"]
    kontrol("daire tek loiter öğesi",
            len(g) == 1 and g[0]["tip"] == "loiter_turns" and g[0]["tur"] == 3)
    kontrol("daire izi 72 örnekle çiziliyor", len(p["iz"]) == DAIRE_CIZIM_ORNEK,
            f"{len(p['iz'])} örnek")
    kontrol("120 m daire temiz geçiyor", not p["engel"],
            "; ".join(u["metin"] for u in p["uyarilar"]) or "uyarı yok")

    p = plan_uret("daire", lat0, lon0, 60.0, olcu_m=30.0,
                  ev_lat=lat0, ev_lon=lon0, esikler=E)
    kontrol("30 m yarıçaplı daire engelleniyor", p["engel"])

    # --- Fizik ---
    kontrol("min dönüş yarıçapı 20 m/s + 40° ≈ 49 m",
            abs(donus_yaricapi(20.0, 40.0) - 48.6) < 1.0,
            f"{donus_yaricapi(20.0, 40.0):.1f} m")

    # --- Çit ---
    p = plan_uret("kare", lat0, lon0, 60.0, olcu_m=700.0,
                  ev_lat=lat0, ev_lon=lon0, esikler=E)
    kontrol("700 m kenarlı kare güvenlik çemberini aşıyor", p["engel"],
            f"en uzak {p['olcumler']['ev_uzakligi_max']} m")

    p = plan_uret("kare", lat0, lon0, 95.0, olcu_m=200.0,
                  ev_lat=lat0, ev_lon=lon0, esikler=E)
    kontrol("95 m irtifa (tavan 100, pay 20) engelleniyor", p["engel"])

    # --- Araç okunamadığında varsayılana düşme ---
    p = plan_uret("kare", lat0, lon0, 60.0, olcu_m=200.0,
                  ev_lat=lat0, ev_lon=lon0, esikler={})
    kontrol("araç okunamadığında varsayılan bildiriliyor",
            len(p["varsayilan_kullanildi"]) == len(ARAC_VARSAYILAN),
            f"{len(p['varsayilan_kullanildi'])} parametre varsayılandan")

    # --- İniş paterni ------------------------------------------------------
    # Bu uçağın gerçek değerleri: AUTOLAND_WP_DIST=400, WP_LOITER_RAD=90,
    # FENCE_RADIUS=300, FENCE_MARGIN=20 -> patern 490 m, çember 280 m.
    esik_gercek = {"AUTOLAND_WP_ALT": 55.0, "AUTOLAND_WP_DIST": 400.0,
                   "WP_LOITER_RAD": 90.0, "FENCE_RADIUS": 300.0,
                   "FENCE_MARGIN": 20.0, "FENCE_ALT_MAX": 100.0}
    pl = plan_uret("kare", lat0, lon0, 60.0, tur=1, olcu_m=250.0,
                   ev_lat=lat0, ev_lon=lon0, esikler=esik_gercek,
                   inis=True, inis_yon=90.0)
    kontrol("iniş istendiğinde plana 'inis' anahtarı geliyor",
            pl["inis"] is not None)
    kontrol("iki ayak izi ayrı hesaplanıyor, denetim büyüğe göre",
            pl["inis"]["gorev_uzakligi"] == 490.0
            and pl["inis"]["mod_uzakligi"] == 500.0
            and pl["inis"]["ev_uzakligi_max"] == 500.0,
            f"görev {pl['inis']['gorev_uzakligi']} m, "
            f"AUTOLAND modu {pl['inis']['mod_uzakligi']} m")
    kontrol("iniş yarıçapı min(mesafe/3, WP_LOITER_RAD) = 90 m",
            pl["inis"]["loiter_yaricap"] == 90.0,
            f"{pl['inis']['loiter_yaricap']} m")
    kontrol("400 m yaklaşma + 90 m daire = 490 m, 280 m çemberi aşıyor",
            any("İniş paterni" in u["metin"] and u["seviye"] == "engel"
                for u in pl["uyarilar"]),
            f"en uzak {pl['inis']['ev_uzakligi_max']} m")

    # Yaklaşma başlangıcı iniş yönünün TERSİNDE olmalı: yön 90 (doğu) ise
    # başlangıç evin BATISINDA, yani boylamı küçük.
    kontrol("yön 90° (doğuya iniş) -> başlangıç evin batısında",
            pl["inis"]["baslangic"]["lon"] < lon0
            and abs(pl["inis"]["baslangic"]["lat"] - lat0) < 1e-4,
            f"lon {pl['inis']['baslangic']['lon']:.5f} < {lon0}")
    kontrol("başlangıç noktası evden tam AUTOLAND_WP_DIST kadar uzakta",
            abs(mesafe_m(lat0, lon0, pl["inis"]["baslangic"]["lat"],
                         pl["inis"]["baslangic"]["lon"]) - 400.0) < 1.0)

    # Çemberi büyütünce engel kalkmalı, süzülme açısı da makul olmalı.
    esik_genis = dict(esik_gercek, FENCE_RADIUS=600.0)
    pl2 = plan_uret("kare", lat0, lon0, 60.0, tur=1, olcu_m=250.0,
                    ev_lat=lat0, ev_lon=lon0, esikler=esik_genis,
                    inis=True, inis_yon=0.0)
    kontrol("çember 600 m olunca iniş engeli kalkıyor", not pl2["engel"],
            f"{[u['metin'][:40] for u in pl2['uyarilar']]}")
    kontrol("süzülme açısı yakın kenardan: 55 m / (400-90) m ≈ 10.1°",
            abs(pl2["inis"]["suzulme_acisi"] - 10.1) < 0.2,
            f"{pl2['inis']['suzulme_acisi']}° (merkezden "
            f"{pl2['inis']['suzulme_acisi_nominal']}°)")
    kontrol("nominal açı da ayrıca bildiriliyor (merkezden 7.8°)",
            abs(pl2["inis"]["suzulme_acisi_nominal"] - 7.8) < 0.2)

    # Dik süzülme engellenmeli: 55 m'den 150 m'de inmek 20°.
    esik_dik = dict(esik_genis, AUTOLAND_WP_DIST=150.0)
    pl3 = plan_uret("kare", lat0, lon0, 60.0, tur=1, olcu_m=250.0,
                    ev_lat=lat0, ev_lon=lon0, esikler=esik_dik,
                    inis=True, inis_yon=0.0)
    kontrol("çok dik süzülme (20°) engelleniyor",
            any("Süzülme" in u["metin"] and u["seviye"] == "engel"
                for u in pl3["uyarilar"]),
            f"{pl3['inis']['suzulme_acisi']}°")

    # Ev bilinmiyorsa iniş kurulamaz — sessizce atlanmamalı.
    pl4 = plan_uret("kare", lat0, lon0, 60.0, tur=1, olcu_m=250.0,
                    ev_lat=None, ev_lon=None, esikler=esik_genis, inis=True)
    kontrol("kalkış noktası yokken iniş engel veriyor",
            pl4["engel"] and pl4["inis"] is None)

    # İniş istenmezse plan değişmemeli.
    pl5 = plan_uret("kare", lat0, lon0, 60.0, tur=1, olcu_m=250.0,
                    ev_lat=lat0, ev_lon=lon0, esikler=esik_gercek)
    kontrol("iniş istenmediğinde 'inis' None ve uyarı eklenmiyor",
            pl5["inis"] is None and not pl5["engel"])

    print()
    if hata:
        print(f"SONUÇ: {len(hata)} test BAŞARISIZ — {', '.join(hata)}")
        return 1
    print("SONUÇ: tüm testler geçti")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Şekil waypoint'lerini hesaplar")
    ap.add_argument("--test", action="store_true", help="öz denetimi çalıştır")
    ap.add_argument("--sekil", choices=SEKILLER, default="kare")
    ap.add_argument("--lat", type=float, default=37.6193)
    ap.add_argument("--lon", type=float, default=-122.3816)
    ap.add_argument("--olcu", type=float, default=200.0,
                    help="kare: kenar, daire: yarıçap, elips: uzun yarı eksen")
    ap.add_argument("--olcu2", type=float, default=None,
                    help="elips kısa yarı eksen")
    ap.add_argument("--irtifa", type=float, default=60.0)
    ap.add_argument("--yon", type=float, default=0.0)
    ap.add_argument("--tur", type=int, default=3)
    args = ap.parse_args()

    if args.test:
        return _testler()

    plan = plan_uret(args.sekil, args.lat, args.lon, args.irtifa, args.tur,
                     args.olcu, args.olcu2, args.yon,
                     ev_lat=args.lat, ev_lon=args.lon)
    # İz uzun olabiliyor; CLI'da özet göster.
    ozet = dict(plan)
    ozet["iz"] = f"<{len(plan['iz'])} nokta>"
    print(json.dumps(ozet, ensure_ascii=False, indent=2))
    return 1 if plan["engel"] else 0


if __name__ == "__main__":
    sys.exit(main())
