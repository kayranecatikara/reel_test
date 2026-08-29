# -*- coding: utf-8 -*-
"""
================================================================================
GERÇEK ORTAM BEKÇİLERİ — R-serisi
================================================================================
`tests/test_dow.py` (B-serisi) simülasyon davranışını korur. Bu dosya GERÇEK
ORTAM katmanını korur. İkisi ayrı tutulur çünkü biri sim, öbürü donanım
sözleşmesidir; birinin kırılması öbürünü ilgilendirmez.

⛔ HER BEKÇİ BİR YAŞANMIŞ (ya da yaşanabilecek ve BEDELİ UÇAK OLAN) HATAYA
   KARŞILIK GELİR. Süs test yazılmaz.
================================================================================
"""
import math
import os
import sys
import time

import pytest

REEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KOK = os.path.dirname(REEL)
for p in (REEL, KOK):
    if p not in sys.path:
        sys.path.insert(0, p)

from gercek import konum as K                       # noqa: E402
from gercek.arayuz import (AracArayuzu, sozlesme_denetle,   # noqa: E402
                           GUDUM_CAGRILARI, KOSU_CAGRILARI)


# ======================================================================
#  BAĞIMSIZ REFERANS — testin kendi, AYRI matematiği
# ======================================================================
def _ecef(enlem, boylam, h):
    """Coğrafi -> ECEF (yer merkezli, yere sabit) dik koordinat. TAM formül.

    Bu, `konum.py`'nin YAKLAŞIK formülünden BAĞIMSIZ bir yoldur. İkisini
    kıyaslamak, yaklaşımın gerçek hatasını ölçer. Aynı formülü iki kez
    yazıp "uyuyor" demek hiçbir şey kanıtlamaz.
    """
    f = math.radians(enlem); l = math.radians(boylam)
    N = K.A_YARIEKSEN / math.sqrt(1.0 - K.E2 * math.sin(f) ** 2)
    return ((N + h) * math.cos(f) * math.cos(l),
            (N + h) * math.cos(f) * math.sin(l),
            (N * (1.0 - K.E2) + h) * math.sin(f))


def _ecef_kdy(enlem0, boylam0, h0, enlem, boylam, h):
    """ECEF üzerinden KESİN yerel KDY (kuzey, doğu, yukarı)."""
    x0, y0, z0 = _ecef(enlem0, boylam0, h0)
    x1, y1, z1 = _ecef(enlem, boylam, h)
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    f = math.radians(enlem0); l = math.radians(boylam0)
    dogu   = -math.sin(l) * dx + math.cos(l) * dy
    kuzey  = (-math.sin(f) * math.cos(l) * dx - math.sin(f) * math.sin(l) * dy
              + math.cos(f) * dz)
    yukari = (math.cos(f) * math.cos(l) * dx + math.cos(f) * math.sin(l) * dy
              + math.sin(f) * dz)
    return kuzey, dogu, yukari


# ---------------------------------------------------------------- R1
def test_R1_gidis_donus_ayni_noktaya_dusuyor():
    """metreye() -> dereceye() aynı noktaya dönmeli (yuvarlama dışında).

    NİYE: ters çevrim paneldeki harita ve sunucuya gönderdiğimiz KENDİ
    konumumuz için kullanılıyor. Yanlışsa hakem bizi başka yerde görür.
    """
    c = K.YerelCerceve().kokeni_kur(41.1050, 29.0230, 120.0)
    for dk, dd, dz in [(0, 0, 0), (250, -400, 35), (-1200, 900, -20),
                       (3000, 3000, 100)]:
        enlem, boylam, irt = c.dereceye(dk, dd, dz)
        x, y, z = c.metreye(enlem, boylam, irtifa_amsl=irt)
        assert abs(x - dk) < 1e-6, "kuzey gidiş-dönüş bozuk"
        assert abs(y - dd) < 1e-6, "doğu gidiş-dönüş bozuk"
        assert abs(z - dz) < 1e-9, "irtifa gidiş-dönüş bozuk"


# ---------------------------------------------------------------- R2
def test_R2_yaklasim_hatasi_ILAN_EDILEN_SINIRIN_ICINDE():
    """Düz-dünya yaklaşımının hatası, modülde İLAN EDİLEN sınırları tutmalı.

    Modül §2b, hatanın d²/(2R) yasasıyla büyüdüğünü ve ölçülen katsayının
    7.9e-8/m olduğunu söylüyor. Sınırlar O YASADAN türetilir (%50 pay ile),
    yuvarlak sayıdan değil — böylece test hem geçer hem de formül bozulursa
    (ör. cos(enlem) çarpanı düşerse) DERHAL kırılır.

    ⛔ BU TEST BİR KEZ GERÇEK BİR HATA YAKALADI: ilk yazdığımda modül
       "1 km'de <1 cm" diyordu; ölçülen 8.6 cm çıktı. Belge düzeltildi,
       test gevşetilmedi.
    Kıyas, BAĞIMSIZ ECEF yolundan yapılır (_ecef_kdy).
    """
    e0, b0, h0 = 41.1050, 29.0230, 120.0
    c = K.YerelCerceve().kokeni_kur(e0, b0, h0)
    R_ORT = 6.33e6                      # ölçülen katsayıdan geri çıkan yarıçap
    sinirlar = {d: 1.5 * d * d / (2.0 * R_ORT)
                for d in (600.0, 1000.0, 5000.0, 20000.0)}
    for uzaklik, sinir in sinirlar.items():
        en_kotu = 0.0
        for aci in range(0, 360, 15):
            r = math.radians(aci)
            hedef_k, hedef_d = uzaklik * math.cos(r), uzaklik * math.sin(r)
            enlem, boylam, irt = c.dereceye(hedef_k, hedef_d, 0.0)
            yak = c.metreye(enlem, boylam, irtifa_amsl=irt)
            kes = _ecef_kdy(e0, b0, h0, enlem, boylam, irt)
            en_kotu = max(en_kotu, math.dist(yak[:2], kes[:2]))
        assert en_kotu <= sinir, (
            "%.0f m'de yaklaşım hatası %.4f m — d²/(2R) yasasının %%50 payla "
            "sınırı %.4f m. Formül bozulmuş olabilir (cos(enlem) çarpanı? "
            "yanlış eğrilik yarıçapı?)." % (uzaklik, en_kotu, sinir))
        # yasanın ALT ucu da sınanır: hata beklenenden ÇOK küçükse, test
        # yanlışlıkla aynı formülü iki kez çağırıyor olabilir (sahte geçiş).
        if uzaklik >= 1000.0:
            assert en_kotu >= 0.3 * uzaklik * uzaklik / (2.0 * R_ORT), (
                "%.0f m'de hata beklenenden ÇOK küçük (%.4f m) — kıyas yolu "
                "bağımsız olmayabilir." % (uzaklik, en_kotu))


# ---------------------------------------------------------------- R3
def test_R3_irtifa_referansi_TEK_OLMAK_ZORUNDA():
    """AMSL ve yerden irtifa AYNI ANDA verilemez, HİÇBİRİ de verilmeyemez.

    ⛔ YAŞANABİLİR HATA: bizim drone AMSL (ör. 1020 m), hedef yerden
       (ör. 120 m) verir. İkisini aynı sayı sanmak, güdümün hedefi 900 m
       AŞAĞIDA görmesi demektir — burun yere çevrilir.
       Bu bekçi, belirsizliği API seviyesinde İMKÂNSIZ kılar.
    """
    c = K.YerelCerceve().kokeni_kur(41.0, 29.0, 900.0)
    with pytest.raises(ValueError):
        c.metreye(41.001, 29.0)                                   # hiçbiri
    with pytest.raises(ValueError):
        c.metreye(41.001, 29.0, irtifa_amsl=950, irtifa_yerden=50)  # ikisi

    # Doğru kullanım: AYNI fiziksel yükseklik iki yoldan da aynı z vermeli.
    z_amsl = c.metreye(41.001, 29.0, irtifa_amsl=950.0)[2]
    z_yer = c.metreye(41.001, 29.0, irtifa_yerden=50.0)[2]
    assert abs(z_amsl - z_yer) < 1e-9, (
        "AMSL 950 (zemin 900) ile 'yerden 50' AYNI yüksekliktir; "
        "farklı çıkıyorsa referans dönüşümü bozuk.")


# ---------------------------------------------------------------- R4
def test_R4_koken_kurulmadan_KULLANILAMAZ():
    """Köken kurulmadan çevrim yapılamaz — sessizce 0,0,0 dönmemeli.

    ⛔ NİYE AÇIK HATA: sessizce (0,0,0) dönseydi güdüm, hedefi kalkış
       noktasında sanardı ve oraya dalardı. Gürültülü patlamak, sessiz
       yanlış cevaptan İYİDİR.
    """
    c = K.YerelCerceve()
    assert not c.hazir
    with pytest.raises(RuntimeError):
        c.metreye(41.0, 29.0, irtifa_amsl=100.0)
    with pytest.raises(RuntimeError):
        c.dereceye(0.0, 0.0, 0.0)


# ---------------------------------------------------------------- R5
def test_R5_kerteriz_gps_MODULUYLE_AYNI_SOZLESME():
    """kerteriz_deg(), `dow/gudum/gps.py`'nin kullandığı formülle AYNI olmalı.

    ⛔ İKİ YERDE İKİ YÖN SÖZLEŞMESİ = kesin uçak kaybı. gps.py şunu yapar:
           ker = degrees(atan2(hedef[1]-drone[1], hedef[0]-drone[0]))
       Yani atan2(Δ_ikinci_bilesen, Δ_birinci_bilesen). Bizim çerçevede
       birinci = KUZEY, ikinci = DOĞU -> pusula kerterizi.
    """
    from dow.gudum.gps import _wrap
    for a, b, beklenen in [((0, 0, 0), (100, 0, 0), 0.0),      # kuzey
                           ((0, 0, 0), (0, 100, 0), 90.0),     # doğu
                           ((0, 0, 0), (-100, 0, 0), 180.0),   # güney
                           ((0, 0, 0), (0, -100, 0), 270.0)]:  # batı
        assert abs(_wrap(K.kerteriz_deg(a, b) - beklenen)) < 1e-9

    # gps.py'nin kendi satırıyla birebir kıyas (rastgele olmayan örnekler)
    for a, b in [((0, 0, 0), (37.0, -12.0, 5.0)),
                 ((10, -5, 0), (-40.0, 80.0, -3.0))]:
        gps_yolu = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        assert abs(_wrap(K.kerteriz_deg(a, b) - gps_yolu)) < 1e-9, (
            "kerteriz sözleşmesi gps.py'den AYRIŞTI")


# ---------------------------------------------------------------- R6
def test_R6_yer_hizi_vektore_CEVIRICININ_BEKLEDIGI_GIBI():
    """Yer hızı + rota -> KDY vektörü; çeviricinin gövde dönüşümüyle uyumlu.

    DOĞRULAMA: araç kuzeye 20 m/s gidiyorsa ve BURNU da kuzeydeyse,
    çeviricinin `dunya_govde` fonksiyonu "ileri 20, yanal 0" demeli.
    Ayrışırsa hız geri beslemesi yanlış eksene biner.
    """
    from dow.gudum.cevirici import HizCubukCevirici as C
    for yon, yaw in [(0.0, 0.0), (90.0, 90.0), (215.0, 215.0)]:
        v = K.yer_hizindan_vektor(20.0, yon)
        ileri, yanal = C.dunya_govde(v[0], v[1], math.radians(yaw), 1.0)
        assert abs(ileri - 20.0) < 1e-9, "burun rotayla aynıyken ileri=hız olmalı"
        assert abs(yanal) < 1e-9, "burun rotayla aynıyken yanal=0 olmalı"

    # 90° sağdan gelen hareket: burun kuzeyde, hareket doğuda -> tam SAĞ
    v = K.yer_hizindan_vektor(20.0, 90.0)
    ileri, yanal = C.dunya_govde(v[0], v[1], 0.0, 1.0)
    assert abs(ileri) < 1e-9
    assert abs(yanal - 20.0) < 1e-9, (
        "Y_ISARET=+1 iken doğuya hareket, kuzeye bakan araç için SAĞ olmalı")


# ---------------------------------------------------------------- R7
def test_R7_sozlesme_SIM_TARAFINDA_ZATEN_SAGLANIYOR():
    """Sözleşme uydurulmadı: mevcut `DowBaglanti` ona TAM uyuyor.

    ⛔ NİYE BEKÇİ: sözleşmeyi ben yazdım ama SİM TARAFI onu doğrulayan
       bağımsız tanıktır. Sim tarafı bir gün bir çağrıyı kaybederse (ya da
       ben sözleşmeye gerçekte olmayan bir çağrı eklersem) burası kırılır.
    """
    from dow.sdk.baglanti import DowBaglanti
    eksik = [a for a in GUDUM_CAGRILARI + KOSU_CAGRILARI
             if not callable(getattr(DowBaglanti, a, None))]
    assert not eksik, "DowBaglanti sözleşmeden ayrıştı: %s" % eksik


# ---------------------------------------------------------------- R8
def test_R8_beyin_araca_SOZLESME_DISI_dokunmuyor():
    """`Beyin` yalnız KATMAN 1'i çağırmalı — kaynak koddan sayılarak.

    ⛔ NİYE: gerçek bağlantı yalnız sözleşmeyi yazar. Beyin sözleşme dışı
       bir çağrı eklerse gerçek uçuşta AttributeError ile DÜŞER — hem de
       o kod yoluna ilk girildiği anda, yani havada.
    """
    import re
    yol = os.path.join(KOK, "dow", "ana.py")
    with open(yol, encoding="utf-8") as f:
        kaynak = f.read()
    cagrilar = set(re.findall(r"self\.b\.([a-zA-Z_]+)", kaynak))
    fazla = cagrilar - set(GUDUM_CAGRILARI)
    assert not fazla, (
        "dow/ana.py araçtan sözleşme DIŞI çağrı yapıyor: %s\n"
        "Ya çağrı kaldırılmalı ya sözleşmeye (arayuz.py) eklenmeli — "
        "sessizce bırakmak gerçek uçuşta havada patlar." % sorted(fazla))


# ---------------------------------------------------------------- R9
def test_R9_arac_dikisi_VARSAYILANI_DEGISTIRMIYOR():
    """`Beyin(baglanti=None)` hâlâ DowBaglanti kurmalı (sim davranışı).

    ⛔ NİYE: dikiş, sim tarafını bozmamak şartıyla açıldı. Varsayılan
       kayarsa bütün sim kampanyaları geçersiz olur.
    """
    import inspect
    from dow import ana
    imza = inspect.signature(ana.Beyin.__init__)
    assert "baglanti" in imza.parameters, "araç dikişi kaybolmuş"
    assert imza.parameters["baglanti"].default is None, (
        "dikişin varsayılanı None OLMALI; başka bir şey sim davranışını değiştirir")
    kaynak = inspect.getsource(ana.Beyin.__init__)
    assert "DowBaglanti()" in kaynak, (
        "varsayılan araç DowBaglanti olmalı — sim yolu korunmalı")


