# Talon Yer Kontrol İstasyonu

X-UAV Talon sabit kanat uçağı için MAVLink yer kontrol yığını. Uçakta
**yalnızca Pixhawk vardır**; yardımcı bilgisayar yoktur. Görev planlama,
telemetri ve kontrol yerdeki dizüstünde çalışır, uçağa SiK telsiziyle bağlanır.

| | |
|---|---|
| Yer bilgisayarı | **Windows 10/11** veya **Ubuntu 22.04+** |
| Python | 3.10+ |
| Otopilot | ArduPlane 4.7 (Pixhawk 2.4.8) |
| Kütüphane | pymavlink, Flask, pyserial |
| Bağlantı | SiK 433 MHz telsiz — USB seri port, 57600 baud |
| Port adı | Windows `COM3` · Linux `/dev/ttyUSB0` |
| Uçakta | Pixhawk 2.4.8 + SiK telsiz. Yardımcı bilgisayar yok |

---

## Dosya yapısı

```
ucak_komutlar/
├── control/
│   ├── mav_common.py        MAVLink altyapısı (bağlantı, arm, mod, telemetri)
│   ├── sekil_geometri.py    Kare/daire/elips GPS noktaları + uçulabilirlik denetimi
│   ├── sekil_gorev.py       Şekli ArduPlane görev öğelerine çevirir
│   ├── plane_functions.py   Temel uçuş fonksiyonları (RC override kontrolü)
│   ├── plane_patterns.py    Manevra paternleri (kare, çember, zigzag, agresif)
│   ├── run_plane_scenario.py Senaryo çalıştırıcı (zaman tabanlı, yalnızca CLI)
│   ├── komut.py             Tek tek komut gönderme (arm, mod, rtl, durum…)
│   └── preflight.py         Uçuş öncesi kontrol (arm etmez, sadece okur)
├── gcs/
│   ├── sunucu.py            Yer kontrol arayüzü sunucusu (port 8000)
│   └── static/index.html    Arayüz — tek dosya, bağımlılıksız
├── baslat.bat               ► BAŞLATICI (Windows)
├── baslat.sh                ► BAŞLATICI (Ubuntu/Linux) — venv, izin ve
│                              ModemManager denetimini kendisi yapar
├── requirements.txt         pymavlink, flask, pyserial
└── arac_parametre_dok.py    Karttaki tüm parametreleri zaman damgalı döker
```

## Adım adım ilk kullanım

Uçağı hemen uçurmaya kalkmayın. Sıra şu:

| # | Adım | Komut | Nerede |
|---|---|---|---|
| 1 | Bağlantıyı doğrula | `python -m control.komut durum` | masada |
| 2 | Uçuş öncesi kontrol | `python -m control.preflight` | masada |
| 3 | Komutlar yüzeylere gidiyor mu | `python -m control.servo_test` | masada |
| 4 | Arayüzü aç, telemetriyi gör | `python -m gcs.sunucu` → tarayıcı | masada |
| 5 | Arm/disarm dene | `python -m control.komut arm` → `disarm` | dışarıda |
| 6 | Joystick ile uç | Arayüzde **MANUEL KONTROL** | sahada |
| 7 | Şekil çiz | Arayüzde KARE / DAİRE / ELİPS → YÜKLE → BAŞLAT | sahada |

> Bu komutlar `MAV_ENDPOINT` ister. Tek seferlik vermek için:
> `set MAV_ENDPOINT=COM3` ve `set MAV_BAUD=57600`. Paneli `baslat.bat COM3`
> ile açarsanız o zaten ayarlar. **Panel açıkken bu komutlar çalışmaz** —
> seri portu tek süreç açabilir, önce paneli kapatın.

İlk 4 adım kapalı ortamda, motor bağlı olmadan yapılabilir. **5. adımdan
itibaren pervaneyi çıkarın** — arm sonrası motor komut bekler. Arm için
GPS 3D fix şarttır, yani dışarı çıkmanız gerekir.

`servo_test` üç şeyi ayrı ayrı gösterir: gönderdiğimiz komut, Pixhawk'ın
aldığı değer, otopilotun ürettiği servo çıkışı. Üçü uyumluysa uçuş kontrol
zinciri sağlamdır — uçağı hiç kaldırmadan bunu bilirsiniz.

---

## Bağlantı: Pixhawk → SiK telsiz → Windows dizüstü

