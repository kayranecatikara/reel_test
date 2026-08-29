# -*- coding: utf-8 -*-
"""
================================================================================
DİKEY DÖNGÜ TEZGÂHI — donanıma dokunmadan, çevrimdışı
================================================================================
⛔ NİYE VAR: `gercek/dikey.py` sistemin EN TEHLİKELİ kodudur. İşaret ya da
   kazanç hatası, aracın göğe kaçması ya da yere inmesi demektir. O yüzden
   karta ilk komut gitmeden ÖNCE burada sınanır.

⚠ BU BİR KANIT DEĞİL, BİR ELEMEDİR (CLAUDE.md §2): "eski log replay'i kanıt
  değildir" kuralının kardeşi — benzetim de kabul kararı vermez. Yaptığı iş,
  KÖTÜ ayarları uçurmadan elemektir. Kabul, gerçek uçuşla gelir.

MODELLENEN FİZİK
  itki (birim kütle başına):  a_itki = g·(u/u_asili)²      u = gaz kesri
  dikey ivme:                 a_z    = a_itki·cos(yatış) − g
  hız:                        vz    += a_z·dt
  sürükleme:                  −KD·vz·|vz|            (terminal hızı sınırlar)

MODELLENEN ÖLÇÜM ZİNCİRİ (gerçekteki gecikmenin kaynakları)
  barometre + füzyon süzgeci : birinci mertebe, τ = 0.25 s
  CRSF telemetri             : sıfırıncı mertebe tutucu, 5-10 Hz
  RF link                    : saf gecikme, 30 ms
================================================================================
"""
import argparse
import math
import os
import sys

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if KOK not in sys.path:
    sys.path.insert(0, KOK)

from gercek.dikey import DikeyDongu, DikeyCfg, yatis_cos    # noqa: E402

G = 9.81


class QuadDikey:
    """Bir quad'ın dikey ekseni + ölçüm zinciri."""

    def __init__(self, u_asili=0.50, kd=0.02, tau_baro=0.25,
                 telem_hz=8.0, gecikme_s=0.03, pil_dusus=0.0):
        self.u_asili = u_asili
        self.kd = kd
        self.tau_baro = tau_baro
        self.telem_dt = 1.0 / telem_hz
        self.gecikme_s = gecikme_s
        self.pil_dusus = pil_dusus       # asılı gazın saniyedeki artışı
        self.vz = 0.0
        self.z = 0.0
        self.t = 0.0
        self._baro = 0.0
        self._kuyruk = []                # (t, baro_degeri) — saf gecikme
        self._son_telem_t = -9e9
        self._telem = 0.0
        self._telem_t = 0.0

    def adim(self, thr_cubuk, cos_yatis, dt):
        u_a = self.u_asili + self.pil_dusus * self.t
        u = max(0.0, min(1.0, (thr_cubuk + 1.0) * 0.5))
        a_itki = G * (u / u_a) ** 2
        a_z = a_itki * cos_yatis - G - self.kd * self.vz * abs(self.vz)
        self.vz += a_z * dt
        self.z += self.vz * dt
        self.t += dt
        # --- ölçüm zinciri ---
        a = dt / (self.tau_baro + dt)
        self._baro += a * (self.vz - self._baro)          # baro süzgeci
        self._kuyruk.append((self.t, self._baro))         # saf gecikme
        while self._kuyruk and self._kuyruk[0][0] < self.t - self.gecikme_s:
            self._gecikmis = self._kuyruk.pop(0)[1]
        gec = getattr(self, "_gecikmis", 0.0)
        if self.t - self._son_telem_t >= self.telem_dt:   # telemetri tutucu
            self._son_telem_t = self.t
            self._telem = gec
            self._telem_t = self.t
        return self._telem, self.t - self._telem_t


