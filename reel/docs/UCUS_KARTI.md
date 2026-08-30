# UÇUŞ KARTI — çalıştırma komutları

Yalnız komutlar. Açıklama için `DRONE_YKI.html` / `TALON_YKI.html`.

---

## BİLGİSAYAR 1 — TALON

### T1 · Drone bilgisayarının IP'sini öğren
Drone bilgisayarında çalıştır, çıkan IP'yi not et:
```bash
ip route get 8.8.8.8 | grep -oP 'src \K\S+'
```
(birden çok ağ arayüzü varsa `hostname -I` yanlış olanı verebilir; bu komut
dışarı giden arayüzün adresini verir — Talon'un ulaşacağı adres odur)

### T2 · Telemetriyi tak, portu gör
```bash
ls -l /dev/serial/by-id/
```

### T3 · Başlat  (bu terminal AÇIK kalır)
```bash
cd ~/projects/drones_of_war_entegrasyon/reel
./baslat_talon.sh /dev/serial/by-id/<TAB-ile-tamamla> <DRONE-IP>
```
Üç süreç açılır: yayıncı + harita(8010) + arayüz(8000).

**Tarayıcı:** `http://localhost:8000`  ve  `http://localhost:8010`

**Bekle:** `BAĞLANTI: BAĞLI` · `GPS: 3D` · **uydu ≥ 10**

Bağlantı yoksa:
```bash
cd ~/projects/drones_of_war_entegrasyon/reel/talon
python3 baglanti_testi.py
```

### T4 · Kalkış parametrelerini doğrula
```bash
cd ~/projects/drones_of_war_entegrasyon/reel/talon
python3 kalkis_ayari.py
```
**Ölü zaman ≈ 0.20 s olmalı. 1 s üstündeyse UÇURMA.**

---

## BİLGİSAYAR 2 — DRONE

### D1 · Hedef GPS'i geliyor mu  (Talon başladıktan SONRA)
```bash
cd ~/projects/drones_of_war_entegrasyon/reel
python3 gercek/hedef_testi.py
```
**Geçer:** `Hz ≥ 5` · `yaş < 1.0 s` · `reddedilen 0`

### D2 · Kamerayı doğrula
```bash
cd ~/projects/drones_of_war_entegrasyon/reel
python3 gercek/kamera_ayari.py --tara
```
**Geçer:** `✔ YAKALAMA KARTI HAZIR: /dev/video2  640x480`

### D3 · Skydagger backend  (Terminal 1, AÇIK kalır)
```bash
cd ~/projects/drones_of_war_entegrasyon/reel/skydagger
./baslat_backend.sh
```
Backend konsoluna sırayla yaz:
```
/connect
RC_ENABLE          → modül MAVİ yanmalı
STOP               → sarı
EXTERNAL
```

### D4 · Yer kontrolü  (Terminal 2, AÇIK kalır)
```bash
cd ~/projects/drones_of_war_entegrasyon/reel
./baslat_drone.sh --gorsel
```
⛔ `--gorsel` OLMADAN YOLO ve görsel güdüm AÇILMAZ.

**Tarayıcı:** `http://localhost:8810`

Açılışta doğrula:
```
ELRS   : SKYDAGGER ...
KAMERA : /dev/video2  640x480      ← çözünürlük uyarısı ÇIKMAMALI
ÇEVİRİCİ: MODEL=aci ACI_MAX=60 Y_ISARET=+1.0
```

---

## GÖREVİN İCRASI

### 1 · Talon'u uçur  (BİLGİSAYAR 1)

`http://localhost:8010` (harita) — rotayı çiz:
- **tıkla** → waypoint · **sağ tık** → sil · **sürükle** → kaydır
- Kalkış irtifası **50**, waypoint irtifası **80**, bitince **EVE DÖN (RTL)**
- **GÖREVİ YÜKLE**

`http://localhost:8000` (arayüz):
- **ARM**  → motor dönmez, normal

`http://localhost:8010`:
- **GÖREVİ BAŞLAT (AUTO)** → onay ver
- Bekle: `MOD: AUTO`

**AT:**
- Rüzgâra karşı, iki elle gövdeden, **koş ve SERT at**
- **Düz ileri, burun ~10° yukarı** — dik atma
- Attıktan sonra elini çek, gaz ~0.5 s'de tam açılır

Talon rotasına ve irtifasına otursun. **Drone'u erken kaldırma.**

### 2 · Drone'u uçur  (BİLGİSAYAR 2)

`http://localhost:8810`:

| sıra | ne | doğrula |
|---|---|---|
| 1 | FPV görüntüsü | akıyor |
| 2 | GPS | **uydu ≥ 10** |
| 3 | **KÖKEN KUR** | araç yerde ve hareketsizken |
| 4 | Hedef | yaş **< 1 s** |
| 5 | Kumandayı oynat | panel joystickleri takip ediyor |
| 6 | Pervaneleri tak | alanı boşalt |

**Elle kaldır:** **ARM (BASILI TUT)** + **MANUEL** → uçağı tanı

**Otonoma geç:** **OTONOM** → dört şart sağlanmalı
(panel OTONOM · pilot izni · taze setpoint · kumanda bağı)

**İzle:** faz `İSTASYON` → hedef görününce `GÖRSEL` → `TERMİNAL`

### 3 · Otonomdan çıkış — iki yol
- Panelde **MANUEL**
- Kumandada **çubuk oynat** — güdüm ANINDA durur ve **geri gelmez**
  (mandallı; otonoma dönmek için panelden yeniden **OTONOM**'a bas)
- Panelde **⛔ FAILSAFE — DİKEY İNİŞ** (olduğu yerde aşağı iner)

### 4 · İniş
- **Drone:** MANUEL → elle indir → **DISARM**
- **Talon:** `http://localhost:8000` → **RTL** ya da **🛬 ŞİMDİ İN** → **DISARM**
- İki bilgisayarda da terminallerde `Ctrl+C`

---

## TERS GİDERSE

| belirti | komut / işlem |
|---|---|
| Araç hedeften **kaçıyor** | MANUEL, sonra: `DOW_CEV_Y_ISARET=-1.0 ./baslat_drone.sh --gorsel` |
| Faz hep İSTASYON | panelde kutu var mı; `--gorsel` verildi mi |
| Menzil tuhaf (20 px ≠ 19 m) | `DOW_OPTIK_F_PX=166.6 ./baslat_drone.sh --gorsel` |
| Hedef GPS yok | `python3 gercek/hedef_testi.py` |
| Talon bağlanmıyor | `python3 talon/baglanti_testi.py` |
| Panel dondu | kumanda zaten öncelikli — kumandayla uç |

**Menzil kontrolü:** 10 px→38 m · 20 px→19 m · 40 px→9.6 m · 90 px→4.3 m

---

## KAPATMA
```bash
cd ~/projects/drones_of_war_entegrasyon/reel
./baslat_talon.sh --kapat            # BİLGİSAYAR 1
./baslat_drone.sh --kapat            # BİLGİSAYAR 2
./skydagger/baslat_backend.sh --kapat
```