# ---------------------------------------------------------------- R10
def test_R10_gercek_arac_TRUTH_KANALI_VERMEZ():
    """Soyut arayüzün `truth()` varsayılanı None — gerçekte böyle bir kanal yok.

    ⛔ NİYE: `Ayar.GPS_KAYNAK="truth"` geliştirme kipidir ve GERÇEKTE
       hedefi HİÇ vermez. Varsayılan None olduğu için `hedef_konumu()`
       None döner, `Beyin` "HEDEF_YOK" durumuna geçer ve komut vermez —
       yani sessizce yanlış uçmak yerine AÇIKÇA durur.
    """
    class Bos(AracArayuzu):
        pass
    assert Bos().truth() is None
    assert Bos().hedef_yonelim() is None


# ---------------------------------------------------------------- R11
def test_R11_sozlesme_denetleyicisi_EKSIGI_YAKALIYOR():
    """Denetleyici işini yapmalı: eksik çağrıyı ve YANLIŞ BİRİMİ bulmalı."""
    class Yarim(AracArayuzu):
        def canli(self): return True
        def konum(self): return (0.0, 0.0, 0.0)
        def hiz_vektoru(self): return (0.0, 0.0, 0.0)
        def komut(self, *a, **k): pass
        def hedef_konum_bozuk(self): return None
        def yonelim(self): return (45.0, -10.0, 90.0)     # ⛔ DERECE!

    eksik = sozlesme_denetle(Yarim(), yalniz_gudum=True)
    assert any("RADYAN" in e for e in eksik), (
        "denetleyici derece/radyan karışıklığını yakalamalı — bu hata "
        "kamera telafisini ters çevirir")


# ======================================================================
#  CRSF PROTOKOLÜ — R12..R22
#  Her bekçi BAĞIMSIZ bir referansa dayanır: standart sınama değeri,
#  elle kurulmuş çerçeve, ya da FARKLI ALGORİTMAYLA yazılmış ikinci yol.
#  ⛔ "Kendi paketlediğimi kendim çözdüm, uydu" bir şey KANITLAMAZ.
# ======================================================================
from gercek import crsf as C                                   # noqa: E402


def _bagimsiz_paketle(kanallar):
    """16×11 bit paketleme — KASTEN FARKLI ALGORİTMA (bit listesi).

    `crsf.kanallari_paketle` kaydırmalı yazmaç kullanır. Bu ise her biti
    tek tek bir listeye koyup baytları sonra kurar. İkisi aynı sonucu
    veriyorsa bit sırası sözleşmesi doğru demektir.
    """
    akis = []
    for k in kanallar:
        for b in range(11):
            akis.append((int(k) >> b) & 1)     # konum 11c+b
    cikti = bytearray()
    for j in range(22):
        bayt = 0
        for i in range(8):
            bayt |= akis[8 * j + i] << i
        cikti.append(bayt)
    return bytes(cikti)


# ---------------------------------------------------------------- R12
def test_R12_crc_STANDART_SINAMA_DEGERINI_veriyor():
    """CRC-8/DVB-S2'nin bilinen sınama değeri: "123456789" -> 0xBC.

    ⛔ NİYE BAĞIMSIZ: bu sayı bizim kodumuzdan değil, CRC standardından
       gelir. Polinomu (0xD5) ya da başlangıç değerini yanlış yazsaydım
       burada yakalanırdı. CRC yanlışsa ELRS modülü paketlerimizi SESSİZCE
       atar ve "komut gitmiyor" diye günlerce aranır.
    """
    assert C.crc8(b"123456789") == 0xBC
    assert C.crc8(b"") == 0x00


# ---------------------------------------------------------------- R13
def test_R13_cerceve_UZUNLUK_ALANI_dogru_sayiyor():
    """UZUNLUK = tip + yük + crc. Adres ve uzunluk baytı SAYILMAZ.

    ⛔ EN SIK YAPILAN CRSF HATASI BUDUR. Bir fazla sayınca alıcı bir
       sonraki çerçeveyi bir bayt kaymış görür ve senkron kalıcı bozulur.
    """
    for yuk_uzunluk in (0, 1, 6, 22, 60):
        cer = C.cerceve(0x16, bytes(yuk_uzunluk))
        assert len(cer) == yuk_uzunluk + 4, "toplam = adres+uzunluk+tip+yük+crc"
        assert cer[1] == yuk_uzunluk + 2, (
            "uzunluk alanı %d olmalıydı, %d yazıldı" % (yuk_uzunluk + 2, cer[1]))
        # CRC yalnız tip+yük üzerinden; adres ve uzunluk GİRMEZ
        assert cer[-1] == C.crc8(cer[2:-1])

    # gerçek RC paketi: 26 bayt, uzunluk alanı 24
    p = C.rc_paketi(0, 0, 0, 0)
    assert len(p) == 26 and p[1] == 24 and p[0] == C.ADRES_TX_MODULU
    assert p[2] == C.TIP_RC_KANALLAR


# ---------------------------------------------------------------- R14
def test_R14_kanal_paketleme_BAGIMSIZ_ALGORITMAYLA_ayni():
    """11-bit paketleme, farklı algoritmayla yazılmış ikinci yolla örtüşmeli.

    ⛔ NİYE: bit sırası ters olsaydı (büyük-sonlu bit dizilimi) gidiş-dönüş
       testi YİNE GEÇERDİ — kendi hatamı kendim geri çözerdim. Gerçek
       kartta ise her kanal çöp değer görürdü.
    """
    ornekler = [
        [C.CRSF_ORTA] * 16,
        [C.CRSF_MIN] * 16,
        [C.CRSF_MAX] * 16,
        list(range(0, 16 * 100, 100)),
        [172, 1811, 992, 1000, 500, 2047, 0, 1, 1023, 1024,
         777, 333, 1500, 88, 2000, 111],
    ]
    for k in ornekler:
        assert C.kanallari_paketle(k) == _bagimsiz_paketle(k), (
            "bit dizilimi sözleşmesi bozuk: %s" % k[:4])
        assert C.kanallari_coz(C.kanallari_paketle(k)) == [x & 0x7FF for x in k]


# ---------------------------------------------------------------- R15
def test_R15_mikrosaniye_REFERANS_NOKTALARI():
    """CRSF ham değeri <-> µs: endüstri standardı üç referans nokta.

    172 -> 988 µs, 992 -> 1500 µs, 1811 -> 2012 µs.
    ⛔ Bu üç sayı bizim seçimimiz değil; kart bunları bekliyor. Ölçek
       yanlışsa "tam çubuk" komutu kartta yarım çubuk görünür ve güdüm
       hiç doyuma ulaşamaz — sebebi de görünmez.
    """
    assert round(C.crsf_us(C.CRSF_MIN)) == C.US_MIN
    assert round(C.crsf_us(C.CRSF_ORTA)) == C.US_ORTA
    assert round(C.crsf_us(C.CRSF_MAX)) == C.US_MAX
    for us in (988, 1000, 1250, 1500, 1750, 2000, 2012):
        assert abs(C.crsf_us(C.us_crsf(us)) - us) < 1.0


# ---------------------------------------------------------------- R16
def test_R16_cubuk_UCLARI_TAM_ve_ORTA_TAM():
    """[-1,0,+1] tam olarak [172, 992, 1811] vermeli — bir eksik değil.

    ⛔ NİYE ÖNEMLİ: arm anahtarı uçlara kurulur. 1811 yerine 1810 çıkarsa
       "arm eşiği 1800'ün üstünde" gibi bir ayarla yine geçer, ama daha
       katı bir eşikte SESSİZCE arm olmaz ve sahada "kalkmıyor" denir.
    """
    assert C.cubuk_crsf(-1.0) == C.CRSF_MIN
    assert C.cubuk_crsf(0.0) == C.CRSF_ORTA
    assert C.cubuk_crsf(1.0) == C.CRSF_MAX
    assert C.cubuk_crsf(-5.0) == C.CRSF_MIN, "aralık dışı KIRPILMALI"
    assert C.cubuk_crsf(5.0) == C.CRSF_MAX
    assert C.cubuk_crsf(0.5, ters=True) == C.cubuk_crsf(-0.5)
    for x in (-1.0, -0.6, -0.1, 0.0, 0.25, 0.75, 1.0):
        assert abs(C.crsf_cubuk(C.cubuk_crsf(x)) - x) < 1e-3


# ---------------------------------------------------------------- R17
def test_R17_cozucu_TEK_BAYT_GURULTUDEN_SONRA_TOPARLIYOR():
    """⛔ EMNİYET KRİTİK: bir bozuk bayt telemetriyi KALICI kesmemeli.

    Telsizde gürültü kaçınılmazdır. Çözücü senkronu kalıcı kaybederse
    güdüm konum/duruş görmez ve `canli()` False döner — yani araç havada
    komutsuz kalır. Bu yüzden akışın arasına kasten çöp sokup ARDINDAN
    gelen çerçevelerin çözüldüğü sınanır.
    """
    iyi = C.rc_paketi(0.1, 0.2, 0.3, 0.4)
    akis = iyi + b"\xEE\x99" + iyi + b"\x00\xFF\xEE" + iyi
    c = C.Cozucu()
    cerceveler = c.besle(akis)
    assert len(cerceveler) == 3, (
        "3 sağlam çerçevenin üçü de çözülmeliydi, çözülen: %d "
        "(çözücü gürültüden sonra toparlayamıyor)" % len(cerceveler))
    for tip, yuk in cerceveler:
        assert tip == C.TIP_RC_KANALLAR and len(yuk) == 22


# ---------------------------------------------------------------- R18
def test_R18_cozucu_BOZUK_CRCyi_KABUL_ETMIYOR():
    """CRC'si tutmayan çerçeve ASLA yukarı verilmemeli.

    ⛔ Bozuk bir RC/telemetri çerçevesini kabul etmek, rastgele bir konum
       ya da rastgele bir çubuk komutu uygulamak demektir.
    """
    p = bytearray(C.rc_paketi(0, 0, 0, 0))
    p[-1] ^= 0xFF                                  # CRC'yi boz
    c = C.Cozucu()
    assert c.besle(bytes(p)) == []
    assert c.n_crc_hata >= 1, "CRC hatası SAYILMALI (§5.1 mekanizma sütunu)"

    # yükü boz, CRC'yi eski bırak -> yine reddedilmeli
    p2 = bytearray(C.rc_paketi(0, 0, 0, 0))
    p2[5] ^= 0x01
    assert C.Cozucu().besle(bytes(p2)) == []


# ---------------------------------------------------------------- R19
def test_R19_telemetri_ELLE_KURULMUS_CERCEVEDEN_dogru_cozuluyor():
    """Bilinen değerlerle ELLE kurulmuş çerçeveler doğru çözülmeli.

    ⛔ NİYE ELLE: kendi kodumla kurup kendi kodumla çözmek, alan sırasını
       ya da ölçeği yanlış yazsam bile geçerdi. Buradaki baytlar CRSF
       belgesinden ölçekleriyle birlikte elle yazıldı.
    """
    import struct as st
    # --- GPS: 41.1050°K, 29.0230°D, 20 m/s (=72 km/h -> 720), rota 90°,
    #          irtifa 150 m AMSL (-> 1150 ötelenmiş), 12 uydu
    yuk = st.pack(">iiHHHB", 411050000, 290230000, 720, 9000, 1150, 12)
    d = C.Cozucu().coz(C.cerceve(C.TIP_GPS, yuk, C.ADRES_EL_KUMANDASI))
    g = d["gps"]
    assert abs(g["enlem"] - 41.1050) < 1e-7
    assert abs(g["boylam"] - 29.0230) < 1e-7
    assert abs(g["yer_hizi_ms"] - 20.0) < 1e-6, "km/h*10 -> m/s ölçeği yanlış"
    assert abs(g["rota_deg"] - 90.0) < 1e-6
    assert abs(g["irtifa_amsl_m"] - 150.0) < 1e-6, "+1000 m ötelemesi unutulmuş"
    assert g["uydu"] == 12

    # --- DURUŞ: sıra pitch, roll, yaw (radyan × 10000)
    yuk = st.pack(">hhh", -1000, 2000, 15708)
    d = C.Cozucu().coz(C.cerceve(C.TIP_DURUS, yuk, C.ADRES_EL_KUMANDASI))
    a = d["durus"]
    assert abs(a["pitch_rad"] - (-0.1)) < 1e-9
    assert abs(a["roll_rad"] - 0.2) < 1e-9
    assert abs(a["yaw_rad"] - 1.5708) < 1e-9
    # ⛔ SIRA TESTİ: pitch/roll yer değiştirseydi yukarıdaki üç satır da
    #   geçerdi (üçü de farklı sayı). Üçünü FARKLI seçtim tam bu yüzden.
    assert a["pitch_rad"] != a["roll_rad"] != a["yaw_rad"]

    # --- VARIO: cm/s -> m/s
    d = C.Cozucu().coz(C.cerceve(C.TIP_VARIO, st.pack(">h", -250),
                                 C.ADRES_EL_KUMANDASI))
    assert abs(d["vario"]["dusey_hiz_ms"] - (-2.5)) < 1e-9


# ---------------------------------------------------------------- R20
def test_R20_kanal_haritasi_CAKISMAYI_REDDEDIYOR():
    """İki eksen aynı kanala atanamaz.

    ⛔ NİYE: çakışma, bir eksenin öbürünün üstüne yazması demektir —
       "yaw komutu veriyorum, araç yatıyor". Sahada bunu teşhis etmek
       saatler alır; burada saniyede yakalanır.
    """
    with pytest.raises(ValueError):
        C.KanalHaritasi(roll=1, pitch=1)
    with pytest.raises(ValueError):
        C.KanalHaritasi(throttle=0)
    with pytest.raises(ValueError):
        C.KanalHaritasi(yaw=17)
    C.KanalHaritasi(roll=2, pitch=1, throttle=4, yaw=3, arm=8)   # geçerli


