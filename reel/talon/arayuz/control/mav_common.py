"""
mav_common.py — MAVLink ortak yardımcıları (ArduPilot / ArduPlane).

Bu modül plane_functions, plane_patterns ve run_plane_scenario'nun ortak
altyapısıdır. Hem SITL (UDP) hem gerçek uçuş bilgisayarı (seri port) ile
çalışır.

BAĞLANTI SEÇİMİ
---------------
connect_mavlink() bağlantı adresini şu sırayla belirler:

1. MAV_ENDPOINT ortam değişkeni (varsa her şeyi ezer)
     export MAV_ENDPOINT=COM3                → seri (Windows)
     export MAV_ENDPOINT=udp:127.0.0.1:14542 → UDP
2. Fonksiyona verilen `port` argümanı:
     int      → udp:127.0.0.1:<port>   (SITL alışkanlığı korunur)
     "COM…"   → seri port (Windows), "/dev/…" → seri port (Linux)
     "udp:…"  → doğrudan pymavlink adresi

Yani SiK telsiziyle uçarken iki satır yeter:
     set MAV_ENDPOINT=COM3
     set MAV_BAUD=57600

GÜVENLİK NOTU — FORCE ARM
-------------------------
arm(force=True) ArduPilot'un pre-arm kontrollerini ATLAR (magic 2989). SITL'de
pratiktir; GERÇEK UÇAKTA tehlikelidir çünkü EKF/pusula/GPS sağlıksızken de
motoru çalıştırır. Gerçek donanımda force arm'ı kapatmak için:
     export MAV_ALLOW_FORCE_ARM=0
Bu ayarla force=True istekleri normal arm'a düşer ve pre-arm kontrolleri işler.
"""

import os
import time
import threading

from pymavlink import mavutil


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

# RC override yalnızca SYSID_MYGCS kaynaklı paketlerden kabul edilir.
# ArduPilot varsayılanı 255'tir; bağlantı bu source_system ile kurulur.
GCS_SOURCE_SYSTEM = 255

# BİLEŞEN KİMLİĞİ AYRIMI — aynı anda çalışan süreçler için ŞART.
#
# Yer kontrol arayüzü (gcs.sunucu) ve senaryo/komut araçları aynı anda
# çalışıyor. İkisi de aynı (sistem, bileşen) çiftini kullanırsa otopilot
# onları TEK bir yer istasyonu sanar ve paketler karışır: 8 Ağu 2026'da
# ölçüldü — arayüz açıkken gönderilen RC override komutlarının bir kısmı
# hiç ulaşmadı (CH1=1200 gönderildi, Pixhawk RC1=1500 aldı), servo çıkışı
# donuk kaldı. Arayüz kapatılınca aynı test sorunsuz geçti.
#
# Sistem ID'si 255 KALMALI (SYSID_MYGCS eşleşmesi RC override'ın şartı);
# ArduPilot bileşen ID'sine bakmaz, o yüzden ayırmak güvenli.
GCS_SOURCE_COMPONENT = mavutil.mavlink.MAV_COMP_ID_ONBOARD_COMPUTER   # 191
# Yer kontrol arayüzü bunu kullanır (gcs/sunucu.py açıkça geçirir).
#
# 190 (MISSIONPLANNER) KULLANILMAZ: Mission Planner'ın kendi varsayılan
# bileşen kimliği odur. Uçuşta SiK radyo üzerinden MP, WiFi üzerinden arayüz
# aynı anda bağlı olacak; ikisi de (255,190) görünürse otopilot onları tek
# istemci sanar ve paketler karışır — 8 Ağu'da senaryo/arayüz arasında bu
# yaşandı, komutların bir kısmı hiç ulaşmadı.
#
# Uçuştaki kimlik dağılımı:
#     (255, 190) → Mission Planner   (SiK / TELEM1)
#     (255, 191) → senaryolar, komut araçları
#     (255, 192) → yer kontrol arayüzü
ARAYUZ_SOURCE_COMPONENT = mavutil.mavlink.MAV_COMP_ID_ONBOARD_COMPUTER2  # 192