def kosu(vz_profili, sure=25.0, dt=0.02, yatis_deg=0.0, cfg=None,
         dis_irtifa_kp=None, hedef_z=0.0, **plant):
    """dis_irtifa_kp verilirse GÜDÜMÜN DIŞ DÖNGÜSÜ de modellenir.

    ⛔ NİYE ŞART: `dow/gudum/gps.py` düşey hızı ŞÖYLE üretir:
           vz = ISTASYON_KP_Z · (hedef_z − z)        (KP_Z = 0.9)
    Yani vz isteği sabit değil, KONUM HATASINDAN gelir. Dikey döngüyü tek
    başına ölçüp "1.5 m/s kalıcı hata var" demek YANILTICIDIR: dış döngü o
    hatayı bir İRTİFA ÖTELEMESİNE çevirir ve orada durur (kaçmaz).
    Bu ayrımı görmeden ayar yapmak, olmayan bir hastalığı tedavi etmektir.
    """
    d = DikeyDongu(cfg or DikeyCfg)
    p = QuadDikey(**plant)
    # SARSINTISIZ DEVİR: pilot asılı duruyordu, çubuğu neyse ondan başla
    thr0 = p.u_asili * 2.0 - 1.0
    d.sifirla(thr0)
    cosy = yatis_cos(math.radians(yatis_deg), 0.0)
    kayit = []
    n = int(sure / dt)
    for i in range(n):
        t = i * dt
        if dis_irtifa_kp is not None:
            vz_ist = dis_irtifa_kp * (hedef_z - p.z)      # GÜDÜMÜN dış döngüsü
        else:
            vz_ist = vz_profili(t)
        olcum, yas = p._telem, p.t - p._telem_t
        thr = d.hesapla(vz_ist, olcum, dt, cos_yatis=cosy, olcum_yasi=yas)
        p.adim(thr, cosy, dt)
        kayit.append((t, vz_ist, p.vz, olcum, thr, p.z, d.I))
    return kayit


