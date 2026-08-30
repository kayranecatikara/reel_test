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
# ⛔ "oto": yakalama kartını KENDİ BULUR. Varsayılan 0 iken panelde
#   dizüstünün DAHİLİ kamerası çıkıyordu (sahada görüldü 2026-08-29).
#   Elle seçmek gerekirse:  DOW_KAM_KAYNAK=/dev/video2 ./baslat_drone.sh

# ---- DEDEKTÖR (YOLO) -------------------------------------------------------
# ⭐ GERÇEK GÖRÜNTÜYLE EĞİTİLMİŞ MODEL (2026-08-29)
#   modeller/tayarti_v1.pt · yolo26s · tek sınıf "tayarti" · 100 epoch
#   ⚠ imgsz=640 ile EĞİTİLDİ. Sim modeli (talon_v3) 960 ile eğitilmişti.
export DOW_MODEL="${DOW_MODEL:-tayarti_v1}"

# ⛔ ÇÖZÜNÜRLÜK — sim sayıları OLDUĞU GİBİ KULLANILAMAZ.
#
#   Sim kadrajı 1920x1080'di ve orada imgsz=1920 demek ölçek katsayısı
#   TAM 1.0, yani NATİF piksel demekti. Gerçek FPV zinciri 640x480 veriyor;
#   orada imgsz=1920 demek 3 KAT BÜYÜTME — yeni bilgi eklemez, yalnız
#   pahalıdır. ÖLÇÜLDÜ (RTX 4060, 640x480 kare, yolo26s):
#
#       imgsz   ms/kare   FPS
#         640      5.3    189     <- modelin eğitim boyutu, karenin natifi
#         960      9.1    110
#        1280     16.7     60
#        1920     44.0     23     <- sim varsayılanı, 8.3 KAT yavaş
#
#   ⛔ SEÇİM DÜZELTİLDİ 2026-08-29 — İLK SEÇİM YANLIŞTI, ÖLÇÜMLE ÇÜRÜDÜ.
#
#   Önce "uzak 960" koymuştum: küçük hedefi büyütmek ağın öznitelik
#   haritasında daha çok piksel verir diye. GERÇEK KAREDE ÖLÇÜLDÜ
#   (Talon kadrajda, 259 px genişliğinde):
#
#       imgsz    güven
#         640    0.746    ✔ eşiğin (0.40) ÜSTÜNDE
#         960    0.266    ✗ eşiğin ALTINDA -> panel kutu ÇİZMEZ
#        1920    0.299    ✗
#
#   Model imgsz=640 ile eğitildi ve büyütme onu BOZUYOR. Sim'deki
#   "büyük imgsz daha iyi" bulgusu 1920x1080 NATİF kaynak içindi;
#   640 genişlikte kaynakta büyütmenin ekleyeceği bilgi YOK.
#
#   ⛔ AYRICA KİLİTLENME VARDI: kutu bulunamayınca `_son_w = 0` kalır ve
#     uyarlanabilir kural bunu "uzak" sayıp DAİMA uzak kolunu seçer.
#     Uzak kol 960 iken hiç tespit olmuyor -> `_son_w` sıfırda kalıyor ->
#     sonsuza kadar 960. Çıkışı yok. İki kolu da 640 yapmak bunu bitirir.
export DOW_DET_IMGSZ_UZAK="${DOW_DET_IMGSZ_UZAK:-640}"
export DOW_DET_IMGSZ_YAKIN="${DOW_DET_IMGSZ_YAKIN:-640}"

# ⛔ YAKIN/UZAK GEÇİŞ EŞİĞİ de 1920 genişlikte ölçüldü (55 px ≈ 18 m).
#   640 genişlikte AYNI fiziksel hedef 3 kat küçük görünür -> 55/3 ≈ 18 px.
#   Eşik düzeltilmezse "yakın" kolu HİÇ devreye girmez.
export DOW_DET_YAKIN_ESIK="${DOW_DET_YAKIN_ESIK:-18}"

# ⛔ KANAL SIRASI — ultralytics numpy dizisini BGR kabul eder.
#   `tayarti_v1` NORMAL eğitildi -> BGR ister.
#   Sim modeli `talon_v3` çevrilmiş karelerle eğitilmişti -> RGB isterdi.
#   ÖLÇÜLDÜ, aynı kare, imgsz 640:  BGR 0.700  ·  RGB 0.000
#   Sim modeline dönersen:  DOW_DET_RENK=rgb DOW_MODEL=talon_v3 ...
export DOW_DET_RENK="${DOW_DET_RENK:-bgr}"

