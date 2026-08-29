#!/usr/bin/env python3
"""
sunucu.py — Talon yer kontrol arayüzü (GCS) sunucusu.

Tarayıcıdan uçağı izlemek, manuel joystick ile uçurmak ve GPS tabanlı
kare/daire/elips görevlerini yükleyip başlatmak için.

Çalıştırma (Windows):
    baslat.bat COM3

ya da elle:
    set MAV_ENDPOINT=COM3
    set MAV_BAUD=57600
    python -m gcs.sunucu

Sonra tarayıcıdan:  http://localhost:8000


MİMARİ NOTU
-----------
Bu sunucu MAVLink bağlantısını sürekli açık tutar ve BAĞLANTIYI TEK BİR THREAD
OKUR (telemetri_dongusu). Başka hiçbir yerde recv_match çağrılmaz — çağrılırsa
ACK'leri, PARAM_VALUE'ları ve görev isteklerini telemetri döngüsünden çalar ve
komutlar sessizce zaman aşımına düşer. mav_common'ın arm()/set_mode() gibi
fonksiyonları kendi recv_match'lerini yaptığı için burada KULLANILAMAZ; onların
yerine komut_arm/komut_mod var.

Gelen yanıtlar Durum üzerindeki posta kutularına bırakılır, isteyen oradan alır:
    COMMAND_ACK   → ack_kaydet   / ack_bekle
    PARAM_VALUE   → param_kaydet / param_bekle
    MISSION_*     → gorev_mesaj_kaydet / gorev_mesaj_al

RC OVERRIDE ÜRETEN İKİ KAYNAK VAR ve aynı anda ikisi birden çalışamaz:
joystick ve (arayüz dışından başlatılan) senaryolar. Ayrıca bu uçakta
STICK_MIXING = 1 olduğu için RC override AUTO modundaki görev uçuşuna da
karışır — bu yüzden AUTO'dayken joystick açılması reddedilir.
"""

import collections
import math
import os
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory

from gcs import markdown_basit
from control.mav_common import (
    ARAYUZ_SOURCE_COMPONENT,
    GCSKeepalive,
    clear_rc_overrides,
    connect_mavlink,
    PLANE_MODE_NAMES,
)
from control.sekil_geometri import (
    SEKILLER, _arac_oku, inis_plani, plan_uret,
)
from control.sekil_gorev import MAV_GOREV_ADLARI, gorev_ogeleri
from pymavlink import mavutil

PROJE_KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__,
            static_folder=os.path.join(os.path.dirname(__file__), "static"))

# Ad -> mod numarası
MOD_ADLARI = {ad.lower(): num for num, ad in PLANE_MODE_NAMES.items()}

# Panelde gösterilecek mod butonları — hepsi değil, sahada kullanılanlar.
PANEL_MODLARI = ("manual", "fbwa", "loiter", "auto", "rtl")

# COMMAND_ACK sonuç kodları. Araç ARM'ı reddettiğinde arayüzde çıplak bir sayı
# yerine ne olduğunu yazabilmek için.
MAV_SONUC_ADLARI = {
    0: "kabul edildi",
    1: "geçici olarak reddedildi (araç şu an uygun durumda değil)",
    2: "reddedildi (koşullar sağlanmıyor)",
    3: "desteklenmiyor",
    4: "başarısız (komut kabul edildi ama uygulanamadı)",
    5: "sürüyor",
    6: "iptal edildi",
    None: "araç yanıt vermedi (zaman aşımı)",
}

# Uçuş eşikleri araçtan okunur, arayüze sabit gömülmez. Failsafe ve çit
# değerleri kartta değişirse panel kendiliğinden doğru sınırları uygular;
# gömülü sayı kartla sessizce ayrışır ve sahada yanlış güven verir.
ESIK_PARAMLARI = (
    "BATT_LOW_VOLT", "BATT_CRT_VOLT",
    "FENCE_ALT_MAX", "FENCE_RADIUS", "FENCE_MARGIN",
    "RTL_ALTITUDE", "TKOFF_ALT",
    # Şekil denetimi bunlara bakar: kabul yarıçapı, dönüş yarıçapı, daire
    # varsayılanı. sekil_geometri okunamayanı kendi varsayılanına düşürür.
    "WP_RADIUS", "WP_LOITER_RAD", "AIRSPEED_CRUISE", "ROLL_LIMIT_DEG",
    # İniş paterni bunlardan üretilir. Kasten AUTOLAND modunun parametreleri:
    # göreve gömülen iniş ile AUTOLAND butonunun uçtuğu iniş aynı olsun.
    "AUTOLAND_WP_ALT", "AUTOLAND_WP_DIST",
    # Batarya failsafe'inin NE YAPACAĞI. Panel "2. kademede otomatik iniş"
    # yazacaksa bunu karttan doğrulamalı — 1 (RTL) ile 7 (AUTOLAND) arasındaki
    # fark, uçağın inmesi ile bataryası bitene kadar çember çizmesi arasındaki
    # farktır.
    "BATT_FS_LOW_ACT", "BATT_FS_CRT_ACT",
    # RTL'in ne yapacağını bu belirler. 0 = eve gel ve sonsuza kadar çember çiz;
    # 1/2 = görevde DO_LAND_START varsa in. Arayüz RTL butonunun etiketini
    # buna göre değiştirir — pilot butona basmadan ne olacağını bilmeli.
    "RTL_AUTOLAND",
)

# Uçağın "havada" sayıldığı göreli irtifa. Havadaki uçağa yer kalkışı
# uygulanmaz; run_plane_scenario'nun devralma mantığıyla aynı eşik.
HAVADA_IRTIFA = 15.0


# ---------------------------------------------------------------------------
# Paylaşılan durum
# ---------------------------------------------------------------------------

class Durum:
    """
    Thread'ler arası paylaşılan durum.

    telemetri_dongusu yazar, Flask istekleri okur. Araçtan gelen tek seferlik
    yanıtlar (ACK, parametre, görev mesajları) burada posta kutusuna bırakılır.
    """

    def __init__(self):
        self.kilit = threading.Lock()
        self.telemetri = {
            "bagli": False,
            "armli": None,
            "mod": None,
            "mod_no": None,
            "lat": None, "lon": None,
            "irtifa": None,
            "yon": None,
            "roll": None, "pitch": None, "yaw": None,
            "hiz": None,
            # Uçağın GERÇEK gaz yüzdesi (VFR_HUD.throttle). Aşağıdaki
            # "throttle" alanıyla karıştırılmasın: o, panelin joystick
            # sürgüsünün PWM değeri ve araçtan gelmiyor.
            "gaz_yuzde": None,
            # Kumandadan gelen ham kanal PWM'leri. Arm reddi ("RC1 is not
            # neutral") gibi durumlarda çubuğun NEREDE olduğunu görmenin
            # tek yolu bu; araç bunu RC_CHANNELS ile bildiriyor.
            "rc": None,
            "gps_fix": None, "uydu": None,
            "voltaj": None, "batarya_yuzde": None,
            "ev_lat": None, "ev_lon": None, "ev_irtifa": None,
            # ArduPilot'un kalkışta yakaladığı iniş yönü (derece) — AUTOLAND
            # bunsuz çalışmaz. Disarm'da temizlenir.
            "inis_yonu": None,
            # SiK telsizin kendi ürettiği link sağlığı (RADIO_STATUS).
            # link_tampon = telsizin gönderim tamponunda KALAN yüzde. 100'ün
            # altına inmesi linkin doyduğunu, yani gecikmenin telsizde
            # biriktiğini gösterir — joystick gecikmesinin asıl ölçüsü budur.
            # USB/UDP bağlantıda bu mesaj hiç gelmez, alanlar None kalır.
            "link_rssi": None, "link_uzak_rssi": None,
            "link_gurultu": None, "link_uzak_gurultu": None,
            "link_tampon": None, "link_kayip": None, "link_duzeltilen": None,
            "link_zaman": None,
            # Joystick uplink'inin ÖLÇÜLEN hızı (paket/sn). Sabit 20 değil:
            # değişmeyen komut gönderilmiyor, bu alan gerçekte ne aktığını
            # gösterir.
            "joy_hz": None,
            "son_mesaj": None,
            "guncelleme": 0,
        }
        self.paramlar = {}
        self.param_zaman = {}
        self.ackler = {}
        self.esikler = {}

        # Araçtan gelen STATUSTEXT geçmişi. ÖNCEDEN yalnızca son mesaj
        # tutuluyordu; ARM reddedildiğinde ArduPilot'un yazdığı gerekçe
        # ("PreArm: ...") bir sonraki mesaj gelir gelmez kayboluyordu ve
        # sahada arm'ın neden olmadığı anlaşılamıyordu.
        self.mesajlar = collections.deque(maxlen=120)

        # Joystick: aktifse sürekli RC override gönderilir. İki ayrı sözlük:
        #   joystick       → tarayıcıdan gelen HEDEF değer (gürültülü)
        #   joystick_cikis → araca giden YUMUŞATILMIŞ değer
        # Fare/dokunmatik her piksel hareketinde yeni değer üretir ve HTTP
        # üzerinden düzensiz aralıklarla gelir; servo her sıçramayı takip
        # etmeye çalışınca titrer.
        self.joystick_aktif = False
        self.joystick = {"roll": 0, "pitch": 0, "yaw": 0, "throttle": 0}
        self.joystick_cikis = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0,
                               "throttle": 0.0}
        self.joystick_son_komut = 0.0
        self.throttle = 600

        # AUTOTUNE aux fonksiyonu açık mı. Araç bunu telemetride bildirmiyor,
        # bu yüzden panelin gönderdiği son KABUL EDİLEN komuttan izleniyor.
        # Kanala atanmış fiziksel switch olmadığı için (kumanda 6 kanal, boş
        # kanal yok) bu değeri ezecek bir RC girdisi de yok.
        self.autotune_aktif = False

        # Görev durumu. "noktalar" burada TUTULMAZ — telemetri her 200 ms'de
        # okunuyor, 20 noktayı her seferinde göndermek gereksiz.
        self.gorev = {
            "sekil": None, "yontem": None, "oge_sayisi": 0,
            "ilk_sekil_seq": None, "irtifa": None, "tur": None,
            "yuklendi": None, "hata": None,
            "aktif_seq": None, "ulasilan": None,
            "inis_var": False,
        }
        self.gorev_plan = None          # son üretilen plan (noktalar dahil)

        # Görev protokolü posta kutusu. Kendi kilidi var: yükleme sırasında
        # dakikalarca beklenebiliyor, self.kilit'i o kadar tutmak telemetriyi
        # durdururdu.
        self.gorev_kosul = threading.Condition()
        self.gorev_kutusu = collections.deque(maxlen=128)

        # run_plane_scenario'nun HTTP ile okuduğu eski şekil ayarları.
        # Arayüz artık kullanmıyor ama CLI senaryoları bozulmasın diye duruyor.
        self.sekil = {"kare_kenar": 4.0, "donus_yatis": 400, "daire_yatis": 400}

    # --- telemetri ---------------------------------------------------------

    def guncelle(self, **kw):
        with self.kilit:
            self.telemetri.update(kw)
            self.telemetri["guncelleme"] = time.time()

    def oku(self):
        with self.kilit:
            return dict(self.telemetri)

    # --- komut yanıtları ---------------------------------------------------

    def ack_kaydet(self, komut, sonuc):
        with self.kilit:
            self.ackler[komut] = (sonuc, time.time())

    def ack_bekle(self, komut, timeout=3.0):
        """
        Belirli bir komutun ACK'ini bekler.

        Bu bağlantıyı tek bir thread okur; başka yerde recv_match çağırmak
        ACK'leri ondan çalar. Komutlar bu yüzden ACK'i buradan bekler.
        """
        t0 = time.time()
        while time.time() - t0 < timeout:
            with self.kilit:
                kayit = self.ackler.get(komut)
                if kayit and kayit[1] >= t0:   # t0'dan ESKİ ACK sayılmaz
                    return kayit[0]
            time.sleep(0.05)
        return None

    def param_kaydet(self, ad, deger):
        with self.kilit:
            self.paramlar[ad] = deger
            self.param_zaman[ad] = time.time()

    def param_bekle(self, ad, t0, timeout=3.0):
        while time.time() - t0 < timeout:
            with self.kilit:
                if self.param_zaman.get(ad, 0) >= t0 and ad in self.paramlar:
                    return self.paramlar[ad]
            time.sleep(0.05)
        return None

    # --- mesajlar ----------------------------------------------------------

    def mesaj_ekle(self, metin, severity):
        """
        Araçtan gelen bir STATUSTEXT'i geçmişe yazar.

        ArduPilot aynı uyarıyı saniyede birkaç kez tekrarlar. Aynı metin arka
        arkaya gelirse yeni satır açmak yerine sayacı artırıyoruz; yoksa geçmiş
        tek bir uyarıyla dolar ve asıl gerekçe kayar.
        """
        with self.kilit:
            if self.mesajlar and self.mesajlar[-1]["metin"] == metin:
                self.mesajlar[-1]["adet"] += 1
                self.mesajlar[-1]["t"] = time.time()
                return
            self.mesajlar.append({"t": time.time(), "sev": int(severity),
                                  "metin": metin, "adet": 1})

    def mesajlar_sonrasi(self, t0):
        """t0'dan SONRA gelen mesajlar — komut gerekçesini ayıklamak için."""
        with self.kilit:
            return [dict(m) for m in self.mesajlar if m["t"] >= t0]

    # --- görev posta kutusu ------------------------------------------------

    def gorev_mesaj_kaydet(self, msg):
        with self.gorev_kosul:
            self.gorev_kutusu.append((msg.get_type(), msg))
            self.gorev_kosul.notify_all()

    def gorev_kutusu_temizle(self):
        with self.gorev_kosul:
            self.gorev_kutusu.clear()

    def gorev_mesaj_al(self, tipler, timeout):
        """Kuyruktan istenen tipteki ilk mesajı alır (tüketir)."""
        son = time.time() + timeout
        with self.gorev_kosul:
            while True:
                while self.gorev_kutusu:
                    tip, msg = self.gorev_kutusu.popleft()
                    if tip in tipler:
                        return msg
                kalan = son - time.time()
                if kalan <= 0:
                    return None
                self.gorev_kosul.wait(kalan)

    def gorev_ilerleme(self, aktif_seq=None, ulasilan=None):
        with self.kilit:
            if aktif_seq is not None:
                self.gorev["aktif_seq"] = int(aktif_seq)
            if ulasilan is not None:
                self.gorev["ulasilan"] = int(ulasilan)