Uçakta SiK 433 MHz telsizin hava tarafı Pixhawk'ın bir **TELEM** portuna takılı.
Yer tarafı, laptopa takılan küçük antenli USB çubuk. Arada başka bir bilgisayar
yok — panel doğrudan bu seri porttan MAVLink konuşuyor.

```
[Pixhawk] --TELEM--> [SiK hava] ))) 433 MHz ((( [SiK USB] --COM3--> [Windows laptop]
```

Kartta **TELEM1 ve TELEM2'nin ikisi de** MAVLink2 / 57600 olarak ayarlı
(`SERIAL1_*` ve `SERIAL2_*`), yani telsiz hangisine takılıysa çalışır.

### Portu bulmak

**Windows** — Aygıt Yöneticisi → **Bağlantı noktaları (COM ve LPT)**. SiK
genelde `USB Serial Port (COM3)` ya da `Silicon Labs CP210x (COM4)` diye
görünür. PowerShell'den de listelenir:

```powershell
[System.IO.Ports.SerialPort]::getportnames()
```

**Ubuntu / Linux:**

```bash
ls -l /dev/serial/by-id/     # kalici isim — tercih edin
ls /dev/ttyUSB*              # klasik isim
dmesg | tail                 # SiK'i taktiktan hemen sonra
```

> Her iki sistemde de **numara USB yuvasına göre değişir.** Linux'ta
> `/dev/serial/by-id/...` altındaki isim cihaza bağlıdır ve değişmez —
> sahada yuva karıştırmamak için onu kullanın.

Portu bulduktan sonra:

```bat
baslat.bat COM3                    :: Windows
```
```bash
./baslat.sh /dev/ttyUSB0           # Ubuntu / Linux
```

Baud farklıysa ikinci argüman: `baslat.bat COM3 115200`

### İki tuzak

**Portu tek süreç açabilir.** Panel çalışırken başka bir Python betiği aynı
COM portunu açamaz — `FileNotFoundError` ya da erişim hatası alırsınız. Panel
açıkken teşhis betiği çalıştıracaksanız önce paneli kapatın.

**Sinyal kopması normaldir.** SiK linki zaman zaman düşer; panel kendiliğinden
yeniden dener (`[GCS] MAVLink bekleniyor: COM3`). USB çubuğu çıkarıp takmak
portu tamamen kaybettirir — o durumda paneli yeniden başlatın.

> ⚠️ **Bağlantı yokken panelin "İniş hazırlığı" kutusunu okumayın.** Araçtan
> eşik okunamazsa panel kendi varsayılanlarına düşer ve gerçek kartla ilgisi
> olmayan sayılar gösterir — hatta olmayan bir "engel" yazar. Bağlantı noktası
> yeşil değilse o bölüm anlamsızdır.

### Pixhawk tarafında ayarlanması gereken parametreler

| Parametre | Değer | Neden |
|---|---|---|
| `SERIAL1_PROTOCOL` / `SERIAL2_PROTOCOL` | `2` | TELEM portlarında MAVLink 2 |
| `SERIAL1_BAUD` / `SERIAL2_BAUD` | `57` | 57600 — SiK'in varsayılanı |
| `SYSID_MYGCS` | `255` | **RC override'ın çalışması için şart** |

Son parametrenin adı firmware sürümüne göre değişir: yeni ArduPlane
sürümlerinde `MAV_GCS_SYSID`, eskilerde `SYSID_MYGCS`. Hangisi varsa onu
**255** yapın — `preflight.py` ikisini de arar. (Bu uçaktaki kartta
`MAV_GCS_SYSID` var ve zaten 255.)

Bu değer yanlışsa kodlar hatasız çalışır ama uçak hiçbir komutu dinlemez.

### Dar bant profili

57600'lük bir telsiz linki, USB'nin taşıdığı telemetrinin çok altındadır.
Panel `MAV_BAUD ≤ 115200` görünce **dar bant profiline** geçer: okumadığı ~35
akışı `SET_MESSAGE_INTERVAL` ile susturur (~4000 B/s kazanç) ve ihtiyacı olan
birkaçını düşük hızda ister. Bu olmadan link tıkanır, telemetri saniyelerce
gecikir.

### Yerdeyken güç

Pixhawk'ı yalnızca USB'den beslerseniz **servo rayına güç gitmez**, kumanda
yüzeyleri hareket etmez. Masada MAVLink testi için USB yeterlidir; yüzeyleri
oynatmak için uçağın kendi bataryası/BEC'i bağlı olmalıdır.

---

## Kullanım

### 1. Kurulum (bir kez)

