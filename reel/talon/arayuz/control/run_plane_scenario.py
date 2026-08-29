#!/usr/bin/env python3
"""
run_plane_scenario.py — Hedef İHA (sabit kanat) uçuş senaryoları.

Kullanım:
    python -m control.run_plane_scenario square      # kare çiz
    python -m control.run_plane_scenario circle      # daire çiz
    python -m control.run_plane_scenario aggressive  # rastgele agresif manevralar

Akış: bağlan → force ARM → TAKEOFF modu ile otonom kalkış → FBWA + RC
override ile seçilen desen. Desen, GCS süreci öldürene (manuel moda geçiş
veya durdur butonu) kadar süresiz döner.

Kare dönüşleri PUSULA (ATTITUDE yaw) tabanlıdır: FBWA'da roll komutu verilir,
heading 90° değişince kenara geçilir. (Kaldırılan eski run_plane_square zaman bazlı
rudder(yaw) dönüşü kullanıyordu — FBWA'da rudder tek başına dönüş üretmediği
için kare bozuktu.)

Throttle GCS'teki slider'dan okunur (http://127.0.0.1:8000/api/plane_throttle);
agresif manevralar kendi throttle'ını kullanır.
"""

import json
import math
import os
import random
import signal
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymavlink import mavutil

from control.plane_functions import (
    connect_plane,
    arm_plane,
    get_conn,
    start_gcs_keepalive,
    stop_gcs_keepalive,
    THROTTLE_CRUISE,
)
from control.mav_common import (
    clear_rc_overrides,
    set_mode,
    PLANE_MODE_NAMES,
    PLANE_MODE_TAKEOFF,
    PLANE_MODE_FBWA,
)

# Havada devralma eşiği: bu irtifanın üstünde armlıysak kalkış ATLANIR.
AIRBORNE_ALT_M = 15.0

CONTROL_RATE = 0.05   # 20 Hz komut döngüsü

# Mod komutu gönderdikten sonra, araç o modu bildirene kadar geçen kısa süre.
# Bu pencere boyunca uyuşmazlık yok sayılır — yoksa scriptin kendi mod
# değişimi "pilot devraldı" sanılır.
#
# Pencere ONAYA BAĞLI: araç komut ettiğimiz modu bildirir bildirmez kapanır.
# Aşağıdaki süre yalnızca ÜST SINIR — komut hiç işlenmezse sonsuza kadar
# açık kalmasın diye. Sabit bekleme değildir; onay 100 ms'de gelirse pencere
# 100 ms sürer.
DEVRALMA_ONAY_TIMEOUT = 2.0

# Araç heartbeat'i varsayılan 1 Hz gelir; devralmayı ortalama 500 ms geç
# görürüz. SET_MESSAGE_INTERVAL ile hızlandırınca tespit ~50 ms'ye iner.
HEARTBEAT_HZ = 10.0

_abort = False

# _pump ile güncellenen son telemetri
_att = {"roll": 0.0, "pitch": 0.0, "yaw": 0.0, "ok": False}
_pos = {"z": 0.0}

# --- Pilot devralma takibi ---
# Script kendi mod değişimlerini _mod_ayarla() ile yapar; istenen mod
# "beklenen" olarak kaydedilir. Araçtan gelen HEARTBEAT bundan başka bir mod
# gösteriyorsa kumandadan mod değiştirilmiş demektir — script çekilir.
#
# NEDEN GEREKLİ: RC override, vericinin çubuk girdilerinin YERİNE geçer.
# Script komut göndermeye devam ettiği sürece pilot mod anahtarını çevirse
# bile uçağı çubuklarla kontrol edemez. Devralmayı fark edip override'ı
# bırakmak, kontrolü pilota geri vermenin tek yoludur.
_mod = {"aktif": None, "beklenen": None, "onaylandi": False, "komut_t": 0.0}
_devralindi = False

# Pilotun dokunduğu, bizim override ETMEDİĞİMİZ kanallar (CH5-CH8).
# NEDEN sadece bunlar: ArduPilot RC_CHANNELS mesajında override edilmiş
# kanallar için BİZİM gönderdiğimiz değeri yayınlar — CH1-CH4'te vericinin
# gerçek çubuk konumu okunamaz (8 Ağu 2026'da SITL'de ölçüldü). CH5+ override
# edilmediği için gerçek verici değerini gösterir; mod anahtarı da orada.
_rc_pilot = {"ilk": None, "son": None, "degisim": 0}