durum = Durum()
conn = None
keepalive = None
MAV_HEDEF = None

# Alt süreçlerin (preflight, CLI senaryoları) bağlanacağı MAVLink adresi.
#
# NEDEN AYRI TUTULUYOR: main() içinde GCS_ENDPOINT, os.environ["MAV_ENDPOINT"]
# üzerine yazılıyor. Alt süreç ortamı olduğu gibi kopyaladığı için arayüzün
# portuna bağlanıyordu — iki süreç aynı UDP portunu bind edince paketler
# aralarında bölünüyor ve PARAM_VALUE gibi TEK SEFERLİK mesajlar kayboluyordu.
# (11 Ağu 2026, SITL: uzak komut "durdur" ulaşmadı.)
SENARYO_ENDPOINT = None

# Görev yükleme protokolü tek uçuculudur: app.run(threaded=True) olduğu için
# iki tarayıcı sekmesi aynı anda yüklemeye kalkarsa araç
# MAV_MISSION_INVALID_SEQUENCE döner.
GOREV_KILIDI = threading.Lock()


def _arac_hazir():
    return conn is not None and keepalive is not None


def _arac_gerekli_hatasi():
    if _arac_hazir():
        return None
    return jsonify({
        "ok": False,
        "hata": "Araç bağlı değil — Pixhawk/MAVLink bekleniyor",
    }), 503


def _overridelari_birak():
    if conn is not None:
        clear_rc_overrides(conn)


def _joysticki_kapat():
    """Joystick'i kapatıp override'ı iki kez bırakır."""
    durum.joystick_aktif = False
    durum.joystick = {"roll": 0, "pitch": 0, "yaw": 0, "throttle": 0}
    durum.joystick_cikis = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0,
                            "throttle": 0.0}
    # İki kez: tek bir UDP paketi kaybolabilir ve override asılı kalır.
    _overridelari_birak()
    time.sleep(0.15)
    _overridelari_birak()


def _parametre_oku(ad, timeout=3.0):
    """Tek bir parametreyi araçtan okur (float döner, okunamazsa None)."""
    if conn is None:
        return None
    t0 = time.time()
    conn.mav.param_request_read_send(
        conn.target_system, conn.target_component, ad.encode(), -1)
    return durum.param_bekle(ad, t0, timeout=timeout)


def _esikleri_oku():
    """
    Uçuş eşiklerini araçtan okuyup durum.esikler'e yazar.

    Bağlantı kurulunca ayrı bir thread'de çağrılır: parametreler sırayla
    okunuyor ve bu saniyeler sürebilir; bağlantı döngüsü bekletilmemeli.
    """
    okunan = {}
    for ad in ESIK_PARAMLARI:
        deger = _parametre_oku(ad, timeout=4.0)
        if deger is not None:
            okunan[ad] = round(float(deger), 3)
    durum.esikler = okunan
    eksik = [a for a in ESIK_PARAMLARI if a not in okunan]
    print(f"[GCS] Uçuş eşikleri okundu: {okunan}"
          + (f" — OKUNAMAYAN: {eksik}" if eksik else ""))


# Panelin gerçekten kullandığı mesajlar ve istenen hızları (Hz).
#
# NEDEN mav_common.request_default_streams KULLANILMIYOR: o fonksiyon
# MAV_DATA_STREAM_ALL'ı 10 Hz istiyor ve araç saniyede ~217 mesaj yolluyor.
# Senaryolar için doğru (pusula tabanlı dönüş ATTITUDE'a bağlı), arayüz için
# değil — panel telemetriyi saniyede 4 kez okuyor.
#
# İki somut zarar ölçüldü/öngörüldü:
#   1. SITL testinde arayüz bu akışa yetişemedi ve bağlantı ~22 saniyede bir
#      koptu (90 saniyede 4 kez). Aynı anda 14551'i dinleyen çıplak istemci
#      hiç boşluk görmüyordu — yük arayüzün kendi döngüsündeydi.
#   2. Gerçek uçuşta SiK telsiz 57600 baud ≈ 5.7 KB/s taşır. 217 mesaj/sn
#      yaklaşık 8.7 KB/s eder; link doyar ve komutlar geçmez.
ARAYUZ_AKISLARI = (
    ("ATTITUDE", 5.0),               # yapay ufuk + 3B panelde uçağın duruşu
    ("GLOBAL_POSITION_INT", 5.0),    # konum, irtifa, yön — izin çözünürlüğü
    ("VFR_HUD", 2.0),                # yer hızı + gaz yüzdesi
    ("RC_CHANNELS", 4.0),            # çubuk konumları (arm reddi teşhisi)
    ("GPS_RAW_INT", 1.0),            # fix + uydu sayısı
    ("SYS_STATUS", 1.0),             # batarya
    ("MISSION_CURRENT", 1.0),        # görev ilerlemesi (aktif öğe)
)


# DAR BANT tablosu — SiK telsiz üzerinden bağlıyken kullanılır.
#
# Yukarıdaki tablo ~520 B/s indirme ister. SiK 57600'ün gerçek kapasitesi
# ~2500-3500 B/s ve YARI ÇİFT YÖNLÜ: indirme ile joystick uplink'i aynı hava
# zamanını paylaşır. Manuel uçarken önemli olan komutun çabuk gitmesi, 3B
# panelin akıcı olması değil. Bu tablo indirmeyi ~288 B/s'ye çekip kalan hava
# zamanını komuta bırakır.
ARAYUZ_AKISLARI_DAR = (
    ("ATTITUDE", 4.0),               # yapay ufuk — 4 Hz elle uçmaya yeter
    ("GLOBAL_POSITION_INT", 2.0),    # konum/irtifa — iz biraz köşeli olur
    ("VFR_HUD", 2.0),               # gaz yüzdesi de buradan; 1 Hz çok kaba
    ("RC_CHANNELS", 2.0),           # ~110 B/s — susturmayla açılan payın içinde
    ("GPS_RAW_INT", 0.5),
    ("SYS_STATUS", 0.5),
    ("MISSION_CURRENT", 0.5),
)


def _dar_bant_mi():
    """
    Bağlantı SiK gibi dar bantlı bir telsiz mi?

    Ayrım seri/UDP değil BAUD üzerinden yapılıyor: doğrudan USB bağlantısı da
    seridir ama yüksek baud'dur ve hiçbir darlığı yoktur. Asıl fark hızda.
    """
    hedef = (MAV_HEDEF or "").lower()
    if hedef.startswith(("udp", "tcp")):
        return False
    try:
        return int(os.environ.get("MAV_BAUD", "57600")) <= 115200
    except ValueError:
        return False


# DAR BANTTA SUSTURULACAK MESAJLAR.
#
# NEDEN GEREKLİ: SET_MESSAGE_INTERVAL yalnızca ADI GEÇEN mesajı etkiler.
# Aşağıdaki tabloyu istemek, araca ZATEN akmakta olan başka hiçbir şeyi
# durdurmaz — ne MAVn_* parametrelerinin varsayılanlarını, ne de başka bir
# aracın (Mission Planner, MAVProxy, mav_common.request_default_streams)
# bu kanala daha önce yaptığı REQUEST_DATA_STREAM isteğini.
#
# 22 Ağu 2026, GERÇEK SiK LİNKİNDE ÖLÇÜLDÜ: araç bu kanala 4502 B/s
# yolluyordu ve bunun 4000 B/s'i (%89) panelin hiç okumadığı mesajlardı.
# SiK 57600'ün çift yönlü gerçek kapasitesi ~2500-3500 B/s; link %150 aşırı
# yüklüydü. Sonuç yavaşlama değil, UPLINK'İN PRATİKTE ÖLMESİYDİ: 60 saniyede
# 62 parametre isteği gönderildi, 0 yanıt geldi. Yani panelden verilen RTL,
# mod değişikliği ve joystick komutları araca ulaşmıyordu.
#
# Bunlar SET_MESSAGE_INTERVAL param2=-1 ile susturuluyor: ÇALIŞMA ZAMANI
# ayarıdır, parametre yazmaz, YALNIZCA BU KANALI etkiler ve araç yeniden
# başlayınca kendiliğinden geri gelir.
#
# YALNIZCA DAR BANTTA yapılıyor. Bir UDP köprüsü üzerinden tüm istemciler AYNI
# kanalı paylaşır; orada susturmak CLI araçlarının (run_plane_scenario
# ATTITUDE'a, servo araçları SERVO_OUTPUT_RAW'a bakar) verisini keserdi.
SUSTURULACAK = (
    # ham sensörler — panel hiçbirini göstermiyor
    "RAW_IMU", "SCALED_IMU2", "SCALED_IMU3", "SENSOR_OFFSETS",
    "SCALED_PRESSURE", "SCALED_PRESSURE2", "SCALED_PRESSURE3",
    "AHRS", "AHRS2", "AHRS3", "EKF_STATUS_REPORT", "VIBRATION", "SIMSTATE",
    # durum/teşhis — panel otopilot mesajlarından okuyor
    "MEMINFO", "POWER_STATUS", "HWSTATUS", "SYSTEM_TIME",
    # navigasyon iç durumu — 3B panel kendi hesabını yapıyor
    "NAV_CONTROLLER_OUTPUT", "POSITION_TARGET_GLOBAL_INT",
    "LOCAL_POSITION_NED", "GLOBAL_POSITION_INT_COV", "ATTITUDE_QUATERNION",
    "TERRAIN_REPORT", "TERRAIN_REQUEST", "WIND", "FENCE_STATUS",
    # çıkış/giriş — panel joystick'i kendi gönderiyor, geri okumuyor
    "SERVO_OUTPUT_RAW", "RC_CHANNELS_RAW", 
    # batarya: panel SYS_STATUS'tan okuyor, BATTERY_STATUS fazladan
    "BATTERY_STATUS", "GPS2_RAW",
)

# Numara ile susturulanlar. İkisi de MAVLink v2 mesajı (ID > 255): bağlantımız
# v1 lehçesiyle kurulduğu için mavutil.mavlink bunların adını çözemiyor, ama
# SET_MESSAGE_INTERVAL'e ID sayı olarak gittiğinden susturmak sorunsuz çalışır.
# Araç v2 çerçeve yolluyor (SERIAL1_PROTOCOL = 2), o yüzden gerçekten geliyorlar.
SUSTURULACAK_ID = (
    11020,   # AOA_SSA                — ölçümde 108 B/s
    11030,   # ESC_TELEMETRY_1_TO_4
    11039,   # MCU_STATUS
    295,     # ölçümde UNKNOWN_295 olarak görüldü — 163 B/s
)


# Susturma komutu KAYBOLABİLİR. Dar bantlı linkte bir SET_MESSAGE_INTERVAL
# yolda kaybolursa o akış susmadan akmaya devam eder ve sessizce bant yer.
#
# 22 Ağu 2026, gerçek SiK linkinde görüldü: 35 komutluk turdan sonra
# SYSTEM_TIME hâlâ 164 B/s ile geliyordu — tek bir komut düşmüştü.
#
# Çare: susturulmuş bir mesaj YİNE DE gelirse komutu tekrarla. Telemetri
# döngüsü zaten her mesajı görüyor, ek maliyeti yok ve kendi kendini onarır.
# Mesaj başına en fazla 5 saniyede bir tekrar — akış hâlâ akarken komut
# yağmuruna tutmamak için.
SUSTUR_TEKRAR_SN = 5.0
_sustur_idler = {}          # mesaj adı -> id (bağlantı kurulunca dolar)
_sustur_son = {}            # mesaj adı -> son tekrar zamanı


def _mesaji_sustur(msg_id):
    """SET_MESSAGE_INTERVAL param2=-1 -> bu mesajı bu kanalda kapat."""
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
        msg_id, -1, 0, 0, 0, 0, 0)


def _inatci_akisi_sustur(tip, simdi):
    """Susturulmuş olması gereken bir mesaj geldiyse komutu tekrarla."""
    msg_id = _sustur_idler.get(tip)
    if msg_id is None or conn is None:
        return
    if simdi - _sustur_son.get(tip, 0.0) < SUSTUR_TEKRAR_SN:
        return
    _sustur_son[tip] = simdi
    try:
        _mesaji_sustur(msg_id)
        print(f"[GCS] {tip} hâlâ geliyor — susturma tekrarlandı")
    except Exception:
        pass


