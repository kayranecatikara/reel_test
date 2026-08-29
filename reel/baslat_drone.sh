#!/usr/bin/env bash
# ==============================================================================
# DRONE YER KONTROL İSTASYONU  (drone bilgisayarında çalışır)
# ==============================================================================
# ⛔ ÖNCE SKYDAGGER BACKEND'İ HAZIR OLMALI:
#      backend çalışıyor -> /connect -> RC_ENABLE -> (modül MAVİ) -> STOP
#      -> EXTERNAL          (Skydagger rehberi §5, §12)
#    Bu program yalnız RC_US basar; kurulum komutu GÖNDERMEZ (rehber §8).
#
# Kullanım:
#     ./baslat_drone.sh                 # Skydagger (VARSAYILAN), kamera 0
#     ./baslat_drone.sh --gorsel        # + YOLO görsel güdüm
#     ./baslat_drone.sh --tcp           # RC'yi TCP'den bas (varsayılan UDP)
#     ./baslat_drone.sh --sahte-backend # sahte backend'i de kendisi başlatır
set -u
cd "$(dirname "$0")"
export PYTHONPATH="$(pwd):$(dirname "$(pwd)"):${PYTHONPATH:-}"

kirmizi(){ printf '\033[31m%s\033[0m\n' "$*"; }
sari(){    printf '\033[33m%s\033[0m\n' "$*"; }
yesil(){   printf '\033[32m%s\033[0m\n' "$*"; }

# ---- GERÇEK ARAÇ MODELİ (ölçülmüş sabitler) --------------------------------
# ⛔ Bunlar DoW'a değil GERÇEK drone'a aittir.
#    Gerekçeler: dow/gudum/cevirici.py · reel/gercek/dikey.py
export DOW_CEV_MODEL=aci          # Angle modunda çubuk AÇIYA eşlenir
export DOW_CEV_ACI_MAX=60         # Betaflight angle_limit = 60
export DOW_GPS_KAYNAK=gercek      # truth/filtre GERÇEKTE YOK
# ⭐ Y_ISARET = +1.0  (2026-08-29, yer testiyle doğrulandı)
#
#   NE ÖLÇÜLDÜ: pervanesiz yer testinde panel çubuklarına karşı Betaflight'ta
#   roll/pitch/yaw kanalları ve aracın duruş tepkisi kontrol edildi —
#   YÖNLERİN HEPSİ STANDART çıktı (sağa çubuk = sağa yatış).
#
#   NİYE +1 BUNDAN ÇIKIYOR: çeviricinin gövde dönüşümü
#       sag = Y_ISARET · (−vx·sin(yaw) + vy·cos(yaw))
#   Bizim çerçevemizde X=kuzey, Y=doğu, yaw=pusula yönü. Burun kuzeydeyken
#   doğuya hareket SAĞDIR; yukarıdaki ifade Y_ISARET=+1 ile tam bunu verir.
#   Bekçi R6 bu eşitliği sayıyla sınıyor.
#
#   DoW'da −1 İDİ ÇÜNKÜ: oyunun sol-elli ekseni + roll çubuğunun ters
#   uygulanması ölçülmüştü ("+roll aracı SOLA götürüyor"). O, DoW'a özgü bir
#   ARIZAYDI; gerçek araç standart davranıyor.
#
#   ⚠ HÂLÂ AÇIK OLAN: bu, çubuk→araç yönünü doğrular. KAPALI ÇEVRİMİN
#     (güdüm hatayı kapatıyor mu, büyütüyor mu) kesin kanıtı ilk otonom
#     uçuştur. İlk otonom denemede araç hedeften KAÇIYORSA ilk bakılacak
#     yer burasıdır:  DOW_CEV_Y_ISARET=-1.0 ./baslat_drone.sh
export DOW_CEV_Y_ISARET="${DOW_CEV_Y_ISARET:-+1.0}"
export DOW_KAM_KAYNAK="${DOW_KAM_KAYNAK:-0}"