def _ozet(ad, kayit, hedef_vz, oturma_bandi=0.3):
    son = kayit[-1]
    vz = [k[2] for k in kayit]
    # oturma: |vz - hedef| bandın içine girip BİR DAHA çıkmadığı ilk an
    otur = None
    for i in range(len(kayit) - 1, -1, -1):
        if abs(kayit[i][2] - hedef_vz) > oturma_bandi:
            otur = kayit[i + 1][0] if i + 1 < len(kayit) else None
            break
    else:
        otur = 0.0
    asim = (max(vz) - hedef_vz) if hedef_vz >= 0 else (hedef_vz - min(vz))
    print("  %-26s otur %5s s   asim %+6.2f m/s   son vz %+6.2f   "
          "irtifa %+7.1f m   I %+.3f"
          % (ad, ("%.1f" % otur) if otur is not None else "YOK",
             asim, son[2], son[5], son[6]))
    return otur, asim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dt", type=float, default=0.02)
    a = ap.parse_args()
    print("=" * 78)
    print("  DİKEY DÖNGÜ TEZGÂHI — varsayılan ayarlarla")
    print("  KP=%.4f  KI=%.4f  P_YETKI=%.2f  I_MAX=%.2f  SLEW=%.1f"
          % (DikeyCfg.KP, DikeyCfg.KI, DikeyCfg.P_YETKI,
             DikeyCfg.I_MAX, DikeyCfg.SLEW))
    print("=" * 78)

    print("\n[1] BASAMAK TEPKİSİ — 0'dan +2 m/s tırmanma isteği")
    for uh in (0.40, 0.50, 0.60):
        k = kosu(lambda t: 0.0 if t < 2 else 2.0, sure=25, dt=a.dt, u_asili=uh)
        _ozet("asili gaz %.2f" % uh, k, 2.0)

    print("\n[2] ASILI TUTMA — istek 0, 30 s (surukleme yok, en zoru)")
    k = kosu(lambda t: 0.0, sure=30, dt=a.dt, u_asili=0.5, kd=0.0)
    _ozet("vz_ist=0, 30 s", k, 0.0)

    print("\n[3] YATIŞTA — 45° ve 60° yatarken asili tutabiliyor mu")
    for yd in (0.0, 45.0, 60.0):
        k = kosu(lambda t: 0.0, sure=20, dt=a.dt, yatis_deg=yd, u_asili=0.5)
        _ozet("yatis %2.0f derece" % yd, k, 0.0)

    print("\n[4] PİL DÜŞÜŞÜ — tumlev RAMPA bozucusunu ne kadar takip edebiliyor")
    print("    TURETME: PI kontrolcu BASAMAK bozucuya sifir kalici hata verir,")
    print("    ama RAMPA bozucuya sabit hata birakir:  e_kalici = R / KI")
    print("    (R = asili gazin CUBUK biriminde saniyelik kaymasi)")
    print("    Gercekci deger: LiPo 4.2 -> 3.5 V/hucre, itki ~%%30 duser,")
    print("    gaz kesri 1/sqrt(0.7)=1.20 kat artar -> 0.45'ten 0.54'e,")
    print("    300 s'de 0.09 kesir = 0.18 cubuk -> R = 0.0006 cubuk/s")
    for R_u, ad in [(0.0003, "GERCEKCI (5 dk ucus)"), (0.004, "13x ABARTILI")]:
        e_teori = (2 * R_u) / DikeyCfg.KI
        k = kosu(lambda t: 0.0, sure=60, dt=a.dt, u_asili=0.45, pil_dusus=R_u)
        print("    %-22s R=%.4f cubuk/s -> teori e=%.2f m/s" % (ad, 2 * R_u, e_teori))
        _ozet("      tek basina vz dongusu", k, 0.0)
        k2 = kosu(None, sure=60, dt=a.dt, u_asili=0.45, pil_dusus=R_u,
                  dis_irtifa_kp=0.9, hedef_z=0.0)
        son = k2[-1]
        print("      + GUDUMUN DIS DONGUSU (KP_Z=0.9): irtifa oteleme %+.2f m, "
              "vz %+.2f m/s" % (son[5], son[2]))
    print("    -> Dis dongu, kalici vz hatasini SABIT bir irtifa otelemesine")
    print("       cevirir ve orada durur; KACMAZ. Tek basina olcup 'kaciyor'")
    print("       demek yanlis teshis olurdu.")

    print("\n[5] ALÇALMA — -2 m/s istegi (asimetrik mi?)")
    k = kosu(lambda t: 0.0 if t < 2 else -2.0, sure=25, dt=a.dt, u_asili=0.5)
    _ozet("vz_ist=-2", k, -2.0)

    print("\n[6] ⛔ İŞARET HATASI — ölçüm tersine çevrilirse")
    # ⚠ İLK YAZDIĞIMDA BU TEST YANLIŞTI: istek 0 ve ölçüm 0 iken −0 = 0,
    #   yani hata hiç doğmuyordu ve test "bir şey olmuyor" diyordu. Bir
    #   kararlılık hatası, sistem RAHATSIZ EDİLMEDEN görünmez. Şimdi
    #   +1 m/s tırmanma isteniyor: doğru işaret oturur, ters işaret KAÇAR.
    for ters in (False, True):
        d = DikeyDongu(); p = QuadDikey(u_asili=0.5)
        d.sifirla(0.0)
        for i in range(int(15 / a.dt)):
            olcum = p._telem * (-1.0 if ters else 1.0)
            thr = d.hesapla(1.0, olcum, a.dt, 1.0, p.t - p._telem_t)
            p.adim(thr, 1.0, a.dt)
        print("  olcum isareti %-6s -> 15 s sonunda vz %+7.2f m/s, irtifa %+8.1f m %s"
              % ("DOGRU" if not ters else "TERS", p.vz, p.z,
                 "" if not ters else "<- KACAK"))
    print("  -> ters isaret dogrusal olarak KACIRIYOR. Bu yuzden")
    print("     `araclar/isaret_olc.py` ile ONCE olculecek, sonra otonom acilacak.")

    print("\n[7] KAZANC TARAMASI — tau'yu kucultmek (KP buyutmek) ne yapiyor")
    for tau in (3.0, 2.0, 1.0, 0.5, 0.25):
        kp = 1.0 / (19.6 * tau)

        class C(DikeyCfg):
            KP = kp
        k = kosu(lambda t: 0.0 if t < 2 else 2.0, sure=25, dt=a.dt, cfg=C)
        vz = [x[2] for x in k]
        salinim = sum(1 for i in range(len(vz) - 1)
                      if (vz[i] - 2.0) * (vz[i + 1] - 2.0) < 0 and k[i][0] > 2)
        print("  tau=%.2f KP=%.4f -> asim %+5.2f m/s, hedef etrafinda %d gecis %s"
              % (tau, kp, max(vz) - 2.0, salinim,
                 "<- SALINIM" if salinim > 6 else ""))

    print("\n[8] GECIKME DUYARLILIGI — tau secimini belirleyen sey")
    print("    (telemetri hizi ve baro gecikmesi kotulestikce hangi tau dayaniyor)")
    print("    %-22s %s" % ("kosul", "  ".join("tau=%.1f" % t for t in (0.5, 1.0, 2.0, 3.0))))
    for ad, kw in [("iyimser  (10Hz,0.15s)", dict(telem_hz=10.0, tau_baro=0.15)),
                   ("beklenen ( 8Hz,0.25s)", dict(telem_hz=8.0, tau_baro=0.25)),
                   ("kotu     ( 5Hz,0.40s)", dict(telem_hz=5.0, tau_baro=0.40)),
                   ("cok kotu ( 3Hz,0.60s)", dict(telem_hz=3.0, tau_baro=0.60))]:
        satir = []
        for tau in (0.5, 1.0, 2.0, 3.0):
            class C2(DikeyCfg):
                KP = 1.0 / (19.6 * tau)
            k = kosu(lambda t: 0.0 if t < 2 else 2.0, sure=30, dt=a.dt,
                     cfg=C2, **kw)
            vz = [x[2] for x in k]
            gec = sum(1 for i in range(len(vz) - 1)
                      if (vz[i] - 2.0) * (vz[i + 1] - 2.0) < 0 and k[i][0] > 2)
            asim = max(vz) - 2.0
            im = "!!" if gec > 6 or asim > 1.0 else ("? " if gec > 3 else "OK")
            satir.append("%s%+4.1f" % (im, asim))
        print("    %-22s %s" % (ad, "  ".join(satir)))
    print("    OK = oturuyor   ? = huzursuz   !! = SALINIM/asim")

    print("\n[9] ⛔ MODEL KAZANCI BELIRSIZLIGI — FIZIKSEL aralikta")
    print("    ⚠ ILK YAZDIGIMDA BU TESTI YANLIS KURDUM: 'kazanc x3' diye")
    print("       taradim, ama o asili gazin %16.7 olmasi demek = 36:1")
    print("       itki/agirlik. Fiziksel degil; test her ayari 'kirik'")
    print("       gosteriyordu. Dogru degisken ITKI/AGIRLIK oranidir.")
    print("    TURETME: itki ~ gaz^2 ise, asili gaz kesri u_a = 1/sqrt(T/W).")
    print("             uyarici kazanci K = 2g/u_a * 0.5 = g/u_a = g*sqrt(T/W)")
    tw_ler = (2.5, 3.0, 4.0, 5.0, 6.0, 8.0)
    print("    %-22s %s" % ("", "  ".join("T/W %.1f" % x for x in tw_ler)))
    print("    %-22s %s" % ("asili gaz kesri", "  ".join(
        "  %.2f " % (1.0 / math.sqrt(x)) for x in tw_ler)))
    print("    %-22s %s" % ("gercek K", "  ".join(
        " %5.1f " % (9.81 * math.sqrt(x)) for x in tw_ler)))
    print("    %-22s %s" % ("K / tahmin(19.6)", "  ".join(
        " x%.2f " % (9.81 * math.sqrt(x) / 19.6) for x in tw_ler)))
    print()
    for tau in (0.5, 1.0, 2.0, 3.0):
        class C3(DikeyCfg):
            KP = 1.0 / (19.6 * tau)
        satir = []
        for tw in tw_ler:
            uh = 1.0 / math.sqrt(tw)
            k = kosu(lambda t: 0.0 if t < 2 else 2.0, sure=30, dt=a.dt,
                     cfg=C3, u_asili=uh, telem_hz=8.0, tau_baro=0.25)
            vz = [x[2] for x in k]
            gec = sum(1 for i in range(len(vz) - 1)
                      if (vz[i] - 2.0) * (vz[i + 1] - 2.0) < 0 and k[i][0] > 2)
            asim = max(vz) - 2.0
            im = "!!" if gec > 6 or asim > 1.0 else ("? " if gec > 3 else "OK")
            satir.append("%s%+5.2f" % (im, asim))
        print("    tau=%.1f (KP=%.4f)  %s" % (tau, C3.KP, " ".join(satir)))
    print("    OK = oturuyor   ? = huzursuz   !! = SALINIM/asim")
    print("    -> 7 inc bir quad tipik olarak T/W 3-6 arasindadir.")

    print("\n[10] OLCUM GURULTUSU — KP'yi buyutmek cubugu titretir mi")
    import random
    for tau in (1.0, 2.0):
        class C4(DikeyCfg):
            KP = 1.0 / (19.6 * tau)
        for gur in (0.0, 0.3, 0.6):
            rnd = random.Random(12345)          # SABIT TOHUM: tekrarlanabilir
            d = DikeyDongu(C4); p = QuadDikey(u_asili=0.5)
            d.sifirla(0.0); thrs = []
            for i in range(int(30 / a.dt)):
                olcum = p._telem + rnd.gauss(0.0, gur)
                thr = d.hesapla(0.0, olcum, a.dt, 1.0, p.t - p._telem_t)
                p.adim(thr, 1.0, a.dt); thrs.append(thr)
            fark = [abs(thrs[i+1]-thrs[i]) for i in range(len(thrs)-1)]
            titrek = sum(fark) / len(fark)
            print("    tau=%.1f gurultu %.1f m/s -> cubuk oynamasi %.5f/tik "
                  "(%.1f us/tik), irtifa sapmasi %+.2f m"
                  % (tau, gur, titrek, titrek * 512, p.z))


if __name__ == "__main__":
    main()