# ⚠ FP16 ARTIK İŞE YARAMIYOR: ultralytics 8.4'te `half` kullanımdan kalktı
#   ve sessizce yok sayılıyor (ölçüldü: fp32 5.3 ms, "fp16" 5.2 ms — fark
#   yok). Simde 1.6 kat kazandırıyordu. 5-9 ms'de önemi kalmadı, kovalanmadı.

# ---- KALKIŞ FAZI KAPATILDI ------------------------------------------------
# ⛔ SİMÜLASYON MANTIĞI GERÇEKTE TERS ÇALIŞIYOR.
#
#   Simde drone yere doğuyordu ve hedefi kovalamadan ÖNCE tırmanması
#   gerekiyordu; `KALKIS` fazı bunun içindi ve 45 m'ye (tolerans −3 →
#   42 m) çıkana kadar YATAY KOMUT ÜRETMİYORDU.
#
#   Gerçek işleyiş TERSİ: pilot aracı ELLE kaldırıyor, sonra OTONOM'a
#   basıyor. Yani araç zaten havada. KALKIS fazı burada işe yaramaz,
#   üstelik ZARARLIDIR: 20 m'de OTONOM'a basarsan araç hedefi kovalamak
#   yerine 42 m'ye tırmanmaya çalışır — pilotun beklediği şey bu değil.
#
#   ÖLÇÜLDÜ (30 Ağu 2026):
#     KALKIS_ALT=45, irtifa  0 m -> faz KALKIS    yatay komut YOK
#     KALKIS_ALT=45, irtifa 43 m -> faz ISTASYON  tam komut
#     KALKIS_ALT=0,  irtifa  0 m -> faz ISTASYON  tam komut
#
#   0 verince kapı (`yukseklik >= 0 − 3`) ilk tikte açılır ve faz
#   doğrudan ISTASYON olur. Kod silinmedi; sim tarafı bozulmasın diye
#   AYARLA kapatıldı, geri açmak için bu satırı değiştirmek yeter.
export DOW_KALKIS_ALT="${DOW_KALKIS_ALT:-0}"

# ---- KAMERA OPTİĞİ ---------------------------------------------------------
# ⛔⛔ ŞU AN SİMÜLASYON DEĞERLERİYLE UÇUYOR — HENÜZ ÖLÇÜLMEDİ.
#
#   dow/gorus/kamera.py'deki sabitler DoW simülasyonunda ölçüldü:
#     F_PX = 540.4 px · TILT = 26.50° · MENZIL_C = 997 px·m · 1920x1080
#   Gerçek FPV kamerası BAŞKA mercek, BAŞKA montaj açısı, BAŞKA çözünürlük.
#
#   NE OLUR: menzil ve kerteriz yanlış hesaplanır. R = MENZIL_C/kutu_px
#   olduğu için F_PX'te %30 hata menzilde de %30 hatadır — güdüm hedefi
#   olduğundan yakın ya da uzak sanır. Hata SESSİZDİR, hiçbir yerde patlamaz.
#
#   NASIL ÖLÇÜLÜR (5 dakika, dedektöre gerek yok):
#       python3 gercek/kamera_ayari.py        # tarayıcı: localhost:8020
#     Talon'u ölçülmüş bir mesafeye koy, kanat uçlarına tıkla, 3-4 mesafede
#     tekrarla. Araç sana aşağıya yapıştırılacak export satırlarını verir.
#
#   ⚠ Ölçümü HANGİ çözünürlükte yaptıysan uçuşta da o kullanılmalı; F_PX
#     çözünürlükle ölçeklenir. drone_yki.py uyuşmazlıkta yüksek sesle uyarır.
#
# ⭐ UYGULANDI 2026-08-29 — kaynak: ÜRETİCİ SPEC'İ (ölçüm DEĞİL)
#   Kullanıcı bildirdi: FOV 125°, montaj TILT 25°, kart 640x480.
#   F_PX = (yarı_köşegen)/tan(FOV/2) = 400/tan(62.5°) = 208.2
#     (KÖŞEGEN kabul edildi — FPV üreticileri köşegen FOV yazar.
#      YATAY olsaydı F_PX 166.6 olurdu, %25 fark.)
#   MENZIL_C = F_PX · 1.718 · 1.0738   (son çarpan: dedektör kutusunun
#     gerçek kanat açıklığından geniş olma payı, simde ölçüldü)
#
#   ⚠ BU BİR SPEC DEĞERİDİR, ÖLÇÜM DEĞİL. Üretici FOV'ları yuvarlanmış ve
#     çoğu zaman abartılıdır; ayrıca yakalama kartı kırpıyorsa gerçek FOV
#     bundan farklıdır. İlk fırsatta kanat ucu ölçümüyle DOĞRULA:
#         python3 gercek/kamera_ayari.py --kamera /dev/video2
#     Araç spec ile ölçüm arasındaki farkı yüzdeyle söyler.
export DOW_OPTIK_W="${DOW_OPTIK_W:-640}"
export DOW_OPTIK_H="${DOW_OPTIK_H:-480}"
# ⛔ DEĞERLER BALIKGÖZE GÖRE YENİLENDİ (30 Ağu 2026).
#   Eskiden pinhole formülüyle türetilmişlerdi (F_PX 208.2 / C 384.2) ve
#   mercek balıkgöz olduğu için 1.76 KAT yanlıştılar.
#   f_bg = (yarı_köşegen)/(yarı_FOV rad) = 400/1.0908 = 366.7 px/rad
#   C    = f_bg · 1.718 · 1.0738 = 676.5   (köşegen ölçüsü için ×1.0568)
export DOW_OPTIK_F_PX="${DOW_OPTIK_F_PX:-366.7}"
export DOW_OPTIK_TILT="${DOW_OPTIK_TILT:-25.0}"
export DOW_OPTIK_MENZIL_C="${DOW_OPTIK_MENZIL_C:-676.5}"
export DOW_OPTIK_MENZIL_C_KOSEGEN="${DOW_OPTIK_MENZIL_C_KOSEGEN:-714.7}"
#
# ⛔⛔ MENZIL_C HÂLÂ TÜRETME, ÖLÇÜM DEĞİL. İçinde iki varsayım var:
#     (a) FOV'un KÖŞEGEN olduğu
#     (b) dedektör kutu payının simdeki gibi %7.4 olduğu
#   İKİSİNİ BİRDEN öldüren tek ölçüm:
#       Talon'u ÖLÇÜLEN R metreye koy, panelden kutu köşegenini oku:
#           DOW_OPTIK_MENZIL_C_KOSEGEN = köşegen_px × R
#   Ör. 10 m'de köşegen 71 px ise -> 710. Birkaç mesafede tekrarla,
#   tutarlıysa doğru.
export DOW_KAM_KAYNAK="${DOW_KAM_KAYNAK:-/dev/video2}"