def _sig_handler(_sig, _frame):
    global _abort
    _abort = True


def _mod_adi(no):
    """Mod numarasını okunur ada çevirir."""
    return PLANE_MODE_NAMES.get(no, str(no))


# ---------------------------------------------------------------------------
# Uçuş kaydı
# ---------------------------------------------------------------------------

LOG_DIZIN = os.path.expanduser("~/ucus_loglari")
_log_dosya = None


def _log_ac(senaryo_adi):
    """
    Uçuş kaydı dosyasını açar.

    Senaryo arayüzden başlatıldığında stdout görünmez (alt süreç), bu yüzden
    önemli olaylar ayrıca dosyaya yazılır — uçuş sonrası incelemek için.
    """
    global _log_dosya
    try:
        os.makedirs(LOG_DIZIN, exist_ok=True)
        yol = os.path.join(
            LOG_DIZIN, time.strftime("%Y%m%d_%H%M%S") + f"_{senaryo_adi}.log")
        # encoding açıkça: günlükte Türkçe ve "→" var; Windows'un cp1254
        # varsayılanı bunlarda UnicodeEncodeError verirdi.
        _log_dosya = open(yol, "a", buffering=1, encoding="utf-8")
        _kayit(f"senaryo={senaryo_adi} baslatildi")
        print(f"[SCN] Uçuş kaydı: {yol}")
    except Exception as exc:
        print(f"[SCN] Uçuş kaydı açılamadı ({exc}) — sadece ekrana yazılacak")


def _kayit(mesaj):
    """Hem ekrana hem uçuş kaydı dosyasına yazar."""
    satir = f"[{time.strftime('%H:%M:%S')}] {mesaj}"
    print(f"[SCN] {mesaj}")
    if _log_dosya is not None:
        try:
            _log_dosya.write(satir + "\n")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Pilot müdahalesi izleme
# ---------------------------------------------------------------------------

# Bu kadar PWM sapma "pilot dokundu" sayılır (gürültü payının üstünde).
PILOT_KANAL_ESIK = 30

# Senaryo anahtarının kanalı (arayüz sunucusu ortam değişkeniyle bildirir).
# O kanaldaki hareket pilot müdahalesi DEĞİLDİR — senaryoyu başlatan/durduran
# kasıtlı komuttur; izleme dışı bırakılmazsa uçuş kaydı yanıltıcı olur.
try:
    ANAHTAR_KANALI = int(os.environ.get("SENARYO_ANAHTAR_KANALI", "0"))
except ValueError:
    ANAHTAR_KANALI = 0


def _rc_pilot_izle(msg):
    """
    Override ETMEDİĞİMİZ kanallarda (CH5-CH8) pilot hareketini kaydeder.

    Mod anahtarı bu kanallardadır (kartta FLTMODE_CH=5), yani pilot devralmaya
    çalıştığında ilk iz burada görünür — mod değişimi HEARTBEAT'e yansımadan
    önce bile.

    ÖNEMLİ SINIR: CH1-CH4'te (çubuklar) pilotun gerçek girdisi OKUNAMAZ.
    ArduPilot, override edilen kanallar için RC_CHANNELS mesajında bizim
    gönderdiğimiz değeri yayınlar. Çubuk sapması bu yüzden loglanamıyor.
    """
    simdi = (msg.chan5_raw, msg.chan6_raw, msg.chan7_raw, msg.chan8_raw)

    if _rc_pilot["ilk"] is None:
        _rc_pilot["ilk"] = simdi
        _rc_pilot["son"] = simdi
        return

    if simdi == _rc_pilot["son"]:
        return

    for i, (baslangic, guncel) in enumerate(zip(_rc_pilot["ilk"], simdi)):
        kanal = i + 5
        onceki = _rc_pilot["son"][i]
        if abs(guncel - onceki) < PILOT_KANAL_ESIK:
            continue
        if kanal == ANAHTAR_KANALI:
            # Senaryo anahtarı — sayaca girmez, "pilot dokundu" sayılmaz.
            _kayit(f"senaryo anahtarı CH{kanal}: {onceki} → {guncel}")
            continue
        _rc_pilot["degisim"] += 1
        _kayit(f"PİLOT KANALI OYNADI — CH{kanal}: {onceki} → {guncel} "
               f"(uçuş başındaki değer {baslangic})")
    _rc_pilot["son"] = simdi


