# SİMÜLASYON KURULUMU — Drones of War

> Bu belge **simülatör** tarafını anlatır: güdüm yasaları burada geliştirildi
> ve ölçüldü. **Gerçek donanım** için ana `README.md`'ye bak.
>
> Simülasyonda ölçülmüş davranış gerçek koda **bit bit** taşındı;
> `araclar/denklik.py` 400 tikte bunu doğruluyor.

# Avcı İHA — Drones of War Entegrasyonu

TEKNOFEST avcı drone sistemi: **GPS yaklaşma + görsel (IBVS) terminal güdüm**,
UE5 tabanlı *Drones of War Teknofest* simülatöründe.

Sistem hedefi ortalama **17 saniyede imha ediyor** (ölçüldü: 7/7, medyan 17.3 s,
en yakın 0.63 m — `docs/kampanya/MODEL20_V3_V5.md`).

---

## Nasıl çalışıyor

```
KALKIŞ  →  ISTASYON  →  GÖRSEL
```

| faz | kaynak | ne yapar |
|---|---|---|
| **KALKIŞ** | — | dikey tırman, yatay komut yok |
| **ISTASYON** | GPS | hedefin kuyruğundaki istasyon noktasına otur (hata ~4.5 m) |
| **GÖRSEL** | **yalnız kamera** | ≤15 m'de devral, bbox ile terminal yaklaşma |

⛔ **Yarışma kısıtı:** görsel temas varken **GPS güdümü yasak**. Yapısal olarak
uygulanır — `ibvs.komut()` imzasında hedef konumu YOKTUR ve `tests/test_dow.py`
bunu bekçiyle sınar (B1, B18, B40).

**Dedektör:** `talon_v3.pt` (YOLO11s, imgsz uyarlanabilir 960/1920, fp16).
Depoda **tek model** vardır ve çalışma anında değişmez — `talon_v5` ölçümle
elenip 2026-08-27'de sistemden tamamen çıkarıldı (sebebi aşağıda).

**Panel:** `http://127.0.0.1:8801` — yer kontrol istasyonu, canlı FPV +
overlay + telemetri + yarışma kilit ölçütü.

---

## Ölçülmüş bulgular

Bu depodaki her sayı taze uçuştan gelir; yöntem `CLAUDE.md`'de yazılı
(tek değişken, dönüşümlü A/B, mekanizma kapısı, geçerlilik eşi, n≥4).

