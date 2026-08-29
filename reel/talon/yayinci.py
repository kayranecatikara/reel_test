#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
TALON YAYINCISI — hedef GPS'ini 5 Hz ile drone bilgisayarına yayınlar
================================================================================
TALON BİLGİSAYARINDA çalışır. TEK İŞİ: Talon'un konumunu, GPS güdüm
denklemine girecek biçimde yaymak.

⛔ SERİ PORTU TEK SÜREÇ AÇABİLİR — VE BU BİR TUZAKTIR.
   `talon_arayuz` belgesinde yazılı: "Panel çalışırken başka bir Python
   betiği aynı COM portunu açamaz." Yani yayıncı ile arayüz aynı anda
   telsize bağlanamaz.
   ÇÖZÜM: bu program bir MAVLink DAĞITICISIDIR (hub). Seri portu O açar,
   trafiği yerel bir UDP portuna aynalar. Arayüz artık seri porta değil
   O UDP'ye bağlanır ve HER ŞEY (görev yükleme, RC override, mod
   değiştirme) çalışmaya devam eder.

        [Pixhawk] --SiK--> [seri] --> YAYINCI --+--> udp:14550  (talon_arayuz)
                                                |
                                                +--> udp:47800  (drone bilgisayarı)
                                                     5 Hz hedef paketi

   Arayüzü şöyle başlatın:
        MAV_ENDPOINT=udp:127.0.0.1:14550 ./baslat.sh

⭐ YAYIN BİÇİMİ = YARIŞMA SUNUCUSUNUN BİÇİMİ (haberleşme dokümanı §7.2).
   Böylece drone tarafındaki kod bugün ile yarışma günü arasında HİÇ
   DEĞİŞMEZ; yalnız verinin geldiği adres değişir.

⚠ NİYE 5 Hz: yarışma sunucusu 1-2 Hz veriyor ve o bizim tavanımız değil,
  ONUN sınırı. Denemede daha hızlı veri, GPS güdümünün gerçek yeteneğini
  görmemizi sağlar. Güdüm tarafı her iki hızda da çalışır — `hedef.py`
  paket yaşına bakar, hızına değil.