**Windows:**
```bat
git clone https://github.com/EfeAtakul/talon_arayuz.git
cd talon_arayuz
pip install -r requirements.txt
```

**Ubuntu / Debian:**
```bash
sudo apt install -y python3 python3-venv python3-pip
git clone https://github.com/EfeAtakul/talon_arayuz.git
cd talon_arayuz
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo usermod -aG dialout $USER     # sonra oturumu kapatip acin
```

> Ubuntu 23.04+ sürümlerinde venv **zorunludur** — sistem Python'una `pip
> install` yapılamaz (PEP 668, `externally-managed-environment` hatası).

Ayrıntı ve tuzaklar: `KURULUM.md`.

#### Claude Code ile kurdurmak

Bilgisayarda Claude Code varsa aşağıdaki metni olduğu gibi yapıştırın; kurulumu
baştan sona yapar, işletim sistemini kendisi ayırt eder ve bağlantıyı doğrular.

```
X-UAV Talon uçağının yer kontrol istasyonunu bu bilgisayara kur.
(Windows ya da Ubuntu — hangisiyse ona göre davran.)

Depo: https://github.com/EfeAtakul/talon_arayuz

Sırayla:
1. Python 3.10+ var mı bak; yoksa kur.
   - Windows: kurulumda "Add Python to PATH" işaretli olsun
   - Ubuntu: sudo apt install -y python3 python3-venv python3-pip
2. Git var mı bak; yoksa kur.
3. Depoyu klonla.
4. Bağımlılıkları kur:
   - Windows: pip install -r requirements.txt
   - Ubuntu: python3 -m venv .venv && source .venv/bin/activate
             && pip install -r requirements.txt
     (Ubuntu 23.04+ sistem Python'una pip ile kurulum yaptırmaz — PEP 668.
      "externally-managed-environment" hatası alırsan venv kullan,
      --break-system-packages ile ZORLAMA.)
5. Seri portları listele, SiK telemetri telsizinin hangisinde olduğunu bul.
   - Windows: Aygıt Yöneticisi, genelde "USB Serial Port (COMx)" veya
     "Silicon Labs CP210x". Bluetooth portlarını eleme.
   - Ubuntu: ls -l /dev/serial/by-id/  ve  dmesg | tail
6. Ubuntu ise ayrıca:
   - sudo usermod -aG dialout $USER   (sonra oturum kapat-aç gerekir, söyle)
   - ModemManager çalışıyorsa kapat: sudo systemctl disable --now ModemManager
7. Paneli başlat:
   - Windows: baslat.bat <COM>
   - Ubuntu:  chmod +x baslat.sh && ./baslat.sh <port>
8. http://localhost:8000 açıldığını doğrula ve /api/telemetri çıktısında
   "bagli": true geldiğini göster. Gelmiyorsa sebebini söyle
   (uçakta enerji yok / SiK ışığı sabit yeşil değil / yanlış COM / menzil dışı).

KURALLAR — istisnasız:
- Bu gerçek bir uçak ve pervanesi takılı olabilir. ARM etme, uçuş modu
  değiştirme, motora gaz gönderme, servo oynatma, görev başlatma — hiçbirini
  yapma. Yalnızca kurulum ve okuma komutları.
- Parametre YAZMA. Sadece oku.
- Bir şey belirsizse dur ve sor.

Kurulum bitince README.md ve UCUS_PROSEDURU.md dosyalarını özetle: uçak nasıl
kalkıyor, nasıl iniyor, acil durumda ne yapılıyor.
```

### 2. Yer kontrol arayüzü

```bat
baslat.bat COM3                    :: Windows
```
```bash
./baslat.sh /dev/ttyUSB0           # Ubuntu / Linux
```

Sonra tarayıcıdan **`http://localhost:8000`**. Aynı WiFi ağındaki telefondan
bakmak isterseniz siyah pencerede yazan `http://<laptop-ip>:8000` adresini
kullanın. Panelde:

