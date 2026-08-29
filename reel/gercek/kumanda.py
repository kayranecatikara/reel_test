# -*- coding: utf-8 -*-
"""
================================================================================
KUMANDA OKUYUCU — RadioMaster (EdgeTX) USB Joystick kipinde
================================================================================
EdgeTX, kumandayı bilgisayara standart bir oyun kolu (HID) gibi tanıtabilir
(SYS -> Hardware -> USB Mode: Joystick). Kullanıcı bu kipi DoW simülatöründe
zaten kullandı, yani yol KANITLI.

⛔ EKSEN SIRASI VARSAYILMAZ — ÖLÇÜLÜR.
   Hangi HID ekseninin hangi kanala denk geldiği; EdgeTX sürümüne, USB
   kipine (Joystick / Gamepad / MultiAxis) ve modelin kanal sırasına göre
   DEĞİŞİR. Yanlış eşleme "throttle verdim, araç yattı" demektir.
   `reel/araclar/kumanda_kalib.py` her ekseni tek tek oynatıp gerçek
   eşlemeyi bulur ve buraya yazılacak haritayı üretir.

⚠ BU DOSYA GÜDÜM DEĞİLDİR. Yalnız pilotun çubuklarını okur. Hakemlik
  (manuel mi otonom mu) `komut.py`'nin işidir.
================================================================================
"""
import os
import time


class KumandaCfg:
    #: HID ekseni -> mantıksal eksen. VARSAYILAN TAHMİNDİR, ölçülecek.
    #: EdgeTX Joystick kipinde kanallar genelde eksen 0..7'ye sırayla düşer;
    #: kanal sırası AETR ise: 0=roll 1=pitch 2=throttle 3=yaw 4..7=AUX
    EKSEN_ROLL     = int(os.environ.get("DOW_KMD_EKS_ROLL", 0))
    EKSEN_PITCH    = int(os.environ.get("DOW_KMD_EKS_PITCH", 1))
    EKSEN_THROTTLE = int(os.environ.get("DOW_KMD_EKS_THR", 2))
    EKSEN_YAW      = int(os.environ.get("DOW_KMD_EKS_YAW", 3))
    EKSEN_ARM      = int(os.environ.get("DOW_KMD_EKS_ARM", 4))      # AUX1/SA
    EKSEN_KIP      = int(os.environ.get("DOW_KMD_EKS_KIP", 5))      # AUX2/SB
    #: İşaret düzeltmeleri (HID ekseni ters gelebilir) — ÖLÇÜLECEK
    TERS_ROLL     = os.environ.get("DOW_KMD_TERS_ROLL", "0") == "1"
    TERS_PITCH    = os.environ.get("DOW_KMD_TERS_PITCH", "0") == "1"
    TERS_THROTTLE = os.environ.get("DOW_KMD_TERS_THR", "0") == "1"
    TERS_YAW      = os.environ.get("DOW_KMD_TERS_YAW", "0") == "1"
    #: Anahtar eşiği: bu değerin üstü "açık" sayılır ([-1,+1] ölçeğinde)
    ANAHTAR_ESIK  = float(os.environ.get("DOW_KMD_ANAHTAR_ESIK", 0.5))
    #: Orta ölü bant — çubuk tam ortada durmuyorsa titremesin
    OLU_BANT      = float(os.environ.get("DOW_KMD_OLU_BANT", 0.02))


class Cubuklar:
    """Tek bir okumanın sonucu."""

    __slots__ = ("throttle", "pitch", "roll", "yaw", "arm", "kip_anahtari",
                 "t", "ham")

    def __init__(self, throttle=0.0, pitch=0.0, roll=0.0, yaw=0.0,
                 arm=False, kip_anahtari=False, t=0.0, ham=None):
        self.throttle = throttle; self.pitch = pitch
        self.roll = roll; self.yaw = yaw
        self.arm = arm; self.kip_anahtari = kip_anahtari
        self.t = t; self.ham = ham or []

    def __repr__(self):
        return ("Cubuklar(thr=%+.3f pitch=%+.3f roll=%+.3f yaw=%+.3f "
                "arm=%s kip=%s)" % (self.throttle, self.pitch, self.roll,
                                    self.yaw, self.arm, self.kip_anahtari))


class Kumanda:
    """EdgeTX kumandasını HID oyun kolu olarak okur.

    ⛔ AÇILIŞTA BAĞLANMAK ZORUNDA DEĞİL. Kumanda takılı değilse `hazir`
       False kalır ve `oku()` None döner. Çağıran buna göre davranır —
       çünkü "kumanda yok" bir hata değil, bir DURUMDUR (ör. tezgâhta
       yalnız otonom sınama).
    """

    def __init__(self, cfg=KumandaCfg, indeks=0):
        self.cfg = cfg
        self.indeks = indeks
        self.hazir = False
        self.ad = ""
        self._js = None
        self._pg = None
        self.n_eksen = 0
        self.son = None
        self.hata = None

    def ac(self):
        try:
            os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
            import pygame
            self._pg = pygame
            pygame.init()
            pygame.joystick.init()
            if pygame.joystick.get_count() <= self.indeks:
                self.hata = ("oyun kolu bulunamadı (bulunan: %d). Kumanda "
                             "açık mı ve USB kipi 'Joystick' mi?"
                             % pygame.joystick.get_count())
                return False
            self._js = pygame.joystick.Joystick(self.indeks)
            self._js.init()
            self.ad = self._js.get_name()
            self.n_eksen = self._js.get_numaxes()
            self.hazir = True
            return True
        except Exception as e:
            self.hata = "%s: %s" % (type(e).__name__, e)
            return False

    def kapat(self):
        try:
            if self._js is not None:
                self._js.quit()
            if self._pg is not None:
                self._pg.joystick.quit()
        except Exception:
            pass
        self.hazir = False

    # ------------------------------------------------------------------
    def _eksen(self, ham, no, ters=False):
        if no < 0 or no >= len(ham):
            return 0.0
        v = float(ham[no])
        if ters:
            v = -v
        if abs(v) < self.cfg.OLU_BANT:
            return 0.0
        return -1.0 if v < -1.0 else (1.0 if v > 1.0 else v)

    def oku(self):
        """Bir okuma. Kumanda yoksa None."""
        if not self.hazir:
            return None
        try:
            self._pg.event.pump()
            ham = [self._js.get_axis(i) for i in range(self.n_eksen)]
        except Exception as e:
            self.hata = "okuma: %s" % e
            self.hazir = False
            return None
        c = self.cfg
        s = Cubuklar(
            throttle=self._eksen(ham, c.EKSEN_THROTTLE, c.TERS_THROTTLE),
            pitch=self._eksen(ham, c.EKSEN_PITCH, c.TERS_PITCH),
            roll=self._eksen(ham, c.EKSEN_ROLL, c.TERS_ROLL),
            yaw=self._eksen(ham, c.EKSEN_YAW, c.TERS_YAW),
            arm=self._eksen(ham, c.EKSEN_ARM) >= c.ANAHTAR_ESIK,
            kip_anahtari=self._eksen(ham, c.EKSEN_KIP) >= c.ANAHTAR_ESIK,
            t=time.monotonic(), ham=ham)
        self.son = s
        return s
