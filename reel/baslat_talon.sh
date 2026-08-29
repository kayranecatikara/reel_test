#!/usr/bin/env bash
# ==============================================================================
# TALON BİLGİSAYARI — yayıncı + kontrol arayüzü, TEK KOMUT
# ==============================================================================
# İki şeyi doğru sırayla başlatır:
#
#   1) talon/yayinci.py   Pixhawk'ın SERİ portunu O AÇAR ve dağıtır:
#                           udp:127.0.0.1:14550  -> kontrol arayüzü
#                           udp:<drone-ip>:47800 -> drone bilgisayarı (5 Hz hedef)
#   2) talon/arayuz       yer kontrol arayüzü (http://localhost:8000)
#
# ⛔ SIRA DEĞİŞMEZ: seri portu TEK süreç açabilir. Arayüz önce açarsa
#   yayıncı porta erişemez ve drone hedef konumunu HİÇ alamaz.
#
# Kullanım:
#   ./baslat_talon.sh                          port kendi bulunur, yayın=broadcast
#   ./baslat_talon.sh /dev/ttyUSB0 192.168.1.50
#   ./baslat_talon.sh --sahte 192.168.1.50     Pixhawk yokken (daire çizen sahte Talon)
#   ./baslat_talon.sh --kapat                  yalnız kapat
set -u
cd "$(dirname "$0")"
KOK="$(pwd)"
export PYTHONPATH="$KOK:$(dirname "$KOK"):${PYTHONPATH:-}"

kirmizi(){ printf '\033[31m%s\033[0m\n' "$*"; }
sari(){    printf '\033[33m%s\033[0m\n' "$*"; }
yesil(){   printf '\033[32m%s\033[0m\n' "$*"; }

# ---- önceki örnekleri temizle (desenler köşeli parantezle kırık, §9) ----
temizle() {
    local v=0
    for d in "[y]ayinci" "[g]cs.sunucu"; do
        pgrep -f "$d" >/dev/null 2>&1 && { v=1; pkill -f "$d" 2>/dev/null || true; }
    done
    [ "$v" = "1" ] && { sari "  önceki Talon süreçleri kapatıldı"; sleep 1; }
    for d in "[y]ayinci" "[g]cs.sunucu"; do pkill -9 -f "$d" 2>/dev/null || true; done
    return 0
}
[ "${1:-}" = "--kapat" ] && { temizle; yesil "  kapatıldı."; exit 0; }
temizle

python3 -c "import pymavlink, flask" 2>/dev/null || {
    kirmizi "  HATA: paketler eksik:  pip install -r talon/arayuz/requirements.txt"
    exit 1; }

# ---- argümanlar ----
SAHTE=0
if [ "${1:-}" = "--sahte" ]; then SAHTE=1; DRONE_IP="${2:-255.255.255.255}"
else
    PORT="${1:-}"
    DRONE_IP="${2:-255.255.255.255}"
    BAUD="${3:-57600}"
    if [ -z "$PORT" ]; then
        for a in /dev/serial/by-id/* /dev/ttyUSB* /dev/ttyACM*; do
            [ -e "$a" ] && PORT="$a" && break
        done
    fi
    if [ -z "${PORT:-}" ] || [ ! -e "$PORT" ]; then
        kirmizi "  HATA: seri port bulunamadı."
        echo   "        ls -l /dev/serial/by-id/"
        echo   "        Pixhawk yokken:  ./baslat_talon.sh --sahte <drone-ip>"
        exit 1
    fi
    [ -w "$PORT" ] || { kirmizi "  HATA: $PORT yazılabilir değil"
        echo "        sudo usermod -aG dialout \$USER   (sonra ÇIK-GİR)"; exit 1; }
fi

# ---- 1) yayıncı ----
echo
if [ "$SAHTE" = "1" ]; then
    sari "  YAYINCI: SAHTE Talon (200 m yarıçaplı daire, 22 m/s, 40 m)"
    python3 talon/yayinci.py --sahte --hedef "$DRONE_IP" &
else
    echo "  YAYINCI: $PORT @ $BAUD  ->  udp:14550 (arayüz) + udp://$DRONE_IP:47800 (drone)"
    python3 talon/yayinci.py --port "$PORT" --baud "$BAUD" --hedef "$DRONE_IP" &
fi
YPID=$!
trap 'kill $YPID 2>/dev/null; pkill -f "[g]cs.sunucu" 2>/dev/null' EXIT INT TERM
sleep 3

if ! kill -0 $YPID 2>/dev/null; then
    kirmizi "  ⛔ yayıncı başlayamadı — yukarıdaki hataya bak"
    exit 1
fi

# ---- 2) kontrol arayüzü (yayıncının UDP aynasına bağlanır) ----
echo
echo "  ARAYÜZ : http://localhost:8000   (udp:127.0.0.1:14550 üzerinden)"
echo
yesil "  ⭐ Talon kontrolü, rota çizme ve GÖREV YÜKLEME arayüzden yapılır."
echo   "     Serbest waypoint planı için:  python3 talon/gorev_plani.py --yardim"
echo
echo "  Ctrl+C ile ikisi birden kapanır."
echo
cd talon/arayuz
# ⛔ İKİ AYRI DEĞİŞKEN — arayüzün kendi tasarımı (gcs/sunucu.py ~2244):
#     GCS_ENDPOINT : panelin KENDİ bağlantısı        -> yayıncı aynası 14552
#     MAV_ENDPOINT : arayüzün ALT SÜREÇLERİ (preflight, senaryo) -> 14550
#   Aynı porta iki soket bağlanırsa çekirdek her datagramı yalnız BİRİNE
#   verir ve İKİSİ DE YARI KÖR kalır — arayüzün kendi belgesinde yazılı,
#   18 Ağu 2026'da yaşanmış bir arıza.
export GCS_ENDPOINT="udp:127.0.0.1:14552"
export MAV_ENDPOINT="udp:127.0.0.1:14550"
export MAV_BAUD=57600
export MAV_ALLOW_FORCE_ARM=0
export PYTHONPATH="$(pwd):${PYTHONPATH}"
exec python3 -m gcs.sunucu