| Bölüm | Ne yapar |
|---|---|
| Durum şeridi | Bağlantı, ARM, mod, batarya, GPS fix/uydu, irtifa, hız, **gaz %**, yüklü görev |
| **3B GPS paneli** | Uçağın konumunu yerel eksende gösterir — zemin ızgarası, kalkış noktası, planlanan şekil, uçuş izi. Parmakla döndürülür, iki parmakla yakınlaşılır. Köşede yapay ufuk, altta eve uzaklık/irtifa (çit sınırı aşılınca kırmızı) |
| **MANUEL KONTROL** | Tam ekran panel açar: joystick + dikey gaz çubuğu, ARM/DISARM, RTL, acil motor durdurma |
| **Şekil çiz** | KARE / DAİRE / ELİPS — GPS görevi olarak yüklenir, AUTO'da uçulur |
| Uçuş modu | MANUAL / STAB / FBWA / LOITER + **AUTOTUNE** aç/kapa |
| **ARM / DISARM** | Ana ekranda, durum satırıyla. ARM onay sorar, DISARM sormaz |
| Alt sıra | Uçuş öncesi kontrol, RTL, 🛬 ŞİMDİ İN |
| **ACİL — MOTORU DURDUR** | Ana ekranın en altında, ayrı bölümde (zorla disarm) |
| Otopilot mesajları | Araçtan gelen uyarılar — ARM neden reddedildiğini burada görürsünüz |

**3B panel kütüphane kullanmaz.** Sahada internet olmayabilir, bu yüzden
arayüz tek dosyadır ve hiçbir CDN'e bağlı değildir. Klasörü kopyalamak
paneli taşımaya yeter.

#### Şekil çizme (GPS görevi)

Şekiller **zaman tabanlı manevra değil, gerçek GPS görevidir**: köşeler
koordinat olarak hesaplanır, araca waypoint görevi yüklenir ve AUTO modda
uçulur. Arayüz çökse bile uçak görevi sürdürür.

Girdikçe panel şekli **uçağın kendi parametrelerine karşı denetler** ve
uçulamayacaksa yüklemeye izin vermez:

- Dönüş yarıçapı `R = v²/(g·tanθ)` — bu uçak 20 m/s'te en dar ~49 m döner.
  Elipste kritik olan kısa eksen değil, uzun eksen ucundaki eğriliktir
  (`b²/a`): 200×60 elipsin en dar kıvrımı 18 m'dir, uçulamaz.
- Güvenlik çemberi (`FENCE_RADIUS`) ve tavan (`FENCE_ALT_MAX`) — aşılırsa
  uçak kendiliğinden RTL'e geçer.
- Waypoint aralığı — her şekil noktasına kendi kabul yarıçapı yazılır
  (`NAV_WAYPOINT.param2`), böylece uçak birkaç noktayı aynı anda geçmiş
  sayıp şekli yuvarlamaz.

Sınırlar arayüze gömülü değildir, **araçtan okunur**; kartta parametre
değişirse panel kendiliğinden yeni sınırı uygular.

Daire poligonla değil `NAV_LOITER_TURNS` ile uçulur — ArduPlane gerçek daire
çizer. Kare ve elips waypoint çokgenidir; tur tekrarı `DO_JUMP` ile yapılır
(tur = 0 → sonsuz).

**Görev bitince** üç seçenek var (panelde üç buton):

| Buton | Ne olur |
|---|---|
| **EVE DÖN** | `NAV_RETURN_TO_LAUNCH` — uçak eve gelir, tepede çember çizer |
| **BEKLE** | `NAV_LOITER_UNLIM` — şekil merkezinde bekler |
| **OTOMATİK İN** | `DO_LAND_START` + `NAV_LOITER_TO_ALT` + `NAV_LAND` — uçak kalkış noktasına iner |

**OTOMATİK İN** seçilince "iniş yönü" alanı açılır. Bu, uçağın **final
yaklaşmasında uçacağı pusula yönüdür** — rüzgâra karşı seçin. Patern şudur:

1. Kalkış noktasından iniş yönünün tersine `AUTOLAND_WP_DIST` kadar uzakta
   bir noktada daire çizerek `AUTOLAND_WP_ALT` irtifasına alçalır.
2. Burnu eve dönene kadar dairede bekler (`verify_loiter_to_alt` bunu
   kendisi yapar), sonra düz süzülerek kalkış noktasına iner.

İki parametre bilinçli olarak **AUTOLAND modunun kendi parametreleridir** —
göreve gömülen iniş ile **ŞİMDİ İN** butonunun uçtuğu iniş aynı olsun diye.
Panel süzülme açısını hesaplar ve 12°'den dik olursa yüklemeyi engeller.

> ⚠️ **İnişli görev RTL'in davranışını da değiştirir.** Bu uçakta
> `RTL_AUTOLAND = 1`; uçak eve varıp çemberi yakaladığında görevde
> `DO_LAND_START` arar, bulursa AUTO'ya geçip **iner**. Yani inişli görev
> yüklüyken RTL artık "eve dön ve bekle" değil, "eve dön ve in" demektir.
> Panel bunu görev durumu satırında ayrıca yazar. Sadece çember istiyorsanız
> önce **GÖREVİ SİL**.