def _akislari_iste():
    """
    Yalnızca panelin gösterdiği mesajları, gösterdiği hızda ister.

    STATUSTEXT, COMMAND_ACK, PARAM_VALUE ve MISSION_* akış değil olay
    mesajlarıdır; istenmelerine gerek yok, araç kendiliğinden yollar.
    """
    if conn is None:
        return
    dar = _dar_bant_mi()
    tablo = ARAYUZ_AKISLARI_DAR if dar else ARAYUZ_AKISLARI

    if dar:
        # ÖNCE SUSTUR, SONRA İSTE. Sırası önemli: susturma linki boşaltır,
        # boşalan linkte istek komutları gerçekten karşıya geçer.
        _sustur_idler.clear()
        _sustur_son.clear()
        susturuldu = 0
        for ad in SUSTURULACAK:
            msg_id = getattr(mavutil.mavlink, f"MAVLINK_MSG_ID_{ad}", None)
            if msg_id is None:
                continue
            _sustur_idler[ad] = msg_id      # kaybolursa tekrar gönderebilelim
            try:
                _mesaji_sustur(msg_id)
                susturuldu += 1
                time.sleep(0.02)
            except Exception as exc:
                print(f"[GCS] {ad} susturulamadı: {exc}")
                break
        for msg_id in SUSTURULACAK_ID:
            try:
                _mesaji_sustur(msg_id)
                susturuldu += 1
                time.sleep(0.02)
            except Exception:
                pass
        print(f"[GCS] Dar bant: {susturuldu} gereksiz akış susturuldu "
              f"(panelin okumadığı ~4000 B/s)")

    for ad, hz in tablo:
        msg_id = getattr(mavutil.mavlink, f"MAVLINK_MSG_ID_{ad}", None)
        if msg_id is None:
            continue
        try:
            conn.mav.command_long_send(
                conn.target_system, conn.target_component,
                mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
                msg_id, int(1e6 / hz), 0, 0, 0, 0, 0)
            time.sleep(0.02)
        except Exception as exc:
            print(f"[GCS] {ad} akışı istenemedi: {exc}")
            return
    print(f"[GCS] Panel akışları istendi ({len(tablo)} mesaj, en yüksek "
          f"{max(h for _, h in tablo):g} Hz"
          + (" — DAR BANT profili: telsiz linki algılandı)" if dar
             else ")"))


def _baglanti_sonrasi_tazele():
    """
    Araca bağlı her şeyi yeniden ister: akışlar, uçuş eşikleri, ev konumu.

    Hem ilk bağlantıda hem uzun sessizlik sonrasında çağrılır. Tek fonksiyon
    olması bilinçli — iki yerde ayrı ayrı yazılırsa biri güncellenip diğeri
    unutulur ve panel eski aracın eşikleriyle çalışmaya devam eder.
    """
    _akislari_iste()
    _esikleri_oku()
    _ev_konumu_iste()


def _ev_konumu_iste():
    """
    Kalkış (home) noktasını araçtan ister.

    Şekiller varsayılan olarak kalkış noktasına göre planlanıyor ve güvenlik
    çemberi denetimi de eve olan uzaklığa bakıyor; ev bilinmezse ikisi de
    yapılamaz. HOME_POSITION kendiliğinden akmaz, istenmesi gerekir.
    """
    if conn is None:
        return
    try:
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_CMD_REQUEST_MESSAGE, 0,
            float(mavutil.mavlink.MAVLINK_MSG_ID_HOME_POSITION),
            0, 0, 0, 0, 0, 0)
    except Exception as exc:
        print(f"[GCS] Ev konumu istenemedi: {exc}")


# ---------------------------------------------------------------------------
# Bağlantı
# ---------------------------------------------------------------------------

def _baglantiyi_kapat(beklenen_conn=None):
    """
    Mevcut MAVLink bağlantısını bırakır.

    telemetri_dongusu eski bağlantıda hata görürken bu sırada yeni bağlantı
    kurulmuş olabilir; beklenen_conn verilirse yalnızca o bağlantıyı kapatır.
    """
    global conn, keepalive

    if beklenen_conn is not None and conn is not beklenen_conn:
        return

    eski_conn, eski_keepalive = conn, keepalive
    conn = None
    keepalive = None
    durum.guncelle(bagli=False)

    if eski_keepalive is not None:
        eski_keepalive.stop(join_timeout=0.5)
    if eski_conn is not None:
        try:
            eski_conn.close()
        except Exception:
            pass


def baglanti_dongusu():
    """
    Aracı arka planda bağlar.

    Arayüz her durumda açılır; Pixhawk bağlı değilse web paneli yine gelir ve
    bağlantı arka planda beklenir. Montaj/ayar işlerinde bu kritik.
    """
    global conn, keepalive

    while True:
        if conn is not None:
            time.sleep(1.0)
            continue
        yeni_conn = None
        try:
            print(f"[GCS] MAVLink bekleniyor: {MAV_HEDEF}")
            # request_streams=False: mav_common'ın varsayılanı MAV_DATA_STREAM_ALL'ı
            # 10 Hz ister (senaryolar için doğru, panel için fazla). Arayüz kendi
            # ölçülü listesini istiyor — bkz. ARAYUZ_AKISLARI.
            yeni_conn = connect_mavlink(
                heartbeat_timeout=8.0,
                source_component=ARAYUZ_SOURCE_COMPONENT,
                request_streams=False,
            )
            yeni_keepalive = GCSKeepalive(yeni_conn, interval=0.5)
            yeni_keepalive.start()
            conn = yeni_conn
            keepalive = yeni_keepalive
            print("[GCS] MAVLink bağlandı")

            threading.Thread(target=_baglanti_sonrasi_tazele,
                             daemon=True).start()
        except Exception as exc:
            # BAŞARISIZ DENEMENİN SOKETİ KAPATILMALI.
            #
            # connect_mavlink önce portu bind eder, SONRA heartbeat bekler.
            # Araç yokken bekleme 8 saniyede zaman aşımına düşer ve istisna
            # fırlar; soket kapatılmazsa bind edilmiş halde sızar. Her denemede
            # bir tane daha sızar ve hepsi AYNI UDP portuna bağlı kalır.
            #
            # Sonuç sinsi: çekirdek aynı porta bağlı soketlerden gelen her
            # datagramı yalnızca BİRİNE verir. Canlı bağlantı, ölü soketlerle
            # datagram paylaşmaya başlar ve telemetri rastgele "susar" —
            # arayüz "bağlantı yok" gösterir, oysa araç yayın yapmaktadır.
            # (18 Ağu 2026, SITL'de `ss -ulpn` ile tek süreçte 14552'ye bağlı
            # iki soket görülerek bulundu.)
            if yeni_conn is not None:
                try:
                    yeni_conn.close()
                except Exception:
                    pass
            durum.guncelle(bagli=False)
            print(f"[GCS] MAVLink bekleniyor ({exc})")
            time.sleep(2.0)


# ---------------------------------------------------------------------------
# MAVLink okuma thread'i — bağlantıyı SADECE bu thread okur
# ---------------------------------------------------------------------------

GOREV_MESAJLARI = ("MISSION_REQUEST", "MISSION_REQUEST_INT",
                   "MISSION_ACK", "MISSION_COUNT")


# Kaç saniye mesaj gelmezse panelde "bağlı değil" gösterilir.
#
# SÜRE AŞIMINDA SOKET KAPATILMAZ. Bir ara kapatılıyordu ("UDP'de karşı taraf
# susunca istisna oluşmaz, o yüzden yeniden bağlanalım" gerekçesiyle); bu
# yanlıştı ve kaldırıldı. İki sebep:
#
#   1. Gereksiz. Soket bind edilmiş ve pasif bekliyor; köprü/SITL geri gelince
#      aynı porta yazmaya devam eder, akış kendiliğinden düzelir. Gerçekten
#      kopan tek durum seri porttur (kablo çekilmesi) ve o zaten recv_match'te
#      istisna fırlatıp _baglantiyi_kapat'ı çalıştırır.
#   2. Kapat-yeniden-bağla döngüsü, asıl arızayı (aşağıda) maskeliyordu.
#
# ASIL ARIZA — telemetrinin rastgele "susmasının" sebebi buydu (18 Ağu 2026,
# SITL): AYNI UDP PORTUNA BAĞLI BİRDEN FAZLA SOKET. Çekirdek, aynı porta bağlı
# soketlerden gelen her datagramı yalnızca birine verir; diğerleri sessizlik
# görür. İki kaynağı vardı:
#   * Başarısız connect_mavlink denemelerinin sızdırdığı soketler
#     (bkz. baglanti_dongusu'ndaki except bloğu — düzeltildi).
#   * Aynı GCS_ENDPOINT ile çalışan İKİNCİ bir arayüz örneği. systemd
#     `talon-arayuz` zaten çalışırken elle ikinci bir örnek başlatmak buna yol
#     açar. Test için ikinci örnek çalıştıracaksanız GCS_PORT'u değiştirmek
#     YETMEZ, GCS_ENDPOINT'i de değiştirin (örn. udp:127.0.0.1:14553) —
#     yoksa iki örnek aynı telemetriyi bölüşür ve ikisi de yarı kör kalır.
VERI_YOK_KOPUK = 3.0

# Uzun bir sessizlikten sonra veri dönerse ARACIN DEĞİŞMİŞ OLABİLECEĞİNİ kabul
# edip araca bağlı her şeyi tazeliyoruz — soketi kapatmadan.
#
# NEDEN GEREKLİ: soketi kapatmadığımız için baglanti_dongusu bir daha çalışmaz;
# _esikleri_oku ve _ev_konumu_iste orada, yani "bağlantı kurulurken bir kez"
# çağrılıyor. Köprü yeniden başlarsa ya da SITL'den gerçek uçağa geçilirse
# telemetri kendiliğinden düzelir ama EŞİKLER ESKİ ARACINKİ kalır.
#
# Bu sessiz ve tehlikeli bir hata: şekil denetleyicisi ROLL_TIMIT/AIRSPEED gibi
# değerleri esikler'den okuyor. 18 Ağu 2026'da SITL'den gerçek Pixhawk'a
# geçildiğinde tam bu yaşandı — panel hâlâ SITL'in ROLL_LIMIT_DEG=65 değerini
# tutuyordu ve gerçek uçağın (40°) dönemeyeceği bir daireyi "uçulabilir"
# sayardı.
VERI_DONDU_TAZELE = 8.0