def _akislari_hizlandir(conn):
    """
    HEARTBEAT ve RC_CHANNELS akışlarını hızlandırır.

    HEARTBEAT varsayılan 1 Hz'dir; devralmayı ortalama 500 ms geç görürüz.
    10 Hz'e çıkarınca tespit ~50 ms'ye iner. RC_CHANNELS da pilot kanallarını
    izlemek için gerekir.
    """
    aralik = int(1e6 / HEARTBEAT_HZ)
    for mid in (mavutil.mavlink.MAVLINK_MSG_ID_HEARTBEAT,
                mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS):
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            mid, aralik, 0, 0, 0, 0, 0)
        time.sleep(0.05)


def _mod_ayarla(conn, mod_no, confirm_timeout: float = 3.0):
    """
    Uçuş modunu değiştirir VE beklenen modu günceller.

    set_mode yerine hep bu kullanılmalı: aksi halde scriptin kendi yaptığı
    mod değişimi "pilot devraldı" sanılır ve senaryo boşuna durur.
    """
    ok = set_mode(conn, mod_no, confirm_timeout=confirm_timeout)

    # BAYAT HEARTBEAT TEMİZLİĞİ — bu satır olmazsa yanlış devralma alarmı olur.
    # set_mode saniyelerce blocking okuma yapar; o sırada _pump çalışmadığı
    # için kuyrukta ESKİ moda ait heartbeat'ler birikir (10 Hz'de ~30 tane).
    # Temizlenmezse _pump bunları okuyup "araç hâlâ eski modda" sanır ve
    # scriptin kendi mod değişimini pilot devralması zanneder.
    # Yalnızca HEARTBEAT çekilir; ATTITUDE kuyrukta kalır (dönüşler ona bağlı).
    while conn.recv_match(type="HEARTBEAT", blocking=False) is not None:
        pass

    _mod["aktif"] = None          # bilinmiyor; ilk TAZE heartbeat dolduracak
    _mod["beklenen"] = mod_no
    _mod["komut_t"] = time.time()
    _mod["onaylandi"] = False     # onay taze heartbeat'ten gelecek
    return ok


def _devralma_kontrol():
    """
    Pilot kumandadan mod değiştirdi mi?

    Onay penceresi mantığı: komut ettiğimiz modu araç bildirdiği anda pencere
    kapanır (_mod["onaylandi"]). Kapandıktan sonra herhangi bir mod
    uyuşmazlığı ANINDA devralma sayılır — kalkış fazında bile.

    Pencere yalnızca komut henüz onaylanmamışken ve üst sınır dolmamışken
    açıktır; o aralıkta görülen "eski mod" bizim komutumuzun daha işlenmemiş
    olmasıdır, devralma değildir.
    """
    if _mod["beklenen"] is None or _mod["aktif"] is None:
        return False
    if _mod["aktif"] == _mod["beklenen"]:
        return False
    if (not _mod["onaylandi"]
            and time.time() - _mod["komut_t"] < DEVRALMA_ONAY_TIMEOUT):
        return False
    return True


def _pump(conn):
    """Bekleyen MAVLink mesajlarını tüket; ATTITUDE, LOCAL_POSITION_NED ve
    HEARTBEAT sakla. Pilot devralmasını da burada yakalar.

    plane_functions.send_manual_control her çağrıda drain_messages ile HER ŞEYİ
    çöpe atıyordu — heading tabanlı dönüş için attitude'u burada yakalıyoruz.
    Tamponu boşaltmak ayrıca telemetrinin bayatlamasını da önler.
    """
    global _abort, _devralindi

    while True:
        msg = conn.recv_match(blocking=False)
        if msg is None:
            break
        t = msg.get_type()
        if t == "ATTITUDE":
            _att.update(roll=msg.roll, pitch=msg.pitch, yaw=msg.yaw, ok=True)
        elif t == "LOCAL_POSITION_NED":
            _pos["z"] = msg.z
        elif t == "HEARTBEAT" and msg.get_srcSystem() == conn.target_system:
            _mod["aktif"] = msg.custom_mode
            # Komut ettiğimiz modu gördük → onay penceresini KAPAT.
            # Bundan sonra her uyuşmazlık anında devralma sayılır.
            if not _mod["onaylandi"] and msg.custom_mode == _mod["beklenen"]:
                _mod["onaylandi"] = True
        elif t == "RC_CHANNELS":
            _rc_pilot_izle(msg)

    if _devralindi or not _devralma_kontrol():
        return

    # Pilot devraldı: komut göndermeyi bırak, senaryoyu sonlandır.
    _devralindi = True
    _abort = True
    print()
    print("=" * 58)
    _kayit(f"PİLOT DEVRALDI — mod {_mod_adi(_mod['beklenen'])} yerine "
           f"{_mod_adi(_mod['aktif'])} görüldü")
    _kayit("Senaryo durduruluyor, RC override bırakılıyor.")
    print("=" * 58)


