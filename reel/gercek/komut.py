# -*- coding: utf-8 -*-
"""
================================================================================
KOMUT SÜRECİ — pilot ile güdüm arasındaki HAKEM (emniyetin kalbi)
================================================================================
⛔ NİYE AYRI VE KÜÇÜK: yerden güdümlü mimaride bilgisayar kontrol
   döngüsünün İÇİNDEDİR. Güdüm süreci (YOLO + IBVS + çevirici) ağırdır ve
   çökebilir. Çökerse pilotun da komutu gidemezse araç kaybedilir.

   Bu yüzden CRSF'i yazan tek yer BURASIDIR ve burası KÜÇÜKTÜR: YOLO yok,
   numpy yok, ağır iş yok. Güdüm ölse bile bu döngü döner ve pilot uçurur.

        [kumanda USB HID] ─┐
                           ├─→ [KOMUT SÜRECİ] 50 Hz ──> ELRS ──> drone
        [güdüm süreci] ────┘    anahtar BURADA

--------------------------------------------------------------------------------
⛔⛔ DEĞİŞMEZ KURAL — ARM DAİMA PİLOTTAN
--------------------------------------------------------------------------------
Güdümün arm kanalına erişimi YOKTUR. `OtonomIstek` yapısında arm alanı
BULUNMAZ; arm değeri her tikte pilotun anahtarından okunur. Yani bir
yazılım hatası aracı arm EDEMEZ. Bekçi R35 bunu sınar.

--------------------------------------------------------------------------------
EMNİYET SIRA DÜZENİ — hangi arıza ne yapar
--------------------------------------------------------------------------------
| durum                                   | ne gönderilir        | neden |
|-----------------------------------------|----------------------|-------|
| OTONOM, pilot İZİN verdi, güdüm taze    | güdüm + pilot ARM    | normal |
| kumanda OYNATILDI (son 3 s)             | kumanda çubukları    | pilot devraldı |
| kumanda takılı ama DURUYOR               | panel çubukları      | operatör sürüyor |
| OTONOM ama pilot VETO etti              | pilot çubukları      | pilot son sözü söyler |
| OTONOM, güdüm BAYAT (>OTO_ASIM)         | pilot çubukları      | güdüm öldü, pilot uçursun |
| MANUEL                                  | pilot çubukları      | pilot komutta |
| kumanda KOPUK, güdüm taze, OTONOM       | güdüm + SON arm      | USB kopması uçağı düşürmemeli |
| kumanda kopuk VE güdüm bayat            | ⛔ PAKET YOK         | RX failsafe -> AUTO-LAND |
| kumanda kopukluğu > KMD_TESLIM (3 s)    | ⛔ PAKET YOK         | müdahale edecek kimse yok -> güvenli iniş |

⛔ "PAKET YOK" NİYE DOĞRU DAVRANIŞ: paket kesilince alıcı failsafe'e girer
   ve Betaflight `failsafe_procedure = AUTO-LAND` uygular. Alternatifler
   daha kötü: nötr çubuk göndermek aracı süzülerek uzaklaştırır; disarm
   göndermek onu DÜŞÜRÜR.

⛔ DISARM ASLA "EMNİYET TEDBİRİ" OLARAK GÖNDERİLMEZ. Havada disarm =
   serbest düşüş. Disarm yalnız pilotun kendi anahtarıyla olur.
================================================================================
"""
import os
import threading
import time

from . import crsf