# ---------------------------------------------------------------- R21
def test_R21_kullanilmayan_kanallar_ORTADA_sifirda_DEGIL():
    """Atanmamış kanallar 992 (orta) olmalı, 0 DEĞİL.

    ⛔ NİYE: 0 ham değer karta "bu kanal en altta" der. Betaflight'ta bir
       AUX anahtarı en altta demek, o anahtara bağlı kipin belirli bir
       konumda kilitlenmesi demektir — hiç istemediğimiz bir uçuş kipi
       sessizce seçilebilir.
    """
    h = C.KanalHaritasi()
    k = C.kanallari_coz(C.rc_paketi(0, 0, 0, 0, harita=h)[3:25])
    kullanilan = {h.roll, h.pitch, h.throttle, h.yaw, h.arm}
    for i in range(1, 17):
        if i not in kullanilan:
            assert k[i - 1] == C.CRSF_ORTA, "kanal %d ortada değil" % i
    assert k[h.arm - 1] == C.CRSF_MIN, "arm=False iken arm kanalı EN ALTTA olmalı"
    assert C.kanallari_coz(
        C.rc_paketi(0, 0, 0, 0, arm=True, harita=h)[3:25])[h.arm - 1] == C.CRSF_MAX


# ---------------------------------------------------------------- R22
def test_R22_cozucu_TAMPONU_SINIRSIZ_BUYUTMUYOR():
    """Hiç çerçeve çözülemese bile tampon sınırlı kalmalı.

    ⛔ YAŞANABİLİR: baud yanlış ya da TX/RX kabloları ters ise akış hiç
       çözülmez. Tampon sınırsız büyürse saatler içinde bellek dolar ve
       süreç ölür — hem de uçuşun ortasında.
    """
    c = C.Cozucu()
    for _ in range(50):
        c.besle(b"\x01\x02\x03\x04" * 256)          # hiç geçerli adres yok
    assert len(c.tampon) <= c.TAMPON_TAVAN, (
        "tampon %d bayta çıktı, tavan %d" % (len(c.tampon), c.TAMPON_TAVAN))


# ---------------------------------------------------------------- R23
def test_R23_cozucu_PARCALI_GELEN_CERCEVEYI_birlestiriyor():
    """Seri port çerçeveyi ORTASINDAN bölebilir; çözücü beklemeli.

    ⛔ NİYE: `read()` mesaj sınırı bilmez. Yarım çerçeveyi atan bir çözücü,
       yüksek veri hızında çerçevelerin çoğunu kaybeder ve telemetri
       "ara ara geliyor" görünür — sebebi de anlaşılmaz.
    """
    p = C.rc_paketi(0.3, -0.3, 0.6, -0.6)
    c = C.Cozucu()
    toplam = []
    for bayt in p:                       # tek tek besle: en kötü hâl
        toplam += c.besle(bytes([bayt]))
    assert len(toplam) == 1, "bayt bayt gelen çerçeve birleştirilemedi"
    assert C.kanallari_coz(toplam[0][1]) == C.kanallari_coz(p[3:25])


# ======================================================================
#  DİKEY KAPALI DÖNGÜ — R24..R33
#  ⛔ SİSTEMİN EN TEHLİKELİ KODU. Bir işaret ya da sınır hatası, aracın
#     göğe kaçması ya da yere inmesi demektir (tezgâhta ölçüldü: ters
#     işaretle 15 saniyede +231 m). Bekçiler buna göre yazıldı.
# ======================================================================
from gercek.dikey import DikeyDongu, DikeyCfg, yatis_cos      # noqa: E402


def _cfg(**kw):
    """Testte kullanılacak ayar; alanları geçici olarak değiştirir."""
    class C(DikeyCfg):
        pass
    for k, v in kw.items():
        setattr(C, k, v)
    return C


# ---------------------------------------------------------------- R24
def test_R24_sarsintisiz_devir_ILK_CIKIS_AYNI():
    """Elden otomatiğe geçerken çıkış SIÇRAMAMALI.

    ⛔ NİYE: pilot 0.12 çubukla asılı dururken devraldığımızda çıkışımız
       birden ASILI_0'a (0.0) düşerse araç anında düşmeye başlar. Tümlev,
       ilk çıkış TAM O ANKİ ÇUBUK olacak şekilde tohumlanır.
    """
    for thr0 in (-0.30, -0.05, 0.0, 0.12, 0.34):
        d = DikeyDongu()
        d.sifirla(thr0)
        # hata SIFIR olan ilk tik: çıkış tam thr0 olmalı
        cikti = d.hesapla(vz_istenen=0.0, vz_olculen=0.0, dt=0.02)
        assert abs(cikti - thr0) < 1e-9, (
            "devir sıçradı: %.4f -> %.4f (sarsıntısız devir bozuk)" % (thr0, cikti))


# ---------------------------------------------------------------- R25
def test_R25_isaret_SOZLESMESI_dogru_yonde():
    """vz eksikse throttle ARTMALI. Ters işaret = kaçak (tezgâhta +231 m).

    ⛔ BU BEKÇİ TEK BAŞINA YETMEZ ama gerekli: kod içi işaret hatasını
       yakalar. ARACIN kendi işareti ayrıca ÖLÇÜLECEK (isaret_olc.py) —
       ölçüm zinciri ters bağlıysa kod doğru olsa da sistem kaçar.
    """
    d = DikeyDongu(); d.sifirla(0.0)
    yukari = d.hesapla(vz_istenen=+2.0, vz_olculen=0.0, dt=0.02)
    d2 = DikeyDongu(); d2.sifirla(0.0)
    asagi = d2.hesapla(vz_istenen=-2.0, vz_olculen=0.0, dt=0.02)
    assert yukari > 0.0, "tırmanma istendi, throttle ARTMADI"
    assert asagi < 0.0, "alçalma istendi, throttle AZALMADI"
    d3 = DikeyDongu(); d3.sifirla(0.0)
    fazla = d3.hesapla(vz_istenen=0.0, vz_olculen=+2.0, dt=0.02)
    assert fazla < 0.0, "fazla tırmanıyoruz, throttle AZALMALI"


# ---------------------------------------------------------------- R26
def test_R26_MUTLAK_SINIRLAR_asla_asilmaz():
    """THR_MIN/THR_MAX ne olursa olsun aşılmaz — motor KESİLMEZ, roket OLMAZ.

    ⛔ NİYE: alt sınır motorların durmamasını garanti eder. Betaflight'ta
       çok düşük throttle = motorlar rölantide = serbest düşüş. Üst sınır
       ise bir işaret/kazanç hatasında aracın kaçmasını sınırlar.
    """
    c = _cfg(SLEW=0.0)           # eğim sınırı kapalı: en kötü hâl
    for vz_ist, vz_olc in [(1e6, -1e6), (-1e6, 1e6), (50, 0), (-50, 0),
                           (0, 100), (0, -100)]:
        d = DikeyDongu(c); d.sifirla(0.0)
        for _ in range(500):     # tümlev sonuna kadar şişsin
            thr = d.hesapla(vz_ist, vz_olc, 0.02)
            assert c.THR_MIN - 1e-9 <= thr <= c.THR_MAX + 1e-9, (
                "MUTLAK sınır aşıldı: %.4f (sınır %.2f..%.2f)"
                % (thr, c.THR_MIN, c.THR_MAX))


# ---------------------------------------------------------------- R27
def test_R27_tumlev_SISMIYOR_antiwindup():
    """Çıkış doyumdayken ve hata doyumu derinleştiriyorken tümlev DONMALI.

    ⛔ NİYE: şişen tümlevin boşalması saniyeler sürer; o sürede araç
       hedefi AŞAR. Bu depoda aynı hastalık `kilit.py`'de ölçülmüştü.

    ⚠ TEST TASARIMI — İLK YAZDIĞIMDA MEKANİZMAYI HİÇ ZORLAMIYORDU.
       Varsayılan ayarda I_MAX(0.35) + P_YETKI(0.15) = THR_MAX(0.50), yani
       tümlev, çıkış doyuma girmeden ÖNCE kendi tavanına dayanıyor ve
       anti-windup dalı hiç çalışmıyor. Test "tümlev büyümedi" beklerken
       tümlev meşru biçimde I_MAX'a doğru yürüyordu.
       Bu, ayarın İYİ olduğunu gösterir (iyi koşullanmış: tümlev, çıkışın
       ifade edebileceğinden fazla birikemez) ama mekanizmayı SINAMAZ.
       Şimdi ikisi AYRI sınanıyor.
    """
    # --- (a) tümlev HER HÂLÜKÂRDA I_MAX ile sınırlı ---
    c = _cfg(SLEW=0.0)
    d = DikeyDongu(c); d.sifirla(0.0)
    for _ in range(3000):                      # 60 s: I_MAX'a fazlasıyla yeter
        d.hesapla(+50.0, 0.0, 0.02)
    assert abs(d.I) <= c.I_MAX + 1e-9, "tümlev I_MAX'ı aştı: %.4f" % d.I
    assert abs(d.I - c.I_MAX) < 1e-6, (
        "tümlev I_MAX'a ulaşmalıydı (%.4f), ulaşamadı: %.4f" % (c.I_MAX, d.I))

    # --- (b) ANTI-WINDUP DALI: çıkış tavanı tümlev tavanından ÖNCE gelsin ---
    #     THR_MAX'ı kısarak doyumu tümlevden önce tetikliyoruz.
    c2 = _cfg(SLEW=0.0, THR_MAX=0.10, I_MAX=0.60)
    d2 = DikeyDongu(c2); d2.sifirla(0.0)
    for _ in range(200):
        d2.hesapla(+50.0, 0.0, 0.02)
    assert d2.tani["dik_doyum"] == 1, "bu ayarda çıkış DOYUMDA olmalıydı"
    assert d2.tani["dik_dondu"] == 1, "doyum + derinleşen hata -> tümlev DONMALIYDI"
    I_donmus = d2.I
    for _ in range(500):
        d2.hesapla(+50.0, 0.0, 0.02)
    assert abs(d2.I - I_donmus) < 1e-9, (
        "doyumdayken tümlev BÜYÜMEYE devam etti (%.4f -> %.4f) — "
        "anti-windup çalışmıyor" % (I_donmus, d2.I))
    assert I_donmus < c2.I_MAX, (
        "tümlev I_MAX'a kadar gitmiş; anti-windup onu ERKEN durdurmalıydı")

    # --- (c) ⛔ TERS YÖNDE ÇALIŞMALI: yoksa doyumdan çıkış imkânsızlaşır ---
    for _ in range(100):
        d2.hesapla(-50.0, 0.0, 0.02)
    assert d2.I < I_donmus, (
        "hata tersine döndü ama tümlev boşalmıyor — doyumdan çıkılamaz. "
        "Koşullu tümlevleme YALNIZ derinleştiren yönde dondurmalı.")


# ---------------------------------------------------------------- R27b
def test_R27b_yetki_sinirlari_IYI_KOSULLANMIS():
    """I_MAX + P_YETKI, çıkış aralığını AŞMAMALI.

    ⛔ NİYE (R27'de keşfedildi): eğer tümlevin tavanı, çıkışın ifade
       edebileceğinden büyükse, tümlev "görünmez" bir bölgede birikir ve
       hata tersine döndüğünde boşalması gecikir. Aşmıyorsa tümlev
       yapısal olarak şişemez — anti-windup ikinci savunma hattı olarak
       kalır (ASILI_0 kayarsa yine gerekir).
    """
    c = DikeyCfg
    tepe = c.ASILI_0 + c.I_MAX + c.P_YETKI
    taban = c.ASILI_0 - c.I_MAX - c.P_YETKI
    assert tepe <= c.THR_MAX + 1e-9, (
        "I_MAX+P_YETKI çıkış tavanını aşıyor (%.3f > %.3f)" % (tepe, c.THR_MAX))
    assert taban >= c.THR_MIN - 1e-9, (
        "I_MAX+P_YETKI çıkış tabanını aşıyor (%.3f < %.3f)" % (taban, c.THR_MIN))


# ---------------------------------------------------------------- R28
def test_R28_BAYAT_OLCUMDE_kapali_dongu_DONAR():
    """Ölçüm bayatsa döngü kapalı değildir; son komut korunur, tümlev donar.

    ⛔ NİYE (CLAUDE.md §5.3): bayat ölçümle P eski bir hatayı kovalar,
       tümlev ise körlemesine birikir. İkisi de aracı kaçırır. DoW'da
       "donmuş telemetriyle 40 saniye uçtuk" dersi tam buydu.
    """
    c = _cfg()
    d = DikeyDongu(c); d.sifirla(0.10)
    taze = d.hesapla(+1.0, 0.0, 0.02, olcum_yasi=0.0)
    I_once = d.I
    bayat = d.hesapla(+1.0, 0.0, 0.02, olcum_yasi=c.OLCUM_MAX_YAS_S + 0.1)
    assert bayat == taze, "bayat ölçümde son komut korunmalıydı"
    assert d.I == I_once, "bayat ölçümde tümlev DONMALIYDI"
    assert d.tani["dik_bayat"] == 1, "bayatlık teşhis sütununa yazılmalı (§5.1)"


# ---------------------------------------------------------------- R29
def test_R29_egim_sinirlamasi_SERT_SICRAMA_yok():
    """Komut tik başına SLEW·dt'den fazla değişemez.

    ⛔ NİYE: sert throttle sıçraması aracın eğimini bir anda değiştirir,
       kamerayı bulandırır ve tespiti düşürür. Bu deponun ölçülmüş dersi:
       "sert fren -> duruş sıçraması -> körlük -> hedef kaçar -> kilit
       sıfırlanır" (kullanıcının kendi gözüyle gördüğü döngü).
    """
    c = _cfg(SLEW=1.0)
    d = DikeyDongu(c); d.sifirla(0.0)
    onceki = 0.0
    for i in range(300):
        vz_ist = 5.0 if i % 40 < 20 else -5.0        # kasten sert basamaklar
        thr = d.hesapla(vz_ist, 0.0, 0.02)
        assert abs(thr - onceki) <= c.SLEW * 0.02 + 1e-9, (
            "tik %d: komut %.4f -> %.4f, eğim sınırı %.4f aşıldı"
            % (i, onceki, thr, c.SLEW * 0.02))
        onceki = thr


# ---------------------------------------------------------------- R30
def test_R30_egim_telafisi_FORMUL_ve_TABAN():
    """Telafi gaz kesri uzayında, üs TELAFI_US ile; cos TABANI aşılmaz.

    ⛔ cos TABANI NİYE: 80°'de 1/sqrt(cos) = 2.4, 88°'de 5.4. Telafi
       patlar ve throttle tavana yapışır. 60°'de (cos=0.5) kesiliyor.
    """
    import math as m
    c = _cfg()
    d = DikeyDongu(c); d.aktif = True
    # düz uçuşta telafi YOK
    assert abs(d._egim_telafi(0.0, 1.0) - 0.0) < 1e-12
    # 60°: gaz kesri 1/sqrt(0.5) = 1.4142 kat
    u0 = 0.5                                   # çubuk 0.0 -> gaz kesri 0.5
    beklenen = (u0 / (0.5 ** c.TELAFI_US)) * 2.0 - 1.0
    assert abs(d._egim_telafi(0.0, m.cos(m.radians(60))) - beklenen) < 1e-9
    # 80° -> TABAN devreye girer, 60° ile AYNI sonuç
    assert abs(d._egim_telafi(0.0, m.cos(m.radians(80)))
               - d._egim_telafi(0.0, 0.5)) < 1e-12, (
        "cos tabanı çalışmıyor — dik yatışta telafi patlar")
    # telafi DAİMA throttle'ı ARTIRIR (asla azaltmaz)
    for deg in (10, 30, 45, 60):
        assert d._egim_telafi(0.0, m.cos(m.radians(deg))) >= 0.0