> **Kalkış:** göreve otomatik kalkış (`NAV_TAKEOFF`) dahildir. Uçak zaten
> havadaysa BAŞLAT kalkış adımını atlar. Kalkış YÖNÜ seçilemez — ArduPlane
> takeoff waypoint'inin konumunu yok sayar, uçak fırlatıldığı yöne tırmanır.
> Şeklin yönünü panelden ayarlayabilirsiniz.

> **Motor hemen dönmez.** `TKOFF_THR_MINACC = 11` olduğu için ArduPlane gazı
> fırlatma ivmesini görene kadar susturur. BAŞLAT'a bastıktan sonra uçağı
> atmanız gerekir; panel bunu ayrıca yazar.

### 3. Sahada gerçek uçuş

```bat
baslat.bat COM3                    :: Windows
./baslat.sh /dev/ttyUSB0           # Ubuntu / Linux
```

Tek komut. Köprü ya da ara katman yok — panel seri portu doğrudan açar.

Sıra:

| # | Adım | Nerede |
|---|---|---|
| 1 | Kumandayı **aç** (uçaktan önce, en son kapat) | sahada |
| 2 | Uçağın bataryasını tak, **uçağa dokunma** ~30 sn | sahada |
| 3 | SiK'i laptopa tak, `baslat.bat COM3` | sahada |
| 4 | GPS 3D fix + 8'den fazla uydu bekle | sahada |
| 5 | Uçağı fırlatacağın noktaya koy, **görevi yükle** | sahada |
| 6 | Emniyet butonu → **ARM** → **BAŞLAT** → fırlat | sahada |

> ⚠️ **2. adımı atlamayın.** Jiro kalibrasyonu yalnızca açılışta bir kez
> çalışır ve uçağın o sırada hareketsiz olmasını ister. Kıpırdarsa
> `PreArm: Gyros not calibrated` çıkar ve **bir daha denenmez** — kartı
> yeniden başlatmadan geçmez.

Görev yüklemek ev konumunu kullanır, ARM ev konumunu kilitler. Bu yüzden
uçağı önce yerine koyun, sonra yükleyip arm edin; sonradan taşırsanız görev
noktaları eski yerde kalır.

---

## Uçağı nasıl indireceğim?

Dört yol var. Panelde üçü buton, biri verici.

**1. 🛬 ŞİMDİ İN — KALKIŞ YERİNE (AUTOLAND).** Tek tuşla otonom iniş. Uçak
nerede olursa olsun, görev sürerken bile, kalkış noktasına iner. Ana ekranda
ve manuel panelde. Karşılığı `AUTOLAND` uçuş modudur (mod 26).

ArduPlane bunun için **kalkış yönünü** kullanır ve o yönü uçuş sırasında GPS
yer rotasından yakalar. İki şart var, ikisi de sağlanmazsa mod reddedilir:

- Uçak **uçuyor** olmalı (`plane.is_flying()`), yerde çalışmaz.
- Kalkış yönü **yakalanmış** olmalı. Yön yalnızca AUTO, FBWA, MANUAL,
  TAKEOFF, ACRO, STABILIZE, TRAINING, AUTOTUNE modlarında yakalanır —
  LOITER, CRUISE, FBWB ve RTL yakalamaz. **Disarm yön kaydını siler**
  (`AP_Arming_Plane.cpp`), yani her uçuşta yeniden kalkmak gerekir.

Panel bu iki şartı önceden kontrol eder; yine de reddedilirse araçtan gelen
gerekçeyi ("Takeoff initial direction not set" gibi) ekrana yazar.

**Vericiden de tetiklenir:** `RC6_OPTION = 183` ile SwD anahtarı AUTOLAND'e
atandı. **Aşağı çekmek = iniş**, yukarı almak = vazgeç (mod knob'unun
gösterdiği moda döner). Uçak panel menzilinin (100–250 m) dışındayken **tek
verici yolu budur**.

**2. Göreve iniş gömmek.** Şekil panelinde **OTOMATİK İN** seçilirse görev
`DO_LAND_START` + `NAV_LOITER_TO_ALT` + `NAV_LAND` ile biter ve uçak şekli
bitirince kendiliğinden iner. Ayrıntı: yukarıdaki "Şekil çizme" bölümü.

**3. RTL — EVE DÖN.** Uçak kalkış noktasına döner. Sonrası `RTL_AUTOLAND`
parametresine bağlıdır:

| `RTL_AUTOLAND` | Görevde `DO_LAND_START` | Sonuç |
|---|---|---|
| 0 | — | Eve gelir, **sonsuza kadar çember çizer** |
| 1 (bu uçakta) | yok | Eve gelir, **sonsuza kadar çember çizer** |
| 1 (bu uçakta) | var | Eve gelir, çemberi yakalayınca **iner** |

Yani RTL tek başına bir iniş komutu **değildir**. Aynı davranış telemetri
kopmasında (`FS_LONG_ACTN=1`), çit ihlalinde (`FENCE_ACTION=1`) ve batarya
failsafe'inde (`BATT_FS_LOW_ACT=1`) de geçerlidir — hepsi RTL'e geçer.

**4. Manuel iniş — ilk uçuşlarda bunu tercih edin.** Vericinizden FBWA veya
MANUAL moda alıp kendiniz indirirsiniz.

### Otomatik iniş — hazır mı (panel kutusu)

Otomatik inişin çalışması üç şarta bağlı ve üçü de sessizce bozulabiliyor.
Panel bunları kalkıştan **önce** tek bir kutuda gösterir:

```
✓ Patern / çit       333 m / 380 m
✓ Süzülme            7.1°
… Kalkış yönü        henüz yakalanmadı
✓ Batarya 2. kademe  OTOMATİK İNİŞ (olmazsa RTL) @ 20.4 V
```

| Satır | Ne kontrol ediyor |
|---|---|
| **Patern / çit** | İniş paterninin en uzak noktası güvenlik çemberine sığıyor mu. Sığmazsa uçak yaklaşmaya giderken çiti aşar, `FENCE_ACTION` devreye girer ve iniş yarıda kalır |
| **Süzülme** | Alçalma açısı. 8°'den dik uyarı, 12°'den dik engel |
| **Kalkış yönü** | ArduPilot kalkışta yönü yakaladı mı. AUTOLAND bunsuz **hiç başlamaz**. Yerdeyken "…" (sırası gelmemiş), havadayken hâlâ yoksa kırmızı |
| **Batarya 2. kademe** | `BATT_FS_CRT_ACT` kritik voltajda ne yapacak — iniş mi, sadece RTL mi |

Kalkış yönü yer istasyonundan **hiçbir mesajla okunamıyor**; ArduPilot yalnızca
yakaladığı anda `Autoland direction= NNN` diye bir kez yazıyor. Panel bunu o
metinden ayıklıyor ve disarm görünce siliyor (disarm yön kaydını siler).

Patern veya süzülme engelliyse panel **🛬 butonunu kapatır** — komutu göndermek
uçağı çitin dışına yollamak demek olurdu ve pilot bunu ancak havada öğrenirdi.

> **İndikten sonra tekrar kalkmak:** göreve gömülü inişten sonra araç arm'ı
> `PreArm: In landing sequence` ile reddeder. **GÖREVİ SİL**'e basıp tekrar
> deneyin — panel silme sırasında bu bayrağı ayrıca temizliyor. AUTOLAND
> (🛬 ŞİMDİ İN) ile inişte bu olmuyor.

> ⚠️ **Otomatik iniş fabrika değerleriyle çalışmaz.** İniş paterni güvenlik
> çemberinin dışına çıkıyor. Paneldeki **"Otomatik iniş — hazır mı"** kutusu
> bunu kalkıştan önce gösterir ve şart sağlanmıyorsa 🛬 butonunu kapatır.
> Uygulanacak parametre seti: `UCUS_PROSEDURU.md` bölüm 7.4.

> ⚠️ **Bu uçakta çalışan pitot yok.** Otomatik iniş hava hızını doğru bilmeye
> dayanır; yer hızıyla inişe kalkmak rüzgârda stall ya da sert çarpma
> demektir. İlk uçuşlarda elle inip uçağın davranışını gördükten sonra
> otomatik inişe geçin.

**Kontrolü acilen geri almak için:**

- **GÖREVİ DURDUR** — AUTO'dan LOITER'a alır, uçak bulunduğu yerde tur atarak
  bekler. Joystick'i kapatır ve RC override'ları bırakır.
- **RTL — EVE DÖN** — kalkış noktasına döndürür (çember çizer, inmez —
  görevde iniş yoksa).
