#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
DRONE YER KONTROL İSTASYONU — tek giriş noktası
================================================================================
DRONE BİLGİSAYARINDA çalışır. Kurduğu zincir:

  [ELRS seri]  <--CRSF-->  drone           telemetri IN / komut OUT
  [kumanda USB]            pilot çubukları  (varsa; panele göre ÖNCELİKLİ)
  [yakalama kartı]         FPV video        -> YOLO -> kilit ölçütü
  [UDP 47800]              hedef GPS        <- Talon bilgisayarı (5 Hz)
  [yarışma sunucusu]       telemetri 1-2 Hz + hedef + kilit paketi
  [panel :8810]            operatör arayüzü + manuel joystickler

⛔ HİÇBİR ŞEY OTOMATİK ARM ETMEZ. Arm yalnız insandan gelir (fiziksel
   kumanda anahtarı ya da panelde BASILI TUTULAN düğme).

⛔ OTONOM İÇİN DÖRT ŞART: panel OTONOM ister + pilot izin verir +
   güdüm taze setpoint üretir + kumandayla bağ tazedir. Biri düşerse
   anında MANUELE düşer (bkz. gercek/komut.py).

KULLANIM
    python3 reel/drone_yki.py --elrs /dev/ttyUSB0 --kamera 0
    python3 reel/drone_yki.py --sahte            # donanımsız deneme