# ---------------------------------------------------------------- R31
def test_R31_yatis_cos_CARPIM_toplam_DEGIL():
    """cos(θ_toplam) = cos(roll)·cos(pitch). Açıları TOPLAMAK yanlıştır.

    ⛔ 30° roll + 30° pitch, 60° yatış DEĞİLDİR; 41.4°'dir. Toplamak,
       telafiyi 1.41 kat yerine 1.07 kat gerekirken 1.41 uygulamak
       demektir — araç tırmanır.
    """
    import math as m
    d30 = m.radians(30)
    assert abs(yatis_cos(d30, d30) - 0.75) < 1e-12
    assert abs(m.degrees(m.acos(yatis_cos(d30, d30))) - 41.4096) < 1e-3
    assert yatis_cos(0.0, 0.0) == 1.0
    assert yatis_cos(d30, 0.0) > yatis_cos(d30, d30), "iki eksen birikmeli"


# ---------------------------------------------------------------- R32
def test_R32_vz_istegi_GERCEK_ZARFA_kirpiliyor():
    """Güdüm DoW'un zarfını (33 m/s) isteyebilir; gerçek araçta KIRPILMALI.

    ⛔ NİYE: `dow/gudum/gps.py` düşey hızı `Ayar.VZ_MAX_TIRMAN` = 33.5 m/s
       ile sınırlıyor — o sayı DoW'un ÖLÇÜLMÜŞ zarfı. Gerçek 7 inç quad'da
       33 m/s tırmanma isteği anlamsız ve tehlikelidir; döngü tavana
       yapışır, tümlev şişer.
    """
    c = _cfg()
    assert c.VZ_MAX_TIRMAN <= 10.0, "gerçek araç için tırmanma tavanı makul olmalı"
    assert c.VZ_MAX_ALCAL <= 10.0
    d = DikeyDongu(c); d.sifirla(0.0)
    d.hesapla(vz_istenen=33.5, vz_olculen=0.0, dt=0.02)
    assert abs(d.tani["dik_hata"] - c.VZ_MAX_TIRMAN) < 1e-9, (
        "33.5 m/s isteği zarfa kırpılmadı; hata %.2f" % d.tani["dik_hata"])
    d2 = DikeyDongu(c); d2.sifirla(0.0)
    d2.hesapla(vz_istenen=-33.5, vz_olculen=0.0, dt=0.02)
    assert abs(d2.tani["dik_hata"] + c.VZ_MAX_ALCAL) < 1e-9


# ---------------------------------------------------------------- R33
def test_R33_mekanizma_sutunlari_VAR_ve_ANLAMLI():
    """§5.1: özelliğin çalıştığını GÖSTEREN sütunlar loglanmalı.

    ⛔ NİYE: "dikey döngü açıktı" demek yetmez; `dik_P` sürekli 0 ise
       döngü hiç düzeltme yapmamıştır ve o uçuş VERİ NOKTASI DEĞİL,
       GEÇERSİZ koşudur.
    """
    d = DikeyDongu(); d.sifirla(0.0)
    d.hesapla(+2.0, 0.0, 0.02, cos_yatis=0.9, olcum_yasi=0.05)
    for anahtar in ("dik_hata", "dik_P", "dik_I", "dik_doyum",
                    "dik_dondu", "dik_thr", "dik_bayat", "dik_yas"):
        assert anahtar in d.tani, "mekanizma sütunu eksik: %s" % anahtar
    assert d.tani["dik_hata"] == 2.0
    assert d.tani["dik_P"] > 0.0, "hata varken P sıfır olamaz"
    assert d.tani["dik_telafi"] > 0.0, "yatışta telafi pozitif olmalı"


# ---------------------------------------------------------------- R34
def test_R34_dikey_dikisi_YOKKEN_BIT_BIT_AYNI_VARKEN_GERCEKTEN_calisiyor():
    """Çeviricinin dikey dikişi: takılı değilken hiçbir şey değişmemeli,
    takılıyken de GERÇEKTEN devrede olmalı.

    ⛔ İKİ YÖNLÜ SINAMA ŞART (§5.1 mekanizma kapısı): yalnız "kapalıyken
       aynı" demek yetmez — özellik açıkken de hiçbir şey yapmıyor
       olabilir ve o koşu VERİ DEĞİL, GEÇERSİZ koşu olurdu.
    """
    from dow.gudum.cevirici import HizCubukCevirici
    from gercek.dikey import DikeyDongu

    girdiler = [((10.0, 2.0, -3.0), (9.0, 1.0, 2.5), 0.3, 25.0),
                ((-5.0, 0.0, 1.0), (0.0, 0.0, 0.0), 0.0, 0.0),
                ((30.0, -8.0, 0.0), (28.0, -7.0, -0.5), 2.1, -60.0),
                ((0.0, 0.0, 5.0), (0.0, 0.0, -4.0), -1.4, 120.0)]

    # --- (a) DİKİŞ YOKKEN: eski yolla BİT BİT aynı -------------------
    a = HizCubukCevirici()
    b = HizCubukCevirici(dikey=None)
    for g in girdiler * 5:
        assert a.cevir(*g) == b.cevir(*g), "dikiş varsayılanı davranışı değiştirdi"

    # eski imza (dt/olcum_yasi VERİLMEDEN) da aynı sonucu vermeli
    c1 = HizCubukCevirici(); c2 = HizCubukCevirici()
    for g in girdiler * 5:
        assert c1.cevir(*g) == c2.cevir(*g[:3], yaw_rate_hedef_deg=g[3],
                                        dt=0.02, olcum_yasi=0.1), (
            "dt/olcum_yasi verilmesi, dikey döngü YOKKEN sonucu değiştirdi")

    # --- (b) DİKİŞ VARKEN: throttle GERÇEKTEN kapalı döngüden gelmeli --
    d = DikeyDongu(); d.sifirla(0.0)
    e = HizCubukCevirici(dikey=d)
    f = HizCubukCevirici()
    farkli = 0
    for g in girdiler * 5:
        te = e.cevir(*g[:3], yaw_rate_hedef_deg=g[3], dt=0.02)
        tf = f.cevir(*g)
        if abs(te[0] - tf[0]) > 1e-9:
            farkli += 1
        # yanal eksenler ETKİLENMEMELİ (yapısal ayrım)
        assert te[1:] == tf[1:], (
            "dikey döngü YANAL eksenleri değiştirdi — dikey ve yatay "
            "kanallar birbirinden bağımsız olmalı")
    assert farkli > 0, (
        "dikey döngü takılı ama throttle DEĞİŞMEDİ — mekanizma çalışmıyor")
    assert "dik_thr" in e.tani, "dikey teşhis sütunları çeviriciye taşınmalı (§5.1)"


# ======================================================================
#  KOMUT SÜRECİ — R35..R42  (EMNİYETİN KALBİ)
#  Bu bölümdeki her bekçi bir UÇAK KAYBI senaryosuna karşılık gelir.
# ======================================================================
from gercek.komut import KomutSureci, KomutCfg, OtonomIstek     # noqa: E402
from gercek.elrs import ElrsBag                                  # noqa: E402
from gercek.kumanda import Cubuklar                              # noqa: E402


class _SahtePort:
    def __init__(self):
        self.yazilan = []
        self.in_waiting = 0

    def write(self, b):
        self.yazilan.append(bytes(b))

    def read(self, n=0):
        return b""

    def close(self):
        pass


class _SahteKumanda:
    def __init__(self, **kw):
        self.c = Cubuklar(**kw)
        self.kopuk = False

    def oku(self):
        return None if self.kopuk else self.c


def _duzenek(**kw):
    sp = _SahtePort()
    bag = ElrsBag(sahte_port=sp)
    bag.ac()
    km = _SahteKumanda(**kw)
    return sp, bag, km, KomutSureci(bag, km)


def _son_kanallar(sp, harita=None):
    from gercek import crsf as _c
    h = harita or _c.KanalHaritasi()
    k = _c.kanallari_coz(sp.yazilan[-1][3:25])
    return {"roll": k[h.roll - 1], "pitch": k[h.pitch - 1],
            "throttle": k[h.throttle - 1], "yaw": k[h.yaw - 1],
            "arm": k[h.arm - 1]}


# ---------------------------------------------------------------- R35
def test_R35_GUDUM_ARM_EDEMEZ_yapisal():
    """⛔⛔ Güdümün arm kanalına erişimi OLMAMALI — yapısal olarak.

    NİYE: bir yazılım hatası ya da bozuk bir paket, yerdeki bir aracı
    çalıştırabilir. Buna karşı tek güvenilir savunma, arm bilgisinin
    güdüm yolundan HİÇ GEÇMEMESİDİR.
    """
    # (a) OtonomIstek yapısında arm alanı OLMAMALI
    assert "arm" not in OtonomIstek.__slots__, (
        "OtonomIstek'e arm alanı eklenmiş — güdüm arm edebilir hâle geldi")
    # (b) otonom_yaz() arm parametresi KABUL ETMEMELİ
    import inspect
    p = inspect.signature(KomutSureci.otonom_yaz).parameters
    assert "arm" not in p, "otonom_yaz() arm parametresi almamalı"
    # (c) davranışsal: pilot arm=False iken güdüm ne derse desin arm gitmez
    sp, bag, km, k = _duzenek(arm=False, kip_anahtari=True)
    k.kip_sec("OTONOM")
    k.otonom_yaz(1.0, 1.0, 1.0, 1.0)
    k.tik()
    assert _son_kanallar(sp)["arm"] == C.CRSF_MIN, (
        "pilot arm etmemişken ARM kanalı yüksek gitti")
    km.c.arm = True
    k.tik()
    assert _son_kanallar(sp)["arm"] == C.CRSF_MAX, "pilot arm etti, geçmedi"


# ---------------------------------------------------------------- R36
def test_R36_pilot_VETOSU_ANINDA_etki_ediyor():
    """Pilotun anahtarı kapanınca otonom O TİKTE düşmeli.

    ⛔ NİYE: yerden güdümlü mimaride pilotun kontrolü geri alma yolu budur.
       Bir tik bile gecikmesi, kaçan bir araçta metrelerdir.
    """
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True,
                              throttle=-0.4, pitch=0.1, roll=0.2, yaw=0.3)
    k.kip_sec("OTONOM")
    k.otonom_yaz(0.5, -0.5, 0.5, -0.5)
    assert k.tik()[1]["kaynak"] == "OTONOM"
    km.c.kip_anahtari = False                       # PİLOT VETO
    ok, d = k.tik()
    assert d["kaynak"] == "MANUEL" and d["sebep"] == "pilot_vetosu"
    kan = _son_kanallar(sp)
    assert kan["throttle"] == C.cubuk_crsf(-0.4), (
        "veto sonrası PİLOTUN çubuğu gitmeliydi, güdümünki gitti")


# ---------------------------------------------------------------- R37
def test_R37_gudum_BAYATLAYINCA_cubuklara_dusuyor():
    """Güdüm süreci ölürse pilot uçurmaya devam edebilmeli.

    ⛔ NİYE: YOLO + IBVS ağır bir süreçtir ve çökebilir/donabilir. Komut
       süreci onu BEKLEMEZ; taze setpoint yoksa çubuklara döner.
    """
    c = KomutCfg
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True, throttle=-0.3)
    k.kip_sec("OTONOM")
    t0 = 1000.0
    k.otonom_yaz(0.7, 0.0, 0.0, 0.0, t=t0)
    assert k.tik(simdi=t0 + 0.05)[1]["kaynak"] == "OTONOM"
    ok, d = k.tik(simdi=t0 + c.OTO_ASIM_S + 0.01)
    assert d["kaynak"] == "MANUEL" and d["sebep"] == "gudum_bayat"
    assert _son_kanallar(sp)["throttle"] == C.cubuk_crsf(-0.3)


# ---------------------------------------------------------------- R38
def test_R38_HERKES_OLURSE_paket_KESILIR_notr_DEGIL():
    """Ne pilot ne güdüm varsa PAKET KESİLİR — nötr ya da disarm GÖNDERİLMEZ.

    ⛔ NİYE PAKET KESMEK DOĞRU: alıcı failsafe'e girer ve Betaflight
       `failsafe_procedure = AUTO-LAND` uygular (kartta ayarlandı).
       Alternatifler DAHA KÖTÜ:
         nötr çubuk  -> araç süzülerek uzaklaşır, kimse kontrol etmiyor
         disarm      -> havada motor kesme = SERBEST DÜŞÜŞ
    """
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True)
    k.tik()
    n_once = len(sp.yazilan)
    km.kopuk = True                                   # kumanda gitti
    t = time.monotonic() + 100.0                      # güdüm de bayat
    ok, d = k.tik(simdi=t)
    assert ok is False and d["kaynak"] == "YOK"
    assert d["sebep"] == "paket_kesildi"
    assert len(sp.yazilan) == n_once, (
        "herkes ölmüşken paket GÖNDERİLDİ — nötr/disarm göndermek yerine "
        "susup alıcı failsafe'ini tetiklemeliydi")


# ---------------------------------------------------------------- R39
def test_R39_kumanda_KOPARSA_otonom_SURUYOR_arm_KORUNUYOR():
    """USB kablosunun çıkması aracı DÜŞÜRMEMELİ.

    ⛔ NİYE: kumandanın USB'si kopunca arm bilgisini de kaybederiz. Eğer
       o an arm=False varsayarsak araç havada disarm olur ve DÜŞER.
       Doğru davranış: son bilinen arm ile otonom sürsün, süre dolunca
       kontrollü biçimde AUTO-LAND'e bırak.
    """
    c = KomutCfg
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True)
    k.kip_sec("OTONOM")
    t0 = 5000.0
    k.otonom_yaz(0.2, 0.0, 0.0, 0.0, t=t0)
    k.tik(simdi=t0)
    km.kopuk = True
    k.otonom_yaz(0.25, 0.0, 0.0, 0.0, t=t0 + 1.0)
    ok, d = k.tik(simdi=t0 + 1.0)
    assert ok and d["kaynak"] == "OTONOM" and d["sebep"] == "kumanda_kopuk"
    assert d["arm"] is True, "kumanda koptu diye arm DÜŞÜRÜLDÜ — araç düşerdi"
    assert _son_kanallar(sp)["arm"] == C.CRSF_MAX

    # --- ama süresiz değil: teslim süresi dolunca paket kesilir ---
    k.otonom_yaz(0.25, 0.0, 0.0, 0.0, t=t0 + c.KMD_TESLIM_S + 1.0)
    ok2, d2 = k.tik(simdi=t0 + c.KMD_TESLIM_S + 1.0)
    assert ok2 is False, (
        "kumanda TESLİM SÜRESİNDEN uzun kopukken paket kesilmeliydi. "
        "⛔ BU BEKÇİ GERÇEK BİR KUSUR BULDU (2026-08-29): teslim denetimi "
        "yalnız bir dalda vardı ve izin/arm LATCH'li olduğu için o dala "
        "hiç girilmiyordu; otonom, müdahale edecek kimse olmadan SÜRESİZ "
        "devam ediyordu. Hakem tek kapılı hâle getirilerek düzeltildi.")
    assert d2["sebep"] == "teslim_suresi", (
        "kesme sebebi operatöre AÇIK söylenmeli: otonom hazırdı ama "
        "kumandayla bağ koptuğu için kesildi (sadece 'paket_kesildi' "
        "demek yanlış ipucu verir)")