================================================================================
"""
import argparse
import json
import os
import socket
import sys
import threading
import time


def _port_bul():
    """Seri portu kendi bul. ⛔ Başlatıcı bunu yapıyordu ama `yayinci.py`
    doğrudan çağrılınca yapmıyordu — teşhis sırasında "0 paket" diye
    görünüp zaman kaybettirdi."""
    import glob
    for kalip in ("/dev/serial/by-id/*", "/dev/ttyUSB*", "/dev/ttyACM*"):
        for a in sorted(glob.glob(kalip)):
            return a
    return None


def _arg():
    a = argparse.ArgumentParser(description="Talon hedef yayıncısı + MAVLink hub")
    a.add_argument("--port", default=os.environ.get("MAV_ENDPOINT", ""),
                   help="Pixhawk seri portu (/dev/ttyUSB0, COM3) ya da udp:...")
    a.add_argument("--baud", type=int,
                   default=int(os.environ.get("MAV_BAUD", 57600)))
    a.add_argument("--hedef", default="255.255.255.255",
                   help="drone bilgisayarının IP'si (varsayılan: yayın)")
    a.add_argument("--hedef-port", type=int, default=47800)
    # ⭐ İKİ AYNA ÇIKIŞI — vendorlanan arayüzün KENDİ tasarımı bunu bekliyor:
    #   "UDP köprüsü varsa sorun yok: panel köprünün bir çıkışına (14552),
    #    alt süreç başka bir porta (14550) bağlanır; köprü ikisini de besler."
    #   (gcs/sunucu.py, satır ~1905)
    # ⛔ NİYE ŞART: arayüz uçuş-öncesi kontrolü ve senaryo koşucusunu ALT
    #   SÜREÇ olarak çalıştırıyor. Tek çıkış olsaydı ikisi AYNI UDP portuna
    #   bağlanırdı ve çekirdek her datagramı yalnız BİRİNE verirdi — ikisi de
    #   yarı kör kalırdı. Arayüzün kendi belgesi bu arızayı 18 Ağu 2026'da
    #   yaşadıklarını yazıyor.
    a.add_argument("--ayna", default="udpout:127.0.0.1:14552",
                   help="ARAYÜZÜN bağlanacağı UDP (boş = ayna yok)")
    a.add_argument("--ayna2", default="udpout:127.0.0.1:14550",
                   help="arayüzün ALT SÜREÇLERİNİN bağlanacağı UDP")
    # ⭐ TAVAN, HEDEF DEĞİL. Yayın artık OLAY GÜDÜMLÜ: araçtan yeni konum
    #   geldiği an basılır. Bu sayı yalnız üst sınırdır — ağı gereksiz
    #   doldurmamak için. ÖLÇÜLDÜ: araçtan konum 6.7 Hz geliyor; tavan
    #   5 Hz olsaydı örneklerin ~%25'ini ATARDIK. 10 = "geleni at, hiçbirini
    #   kaybetme" demek. Yerel ağda maliyeti önemsiz (paket ~200 bayt).
    a.add_argument("--hz", type=float, default=10.0,
                   help="yayın TAVANI (olay güdümlü; araç ne verirse o basılır)")
    # ⭐ DARBOĞAZ AĞ DEĞİL, TELSİZ LİNKİDİR.
    #   Yerel ağda paket 1 ms'de gider; asıl gecikme Pixhawk'ın MAVLink
    #   akış hızından ve 57600 baud'luk SiK linkinden gelir. ArduPilot
    #   varsayılanı POSITION akışı için ~3-4 Hz'dir. Aşağıdaki değer
    #   `SET_MESSAGE_INTERVAL` ile araçtan İSTENİR.
    # ⛔ SINIRSIZ İSTEME: 57600 baud ~5.7 kB/s taşır. GLOBAL_POSITION_INT
    #   ~28 bayt + çerçeve ≈ 40 bayt; 10 Hz = 400 B/s, sorun değil. Ama
    #   bütün akışları yükseltmek linki doldurur ve HER ŞEY gecikir.
    #   Bu yüzden YALNIZ konum akışı yükseltilir.
    a.add_argument("--konum-hz", type=float, default=10.0,
                   help="araçtan istenecek GLOBAL_POSITION_INT hızı")
    a.add_argument("--akis-duzenleme-yok", action="store_true",
                   help="gereksiz akışları KISMA (bant genişliği paylaşımı kapalı)")
    a.add_argument("--takim", type=int,
                   default=int(os.environ.get("DOW_TAKIM_NO", 0)))
    a.add_argument("--sahte", action="store_true",
                   help="Pixhawk yok — daire çizen sahte bir Talon yayınla")
    return a.parse_args()


class Yayinci:
    def __init__(self, a):
        self.a = a
        self.sok = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sok.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.durum = {"enlem": None, "boylam": None, "irtifa_ev": None,
                      "hiz": 0.0, "t": 0.0}
        self.n_yayin = 0
        self.n_mavlink = 0
        self.n_konum = 0          # ⭐ GERÇEK tazelik ölçütü
        self._son_yayin = 0.0
        self._min_aralik = 1.0 / max(0.5, float(getattr(a, "hz", 5.0)))
        self._kilit = threading.Lock()

    # ------------------------------------------------------------------
    def guncelle(self, enlem, boylam, irtifa_ev, hiz):
        with self._kilit:
            self.durum.update(enlem=enlem, boylam=boylam,
                              irtifa_ev=irtifa_ev, hiz=hiz,
                              t=time.monotonic())

    def paket(self):
        with self._kilit:
            d = dict(self.durum)
        if d["enlem"] is None:
            return None
        # `saat_farki`: verinin YAŞI, milisaniye. Sunucu bu alanı böyle
        # kullanıyor; aynı anlamı koruyoruz ki drone tarafı ayırt etmesin.
        yas_ms = int(max(0.0, (time.monotonic() - d["t"])) * 1000.0)
        return {"sunucu_saati": _saat(),
                "hedef_iha_verileri": [{
                    "takim_no": self.a.takim,
                    "enlem": round(d["enlem"], 7),
                    "boylam": round(d["boylam"], 7),
                    "irtifa_ev": round(d["irtifa_ev"], 1),
                    "hiz": round(d["hiz"], 1),
                    "saat_farki": yas_ms}]}

    def yayinla(self, olaydan=False):
        """Hedef paketini yolla.

        `olaydan=True`: araçtan YENİ konum geldiği an çağrılır. Tavan
        (`--hz`) aşılmasın diye son yayından bu yana geçen süre denetlenir.
        """
        simdi = time.monotonic()
        if olaydan and (simdi - self._son_yayin) < self._min_aralik:
            return False
        p = self.paket()
        if p is None:
            return False
        self._son_yayin = simdi
        try:
            self.sok.sendto(json.dumps(p).encode("utf-8"),
                            (self.a.hedef, self.a.hedef_port))
            self.n_yayin += 1
            return True
        except Exception:
            return False


def _saat():
    t = time.localtime()
    return {"saat": t.tm_hour, "dakika": t.tm_min, "saniye": t.tm_sec,
            "milisaniye": int((time.time() % 1.0) * 1000)}


def _sahte_dongu(y):
    """Pixhawk yokken: 40 m irtifada, 200 m yarıçaplı daire çizen Talon."""
    import math
    e0, b0 = 41.10500, 29.02300
    R, V = 200.0, 22.0
    t0 = time.time()
    while True:
        t = time.time() - t0
        w = V / R
        x, yy = R * math.cos(w * t), R * math.sin(w * t)
        # yaklaşık: 1° enlem ~ 111 km, 1° boylam ~ 111 km * cos(enlem)
        e = e0 + (x / 111320.0)
        b = b0 + (yy / (111320.0 * math.cos(math.radians(e0))))
        y.guncelle(e, b, 40.0, V)
        time.sleep(0.05)


def main():
    a = _arg()
    print("=" * 70)
    print("  TALON YAYINCISI — hedef GPS'i %g Hz" % a.hz)
    print("=" * 70)
    y = Yayinci(a)

    if a.sahte:
        print("  KAYNAK    : SAHTE (200 m yarıçaplı daire, 22 m/s, 40 m)")
        threading.Thread(target=_sahte_dongu, args=(y,), daemon=True).start()
    else:
        if not a.port:
            a.port = _port_bul()
        if not a.port:
            print("⛔ seri port bulunamadı (Pixhawk / SiK telsizi).")
            print("   ls -l /dev/serial/by-id/   ·   Windows: COM3")
            print("   Donanımsız denemek için: --sahte")
            return 2
        try:
            from pymavlink import mavutil
        except ImportError:
            print("⛔ pymavlink yok:  pip install pymavlink")
            return 2
        print("  KAYNAK    : %s @ %d baud" % (a.port, a.baud))
        try:
            m = (mavutil.mavlink_connection(a.port, baud=a.baud)
                 if not a.port.startswith(("udp", "tcp"))
                 else mavutil.mavlink_connection(a.port))
        except Exception as e:
            print("⛔ bağlanılamadı: %s" % e)
            return 2
        aynalar = []
        for etiket, adres in (("arayüz (GCS_ENDPOINT)", a.ayna),
                              ("alt süreç (MAV_ENDPOINT)", a.ayna2)):
            if not adres:
                continue
            try:
                aynalar.append(mavutil.mavlink_connection(adres, input=False))
                print("  AYNA      : %-24s -> %s" % (adres, etiket))
            except Exception as e:
                print("  AYNA      : ⛔ %s açılamadı (%s)" % (adres, e))
        if not aynalar:
            print("  AYNA      : ⚠ hiç ayna yok — arayüz araca ULAŞAMAZ")
        _akis_iste(m, a.konum_hz, duzenle=not a.akis_duzenleme_yok)
        threading.Thread(target=_mavlink_dongu, args=(y, m, aynalar),
                         daemon=True).start()

    print("  YAYIN     : udp://%s:%d" % (a.hedef, a.hedef_port))
    print("  ⛔ Drone bilgisayarı aynı ağda olmalı. Yayın (broadcast)")
    print("     engelliyse --hedef <drone-ip> ile doğrudan gönder.")
    print("=" * 70)

    periyot = 1.0 / max(0.5, a.hz)
    son_rapor = 0.0
    _basla = time.monotonic()
    try:
        while True:
            t0 = time.monotonic()
            y.yayinla()
            if t0 - son_rapor >= 2.0:
                son_rapor = t0
                d = y.durum
                if d["enlem"] is None:
                    print("  ⚠ GPS bekleniyor... (MAVLink paketi: %d)" % y.n_mavlink)
                else:
                    kon_hz = y.n_konum / max(0.001, time.monotonic() - _basla)
                    print("  %7.4f, %7.4f  irtifa %5.1f m  hız %4.1f m/s   "
                          "| KONUM %.1f Hz  yayın %d  mavlink %d"
                          % (d["enlem"], d["boylam"], d["irtifa_ev"],
                             d["hiz"], kon_hz, y.n_yayin, y.n_mavlink))
                    if kon_hz < a.hz * 0.8:
                        print("     ⚠ araçtan gelen konum (%.1f Hz) yayın "
                              "hızının (%.0f Hz) ALTINDA — yayın aynı konumu "
                              "tekrarlıyor. Telsiz baud'u ya da akış hızı "
                              "sınırlıyor." % (kon_hz, a.hz))
            uyku = periyot - (time.monotonic() - t0)
            time.sleep(uyku if uyku > 0 else 0.0)
    except KeyboardInterrupt:
        print("\n  kapandı.")
    return 0


def _akis_iste(m, hz, duzenle=True):
    """Telemetri linkinin BANT GENİŞLİĞİNİ hedefe göre paylaştır.

    ⛔⛔ DARBOĞAZ AĞ DEĞİL, TELSİZ LİNKİDİR — ÖLÇÜLDÜ (2026-08-29):
       Yerel ağda paket 1 ms'de gider. Ama SiK telsizi 57600 baud
       (~5.7 kB/s ham, gerçekte ~4 kB/s kullanılabilir) ve araç
       VARSAYILAN OLARAK bize hiç işimize yaramayan onlarca akış
       gönderiyor. Ölçülen ilk hâl:

          toplam                72 paket/s  (~2.9 kB/s = linkin ~%70'i)
          GLOBAL_POSITION_INT  3.5 Hz   ← BİZİM 5 Hz YAYINIMIZIN ALTINDA
          MEMINFO              3.7 Hz   ← işe yaramaz
          RAW_IMU              3.6 Hz   ← işe yaramaz
          SCALED_IMU2          3.6 Hz   ← işe yaramaz
          TERRAIN_REPORT       3.8 Hz   ← işe yaramaz
          AOA_SSA              3.8 Hz   ← işe yaramaz
          VIBRATION            3.8 Hz   ← işe yaramaz

       Konum 3.5 Hz iken 5 Hz yayınlamak, paketlerin bir kısmının AYNI
       konumu tekrarlaması demektir — hedef "donmuş" görünür ve güdüm
       eski dünyaya nişan alır.

    ⭐ ÇÖZÜM: ÇÖPÜ KIS, KONUMU AÇ. ArduPilot akışları GRUP grup ayarlanır:
          POSITION  -> GLOBAL_POSITION_INT      ⭐ yükselt
          EXTRA1    -> ATTITUDE                  orta
          EXTRA2    -> VFR_HUD                   düşük
          EXT_STAT  -> GPS_RAW_INT, SYS_STATUS   düşük
          EXTRA3    -> AHRS, VIBRATION, MEMINFO… KIS
          RAW_SENS  -> RAW_IMU, SCALED_IMU…      KIS
          RC_CHAN   -> RC kanalları              KIS
    ⚠ SIFIRLANMAZ, 1 Hz'e İNDİRİLİR: vendorlanan arayüz EKF durumu,
      titreşim ve çit bilgisini gösteriyor; kapatmak onu kör ederdi.
      Gösterim için 1 Hz fazlasıyla yeter.

    İKİ YOL DA DENENİR:
      * SET_MESSAGE_INTERVAL (MAVLink 2, yeni ArduPilot) — mesaj bazlı
      * REQUEST_DATA_STREAM  (eski, akış bazlı)          — yedek
    Eski firmware birinciyi yok sayar; ikincisi her sürümde çalışır.
    """
    from pymavlink import mavutil
    M = mavutil.mavlink
    hz = max(1.0, min(20.0, float(hz)))
    s, b = m.target_system or 1, m.target_component or 1

    # 1) konum akışını mesaj bazlı iste (en kesin yol)
    try:
        m.mav.command_long_send(
            s, b, M.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            M.MAVLINK_MSG_ID_GLOBAL_POSITION_INT, 1e6 / hz, 0, 0, 0, 0, 0)
    except Exception:
        pass

    # 2) grup bazlı bant genişliği paylaşımı
    plan = [(M.MAV_DATA_STREAM_POSITION, int(hz), "konum"),
            (M.MAV_DATA_STREAM_EXTRA1, 4, "duruş"),
            (M.MAV_DATA_STREAM_EXTRA2, 2, "VFR_HUD"),
            (M.MAV_DATA_STREAM_EXTENDED_STATUS, 2, "GPS/sistem")]
    if duzenle:
        plan += [(M.MAV_DATA_STREAM_EXTRA3, 1, "AHRS/titreşim/bellek ⏬"),
                 (M.MAV_DATA_STREAM_RAW_SENSORS, 1, "ham sensör ⏬"),
                 (M.MAV_DATA_STREAM_RC_CHANNELS, 1, "RC kanalları ⏬")]
    for akis, oran, ad in plan:
        try:
            m.mav.request_data_stream_send(s, b, akis, int(oran), 1)
        except Exception:
            pass
        time.sleep(0.05)          # araç isteği sindirsin
    print("  AKIŞ      : konum %.0f Hz istendi%s"
          % (hz, "; gereksiz akışlar 1 Hz'e kısıldı" if duzenle else ""))


def _mavlink_dongu(y, m, aynalar):
    """MAVLink'i oku, hedefi çıkar, aynalara geçir; aynadan geleni araca yolla.

    ⛔ ÇİFT YÖNLÜ: arayüzün gönderdiği komutlar (arm, mod, GÖREV YÜKLEME)
       bu yoldan araca gider. Tek yönlü bir ayna, arayüzü kör bir gösterge
       paneline çevirirdi — görev yükleyemezdi.
    """
    if not isinstance(aynalar, (list, tuple)):
        aynalar = [aynalar] if aynalar is not None else []
    while True:
        msg = m.recv_match(blocking=True, timeout=1.0)
        if msg is None:
            continue
        y.n_mavlink += 1
        # araçtan gelen HER paketi BÜTÜN aynalara geçir
        for ayna in aynalar:
            try:
                ayna.write(msg.get_msgbuf())
            except Exception:
                pass
        tip = msg.get_type()
        if tip == "GLOBAL_POSITION_INT":
            y.n_konum += 1
            # ⚠ `relative_alt` EV (kalkış) seviyesine göredir — şartnamenin
            #   `irtifa_ev` alanı da öyle. `alt` ise AMSL'dir; karıştırmak
            #   arazi kotu kadar sistematik hata verir.
            y.guncelle(msg.lat / 1e7, msg.lon / 1e7,
                       msg.relative_alt / 1000.0,
                       (msg.vx ** 2 + msg.vy ** 2) ** 0.5 / 100.0)
            # ⭐ OLAY GÜDÜMLÜ YAYIN — SAATE GÖRE DEĞİL, VERİ GELİNCE.
            #   Zamanlayıcıyla yayınlamak, en kötü hâlde bir yayın
            #   periyodu (200 ms) kadar BAYAT veri göndermek demektir.
            #   Araçtan konum 6.7 Hz geliyor (ölçüldü); paketi tam o an
            #   basmak gecikmeyi ~0'a indirir.
            #   ⚠ TAVAN VAR: `--hz` üst sınırdır; araç daha hızlı verse
            #     bile ağı gereksiz doldurmayız.
            y.yayinla(olaydan=True)
        elif tip == "VFR_HUD" and y.durum["enlem"] is not None:
            with y._kilit:
                y.durum["hiz"] = float(msg.groundspeed)
        # aynadan (arayüzden / alt süreçten) gelen komutları ARACA geçir
        for ayna in aynalar:
            try:
                for _ in range(8):          # bir tikte birikmiş komutları boşalt
                    g = ayna.recv_match(blocking=False)
                    if g is None:
                        break
                    m.write(g.get_msgbuf())
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