# ArduPlane flight mode numaraları (custom_mode alanı)
PLANE_MODE_MANUAL = 0
PLANE_MODE_CIRCLE = 1
PLANE_MODE_STABILIZE = 2
PLANE_MODE_TRAINING = 3
PLANE_MODE_ACRO = 4
PLANE_MODE_FBWA = 5
PLANE_MODE_FBWB = 6
PLANE_MODE_CRUISE = 7
PLANE_MODE_AUTOTUNE = 8
PLANE_MODE_AUTO = 10
PLANE_MODE_RTL = 11
PLANE_MODE_LOITER = 12
PLANE_MODE_TAKEOFF = 13
PLANE_MODE_AVOID_ADSB = 14
PLANE_MODE_GUIDED = 15
PLANE_MODE_QSTABILIZE = 17
PLANE_MODE_QLOITER = 19
PLANE_MODE_QLAND = 20
PLANE_MODE_QRTL = 21

PLANE_MODE_NAMES = {
    0: "MANUAL", 1: "CIRCLE", 2: "STABILIZE", 3: "TRAINING", 4: "ACRO",
    5: "FBWA", 6: "FBWB", 7: "CRUISE", 8: "AUTOTUNE", 10: "AUTO", 11: "RTL",
    12: "LOITER", 13: "TAKEOFF", 14: "AVOID_ADSB", 15: "GUIDED",
    16: "INITIALISING",
    17: "QSTABILIZE", 18: "QHOVER", 19: "QLOITER", 20: "QLAND", 21: "QRTL",
    22: "QAUTOTUNE", 23: "QACRO", 24: "THERMAL", 25: "LOITER_ALT_QLAND",
    # AUTOLAND (ArduPlane 4.6+, mode.h Number::AUTOLAND = 26): kalkışta
    # yakalanan yön boyunca kendiliğinden iniş yapar. Görevde DO_LAND_START
    # aramaz, bu yüzden RTL'den farklıdır — bkz. gcs/sunucu.py api_inis.
    26: "AUTOLAND",
}

# ArduPilot force-arm/disarm magic sayısı (COMPONENT_ARM_DISARM param2)
ARM_FORCE_MAGIC = 2989

# SiK telsiz linkinin hızı. Bu kurulumda tek seri yol o, bu yüzden MAV_BAUD
# verilmediğinde doğru varsayılan budur.
DEFAULT_SERIAL_BAUD = 57600


def _force_arm_allowed() -> bool:
    """MAV_ALLOW_FORCE_ARM=0 ise force arm istekleri normal arm'a düşer."""
    return os.environ.get("MAV_ALLOW_FORCE_ARM", "1") not in ("0", "false", "no")


# ---------------------------------------------------------------------------
# Zaman
# ---------------------------------------------------------------------------

def timestamp_ms() -> int:
    """Unix epoch milisaniye (MAVLink time_boot_ms alanları için)."""
    return int(time.time() * 1000)


def timestamp_us() -> int:
    """Unix epoch mikrosaniye."""
    return int(time.time() * 1e6)


# ---------------------------------------------------------------------------
# Bağlantı
# ---------------------------------------------------------------------------

def _resolve_endpoint(port):
    """(adres, baud) çiftini çözer. Bkz. modül başlığı."""
    baud = int(os.environ.get("MAV_BAUD", DEFAULT_SERIAL_BAUD))

    env = os.environ.get("MAV_ENDPOINT")
    if env:
        return env, baud

    if isinstance(port, int):
        # SITL alışkanlığı: çıplak port numarası = yerel UDP dinleme
        return f"udp:127.0.0.1:{port}", baud

    return str(port), baud