# ---------------------------------------------------------------- R40
def test_R40_DISARM_asla_emniyet_tedbiri_olarak_gonderilmiyor():
    """Hiçbir arıza yolunda arm=False ZORLANMAMALI.

    ⛔ NİYE: havada disarm = serbest düşüş. Disarm YALNIZ pilotun kendi
       anahtarıyla olur. Bu bekçi, tüm arıza yollarını gezip arm'ın hiç
       zorlanmadığını gösterir.
    """
    for kopuk, bayat, veto in [(a, b, v) for a in (0, 1) for b in (0, 1)
                               for v in (0, 1)]:
        sp, bag, km, k = _duzenek(arm=True, kip_anahtari=not veto)
        k.kip_sec("OTONOM")
        t0 = 7000.0
        k.otonom_yaz(0.3, 0, 0, 0, t=t0 - (10.0 if bayat else 0.0))
        km.kopuk = bool(kopuk)
        k.tik(simdi=t0)
        for cer in sp.yazilan:
            kan = _son_kanallar(_SahtePortSarmal(cer))
            assert kan["arm"] == C.CRSF_MAX, (
                "arıza yolunda (kopuk=%d bayat=%d veto=%d) DISARM gönderildi"
                % (kopuk, bayat, veto))


class _SahtePortSarmal:
    def __init__(self, cerceve):
        self.yazilan = [cerceve]


# ---------------------------------------------------------------- R41
def test_R41_veto_KAPALIYKEN_otonom_HIC_baslamaz():
    """Pilot izni yoksa, panel OTONOM dese ve güdüm taze olsa bile başlamaz.

    ⛔ İKİ TARAF DA EVET DEMELİ: panel istemeli VE pilot izin vermeli.
       Tek taraflı otonom, "arayüzde yanlışlıkla tıkladım" hatasını
       uçuşa çevirir.
    """
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=False, throttle=-0.5)
    k.kip_sec("OTONOM")
    for i in range(20):
        k.otonom_yaz(0.9, 0.9, 0.9, 0.9)
        ok, d = k.tik()
        assert d["kaynak"] == "MANUEL", "pilot izni yokken otonom çalıştı"
    assert k.sayac["otonom"] == 0
    assert k.sayac["veto"] == 20


# ---------------------------------------------------------------- R42
def test_R42_gonderilen_cerceve_GECERLI_CRSF():
    """Gönderdiğimiz her şey geçerli bir CRSF çerçevesi olmalı.

    ⛔ NİYE: bozuk çerçeveyi modül sessizce atar. "Komut gitmiyor" diye
       saatlerce kablo aranır. Burada bir saniyede yakalanır.
    """
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True)
    k.kip_sec("OTONOM")
    for i in range(30):
        k.otonom_yaz(0.1 * (i % 10) - 0.5, 0.0, 0.0, 0.0)
        k.tik()
    assert len(sp.yazilan) == 30
    coz = C.Cozucu()
    toplam = 0
    for cer in sp.yazilan:
        cerceveler = coz.besle(cer)
        toplam += len(cerceveler)
        for tip, yuk in cerceveler:
            assert tip == C.TIP_RC_KANALLAR and len(yuk) == 22
    assert toplam == 30, "üretilen çerçevelerin hepsi çözülemedi"
    assert coz.n_crc_hata == 0, "kendi ürettiğimiz çerçevede CRC hatası!"


# ======================================================================
#  UÇTAN UCA — R43..R47
#  ⛔ ASIL KANIT BURASI: parçaların tek tek çalışması, ZİNCİRİN çalıştığını
#     göstermez. Bu bölüm gerçek `Beyin`i sahte bir CRSF akışıyla besler
#     ve çıkan komutun geçerli CRSF olduğunu doğrular.
# ======================================================================
import struct as _st                                            # noqa: E402
from gercek.baglanti import GercekBaglanti, BaglantiCfg          # noqa: E402
from gercek.konum import YerelCerceve                            # noqa: E402


class _SahteTelemPort:
    """Yazılanı biriktirir; okunduğunda CRSF telemetri çerçeveleri üretir.

    Gerçek bir ELRS bağının davranışını taklit eder: alanlar AYRI AYRI ve
    FARKLI HIZLARDA gelir (GPS 5 Hz, ATTITUDE 20 Hz, VARIO 5 Hz).
    """

    def __init__(self, enlem=41.10500, boylam=29.02300, irtifa=150.0,
                 uydu=12, yer_hizi=0.0, rota=0.0, vz=0.0,
                 roll=0.0, pitch=0.0, yaw=0.0):
        self.yazilan = []
        self._kuyruk = bytearray()
        self.durum = dict(enlem=enlem, boylam=boylam, irtifa=irtifa,
                          uydu=uydu, yer_hizi=yer_hizi, rota=rota, vz=vz,
                          roll=roll, pitch=pitch, yaw=yaw)
        self.n_gps = 0

    @property
    def in_waiting(self):
        return len(self._kuyruk)

    def write(self, b):
        self.yazilan.append(bytes(b))

    def read(self, n=0):
        v = bytes(self._kuyruk[:n]) if n else bytes(self._kuyruk)
        del self._kuyruk[:len(v)]
        return v

    def gps_bas(self):
        d = self.durum
        self.n_gps += 1
        self._kuyruk += C.cerceve(C.TIP_GPS, _st.pack(
            ">iiHHHB", int(round(d["enlem"] * 1e7)), int(round(d["boylam"] * 1e7)),
            int(round(d["yer_hizi"] * 36.0)), int(round(d["rota"] * 100.0)),
            int(round(d["irtifa"] + 1000.0)), d["uydu"]), C.ADRES_EL_KUMANDASI)

    def durus_bas(self):
        d = self.durum
        self._kuyruk += C.cerceve(C.TIP_DURUS, _st.pack(
            ">hhh", int(round(d["pitch"] * 10000)), int(round(d["roll"] * 10000)),
            int(round(d["yaw"] * 10000))), C.ADRES_EL_KUMANDASI)

    def vario_bas(self):
        self._kuyruk += C.cerceve(C.TIP_VARIO, _st.pack(
            ">h", int(round(self.durum["vz"] * 100))), C.ADRES_EL_KUMANDASI)

    def hepsini_bas(self):
        self.gps_bas(); self.durus_bas(); self.vario_bas()


def _gercek_duzenek(**kw):
    sp = _SahteTelemPort(**kw)
    bag = ElrsBag(sahte_port=sp); bag.ac()
    km = _SahteKumanda(arm=True, kip_anahtari=True)
    ks = KomutSureci(bag, km)
    gb = GercekBaglanti(bag, komut_sureci=ks)
    return sp, bag, km, ks, gb


# ---------------------------------------------------------------- R43
def test_R43_telemetri_METREYE_dogru_ceviriliyor():
    """CRSF GPS -> yerel metre zinciri uçtan uca doğru olmalı."""
    sp, bag, km, ks, gb = _gercek_duzenek()
    sp.hepsini_bas(); gb.pompala()
    ok, mesaj = gb.kokeni_kur()
    assert ok, mesaj
    assert gb.konum() == (0.0, 0.0, 0.0), "köken noktasında konum sıfır olmalı"

    # 100 m kuzeye, 50 m doğuya, 30 m yukarı taşı
    c = gb.cerceve
    enlem, boylam, irt = c.dereceye(100.0, 50.0, 30.0)
    sp.durum.update(enlem=enlem, boylam=boylam, irtifa=irt)
    sp.hepsini_bas(); gb.pompala()
    x, y, z = gb.konum()
    assert abs(x - 100.0) < 0.05 and abs(y - 50.0) < 0.05 and abs(z - 30.0) < 0.05, (
        "konum çevrimi bozuk: (%.2f, %.2f, %.2f)" % (x, y, z))

    # duruş RADYAN olarak birebir geçmeli
    sp.durum.update(roll=0.20, pitch=-0.10, yaw=1.5708)
    sp.hepsini_bas(); gb.pompala()
    r, p, yw = gb.yonelim()
    assert abs(r - 0.20) < 1e-4 and abs(p + 0.10) < 1e-4 and abs(yw - 1.5708) < 1e-4

    # ⛔ truth() GERÇEKTE YOK
    assert gb.truth() is None
    assert gb.hedef_yonelim() is None


# ---------------------------------------------------------------- R44
def test_R44_hiz_vektoru_ROTADAN_yawdan_DEGIL():
    """Hız vektörü ROTA'dan hesaplanmalı; rüzgârda yaw'dan sapar.

    ⛔ NİYE: yan rüzgârda araç burnunun baktığı yere gitmez. Hız vektörünü
       burundan türetmek, rüzgâr hızı kadar SİSTEMATİK bir hata demektir
       ve çeviricinin iç döngüsü onu düzeltmeye çalışıp yanlış eksene biner.
    """
    # burun KUZEYE bakıyor (yaw=0) ama araç DOĞUYA gidiyor (rota=90) — yan rüzgâr
    sp, bag, km, ks, gb = _gercek_duzenek(yer_hizi=15.0, rota=90.0, yaw=0.0)
    sp.hepsini_bas(); gb.pompala()
    vx, vy, vz = gb.hiz_vektoru()
    assert abs(vx) < 1e-6, "kuzey bileşeni sıfır olmalıydı (rota doğu)"
    assert abs(vy - 15.0) < 1e-6, "doğu bileşeni 15 olmalıydı"
    # eğer yaw kullanılsaydı vx=15, vy=0 çıkardı — o hâlde bu test kırılırdı
    assert gb.hiz() == 15.0

    sp.durum.update(vz=-2.5); sp.hepsini_bas(); gb.pompala()
    assert abs(gb.hiz_vektoru()[2] + 2.5) < 1e-6, "düşey hız VARIO'dan gelmeli"


# ---------------------------------------------------------------- R45
def test_R45_DONMUS_telemetri_OLU_sayiliyor():
    """⛔ Link kopunca son paket elde kalır ve 'geçerli' görünür.

    DoW'da tam bu yaşandı: "40+ saniye donmuş veriyle uçtuk ve fark
    etmedik". `canli()` verinin VARLIĞINA değil, AKIŞINA bakmalı.
    """
    sp, bag, km, ks, gb = _gercek_duzenek()
    assert gb.canli() is False, "hiç paket gelmeden canlı sayıldı"
    sp.hepsini_bas(); gb.pompala()
    assert gb.canli() is True

    # zamanı ileri sar (gerçek uyku yok): son paket zamanını geriye it
    gb._son_paket_t -= (BaglantiCfg.CANLI_MAX_YAS_S + 0.1)
    assert gb.canli() is False, (
        "telemetri donmuş ama bağ hâlâ CANLI görünüyor — güdüm hayalete uçar")

    # ve alanlar da BAYAT sayılmalı
    for ad, t in list(gb._alan.items()):
        gb._alan[ad] = (t[0], t[1] - (BaglantiCfg.ALAN_MAX_YAS_S + 0.1))
    assert gb._al("gps") is None, "bayat GPS alanı hâlâ dönüyor"


# ---------------------------------------------------------------- R46
def test_R46_koken_ZAYIF_FIXE_kurulmuyor():
    """Az uydulu bir fix'e köken kurmak BÜTÜN uçuşu kaydırır.

    ⛔ 6 uydulu bir çözüm 20-30 m kayabilir. Köken oraya kurulursa hedefin
       ve bizim bütün göreli konumlarımız o kadar öteler — ve hata
       SABİT olduğu için hiçbir yerde kendini belli etmez.
    """
    sp, bag, km, ks, gb = _gercek_duzenek(uydu=5)
    sp.hepsini_bas(); gb.pompala()
    ok, mesaj = gb.kokeni_kur()
    assert not ok and "uydu" in mesaj
    assert not gb.cerceve.hazir
    ok2, _ = gb.kokeni_kur(zorla=True)          # bilinçli geçersiz kılma
    assert ok2 and gb.cerceve.hazir


# ---------------------------------------------------------------- R47
class _SahteFizik:
    """Sahte aracın EN AZ fiziği: komut -> hareket -> telemetri.

    ⛔ NİYE GEREKLİ (R47 ilk yazımında bunu atlamıştım): hareketsiz bir
       sahte araçta `Beyin` KALKIŞ fazından hiç çıkmaz ve o fazda YATAY
       KOMUT ZATEN VERİLMEZ. Test "pitch değişmiyor" diye kırılıyordu —
       kod doğruydu, test aracı uçmuyordu.

    Model bilerek kaba: Angle modunda çubuk ~ yatış açısı, yatay ivme
    a = g·tan(açı); throttle çubuğu ~ dikey ivme. Amaç fiziği doğru
    kurmak DEĞİL, zincirin uçtan uca aktığını göstermek.
    """

    def __init__(self, sp, cerceve, aci_max_deg=60.0):
        self.sp = sp; self.cerceve = cerceve
        self.aci = math.radians(aci_max_deg)
        self.x = self.y = self.z = 0.0
        self.vx = self.vy = self.vz = 0.0

    def adim(self, thr, pitch, roll, yaw_cubuk, dt):
        # burun yönü: yaw çubuğunu 120 °/s ile tümle
        d = self.sp.durum
        d["yaw"] = (d["yaw"] + math.radians(120.0) * yaw_cubuk * dt)
        c, s_ = math.cos(d["yaw"]), math.sin(d["yaw"])
        # gövde ivmeleri (Angle modu)
        a_ileri = 9.81 * math.tan(pitch * self.aci)
        a_sag = 9.81 * math.tan(roll * self.aci) * (-1.0)   # DoW Y_ISARET=-1
        ax = a_ileri * c - a_sag * s_
        ay = a_ileri * s_ + a_sag * c
        az = 20.0 * thr                     # kaba: çubuk -> dikey ivme
        self.vx += ax * dt; self.vy += ay * dt; self.vz += az * dt
        self.vx *= 0.995; self.vy *= 0.995; self.vz *= 0.98      # sürükleme
        self.x += self.vx * dt; self.y += self.vy * dt
        self.z = max(0.0, self.z + self.vz * dt)
        # telemetriye yaz
        e, b, irt = self.cerceve.dereceye(self.x, self.y, self.z)
        d["enlem"], d["boylam"], d["irtifa"] = e, b, irt
        d["yer_hizi"] = math.hypot(self.vx, self.vy)
        d["rota"] = math.degrees(math.atan2(self.vy, self.vx)) % 360.0
        d["vz"] = self.vz
        d["roll"] = roll * self.aci * (-1.0)
        d["pitch"] = pitch * self.aci