- **🛬 ŞİMDİ İN** — AUTOLAND; kalkış yerine otonom iner. Onay sorar.
- Manuel paneldeki iki disarm butonu **bilinçli olarak farklı davranır:**

  | Buton | Gönderdiği | Havada basılırsa |
  |---|---|---|
  | **DISARM** (üst sırada) | normal disarm | Otopilot **reddeder**, uçak uçmaya devam eder |
  | **ACİL — MOTORU DURDUR** (altta, kırmızı) | **zorla** disarm (`param2 = 21196`) | **Motor kesilir, uçak düşer** |

  > ⚠️ **ACİL butonu gerçekten uçağı düşürür.** ArduPilot normalde uçarken GCS
  > disarm'ını reddeder (`AP_Arming_Plane::disarm` → `plane.is_flying()`
  > kontrolü); zorla bayrağı bu kilidi atlar. SITL'de doğrulandı: normal disarm
  > reddedildi, zorla disarm kabul edildi ve irtifa 59 m'den yere düştü.
  >
  > Onay penceresi **yok** — acil durumda araya bir tık daha koymak butonun
  > amacını bozar. Yanlış dokunmaya karşı tek koruma butonun ayrı satırda,
  > farklı renkte ve diğer kontrollerden uzakta olmasıdır.
  >
  > **Uçağı indirmek için ACİL butonu değil, RTL kullanın.** ACİL yalnızca
  > "motor şimdi dursun" gerektiren durumlar içindir (yerde kontrolsüz gaz,
  > pervane tehlikesi, havada yangın/yapısal arıza gibi).

Manuel panel açıkken joystick 20 Hz komut gönderir. Tarayıcı donar, telefon
uykuya geçer veya WiFi koparsa sunucudaki **ölü adam anahtarı** 1,5 saniyede
override'ı bırakır ve kontrol vericiye döner. Panelin üstündeki sayaç bu
gecikmeyi canlı gösterir.

**Görev uçarken joystick açılamaz.** Bu uçakta `STICK_MIXING = 1` olduğu için
RC override AUTO'nun navigasyon çıkışına karışır ve rotayı sessizce bozar;
arayüz isteği reddedip önce GÖREVİ DURDUR'a basmanızı ister.

---

## Komut aracı

```bash
python -m control.komut durum      # telemetriyi oku (hiçbir şey değiştirmez)
python -m control.komut izle       # sürekli telemetri
python -m control.komut arm        # ARM (onay ister)
python -m control.komut disarm     # DISARM
python -m control.komut mod fbwa   # uçuş modu değiştir
python -m control.komut modlar     # modları açıklamalarıyla listele
python -m control.komut kalkis     # otonom kalkış
python -m control.komut eve        # RTL
python -m control.komut daire      # LOITER — yerinde bekle
python -m control.komut in         # iniş bilgisi + RTL
python -m control.komut dur        # RC override'ları bırak
python -m control.komut parametre FS_LONG_ACTN     # parametre oku
python -m control.komut parametre FS_LONG_ACTN 1   # yaz + geri okuyup doğrula
```

`parametre` komutu Mission Planner olmadan sahada güvenlik parametresi
düzeltmek için. Yazdıktan sonra değeri geri okur; eşleşmezse hata verir —
sessizce yazılmamış bir güvenlik parametresi, yazılmadığını bilmemekten
daha tehlikelidir.

---

## Ortam değişkenleri

`baslat.bat` bunları argümanlardan ayarlar; elle de verebilirsiniz.

| Değişken | Windows'ta anlamı | Örnek |
|---|---|---|
| `MAV_ENDPOINT` | Seri port ya da UDP adresi | `COM3`, `/dev/ttyUSB0`, `udp:127.0.0.1:14550` |
| `MAV_BAUD` | Seri hız. **≤115200 dar bant profilini açar** | `57600` |
| `MAV_ALLOW_FORCE_ARM` | `0` = pre-arm kontrolleri işlesin (gerçek uçuş) | `0` |

```bat
:: Windows
set MAV_ENDPOINT=COM3
set MAV_BAUD=57600
python -m gcs.sunucu
```
```bash
# Ubuntu / Linux
export MAV_ENDPOINT=/dev/ttyUSB0
export MAV_BAUD=57600
python3 -m gcs.sunucu
```

---

## Güvenlik

**Force arm.** Kodlardaki `arm_plane()` ArduPilot'un force-arm magic'ini
(2989) kullanır ve pre-arm kontrollerini atlar. Simülasyonda pratiktir;
gerçek uçakta EKF oturmadan, pusula bozukken, GPS fix'i yokken de motoru
çalıştırır. Gerçek uçuşta `MAV_ALLOW_FORCE_ARM=0` kullanın — `mav_common`
bunu normal arm'a düşürür ve otopilot kendi kontrollerini işletir.
`baslat.bat` bunu zaten `0` olarak ayarlar.