def _rc(conn, roll=0, pitch=0, throttle=0, yaw=0):
    """RC override gönder — plane_functions.send_manual_control ile aynı eşleme.

    roll/pitch/yaw: -1000..+1000 (pozitif = sağa yatış / burun yukarı / sağa),
    throttle: 0..1000.
    """
    conn.mav.rc_channels_override_send(
        conn.target_system,
        conn.target_component,
        int(1500 + roll / 2),       # CH1: Aileron
        int(1500 + pitch / 2),      # CH2: Elevator (YÜKSEK PWM = burun yukarı,
                                    #      canlı SITL'de doğrulandı)
        int(1000 + throttle),       # CH3: Throttle
        int(1500 + yaw / 2),        # CH4: Rudder
        0, 0, 0, 0,
    )


_thr_cache = {"val": THROTTLE_CRUISE, "t": 0.0}


def gcs_throttle():
    """GCS slider'ından throttle oku (0.5s önbellekli; GCS yoksa cruise)."""
    now = time.time()
    if now - _thr_cache["t"] > 0.5:
        _thr_cache["t"] = now
        try:
            req = urllib.request.urlopen(
                "http://127.0.0.1:8000/api/plane_throttle", timeout=0.2)
            _thr_cache["val"] = json.loads(req.read().decode()).get(
                "throttle", THROTTLE_CRUISE)
        except Exception:
            pass
    return _thr_cache["val"]


# Şekil ayarları arayüzden gelir. GCS kapalıysa bu varsayılanlar kullanılır —
# senaryo yine çalışır, sadece ayarlanamaz.
SEKIL_VARSAYILAN = {"kare_kenar": 5.0, "donus_yatis": 650, "daire_yatis": 500}
_sekil_cache = {"val": dict(SEKIL_VARSAYILAN), "t": 0.0}


def gcs_sekil():
    """
    Arayüzden şekil ayarlarını oku (1 sn önbellekli).

    Uçuş sırasında değiştirilebilir: bir sonraki kenar/dönüş/tur yeni değerle
    uçulur. Devam eden hareket kesilmez.
    """
    now = time.time()
    if now - _sekil_cache["t"] > 1.0:
        _sekil_cache["t"] = now
        try:
            req = urllib.request.urlopen(
                "http://127.0.0.1:8000/api/sekil", timeout=0.2)
            gelen = json.loads(req.read().decode())
            for anahtar in SEKIL_VARSAYILAN:
                if anahtar in gelen:
                    _sekil_cache["val"][anahtar] = gelen[anahtar]
        except Exception:
            pass
    return _sekil_cache["val"]


def hold(conn, duration, roll=0, pitch=0, throttle=None, yaw=0):
    """duration boyunca sabit komut uygula (throttle=None → GCS slider)."""
    t0 = time.time()
    while not _abort and time.time() - t0 < duration:
        _pump(conn)
        if _abort:
            break        # _pump devralma gördüyse tek bir komut bile gönderme
        thr = gcs_throttle() if throttle is None else throttle
        _rc(conn, roll=roll, pitch=pitch, throttle=thr, yaw=yaw)
        time.sleep(CONTROL_RATE)


def _angdiff(a, b):
    """a-b farkını [-pi, pi] aralığına sar."""
    d = a - b
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def turn_by(conn, deg, bank=None, timeout=20.0):
    """Heading tabanlı dönüş: hedef yaw'a ulaşana dek FBWA roll komutu.

    Dönüşte hafif up-elevator irtifa kaybını azaltır. 10° toleransta bırakılır
    (FBWA kanatları düzeltirken kalan momentum farkı kapatır).
    """
    if bank is None:
        bank = gcs_sekil()["donus_yatis"]     # arayüzdeki dönüş keskinliği
    _pump(conn)
    if not _att["ok"]:
        hold(conn, 1.0)
        _pump(conn)
    target = _att["yaw"] + math.radians(deg)
    roll_cmd = bank if deg > 0 else -bank
    t0 = time.time()
    while not _abort and time.time() - t0 < timeout:
        _pump(conn)
        if _abort:
            break        # devralma görüldü
        if _att["ok"] and abs(_angdiff(target, _att["yaw"])) < math.radians(10):
            break
        _rc(conn, roll=roll_cmd, pitch=180, throttle=gcs_throttle())
        time.sleep(CONTROL_RATE)