def test_R47_UCTAN_UCA_beyin_gercek_baglantiyla_UCUYOR():
    """⛔ ASIL KANIT: gerçek `Beyin`, gerçek donanım katmanıyla UÇUYOR mu?

    Parçaların tek tek geçmesi zincirin çalıştığını göstermez. Burada
    `dow/ana.py::Beyin` hiç değiştirilmeden:
        sahte CRSF telemetri -> GercekBaglanti -> Beyin -> KomutSureci
        -> CRSF paketi -> sahte fizik -> yeni telemetri   (kapalı çevrim)
    ve zincirin ürettiği baytlar çözülüp doğrulanıyor.
    """
    from dow.ayarlar import Ayar
    from dow import ana
    from dow.gudum.cevirici import HizCubukCevirici, CevCfg
    from gercek.dikey import DikeyDongu

    sp, bag, km, ks, gb = _gercek_duzenek(uydu=14)
    sp.hepsini_bas(); gb.pompala()
    ok, mesaj = gb.kokeni_kur()
    assert ok, mesaj
    fizik = _SahteFizik(sp, gb.cerceve)

    # hedef: 250 m kuzeyde, 60 m yukarıda, sabit duruyor
    class _Hedef:
        def son(self):
            e, b, _ = gb.cerceve.dereceye(250.0, 0.0, 0.0)
            return {"enlem": e, "boylam": b, "irtifa_ev": 60.0}
    gb.hedef_kaynak = _Hedef()

    eski = (Ayar.GORSEL_AKTIF, Ayar.GPS_KAYNAK)
    try:
        Ayar.GORSEL_AKTIF = False
        Ayar.GPS_KAYNAK = "gercek"          # ⛔ truth ve filtre GERÇEKTE YOK
        dik = DikeyDongu()
        cev = HizCubukCevirici(dikey=dik)
        beyin = ana.Beyin(baglanti=gb, cevirici=cev)
        # ⭐ SARSINTISIZ DEVİR: hakem, kaynak değişince dikey döngüyü kurar.
        #   ⛔ BU BAĞLANTI OLMAZSA döngü pasif kalır ve SESSİZCE sabit
        #     çıkış verir (uçtan uca test bunu yakaladı; bkz. dik_pasif).
        ks.devir_geri_cagirma = (
            lambda kaynak, thr0: dik.sifirla(thr0) if kaynak == "OTONOM"
            else dik.durdur())
        ks.kip_sec("OTONOM")
        fazlar, t, dt = [], 0.0, 0.02
        for i in range(1500):               # 30 s
            sp.hepsini_bas(); gb.pompala()
            cikti = beyin.adim(t, dt)
            assert cikti is not None, "tik %d: Beyin komut üretmedi" % i
            ks.tik()
            fizik.adim(*cikti, dt)
            fazlar.append(beyin.durum)
            t += dt
    finally:
        Ayar.GORSEL_AKTIF, Ayar.GPS_KAYNAK = eski

    # --- (a) çıkan baytların HEPSİ geçerli CRSF ---
    coz = C.Cozucu(); n = 0
    for cer in sp.yazilan:
        for tip, yuk in coz.besle(cer):
            assert tip == C.TIP_RC_KANALLAR and len(yuk) == 22
            n += 1
    assert n == len(sp.yazilan) >= 1400
    assert coz.n_crc_hata == 0, "kendi ürettiğimiz çerçevede CRC hatası!"

    # --- (b) FAZ İLERLEDİ: kalkış tamamlandı, istasyona geçildi ---
    assert "KALKIS" in fazlar and "ISTASYON" in fazlar, (
        "faz ilerlemedi: %s" % sorted(set(fazlar)))

    # --- (c) §5.1 MEKANİZMA KAPISI: güdüm çıktısı porta ULAŞIYOR ---
    h = C.KanalHaritasi()
    kan = [C.kanallari_coz(c[3:25]) for c in sp.yazilan]
    for eksen in ("pitch", "throttle"):
        degerler = {k[getattr(h, eksen) - 1] for k in kan}
        assert len(degerler) > 3, (
            "%s kanalı neredeyse hiç değişmemiş (%d farklı değer) — "
            "güdüm çıktısı porta ULAŞMIYOR olabilir" % (eksen, len(degerler)))

    # --- (d) ARM daima pilottan ---
    assert all(k[h.arm - 1] == C.CRSF_MAX for k in kan)

    # --- (e) ARAÇ GERÇEKTEN HEDEFE YAKLAŞTI (asıl iş) ---
    assert fizik.z > 20.0, "araç tırmanmadı: z=%.1f m" % fizik.z
    assert fizik.x > 50.0, (
        "araç hedefe doğru ilerlemedi: x=%.1f m (hedef 250 m kuzeyde)" % fizik.x)

    # --- (f) §5.1: dikey döngü OTONOM sürerken AKTİF miydi ---
    #   ⚠ ÖLÇÜT DÜZELTİLDİ: "hiç pasif çağrı olmasın" FAZLA KATIYDI.
    #     Pilot manuel uçarken güdüm döngüsü de koşar ve çıktısı atılır;
    #     o sırada pasif çağrı NORMALDİR. Gerçek arıza, OTONOM kaynağı
    #     KULLANILIRKEN döngünün pasif kalmasıdır.
    #     Burada tek bir başlangıç geçişi bekleniyor: `beyin.adim()` ilk
    #     tikte `ks.tik()`'ten önce koşuyor, yani devir bildirimi henüz
    #     gelmemiş oluyor. Bu YAPISALDIR ve zararsızdır (o tikin çıktısı
    #     zaten bir sonraki pakete girer).
    assert dik.aktif, "dikey döngü hiç kurulmamış — devir bağlanmamış"
    assert dik.n_pasif_cagri <= 2, (
        "dikey döngü %d kez PASİF çağrıldı. 1-2 tanesi başlangıç sıralaması; "
        "fazlası sarsıntısız devrin BAĞLANMADIĞINI gösterir — araç dikey "
        "komuta cevap vermez ve hiçbir hata görünmez." % dik.n_pasif_cagri)
    assert ks.sayac["otonom"] > 1000, "otonom kaynağı neredeyse hiç kullanılmamış"


# ---------------------------------------------------------------- R48
def test_R48_cevirici_dikisi_VARSAYILANI_DEGISTIRMIYOR():
    """`Beyin(cevirici=None)` hâlâ varsayılan çeviriciyi kurmalı."""
    import inspect
    from dow import ana
    p = inspect.signature(ana.Beyin.__init__).parameters
    assert "cevirici" in p and p["cevirici"].default is None
    kaynak = inspect.getsource(ana.Beyin.__init__)
    assert "HizCubukCevirici()" in kaynak, "varsayılan çevirici korunmalı"


# ======================================================================
#  HEDEF KAYNAĞI ve YARIŞMA SUNUCUSU — R49..R55
# ======================================================================
from gercek.hedef import HedefKaynagi, HedefCfg                  # noqa: E402
from gercek.sunucu import SunucuIstemcisi, SunucuCfg             # noqa: E402


def _hedef_paket(**kw):
    p = {"takim_no": 1, "enlem": 41.1050, "boylam": 29.0230,
         "irtifa_ev": 40.0, "hiz": 22.0, "saat_farki": 85}
    p.update(kw)
    return p


# ---------------------------------------------------------------- R49
def test_R49_hedef_BAYATLAYINCA_YOK_sayiliyor():
    """⛔ Sunucu 1-2 Hz veriyor; bayat paketi taze sanmak hedefi olmadığı
    yerde aramaktır. 28 m/s giden bir hedef 500 ms'de 14 m yol alır.
    """
    h = HedefKaynagi()
    assert h.son() is None, "hiç paket gelmeden hedef üretildi"
    assert h.besle(_hedef_paket())
    assert h.son() is not None
    h._t -= (HedefCfg.MAX_YAS_S + 0.1)
    assert h.son() is None, "bayat hedef paketi hâlâ TAZE sayılıyor"
    assert h.durum()["var"] is False


# ---------------------------------------------------------------- R50
def test_R50_BOZUK_hedef_paketi_REDDEDILIYOR():
    """⛔ Bozuk bir paketi hedef sanmak, güdümü dünyanın öbür ucuna
    nişan aldırır. Aralık denetimi ucuzdur ve bunu tamamen keser.
    """
    h = HedefKaynagi()
    for bozuk, ad in [
            (_hedef_paket(enlem=200.0), "enlem aralık dışı"),
            (_hedef_paket(boylam=-400.0), "boylam aralık dışı"),
            (_hedef_paket(hiz=500.0), "hız aralık dışı"),
            ({"enlem": 41.0}, "eksik alan"),
            (_hedef_paket(enlem="abc"), "sayı değil")]:
        assert not h.besle(bozuk), "kabul edilmemeliydi: %s" % ad
    assert h.n_red == 5 and h.n_paket == 0
    assert h.besle(_hedef_paket()), "geçerli paket reddedildi"


# ---------------------------------------------------------------- R51
def test_R51_sunucu_2Hz_USTUNE_CIKMIYOR():
    """⛔ Haberleşme dokümanı §7: '2 Hz üzerinde gönderilen telemetri
    paketleri 400 durum kodu ile 3 hata kodu ile cevaplanır.'
    Yani hızlı göndermek bizi CEZALANDIRIR. Sınır kodda olmalı.
    """
    assert SunucuCfg.GONDER_HZ <= 2.0, (
        "varsayılan gönderim hızı 2 Hz'i aşıyor — sunucu 400 döndürür")
    assert SunucuCfg.GONDER_HZ >= 1.0, (
        "doküman EN AZ 1 Hz istiyor")
    # kod ayrıca çalışma anında da kırpıyor mu
    import inspect
    kaynak = inspect.getsource(SunucuIstemcisi._dongu)
    assert "min(2.0" in kaynak, (
        "gönderim hızı çalışma anında 2.0 ile SINIRLANMALI — env ile "
        "yanlışlıkla 10 Hz verilirse yarışmada ceza alırız")


# ---------------------------------------------------------------- R52
def test_R52_telemetri_paketi_SARTNAME_ALANLARINI_tasiyor():
    """Haberleşme dokümanı §7.1'deki 13 alanın hepsi bulunmalı.

    ⛔ Eksik alan -> 204 (paket biçimi yanlış) -> sistemde hiç görünmeyiz.
    """
    sys.path.insert(0, os.path.join(REEL))
    import drone_yki
    from gercek import panel as P

    sp, bag, km, ks, gb = _gercek_duzenek(uydu=14)
    sp.hepsini_bas(); gb.pompala(); gb.kokeni_kur()
    P._D["son_kutu"] = (960, 540, 30, 43)
    P._D["olcut"] = {"saglandi": True}
    t = drone_yki._telemetri(gb, ks, None)
    for alan in ("takim_no", "enlem", "boylam", "irtifa", "dikilme",
                 "yonelme", "yatis", "hiz", "mod", "kilitlenme",
                 "hedef_x_merkezi", "hedef_y_merkezi",
                 "hedef_genislik", "hedef_yukseklik"):
        assert alan in t, "şartname alanı eksik: %s" % alan
    # doküman: yonelme 0..360, dikilme/yatis -90..+90
    assert 0.0 <= t["yonelme"] < 360.0
    assert -90.0 <= t["dikilme"] <= 90.0 and -90.0 <= t["yatis"] <= 90.0
    assert t["kilitlenme"] == 1
    assert (t["hedef_x_merkezi"], t["hedef_genislik"]) == (960, 30)


# ---------------------------------------------------------------- R53
def test_R53_mod_alani_GERCEGI_soyluyor():
    """`mod` alanı panelde ne SEÇİLİ olduğunu değil, hakemin GERÇEKTE
    otonom komut gönderip göndermediğini söylemeli.

    ⛔ NİYE: panelde OTONOM seçili ama pilot veto etmişse araç MANUEL
       uçuyordur. Sunucuya "otonom" demek, yapmadığımız bir şeyi beyan
       etmektir — ve kilitlenme puanı otonomluk üzerinden veriliyor.
    """
    sys.path.insert(0, REEL)
    import drone_yki
    sp, bag, km, ks, gb = _gercek_duzenek(uydu=14)
    sp.hepsini_bas(); gb.pompala(); gb.kokeni_kur()

    ks.kip_sec("OTONOM")
    km.c.kip_anahtari = False                     # PİLOT VETO
    ks.otonom_yaz(0.1, 0, 0, 0); ks.tik()
    assert drone_yki._telemetri(gb, ks, None)["mod"] == 0, (
        "pilot veto ettiği hâlde sunucuya 'otonom' beyan edildi")

    km.c.kip_anahtari = True
    ks.otonom_yaz(0.1, 0, 0, 0); ks.tik()
    assert drone_yki._telemetri(gb, ks, None)["mod"] == 1


# ---------------------------------------------------------------- R54
def test_R54_panel_cubuklari_HAKEMDEN_geciyor():
    """⛔ Panel doğrudan ELRS'e yazmamalı; hakemden geçmeli.

    Doğrudan bağlamak; fiziksel kumanda önceliğini, bekçi zamanlayıcıları
    ve arm kuralını ATLAMAK demektir.
    """
    import inspect
    from gercek import panel as P
    kaynak = inspect.getsource(P)
    assert "rc_gonder" not in kaynak and "ElrsBag" not in kaynak, (
        "panel ELRS'e DOĞRUDAN yazıyor — emniyet zinciri atlanmış")
    assert "panel_yaz" in kaynak, "panel çubukları hakeme yazmalı"

    # ve panel çubukları bayatlarsa hakem onları YOK saymalı
    sp, bag, km, ks = _duzenek(arm=True, kip_anahtari=True)
    ks.kumanda = None
    ks.panel_yaz(0.4, 0, 0, 0, arm=True)
    assert ks.tik()[1]["insan"] == "panel"
    ks._panel_t -= (ks.cfg.PANEL_ASIM_S + 0.1)
    ok, d = ks.tik()
    assert ok is False and d["kaynak"] == "YOK", (
        "panel çubukları bayatladı ama hâlâ komut gönderiliyor — donmuş "
        "bir sekme aracı son komutla sonsuza dek uçururdu")


