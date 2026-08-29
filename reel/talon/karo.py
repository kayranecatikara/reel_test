# -*- coding: utf-8 -*-
"""
================================================================================
HARİTA KAROSU — bir kez indir, sahada ÇEVRİMDIŞI kullan
================================================================================
⛔⛔ NİYE ÖNBELLEK: uçuş alanında internet OLMAYABİLİR. Doğrudan OSM'den
   karo çeken bir plan ekranı sahada BOŞ açılır — ve bunu tam waypoint
   koyman gereken anda öğrenirsin. Bu yüzden karolar ÖNCEDEN indirilir,
   diske yazılır ve panel onları DİSKTEN servis eder.

TERİMLER (CLAUDE.md §0.2):
  * KARO (tile): harita 256x256 piksellik karelere bölünür. Her karo
    (z, x, y) ile adreslenir: z = yakınlaşma seviyesi, x/y = ızgara yeri.
  * WEB MERCATOR: karoların kullandığı izdüşüm. Enlem/boylamı karo
    numarasına çeviren formül aşağıda; kutuplara doğru mesafeleri şişirir
    ama bizim ölçeğimizde (birkaç km) etkisi ihmal edilebilir.
  * ZOOM SEVİYESİ: z arttıkça karo küçülür, ayrıntı artar, SAYI 4 KATINA
    çıkar. 41° enlemde karo kenarı:
        z=15 -> 923 m     z=16 -> 462 m     z=17 -> 231 m     z=18 -> 115 m

⚠ OSM KULLANIM NEZAKETİ: karolar gönüllü sunuculardan gelir. İndirici
  saniyede en fazla birkaç istek atar, kimliğini bildirir ve İNDİRDİĞİNİ
  BİR DAHA İNDİRMEZ. Toplu indirme yalnız kendi uçuş alanın içindir.
================================================================================
"""
import json
import math
import os
import time
import urllib.request

KOK = os.path.expanduser(os.environ.get("DOW_KARO_DIZIN", "~/.skydagger/karolar"))
SUNUCU = os.environ.get(
    "DOW_KARO_SUNUCU", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
KIMLIK = "TeknofestAvciDrone/1.0 (yer kontrol istasyonu; tek seferlik alan indirmesi)"


# ----------------------------------------------------------------------
#  WEB MERCATOR
# ----------------------------------------------------------------------
def karo_no(enlem, boylam, z):
    """(enlem, boylam, z) -> (x, y) karo numarası (tam sayı)."""
    n = 2.0 ** z
    x = (boylam + 180.0) / 360.0 * n
    r = math.radians(max(-85.05, min(85.05, enlem)))
    y = (1.0 - math.asinh(math.tan(r)) / math.pi) / 2.0 * n
    return int(x), int(y)


def karo_kose(x, y, z):
    """Karo numarasından SOL ÜST köşenin (enlem, boylam)'ı."""
    n = 2.0 ** z
    boylam = x / n * 360.0 - 180.0
    enlem = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return enlem, boylam


def metre_piksel(enlem, z):
    """Bir pikselin kaç metreye denk geldiği (o enlemde)."""
    return 156543.03392 * math.cos(math.radians(enlem)) / (2.0 ** z)


# ----------------------------------------------------------------------
#  ÖNBELLEK
# ----------------------------------------------------------------------
def yol(z, x, y):
    return os.path.join(KOK, str(z), str(x), "%d.png" % y)


def var_mi(z, x, y):
    p = yol(z, x, y)
    return os.path.exists(p) and os.path.getsize(p) > 100


def oku(z, x, y):
    p = yol(z, x, y)
    if not var_mi(z, x, y):
        return None
    with open(p, "rb") as f:
        return f.read()


def indir(z, x, y, zaman_asimi=10.0):
    """Tek karo indir ve önbelleğe yaz. Döner: (basarili, mesaj)."""
    if var_mi(z, x, y):
        return True, "zaten var"
    url = SUNUCU.format(z=z, x=x, y=y)
    istek = urllib.request.Request(url, headers={"User-Agent": KIMLIK})
    try:
        with urllib.request.urlopen(istek, timeout=zaman_asimi) as y_:
            veri = y_.read()
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)
    if len(veri) < 100:
        return False, "boş karo"
    p = yol(z, x, y)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    gecici = p + ".tmp"
    with open(gecici, "wb") as f:
        f.write(veri)
    os.replace(gecici, p)          # ⛔ ATOMİK: yarım dosya önbelleğe girmesin
    return True, "indirildi"