def connect_mavlink(port=14542, source_system: int = GCS_SOURCE_SYSTEM,
                    source_component: int = GCS_SOURCE_COMPONENT,
                    wait_heartbeat: bool = True,
                    heartbeat_timeout: float = 30.0,
                    request_streams: bool = True):
    """
    MAVLink bağlantısı kurar ve araçtan heartbeat bekler.

    source_system=255 kritiktir: ArduPilot RC override'ı yalnızca SYSID_MYGCS
    ile eşleşen kaynaktan kabul eder.

    Args:
        port: int (UDP portu), "COM3" / "/dev/ttyUSB0" veya "udp:host:port"
        source_system: Gönderen sistem ID'si (RC override için 255 olmalı)
        wait_heartbeat: Araç heartbeat'i beklensin mi
        request_streams: ATTITUDE/POSITION telemetri akışları istensin mi
                         (gerçek donanımda şart — varsayılan hızlar düşüktür)

    Returns:
        mavutil bağlantı nesnesi (target_system/target_component doldurulmuş)
    """
    address, baud = _resolve_endpoint(port)
    is_serial = address.startswith("/dev/") or address.startswith("COM")

    if is_serial:
        print(f"[MAV] Seri bağlantı: {address} @ {baud} baud")
        conn = mavutil.mavlink_connection(
            address, baud=baud,
            source_system=source_system,
            source_component=source_component,
        )
    else:
        print(f"[MAV] Ağ bağlantısı: {address}")
        conn = mavutil.mavlink_connection(
            address,
            source_system=source_system,
            source_component=source_component,
        )

    # BURADAN SONRA HER HATA SOKETİ KAPATMAK ZORUNDA.
    #
    # mavlink_connection portu HEMEN bind eder; heartbeat beklemesi ondan
    # sonra gelir. Zaman aşımında istisna fırlatıp soketi açık bırakırsak
    # bind edilmiş halde sızar ve HER denemede bir tane daha eklenir.
    #
    # Sonuç sinsi: çekirdek aynı UDP portuna bağlı soketlerden gelen her
    # datagramı yalnızca BİRİNE verir. Sonunda kurulan canlı bağlantı, ölü
    # soketlerle datagram paylaşmaya başlar ve telemetri rastgele "susar" —
    # panel "bağlantı yok" gösterir, oysa araç yayın yapmaktadır.
    #
    # (22 Ağu 2026: köprü çökmüşken panel 2.5 saat yeniden bağlanmayı
    # denedi ve `ss -ulpn` tek süreçte 14552'ye bağlı 29 soket gösterdi.
    # gcs/sunucu.py'deki koruma bunu yakalayamıyordu: istisna connect_mavlink
    # DÖNMEDEN fırladığı için çağıranın elinde kapatacak bir nesne olmuyor.
    # Kapatma sorumluluğu bu yüzden soketi açan yere, buraya taşındı.)
    try:
        if wait_heartbeat:
            print(f"[MAV] Araç heartbeat'i bekleniyor (max {heartbeat_timeout:.0f}s)...")
            hb = conn.wait_heartbeat(timeout=heartbeat_timeout)
            if hb is None:
                raise ConnectionError(
                    f"[MAV] {address} üzerinden heartbeat alınamadı. "
                    "Kablo/baud/port ayarlarını ve uçuş kontrolcüsünün açık "
                    "olduğunu kontrol edin."
                )
            print(f"[MAV] Bağlandı — sistem {conn.target_system}, "
                  f"bileşen {conn.target_component}")

        if request_streams and conn.target_system:
            request_default_streams(conn)
    except BaseException:
        # BaseException: KeyboardInterrupt de soketi sızdırmasın.
        try:
            conn.close()
        except Exception:
            pass
        raise

    return conn


def dar_bant_mi() -> bool:
    """
    Bağlantı SiK gibi dar bantlı bir telsiz linki mi?

    Ayrım seri/UDP değil BAUD üzerinden: doğrudan USB bağlantısı da seridir
    ama yüksek baud'dur ve hiçbir darlığı yoktur.
    """
    address, baud = _resolve_endpoint(14542)
    if address.lower().startswith(("udp", "tcp")):
        return False
    return baud <= 115200