================================================================================
"""
import argparse
import math
import os
import sys
import threading
import time

KOK = os.path.dirname(os.path.abspath(__file__))
UST = os.path.dirname(KOK)
for p in (KOK, UST):
    if p not in sys.path:
        sys.path.insert(0, p)

from gercek import panel as PANEL                       # noqa: E402
from gercek.baglanti import GercekBaglanti              # noqa: E402
from gercek.dikey import DikeyDongu                     # noqa: E402
from gercek.elrs import ElrsBag                         # noqa: E402
from gercek.hedef import HedefKaynagi, UdpDinleyici     # noqa: E402
from gercek.kamera_yakala import Kamera, KameraCfg      # noqa: E402
from gercek.komut import KomutSureci                    # noqa: E402
from gercek.kumanda import Kumanda                      # noqa: E402
from gercek.skydagger import SkydaggerBag, SkydaggerCfg  # noqa: E402
from gercek.sunucu import SunucuIstemcisi, SunucuCfg    # noqa: E402


def _arg():
    a = argparse.ArgumentParser(description="Avcı drone yer kontrol istasyonu")
    a.add_argument("--bag", default=os.environ.get("DOW_BAG", "skydagger"),
                   choices=("skydagger", "crsf"),
                   help="skydagger = komitenin ESP32 backend'i (VARSAYILAN); "
                        "crsf = doğrudan seri CRSF (yedek yol)")
    a.add_argument("--sky-host", default=SkydaggerCfg.HOST)
    a.add_argument("--sky-tasima", default=SkydaggerCfg.TASIMA,
                   choices=("udp", "tcp"), help="RC yolu (rehber §8.3)")
    a.add_argument("--elrs", default=os.environ.get("DOW_ELRS_PORT", ""),
                   help="(yalnız --bag crsf) ELRS seri portu")
    a.add_argument("--baud", type=int, default=int(
        os.environ.get("DOW_ELRS_BAUD", 420000)),
        help="(yalnız --bag crsf) CRSF baud")
    a.add_argument("--kamera", default=os.environ.get("DOW_KAM_KAYNAK", "0"))
    a.add_argument("--port", type=int, default=8810, help="panel portu")
    a.add_argument("--gorsel", action="store_true",
                   help="YOLO + görsel güdümü aç (model gerekir)")
    a.add_argument("--sunucu", default="", help="yarışma sunucusu adresi")
    a.add_argument("--hz", type=float, default=50.0, help="güdüm döngü hızı")
    a.add_argument("--sahte", action="store_true",
                   help="donanımsız deneme (seri port ve kamera aranmaz)")
    return a.parse_args()


class _SahtePort:
    def __init__(self):
        self.in_waiting = 0
        self.n = 0

    def write(self, b):
        self.n += 1

    def read(self, n=0):
        return b""

    def close(self):
        pass


def main():
    a = _arg()
    print("=" * 70)
    print("  AVCI DRONE — YER KONTROL İSTASYONU")
    print("=" * 70)

    # ---------------- 1) ELRS bağı ----------------
    if a.bag == "skydagger":
        # ⭐ KOMİTENİN RESMÎ YOLU (Skydagger rehberi v2.0):
        #    bizim yazılım --RC_US--> backend --USB--> ESP32 --tel--> ELRS TX
        #    ⛔ Backend'i BİZ başlatmayız; operatör konsoldan /connect ve
        #      EXTERNAL yapar (rehber §8: "harici script kurulum komutu
        #      göndermez"). Biz yalnız RC_US basar, telemetri okuruz.
        SkydaggerCfg.HOST = a.sky_host
        SkydaggerCfg.TASIMA = a.sky_tasima
        bag = SkydaggerBag()
        if not bag.ac():
            print("⛔ %s" % bag.hata)
            print("   SIRA: backend'i başlat -> /connect -> RC_ENABLE ->")
            print("         (modül MAVİ) -> STOP -> EXTERNAL -> sonra bu program")
            return 2
        print("  BAĞ       : SKYDAGGER  %s:%s  (RC=%s, telemetri=TCP)"
              % (a.sky_host, SkydaggerCfg.UDP_PORT if a.sky_tasima == "udp"
                 else SkydaggerCfg.TCP_PORT, a.sky_tasima.upper()))
        print("              ⛔ İlk %.0f s YALNIZ SAFE basılacak (rehber §8) —"
              % SkydaggerCfg.GUVENLI_SURE_S)
        print("                 bu sırada modülün MAVİ ışığını doğrula.")
    elif a.sahte:
        bag = ElrsBag(sahte_port=_SahtePort())
        bag.ac()
        print("  ELRS      : SAHTE (donanımsız deneme)")
    else:
        if not a.elrs:
            print("⛔ --elrs verilmedi. Portu bulmak için:")
            print("     ls -l /dev/serial/by-id/   ·   ls /dev/ttyUSB* /dev/ttyACM*")
            print("   Donanımsız denemek için:  --sahte")
            return 2
        bag = ElrsBag(port=a.elrs, baud=a.baud)
        if not bag.ac():
            print("⛔ ELRS portu açılamadı: %s" % bag.hata)
            print("   · kullanıcı `dialout` grubunda mı?  sudo usermod -aG dialout $USER")
            print("   · ModemManager kapalı mı?  sudo systemctl disable --now ModemManager")
            print("   · baud: CH340 yongaları 420000'i desteklemez, 400000 dene")
            return 2
        print("  ELRS      : %s @ %d baud" % (a.elrs, a.baud))

    # ---------------- 2) kumanda ----------------
    kmd = Kumanda()
    if kmd.ac():
        print("  KUMANDA   : %s (%d eksen)" % (kmd.ad, kmd.n_eksen))
    else:
        kmd = None
        print("  KUMANDA   : YOK — panelin sanal çubukları kullanılacak")
        print("              (%s)" % Kumanda().hata)

    # ---------------- 3) hakem ----------------
    ks = KomutSureci(bag, kmd)
    if kmd is None:
        # ⛔ Fiziksel kumanda yoksa VETO ANAHTARI da yok; izin panelden gelir.
        #   Bu bilinçli bir GEVŞETMEDİR ve sahada kumanda takılıysa
        #   otomatik olarak sıkılaşır.
        ks.cfg.VETO_ZORUNLU = True     # panel `izin` alanını gönderiyor

    # ---------------- 4) hedef kaynağı ----------------
    hedef = HedefKaynagi()
    udp = UdpDinleyici(hedef)
    if udp.basla():
        print("  HEDEF     : UDP :%d dinleniyor (Talon bilgisayarı)" % udp.port)
    else:
        print("  HEDEF     : ⛔ UDP açılamadı: %s" % udp.hata)

    # ---------------- 5) araç bağlantısı ----------------
    gb = GercekBaglanti(bag, komut_sureci=ks, hedef_kaynak=hedef)

    # ---------------- 6) güdüm ----------------
    from dow.ayarlar import Ayar
    from dow import ana
    from dow.gudum.cevirici import HizCubukCevirici, CevCfg
    Ayar.GPS_KAYNAK = "gercek"          # ⛔ truth/filtre GERÇEKTE YOK
    Ayar.GORSEL_AKTIF = bool(a.gorsel)

    det = None
    if a.gorsel:
        try:
            from dow.gorus.dedektor import Dedektor
            det = Dedektor()
            print("  DEDEKTÖR  : yüklendi")
        except Exception as e:
            print("  DEDEKTÖR  : ⛔ yüklenemedi (%s) — görsel KAPALI" % e)
            Ayar.GORSEL_AKTIF = False

    dik = DikeyDongu()
    cev = HizCubukCevirici(dikey=dik)
    beyin = ana.Beyin(baglanti=gb, cevirici=cev, dedektor=det)
    # ⭐ SARSINTISIZ DEVİR: hakem kaynak değiştirdiğinde dikey döngü
    #   pilotun O ANKİ çubuğuyla tohumlanır (bkz. gercek/dikey.py::sifirla)
    ks.devir_geri_cagirma = (
        lambda kaynak, thr0: dik.sifirla(thr0) if kaynak == "OTONOM"
        else dik.durdur())
    print("  ÇEVİRİCİ  : MODEL=%s  ACI_MAX=%.0f  Y_ISARET=%+.1f"
          % (CevCfg.MODEL, CevCfg.MAX_YATIS_DEG, CevCfg.Y_ISARET))
    if CevCfg.MODEL != "aci":
        print("              ⚠ GERÇEK ARAÇ İÇİN 'aci' OLMALI:")
        print("                export DOW_CEV_MODEL=aci DOW_CEV_ACI_MAX=60")

    # ---------------- 7) kamera ----------------
    kam = None
    if not a.sahte:
        KameraCfg.KAYNAK = a.kamera
        kam = Kamera()
        if kam.ac():
            time.sleep(0.5)
            w, h = kam.cozunurluk()
            print("  KAMERA    : %s  %dx%d" % (a.kamera, w, h))
        else:
            print("  KAMERA    : ⛔ %s" % kam.hata)
            kam = None

    # ---------------- 8) yarışma sunucusu ----------------
    sv = None
    adres = a.sunucu or (SunucuCfg.ADRES if os.environ.get("DOW_SUNUCU") else "")
    if adres:
        SunucuCfg.ADRES = adres
        sv = SunucuIstemcisi(hedef, lambda: _telemetri(gb, ks, beyin))
        ok, mesaj = sv.giris()
        print("  SUNUCU    : %s — %s" % (adres, mesaj))
        sv.basla()
    else:
        print("  SUNUCU    : kapalı (--sunucu ile aç)")

    # ---------------- 9) panel ----------------
    PANEL.kur(kamera=kam, komut=ks, baglanti=gb, hedef=hedef,
              sunucu=sv, beyin=beyin, dikey=dik)
    p = PANEL.baslat(a.port)
    print("  PANEL     : http://127.0.0.1:%d" % p)
    print("=" * 70)
    print("  ⛔ ARM yalnız insandan gelir. Otonom için panelde OTONOM +")
    print("     kumandada izin anahtarı BİRLİKTE gerekir.")
    print("  Çıkmak için Ctrl+C")
    print("=" * 70)

    ks.basla()                     # 50 Hz CRSF yazıcısı kendi ipliğinde

    # ---------------- 10) ana döngü ----------------
    periyot = 1.0 / max(1.0, a.hz)
    t0 = time.monotonic()
    sonraki = time.monotonic()
    son_kare_sayac = -1
    try:
        while True:
            simdi = time.monotonic()
            t = simdi - t0
            gb.pompala()                       # CRSF telemetri -> alanlar

            # --- görüş ---
            if kam is not None:
                kare, kare_t, sayac = kam.son_kare()
                if kare is not None and sayac != son_kare_sayac:
                    son_kare_sayac = sayac
                    _gorus(beyin, kare, t, kare_t - t0, a.gorsel)

            # --- güdüm ---
            if gb.canli():
                beyin.adim(t, periyot)
            sonraki += periyot
            uyku = sonraki - time.monotonic()
            time.sleep(uyku if uyku > 0 else 0.0)
            if uyku < -0.5:
                sonraki = time.monotonic()
    except KeyboardInterrupt:
        print("\n  kapatılıyor...")
    finally:
        ks.dur()
        if sv:
            sv.dur()
        udp.dur()
        if kam:
            kam.kapat()
        gb.kapat()
        PANEL.durdur()
        print("  kapandı. ⛔ Aracı havada bırakma — pilot indirsin.")
    return 0


def _gorus(beyin, kare, t, kare_t, gorsel_acik):
    """Kareyi dedektöre ver ve panel için kilit ölçütünü hesapla."""
    import cv2
    from dow.ayarlar import Ayar
    from dow.gudum.kilit import KilitDurumu
    if not hasattr(_gorus, "_olcut"):
        _gorus._olcut = KilitDurumu(Ayar)
    kabul = None
    if gorsel_acik and beyin.det is not None:
        rgb = cv2.cvtColor(kare, cv2.COLOR_BGR2RGB)
        kabul = beyin.gorsel_tik(rgb, t, kare_t)
    bilgi = _gorus._olcut.guncelle(t, kabul)
    PANEL._D["son_kutu"] = kabul[:4] if kabul else None
    PANEL._D["olcut"] = {"bu_kare": bool(bilgi.get("kilit_bu")),
                         "kilit_s": round(bilgi.get("kilit_s", 0.0), 2),
                         "sebep": bilgi.get("kilit_sebep", ""),
                         "saglandi": bool(_gorus._olcut.saglandi)}


def _telemetri(gb, ks, beyin):
    """Yarışma sunucusuna gönderilecek paket (haberleşme dokümanı §7.1)."""
    from dow.ayarlar import Ayar
    x, y, z = gb.konum()
    r, p, yw = gb.yonelim()
    kutu = PANEL._D.get("son_kutu") or (0, 0, 0, 0)
    olcut = PANEL._D.get("olcut") or {}
    enlem, boylam, _ = (gb.cerceve.dereceye(x, y, z) if gb.cerceve.hazir
                        else (0.0, 0.0, 0.0))
    return {
        "takim_no": SunucuCfg.TAKIM_NO,
        "enlem": round(enlem, 7), "boylam": round(boylam, 7),
        "irtifa": round(z, 1),
        "dikilme": round(math.degrees(p), 1),
        "yonelme": round(math.degrees(yw) % 360.0, 1),
        "yatis": round(math.degrees(r), 1),
        "hiz": round(gb.hiz(), 1),
        # ⛔ mod: 1 = otonom. Hakem GERÇEKTE otonom komut mu gönderiyor,
        #   onu söyler — panelde ne seçili olduğunu değil.
        "mod": 1 if ks.durum.get("kaynak") == "OTONOM" else 0,
        "kilitlenme": 1 if olcut.get("saglandi") else 0,
        "hedef_x_merkezi": int(kutu[0]), "hedef_y_merkezi": int(kutu[1]),
        "hedef_genislik": int(kutu[2]), "hedef_yukseklik": int(kutu[3]),
    }


if __name__ == "__main__":
    sys.exit(main())