def alan_karolari(enlem, boylam, yaricap_m, z_alt, z_ust):
    """Verilen daireyi kapsayan karo listesi: [(z, x, y), ...]"""
    liste = []
    for z in range(int(z_alt), int(z_ust) + 1):
        mp = metre_piksel(enlem, z)
        karo_m = mp * 256.0
        n_karo = int(math.ceil(yaricap_m / karo_m)) + 1
        x0, y0 = karo_no(enlem, boylam, z)
        for dx in range(-n_karo, n_karo + 1):
            for dy in range(-n_karo, n_karo + 1):
                liste.append((z, x0 + dx, y0 + dy))
    return liste


def alan_indir(enlem, boylam, yaricap_m=2000.0, z_alt=14, z_ust=17,
               bekle=0.12, ilerleme=None):
    """Uçuş alanını indir. Döner: (indirilen, zaten_var, hata)."""
    liste = alan_karolari(enlem, boylam, yaricap_m, z_alt, z_ust)
    ind = varr = hata = 0
    for i, (z, x, y) in enumerate(liste):
        if var_mi(z, x, y):
            varr += 1
        else:
            ok, _m = indir(z, x, y)
            if ok:
                ind += 1
            else:
                hata += 1
            time.sleep(bekle)      # ⚠ OSM nezaketi: saniyede ~8 istek
        if ilerleme and (i % 10 == 0 or i == len(liste) - 1):
            ilerleme(i + 1, len(liste), ind, varr, hata)
    if ind or varr:
        # En az bir karo eldeyse alan kullanılabilir demektir; hepsi hata
        # verdiyse (internet yok) not TUTMA — panel boş haritaya oturmasın.
        alan_yaz(enlem, boylam, yaricap, z_alt, z_ust)
    return ind, varr, hata


ALAN_DOSYA = os.path.join(KOK, "alan.json")


def alan_yaz(enlem, boylam, yaricap, z_alt, z_ust):
    """En son indirilen alanı diske not et.

    NEDEN: panel açıldığında haritayı bir yere oturtmak zorunda. GPS fix
    henüz yoksa (uçak daha açılmadı, ya da kapalı ortamdasın) elde tek
    bilgi budur — kullanıcı zaten TAM O ALANI indirdiği için doğru
    tahmindir. EV noktası gelince panel oraya kayar.
    """
    try:
        os.makedirs(KOK, exist_ok=True)
        gecici = ALAN_DOSYA + ".yeni"
        with open(gecici, "w", encoding="utf-8") as f:
            json.dump({"enlem": float(enlem), "boylam": float(boylam),
                       "yaricap": float(yaricap), "z_alt": int(z_alt),
                       "z_ust": int(z_ust), "zaman": time.time()}, f)
        os.replace(gecici, ALAN_DOSYA)
    except OSError:
        pass        # not tutamamak indirmeyi geçersiz kılmaz


def alan_oku():
    """En son indirilen alan, ya da None."""
    try:
        with open(ALAN_DOSYA, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d.get("enlem"), (int, float)) and \
                isinstance(d.get("boylam"), (int, float)):
            return d
    except (OSError, ValueError):
        pass
    return None


_DURUM_ONB = {"t": 0.0, "d": None}
_DURUM_TTL = 3.0        # s


def onbellek_durumu(taze=False):
    """Önbellekteki karo sayısı ve boyutu.

    ⚠ Bu fonksiyon TÜM DİZİNİ dolaşır. 2000 karoda bu bir HTTP isteğini
      onlarca ms bekletir; panel 700 ms'de bir sorduğu için sonucu
      3 s boyunca saklıyoruz. `taze=True` taramayı zorlar.
    """
    simdi = time.time()
    if not taze and _DURUM_ONB["d"] is not None and \
            simdi - _DURUM_ONB["t"] < _DURUM_TTL:
        return _DURUM_ONB["d"]
    n = 0
    bayt = 0
    for kok, _d, dosyalar in os.walk(KOK):
        for f in dosyalar:
            if f.endswith(".png"):
                n += 1
                try:
                    bayt += os.path.getsize(os.path.join(kok, f))
                except OSError:
                    pass
    d = {"dizin": KOK, "karo": n, "mb": round(bayt / 1e6, 1),
         "alan": alan_oku()}
    _DURUM_ONB["t"] = simdi
    _DURUM_ONB["d"] = d
    return d