**RC override zaman aşımı.** ArduPilot, override paketleri 3 saniye
yenilenmezse kontrolü bırakır (`RC_OVERRIDE_TIME`). Kontrol döngüleri
10-20 Hz gönderdiği için normalde sorun olmaz; ama Python süreci çökerse
uçak 3 saniye sonra son komutta kalmaz, otopilota döner. Bu bir güvenlik
özelliğidir — kapatmayın.

**Vericiniz her zaman açık olsun.** Mod anahtarıyla MANUAL/FBWA'ya alıp
kontrolü devralabilmelisiniz. RC override, verici girdisini ezer; devralmak
için Python sürecini durdurun (`Ctrl+C`) veya vericiden mod değiştirin.

**İlk uçuşta:** `aggressive` senaryosunu kullanmayın. Önce `square`, geniş
bir alanda, yeterli irtifada.

---

## Sorun giderme

| Belirti | Kontrol |
|---|---|
| `FileNotFoundError` (Windows) / `No such file or directory` (Linux) | Port **yok** — SiK takılı mı. Windows: Aygıt Yöneticisi. Linux: `ls /dev/serial/by-id/`. Numara değişmiş olabilir |
| `PermissionError / Access denied` (Windows) | Port **meşgul** — başka bir panel penceresi ya da teşhis betiği açık. Seri portu tek süreç açabilir |
| `Permission denied: '/dev/ttyUSB0'` (Linux) | `dialout` grubunda değilsiniz: `sudo usermod -aG dialout $USER`, sonra **oturumu kapatıp açın** |
| `error: externally-managed-environment` (Ubuntu) | PEP 668. venv kullanın: `python3 -m venv .venv && source .venv/bin/activate` |
| `python bulunamadı` | PATH'e eklenmemiş — Python'u "Add to PATH" ile yeniden kurun (Windows) / `sudo apt install python3` |
| `ModuleNotFoundError: serial` | `pip install -r requirements.txt` çalıştırılmamış. Panel açılır ama araca hiç bağlanamaz |
| Bağlanır sonra düşer, telemetri saçmalar (Linux) | ModemManager seri porta AT komutu gönderiyor: `sudo systemctl disable --now ModemManager` |
| Panel açılıyor, `bagli: false` | Uçakta enerji var mı, SiK ışığı sabit yeşil mi, iki telsiz de takılı mı |
| Uçak komutları dinlemiyor | `SYSID_MYGCS` / `MAV_GCS_SYSID` = 255 mi — `preflight.py` söyler |
| Telemetri saniyelerce gecikiyor | Dar bant profili açıldı mı — `MAV_BAUD` 57600 verilmiş olmalı |
| `PreArm: Gyros not calibrated` | Açılışta uçak kıpırdamış. Bataryayı çevirip **dokunmadan** bekleyin |
| `Arm: Roll (RC1) is not neutral` | Çubuk ya da trim merkezde değil. Panelde ham kanal değerleri görünür |
| `PreArm: Check mag field` | Manyetik girişim — metalden uzaklaşın; geçmezse pusula kalibrasyonu |

---

## Notlar

- **Zaman tabanlı senaryolar artık panelde yok, CLI'da duruyor.** Arayüzdeki
  şekiller GPS görevine geçti; `run_plane_scenario.py` (square, circle,
  aggressive…) komut satırından çalışmaya devam eder. İkisi aynı anda
  kullanılmaz — senaryolar RC override gönderir, GPS görevi AUTO'da uçar.
- `run_plane_scenario.py` throttle değerini `http://127.0.0.1:8000/api/plane_throttle`
  adresindeki GCS'ten okumaya çalışır. O servis çalışmıyorsa sessizce
  `THROTTLE_CRUISE` (600) kullanır — sorun değil. Arayüz bu iki uç noktayı
  (`/api/plane_throttle`, `/api/sekil`) yalnızca bu uyumluluk için tutuyor.
- Şekil matematiği araç olmadan test edilebilir:
  `python -m control.sekil_geometri --test` ve
  `python -m control.sekil_gorev --test`.
- Kodlar Gazebo simülasyonundan geliyor; `mav_common.py` gerçek donanım için
  telemetri akış isteği (`SET_MESSAGE_INTERVAL`) ekler. SITL bol telemetri
  yollar, gerçek telemetri linki yollamaz — bu istek olmadan pusula tabanlı
  dönüşler çalışmaz.