# ---- BALIKGÖZ (FISHEYE) MERCEK MODELİ --------------------------------------
# ⛔⛔ ŞU AN KAPALI (pinhole) — davranış simülasyondaki gibi.
#
#   SORUN: FPV merceği balıkgözdür, oyun motorunun kamerası DEĞİLDİ.
#   FOV'dan pinhole formülüyle türetilen F_PX (208.2) yalnız KÖŞEDE
#   doğrudur; merkez civarında balıkgöz odağı 366.7 px/rad — 1.76 KAT
#   fark. Güdüm `yaw + 3·azimut` uyguladığı için bu, kadrajın ortasında
#   38°'ye varan FAZLA YAW KOMUTU demektir.
#
#   ⚠ Bu yüzden yukarıdaki DOW_OPTIK_F_PX / MENZIL_C değerleri de
#     ŞÜPHELİ: pinhole varsayımıyla türetildiler. Arkadaşın OpenCV
#     kalibrasyonu gelince ikisi de yenilenmeli.
#
#   KALİBRASYON GELİNCE (cv2.fisheye.calibrate çıktısı):
#     K = [[fx,0,cx],[0,fy,cy],[0,0,1]]   D = [k1,k2,k3,k4]
#   şu satırların yorumunu kaldır ve fx / D değerlerini yaz:
#
#   ⭐ AÇILDI 2026-08-30 — kalibrasyon FOV 125°, TILT 25°, balıkgöz TEYİT.
export DOW_OPTIK_MODEL="${DOW_OPTIK_MODEL:-esuzaklik}"
export DOW_OPTIK_FOV_KOSEGEN="${DOW_OPTIK_FOV_KOSEGEN:-125}"
#
#   ⚠ "KÖŞEGEN" KABUL EDİLDİ — balıkgöz merceklerinde üreticiler ve
#     kalibrasyon araçları genelde köşegen FOV verir. YANLIŞSA:
#         köşegen 125 -> f_bg 366.7   MENZIL_C 676.5   40px = 16.9 m
#         yatay   125 -> f_bg 293.4   MENZIL_C 541.2   40px = 13.5 m
#         dikey   125 -> f_bg 220.0   MENZIL_C 405.9   40px = 10.1 m
#     Doğru ekseni bilmiyorsan MENZIL_C'yi ÖLÇ (aşağıya bak) — ölçüm
#     ekseni bilmeye gerek bırakmaz.
#
#   K/D matrisleri gelirse KESİN model (bozulma katsayıları dahil):
# export DOW_OPTIK_MODEL=opencv
# export DOW_OPTIK_FBG=<K'daki fx>
# export DOW_OPTIK_D="<k1>,<k2>,<k3>,<k4>"
#
#   ⛔ AÇMADAN ÖNCE ÖLÇ: hedefi sabit mesafede tutup kadrajda gezdir;
#     panelde "görsel menzil" SABİT kalmalı. Kalmıyorsa model yanlış.

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