# ---- KUMANDA EKSEN HARİTASI (JUMPER-RC / RadioMaster Pocket, 7 eksen) ----
# ⛔ ÖLÇÜLDÜ, VARSAYILMADI (araclar/kumanda_kalib.py, 2026-08-29) ve
#   Betaflight Receiver sekmesinde gözle DOĞRULANDI.
#   Dördü de "ikinci en büyük 0.00" ile çıktı — hiç belirsizlik yok.
#
#   ⭐ EŞLEME BASİT: eksen N = kanal N+1
#        eksen 0 = ch1 ROLL      eksen 3 = ch4 YAW
#        eksen 1 = ch2 PITCH     eksen 4 = ch5 AUX1 = ARM
#        eksen 2 = ch3 THROTTLE
#   ⚠ Gaz ekseni dinlenmede -0.53 okunuyor ve ORTALANMIYOR (normal).
export DOW_KMD_EKS_ROLL="${DOW_KMD_EKS_ROLL:-0}"
export DOW_KMD_EKS_PITCH="${DOW_KMD_EKS_PITCH:-1}"
export DOW_KMD_EKS_THR="${DOW_KMD_EKS_THR:-2}"
export DOW_KMD_EKS_YAW="${DOW_KMD_EKS_YAW:-3}"
export DOW_KMD_EKS_ARM="${DOW_KMD_EKS_ARM:-4}"
# ⛔⛔ OTONOM İZİN ANAHTARI: -1 = YOK.
#   İkinci kalibrasyonda "KIP" adımı eksen 4 buldu — ama o ARM anahtarıydı
#   (ARM adımında çevrilmemiş, KIP adımında çevrilmişti). Çıktıyı olduğu
#   gibi almak, otonom iznini ARM anahtarına bağlamak olurdu: arm ettiğin
#   anda otonoma da izin vermiş olurdun. İKİ EMNİYET-KRİTİK İŞLEV TEK
#   ANAHTARDA — kabul edilemez.
#   Şimdilik izin PANELDEN geliyor. Kumandada boş bir anahtarı AUX2'ye
#   (kanal 6 = eksen 5) atarsan burayı 5 yap; pilot o zaman otonomu tek
#   hareketle veto edebilir — yerden güdümlü mimaride en güçlü emniyet.
export DOW_KMD_EKS_KIP="${DOW_KMD_EKS_KIP:--1}"

EK=()
SAHTE_BACKEND=0
for x in "$@"; do
    case "$x" in
        --sahte-backend) SAHTE_BACKEND=1 ;;
        --tcp) EK+=(--sky-tasima tcp) ;;
        *) EK+=("$x") ;;
    esac
done

python3 -c "import cv2,numpy" 2>/dev/null || {
    kirmizi "  HATA: paketler eksik:  pip install -r requirements.txt"; exit 1; }

if [ "$SAHTE_BACKEND" = "1" ]; then
    sari "  SAHTE BACKEND başlatılıyor (yalnız sınama — donanım YOK)"
    python3 araclar/sahte_skydagger.py &
    SAHTE_PID=$!
    trap 'kill $SAHTE_PID 2>/dev/null' EXIT
    sleep 1.5
fi

# ---- backend ayakta mı ------------------------------------------------------
if ! python3 - <<'PY'
import socket, sys
try:
    socket.create_connection(("127.0.0.1", 8766), timeout=1.5).close()
except Exception:
    sys.exit(1)
PY
then
    kirmizi "  HATA: Skydagger backend'e ulaşılamıyor (127.0.0.1:8766)"
    echo
    echo "  SIRA (Skydagger rehberi §5):"
    echo "     1) backend'i çalıştır      (skydagger-backend.exe / backend.py)"
    echo "     2) konsolda:  /connect     -> ESP32 seri portu bulunur"
    echo "     3) konsolda:  RC_ENABLE    -> modül MAVİ yanmalı"
    echo "     4) konsolda:  STOP         -> sarı"
    echo "     5) konsolda:  EXTERNAL     -> harici script kabul edilir"
    echo "     6) sonra bu programı çalıştır"
    echo
    echo "  Donanımsız denemek için:  ./baslat_drone.sh --sahte-backend"
    exit 1
fi
yesil "  Skydagger backend: BULUNDU (127.0.0.1:8766)"

[ -e "/dev/video$DOW_KAM_KAYNAK" ] || \
    sari "  UYARI: /dev/video$DOW_KAM_KAYNAK yok — kamera açılmayabilir"

echo
echo "  panel  : http://127.0.0.1:8810"
echo "  ⛔ İlk 5 saniye YALNIZ SAFE basılacak (rehber §8) — modülün"
echo "     MAVİ ışığını o sırada doğrula."
echo
exec python3 drone_yki.py --bag skydagger --kamera "$DOW_KAM_KAYNAK" "${EK[@]}"