### ⭐ Model seçimi — yeni model her zaman iyi değil
*(v5 bu ölçümden sonra elendi; 2026-08-27'de koddan tamamen çıkarıldı.)*

| | **talon_v3** | talon_v5 (elendi) |
|---|---|---|
| imha | **7/7** | 2/6 |
| süre medyanı | **17.3 s** | 129.4 s |
| en yakın | **0.63 m** | 1.01 m |

v5 **uzak menzil** için eğitildi (hard negatif + uzak uçak fotoğrafı) ve orada
daha iyi. Ama bu sistemin vuruşu **4-15 m**'de oluyor:

| menzil | v3 | v5 |
|---|---|---|
| 4-8 m | **%67.6** | %53.9 |
| 8-15 m | **%87.7** | %74.0 |

v5 terminalde temas kaybediyor → görselden istasyona 2 kat sık düşüyor →
devirden vuruşa 20 s yerine 51 s. **Yeni model eğitecekler 4-15 m bandını
hedeflemeli.**

### Diğer kampanyalar

| konu | sonuç | belge |
|---|---|---|
| görüş zinciri hızı | tavan semptom, blokaj sebep | `docs/kampanya/HZ4_GORUS_HIZI.md` |
| ayrı görüş iş parçacığı | kontrol 40→47 Hz ama kazanç yok → KAPALI | `docs/kampanya/ISP_GORUS_IS_PARCACIGI.md` |
| HybridSort takipçi | v5'le ölçüldü → **geçersiz**, v3'le tekrar gerekiyor | `docs/kampanya/TAKIP_HYBRIDSORT.md` |

---

## Gereksinimler

| | sürüm | neden kritik |
|---|---|---|
| Ubuntu | 22.04+ (glibc 2.35) | GE-Proton bu tabana derli |
| Python | **3.10** | torch 2.5.1+cu121 tekerleri 3.10 için |
| NVIDIA sürücü | **≥ 550** (ölçüldüğü: 580.173.02) | CUDA 12.1 çalışma zamanı |
| GPU | CUDA'lı, ≥6 GB (ölçüldüğü: RTX 4060 8 GB) | YOLO + oyun aynı GPU'da |
| disk | ~8 GB | oyun 1.6 GB + Proton 533 MB + tekerler |

**Bu sistemin ölçüldüğü ortam** (referans):

```
Ubuntu 22.04 · glibc 2.35 · çekirdek 6.8.0 · Python 3.10.12
torch 2.5.1+cu121 · ultralytics 8.4.103 · numpy 1.26.3 · opencv 4.9.0
boxmot 18.0.0 · mss 10.2.0 · gdown 5.2.1
NVIDIA 580.173.02 · CUDA 12.1 · RTX 4060 Laptop 8 GB
GE-Proton11-5-x86_64 · umu-launcher 1.4.4
```

⚠ **numpy 2.x KURMAYIN.** `opencv-python 4.9` ve `torch 2.5.1` numpy<2'ye
bağlı; numpy 2 kurulursa `cv2` import'u çöker. `boxmot` 19+ numpy≥2 dayatır,
bu yüzden **boxmot 18.0.0** sabitlenmiştir.

---

## Kurulum

En kolayı: bu dosyanın **en sonundaki MASTER PROMPT**'u Claude Code CLI'ye
yapıştırın; her şeyi kendisi kurar.

Elle kurmak isterseniz:

```bash
git clone https://github.com/kayranecatikara/drones_of_war_entegrasyon.git
cd drones_of_war_entegrasyon

python3.10 -m venv .venv && source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cu121 \
    torch==2.5.1 torchvision==0.20.1
pip install ultralytics==8.4.103 "numpy==1.26.3" opencv-python==4.9.0.80 \
    boxmot==18.0.0 mss==10.2.0 pillow gdown==5.2.1
sudo apt install -y xdotool wmctrl x11-utils

# Oyun (1.5 GB) — Drive'dan
mkdir -p indirilen oyun
gdown 1l7JsnKOAMoXb2fwzfPA0egQ8o7DNs0q9 -O "indirilen/dow.zip"
unzip -q "indirilen/dow.zip" -d oyun/

# GE-Proton11-5
mkdir -p ~/.local/share/Steam/compatibilitytools.d calistirma
curl -L -o calistirma/GE-Proton11-5.tar.gz \
  https://github.com/GloriousEggroll/proton-ge-custom/releases/download/GE-Proton11-5/GE-Proton11-5-x86_64.tar.gz
sha512sum -c calistirma/beklenen.sha512     # doğrula
tar -xf calistirma/GE-Proton11-5.tar.gz -C ~/.local/share/Steam/compatibilitytools.d/

# umu-launcher (ZIPAPP — tek dosya indirmesi YOK, tar açılır)
mkdir -p calistirma
curl -L -o calistirma/umu.tar \
  https://github.com/Open-Wine-Components/umu-launcher/releases/download/1.4.4/umu-launcher-1.4.4-zipapp.tar
tar -xf calistirma/umu.tar -C calistirma/      # -> calistirma/umu/umu-run
chmod +x calistirma/umu/umu-run
```

### Çalıştırma

```bash
# 1) oyunu aç + göreve gir (~2 dk)
DISPLAY=:1 python3 araclar/sim.py

# 2) panel
xdg-open http://127.0.0.1:8801

# 3) uçuş
echo -n hibrit > .gudum_kipi
DISPLAY=:1 DOW_GORSEL=1 DOW_KIP=hibrit python3 araclar/kosu.py DENEME 4 150

# 4) sonuç
python3 araclar/gorsel_ozet.py logs/DENEME
python3 araclar/video.py logs/DENEME/k01 logs/deneme.mp4 5
```

Testler: `python3 -m pytest tests/test_dow.py -q` → **60 bekçi**.

---

## Kill-switch'ler

Her davranış değişikliğinin env anahtarı vardır; varsayılanı **ölçüm** belirler.

| anahtar | varsayılan | ne yapar |
|---|---|---|
| `DOW_MODEL` | `talon_v3` | dedektör modeli |
| `DOW_TAKIP` | `0` | HybridSort takipçi (v3'le ölçülmedi) |
| `DOW_GORUS_ISP` | `0` | çıkarımı ayrı iş parçacığına al |
| `DOW_KIP` | `hibrit` | `hibrit` / `gps` / `gorsel` |
| `DOW_GORSEL_DET_HZ` | `10` | çıkarım tavanı |

---
---

# 🤖 MASTER PROMPT

Aşağıdaki metnin tamamını kopyalayıp **Claude Code CLI**'ye yapıştırın.
Sistemi sıfırdan kurar ve uçuşa hazır hale getirir.

````
Bu sistemi Ubuntu makineme sıfırdan kur. Sürüm uyumluluğu KRİTİK — aşağıdaki
sürümlerin dışına çıkma, çıkman gerekirse önce bana sor.

## 1. Depoyu çek
git clone https://github.com/kayranecatikara/drones_of_war_entegrasyon.git
cd drones_of_war_entegrasyon
Depo `talon_v3.pt` modelini İÇERİR, ayrıca indirme yok. Model TEK yerden
seçilir: `dow/gorus/dedektor.py` içindeki `MODEL_YOLU`. Çalışma anında model
değiştiren kapı 2026-08-27'de SİLİNDİ — iki ayrı varsayılan tanımlıydı ve
elenen modeli sessizce geri yüklüyordu.

## 2. Ön koşulları doğrula (kurmadan ÖNCE)
- Ubuntu 22.04+ (glibc >= 2.35):  ldd --version
- NVIDIA sürücü >= 550:           nvidia-smi --query-gpu=driver_version --format=csv
- CUDA'lı GPU, >= 6 GB VRAM
- Python 3.10 var mı:             python3.10 --version
- Boş disk >= 8 GB
Bunlardan biri sağlanmıyorsa DUR ve bana söyle. Sürücü eskiyse kendin
yükseltmeye çalışma.

## 3. Python ortamı — SÜRÜMLER SABİT
python3.10 -m venv .venv && source .venv/bin/activate
pip install --upgrade pip
pip install --index-url https://download.pytorch.org/whl/cu121 torch==2.5.1 torchvision==0.20.1
pip install ultralytics==8.4.103 "numpy==1.26.3" opencv-python==4.9.0.80 boxmot==18.0.0 mss==10.2.0 pillow gdown==5.2.1

⚠ numpy 2.x ASLA KURMA. opencv 4.9 ve torch 2.5.1 numpy<2'ye bağlı; numpy 2
gelirse `import cv2` çöker. boxmot 19+ numpy>=2 dayatır — bu yüzden 18.0.0
sabit. Kurulum sonrası `pip install` çıktısında numpy'nin yükseltilmediğini
DOĞRULA, yükseltildiyse `pip install numpy==1.26.3` ile geri al.

Doğrula: python3 -c "import torch,cv2,numpy,ultralytics,boxmot;
print(torch.__version__, torch.cuda.is_available(), numpy.__version__, cv2.__version__)"
Beklenen: 2.5.1+cu121 True 1.26.3 4.9.0

## 4. Sistem araçları
sudo apt update && sudo apt install -y xdotool wmctrl x11-utils unzip curl

## 5. Oyunu OTOMATİK indir (kullanıcıdan indirme İSTEME)
Drones of War Teknofest, Google Drive'da. Dosya kimliği:
  1l7JsnKOAMoXb2fwzfPA0egQ8o7DNs0q9   (Drones of War Teknofest.zip, ~1.5 GB)
Ayrıca aynı klasörde (opsiyonel, SDK zaten depoda vendorlanmış):
  1ndpiKGNLoREuOkJE4EvkbzXnyWD_kxqR   (drone_sdk.py)
  1EajS4ILi2QqJdYUuDVmSo1W4M6l9Yb-g   (README.md)

mkdir -p indirilen oyun
gdown 1l7JsnKOAMoXb2fwzfPA0egQ8o7DNs0q9 -O indirilen/dow.zip
unzip -q indirilen/dow.zip -d oyun/

İndirme yarıda kalırsa gdown'u tekrar çalıştır (kaldığı yerden devam eder).
Drive kota hatası verirse bana söyle, tarayıcıdan indireceğim.
Sonuç şu yolda olmalı:
  oyun/Drones of War Teknofest/DronesOfWar.exe

## 6. GE-Proton11-5 (oyun UE5 + D3D12; düz Wine ÇALIŞMAZ)
mkdir -p ~/.local/share/Steam/compatibilitytools.d calistirma
curl -L -o calistirma/GE-Proton11-5.tar.gz \
  https://github.com/GloriousEggroll/proton-ge-custom/releases/download/GE-Proton11-5/GE-Proton11-5-x86_64.tar.gz
Doğrula (sha512):
8fb1f3ae65a8dc22efd8099ff489075f0eebddf01c445b423244589f6f0a1e19c01de5d1e722b97fc1ebaf6390c813052ed55290058f8d21f1353a36146f4a2c
tar -xf calistirma/GE-Proton11-5.tar.gz -C ~/.local/share/Steam/compatibilitytools.d/
⚠ Başka GE-Proton sürümü kurma; betikler `GE-Proton11-5-x86_64` klasör adını
arıyor.

## 7. umu-launcher — ZIPAPP (dikkat: tek dosya indirme linki YOKTUR)
mkdir -p calistirma
curl -L -o calistirma/umu.tar \
  https://github.com/Open-Wine-Components/umu-launcher/releases/download/1.4.4/umu-launcher-1.4.4-zipapp.tar
tar -xf calistirma/umu.tar -C calistirma/
chmod +x calistirma/umu/umu-run
Sonuç: calistirma/umu/umu-run ve calistirma/umu/umu_run.py olmalı.
⚠ `.../releases/latest/download/umu-run` diye bir varlık YOK (404 verir);
  yayınlanan asset ZIPAPP TAR'ıdır. Sürümü 1.4.4'te sabitledim; "latest"
  kullanma, ileride asset adları değişebilir.

## 8. Doğrula
python3 -m pytest tests/test_dow.py -q      # 60 bekçi GEÇMELİ
python3 -c "import sys;sys.path.insert(0,'.');
from dow.gorus.dedektor import MODEL_YOLU; print(MODEL_YOLU)"   # talon_v3.pt

## 9. İlk uçuş
DISPLAY=:1 python3 araclar/sim.py           # oyunu açar, göreve girer (~2 dk)
Ayrı terminalde panel: http://127.0.0.1:8801
echo -n hibrit > .gudum_kipi
DISPLAY=:1 DOW_GORSEL=1 DOW_KIP=hibrit python3 araclar/kosu.py DENEME 2 150

Beklenen: hedef ~15-35 saniyede imha, en yakın 0.4-0.9 m.
Olmuyorsa `logs/DENEME/ozet.csv`'deki `imha`, `devir_s`, `en_yakin_m`
sütunlarını bana göster.

## TUZAKLAR (hepsi yaşandı, tekrarlama)
- Oyun penceresi HDMI-0'da (0,0), KENARLIKSIZ TAM EKRAN olmalı; ekran
  yakalama oradan okuyor. Üstüne pencere açma, odağını çalma.
- `pkill -f` desenini köşeli parantezle kır (`kosu[.]py`), yoksa kendi
  kabuğunu öldürür.
- Sim kuran betiği boruya bağlama (`| tail`); arka plandaki süreçler
  yüzünden EOF gelmez ve asılır.
- Hedefi VURUNCA oyun "MISSION COMPLETED" ekranına düşer ve SDK 12345
  portunu KAPATIR. Sistem bunu tanıyıp PLAY AGAIN'e basıyor; portun
  açılması 60 saniyeyi bulabilir.
- Kritik veriyi `logs/` altına yaz, `/tmp` gecelik temizlenir.

## ÇALIŞMA KURALLARI
`CLAUDE.md`'yi OKU ve uy. Özetle: güdüm davranışını değiştiren kod
kullanıcı onayı olmadan yazılmaz; her özellik kill-switch'li girer;
karar TAZE UÇUŞ + video + log ile verilir, eski log replay'i kanıt
değildir; kol başına en az 4 uçuş; ölçütler koşmadan ÖNCE ilan edilir.
````