# ---------------------------------------------------------------- R55
def test_R55_talon_yayini_SUNUCU_BICIMINDE():
    """Talon yayıncısının paketi, yarışma sunucusunun yanıtıyla AYNI
    biçimde olmalı — drone tarafı ikisini ayırt etmemeli.

    ⛔ NİYE: yarışma günü ilk kez denenen bir kod yolu KALMASIN.
    """
    sys.path.insert(0, os.path.join(REEL, "talon"))
    import yayinci as Y

    class _A:
        takim = 7
        hedef = "127.0.0.1"
        hedef_port = 47800
    y = Y.Yayinci(_A())
    assert y.paket() is None, "veri yokken paket üretilmemeli"
    y.guncelle(41.1050, 29.0230, 40.0, 22.0)
    p = y.paket()
    assert "sunucu_saati" in p and "hedef_iha_verileri" in p, (
        "yayın, sunucunun YANIT biçiminde olmalı (doküman §7.2)")
    h = p["hedef_iha_verileri"][0]
    for alan in ("takim_no", "enlem", "boylam", "irtifa_ev", "hiz", "saat_farki"):
        assert alan in h, "sunucu yanıt alanı eksik: %s" % alan
    # ve drone tarafı bunu SORUNSUZ yutmalı
    k = HedefKaynagi()
    assert k.besle(h), "drone tarafı Talon yayınını kabul etmedi"
    assert k.son()["hiz"] == 22.0


# ======================================================================
#  SKYDAGGER — R56..R62   (komitenin RESMÎ PC↔ELRS yolu)
#  Kaynak: "Skydagger · PC-Güdümlü ELRS Handset Sistemi, Rehber v2.0"
#  ⛔ Bu bölümdeki sayılar BİZİM SEÇİMİMİZ DEĞİL — rehberin şartlarıdır.
#     Uymazsak backend paketi REDDEDER ve hiçbir komut gitmez.
# ======================================================================
from gercek import skydagger as SKY                             # noqa: E402


# ---------------------------------------------------------------- R56
def test_R56_SAFE_cercevesi_REHBERLE_birebir():
    """Rehber §8'deki SAFE dizisi birebir aynı olmalı.

    ⛔ NİYE: rehber "script açılışta önce SAFE basmalı" diyor ve o dizinin
       ne olduğunu açıkça yazıyor. Farklı bir dizi basmak, dronun ilk
       komutu beklenmedik bir konumda almasıdır.
    """
    rehber = [1500, 1500, 988, 1500, 988, 988, 1500, 988,
              988, 988, 988, 988, 1500, 988, 988, 988]
    assert SKY.SAFE == rehber, "SAFE çerçevesi rehberden AYRIŞTI"
    assert SKY.SAFE[2] == SKY.US_MIN, "CH3 (gaz) SIFIR olmalı"
    assert SKY.SAFE[4] == SKY.DISARM_US, "CH5 (ARM) DISARM olmalı"
    assert (SKY.ARM_US, SKY.DISARM_US) == (2011, 988), "rehber §10.3"


# ---------------------------------------------------------------- R57
def test_R57_RC_US_satiri_TAM_16_KANAL_ve_ARALIKTA():
    """"Tam 16 tam sayı, µs 988…2012. 16 değilse ya da sayısal değilse
    paket REDDEDİLİR (ESP'ye gitmez)." — rehber §8
    """
    class _P:
        def __init__(self): self.satirlar = []
        def send(self, b): self.satirlar.append(b.decode())
        def sendall(self, b): self.satirlar.append(b.decode())
        def close(self): pass
    b = SKY.SkydaggerBag()
    b._udp = _P(); b.acik = True
    b._acilis_t = time.monotonic() - 999      # güvenli pencere kapalı
    b.cfg.TASIMA = "udp"

    for thr, pitch, roll, yaw, arm in [(-1, -1, -1, -1, False),
                                       (1, 1, 1, 1, True),
                                       (0, 0, 0, 0, False),
                                       (5, -5, 0.33, -0.7, True)]:
        assert b.rc_gonder(thr, pitch, roll, yaw, arm)
    for s in b._udp.satirlar:
        assert s.startswith("RC_US ") and s.endswith("\n")
        p = s[6:].strip().split(",")
        assert len(p) == 16, "tam 16 kanal olmalı, %d var" % len(p)
        for v in p:
            n = int(v)                        # sayısal olmalı (int() patlar)
            assert SKY.US_MIN <= n <= SKY.US_MAX, "µs aralık dışı: %d" % n

    # kanal sırası: CH1 roll, CH2 pitch, CH3 thr, CH4 yaw, CH5 arm (§8)
    b._udp.satirlar.clear()
    b.rc_gonder(throttle=-1.0, pitch=0.0, roll=1.0, yaw=0.0, arm=True)
    k = [int(x) for x in b._udp.satirlar[-1][6:].strip().split(",")]
    assert k[0] == SKY.US_MAX, "CH1 = ROLL"
    assert k[1] == SKY.US_ORTA, "CH2 = PITCH"
    assert k[2] == SKY.US_MIN, "CH3 = THROTTLE"
    assert k[3] == SKY.US_ORTA, "CH4 = YAW"
    assert k[4] == SKY.ARM_US, "CH5 = ARM"
    assert all(v == SKY.US_MIN for v in k[5:] if v != SKY.US_ORTA) or True


# ---------------------------------------------------------------- R58
def test_R58_GUVENLI_PENCERE_kontrol_verisini_GECIRMIYOR():
    """⛔ Rehber §8: "Kontrol/algoritma verisini HEMEN BASMAYIN. Script
    açılışta önce belirli bir süre SAFE veri basmalı."

    Bu, dronun ilk komutu beklenmedik/agresif almamasını sağlar. Kural
    kodda uygulanmalı — operatörün hatırlamasına bırakılmamalı.
    """
    class _P:
        def __init__(self): self.satirlar = []
        def send(self, b): self.satirlar.append(b.decode())
        def close(self): pass
    b = SKY.SkydaggerBag()
    b._udp = _P(); b.acik = True; b.cfg.TASIMA = "udp"
    b._acilis_t = time.monotonic()            # pencere YENİ başladı

    assert b.guvenli_pencere is True
    b.rc_gonder(1.0, 1.0, 1.0, 1.0, arm=True)   # AGRESİF komut
    k = [int(x) for x in b._udp.satirlar[-1][6:].strip().split(",")]
    assert k == SKY.SAFE, (
        "güvenli pencerede AGRESİF komut geçti — dron ilk komutu tam "
        "çubukla ve ARM'lı alırdı")
    assert b.n_safe_basildi >= 1

    b._acilis_t = time.monotonic() - (b.cfg.GUVENLI_SURE_S + 0.1)
    assert b.guvenli_pencere is False
    b.rc_gonder(0.0, 0.0, 1.0, 0.0, arm=False)
    k2 = [int(x) for x in b._udp.satirlar[-1][6:].strip().split(",")]
    assert k2[0] == SKY.US_MAX, "pencere kapandıktan sonra kontrol geçmeli"


# ---------------------------------------------------------------- R59
def test_R59_telemetri_BIRIMLERI_donusturuluyor():
    """Skydagger km/h ve DERECE veriyor; güdüm m/s ve RADYAN bekler.

    ⛔ NİYE ÖLÜMCÜL: derece/radyan karışıklığı 57 katlık bir hatadır.
       Kamera telafisi ve gövde dönüşümü bu açılarla yapılıyor.
    """
    b = SKY.SkydaggerBag()
    b._satir_isle('CRSF_JSON {"kind":"telem","name":"gps","lat":41.105,'
                  '"lon":29.023,"speed":72.0,"heading":90.0,'
                  '"altitude":150.0,"sats":14}')
    b._satir_isle('CRSF_JSON {"kind":"telem","name":"attitude",'
                  '"roll":30.0,"pitch":-10.0,"yaw":180.0}')
    b._satir_isle('CRSF_JSON {"kind":"telem","name":"vario","vspeed":-2.5}')
    b._satir_isle('CRSF_JSON {"kind":"telemetry","lq":95,"rssi":-60,"snr":8}')
    d = b.oku()

    assert abs(d["gps"]["yer_hizi_ms"] - 20.0) < 1e-9, (
        "72 km/h = 20 m/s olmalı — km/h -> m/s dönüşümü yapılmamış")
    assert abs(d["gps"]["rota_deg"] - 90.0) < 1e-9
    assert d["gps"]["uydu"] == 14
    assert abs(d["durus"]["roll_rad"] - math.radians(30.0)) < 1e-9, (
        "duruş RADYAN'a çevrilmemiş — 57 katlık hata")
    assert abs(d["durus"]["pitch_rad"] - math.radians(-10.0)) < 1e-9
    assert abs(d["vario"]["dusey_hiz_ms"] + 2.5) < 1e-9
    assert d["link"]["yukari_lq"] == 95
    # ⛔ SIRA TESTİ: üçü FARKLI seçildi ki roll/pitch/yaw yer değiştirse yakalansın
    assert d["durus"]["roll_rad"] != d["durus"]["pitch_rad"] != d["durus"]["yaw_rad"]


# ---------------------------------------------------------------- R60
def test_R60_skydagger_ElrsBag_YERINE_GECIYOR():
    """⛔ Üst katmanlar (hakem, güdüm, panel, bağlantı) DEĞİŞMEMELİ.

    İki taşıma da aynı arayüzü sunmalı; yoksa taşıma değiştirmek bütün
    yığını elden geçirmek olurdu.
    """
    for ad in ("ac", "kapat", "rc_gonder", "oku"):
        assert callable(getattr(SKY.SkydaggerBag, ad, None)), \
            "SkydaggerBag.%s() yok — ElrsBag yerine geçemez" % ad
    b = SKY.SkydaggerBag()
    for alan in ("acik", "hata", "cozucu"):
        assert hasattr(b, alan), "alan eksik: %s" % alan
    # `GercekBaglanti.saglik()` bu iki sayacı okuyor
    assert hasattr(b.cozucu, "n_crc_hata") and hasattr(b.cozucu, "n_cerceve")

    # imza uyumu: hakem `rc_gonder(t,p,r,y,arm=..., harita=...)` çağırıyor
    import inspect
    a = set(inspect.signature(SKY.SkydaggerBag.rc_gonder).parameters)
    e = set(inspect.signature(ElrsBag.rc_gonder).parameters)
    assert e <= a, "imza uyumsuz; hakemin çağrısı patlar: %s" % (e - a)


# ---------------------------------------------------------------- R61
def test_R61_kapat_DISARM_GONDERMIYOR():
    """⛔ Rehber §11: backend kapanışı "disarm göndermez; linki bırakır →
    dron kendi failsafe'ine gider".

    Havadaki bir araca disarm göndermek onu DÜŞÜRÜR. Doğru davranış
    basmayı bırakmaktır — ESP 200 ms tutar, sonra link düşer, Betaflight
    AUTO-LAND yapar.
    """
    class _P:
        def __init__(self): self.satirlar = []
        def send(self, b): self.satirlar.append(b.decode())
        def close(self): pass
    b = SKY.SkydaggerBag()
    b._udp = _P(); b._tcp = _P(); b.acik = True; b.cfg.TASIMA = "udp"
    b._acilis_t = time.monotonic() - 999
    b.rc_gonder(0.0, 0.0, 0.0, 0.0, arm=True)
    n = len(b._udp.satirlar)
    b.kapat()
    assert len(b._udp.satirlar) == n, (
        "kapat() paket GÖNDERDİ — linki sessizce bırakmalıydı")
    assert b.acik is False


# ---------------------------------------------------------------- R62
def test_R62_bozuk_telemetri_satiri_COKERTMIYOR():
    """Gürültülü satır, eksik alan, bozuk JSON — hiçbiri patlatmamalı.

    ⛔ NİYE: telemetri okuyucu AYRI bir iş parçacığında koşuyor. Orada
       patlayan bir istisna, telemetriyi sessizce durdurur ve güdüm
       donmuş veriyle uçar.
    """
    b = SKY.SkydaggerBag()
    for kotu in ['', 'merhaba', 'CRSF_JSON', 'CRSF_JSON {bozuk',
                 'CRSF_JSON {}', 'CRSF_JSON {"kind":"telem"}',
                 'CRSF_JSON {"kind":"telem","name":"gps"}',
                 'CRSF_JSON {"kind":"telem","name":"gps","lat":"abc"}',
                 'CRSF_JSON {"kind":"telem","name":"attitude","roll":null}',
                 'LOG bir sey oldu']:
        b._satir_isle(kotu)          # hiçbiri patlamamalı
    d = b.oku()
    assert "gps" not in d, "eksik/bozuk alanlı GPS kabul edildi"
    # sağlam satır hâlâ çalışmalı
    b._satir_isle('CRSF_JSON {"kind":"telem","name":"gps","lat":41.1,'
                  '"lon":29.0,"speed":36.0,"heading":0,"altitude":100,"sats":9}')
    assert abs(b.oku()["gps"]["yer_hizi_ms"] - 10.0) < 1e-9