class KomutCfg:
    HZ          = float(os.environ.get("DOW_KMT_HZ", 50.0))
    #: Güdüm bu süre sessiz kalırsa OTONOM düşer, çubuklara dönülür.
    #: 200 ms = 10 güdüm tiki (50 Hz). Daha kısası, tek bir gecikme
    #: sıçramasında gereksiz yere kipi düşürür.
    OTO_ASIM_S  = float(os.environ.get("DOW_KMT_OTO_ASIM", 0.20))
    #: Kumanda bu süre okunamazsa "kopuk" sayılır.
    KMD_ASIM_S  = float(os.environ.get("DOW_KMT_KMD_ASIM", 0.30))
    #: Kumanda bu kadar uzun kopuk kalırsa paket kesilir (-> AUTO-LAND).
    KMD_TESLIM_S = float(os.environ.get("DOW_KMT_KMD_TESLIM", 3.0))
    #: Panel çubukları bu süre tazelenmezse YOK sayılır.
    #: ⛔ Tarayıcı sekmesi kapanır, WiFi düşer, sayfa donar — hepsi olur.
    #:   Donmuş bir çubuk değerini "pilot komutu" sanmak, aracı son
    #:   verilen komutla sonsuza dek uçurmak demektir.
    PANEL_ASIM_S = float(os.environ.get("DOW_KMT_PANEL_ASIM", 1.5))
    #: ⭐ KUMANDA DEVRALMA (kullanıcı kararı 2026-08-29):
    #:   "kumanda takılı olsa bile arayüzden kontrol olsun; eğer kumandadan
    #:    joystickler hareket etmeye başlarsa o veri değişmeye başlarsa
    #:    kumandadaki girdiye bakılsın ve drone kumanda ile yönetilsin."
    #:
    #: Yani kumanda TAKILI OLMAK'la değil, OYNATILMAK'la devralır.
    #: Bir eksen bu kadar değişirse "hareket" sayılır. 0.04 seçildi:
    #: gimbal gürültüsü/ölü bant tipik olarak ±0.02'nin altında kalır;
    #: eşik onun iki katı, yani kendiliğinden devralma olmaz.
    KMD_HAREKET_ESIK = float(os.environ.get("DOW_KMT_KMD_ESIK", 0.04))
    #: Hareketten sonra kumanda bu kadar süre HÂKİM kalır. Pilot çubuğu
    #: ortada tutarken (hareket yokken) panelin devralmasını engeller.
    KMD_HAKIMIYET_S = float(os.environ.get("DOW_KMT_KMD_HAKIM", 3.0))
    #: Pilotun VETO anahtarı zorunlu mu?
    #:   True  (varsayılan): otonom, ancak pilotun anahtarı İZİN VERİYORSA
    #:                       çalışır. Anahtar kapanınca ANINDA manuele düşer.
    #:   False            : anahtar yok (tezgâh/kumandasız sınama).
    #: ⛔ SAHADA DAİMA True. Bu, pilotun tek hareketle otonomiyi kesme
    #:   yetkisidir ve yerden güdümlü mimaride EN ÖNEMLİ emniyet unsurudur.
    VETO_ZORUNLU = os.environ.get("DOW_KMT_VETO", "1") != "0"


class OtonomIstek:
    """Güdümün ürettiği çubuk isteği.

    ⛔ `arm` ALANI KASTEN YOKTUR (bkz. modül başlığı). Güdüm arm edemez.
    """
    __slots__ = ("throttle", "pitch", "roll", "yaw", "t")

    def __init__(self, throttle=0.0, pitch=0.0, roll=0.0, yaw=0.0, t=0.0):
        self.throttle = throttle; self.pitch = pitch
        self.roll = roll; self.yaw = yaw; self.t = t