def request_default_streams(conn, rate_hz: float = None):
    """
    Kontrol döngülerinin ihtiyaç duyduğu telemetri akışlarını ister.

    Gerçek uçuş kontrolcüsünde bu ADIM ATLANAMAZ: SITL bol telemetri yollar
    ama gerçek linkte akış hızları düşüktür ve ATTITUDE seyrek gelir.
    run_plane_scenario'nun pusula tabanlı dönüşü ATTITUDE'a bağlıdır.

    DAR BANTTA (SiK) İKİ ŞEY DEĞİŞİR:
      * Hız 10 Hz yerine 2 Hz istenir.
      * MAV_DATA_STREAM_ALL yedeği HİÇ GÖNDERİLMEZ.

    NEDEN: MAV_DATA_STREAM_ALL, aracın O KANALDAKİ BÜTÜN akışlarını istenen
    hıza çeker — panelin hiç okumadığı RAW_IMU, VIBRATION, EKF_STATUS_REPORT,
    POSITION_TARGET_GLOBAL_INT dahil. Ve bu ayar çalışma zamanında KALICIDIR:
    aracı yeniden başlatana kadar sürer. Yani bu fonksiyonu SiK üzerinden bir
    kez çalıştıran herhangi bir CLI aracı, linki kendisinden sonra açılan
    panel için de bozar.

    22 Ağu 2026, gerçek SiK linkinde ölçüldü: araç 4502 B/s yolluyordu, bunun
    4000 B/s'i (%89) hiç kullanılmayan mesajlardı. Link ~2500-3500 B/s
    taşıyabildiği için UPLINK ÖLDÜ — 60 saniyede 62 istek, 0 yanıt.
    """
    if rate_hz is None:
        rate_hz = 2.0 if dar_bant_mi() else 10.0
    interval_us = int(1e6 / rate_hz)
    wanted = [
        mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE,
        mavutil.mavlink.MAVLINK_MSG_ID_LOCAL_POSITION_NED,
        mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD,
        mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
        # RC_CHANNELS: verici anahtarıyla senaryo tetikleme (gcs.sunucu) ve
        # pilot müdahalesi izleme (run_plane_scenario) buna bağlı.
        mavutil.mavlink.MAVLINK_MSG_ID_RC_CHANNELS,
    ]
    for msg_id in wanted:
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0,
            msg_id, interval_us, 0, 0, 0, 0, 0,
        )
        time.sleep(0.02)

    # Eski firmware'ler SET_MESSAGE_INTERVAL'i yok sayabilir — klasik
    # REQUEST_DATA_STREAM'i yedek olarak gönderiyoruz. DAR BANTTA GÖNDERMİYORUZ:
    # yukarıdaki açıklamaya bakın, bu tek mesaj linki tek başına doyuruyor.
    if dar_bant_mi():
        print(f"[MAV] Telemetri akışları istendi ({rate_hz:.0f} Hz, DAR BANT — "
              f"MAV_DATA_STREAM_ALL gönderilmedi)")
    else:
        conn.mav.request_data_stream_send(
            conn.target_system, conn.target_component,
            mavutil.mavlink.MAV_DATA_STREAM_ALL, int(rate_hz), 1,
        )
        print(f"[MAV] Telemetri akışları istendi ({rate_hz:.0f} Hz)")


# ---------------------------------------------------------------------------
# Mesaj yardımcıları
# ---------------------------------------------------------------------------

def drain_messages(conn, max_messages: int = 500):
    """
    Bekleyen tüm mesajları tüketip atar.

    Komut döngüleri hiç okuma yapmazsa soket/seri tamponu dolar ve telemetri
    bayatlar. max_messages, yoğun linkte döngünün kilitlenmesini önler.

    Returns:
        Atılan mesaj sayısı
    """
    count = 0
    while count < max_messages:
        if conn.recv_match(blocking=False) is None:
            break
        count += 1
    return count