# ---- önceki yer kontrolünü temizle (panel portu tutulu kalmasın) ----
# ⛔ Desen köşeli parantezle kırılır; `pkill -f` kendi kabuğunu öldürebilir
#   (CLAUDE.md §9, bu depoda yaşandı: exit 144).
# ⚠ SAHTE BACKEND DE TEMİZLENİR: ana süreç `pkill` ile ölünce çocuk
#   süreç HAYATTA KALIYOR (trap EXIT çalışmıyor) ve bir sonraki örnek
#   8766/8767'yi bağlayamıyor. Test sırasında görüldü.
for _d in "[d]rone_yki" "[s]ahte_skydagger"; do
    if pgrep -f "$_d" >/dev/null 2>&1; then
        sari "  önceki süreç kapatılıyor: ${_d//[\[\]]/}"
        pkill -f "$_d" 2>/dev/null || true
    fi
done
sleep 1
for _d in "[d]rone_yki" "[s]ahte_skydagger"; do
    pkill -9 -f "$_d" 2>/dev/null || true
done
if [ "${1:-}" = "--kapat" ]; then yesil "  kapatıldı."; exit 0; fi

python3 -c "import cv2,numpy" 2>/dev/null || {
    kirmizi "  HATA: paketler eksik:  pip install -r requirements.txt"; exit 1; }

if [ "$SAHTE_BACKEND" = "1" ]; then
    # ⛔ ZATEN BİR BACKEND VARSA SAHTEYİ BAŞLATMA — SESSİZ KARIŞIKLIK OLUR.
    #   YAŞANDI (2026-08-29): gerçek backend açık unutulmuştu; sahte sunucu
    #   portu bağlayamayıp çıktı, panel GERÇEK backend'e bağlandı ve
    #   gerçek drone'un telemetrisini gösterdi. Yarım saat "sahte veri niye
    #   böyle" diye arandı — oysa veri gerçekti.
    if python3 - <<'PY' 2>/dev/null
import socket, sys
try:
    socket.create_connection(("127.0.0.1", 8766), timeout=1.0).close()
except Exception:
    sys.exit(1)
PY
    then
        kirmizi "  ⛔ 8766'da ZATEN bir backend var — sahte sunucu BAŞLATILMADI."
        echo   "     Panel O backend'e bağlanacak (muhtemelen GERÇEK donanım)."
        echo   "     Gerçekten sahte sınama istiyorsan önce onu kapat:"
        echo   "         ./reel/skydagger/baslat_backend.sh --kapat"
        echo
        SAHTE_BACKEND=0
    fi
fi
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

ls /dev/video* >/dev/null 2>&1 || sari "  UYARI: hiç /dev/video* yok — kamera açılmayacak"

echo
echo "  panel  : http://127.0.0.1:8810"
echo "  ⛔ İlk 5 saniye YALNIZ SAFE basılacak (rehber §8) — modülün"
echo "     MAVİ ışığını o sırada doğrula."
echo
# ⛔ -u (TAMPONSUZ): çıktı bir dosyaya yönlendirilince Python stdout'u
#   tamponlar ve AÇILIŞ TEŞHİSLERİ (kamera, model, kayıt) hiç görünmez.
#   Sahada `tail -f` ile izlemek imkânsız hâle gelir. (30 Ağu 2026)
# ⛔ SAHTE BACKEND VARKEN `exec` KULLANILMAZ (30 Ağu 2026'da yaşandı).
#   `exec` kabuğu YERİNE GEÇER; kabuk ölünce `trap ... EXIT` HİÇ çalışmaz
#   ve sahte backend Ctrl+C'den sonra yaşamaya devam eder — terminale RC
#   satırı basıp durur, sonraki çalıştırmada da 8766'yı tutar.
#   Gerçek backend'de exec doğru: fazladan bir kabuk süreci taşımayalım.
if [ "$SAHTE_BACKEND" = "1" ]; then
    python3 -u drone_yki.py --bag skydagger --kamera "$DOW_KAM_KAYNAK" "${EK[@]}"
    _CIKIS=$?
    kill "$SAHTE_PID" 2>/dev/null || true
    wait "$SAHTE_PID" 2>/dev/null || true
    yesil "  sahte backend kapatıldı."
    exit $_CIKIS
fi
exec python3 -u drone_yki.py --bag skydagger --kamera "$DOW_KAM_KAYNAK" "${EK[@]}"
