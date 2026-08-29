#!/usr/bin/env bash
# ==============================================================================
# TALON YAYINCISINI BAŞLATIR  (Talon bilgisayarında çalışır)
# ==============================================================================
# Pixhawk'ın seri portunu AÇAR ve iki yere dağıtır:
#     udp:127.0.0.1:14550  -> talon_arayuz paneli buraya bağlanır
#     udp:<drone-ip>:47800 -> drone bilgisayarına 5 Hz hedef paketi
#
# ⛔ SIRA ÖNEMLİ: ÖNCE bu betik, SONRA talon_arayuz paneli.
#    Seri portu tek süreç açabilir; panel önce açarsa bu betik bağlanamaz.
#
# Kullanım:
#     ./baslat_talon.sh /dev/ttyUSB0 192.168.1.50
#     ./baslat_talon.sh --sahte 192.168.1.50      # Pixhawk yokken
set -u
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd):$(dirname "$(pwd)"):${PYTHONPATH:-}"
kirmizi(){ printf '\033[31m%s\033[0m\n' "$*"; }

if [ "${1:-}" = "--sahte" ]; then
    exec python3 talon/yayinci.py --sahte --hedef "${2:-255.255.255.255}"
fi
PORT="${1:-}"; DRONE_IP="${2:-255.255.255.255}"; BAUD="${3:-57600}"
if [ -z "$PORT" ]; then
    kirmizi "  Kullanim: ./baslat_talon.sh <seri-port> [drone-ip] [baud]"
    echo   "            ./baslat_talon.sh /dev/ttyUSB0 192.168.1.50"
    echo   "            ./baslat_talon.sh --sahte 192.168.1.50"
    echo
    echo   "  Portu bulmak icin:  ls -l /dev/serial/by-id/"
    exit 1
fi
[ -e "$PORT" ] || { kirmizi "  HATA: $PORT yok. SiK telsizi takili mi?"; exit 1; }
[ -w "$PORT" ] || { kirmizi "  HATA: $PORT yazilabilir degil -> sudo usermod -aG dialout \$USER"; exit 1; }
python3 -c "import pymavlink" 2>/dev/null || {
    kirmizi "  HATA: pymavlink yok:  pip install pymavlink"; exit 1; }

echo
echo "  Pixhawk : $PORT @ $BAUD"
echo "  Drone   : udp://$DRONE_IP:47800  (5 Hz hedef paketi)"
echo "  Arayuz  : udp:127.0.0.1:14550"
echo
echo "  SIMDI IKINCI BIR TERMINALDE talon_arayuz'u ac:"
echo "      cd <talon_arayuz>  &&  MAV_ENDPOINT=udp:127.0.0.1:14550 ./baslat.sh udp:127.0.0.1:14550"
echo
exec python3 talon/yayinci.py --port "$PORT" --baud "$BAUD" --hedef "$DRONE_IP"