def wait_ack(conn, command: int, timeout: float = 3.0):
    """
    Belirli bir komut için COMMAND_ACK bekler.

    Returns:
        (command, result) tuple — result 0 (MAV_RESULT_ACCEPTED) ise başarı.
        Zaman aşımında None.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = conn.recv_match(type="COMMAND_ACK", blocking=True,
                              timeout=max(0.1, deadline - time.time()))
        if msg is None:
            continue
        if msg.command == command:
            return (msg.command, msg.result)
    return None


def get_message(conn, msg_type: str, timeout: float = 1.0):
    """Belirtilen tipte tek mesaj okur (yoksa None)."""
    return conn.recv_match(type=msg_type, blocking=True, timeout=timeout)


# ---------------------------------------------------------------------------
# Arm / Disarm
# ---------------------------------------------------------------------------

def _arm_disarm(conn, arm_flag: int, force: bool, retries: int,
                retry_interval: float, ack_timeout: float = 3.0):
    """arm/disarm ortak gövdesi."""
    cmd = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM

    use_force = force and _force_arm_allowed()
    if force and not use_force:
        print("[MAV] MAV_ALLOW_FORCE_ARM=0 — force atlandı, normal arm "
              "deneniyor (pre-arm kontrolleri işleyecek)")
    magic = ARM_FORCE_MAGIC if use_force else 0

    result = None
    for attempt in range(1, retries + 1):
        conn.mav.command_long_send(
            conn.target_system, conn.target_component,
            cmd, 0,
            float(arm_flag), float(magic), 0, 0, 0, 0, 0,
        )
        result = wait_ack(conn, cmd, timeout=ack_timeout)

        if result and result[1] == mavutil.mavlink.MAV_RESULT_ACCEPTED:
            return result

        label = "ARM" if arm_flag else "DISARM"
        reason = f"result={result[1]}" if result else "ACK yok"
        print(f"[MAV] {label} denemesi {attempt}/{retries} başarısız ({reason})")

        # Reddedilme sebebi genelde STATUSTEXT'te (PreArm: ...) gelir
        st = conn.recv_match(type="STATUSTEXT", blocking=False)
        if st is not None:
            text = st.text.decode() if isinstance(st.text, bytes) else st.text
            print(f"[MAV] Araç mesajı: {text}")

        if attempt < retries:
            time.sleep(retry_interval)

    return result


def arm(conn, force: bool = False, retries: int = 5,
        retry_interval: float = 2.0):
    """
    Aracı arm eder.

    Args:
        force: True ise ArduPilot force-arm magic'i (2989) kullanılır —
               pre-arm kontrollerini ATLAR. Gerçek uçuşta dikkat;
               MAV_ALLOW_FORCE_ARM=0 ile kapatılabilir.

    Returns:
        (command, result) tuple veya None. result == 0 → başarı.
    """
    return _arm_disarm(conn, 1, force, retries, retry_interval)


def disarm(conn, force: bool = False, retries: int = 5,
           retry_interval: float = 1.0):
    """
    Aracı disarm eder.

    Returns:
        (command, result) tuple veya None. result == 0 → başarı.
    """
    return _arm_disarm(conn, 0, force, retries, retry_interval)


def is_armed(conn, timeout: float = 2.0):
    """
    Aracın arm durumunu HEARTBEAT'ten okur.

    Returns:
        True/False, heartbeat gelmezse None.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
        if msg is not None and msg.get_srcSystem() == conn.target_system:
            return bool(msg.base_mode
                        & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
    return None


# ---------------------------------------------------------------------------
# Mod değiştirme
# ---------------------------------------------------------------------------

def set_mode(conn, mode: int, confirm_timeout: float = 3.0,
             retries: int = 3):
    """
    Uçuş modunu değiştirir (ArduPlane custom_mode numarası ile).

    Args:
        mode: PLANE_MODE_* sabitlerinden biri
        confirm_timeout: HEARTBEAT ile mod doğrulaması için süre.
                         0 verilirse komut gönderilir, doğrulama BEKLENMEZ
                         (havada devralma gibi gecikmeye tahammülsüz yerlerde).

    Returns:
        True (doğrulandı / doğrulama istenmedi), False (doğrulanamadı)
    """
    name = PLANE_MODE_NAMES.get(mode, str(mode))

    for attempt in range(1, retries + 1):
        conn.mav.set_mode_send(
            conn.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode,
        )

        if confirm_timeout <= 0:
            print(f"[MAV] Mod komutu gönderildi: {name} ({mode}) — doğrulama yok")
            return True

        deadline = time.time() + confirm_timeout
        while time.time() < deadline:
            msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
            if msg is None:
                continue
            if msg.get_srcSystem() != conn.target_system:
                continue
            if msg.custom_mode == mode:
                print(f"[MAV] Mod: {name} ({mode})")
                return True

        if attempt < retries:
            print(f"[MAV] Mod {name} doğrulanamadı, tekrar deneniyor "
                  f"({attempt}/{retries})")

    print(f"[MAV] UYARI: Mod {name} ({mode}) doğrulanamadı")
    return False


def get_mode(conn, timeout: float = 2.0):
    """
    Aktif uçuş modunu döndürür.

    Returns:
        (mode_num, mode_name) veya None
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=0.5)
        if msg is not None and msg.get_srcSystem() == conn.target_system:
            m = msg.custom_mode
            return (m, PLANE_MODE_NAMES.get(m, str(m)))
    return None


# ---------------------------------------------------------------------------
# Telemetri okuma
# ---------------------------------------------------------------------------

def get_local_position(conn, timeout: float = 1.0):
    """
    LOCAL_POSITION_NED okur.

    Returns:
        {"x","y","z","vx","vy","vz"} — z NED'dir (AŞAĞI pozitif),
        irtifa için -z kullanın. Mesaj gelmezse None.
    """
    msg = conn.recv_match(type="LOCAL_POSITION_NED", blocking=True,
                          timeout=timeout)
    if msg is None:
        return None
    return {
        "x": msg.x, "y": msg.y, "z": msg.z,
        "vx": msg.vx, "vy": msg.vy, "vz": msg.vz,
    }


def get_attitude(conn, timeout: float = 1.0):
    """
    ATTITUDE okur.

    Returns:
        {"roll","pitch","yaw","rollspeed","pitchspeed","yawspeed"} — RADYAN.
        Mesaj gelmezse None.
    """
    msg = conn.recv_match(type="ATTITUDE", blocking=True, timeout=timeout)
    if msg is None:
        return None
    return {
        "roll": msg.roll, "pitch": msg.pitch, "yaw": msg.yaw,
        "rollspeed": msg.rollspeed, "pitchspeed": msg.pitchspeed,
        "yawspeed": msg.yawspeed,
    }


def get_global_position(conn, timeout: float = 1.0):
    """
    GLOBAL_POSITION_INT okur.

    Returns:
        {"lat","lon","alt","rel_alt","hdg"} — derece/metre. Yoksa None.
    """
    msg = conn.recv_match(type="GLOBAL_POSITION_INT", blocking=True,
                          timeout=timeout)
    if msg is None:
        return None
    return {
        "lat": msg.lat / 1e7,
        "lon": msg.lon / 1e7,
        "alt": msg.alt / 1000.0,
        "rel_alt": msg.relative_alt / 1000.0,
        "hdg": msg.hdg / 100.0 if msg.hdg != 65535 else None,
    }


def get_gps_status(conn, timeout: float = 1.0):
    """
    GPS_RAW_INT okur.

    Returns:
        {"fix_type","satellites","hdop"} veya None. fix_type >= 3 → 3D fix.
    """
    msg = conn.recv_match(type="GPS_RAW_INT", blocking=True, timeout=timeout)
    if msg is None:
        return None
    return {
        "fix_type": msg.fix_type,
        "satellites": msg.satellites_visible,
        "hdop": msg.eph / 100.0 if msg.eph != 65535 else None,
    }


def get_battery(conn, timeout: float = 1.0):
    """
    SYS_STATUS'tan batarya durumu okur.

    Returns:
        {"voltage","current","remaining"} veya None.
    """
    msg = conn.recv_match(type="SYS_STATUS", blocking=True, timeout=timeout)
    if msg is None:
        return None
    return {
        "voltage": msg.voltage_battery / 1000.0,
        "current": msg.current_battery / 100.0 if msg.current_battery != -1 else None,
        "remaining": msg.battery_remaining if msg.battery_remaining != -1 else None,
    }


# ---------------------------------------------------------------------------
# GCS Heartbeat / Keepalive
# ---------------------------------------------------------------------------

def send_gcs_heartbeat(conn):
    """
    Tek bir GCS heartbeat'i gönderir.

    ArduPilot GCS failsafe'i (FS_GCS_ENABL) bu heartbeat'lerin kesilmesini
    bağlantı kaybı sayar. RC override kullanan kontrol döngülerinde bu akışın
    sürmesi şarttır.
    """
    conn.mav.heartbeat_send(
        mavutil.mavlink.MAV_TYPE_GCS,
        mavutil.mavlink.MAV_AUTOPILOT_INVALID,
        0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
    )


class GCSKeepalive:
    """
    Arka planda düzenli GCS heartbeat'i gönderen thread.

    plane_functions._keepalive._running alanını okuduğu için bu isim korundu.

    Kullanım:
        ka = GCSKeepalive(conn, interval=0.1)
        ka.start()
        ...
        ka.stop()
    """

    def __init__(self, conn, interval: float = 1.0):
        self.conn = conn
        self.interval = interval
        self._running = False
        self._thread = None

    def start(self):
        """Heartbeat thread'ini başlatır (zaten çalışıyorsa bir şey yapmaz)."""
        if self._running:
            return self
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="GCSKeepalive", daemon=True)
        self._thread.start()
        print(f"[MAV] GCS keepalive başladı ({1.0 / self.interval:.0f} Hz)")
        return self

    def _loop(self):
        while self._running:
            try:
                send_gcs_heartbeat(self.conn)
            except Exception as exc:
                # Bağlantı koptuysa thread'i öldürme: kontrol döngüsü kendi
                # hata yolunu işletsin, keepalive link dönerse devam etsin.
                print(f"[MAV] Keepalive heartbeat hatası: {exc}")
            time.sleep(self.interval)

    def stop(self, join_timeout: float = 2.0):
        """Thread'i durdurur ve sonlanmasını bekler."""
        if not self._running:
            return
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=join_timeout)
            self._thread = None
        print("[MAV] GCS keepalive durdu")