def telemetri_dongusu():
    """Gelen MAVLink mesajlarını sürekli okuyup durumu günceller."""
    son_veri = time.time()
    while True:
        c = conn
        if c is None:
            son_veri = time.time()
            time.sleep(0.5)
            continue
        try:
            msg = c.recv_match(blocking=True, timeout=1.0)

            # KOPUKLUK KONTROLÜ HER TURDA YAPILIR — eskiden yalnızca
            # recv_match zaman aşımına düştüğünde (msg is None) yapılıyordu.
            #
            # SiK telsizi RADIO_STATUS'u SANİYEDE BİR kendisi üretir ve bunu
            # yer tarafında akışa enjekte eder. Yani uçak tamamen sussa bile
            # recv_match mesaj döndürmeye devam eder, msg hiç None olmaz ve bu
            # kontrol hiç çalışmazdı: panel araç gitmişken "BAĞLI" gösterirdi.
            if time.time() - son_veri > VERI_YOK_KOPUK:
                durum.guncelle(bagli=False)

            if msg is None:
                continue

            tip = msg.get_type()

            # TELSİZİN KENDİ MESAJI — ARAÇTAN GELMEZ.
            #
            # NE ZAMAN GELİR: SiK bu mesajı ancak BİLGİSAYARDAN MAVLink
            # gördüğünde üretir (firmware'de seen_mavlink bayrağı). Panel
            # GCSKeepalive ile 2 Hz heartbeat yolladığı için hep gelir; ama
            # sadece dinleyen bir araçla bakarsanız HİÇ göremezsiniz.
            # (22 Ağu 2026 gerçek SiK linkinde doğrulandı: pasif dinlemede 0
            # örnek, heartbeat yollarken 2.0 Hz.)
            # Bu yüzden son_veri'yi TAZELEMİYORUZ ve akış tazeleme mantığını
            # tetiklemiyoruz; yoksa yukarıdaki kopukluk kontrolü anlamsızlaşır.
            # Eski firmware RADIO (166), yenisi RADIO_STATUS (109) yollar.
            # rssi/noise ham birimdedir: dBm ~ deger/1.9 - 127.
            if tip in ("RADIO_STATUS", "RADIO"):
                durum.guncelle(
                    link_rssi=msg.rssi, link_uzak_rssi=msg.remrssi,
                    link_gurultu=msg.noise, link_uzak_gurultu=msg.remnoise,
                    link_tampon=msg.txbuf,
                    link_kayip=msg.rxerrors, link_duzeltilen=msg.fixed,
                    link_zaman=time.time(),
                )
                continue

            # SON_VERI YALNIZCA ARAÇTAN GELEN MESAJLA TAZELENİR.
            #
            # Linkte araçtan başka konuşanlar var: SiK telsizi (yukarıda
            # ayrıldı), MAVProxy köprüsü ve bağlıysa Mission Planner kendi
            # HEARTBEAT'ini yollar. Bunları "araçtan veri geldi" saymak,
            # Pixhawk sussa bile panelin BAĞLI görünmesine yol açar: köprü
            # ayakta kaldığı sürece kopukluk hiç fark edilmez.
            #
            # Mesaj yine de işlenir (aşağıdaki dallar zaten kendi süzgeçlerini
            # uyguluyor); burada değişen sadece CANLILIK sayacı.
            aractan = (not c.target_system
                       or msg.get_srcSystem() == c.target_system)

            # Uzun bir sessizlikten sonra veri döndüyse akış isteklerini
            # tazele: araç yeniden başlamış olabilir ve SET_MESSAGE_INTERVAL
            # istekleri onunla birlikte sıfırlanmıştır.
            simdi = time.time()

            # Susturulmuş olması gereken bir akış hâlâ geliyorsa komut yolda
            # kaybolmuş demektir — tekrarla. Bkz. _inatci_akisi_sustur.
            if tip in _sustur_idler:
                _inatci_akisi_sustur(tip, simdi)

            if aractan:
                if simdi - son_veri > VERI_DONDU_TAZELE:
                    print(f"[GCS] {simdi - son_veri:.0f} saniyelik sessizlikten "
                          f"sonra telemetri döndü — akışlar, eşikler ve ev "
                          f"konumu tazeleniyor (araç değişmiş olabilir)")
                    threading.Thread(target=_baglanti_sonrasi_tazele,
                                     daemon=True).start()
                son_veri = simdi

            if tip == "HEARTBEAT" and msg.get_srcSystem() == c.target_system:
                armli = bool(msg.base_mode
                             & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                yeni_alanlar = {
                    "bagli": True,
                    "armli": armli,
                    "mod": PLANE_MODE_NAMES.get(msg.custom_mode,
                                                str(msg.custom_mode)),
                    "mod_no": msg.custom_mode,
                }
                # Disarm kalkış yönü kaydını siler (AP_Arming_Plane.cpp:368).
                # Panel de silmezse pilot yerdeyken "yön yakalandı" görüp
                # havada AUTOLAND'in reddedildiğini fark eder — en kötü an.
                if not armli and durum.telemetri.get("inis_yonu") is not None:
                    yeni_alanlar["inis_yonu"] = None
                durum.guncelle(**yeni_alanlar)
            elif tip == "GLOBAL_POSITION_INT":
                durum.guncelle(
                    lat=msg.lat / 1e7, lon=msg.lon / 1e7,
                    irtifa=msg.relative_alt / 1000.0,
                    yon=msg.hdg / 100.0 if msg.hdg != 65535 else None,
                )
            elif tip == "ATTITUDE":
                durum.guncelle(roll=math.degrees(msg.roll),
                               pitch=math.degrees(msg.pitch),
                               yaw=math.degrees(msg.yaw))
            elif tip == "VFR_HUD":
                durum.guncelle(hiz=msg.groundspeed,
                               gaz_yuzde=msg.throttle)
            elif tip == "RC_CHANNELS":
                durum.guncelle(rc=[msg.chan1_raw, msg.chan2_raw,
                                   msg.chan3_raw, msg.chan4_raw,
                                   msg.chan5_raw, msg.chan6_raw,
                                   msg.chan7_raw, msg.chan8_raw])
            elif tip == "GPS_RAW_INT":
                durum.guncelle(gps_fix=msg.fix_type,
                               uydu=msg.satellites_visible)
            elif tip == "SYS_STATUS":
                durum.guncelle(
                    voltaj=msg.voltage_battery / 1000.0,
                    batarya_yuzde=(msg.battery_remaining
                                   if msg.battery_remaining != -1 else None),
                )
            elif tip == "HOME_POSITION":
                durum.guncelle(ev_lat=msg.latitude / 1e7,
                               ev_lon=msg.longitude / 1e7,
                               ev_irtifa=msg.altitude / 1000.0)
            elif tip == "STATUSTEXT":
                metin = (msg.text.decode() if isinstance(msg.text, bytes)
                         else msg.text).strip()
                durum.guncelle(son_mesaj=metin)
                durum.mesaj_ekle(metin, msg.severity)

                # KALKIŞ YÖNÜ YAKALANDI MI — otomatik inişin ön şartı.
                #
                # AUTOLAND modu, kalkışta yakalanan yön olmadan hiç
                # başlamıyor (mode_autoland.cpp _enter). Bu yön yer
                # istasyonundan hiçbir mesajla okunamıyor; ArduPilot yalnızca
                # yakaladığı anda "Autoland direction= NNN" diye bir kez
                # yazıyor (set_autoland_direction). Tek kaynak bu, o yüzden
                # metinden ayıklıyoruz.
                #
                # Disarm yönü SİLER (AP_Arming_Plane.cpp:368) — panel de
                # disarm görünce sıfırlıyor, aşağıdaki HEARTBEAT işleyicisinde.
                if metin.startswith("Autoland direction"):
                    try:
                        durum.guncelle(inis_yonu=float(
                            metin.split("=")[1].strip().rstrip("\u00b0")))
                    except (IndexError, ValueError):
                        pass
            elif tip == "PARAM_VALUE":
                param = msg.param_id
                if isinstance(param, bytes):
                    param = param.decode(errors="ignore")
                param = param.rstrip("\x00")
                durum.param_kaydet(param, msg.param_value)
                # Eşikler yalnızca bağlantı anında okunuyordu. Mission
                # Planner'dan (ya da başka bir yer istasyonundan) FENCE_RADIUS
                # veya AUTOLAND_WP_DIST değiştirildiğinde panel eski değerle
                # planlamaya devam ediyor, uçulamayacak bir şekli onaylayabilir
                # ya da uçulabilir olanı reddedebilirdi.
                #
                # ArduPilot bir parametre YAZILDIĞINDA yeni değeri PARAM_VALUE
                # ile HERKESE yayınlar (GCS_MAVLINK::handle_common_message ->
                # param yayını). Kim değiştirirse değiştirsin buraya düşer;
                # ayrıca yoklamaya gerek yok.
                if param in ESIK_PARAMLARI:
                    eski_deger = durum.esikler.get(param)
                    yeni_deger = round(float(msg.param_value), 3)
                    if eski_deger != yeni_deger:
                        durum.esikler = dict(durum.esikler,
                                             **{param: yeni_deger})
                        if eski_deger is not None:
                            durum.mesaj_ekle(
                                f"{param}: {eski_deger} -> {yeni_deger} "
                                f"(araçtan güncellendi)", 6)
            elif tip == "COMMAND_ACK":
                durum.ack_kaydet(msg.command, msg.result)
            elif tip == "MISSION_CURRENT":
                durum.gorev_ilerleme(aktif_seq=msg.seq)
            elif tip == "MISSION_ITEM_REACHED":
                durum.gorev_ilerleme(ulasilan=msg.seq)
            elif tip in GOREV_MESAJLARI:
                # Uçuşta SiK üzerinden Mission Planner de bağlı olabilir ve o
                # da görev yükleyebilir. Onun trafiği bizim posta kutumuza
                # düşerse yükleyici yanlış seq gönderir. Filtre şart.
                if (getattr(msg, "target_system", 0) == c.mav.srcSystem
                        and getattr(msg, "target_component", 0)
                        == c.mav.srcComponent):
                    durum.gorev_mesaj_kaydet(msg)
        except Exception as exc:
            print(f"[GCS] Telemetri hatası: {exc}")
            _baglantiyi_kapat(beklenen_conn=c)
            time.sleep(0.5)


# ---------------------------------------------------------------------------
# Joystick gönderim thread'i
# ---------------------------------------------------------------------------

# Titreme önleme ayarları. Analog servolarda (bu uçaktakiler) titreme belirgin:
# her küçük komut değişimini takip etmeye çalışırlar.
# 0..1 — küçük = daha yumuşak ama daha gecikmeli. Zaman sabiti:
#   tau = -0.05 / ln(1 - a)   ->  0.18 icin 252 ms, 0.30 icin 140 ms
# Kod değiştirmeden denemek için: JOY_YUMUSATMA=0.30 ortam değişkeni.
JOY_YUMUSATMA = float(os.environ.get("JOY_YUMUSATMA", "0.18"))
JOY_OLU_BOLGE = 40     # bu değerin altındaki komutlar sıfır sayılır

# OTURMA EŞİĞİ — titremenin asıl çaresi. Üstel yumuşatma hedefe asla tam
# ulaşmaz, sonsuza kadar yaklaşır ve her döngüde 1-2 birimlik değişim üretir.
# Analog servo bu bitmeyen mikro değişimi titreyerek takip eder. Fark bu eşiğin
# altına inince değer hedefe OTURTULUR ve akış durulur.
JOY_OTURMA = 4.0

# Gönderilen PWM bu adıma yuvarlanır: kalan mikro salınım servoya gitmez.
JOY_PWM_ADIM = 5

# ÖLÜ ADAM ANAHTARI — tarayıcıdan bu süre boyunca komut gelmezse override
# bırakılır ve kontrol vericiye döner.
#
# NEDEN: Arayüz joystick'i 20 Hz gönderir, sunucu ise durum.joystick'i
# tarayıcıdan bağımsız olarak sürekli akıtır. Telefon uykuya geçse, sekme
# arkaya atılsa, WiFi kopsa ya da tarayıcı donsa SON GAZ DEĞERİ sonsuza dek
# gitmeye devam ederdi. ArduPilot'un RC_OVERRIDE_TIME koruması da işe yaramaz,
# çünkü override'ı tazeleyen sunucunun kendisidir.
#
# 1.5 sn = 30 kaçırılmış paket. Wi-Fi'da tek tük paket kaybı bunu tetiklemez,
# gerçek kopmayı ise yarım saniyede yakalar.
JOY_ZAMAN_ASIMI = 1.5

# KEEPALIVE — komut DEĞİŞMEDİĞİNDE override'ı bu aralıkla tazeleriz.
#
# NEDEN VAR: eskiden her döngüde (20 Hz) koşulsuz RC_CHANNELS_OVERRIDE
# gidiyordu. MAVLink v1'de bu mesaj 26 bayt, yani sabit 520 B/s uplink —
# çubuk hiç kıpırdamasa bile. USB'de sorun değil (921600 baud), ama SiK
# 57600'de gerçek kapasite ~2500-3500 B/s ve yarı çift yönlü: 520 B/s uplink
# + ~520 B/s telemetri telsizin tamponunu doldurur. Tampon dolduğunda gecikme
# BİRİKİR ve bir daha inmez — çubuğu bıraksanız bile. Sahada görülen "aşırı
# gecikme" tam olarak budur; yumuşatma filtresiyle ilgisi yok.
#
# Artık yalnızca yuvarlanmış PWM DEĞİŞTİĞİNDE gönderiyoruz. Çubuk sabitken
# uplink 520 B/s'den ~52 B/s'ye düşüyor ve tampon boşalıyor.
#
# 0.5 sn güvenli: ArduPilot override'ı RC_OVERRIDE_TIME (varsayılan 3.0 sn)
# yenilenmezse bırakır — 6 kat pay var. Ölü adam anahtarı bundan bağımsız
# çalışmaya devam ediyor (tarayıcı susarsa 1.5 sn'de override bırakılır).
JOY_KEEPALIVE = 0.5


def joystick_dongusu():
    """
    Joystick aktifken 20 Hz RC override gönderir.

    Sürekli göndermek şart: ArduPilot override'ı 3 saniye yenilenmezse bırakır
    (RC_OVERRIDE_TIME). Bu bir güvenlik özelliğidir — arayüz çökerse uçak
    otopilota döner.
    """
    son_pwm = None          # en son GÖNDERİLEN kanal değerleri
    son_gonderim = 0.0
    gonderimler = collections.deque(maxlen=64)   # hız ölçümü için zaman damgaları
    son_hiz_yayini = 0.0

    while True:
        try:
            if durum.joystick_aktif and conn is not None:
                if time.time() - durum.joystick_son_komut > JOY_ZAMAN_ASIMI:
                    _joysticki_kapat()
                    durum.guncelle(son_mesaj=(
                        "Joystick komut akışı kesildi — RC override bırakıldı, "
                        "kontrol vericide"))
                    print("[GCS] Joystick zaman aşımı — override bırakıldı")
                    continue

                hedef = durum.joystick
                cikis = durum.joystick_cikis

                for eksen in ("roll", "pitch", "yaw", "throttle"):
                    h = float(hedef[eksen])
                    # Merkeze yakın gürültüyü ele. Gaz hariç: orada 0 gerçek
                    # bir komuttur, motoru durdurur.
                    if eksen != "throttle" and abs(h) < JOY_OLU_BOLGE:
                        h = 0.0
                    fark = h - cikis[eksen]
                    if abs(fark) < JOY_OTURMA:
                        cikis[eksen] = h          # hedefe otur, salınımı kes
                    else:
                        cikis[eksen] += JOY_YUMUSATMA * fark

                def yuvarla(deger):
                    return int(round(deger / JOY_PWM_ADIM) * JOY_PWM_ADIM)

                pwm = (
                    yuvarla(1500 + cikis["roll"] / 2),
                    yuvarla(1500 + cikis["pitch"] / 2),
                    int(1000 + cikis["throttle"]),
                    yuvarla(1500 + cikis["yaw"] / 2),
                )

                # DEĞİŞTİYSE ya da keepalive vakti geldiyse gönder. Bkz.
                # JOY_KEEPALIVE — dar bantlı linkte gecikmenin asıl çaresi bu.
                simdi = time.time()
                if pwm != son_pwm or simdi - son_gonderim >= JOY_KEEPALIVE:
                    conn.mav.rc_channels_override_send(
                        conn.target_system, conn.target_component,
                        pwm[0], pwm[1], pwm[2], pwm[3], 0, 0, 0, 0)
                    son_pwm = pwm
                    son_gonderim = simdi
                    gonderimler.append(simdi)

                # Ölçülen uplink hızını yarım saniyede bir yayınla. Panelde
                # görünür: link doluysa neyin aktığını tahmin etmek gerekmesin.
                if simdi - son_hiz_yayini >= 0.5:
                    son_hiz_yayini = simdi
                    pencere = [t for t in gonderimler if simdi - t <= 2.0]
                    durum.guncelle(joy_hz=round(len(pencere) / 2.0, 1))
            else:
                # Joystick kapalıyken sonraki açılışta ilk paket MUTLAKA
                # gitsin: aksi halde eski son_pwm ile aynı değere denk gelir
                # ve override hiç kurulmaz.
                if son_pwm is not None:
                    son_pwm = None
                    durum.guncelle(joy_hz=None)
            time.sleep(0.05)
        except Exception as exc:
            print(f"[GCS] Joystick hatası: {exc}")
            time.sleep(0.5)


# ---------------------------------------------------------------------------
# Komut gönderme
# ---------------------------------------------------------------------------

# ArduPilot'un "zorla" sihirli sayısı (COMPONENT_ARM_DISARM param2).
#
# Kaynaktan doğrulandı (GCS.h:789 magic_force_arm_disarm_value = 21196):
#     GCS_Common.cpp:5258  const bool forced = is_equal(packet.param2, 21196);
#                          AP::arming().disarm(Method::MAVLINK, !forced);
#     AP_Arming_Plane.cpp  do_disarm_checks true ise ve plane.is_flying() ise
#                          GCS disarm'ı REDDEDİLİR.
# Yani 21196 uçuş kilidini atlar. mav_common'daki ARM_FORCE_MAGIC (2989) force
# ARM içindir, disarm'da işe yaramaz — ikisi ayrı sayı.
ZORLA_DISARM_MAGIC = 21196.0


def komut_arm(arm_et: bool, denemeler: int = 2, zorla: bool = False):
    """
    ARM/DISARM komutu gönderir, ACK'i durum üzerinden bekler.

    zorla=True yalnızca DISARM için anlamlıdır ve otopilotun "uçarken motoru
    kesme" kilidini atlar. Sadece acil durdurma butonu bunu kullanır; normal
    DISARM butonu kilidi yerinde bırakır (bkz. api_arm).
    """
    cmd = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
    param2 = ZORLA_DISARM_MAGIC if (zorla and not arm_et) else 0.0
    sonuc = None
    for _ in range(denemeler):
        conn.mav.command_long_send(
            conn.target_system, conn.target_component, cmd, 0,
            1.0 if arm_et else 0.0, param2, 0, 0, 0, 0, 0,
        )
        sonuc = durum.ack_bekle(cmd, timeout=3.0)
        if sonuc == mavutil.mavlink.MAV_RESULT_ACCEPTED:
            return sonuc
        time.sleep(0.5)
    return sonuc


# İNİŞ SONRASI ARM TUZAĞI — bu modlarda yerde ARM etmek işe yaramaz.
#
# ArduPlane iniş bittiğinde "ne zamandır uçmuyorum" sayacını (last_flying_ms)
# tutmaya devam eder ve otomatik iniş modlarında bu sayaç dolduğunda aracı
# kendiliğinden disarm eder (disarm_if_autoland_complete). Uçak indikten sonra
# AUTOLAND/AUTO/RTL modunda beklerken ARM'a basarsanız sayaç ZATEN dolu
# olduğu için araç ANINDA "Auto disarmed" der. Kalkış hiç tetiklenmez.
#
# 22 Ağu 2026 SITL'de ölçüldü:
#   AUTOLAND'de arm  -> Throttle armed -> Throttle disarmed -> Auto disarmed
#   FBWA'da arm      -> Throttle armed -> AUTO -> Triggered AUTO -> kalkış
#
# Çözüm: yerdeyken bu modlardan birindeyken ARM etmeden ÖNCE FBWA'ya al.
# FBWA seçildi çünkü stabilize bir mod, gaz pilotun elinde ve ArduPlane
# burada otomatik disarm uygulamıyor.
# Adlar PLANE_MODE_NAMES'ten; "land" diye bir ArduPlane modu YOK — iniş
# AUTO içindeki NAV_LAND öğesiyle ya da AUTOLAND moduyla yapılıyor.
INIS_SONRASI_MODLAR = ("auto", "autoland", "rtl", "qland", "qrtl",
                       "loiter_alt_qland")


def _yerde_otomatik_moddan_cik(sebep: str) -> bool:
    """
    Yerdeyken otomatik bir moddaysak FBWA'ya al. Havadaysa DOKUNMAZ.

    Havada mod değiştirmek pilotun kararıdır; burada asla yapılmaz.
    """
    if conn is None:
        return False
    t = durum.oku()
    havada = bool(t.get("armli")) and (t.get("irtifa") or 0) > HAVADA_IRTIFA
    if havada:
        return False
    simdiki = (t.get("mod") or "").lower()
    if simdiki not in INIS_SONRASI_MODLAR:
        return False
    if komut_mod(MOD_ADLARI["fbwa"], deneme=2):
        durum.mesaj_ekle(f"{simdiki.upper()} -> FBWA ({sebep})", 4)
        print(f"[GCS] Yerde {simdiki.upper()} modundaydı, FBWA'ya alındı — {sebep}")
        return True
    return False


def komut_mod(mod_no: int, deneme: int = 3, deneme_suresi: float = 1.6):
    """
    Uçuş modunu değiştirir; telemetriden gelen HEARTBEAT ile doğrular.

    NEDEN TEKRARLI: set_mode'un ACK'i yoktur, doğrulama HEARTBEAT'in yeni modu
    bildirmesiyle olur. Tek gönderimde paket düşerse komut sessizce kaybolur ve
    arayüz "mod değiştirilemedi" der — oysa kullanıcı RTL'e basmıştır. SITL
    testinde tam bu görüldü: RTL "başarısız" döndü ama uçak birkaç saniye sonra
    RTL'e geçti. Telsiz linkinde (SiK) paket kaybı normaldir, bu yüzden
    mav_common.set_mode gibi birkaç kez denenir.
    """
    for _ in range(deneme):
        conn.mav.set_mode_send(
            conn.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mod_no,
        )
        t0 = time.time()
        while time.time() - t0 < deneme_suresi:
            if durum.oku().get("mod_no") == mod_no:
                return True
            time.sleep(0.1)
    return False


def _auto_modda():
    return durum.oku().get("mod") == "AUTO"


# ---------------------------------------------------------------------------
# Görev yükleme protokolü
# ---------------------------------------------------------------------------

def gorev_yukle_protokol(ogeler, zaman_asimi=20.0):
    """
    MISSION_COUNT → MISSION_REQUEST → MISSION_ITEM_INT → MISSION_ACK.

    ArduPilot davranışı (MissionItemProtocol.cpp'den okundu):
      * Öğeleri MISSION_REQUEST ile ister, MISSION_REQUEST_INT ile DEĞİL.
        Yalnızca _INT bekleyen bir istemci sonsuza kadar bekler.
      * Yanıt alamazsa aynı isteği SANİYEDE BİR kendisi tekrarlar. Bu yüzden
        bizim öğe tekrarı göndermemize gerek yok; iki taraflı tekrar
        MAV_MISSION_INVALID_SEQUENCE üretir.
      * 8 saniye hiç öğe gelmezse yüklemeyi iptal eder
        (upload_timeout_ms = 8000) ve OPERATION_CANCELLED ACK'i yollar.

    seq'in artan gittiği VARSAYILMAZ: kaybolan bir öğeden sonra araç aynı
    seq'i tekrar ister. Ne istenirse o gönderilir.
    """
    with GOREV_KILIDI:
        durum.gorev_kutusu_temizle()
        t0 = time.time()
        son = t0 + zaman_asimi
        count_deneme = 0
        son_count = 0.0
        gonderilen = set()

        while time.time() < son:
            # MISSION_COUNT'u yalnızca hiç öğe istenmemişken tekrarla.
            if count_deneme == 0 or (not gonderilen
                                     and time.time() - son_count > 3.0):
                if count_deneme >= 3:
                    return False, {"asama": "count",
                                   "hata": "Araç MISSION_COUNT'a yanıt vermedi"}
                conn.mav.mission_count_send(
                    conn.target_system, conn.target_component, len(ogeler))
                count_deneme += 1
                son_count = time.time()

            msg = durum.gorev_mesaj_al(
                ("MISSION_REQUEST", "MISSION_REQUEST_INT", "MISSION_ACK"),
                timeout=2.0)
            if msg is None:
                continue

            if msg.get_type() == "MISSION_ACK":
                ok = msg.type == mavutil.mavlink.MAV_MISSION_ACCEPTED
                return ok, {
                    "asama": "ack",
                    "mav_sonuc": int(msg.type),
                    "mav_sonuc_adi": MAV_GOREV_ADLARI.get(
                        int(msg.type), f"bilinmeyen kod {msg.type}"),
                    "sure": round(time.time() - t0, 2),
                    "gonderilen": len(gonderilen),
                }

            seq = int(msg.seq)
            if seq >= len(ogeler):
                return False, {"asama": "istek",
                               "hata": f"Araç olmayan {seq}. öğeyi istedi"}
            conn.mav.mission_item_int_send(
                conn.target_system, conn.target_component, **ogeler[seq])
            gonderilen.add(seq)

        return False, {"asama": "zaman_asimi",
                       "hata": f"Yükleme {zaman_asimi:.0f} saniyede bitmedi",
                       "son_seq": max(gonderilen, default=None)}


def gorev_sayisi_oku(timeout=3.0):
    """
    Araçtaki görev öğesi sayısını okur — yüklemenin gerçekten oturduğunu
    doğrulamak için. Sessiz yarım yükleme sahada en kötü hata türüdür.
    """
    durum.gorev_kutusu_temizle()
    conn.mav.mission_request_list_send(
        conn.target_system, conn.target_component)
    msg = durum.gorev_mesaj_al(("MISSION_COUNT",), timeout=timeout)
    return int(msg.count) if msg is not None else None


# GPS fix'in "gerçek konum" saydığımız alt sınırı. 3 = 3D fix.
GECERLI_FIX = 3


def _konum_gecerli(lat, lon):
    """
    Bu koordinat gerçek bir GPS konumu mu?

    NEDEN SADECE None KONTROLÜ YETMİYOR: fix yokken ArduPilot lat/lon alanlarını
    0 gönderiyor, None değil. `if lat is not None` testi bunu geçerli sayıyordu
    ve panel şekli (0, 0) — Gine Körfezi — merkezli planlıyordu. Uyarı veriyordu
    ama engel bayrağı düşmediği için GÖREVİ YÜKLE açık kalıyordu; araca 0,0
    merkezli bir görev yazılabilirdi. (19 Ağu 2026, gerçek Pixhawk'ta görüldü.)
    """
    if lat is None or lon is None:
        return False
    return not (abs(lat) < 1e-6 and abs(lon) < 1e-6)


def _konum_hatasi():
    """Görev planı/yüklemesi için konum yoksa nedenini söyleyen metin."""
    t = durum.oku()
    fix = t.get("gps_fix") or 0
    if fix < GECERLI_FIX:
        return (f"GPS fix yok (fix={fix}, {t.get('uydu') or 0} uydu) — "
                f"şekil planlamak için 3D fix gerekli. Dışarıda 1-3 dakika "
                f"bekleyin.")
    return "Konum bilinmiyor — araçtan geçerli koordinat gelmedi"


def _plan_istekten(veri):
    """
    İstek gövdesinden plan üretir. Hem önizleme hem yükleme bunu kullanır —
    panelde gördüğünüz şekil ile araca giden şekil ayrışamasın.
    """
    sekil = str(veri.get("sekil", "kare")).lower()
    if sekil not in SEKILLER:
        raise ValueError(f"bilinmeyen şekil: {sekil}")

    t = durum.oku()
    merkez_kaynak = str(veri.get("merkez", "ev")).lower()
    if merkez_kaynak == "ucak" and _konum_gecerli(t.get("lat"), t.get("lon")):
        merkez_lat, merkez_lon = t["lat"], t["lon"]
    elif _konum_gecerli(t.get("ev_lat"), t.get("ev_lon")):
        merkez_lat, merkez_lon = t["ev_lat"], t["ev_lon"]
        merkez_kaynak = "ev"
    elif _konum_gecerli(t.get("lat"), t.get("lon")):
        # Ev henüz gelmedi ama uçağın yeri biliniyor — yerdeyken ikisi aynıdır.
        merkez_lat, merkez_lon = t["lat"], t["lon"]
        merkez_kaynak = "anlik_konum"
    else:
        raise ValueError(_konum_hatasi())

    plan = plan_uret(
        sekil, merkez_lat, merkez_lon,
        irtifa_m=float(veri.get("irtifa", 60)),
        tur=int(veri.get("tur", 3)),
        olcu_m=float(veri.get("olcu", 250)),
        olcu2_m=(float(veri["olcu2"]) if veri.get("olcu2") else None),
        yon_derece=float(veri.get("yon", 0)),
        ev_lat=t.get("ev_lat"), ev_lon=t.get("ev_lon"),
        esikler=durum.esikler,
        inis=bool(veri.get("inis")),
        inis_yon=float(veri.get("inis_yon", 0)),
    )
    plan["merkez_kaynak"] = merkez_kaynak
    return plan


# ---------------------------------------------------------------------------
# Sayfalar
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/dok/<ad>")
def dokuman(ad):
    """
    Uçuş prosedürünü telefondan okunabilir kılar — sahada internet yok.
    """
    dosyalar = {
        "prosedur": ("UCUS_PROSEDURU.md", "Uçuş Prosedürü"),
        "kurulum": ("KURULUM_NOTLARI.md", "Kurulum Notları"),
    }
    if ad not in dosyalar:
        return "Bilinmeyen doküman", 404
    dosya, baslik = dosyalar[ad]
    try:
        with open(os.path.join(PROJE_KOK, dosya), encoding="utf-8") as f:
            kaynak = f.read()
    except OSError as exc:
        return f"{dosya} okunamadı: {exc}", 404
    return markdown_basit.sayfa(kaynak, baslik)


# ---------------------------------------------------------------------------
# Telemetri API'leri
# ---------------------------------------------------------------------------

# Batarya failsafe eylem kodları (ArduPlane/Plane.h enum Failsafe_Action).
BATARYA_EYLEMLERI = {
    0: ("hiçbir şey", False),
    1: ("RTL — eve gel, çember çiz", False),
    2: ("görevdeki iniş dizisi", False),
    3: ("uçuşu sonlandır (disarm)", False),
    4: ("QLand", False),
    5: ("paraşüt", False),
    6: ("Loiter + QLand", False),
    7: ("OTOMATİK İNİŞ (olmazsa RTL)", True),
}


def _inis_hazirlik():
    """
    Otomatik inişin GERÇEKTEN çalışıp çalışmayacağını uçuştan ÖNCE söyler.

    Üç bağımsız şart var ve üçü de sessizce bozulabiliyor:

      1. İniş paterni güvenlik çemberinin içinde mi? Değilse uçak yaklaşmaya
         giderken çiti aşar, FENCE_ACTION devreye girer ve iniş yarıda kalır.
      2. Süzülme açısı makul mü?
      3. Kalkış yönü yakalanmış mı? AUTOLAND bunsuz hiç başlamaz ve bunu
         ancak butona bastığınızda öğrenirsiniz — havada.

    Ayrıca batarya 2. kademesinin ne yapacağı da buradan bildiriliyor:
    BATT_FS_CRT_ACT 7 ise iner, 1 ise yalnızca eve gelip çember çizer.

    Patern uzaklığı iniş YÖNÜNDEN bağımsızdır (her yönde aynı yarıçap), bu
    yüzden denetim yön 0 ile yapılabiliyor.
    """
    t = durum.oku()
    esik = dict(durum.esikler)
    arac, varsayilan = _arac_oku(esik)

    # seviye: "ok" | "uyari" | "engel" | "bekliyor" | "bilinmiyor"
    # Sadece iyi/kötü ikilisi yetmiyordu: 11.5°'lik bir süzülme engel eşiğinin
    # (12°) altında kaldığı için ✓ görünüyordu, oysa uyarı eşiğinin (8°)
    # üstünde. "Yeşil ama aslında sınırda" en kötü gösterge türüdür.
    sonuc = {"engel": False, "satirlar": [], "yon_yakalandi": t.get("inis_yonu")}

    # Aynı sıfır-koordinat tuzağı: fix yokken lat/lon 0 gelir, None değil.
    if _konum_gecerli(t.get("ev_lat"), t.get("ev_lon")):
        ev_lat, ev_lon = t["ev_lat"], t["ev_lon"]
    elif _konum_gecerli(t.get("lat"), t.get("lon")):
        ev_lat, ev_lon = t["lat"], t["lon"]
    else:
        ev_lat = None

    if ev_lat is None:
        sonuc["satirlar"].append(
            {"ad": "Kalkış noktası", "deger": "bilinmiyor",
             "seviye": "bilinmiyor", "not": _konum_hatasi()})
        # Çit/süzülme denetimi konumdan BAĞIMSIZ (patern yarıçapı her yönde
        # aynı), o yüzden GPS olmadan da gösteriliyor — pilot kalkıştan önce
        # parametrelerin uygun olduğunu görebilsin.
        arac2, _ = _arac_oku(esik)
        uy2 = []
        p2 = inis_plani(0.0, 0.0, 0.0, arac2,
                        ekle=lambda sev, m: uy2.append((sev, m)), iz_uret=False)
        kul = arac2["FENCE_RADIUS"] - arac2["FENCE_MARGIN"]
        for ad, anahtar, deger in (
                ("Patern / çit", "İniş paterni",
                 f"{p2['ev_uzakligi_max']:.0f} m / {kul:.0f} m"),
                ("Süzülme", "Süzülme", f"{p2['suzulme_acisi']:.1f}°")):
            ilgili = [sev for sev, m in uy2 if anahtar in m]
            sonuc["satirlar"].append({
                "ad": ad, "deger": deger,
                "seviye": ("engel" if "engel" in ilgili
                           else ("uyari" if ilgili else "ok")),
                "not": next((m for sev, m in uy2 if anahtar in m), ""),
            })
            if "engel" in ilgili:
                sonuc["engel"] = True
        krt0 = esik.get("BATT_FS_CRT_ACT")
        if krt0 is not None:
            ad0, iner0 = BATARYA_EYLEMLERI.get(
                int(krt0), (f"bilinmeyen ({krt0:.0f})", False))
            v0 = esik.get("BATT_CRT_VOLT")
            sonuc["satirlar"].append({
                "ad": "Batarya 2. kademe",
                "deger": ad0 + (f" @ {v0:.1f} V" if v0 else ""),
                "seviye": "ok" if iner0 else "uyari",
                "not": ("" if iner0 else "BATT_FS_CRT_ACT = 7 yapılırsa kritik "
                                         "batarya otomatik iniş başlatır."),
            })
        return sonuc

    uyarilar = []
    plan = inis_plani(ev_lat, ev_lon, 0.0, arac,
                      ekle=lambda sev, m: uyarilar.append((sev, m)),
                      iz_uret=False)

    def seviye_bul(anahtar):
        """Bu konudaki en ağır uyarı hangisi — engel > uyarı > temiz."""
        ilgili = [sev for sev, m in uyarilar if anahtar in m]
        if "engel" in ilgili:
            return "engel"
        return "uyari" if ilgili else "ok"

    def notu(anahtar):
        return next((m for sev, m in uyarilar if anahtar in m), "")

    cit_sev = seviye_bul("İniş paterni")
    aci_sev = seviye_bul("Süzülme")
    kullanilabilir = arac["FENCE_RADIUS"] - arac["FENCE_MARGIN"]

    sonuc["satirlar"].append({
        "ad": "Patern / çit",
        "deger": f"{plan['ev_uzakligi_max']:.0f} m / {kullanilabilir:.0f} m",
        "seviye": cit_sev,
        "not": notu("İniş paterni"),
    })
    sonuc["satirlar"].append({
        "ad": "Süzülme",
        "deger": f"{plan['suzulme_acisi']:.1f}°",
        "seviye": aci_sev,
        "not": notu("Süzülme"),
    })

    yon = t.get("inis_yonu")
    sonuc["satirlar"].append({
        "ad": "Kalkış yönü",
        "deger": (f"{yon:.0f}° yakalandı" if yon is not None
                  else "henüz yakalanmadı"),
        # Yerdeyken yön HENÜZ yakalanamaz — bu bir hata değil, sırası
        # gelmemiş bir şart. Kalkış öncesi kırmızı göstermek paneli boşuna
        # alarma boğar; havadayken hâlâ yoksa o zaman gerçekten sorun.
        "seviye": ("ok" if yon is not None
                   else ("engel" if (t.get("irtifa") or 0) > HAVADA_IRTIFA
                         else "bekliyor")),
        "not": ("" if yon is not None else
                "AUTOLAND bunsuz reddedilir. Kalkıştan sonra AUTO/FBWA/MANUAL"
                " gibi bir modda uçunca yakalanır; disarm silir."),
    })

    krt = esik.get("BATT_FS_CRT_ACT")
    if krt is not None:
        ad, iner = BATARYA_EYLEMLERI.get(int(krt), (f"bilinmeyen ({krt:.0f})",
                                                    False))
        volt = esik.get("BATT_CRT_VOLT")
        sonuc["satirlar"].append({
            "ad": "Batarya 2. kademe",
            "deger": ad + (f" @ {volt:.1f} V" if volt else ""),
            # Otomatik iniş yapmaması bir ARIZA değil, bir tercih — uyarı
            # seviyesi doğru olan. Engel deseydik 🛬 butonu da kapanırdı,
            # oysa buton batarya ayarından bağımsız çalışıyor.
            "seviye": "ok" if iner else "uyari",
            "not": ("" if iner else
                    "BATT_FS_CRT_ACT = 7 yapılırsa kritik batarya otomatik "
                    "iniş başlatır."),
        })

    # Butonu YALNIZCA geometri engelinde kapat. Kalkış yönü yerdeyken zaten
    # yok; onun yüzünden kapatmak butonu kalkıştan önce hep kapalı bırakırdı.
    sonuc["engel"] = cit_sev == "engel" or aci_sev == "engel"
    sonuc["olcumler"] = {
        "mesafe": plan["mesafe"], "yaklasma_irtifa": plan["yaklasma_irtifa"],
        "daire": plan["loiter_yaricap"], "en_uzak": plan["ev_uzakligi_max"],
        "suzulme": plan["suzulme_acisi"],
        "suzulme_nominal": plan["suzulme_acisi_nominal"],
    }
    if varsayilan:
        sonuc["varsayilan_kullanildi"] = varsayilan
    return sonuc


@app.route("/api/telemetri")
def api_telemetri():
    t = durum.oku()
    t["joystick_aktif"] = durum.joystick_aktif
    t["throttle"] = durum.throttle
    t["autotune_aktif"] = durum.autotune_aktif
    t["esikler"] = dict(durum.esikler)
    t["inis_hazirlik"] = _inis_hazirlik()
    with durum.kilit:
        t["gorev"] = dict(durum.gorev)
    t["sunucu_saati"] = time.time()
    return jsonify(t)


@app.route("/api/mesajlar")
def api_mesajlar():
    """Araçtan gelen STATUSTEXT geçmişi — arm neden olmadığının kaydı."""
    with durum.kilit:
        kayit = [dict(m) for m in durum.mesajlar]
    return jsonify({"mesajlar": kayit[-60:], "sunucu_saati": time.time()})


# ---------------------------------------------------------------------------
# Uçuş kontrol API'leri
# ---------------------------------------------------------------------------

@app.route("/api/arm", methods=["POST"])
def api_arm():
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata

    veri = request.get_json(force=True)
    istek = bool(veri.get("arm", False))
    # zorla: yalnızca acil durdurma butonu gönderir. Otopilotun "uçarken
    # motoru kesme" kilidini atlar — havada basılırsa uçak motorsuz kalır.
    # Normal DISARM butonu bunu GÖNDERMEZ, kilit yerinde kalır.
    zorla = bool(veri.get("zorla", False)) and not istek
    t0 = time.time()

    if not istek:
        # DISARM istendiğinde önce kontrolü bırak: override akmaya devam
        # ederken disarm etmek anlamsız bir yarış yaratır.
        _joysticki_kapat()
    else:
        # ARM'dan ÖNCE otomatik moddan çık — bkz. INIS_SONRASI_MODLAR.
        # Yapılmazsa iniş sonrası ARM anında geri alınır ve uçak kalkmaz.
        _yerde_otomatik_moddan_cik("ARM için")

    sonuc = komut_arm(istek, zorla=zorla)
    kabul = sonuc == mavutil.mavlink.MAV_RESULT_ACCEPTED

    if zorla:
        t = durum.oku()
        print(f"[GCS] ZORLA DISARM {'kabul edildi' if kabul else 'reddedildi'}"
              f" — irtifa {t.get('irtifa')} m, mod {t.get('mod')}")

    # Reddedilme gerekçesi ArduPilot'un komuttan SONRA yazdığı STATUSTEXT'te.
    gerekceler = []
    if not kabul:
        time.sleep(0.4)      # gerekçe ACK'ten sonra gelebiliyor
        gerekceler = [m["metin"] for m in durum.mesajlar_sonrasi(t0)
                      if m["metin"]]

    return jsonify({
        "ok": kabul,
        "armli": istek if kabul else None,
        "sonuc": sonuc,
        "sonuc_adi": MAV_SONUC_ADLARI.get(sonuc, f"bilinmeyen kod {sonuc}"),
        "zorla": zorla,
        "gerekceler": gerekceler[-6:],
    })


@app.route("/api/mod", methods=["POST"])
def api_mod():
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata

    veri = request.get_json(force=True)
    ad = str(veri.get("mod", "")).lower()
    if ad not in MOD_ADLARI:
        return jsonify({"ok": False, "hata": f"bilinmeyen mod: {ad}"}), 400

    if ad == "auto":
        return jsonify({
            "ok": False,
            "hata": "AUTO'ya buradan geçilmez — önce şekli yükleyip BAŞLAT'a "
                    "basın. (Görev başlatma joystick'i kapatıp override'ı "
                    "bırakmak zorunda; bu buton onu yapmaz.)",
        }), 400

    # Mod değiştirirken override'ı bırak: otopilot yeni modu serbestçe uygulasın.
    if not durum.joystick_aktif:
        _overridelari_birak()
    ok = komut_mod(MOD_ADLARI[ad])
    return jsonify({"ok": ok, "mod": ad.upper()})


@app.route("/api/joystick", methods=["POST"])
def api_joystick():
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata

    veri = request.get_json(force=True)

    if "aktif" in veri:
        istek = bool(veri["aktif"])
        if istek:
            # STICK_MIXING = 1: RC override AUTO'nun navigasyon çıkışına
            # KARIŞIR. Sessizce AUTO'dan çıkmak yerine reddediyoruz — uçuş
            # modunu değiştirmek büyük bir karar, kullanıcı onaylasın.
            if _auto_modda():
                return jsonify({
                    "ok": False,
                    "hata": "GPS görevi uçuyor — önce GÖREVİ DURDUR'a basın. "
                            "(STICK_MIXING=1 olduğu için joystick AUTO'nun "
                            "rotasına karışır.)",
                }), 409
            durum.joystick_son_komut = time.time()
            durum.joystick_aktif = True
        else:
            _joysticki_kapat()
        return jsonify({"ok": True, "aktif": durum.joystick_aktif})

    # Eksen güncellemesi
    durum.joystick = {
        "roll": max(-1000, min(1000, int(veri.get("roll", 0)))),
        "pitch": max(-1000, min(1000, int(veri.get("pitch", 0)))),
        # Uçak V-kuyruk: yaw kanalı kullanılmıyor, her zaman nötr.
        "yaw": 0,
        "throttle": max(0, min(1000, int(veri.get("throttle", 0)))),
    }
    durum.joystick_son_komut = time.time()
    return jsonify({"ok": True, "aktif": durum.joystick_aktif})


@app.route("/api/dur", methods=["POST"])
def api_dur():
    """Her şeyi bırak — joystick kapansın, override serbest, AUTO ise LOITER."""
    _joysticki_kapat()
    mod = None
    if _arac_hazir() and _auto_modda():
        # AUTO override kullanmıyor; sadece override bırakmak görevi durdurmaz.
        if komut_mod(MOD_ADLARI["loiter"]):
            mod = "LOITER"
    return jsonify({"ok": True, "mod": mod})


@app.route("/api/eve", methods=["POST"])
def api_eve():
    """RTL — acil durum butonu."""
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata
    _joysticki_kapat()
    ok = komut_mod(MOD_ADLARI["rtl"])
    return jsonify({"ok": ok, "mod": "RTL"})


AUTOLAND_MOD_NO = 26


@app.route("/api/inis", methods=["POST"])
def api_inis():
    """
    AUTOLAND — uçak nerede olursa olsun kalktığı yere iner.

    RTL'DEN FARKI: RTL eve gelip çember çizer (RTL_AUTOLAND=1 olsa bile, iniş
    ancak görevde DO_LAND_START varsa olur). AUTOLAND göreve HİÇ bakmaz;
    kalkışta yakaladığı yönü kullanıp base leg + final + flare paternini
    kendisi kurar (mode_autoland.cpp).

    ARDUPLANE'İN İKİ ŞARTI (mode_autoland.cpp _enter, satır 80-93). İkisi de
    burada ÖNCEDEN kontrol ediliyor, çünkü şart sağlanmazsa uçak modu sessizce
    reddeder; arayüzde sadece "mod değişmedi" görünür ve pilot sebebini bilemez.

      1. Uçak UÇUYOR olmalı. Yerdeyken "Must already be flying!" der.
      2. Kalkış yönü YAKALANMIŞ olmalı. Yön, uçuş sırasında GPS yer rotasından
         alınır ve yalnızca bazı modlar yakalar (AUTO, FBWA, MANUAL, TAKEOFF,
         ACRO, STABILIZE, TRAINING, AUTOTUNE — mode.h). LOITER/CRUISE/FBWB/RTL
         yakalamaz. Disarm yön kaydını SİLER (AP_Arming_Plane.cpp:368), yani
         her uçuşta yeniden kalkmak gerekir.

    2. şartı yer istasyonundan doğrudan okunamaz. Bu yüzden mod komutu
    başarısız olursa araçtan gelen son STATUSTEXT'ler gerekçe olarak
    döndürülür — "Takeoff initial direction not set" mesajı orada görünür.
    """
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata

    t = durum.oku()
    if not t.get("armli"):
        return jsonify({
            "ok": False,
            "hata": "Uçak disarm — AUTOLAND yalnızca uçarken çalışır.",
        }), 409

    irtifa = t.get("irtifa") or 0.0
    if irtifa < HAVADA_IRTIFA:
        return jsonify({
            "ok": False,
            "hata": (f"Uçak havada görünmüyor (irtifa {irtifa:.0f} m). "
                     f"AUTOLAND uçarken devreye girer."),
        }), 409

    # AUTO'dan çıkıyoruz: görev sürüyorsa iniş onu devralır.
    _joysticki_kapat()

    t0 = time.time()
    ok = komut_mod(AUTOLAND_MOD_NO)
    cevap = {"ok": ok, "mod": "AUTOLAND" if ok else None}
    if not ok:
        cevap["hata"] = ("Araç AUTOLAND'e geçmedi. En olası sebep: kalkış yönü "
                         "yakalanmamış (kalkıştan sonra hiç AUTO/FBWA/MANUAL'de "
                         "uçulmadıysa olur).")
        cevap["gerekceler"] = [m["metin"] for m in durum.mesajlar_sonrasi(t0)]
    return jsonify(cevap)


# ---------------------------------------------------------------------------
# AUTOTUNE — uçarken PID kazançlarını öğrenir, MODU DEĞİŞTİRMEZ
# ---------------------------------------------------------------------------
#
# NEDEN AUX FONKSİYONU, MOD DEĞİL: RCx_OPTION 17 (AUTOTUNE mode) uçağı
# AUTOTUNE moduna alır ve GÖREVİ KESER. 107 (FW_AUTOTUNE) ise bulunduğu modda
# öğrenmeyi açar — AUTO'da görev kesilmeden ayar yapılabilir.
# ArduPlane/RC_Channel_Plane.cpp:
#     case AUX_FUNC::FW_AUTOTUNE:
#         if (ch_flag == HIGH && plane.control_mode->mode_allows_autotuning())
#             plane.autotune_enable(true);
# set_mode çağrısı yoktur; ModeAuto::mode_allows_autotuning() true döner.
#
# NEDEN KANAL ATAMASI GEREKMİYOR: MAVLink'ten gelen komut GCS_Common.cpp'de
# rc().run_aux_function(..., Source::MAVLINK) ile DOĞRUDAN çalıştırılır;
# RCx_OPTION ataması aranmaz. Kumandada boş kanal olmaması bunu engellemez.
#
# ÖĞRENME ÇUBUKLA OLUR: talep, hız limitinin %40'ını aşmalı (AP_AutoTune.cpp
# rate_threshold1). Sabit dairede talep ~0'dır, sert çubuk hareketi şarttır.
AUTOTUNE_AUX_FONKSIYON = 107
AUX_SEVIYE_YUKSEK = 2      # MAV_CMD_DO_AUX_FUNCTION_SWITCH_LEVEL_HIGH
AUX_SEVIYE_DUSUK = 0       # ..._LOW


@app.route("/api/autotune", methods=["POST"])
def api_autotune():
    """
    Autotune öğrenmesini açar/kapatır. Uçuş modunu DEĞİŞTİRMEZ.

    Araç yalnızca izin veren modlarda kabul eder (AUTO, FBWA, FBWB, LOITER).
    MANUAL/CRUISE'da otopilot "Autotuning not allowed in this mode!" yazar —
    bu mesaj gerekcelerde döner, yerde test etmenin yolu budur.
    """
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata

    veri = request.get_json(force=True)
    istek = bool(veri.get("aktif", False))
    seviye = AUX_SEVIYE_YUKSEK if istek else AUX_SEVIYE_DUSUK

    t0 = time.time()
    conn.mav.command_long_send(
        conn.target_system, conn.target_component,
        mavutil.mavlink.MAV_CMD_DO_AUX_FUNCTION, 0,
        AUTOTUNE_AUX_FONKSIYON, seviye, 0, 0, 0, 0, 0)

    sonuc = durum.ack_bekle(mavutil.mavlink.MAV_CMD_DO_AUX_FUNCTION, timeout=3.0)
    kabul = sonuc == mavutil.mavlink.MAV_RESULT_ACCEPTED

    # ACK "aux fonksiyonu çalıştırıldı" demek, "autotune açıldı" DEMEK DEĞİL.
    # İzin verilmeyen modda (MANUAL, CRUISE, RTL...) otopilot komutu yine
    # ACCEPTED'lar ama şunu yazar:
    #     "Autotuning not allowed in this mode!"   (RC_Channel_Plane.cpp)
    # Bu STATUSTEXT ACK'ten SONRA ve SiK üzerinden gecikmeli gelir. 0.4 sn
    # beklemek yetmiyordu: panel "AÇIK" gösterirken araç reddetmiş oluyordu —
    # pilot çubukları boşuna sallardı. 22 Ağu 2026 yer testinde görüldü.
    RED_IMZASI = "not allowed in this mode"
    reddedildi = False
    son = time.time() + 2.5
    while time.time() < son:
        if any(RED_IMZASI in m["metin"] for m in durum.mesajlar_sonrasi(t0)):
            reddedildi = True
            break
        time.sleep(0.1)

    gerekceler = [m["metin"] for m in durum.mesajlar_sonrasi(t0) if m["metin"]]
    if reddedildi:
        kabul = False

    if kabul:
        durum.autotune_aktif = istek
    elif not istek:
        # Kapatma her modda geçerlidir; red yalnızca AÇMA için anlamlı.
        durum.autotune_aktif = False
    print(f"[GCS] AUTOTUNE {'AÇ' if istek else 'KAPAT'} — "
          f"{'kabul' if kabul else 'RED'} ({sonuc})")

    return jsonify({
        "ok": kabul,
        "aktif": durum.autotune_aktif,
        "sonuc": sonuc,
        "sonuc_adi": MAV_SONUC_ADLARI.get(sonuc, f"bilinmeyen kod {sonuc}"),
        "gerekceler": gerekceler[-6:],
    })


@app.route("/api/preflight", methods=["POST"])
def api_preflight():
    """
    Uçuş öncesi kontrolü çalıştırır ve raporu metin olarak döndürür.

    NEDEN ALT SÜREÇ: control.preflight kendi MAVLink bağlantısını açıp kendi
    akış isteklerini yapar. Aynı işi burada tekrarlamak yerine denenmiş aracı
    olduğu gibi çalıştırıyoruz — tek kaynak, tek doğruluk.
    """
    ortam = dict(os.environ)
    ortam["PYTHONPATH"] = PROJE_KOK
    # WINDOWS: alt sürecin çıktısı BORUYA yazıldığında Python konsol yolunu
    # kullanamaz ve yerel kod sayfasına (Türkçe Windows'ta cp1254) düşer.
    # Çıktıda o kod sayfasında olmayan tek bir karakter olsa alt süreç
    # UnicodeEncodeError ile ölür ve panele HİÇ çıktı gelmez. İki tarafı da
    # UTF-8'e sabitliyoruz.
    ortam["PYTHONIOENCODING"] = "utf-8"
    hedef = SENARYO_ENDPOINT or "udp:127.0.0.1:14542"
    if SENARYO_ENDPOINT:
        ortam["MAV_ENDPOINT"] = SENARYO_ENDPOINT
    else:
        ortam.pop("MAV_ENDPOINT", None)

    # SERİ PORT ÇAKIŞMASINI ÖNCEDEN YAKALA.
    #
    # Bir seri portu tek süreç açabilir. Yer bilgisayarı kurulumunda panel
    # SiK'i doğrudan tutar (MAV_ENDPOINT=COM3), alt süreç aynı porta bağlanmayı
    # dener ve işletim sistemine göre ya anlaşılmaz bir hata verir ya da hiç
    # çıktı üretmeden ölür — sahada "çıktı yok" diye görünen buydu.
    #
    # UDP köprüsü varsa sorun yok: panel köprünün bir çıkışına (14552), alt
    # süreç başka bir porta (14550) bağlanır; köprü ikisini de besler.
    if (conn is not None and hedef == MAV_HEDEF
            and not hedef.lower().startswith(("udp", "tcp"))):
        return jsonify({
            "ok": False,
            "hata": (
                f"Uçuş öncesi kontrol bu kurulumda çalışamaz: panel {hedef} "
                "seri portunu tutuyor ve bir seri portu aynı anda tek süreç "
                "açabilir.\n\n"
                "Kaybınız yok — kontrolün baktığı her şey zaten panelde: GPS "
                "fix, batarya, uçuş modu, arm durumu ve otopilotun kendi "
                "gerekçeleri (MESAJLAR bölümü). ARM'a bastığınızda ArduPilot "
                "eksikleri tek tek yazar.\n\n"
                "Gerçekten çalıştırmak isterseniz PANELİ KAPATIN, sonra "
                "`python -m control.preflight` deyin — seri portu tek süreç "
                "açabilir. Ya da MAVProxy/Mission Planner ile bir UDP köprüsü "
                "kurup paneli o UDP adresine bağlayın (bkz. KURULUM.md)."
            ),
        }), 409

    komut = [sys.executable, "-u", "-m", "control.preflight"]
    try:
        p = subprocess.run(komut, cwd=PROJE_KOK, env=ortam,
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return jsonify({
            "ok": False,
            "hata": f"Kontrol 60 saniyede bitmedi — MAVLink bağlantısı yok "
                    f"olabilir (hedef: {hedef})",
        }), 504
    except Exception as exc:
        # Alt süreç hiç başlatılamadı (yanlış yorumlayıcı, eksik modül...).
        # Bunu 500 HTML sayfası olarak dönersek panel JSON çözemez ve
        # kullanıcı sebebi hiç göremez.
        return jsonify({
            "ok": False,
            "hata": f"Kontrol aracı başlatılamadı: {type(exc).__name__}: {exc}",
        }), 500

    cikti = (p.stdout or "") + (p.stderr or "")
    if not cikti.strip():
        # ASLA BOŞ DÖNME. Panel boş çıktıyı "çıktı yok" diye gösteriyordu ve
        # bu hiçbir şey anlatmıyordu — teşhis için gereken her şeyi yaz.
        cikti = (
            "Kontrol aracı hiç çıktı üretmeden "
            f"{p.returncode} çıkış koduyla bitti.\n\n"
            f"Çalıştırılan : {' '.join(komut)}\n"
            f"Dizin        : {PROJE_KOK}\n"
            f"MAVLink hedefi: {hedef}\n\n"
            "Bu genelde alt sürecin MAVLink portunu açamadığı anlamına gelir."
        )
    return jsonify({"ok": p.returncode == 0, "cikti": cikti})


# ---------------------------------------------------------------------------
# GPS şekil görevi
# ---------------------------------------------------------------------------

@app.route("/api/gorev/plan", methods=["POST"])
def api_gorev_plan():
    """
    Şekli hesaplar ve döndürür — ARACA HİÇ DOKUNMAZ.

    Arayüz her parametre değişikliğinde bunu çağırır; 3B panel dönen noktaları
    çizer, uyarılar anında görünür. Araç bağlı değilken de çalışır (eşikler
    okunamazsa sekil_geometri kendi varsayılanlarına düşer ve bunu bildirir).
    """
    try:
        plan = _plan_istekten(request.get_json(force=True))
    except ValueError as exc:
        return jsonify({"ok": False, "hata": str(exc)}), 400
    durum.gorev_plan = plan
    return jsonify({"ok": True, **plan})


@app.route("/api/gorev/yukle", methods=["POST"])
def api_gorev_yukle():
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata

    veri = request.get_json(force=True)
    try:
        plan = _plan_istekten(veri)
    except ValueError as exc:
        return jsonify({"ok": False, "hata": str(exc)}), 400

    if plan["engel"]:
        return jsonify({
            "ok": False,
            "hata": "Şekil bu uçakla uçulamaz",
            "uyarilar": plan["uyarilar"],
        }), 400

    t = durum.oku()
    if _konum_gecerli(t.get("ev_lat"), t.get("ev_lon")):
        ev_lat, ev_lon = t["ev_lat"], t["ev_lon"]
    elif _konum_gecerli(t.get("lat"), t.get("lon")):
        ev_lat, ev_lon = t["lat"], t["lon"]
    else:
        return jsonify({"ok": False, "hata": _konum_hatasi()}), 409

    # İniş kutusu işaretliyse bitiş türünü İSTEK EZMESİN: plan iniş paterni
    # içeriyorsa görev de inişle bitmeli. Arayüzün iki ayrı alanı (inis kutusu
    # ve bitince) ayrışırsa uçak "iniyorum" yazısıyla RTL çemberine girer.
    bitince = "inis" if plan.get("inis") else str(veri.get("bitince", "rtl"))
    g = gorev_ogeleri(plan, ev_lat, ev_lon, t.get("ev_irtifa") or 0.0,
                      bitince=bitince)

    t0 = time.time()
    ok, ayrinti = gorev_yukle_protokol(g["ogeler"])

    if ok:
        # Yükleme "kabul edildi" dedi diye oturmuş sayılmaz — geri okuyup
        # öğe sayısını doğruluyoruz.
        sayi = gorev_sayisi_oku()
        if sayi is not None and sayi != len(g["ogeler"]):
            ok = False
            ayrinti["hata"] = (f"Araçta {sayi} öğe var, {len(g['ogeler'])} "
                               f"gönderildi — yükleme yarım kalmış")
        ayrinti["aractaki_oge"] = sayi

    with durum.kilit:
        durum.gorev.update({
            "sekil": plan["sekil"] if ok else None,
            "yontem": plan["yontem"] if ok else None,
            "oge_sayisi": len(g["ogeler"]) if ok else 0,
            "ilk_sekil_seq": g["ilk_sekil_seq"] if ok else None,
            "irtifa": plan["irtifa"] if ok else None,
            "tur": plan["tur"] if ok else None,
            "yuklendi": time.time() if ok else None,
            "hata": None if ok else ayrinti.get("hata") or ayrinti.get("mav_sonuc_adi"),
            "aktif_seq": None, "ulasilan": None,
            "inis_var": bool(plan.get("inis")) if ok else False,
        })
    durum.gorev_plan = plan

    if not ok:
        ayrinti["gerekceler"] = [m["metin"] for m in durum.mesajlar_sonrasi(t0)]

    return jsonify({"ok": ok, "oge_sayisi": len(g["ogeler"]),
                    "kalkis_irtifa": g["kalkis_irtifa"],
                    "bitince": bitince, "inis": plan.get("inis"),
                    "uyarilar": plan["uyarilar"], **ayrinti})


@app.route("/api/gorev")
def api_gorev():
    """Yüklü görevin özeti + planlanan noktalar (3B panel bunu çizer)."""
    with durum.kilit:
        gorev = dict(durum.gorev)
    plan = durum.gorev_plan
    return jsonify({
        "gorev": gorev,
        "iz": plan["iz"] if plan else [],
        # İniş izi AYRI gönderiliyor: 3B panel şekli mavi, inişi turuncu
        # çiziyor. Tek listede birleştirilseydi iniş, şeklin son köşesinden
        # yaklaşma noktasına giden hayali bir kenar gibi görünürdü.
        "inis_iz": (plan.get("inis") or {}).get("iz", []) if plan else [],
        "merkez": plan["merkez"] if plan else None,
        "olcumler": plan["olcumler"] if plan else {},
    })


@app.route("/api/gorev/baslat", methods=["POST"])
def api_gorev_baslat():
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata

    with durum.kilit:
        gorev = dict(durum.gorev)
    if not gorev["oge_sayisi"]:
        return jsonify({"ok": False,
                        "hata": "Önce bir şekil yükleyin"}), 400

    # RC override üreten her şeyi kapat. STICK_MIXING=1 olduğu için kalan tek
    # bir override akışı AUTO'nun rotasını sessizce bozar — hata da vermez.
    _joysticki_kapat()

    # Başlangıç öğesini DETERMİNİSTİK yap. MIS_RESTART=0 olduğundan AUTO'ya
    # girmek görevi KALDIĞI YERDEN sürdürür; kullanıcı baştan başlayacağını
    # sanır. Uçak zaten havadaysa kalkış adımını atlayıp şekle geç.
    t = durum.oku()
    havada = bool(t.get("armli")) and (t.get("irtifa") or 0) > HAVADA_IRTIFA
    baslangic = gorev["ilk_sekil_seq"] if havada else 1
    conn.mav.mission_set_current_send(
        conn.target_system, conn.target_component, int(baslangic))

    # YERDEYKEN ZATEN AUTO'DAYSAK ÖNCE AUTO'DAN ÇIK.
    #
    # Otomatik iniş bittiğinde uçak AUTO modunda kalıyor. Bir sonraki uçuş için
    # "AUTO'ya geç" demek hiçbir şey yapmaz — araç zaten AUTO'dadır, komut boşa
    # gider ve ArduPlane'in kalkış tetikleyicisi (auto_takeoff_check) HİÇ
    # ÇALIŞMAZ. Uçak arm'lı halde yerde bekler ve DISARM_DELAY dolunca
    # kendiliğinden disarm olur. Yani günün ikinci uçuşu hiç kalkmaz.
    #
    # 22 Ağu 2026 SITL'de ölçüldü: iniş sonrası doğrudan AUTO -> 600 saniye
    # boyunca irtifa 0. Aynı dizide araya FBWA girildiğinde kalkış oldu.
    #
    # HAVADAYKEN YAPILMAZ: uçuş sırasında AUTO'dan çıkıp girmek rotayı bozar.
    if not havada and _yerde_otomatik_moddan_cik("kalkış için AUTO yenileniyor"):
        time.sleep(0.5)

    ok = komut_mod(MOD_ADLARI["auto"])
    return jsonify({
        "ok": ok, "mod": "AUTO" if ok else None,
        "kalkis_atlandi": havada,
        "baslangic_seq": int(baslangic),
    })


@app.route("/api/gorev/dur", methods=["POST"])
def api_gorev_dur():
    """Görevi durdur — uçak LOITER'da bulunduğu yerde tur atarak bekler."""
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata
    _joysticki_kapat()
    ok = komut_mod(MOD_ADLARI["loiter"])
    return jsonify({"ok": ok, "mod": "LOITER" if ok else None})


@app.route("/api/gorev/sil", methods=["POST"])
def api_gorev_sil():
    """
    Araçtaki görevi siler.

    Yüklü görevin varlığı failsafe ve RTL davranışını etkiler:
      * FS_LONG_ACTN = 1 (ReturnToLaunch) — uzun failsafe'te RTL'e geçer.
      * RTL_AUTOLAND = 1 — RTL eve varınca görevde DO_LAND_START ARAR ve
        bulursa iner. Yani inişli bir görev yüklüyken RTL de iniş demektir.
    Görevi silmek bu bağın ikisini de koparır; inişi iptal edip elle inmek
    isteyen pilotun buna ihtiyacı var.
    """
    hata = _arac_gerekli_hatasi()
    if hata:
        return hata
    durum.gorev_kutusu_temizle()
    conn.mav.mission_count_send(conn.target_system, conn.target_component, 0)
    msg = durum.gorev_mesaj_al(("MISSION_ACK",), timeout=3.0)
    ok = msg is not None and msg.type == mavutil.mavlink.MAV_MISSION_ACCEPTED

    # "İNİŞ DİZİSİNDEYİM" BAYRAĞINI DA TEMİZLE.
    #
    # Görev bir iniş dizisiyle bittiğinde ArduPilot _flags.in_landing_sequence
    # bayrağını 1'de bırakır ve bir sonraki ARM'ı "PreArm: In landing sequence"
    # ile reddeder. 19 Ağu 2026 SITL uçuşunda yaşandı: uçak otomatik indi,
    # sonra tekrar arm edilemedi.
    #
    # Görevi silmek bunu TEK BAŞINA çözmez — AP_Mission::clear() bayrağa hiç
    # dokunmaz (yalnızca reset() dokunur, o da mission start'ta çağrılır).
    # set_current_cmd() ise bayrağı EN BAŞTA koşulsuz siliyor; boş göreve
    # 0. öğeyi göstermek de bu yolu tetikliyor.
    if ok:
        conn.mav.mission_set_current_send(
            conn.target_system, conn.target_component, 0)

    # YERDE VE AUTO'DAYSAK AUTO'DAN ÇIK.
    #
    # Görev silinince AUTO modu görevsiz kalır ve ArduPlane bir sonraki ARM'ı
    # "PreArm: Mode requires mission" ile reddeder. Kullanıcı görevi bilerek
    # sildiği için bu mesaj kafa karıştırıcı; üstelik iniş sonrası uçak zaten
    # AUTO'da kalıyor, yani bu durum HER iniş sonrası oluşuyor.
    #
    # HAVADAYKEN YAPILMAZ: uçarken modu değiştirmek pilotun kararı olmalı.
    # (Zaten uçarken görev silmenin amacı çoğu zaman inişi iptal etmektir ve
    # o durumda uçak AUTO'dan çıkmadan LOITER'a alınmalı — bu ayrı bir buton.)
    if ok:
        _yerde_otomatik_moddan_cik("görev silindi")

    if ok:
        with durum.kilit:
            durum.gorev.update({"sekil": None, "yontem": None, "oge_sayisi": 0,
                                "ilk_sekil_seq": None, "yuklendi": None,
                                "aktif_seq": None, "ulasilan": None,
                                "inis_var": False})
        durum.gorev_plan = None
    return jsonify({"ok": ok})


# ---------------------------------------------------------------------------
# CLI senaryolarıyla uyumluluk
#
# Arayüz bunları kullanmıyor. control/run_plane_scenario.py bu iki adresi HTTP
# ile okuyor (run_plane_scenario.py:333 ve :359); kaldırılırsa CLI'dan senaryo
# çalıştırmak sessizce varsayılanlara düşer. Format DEĞİŞTİRİLMEMELİ.
# ---------------------------------------------------------------------------

@app.route("/api/plane_throttle")
def api_plane_throttle():
    return jsonify({"throttle": durum.throttle})


@app.route("/api/throttle", methods=["POST"])
def api_throttle_ayarla():
    veri = request.get_json(force=True)
    durum.throttle = max(0, min(1000, int(veri.get("throttle", 600))))
    return jsonify({"ok": True, "throttle": durum.throttle})


@app.route("/api/sekil")
def api_sekil_oku():
    return jsonify(durum.sekil)


@app.route("/api/sekil", methods=["POST"])
def api_sekil_ayarla():
    veri = request.get_json(force=True)

    def sinirla(deger, alt, ust):
        return max(alt, min(ust, deger))

    if "kare_kenar" in veri:
        durum.sekil["kare_kenar"] = sinirla(float(veri["kare_kenar"]), 2.0, 20.0)
    if "donus_yatis" in veri:
        durum.sekil["donus_yatis"] = int(sinirla(int(veri["donus_yatis"]), 200, 900))
    if "daire_yatis" in veri:
        durum.sekil["daire_yatis"] = int(sinirla(int(veri["daire_yatis"]), 200, 800))
    return jsonify({"ok": True, **durum.sekil})


# ---------------------------------------------------------------------------
# Başlatma
# ---------------------------------------------------------------------------

def main():
    global MAV_HEDEF, SENARYO_ENDPOINT

    print("=" * 60)
    print("  TALON YER KONTROL ARAYÜZÜ")
    print("=" * 60)

    # Arayüz KENDİ portundan bağlanır: aynı UDP portunu iki süreç bind edemez,
    # CLI senaryoları 14550'yi kullanıyor. GCS_ENDPOINT bunu ayırır.
    # Alt süreçlerin adresini, üzerine yazmadan ÖNCE sakla.
    SENARYO_ENDPOINT = os.environ.get("MAV_ENDPOINT")

    gcs_hedef = os.environ.get("GCS_ENDPOINT")
    if gcs_hedef:
        os.environ["MAV_ENDPOINT"] = gcs_hedef

    MAV_HEDEF = os.environ.get("MAV_ENDPOINT", "udp:127.0.0.1:14550")
    print(f"Bağlantı hedefi: {MAV_HEDEF}")

    # Web arayüzü HEMEN açılsın; araç sonradan takılsa bile arka planda
    # bağlanır. Pixhawk yokken bile panelin açılması montaj işlerinde kritik.
    threading.Thread(target=baglanti_dongusu, daemon=True).start()
    threading.Thread(target=telemetri_dongusu, daemon=True).start()
    threading.Thread(target=joystick_dongusu, daemon=True).start()

    # GCS_PORT: SITL testinde ikinci bir arayüz örneği ayrı portta çalışsın
    # diye. Verilmezse üretimdeki 8000 değişmez.
    port = int(os.environ.get("GCS_PORT", "8000"))

    print()
    print("Arayüz hazır:")
    print(f"   http://localhost:{port}          (bu bilgisayarda)")
    # Ağ adreslerini platform BAĞIMSIZ bul. Eskiden `hostname -I` çalıştırıyordu;
    # o bir Linux komutu ve panel yer bilgisayarında (Windows/mac) çalıştırılınca
    # sessizce boş dönüyordu — kullanıcı bağlanacağı adresi göremiyordu.
    try:
        import socket
        adresler = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None)
                    if a[0] == socket.AF_INET}
        # Hostname hiçbir şeye çözülmezse dış dünyaya bakan arayüzü sor.
        if not adresler or adresler <= {"127.0.0.1"}:
            sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sk.connect(("8.8.8.8", 80))      # paket GÖNDERİLMEZ, sadece yönlendirme sorulur
                adresler.add(sk.getsockname()[0])
            finally:
                sk.close()
        for adres in sorted(adresler):
            if adres != "127.0.0.1":
                print(f"   http://{adres}:{port}            (ağdaki başka cihazdan)")
    except Exception:
        pass        # adres bulunamazsa panel yine çalışır, sadece yazdırmaz
    print()
    print("Durdurmak için Ctrl+C")
    print("=" * 60)

    app.run(host="0.0.0.0", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