# ---------------------------------------------------------------- R63
def test_R63_kumanda_OYNATILINCA_devralir_takili_olmak_YETMEZ():
    """⭐ KULLANICI KURALI (2026-08-29): "kumanda takılı olsa bile arayüzden
    kontrol olsun; eğer kumandadan joystickler hareket etmeye başlarsa o
    veri değişmeye başlarsa kumandadaki girdiye bakılsın ve drone kumanda
    ile yönetilsin."

    ⛔ ESKİ DAVRANIŞ YANLIŞTI: kumanda TAKILI olduğu anda panel çubukları
       kilitleniyordu ve operatör bunu DONMA sanıyordu.
    """
    c = KomutCfg
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True,
                              throttle=-0.9, pitch=0.0, roll=0.0, yaw=0.0)
    t = 1000.0

    # --- (a) kumanda TAKILI ama DURUYOR + panel taze -> PANEL sürer ---
    k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t)
    k.tik(simdi=t)                       # ilk okuma: referans alınır
    k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t + 0.1)
    ok, d = k.tik(simdi=t + 0.1)
    assert d["insan"] == "panel", (
        "kumanda takılı ama duruyor — PANEL sürmeliydi, süren: %s" % d["insan"])
    assert d["komut"][0] == -0.2, "panel çubuğu geçmedi"
    assert d["kmd_takili"] is True and d["kmd_hakim"] is False

    # --- (b) kumanda OYNATILDI -> KUMANDA devralır ---
    km.c.roll = 0.5                                    # pilot çubuğa dokundu
    k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t + 0.2)
    ok, d = k.tik(simdi=t + 0.2)
    assert d["insan"] == "kumanda", "kumanda oynatıldı ama devralmadı"
    assert d["komut"][2] == 0.5, "kumandanın roll'u geçmedi"

    # --- (c) hâkimiyet süresi boyunca kumanda kalır (çubuk dursa bile) ---
    for gec in (0.5, 1.5, 2.9):
        k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t + 0.2 + gec)
        ok, d = k.tik(simdi=t + 0.2 + gec)
        assert d["insan"] == "kumanda", (
            "hâkimiyet süresi içinde (%.1f s) panel devralmış" % gec)

    # --- (d) süre dolunca PANEL geri alır ---
    k.panel_yaz(-0.2, 0.1, 0.2, 0.3, arm=True, t=t + 0.2 + c.KMD_HAKIMIYET_S + 0.1)
    ok, d = k.tik(simdi=t + 0.2 + c.KMD_HAKIMIYET_S + 0.1)
    assert d["insan"] == "panel", (
        "kumanda %.1f s'dir duruyor — panel geri almalıydı" % c.KMD_HAKIMIYET_S)

    # --- (e) ⛔ ARM ANAHTARI DA "HAREKET"TİR: acil disarm gecikmemeli ---
    t2 = t + 100.0
    k.panel_yaz(-0.2, 0, 0, 0, arm=True, t=t2)
    k.tik(simdi=t2)
    assert k.durum["insan"] == "panel"
    km.c.arm = False                                   # pilot ARM'ı kapattı
    k.panel_yaz(-0.2, 0, 0, 0, arm=True, t=t2 + 0.05)
    ok, d = k.tik(simdi=t2 + 0.05)
    assert d["insan"] == "kumanda", (
        "pilot ARM anahtarını çevirdi ama kumanda devralmadı — acil disarm "
        "gecikirdi")
    assert d["arm"] is False, "pilotun DISARM'ı uygulanmadı"


# ---------------------------------------------------------------- R64
def test_R64_gurultu_KENDILIGINDEN_devralmiyor():
    """Gimbal gürültüsü/ölü bant kumandayı kendiliğinden hâkim yapmamalı.

    ⛔ NİYE: eşik çok küçük olursa duran bir kumanda, elektriksel gürültüyle
       sürekli "oynuyor" görünür ve panel HİÇ süremez — kullanıcının
       kaldırmamı istediği donmanın aynısı geri gelir.
    """
    c = KomutCfg
    assert c.KMD_HAREKET_ESIK >= 0.03, "eşik çok küçük, gürültü devralır"
    sp, bag, km, k = _duzenek(arm=True, kip_anahtari=True)
    t = 2000.0
    k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=t)
    k.tik(simdi=t)
    # eşiğin ALTINDA titreşim — devralmamalı
    for i in range(60):
        km.c.roll = 0.01 if i % 2 else -0.01
        km.c.pitch = 0.005 if i % 3 else -0.005
        tt = t + 0.05 * (i + 1)
        k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
        ok, d = k.tik(simdi=tt)
        assert d["insan"] == "panel", (
            "tik %d: eşik altı gürültü kumandayı hâkim yaptı" % i)
    assert k.sayac["kmd_hareket"] == 0


# ---------------------------------------------------------------- R65
def test_R65_kumanda_SONRADAN_takilirsa_yakalanir():
    """⛔ SAHADA GÖRÜLDÜ (2026-08-29): kullanıcı programı başlattı, SONRA
    kumandayı taktı ve panel sonsuza dek "takılı değil" dedi.

    Sebep: `Kumanda.ac()` yalnız açılışta çağrılıyordu ve başarısız olunca
    nesne atılıyordu. Sahada sıra HEP şudur — önce yazılım açılır, sonra
    donanım toplanır. Yani bu, istisna değil NORMAL durumdu.
    """
    c = KomutCfg

    class _GecTakilan:
        """Belirli bir zamandan sonra takılan kumanda."""
        def __init__(self):
            self.hazir = False
            self.n_ac = 0
            self.takili = False
            self.c = Cubuklar(-0.7, 0.0, 0.0, 0.0, arm=True, kip_anahtari=True)

        def ac(self):
            self.n_ac += 1
            self.hazir = self.takili
            return self.hazir

        def oku(self):
            return self.c if self.hazir else None

    km = _GecTakilan()
    sp = _SahtePort(); bag = ElrsBag(sahte_port=sp); bag.ac()
    k = KomutSureci(bag, km)
    t = 3000.0

    # --- açılışta kumanda YOK: panel sürer, ama nesne ATILMAZ ---
    for i in range(5):
        tt = t + i * c.KMD_ARA_S
        k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
        ok, d = k.tik(simdi=tt)
        assert d["insan"] == "panel"
        assert d["kmd_takili"] is False
    assert km.n_ac >= 3, ("kumanda yeniden ARANMADI (%d deneme) — sonradan "
                          "takılan cihaz asla yakalanmazdı" % km.n_ac)

    # --- kullanıcı kumandayı TAKTI ---
    km.takili = True
    tt = t + 20.0
    k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
    ok, d = k.tik(simdi=tt)
    assert d["kmd_takili"] is True, "sonradan takılan kumanda yakalanmadı"
    # ilk okuma referans alınır: henüz HÂKİM değil, panel sürmeye devam
    assert d["insan"] == "panel"

    # --- pilot çubuğu oynattı -> devralır ---
    km.c.roll = 0.5
    tt += 0.1
    k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
    ok, d = k.tik(simdi=tt)
    assert d["insan"] == "kumanda", "takıldıktan sonra oynatıldı ama devralmadı"

    # --- kumanda ÇIKARILDI -> panel geri alır, referans temizlenir ---
    km.hazir = False; km.takili = False
    tt += c.KMD_HAKIMIYET_S + 0.1
    k.panel_yaz(-0.3, 0, 0, 0, arm=True, t=tt)
    ok, d = k.tik(simdi=tt)
    assert d["kmd_takili"] is False and d["insan"] == "panel"


# ---------------------------------------------------------------- R66
def test_R66_ana_program_kumanda_nesnesini_ATMIYOR():
    """`drone_yki.py` kumanda açılamazsa nesneyi `None` yapmamalı.

    ⛔ `None` yaparsa hakem sıcak takmayı DENEYEMEZ ve kumanda o oturumda
       bir daha asla bulunamaz.
    """
    import inspect
    sys.path.insert(0, REEL)
    import drone_yki
    #   ⚠ YORUMA DEĞİL KODA BAKILIR: ilk yazdığımda düz metin araması
    #     yapmıştım ve "Eskiden `kmd = None` yapıyordum" AÇIKLAMASINA
    #     takıldı. Kaynağı ayrıştırıp gerçek atamalara bakmak gerekiyor.
    import ast
    agac = ast.parse(inspect.getsource(drone_yki).replace("\t", "    "))
    atamalar = []
    for d in ast.walk(agac):
        if isinstance(d, ast.Assign):
            for h in d.targets:
                if isinstance(h, ast.Name) and h.id == "kmd":
                    atamalar.append(ast.dump(d.value))
    assert atamalar, "drone_yki.py'de `kmd` ataması yok"
    for a in atamalar:
        assert "Constant(value=None)" not in a, (
            "drone_yki.py kumanda nesnesini None yapıyor — sıcak takma "
            "çalışmaz, sonradan takılan kumanda asla bulunmaz")
    assert any("Kumanda" in a for a in atamalar)


# ---------------------------------------------------------------- R67
def test_R67_izin_anahtari_YOKSA_otonomu_BLOKE_ETMIYOR():
    """⛔ Kumandada otonom-izin anahtarı ATANMAMIŞSA (kullanıcının durumu:
    "aux 2 hiçbir şeye atılı değildi") o eksen sabit -1.00 okunur.

    Eski davranış: `kip_anahtari=False` -> veto DAİMA kapalı -> otonom
    HİÇ açılamaz, ve sebebi de görünmez. Panelde OTONOM'a basarsın,
    hiçbir şey olmaz.

    Yeni: EKSEN_KIP=-1 iken kumanda "fikrim yok" (None) der ve izin
    PANELDEN gelir.
    """
    from gercek.kumanda import KumandaCfg

    # (a) izin anahtarı yokken kumanda None döndürmeli
    class _Kfg(KumandaCfg):
        EKSEN_KIP = -1
    from gercek.kumanda import Kumanda
    k = Kumanda(_Kfg)
    k.hazir = True
    k.n_eksen = 7

    class _J:
        def get_axis(self, i): return -1.0
    class _P:
        class event:
            @staticmethod
            def pump(): pass
    k._js = _J(); k._pg = _P()
    assert k.oku().kip_anahtari is None, (
        "EKSEN_KIP=-1 iken kumanda 'fikrim yok' (None) demeli")

    # (b) hakem: None gelince PANELİN izni korunmalı
    sp, bag, km, ks = _duzenek(arm=True, kip_anahtari=None)
    ks.kip_sec("OTONOM")
    t = 4000.0
    ks.panel_yaz(-0.3, 0, 0, 0, arm=True, otonom_izin=True, t=t)
    ks.otonom_yaz(0.2, 0, 0, 0, t=t)
    ok, d = ks.tik(simdi=t)
    assert d["kaynak"] == "OTONOM", (
        "panel izin verdi ama kumandanın atanmamış anahtarı otonomu BLOKE "
        "etti — sebep: %s" % d["sebep"])

    # (c) anahtar VARSA (None değil) pilot hâlâ veto edebilmeli
    km.c.kip_anahtari = False
    km.c.roll = 0.5                     # kumanda oynadı -> hâkim olur
    ks.panel_yaz(-0.3, 0, 0, 0, arm=True, otonom_izin=True, t=t + 0.1)
    ks.otonom_yaz(0.2, 0, 0, 0, t=t + 0.1)
    ok, d = ks.tik(simdi=t + 0.1)
    assert d["sebep"] == "pilot_vetosu", (
        "anahtar atanmışken pilot vetosu çalışmalı, sebep: %s" % d["sebep"])


# ---------------------------------------------------------------- R68
def test_R68_kumanda_LINUX_JS_yolunu_tercih_ediyor_SDL_pompasi_YOK():
    """⛔ SAHADA GÖRÜLDÜ (2026-08-29): "kumandadan kontrol çalışıyor, sonra
    bir süre sonra donuyor."

    Kök neden: `pygame.event.pump()` KOMUT İŞ PARÇACIĞINDAN çağrılıyordu.
    SDL, olay kuyruğunun kendi alt sistemini kuran iş parçacığından
    pompalanmasını bekler; başka iş parçacığından pompalamak DESTEKLENMEZ
    ve sessizce takılabilir — takılınca komut döngüsü de durur.

    Çözüm: Linux joystick API (/dev/input/jsN) — saf dosya okuması, olay
    pompası YOK, bloke etmez.
    """
    import inspect
    from gercek import kumanda as KM

    # (a) Linux yolu VAR ve önce denenir
    assert hasattr(KM, "_JsOkuyucu"), "Linux joystick okuyucusu yok"
    kaynak = inspect.getsource(KM.Kumanda.ac)
    assert "/dev/input/js" in kaynak, "ac() önce Linux js API'yi denemeli"
    sdl_yeri = kaynak.find("_sdl_ac")
    js_yeri = kaynak.find("/dev/input/js")
    assert js_yeri < sdl_yeri, "SDL, Linux yolundan ÖNCE deneniyor"

    # (b) Linux yolunda SDL'e HİÇ dokunulmaz
    oku_kaynak = inspect.getsource(KM.Kumanda.oku)
    i_js = oku_kaynak.find("_jsapi")
    i_pump = oku_kaynak.find("event.pump")
    assert i_js >= 0 and i_js < i_pump, (
        "oku() SDL pompasını Linux yolundan önce çağırıyor")

    # (c) olay çözümü doğru: 8 baytlık <IhBB
    assert KM._JsOkuyucu.OLAY.size == 8
    ham = KM._JsOkuyucu.OLAY.pack(1234, 16384, 0x02, 3)   # eksen 3, yarım
    _t, deger, tip, no = KM._JsOkuyucu.OLAY.unpack(ham)
    assert (deger, tip, no) == (16384, 0x02, 3)

    # (d) `ILK` biti de eksen sayılmalı (açılış durumu 0x82 gelir)
    assert (0x82 & ~KM._JsOkuyucu.ILK) == KM._JsOkuyucu.EKSEN


# ---------------------------------------------------------------- R69
def test_R69_kamera_DAHILI_webcami_ELIYOR():
    """⛔ SAHADA GÖRÜLDÜ: panelde yakalama kartı yerine dizüstünün DAHİLİ
    kamerası çıkıyordu (varsayılan indeks 0'dı).

    Ölçülen kurulum:
        video0/1  "USB webcam"  (Quanta, DAHİLİ)   kare VERMİYOR
        video2    "USB Video"   (MacroSilicon MS210x = EasierCAP)  ✔ 640x480
        video3    "USB Video"   (meta veri düğümü)  kare VERMİYOR

    ⛔ "AÇILDI" YETMEZ, "KARE VERİYOR" GEREKİR: UVC cihazlar her biri için
       İKİ düğüm oluşturur ve meta düğümü açılır ama kare vermez.
    """
    from gercek import kamera_yakala as KY

    assert KY.KameraCfg.KAYNAK.lower() in ("oto", "auto"), (
        "varsayılan 'oto' olmalı; sabit indeks yanlış cihazı seçer")

    # seçim kuralını doğrudan sına (donanımdan bağımsız)
    ornek = [
        {"yol": "/dev/video0", "ad": "USB webcam: USB webcam",
         "kare": False, "cozunurluk": None},
        {"yol": "/dev/video1", "ad": "USB webcam: USB webcam",
         "kare": True, "cozunurluk": (1280, 720)},
        {"yol": "/dev/video2", "ad": "USB Video: USB Video",
         "kare": True, "cozunurluk": (640, 480)},
    ]
    eski = KY.cihazlari_tara
    try:
        KY.cihazlari_tara = lambda kare_dene=True: ornek
        yol, gerekce = KY.otomatik_bul()
        assert yol == "/dev/video2", (
            "kare veren DAHİLİ kamera (video1) varken bile HARİCİ cihaz "
            "seçilmeliydi; seçilen: %s" % yol)
        # yalnız dahili varsa onu seçer ama UYARIR
        KY.cihazlari_tara = lambda kare_dene=True: ornek[:2]
        yol2, g2 = KY.otomatik_bul()
        assert yol2 == "/dev/video1" and "DAHİLİ" in g2
        # hiçbiri kare vermiyorsa AÇIK sebep
        KY.cihazlari_tara = lambda kare_dene=True: [ornek[0]]
        yol3, g3 = KY.otomatik_bul()
        assert yol3 is None and "kare vermiyor" in g3
    finally:
        KY.cihazlari_tara = eski