# ---------------------------------------------------------------------------
# Parametre okuma/yazma
# ---------------------------------------------------------------------------

def get_param(conn, name: str, timeout: float = 5.0):
    """
    Tek bir araç parametresini okur (ör. "SYSID_MYGCS").

    Returns:
        float değer veya None.
    """
    conn.mav.param_request_read_send(
        conn.target_system, conn.target_component,
        name.encode("utf-8"), -1,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.5)
        if msg is None:
            continue
        pid = msg.param_id
        if isinstance(pid, bytes):
            pid = pid.decode("utf-8")
        if pid.strip("\x00") == name:
            return msg.param_value
    return None


def set_param(conn, name: str, value: float,
              param_type: int = mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
              timeout: float = 5.0):
    """
    Araç parametresi yazar ve araçtan gelen yankı ile doğrular.

    Returns:
        Yazılan değer (doğrulanmışsa) veya None.
    """
    conn.mav.param_set_send(
        conn.target_system, conn.target_component,
        name.encode("utf-8"), float(value), param_type,
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=0.5)
        if msg is None:
            continue
        pid = msg.param_id
        if isinstance(pid, bytes):
            pid = pid.decode("utf-8")
        if pid.strip("\x00") == name:
            print(f"[MAV] Parametre {name} = {msg.param_value}")
            return msg.param_value
    print(f"[MAV] UYARI: {name} parametresi doğrulanamadı")
    return None


# ---------------------------------------------------------------------------
# Acil durum
# ---------------------------------------------------------------------------

def clear_rc_overrides(conn):
    """
    Tüm RC override kanallarını serbest bırakır (0 = override yok).

    Kontrol döngüsünden çıkarken çağrılmalıdır; aksi halde araç override
    zaman aşımına (RC_OVERRIDE_TIME, ~3 sn) kadar son komutta kalır.
    """
    conn.mav.rc_channels_override_send(
        conn.target_system, conn.target_component,
        0, 0, 0, 0, 0, 0, 0, 0,
    )


def emergency_rtl(conn):
    """Acil durumda RTL moduna alır (Return To Launch)."""
    print("[MAV] ACİL: RTL moduna geçiliyor")
    clear_rc_overrides(conn)
    return set_mode(conn, PLANE_MODE_RTL)