class KomutSureci:
    """50 Hz CRSF yazıcısı + kaynak hakemi + bekçi zamanlayıcı."""

    def __init__(self, bag, kumanda=None, harita=None, cfg=KomutCfg):
        self.bag = bag
        self.kumanda = kumanda
        self.harita = harita or crsf.KanalHaritasi()
        self.cfg = cfg
        self.kip = "MANUEL"              # MANUEL | OTONOM
        # ⭐ DEVİR BİLDİRİMİ — SARSINTISIZ GEÇİŞİN DOĞDUĞU YER.
        #   fn(yeni_kaynak, son_manuel_throttle) diye çağrılır.
        #   MANUEL -> OTONOM anında güdüm tarafı dikey döngüyü pilotun
        #   O ANKİ çubuğuyla tohumlar; çıkış sıçramaz ve asılı gazın
        #   ÖLÇÜLMÜŞ değeri bedavaya gelir.
        #   OTONOM -> MANUEL anında döngü durdurulur; pilot uçarken
        #   tümlevin körlemesine birikmesi engellenir.
        self.devir_geri_cagirma = None
        self._onceki_kaynak = "MANUEL"
        self._son_manuel_thr = 0.0
        self._oto = None
        self._oto_kilit = threading.Lock()
        self._son_arm = False
        self._son_kmd_t = 0.0
        self._veto_izin = False        # pilot izin vermeden otonom YOK
        # ⭐ PANEL ÇUBUKLARI — fiziksel kumanda YOKKEN insan girdisi.
        #   ⛔ ARM KURALI DEĞİŞMEDİ: arm bir İNSAN kaynağından gelir
        #     (fiziksel kumanda ya da panel), GÜDÜMDEN ASLA. Güdümün
        #     `otonom_yaz()` yolunda arm alanı hâlâ YOKTUR (bekçi R35).
        self._panel = None
        self._panel_t = 0.0
        # ⭐ KUMANDA HAREKET TAKİBİ
        self._kmd_onceki = None       # son okunan çubuk değerleri
        self._kmd_hareket_t = -9e9    # son HAREKET anı
        self._kmd_takili = False
        self._calisiyor = False
        self._is = None
        # §5.1 mekanizma / teşhis
        self.sayac = {"tik": 0, "gonderilen": 0, "kesilen": 0,
                      "oto_dusme": 0, "kmd_kopuk": 0, "manuel": 0,
                      "otonom": 0, "veto": 0, "kmd_hareket": 0}
        self.durum = {"kaynak": "-", "sebep": "-", "arm": False}
        self.insan_kaynagi = ""

    # ---------------- güdümün arayüzü ----------------
    def otonom_yaz(self, throttle, pitch, roll, yaw, t=None):
        """Güdüm süreci bunu her tikte çağırır. Bloke etmez."""
        with self._oto_kilit:
            self._oto = OtonomIstek(throttle, pitch, roll, yaw,
                                    t if t is not None else time.monotonic())

    def panel_yaz(self, throttle, pitch, roll, yaw, arm=None,
                  otonom_izin=None, t=None):
        """Panelin sanal çubukları. Fiziksel kumanda varsa O ÖNCELİKLİDİR.

        `arm` ve `otonom_izin` None ise önceki değer korunur — panel her
        karede arm göndermek zorunda kalmasın.
        """
        from .kumanda import Cubuklar
        self._panel = Cubuklar(throttle, pitch, roll, yaw,
                               arm=self._son_arm if arm is None else bool(arm),
                               kip_anahtari=(self._veto_izin
                                             if otonom_izin is None
                                             else bool(otonom_izin)))
        self._panel_t = time.monotonic() if t is None else t

    def _panel_oku(self, simdi):
        if self._panel is None:
            return None
        if (simdi - self._panel_t) > self.cfg.PANEL_ASIM_S:
            return None
        return self._panel

    def kip_sec(self, kip):
        if kip not in ("MANUEL", "OTONOM"):
            raise ValueError("kip MANUEL ya da OTONOM olmalı: %r" % kip)
        self.kip = kip

    # ---------------- tek tik ----------------
    def tik(self, simdi=None):
        """Bir karar + bir paket. Döner: (gonderildi_mi, durum_sozlugu)."""
        c = self.cfg
        simdi = time.monotonic() if simdi is None else simdi
        self.sayac["tik"] += 1

        # --- 1) İNSAN GİRDİSİ — kumanda OYNATILINCA devralır ---
        #   ⭐ KURAL (kullanıcı 2026-08-29): kumanda TAKILI OLMAK'la değil,
        #     OYNATILMAK'la devralır. Takılı ama duruyorsa panel sürer;
        #     pilot çubuğa dokunduğu an kumanda hâkim olur ve
        #     KMD_HAKIMIYET_S boyunca öyle kalır.
        #   ⛔ ARM/İZİN ANAHTARI DA "HAREKET"TİR: pilot arm anahtarını
        #     çevirdiği an devralmalı — yoksa acil disarm gecikirdi.
        kmd = self.kumanda.oku() if self.kumanda is not None else None
        self._kmd_takili = kmd is not None
        if kmd is not None:
            # ⛔ DEĞERLER SAKLANIR, NESNE REFERANSI DEĞİL — bekçi R63 bunu
            #   yakaladı. Kaynak her çağrıda AYNI nesneyi döndürürse (ki
            #   meşru bir uygulamadır: tampon yeniden kullanmak) referans
            #   saklamak, "önceki" ile "şimdiki"yi AYNI şey yapar ve
            #   hareket SESSİZCE hiç görünmez. Pilot çubuğu oynatır,
            #   sistem duymaz.
            simdiki = (kmd.throttle, kmd.pitch, kmd.roll, kmd.yaw,
                       bool(kmd.arm), bool(kmd.kip_anahtari))
            o = self._kmd_onceki
            if o is None:
                self._kmd_onceki = simdiki      # ilk okuma: referans, hareket DEĞİL
            else:
                oynadi = (any(abs(simdiki[i] - o[i]) > c.KMD_HAREKET_ESIK
                              for i in range(4))
                          or simdiki[4] != o[4] or simdiki[5] != o[5])
                if oynadi:
                    self._kmd_hareket_t = simdi
                    self.sayac["kmd_hareket"] = self.sayac.get("kmd_hareket", 0) + 1
                self._kmd_onceki = simdiki

        kmd_hakim = (kmd is not None
                     and (simdi - self._kmd_hareket_t) <= c.KMD_HAKIMIYET_S)
        panel = self._panel_oku(simdi)

        if kmd_hakim:
            cubuk = kmd
            self.insan_kaynagi = "kumanda"
        elif panel is not None:
            cubuk = panel
            self.insan_kaynagi = "panel"
        elif kmd is not None:
            # Panel yok/bayat ama kumanda takılı: yine de o sürsün —
            # insansız kalmaktansa duran bir çubuk iyidir.
            cubuk = kmd
            self.insan_kaynagi = "kumanda"
        else:
            cubuk = None
            self.insan_kaynagi = ""
        if cubuk is not None:
            self._son_kmd_t = simdi
            self._son_arm = cubuk.arm
            # ⛔⛔ PİLOTUN VETO ANAHTARI — panelden seçilen kipi EZER.
            #   Pilot anahtarı kapatınca otonom O TİKTE düşer; panelin
            #   ne dediği önemsizdir. Bu, yerden güdümlü mimaride pilotun
            #   tek hareketle kontrolü geri alma yoludur.
            #   ⚠ "İzin" olarak kurgulandı, "kip seçimi" olarak değil:
            #     anahtar AÇIK iken otonom OTOMATİK başlamaz — panel de
            #     istemelidir. İki taraf da evet demeden otonom olmaz.
            self._veto_izin = bool(cubuk.kip_anahtari)
        kmd_kopuk = (simdi - self._son_kmd_t) > c.KMD_ASIM_S
        # ⛔⛔ TESLİM SÜRESİ — R39 BUNU EKSİK BULDU (2026-08-29).
        #   İlk yazdığımda `KMD_TESLIM_S` denetimi yalnız BİR dalda vardı ve
        #   izin/arm LATCH'li olduğu için o dala hiç girilmiyordu. Sonuç:
        #   kumanda kopup kopuk KALSA BİLE otonom SÜRESİZ devam ediyordu —
        #   yani havada, müdahale edebilecek kimse olmadan.
        #   Şimdi denetim TÜM otonom yollarının ÖNÜNDE, tek yerde.
        kmd_teslim = (simdi - self._son_kmd_t) > c.KMD_TESLIM_S
        if kmd_kopuk:
            self.sayac["kmd_kopuk"] += 1

        # --- 2) güdüm tazeliği ---
        with self._oto_kilit:
            oto = self._oto
        oto_taze = oto is not None and (simdi - oto.t) <= c.OTO_ASIM_S

        # --- 3) HAKEM — otonom için DÖRT şart birden ---
        #   (a) panel OTONOM istiyor
        #   (b) pilot izin veriyor (veto anahtarı)
        #   (c) güdüm taze setpoint üretiyor
        #   (d) kumandayla bağ TESLİM SÜRESİ içinde
        #   Biri bile düşerse otonom YOK.
        #   ⚠ VETO_ZORUNLU=False (tezgâh kipi) hem (b)'yi hem (d)'yi devre
        #     dışı bırakır: kumandasız sınamada pilot zinciri zaten yoktur.
        izin = (not c.VETO_ZORUNLU) or getattr(self, "_veto_izin", False)
        teslim_engeli = c.VETO_ZORUNLU and kmd_teslim
        if self.kip == "OTONOM" and not izin:
            self.sayac["veto"] += 1
        otonom_uygun = (self.kip == "OTONOM" and izin and oto_taze
                        and not teslim_engeli)

        if otonom_uygun:
            komut = (oto.throttle, oto.pitch, oto.roll, oto.yaw)
            # ⚠ Kumanda kopukken de bu dal çalışır (izin ve arm LATCH'lidir).
            #   Sebep alanı bunu SÖYLEMELİ: operatör "otonom sürüyor ama
            #   kumandayla bağım yok" durumunu görmeden fark edemez.
            kaynak = "OTONOM"
            sebep = "kumanda_kopuk" if kmd_kopuk else "-"
            self.sayac["otonom"] += 1
        elif cubuk is not None:
            komut = (cubuk.throttle, cubuk.pitch, cubuk.roll, cubuk.yaw)
            kaynak = "MANUEL"
            if self.kip != "OTONOM":
                sebep = "-"
            elif not izin:
                sebep = "pilot_vetosu"; self.sayac["oto_dusme"] += 1
            elif not oto_taze:
                sebep = "gudum_bayat"; self.sayac["oto_dusme"] += 1
            else:
                sebep = "teslim_suresi"; self.sayac["oto_dusme"] += 1
            self.sayac["manuel"] += 1
        else:
            # ⛔ NE PİLOT NE OTONOM -> PAKET KESİLİR.
            #    Alıcı failsafe'e girer, Betaflight AUTO-LAND yapar.
            self.sayac["kesilen"] += 1
            # Etiket AYIRIMI: "teslim_suresi", otonomun GERÇEKTEN
            # engellendiği hâldir (panel istiyordu, güdüm tazeydi, ama
            # kumandayla bağ koptuğu için kesildi). Hiçbir kaynak yokken
            # sebep sadece "paket_kesildi"dir — operatöre yanlış ipucu
            # vermemek için ikisi ayrı tutulur.
            _teslimden = teslim_engeli and self.kip == "OTONOM" and oto_taze
            self.durum = {"kaynak": "YOK", "insan": self.insan_kaynagi,
                          "komut": None,
                          "sebep": ("teslim_suresi" if _teslimden
                                    else "paket_kesildi"),
                          "arm": self._son_arm, "kmd_kopuk": kmd_kopuk}
            return False, self.durum

        # --- 3b) DEVİR BİLDİRİMİ (kaynak değiştiyse) ---
        if kaynak != self._onceki_kaynak:
            if self.devir_geri_cagirma is not None:
                try:
                    self.devir_geri_cagirma(kaynak, self._son_manuel_thr)
                except Exception:
                    # ⛔ Geri çağırma patlarsa KOMUT DÖNGÜSÜ DURMAZ.
                    #   Bu döngü pilotun tek yoludur; onu bir yardımcı
                    #   fonksiyonun hatası öldüremez.
                    pass
            self._onceki_kaynak = kaynak
        if kaynak == "MANUEL":
            self._son_manuel_thr = komut[0]

        # --- 4) ⛔ ARM DAİMA PİLOTTAN ---
        arm = self._son_arm
        ok = self.bag.rc_gonder(komut[0], komut[1], komut[2], komut[3],
                                arm=arm, harita=self.harita)
        if ok:
            self.sayac["gonderilen"] += 1
        self.durum = {"kaynak": kaynak, "sebep": sebep, "arm": arm,
                      "kmd_kopuk": kmd_kopuk, "komut": komut,
                      "insan": self.insan_kaynagi,
                      "kmd_takili": self._kmd_takili,
                      "kmd_hakim": bool(kmd_hakim)}
        return ok, self.durum

    # ---------------- kendi iş parçacığı ----------------
    def basla(self):
        if self._calisiyor:
            return
        self._calisiyor = True
        self._is = threading.Thread(target=self._dongu, daemon=True,
                                    name="komut-sureci")
        self._is.start()

    def dur(self):
        self._calisiyor = False
        if self._is is not None:
            self._is.join(timeout=1.0)

    def _dongu(self):
        periyot = 1.0 / self.cfg.HZ
        sonraki = time.monotonic()
        while self._calisiyor:
            self.tik()
            sonraki += periyot
            uyku = sonraki - time.monotonic()
            if uyku > 0:
                time.sleep(uyku)
            else:
                # ⛔ GERİ KALMIŞSAK BİRİKMİŞ TİKLERİ KOVALAMA: sonraki'yi
                #   şimdiye çek. Yoksa sistem yavaşladığında yüzlerce tik
                #   art arda koşar ve durum daha da kötüleşir.
                sonraki = time.monotonic()