def _read_vehicle_state(conn, wait=1.5):
    """Kısa süre telemetri toplayıp (armed, irtifa_m) döndürür.

    Senaryo geçişinde kritik: önceki senaryo öldürülüp yenisi başlarken araç
    HAVADA. Eski akış havadaki uçağa yerden kalkış prosedürü uyguluyordu
    (warmup + GPS bekleme sırasında RC failsafe → arm_plane'in MANUAL moda
    alması → gaz trim'e düşüp dalış → havada TAKEOFF) ve araç yere çakılıyordu.
    """
    armed = False
    t0 = time.time()
    while time.time() - t0 < wait:
        msg = conn.recv_match(
            type=["HEARTBEAT", "LOCAL_POSITION_NED", "ATTITUDE"],
            blocking=True, timeout=0.3)
        if msg is None:
            continue
        t = msg.get_type()
        if t == "HEARTBEAT" and msg.get_srcSystem() == conn.target_system:
            armed = bool(msg.base_mode
                         & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            _mod["aktif"] = msg.custom_mode
        elif t == "LOCAL_POSITION_NED":
            _pos["z"] = msg.z
        elif t == "ATTITUDE":
            _att.update(roll=msg.roll, pitch=msg.pitch, yaw=msg.yaw, ok=True)
    return armed, -_pos["z"]


def takeoff(conn, climb_time=8.0):
    """Otonom kalkış: TAKEOFF modu motoru açıp TKOFF_ALT'a tırmandırır,
    ardından FBWA'ya geçilip kısa düz uçuşla stabilize edilir."""
    print("[SCN] Otonom kalkış (TAKEOFF modu)...")
    _mod_ayarla(conn, PLANE_MODE_TAKEOFF)
    t0 = time.time()
    while not _abort and time.time() - t0 < climb_time:
        _pump(conn)
        time.sleep(0.2)
    if _abort:
        return
    print(f"[SCN] Kalkış bitti (irtifa ~{-_pos['z']:.0f}m) → FBWA")
    _mod_ayarla(conn, PLANE_MODE_FBWA)
    hold(conn, 2.0)


# ---------------------------------------------------------------------------
# Senaryolar — hepsi süresiz döner, GCS süreci öldürünce biter
# ---------------------------------------------------------------------------

def scenario_square(conn):
    print(f"[SCN] KARE — kenar {gcs_sekil()['kare_kenar']:.1f}s, "
          "90° pusula dönüşleri (ölçüler arayüzden ayarlanır)")
    i = 0
    while not _abort:
        # Her kenarda yeniden okunur: uçuş sırasında arayüzden değiştirince
        # bir sonraki kenar yeni ölçüyle uçulur.
        side = gcs_sekil()["kare_kenar"]
        print(f"[SCN] Kenar {i % 4 + 1}/4 ({side:.1f}s)")
        hold(conn, side)
        if _abort:
            break
        print(f"[SCN] Dönüş {i % 4 + 1}/4 (heading +90°)")
        turn_by(conn, 90)
        i += 1


# ── DAİRE ÇAPLARI (2026-08-05) ──
# Yarıçap yatış açısıyla belirlenir: R = v²/(g·tanθ). Roll komutu FBWA'da
# yatış hedefine ölçeklenir (roll=1000 ≈ 45°). v≈15 m/s için:
#     roll   yatış   yarıçap   yük faktörü   stall hızı×
#      300     14°      96 m       1.03         1.01
#      400     18°      71 m       1.05         1.03
#      500     22°      55 m       1.08         1.04   ← eski tek daire
#      650     29°      41 m       1.15         1.07
#      800     36°      32 m       1.24         1.11
# 40°+ eklenmedi: AIRSPEED_MIN=12 / CRUISE=15 ile stall payı daralıyor.
#
# NEDEN VAR: iç daire nişanının yarıçap-oranlı sürümünü sınamak için hedefin
# FARKLI yarıçaplarda dönmesi gerekiyor. Sabit-metre sürüm (14 m) yalnız
# ~52 m yarıçapta ölçüldü; oranlı sürümün asıl kazancı dar ve geniş dairede
# ortaya çıkar (24 m'de 6.5 m, 80 m'de 21.6 m kayma üretir).
#
# Pitch, yatışla birlikte artar: yatışta düşey kaldırma bileşeni azalır,
# irtifayı korumak için burun biraz yukarı gerekir (kabaca 1/cosθ ile).
DAIRE_CAPLARI = {
    "circle_xl": (300, "çok geniş (~96 m)"),
    "circle_l":  (400, "geniş (~71 m)"),
    "circle":    (500, "orta (~55 m) — referans"),
    "circle_s":  (650, "dar (~41 m)"),
    # ⌀32 (roll 800) KALDIRILDI (2026-08-06, kullanıcı kararı): o kadar sert ve
    # SÜREKLİ bir manevra gerçekçi bir hedef davranışı değil; ayrıca avcı drone
    # orada ivme tavanına dayanıp kontrolü kaybediyordu (v_sürdürülebilir =
    # a_max/ω = 8/0.564 = 14.2 m/s, hedefin hızına eşit → sıfır pay).
    # Geri eklemek gerekirse: "circle_xs": (800, "çok dar (~32 m)")
}


def _daire(conn, roll_cmd, etiket, ayarlanabilir=False):
    """Sabit yatışla süresiz tur. Pitch yatışa göre ölçeklenir (irtifa korunsun).

    ayarlanabilir=True ise her turda arayüzdeki yatış değeri yeniden okunur.
    """
    import math as _m
    yatis_deg = roll_cmd / 1000.0 * 45.0
    pitch_cmd = int(150 * (1.0 / _m.cos(_m.radians(yatis_deg))))
    print(f"[SCN] DAİRE {etiket} — roll={roll_cmd} (~{yatis_deg:.0f}° yatış), "
          f"pitch={pitch_cmd}")
    while not _abort:
        if ayarlanabilir:
            yeni = gcs_sekil()["daire_yatis"]
            if yeni != roll_cmd:
                roll_cmd = yeni
                yatis_deg = roll_cmd / 1000.0 * 45.0
                pitch_cmd = int(150 * (1.0 / _m.cos(_m.radians(yatis_deg))))
                print(f"[SCN] Daire güncellendi — roll={roll_cmd} "
                      f"(~{yatis_deg:.0f}° yatış)")
        hold(conn, 0.5, roll=roll_cmd, pitch=pitch_cmd)


def scenario_circle(conn):
    """
    Ayarlanabilir daire — yatış açısı arayüzden gelir.

    circle_xl/l/s varyantları sabit çaplarda kalır (hazır seçenekler);
    bu senaryo arayüzdeki kaydırıcıyı dinler.
    """
    roll_cmd = gcs_sekil()["daire_yatis"]
    _daire(conn, roll_cmd, "arayüzden ayarlı", ayarlanabilir=True)


TIRMANIS_MIN_THR = 600      # tırmanış/spiral için taban gaz (= THROTTLE_CRUISE)


def tirmanis_throttle():
    """Tırmanış manevralarında gaz: GCS slider'ını dinler ama TABAN uygular.

    Neden taban var: burun yukarıdayken gaz düşük olursa uçak hız kaybedip
    stall eder ve düşer — senaryo biter. Slider daha yükseği isterse ona uyar,
    daha düşüğü isterse tırmanış boyunca tabanda kalır (düz/dönüş kısımlarında
    slider aynen geçerli). Yani "hedefi yavaşlat" isteği çalışır, uçak düşmez.
    """
    return max(gcs_throttle(), TIRMANIS_MIN_THR)


def scenario_aggressive(conn):
    print("[SCN] AGRESİF — rastgele manevralar (gaz: GCS slider'ı)")
    maneuvers = ["climb", "dive", "bank_l", "bank_r", "s_turn", "spiral"]
    while not _abort:
        m = random.choice(maneuvers)
        if m == "climb":
            print("[SCN] Sert tırmanış")
            hold(conn, random.uniform(1.5, 3.0),
                 pitch=random.randint(500, 800), throttle=tirmanis_throttle())
        elif m == "dive":
            # irtifa emniyeti: 40m altındaysa dalma, yerine tırman
            if -_pos["z"] > 40.0:
                print("[SCN] Dalış")
                # dalışta gaz KESİLİR (slider'dan bağımsız) — burun aşağıyken
                # gaz vermek uçağı hedefin yakalanamayacağı hıza fırlatır
                hold(conn, random.uniform(1.0, 2.0),
                     pitch=-random.randint(350, 600), throttle=200)
            else:
                print("[SCN] İrtifa düşük — dalış yerine tırmanış")
                hold(conn, 2.0, pitch=500, throttle=tirmanis_throttle())
        elif m in ("bank_l", "bank_r"):
            s = -1 if m == "bank_l" else 1
            print("[SCN] Sert yatışlı dönüş" + (" (sol)" if s < 0 else " (sağ)"))
            hold(conn, random.uniform(1.5, 3.0),
                 roll=s * random.randint(600, 900), pitch=200)   # throttle=None → slider
        elif m == "s_turn":
            print("[SCN] Keskin S-dönüşü")
            hold(conn, 1.5, roll=-750, pitch=200)                # throttle=None → slider
            hold(conn, 1.5, roll=750, pitch=200)
        elif m == "spiral":
            print("[SCN] Spiral tırmanış")
            hold(conn, random.uniform(3.0, 5.0),
                 roll=450, pitch=450, throttle=tirmanis_throttle())
        # toparlanma: kısa düz uçuş (gaz: slider)
        hold(conn, random.uniform(1.0, 2.0))


SCENARIOS = {
    "square": scenario_square,
    "circle": scenario_circle,
    "aggressive": scenario_aggressive,
}

# Beş daire çapı tek tek kaydedilir (functools.partial yerine varsayılan
# argümanlı lambda: döngü değişkeni geç-bağlanma tuzağına düşmesin).
for _ad, (_roll, _etiket) in DAIRE_CAPLARI.items():
    if _ad != "circle":
        SCENARIOS[_ad] = (lambda c, r=_roll, e=_etiket: _daire(c, r, e))


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "square"
    if name not in SCENARIOS:
        print(f"[SCN] Bilinmeyen senaryo: {name} — seçenekler: {list(SCENARIOS)}")
        sys.exit(2)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    print("=" * 50)
    print(f"[SCN] Uçuş senaryosu: {name.upper()}")
    print("=" * 50)

    _log_ac(name)

    connect_plane()
    conn = get_conn()
    start_gcs_keepalive()
    _akislari_hizlandir(conn)

    armed, alt = _read_vehicle_state(conn)
    if armed and alt > AIRBORNE_ALT_M:
        # HAVADA DEVRALMA — önceki senaryodan/manuelden geçiş. Kalkış YOK;
        # önceki RC override 3 sn içinde düşmeden FBWA + desen devralır.
        print(f"[SCN] Araç zaten havada (irtifa {alt:.0f}m, armlı) — "
              "kalkış atlanıyor, doğrudan FBWA + desen")
        _rc(conn, throttle=gcs_throttle())        # override akışı hemen başlasın
        _mod_ayarla(conn, PLANE_MODE_FBWA, confirm_timeout=0)
        hold(conn, 1.0)                           # düz uçuşla kısa stabilizasyon
    elif armed:
        print(f"[SCN] Armlı ama yerde (irtifa {alt:.0f}m) — doğrudan kalkış")
        takeoff(conn)
    else:
        result = arm_plane(warmup_duration=3.0)
        if result is None or result[1] != 0:
            print("[SCN] ARM başarısız!")
            return
        takeoff(conn)

    if not _abort:
        SCENARIOS[name](conn)

    if _devralindi:
        # PİLOT DEVRALDI → override'ı BIRAK. Cruise gaz göndermek burada
        # yanlış olurdu: override akmaya devam ettiği sürece vericinin
        # çubukları uçağa işlemez, yani pilot kontrolü geri alamaz.
        clear_rc_overrides(conn)
        time.sleep(0.2)
        clear_rc_overrides(conn)
        stop_gcs_keepalive()
        _kayit(f"RC override bırakıldı — kontrol pilotta. "
               f"(pilot kanal hareketi: {_rc_pilot['degisim']} kez)")
        return

    # Durduruldu → nötr yüzey + cruise gazla bırak (manuel mod hemen devralır)
    _rc(conn, throttle=THROTTLE_CRUISE)
    stop_gcs_keepalive()
    _kayit(f"Senaryo sonlandı. (pilot kanal hareketi: "
           f"{_rc_pilot['degisim']} kez)")


if __name__ == "__main__":
    main()
