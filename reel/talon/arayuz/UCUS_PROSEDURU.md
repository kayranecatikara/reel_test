# Talon "Hedef İHA" — Saha Uçuş Prosedürü

Kalkıştan inişe, adım adım. Sahada telefondan okunacak şekilde yazıldı.

Bu doküman **ne yapacağını** söyler.

> ℹ️ **Mimari:** Uçakta **yalnızca Pixhawk ve SiK telsiz** vardır. Yer
> istasyonu, SiK'in USB ucunun takılı olduğu **Windows dizüstüdür**. Bu
> `KURULUM_NOTLARI.md` uçağın kalibrasyon ve parametre kaydını tutar.

> **Uçuş sırası kuralı — atlanmaz:**
> mekanik montaj → CG ayarı → MANUAL ilk uçuş → FBWA → AUTOTUNE → otonom senaryo
>
> PID'leri ayarlanmamış uçakta otonom görev denenmez. FBWA'da salınım yapan
> uçak senaryoda da yapar, üstelik müdahale penceresi daha dardır.

---

## ACİL DURUM — önce bunu ezberle

Uçak ters giderse **mod düğmesini (VrA, CH5) RTL ucuna çevir.**

Bu tek hareket üç şeyi birden yapar:

1. Uçuş modunu **RTL** yapar — otopilot `RTL_ALTITUDE` irtifasında eve döner
2. Panel RC override gönderiyorsa mod değişimini görüp **bırakır**
3. Kontrol vericiye geri döner

**Neden en güvenilir yol bu:** laptopa, telemetriye, tarayıcıya bağlı değil.
Verici doğrudan alıcıyla konuşuyor. Panel donsa, laptop kapansa, SiK linki
kopsa bile çalışır.

> **Hangi uç RTL?** Mod düğmesi kademeli anahtar değil, **döner potansiyometre**.
> Bantlar: PWM **< 1231 → MANUAL**, **1231–1749 → FBWA** (dört konumun hepsi),
> **≥ 1750 → RTL**. Yani RTL bir uçta, MANUAL diğer uçta, arası hep FBWA.
> **Uçuş öncesi kontrolde düğmeyi üç konuma da çevirip panelde hangisinin
> yazdığını bir kez öğrenin** — acil durumda düşünecek vaktiniz olmaz.

Sıralı yedekler:

| Sıra | Yöntem | Bağımlılık |
|---|---|---|
| 1 | **Mod düğmesi → RTL ucu** | yalnız verici |
| 2 | **SwD anahtarını aşağı indir** (AUTOLAND — kalkış yerine iner) | yalnız verici |
| 3 | Panelde **RTL — EVE DÖN** | SiK telsiz + laptop |
| 4 | Panelde **GÖREVİ DURDUR** (AUTO → LOITER) | SiK telsiz + laptop |
| 5 | Mission Planner'dan mod değiştir | SiK telsiz |

SwD `RC6_OPTION = 183` ile AUTOLAND'e atanmış; **aşağı = iniş**, yukarı =
vazgeç. Yön vericide ters çevrilmiş (`Functions → Reverse → Channel 6`),
kartta `RC6_REVERSED` kullanılmıyor — ölçüt net: **SwD yukarıdayken CH6 = 1000.**

> **ACİL — MOTORU DURDUR butonu bu listede YOK.** O buton zorla disarm gönderir
> (`param2 = 21196`) ve otopilotun "uçarken motoru kesme" kilidini atlar —
> yani havada basılırsa **uçak düşer**. Kontrolü geri almak için değil,
> yalnızca "motor şimdi dursun" gerektiren durumlar içindir (yerde kontrolsüz
> gaz, pervane tehlikesi, havada yangın/yapısal arıza). Sahayı terk eden veya
> kontrolden çıkan uçak için yukarıdaki 5 yolu kullanın.
>
> Ayrıca **havada disarm, kalkışta yakalanan yön kaydını siler** — o uçuşta
> SwD/AUTOLAND bir daha çalışmaz.

**Uçak sahayı terk ediyorsa hiçbir şey yapma, geofence devrede:** **400 m**
yarıçap veya **100 m** irtifa aşılırsa otopilot kendiliğinden RTL'e geçer. Çit
otopilot seviyesinde çalışır — laptop kapansa, panel kilitlense bile devrededir.

> ⚠️ **Çit ihlalinden sonra mod değiştiremezsiniz.** `FENCE_OPTIONS = 1`, yani
> ihlal temizlenene kadar vericiden mod değişimi **kilitli**. Düğmeyi çevirmek
> hiçbir şey yapmaz — kumanda bozuldu sanmayın. `RTL_AUTOLAND = 1` olduğu için
> uçak eve gelip iner, sonuç güvenlidir.

> **GPS görevinde kritik fark:** şekil AUTO modunda otopilotun kendi görevi
> olarak uçuluyor. **Laptobu kapatmak, paneli kapatmak veya SiK linkinin
> kopması uçağı durdurmaz** — görev devam eder (`FS_GCS_ENABL = 0`). Durdurmak
> için ya vericiden mod değiştirin ya da panelden GÖREVİ DURDUR / RTL kullanın.
> Bu bilinçli bir tasarım tercihi: yer istasyonu çökse bile görev tamamlanıyor.

> ⚠️ **Panelin ACİL butonu telemetriye bağlıdır.** SiK menzil dışına çıkarsa o
> buton işlemez. Menzil dışında tek acil kaynağınız vericidir.

---

## BÖLÜM 0 — Evden çıkmadan

- [ ] Batarya **dolu** (6S için 25.2 V). 21 V altına inmiş pille sahaya gitme:
      arm eder etmez düşük batarya failsafe'i modu RTL'e atar, motor dönmez.
- [ ] Verici pili dolu
- [ ] Yedek pervane
- [ ] Multimetre
- [ ] Laptop şarjı dolu, panel evde bir kez açılıp bağlandığı doğrulanmış
- [ ] SiK telsizin **iki ucu** da yanında (hava tarafı uçakta, USB tarafı çantada)
- [ ] Bu doküman telefonda açık

---

## BÖLÜM 1 — Sahada kurulum

### 1.1 Güç verme SIRASI — bu sıra bozulmaz

```
1. VERİCİYİ AÇ          ← her zaman ilk
2. VrA'yı sola al (RTL konumu)
3. Gaz çubuğunu tam aşağı çek
4. Uçağın bataryasını tak    ← her zaman ikinci
```

**Neden bu sıra:** Alıcı önce açılırsa ve verici kapalıysa alıcı failsafe
değerlerini uygular. Verici önce açık olursa alıcı gerçek çubuk konumlarını
görür. Gaz çubuğu yukarıdayken batarya takmak ise ESC'yi kalibrasyon moduna
sokabilir veya motoru döndürebilir.

### 1.2 Uçak açılışı — jiro tuzağı burada

- [ ] Uçağı **yere koy**, düz dursun
- [ ] Bataryayı tak — ESC bip sesi gelmeli
- [ ] **UÇAĞA DOKUNMA — 30 saniye.** Ne tut, ne yasla, ne çevir
- [ ] Pixhawk açılış tonunu bekle
- [ ] Emniyet butonu: yanıp sönüyorsa **basılı tut**, sabit yanana kadar
      (sabit = çıkışlar aktif)

> ⚠️ **Açılış sırasında uçak kıpırdarsa jiro kalibrasyonu başarısız olur.**
> `PreArm: Gyros not calibrated` çıkar ve otopilot bunu **bir daha denemez** —
> beklemek, dışarı çıkmak, GPS'in oturması hiçbir şeyi değiştirmez. Tek çözüm
> bataryayı çevirip **bu sefer dokunmadan** beklemektir. Rüzgâr sallıyorsa
> bedeninle siper ol ama uçağa değme.

### 1.3 Panele bağlan

Uçakta yardımcı bilgisayar yok; panel **yerdeki Windows dizüstünde** çalışır ve
uçağa SiK telsiziyle bağlanır.

- [ ] SiK'in USB ucunu laptopa tak — ışığı **sabit yeşil** yanmalı
- [ ] Depo klasöründe komut istemi aç, çalıştır:

```bat
baslat.bat COM3
```

- [ ] Tarayıcıdan **`http://localhost:8000`**

COM numarası laptoptan laptopa ve USB yuvasından yuvaya değişir. Bulmak için
**Aygıt Yöneticisi → Bağlantı noktaları (COM ve LPT)**; SiK genelde
`USB Serial Port (COMx)` diye görünür.

Başlıktaki **bağlantı noktası yeşil** olmalı, telemetri kutuları dolmalı.

| Belirti | Sebep |
|---|---|
| `could not open port: FileNotFoundError` | Port yok — SiK takılı değil ya da numarası değişmiş |
| `could not open port: PermissionError` | Port meşgul — başka bir panel penceresi veya teşhis betiği açık |
| Panel açılıyor, nokta **kırmızı** | Uçakta enerji yok, SiK ışığı sabit değil, ya da menzil dışı |

> ⚠️ **Nokta yeşil değilken "Otomatik iniş — hazır mı" kutusunu okuma.**
> Araçtan eşik okunamazsa panel kendi varsayılanlarına düşer ve gerçek kartla
> ilgisi olmayan sayılar gösterir — hatta olmayan bir "engel" yazar. O sayılara
> bakıp kartta parametre değiştirmeyin.

> SiK linki zaman zaman düşer, panel kendiliğinden yeniden dener. USB çubuğu
> çıkarıp takarsanız port tamamen kaybolur — o durumda paneli yeniden başlatın.

### 1.4 GPS fix bekle

Dışarıda 1–3 dakika. Arayüzdeki **GPS** kutusu 3D fix ve 8+ uydu göstermeli.

**Fix olmadan otonom kalkış reddedilir.** Bu bir hata değil, koruma.

---

## BÖLÜM 2 — Uçuş öncesi kontrol

### 2.1 Arayüzden otomatik kontrol

Komutlar panelinde **UÇUŞ ÖNCESİ KONTROL** butonuna bas. ~15 saniye sürer.

Kontrol ettikleri:

| Kontrol | Neden önemli |
|---|---|
| Heartbeat | bağlantı gerçekten var mı |
| Arm durumu | araç disarm mı (güvenli mi) |
| `MAV_GCS_SYSID` | **eşleşmezse RC override sessizce yok sayılır** — senaryolar hiç çalışmaz |
| GPS fix | otonom kalkış için şart |
| ATTITUDE akış hızı | kare deseninin pusula dönüşleri buna bağlı |
| Batarya voltajı | |

Kutu **yeşil** çerçeveliyse engelleyici sorun yok. **Kırmızıysa raporu oku** —
hangi kontrolün patladığını satır satır yazar.

Bu buton arm etmez, motoru döndürmez. Sadece okur.

### 2.1b Arm neden reddediliyor — gerçek engel listesi

`ARMING_SKIPCHK = 0` (19 Ağu 2026) olduğundan otopilot artık **her** pre-arm
kontrolünü çalıştırıyor ve reddin sebebini tek tek yazıyor. Panelin ARM
butonuna basıp mesaj listesine bakın. Tezgahta görülen gerçek çıktı:

```
Arm: Hardware safety switch          -> emniyet butonuna basılmamış
Arm: AHRS: EKF3 Roll/Pitch inconsistent 53 deg  -> uçak düz durmuyor
Arm: Compass not calibrated          -> pusula kalibrasyonu yapılmamış
Arm: GPS 1: Bad fix                  -> 3D fix yok
Arm: Battery 1 low voltage failsafe  -> pil takılı değil / voltaj düşük
Arm: Fence requires position         -> çit açık ama konum yok
Arm: RTL mode not armable            -> mod knob'u RTL'de, MANUAL/FBWA olmalı
```

Sahada bu listeyi tek tek sıfırlayın. Hepsi temizlenmeden uçak arm olmaz —
**ve bu istenen davranıştır.** 19 Ağustos öncesinde `ARMING_SKIPCHK = -1`
olduğu için bunların hiçbiri kontrol edilmiyordu; uçak pusulasız ve GPS'siz
arm oluyordu.

### 2.2 Elle kontrol — arayüz bunları göremez

- [ ] **CG (ağırlık merkezi)** doğru yerde. Yanlış CG'yi hiçbir yazılım
      kurtaramaz; burun ağır uçak zor kalkar, kuyruk ağır uçak toparlanmaz.
- [ ] Pervane sıkı, çatlaksız, **yazılı yüzü buruna bakıyor**
- [ ] Pervane dönüş yönü: kısa gazda hava **kuyruğa** üflemeli
      (ters ise motor–ESC arası üç kablodan ikisini değiştir)
- [ ] Kanat, kuyruk, boom vidaları sıkı
- [ ] Kumanda yüzeyleri **MANUAL** modda doğru yöne hareket ediyor
      (çubuk → yüzey):
      - Sağa yatır → sağ kanatçık **yukarı**, sol kanatçık **aşağı**
      - Burun yukarı → V-kuyruk yüzeyleri **yukarı**
      - Ters ise `SERVOn_REVERSED`
- [ ] 🔴 Kumanda yüzeyleri **FBWA** modda doğru yöne düzeltiyor
      (duruş → yüzey — **bu ayrı bir kontrol**, yukarıdakiyle karıştırmayın):
      - Uçağı **sağa yatır** → sağ kanatçık **aşağı** (düzeltmeye çalışır)
      - Uçağın **burnunu aşağı eğ** → V-kuyruk arka kenarları **yukarı**
      - Aynı yöne gidiyorsa stabilizasyon **ters** — **UÇMAYIN**

      > MANUAL kontrolü geçip FBWA kontrolü kalabilir: biri çubuğu, diğeri
      > jiroskopu takip eder. Roll yönü 19 Ağu'da ölçülerek doğrulandı,
      > **pitch yönü henüz doğrulanmadı** (bkz. KURULUM_NOTLARI, 27 Ağu).
- [ ] **Mod düğmesi FBWA'da** — ArduPilot RTL modunda **ARM ETMEZ**
- [ ] **Gaz çubuğu tam dipte** — FBWA'da gaz çubuğa bağlı, yukarıdayken
      ARM edilirse motor anında döner
- [ ] Bütün konnektörler yerinde, kablo pervaneye yakın değil
- [ ] **SiK hava modülünün konnektörü sıkı oturmuş** — 27 Ağu'da gevşeyip
      telemetriyi defalarca düşürdü
- [ ] Anten dikey, karbondan/ESC güç kablolarından uzak
- [ ] Rüzgâr yönü ve şiddeti — kalkış rüzgâra karşı
- [ ] Saha boş, insan yok

---

## BÖLÜM 3 — İLK UÇUŞ (MANUAL)

**Senaryo yok, arayüzden komut yok.** Bu uçuşun tek amacı: uçak düzgün uçuyor mu,
trim'i tutuyor mu, yüzeyler doğru mu.

### 3.1 Kalkış

1. VrA'yı **sağa sonuna kadar** çevir → **MANUAL**
2. Arayüzde Mod kutusunun `MANUAL` yazdığını gör
3. Arayüzde **ARM ET**
4. Gaz çubuğunu kademeli aç
5. Rüzgâra karşı elden fırlat veya pistten kaldır

### 3.2 Havada

- Trim'i ayarla: eller çubukta değilken uçak düz uçmalı
- Yüzey yönlerini teyit et
- Salınım, titreşim, tek tarafa yatma var mı — not al

**Kanatçıklar eşit değilse burada belli olur.** Sol ve sağ kanatçığın hareket
aralığı şu an farklı (aşağıdaki "Bilinen açık işler"). Uçak bir tarafa yatmaya
çalışıyorsa sebebi bu olabilir.

### 3.3 İniş

1. Gazı kes
2. Rüzgâra karşı, alçak süzülüşle
3. Yere yakınken hafif burun yukarı
4. **DISARM** (arayüzden veya vericiden)

---

## BÖLÜM 4 — FBWA uçuşu

MANUAL'de sorun kalmadıysa.

1. Havalan (MANUAL)
2. Güvenli irtifada VrA'yı **ortaya** al → **FBWA**
3. Çubuğu bırak — uçak kanatlarını **kendi düzeltmeli**
4. Yatış ve burun komutlarını dene

**FBWA'da salınım varsa AUTOTUNE'a geçme, önce sebebini bul.** Salınım genelde
PID'lerin uçak için fazla agresif olmasıdır.

---

## BÖLÜM 5 — AUTOTUNE

Senaryolar FBWA üzerine kuruludur; FBWA iyi ayarlı değilse hiçbir desen düzgün
çıkmaz.

1. Havalan, FBWA'da stabilize et
2. Vericiden AUTOTUNE moduna al
3. **Çubukları sürekli oynat** — AUTOTUNE hareketten öğrenir, düz uçuşta
   hiçbir şey öğrenmez. Tam yatış, tam burun komutları ver.
4. 1–2 dakika sürer
5. FBWA'ya dön, davranışı kontrol et
6. **İn ve DISARM et** — kazanımlar disarm'da kaydedilir

---

## BÖLÜM 6 — GPS ŞEKİL GÖREVİ (asıl görev)

Buraya ancak AUTOTUNE bittikten sonra gelinir.

Şekiller artık **AUTO görevi** olarak uçuluyor: köşeler GPS koordinatı olarak
hesaplanıp araca waypoint görevi yükleniyor. Zaman/yatış tabanlı eski
senaryolar yalnızca komut satırında duruyor (`run_plane_scenario.py`).

### 6.1 Kalkıştan önce arayüzde hazırlık

- [ ] **Şekil** bölümünden KARE / DAİRE / ELİPS seç
- [ ] Boyut, irtifa, tur sayısını gir — panel yazdıkça denetler
- [ ] Uyarı satırlarını **oku**. Kırmızı (engel) varsa yükleme butonu kapalıdır
- [ ] **Merkez**: kalkış noktası (varsayılan) veya uçağın anlık konumu
- [ ] **Bitince**: eve dön (varsayılan) veya merkezde bekle
- [ ] **GÖREVİ YÜKLE** → "araçta N öğe doğrulandı" yazmalı
- [ ] 3B panelde planlanan şekli gör; kalkış noktasına göre yeri doğru mu

> Panel şekli uçağın kendi parametrelerine karşı denetler: dönüş yarıçapı
> (`AIRSPEED_CRUISE`, `ROLL_LIMIT_DEG`), güvenlik çemberi (`FENCE_RADIUS`
> 300 m), tavan (`FENCE_ALT_MAX` 100 m). Bu sayılar arayüze gömülü değil,
> karttan okunuyor — kartta değişirse panel yeni sınırı uygular.

### 6.2 Görevi başlatma

**Sıra: ARM önce, BAŞLAT sonra.** BAŞLAT tek başına yetmez — ARM edilmemiş
uçakta ArduPilot gaz çıkışını fiziksel olarak kilitler ve ne kadar sert
atarsanız atın motor dönmez.

```
1. Mod düğmesi FBWA'da          ← RTL'de ARM EDİLMEZ
2. Gaz çubuğu tam dipte
3. ARM                          ← durum satırında ⚠ ARMLI görün
4. Uçağı kavra, atmaya hazır ol
5. BAŞLAT
6. Fırlat
```

**BAŞLAT** butonu joystick'i kapatır, RC override'ı bırakır, başlangıç öğesini
belirler ve AUTO'ya geçer.

> 🔴 **BAŞLAT'a basınca PERVANE DÖNMEYE BAŞLAR.** `TKOFF_THR_IDLE = 15`
> (27 Ağu 2026'da eklendi): otopilot fırlatmayı beklerken motoru %15'te
> tutuyor. Bu gaz **çubuğa bağlı değil**, siz kapatamazsınız.
>
> Uçağı **gövdesinden, kanadın ÖNÜNDEN** kavrayın. Elinizi asla arkaya
> götürmeyin — pervane orada ve dönüyor.
>
> **BAŞLAT'a ancak atmaya hazır olduğunuz an basın**, öncesinde değil.
> Vazgeçerseniz: panelden **DISARM** ya da mod düğmesini çevirin.

> **Tam gaz fırlatmayla gelir.** İvme `TKOFF_THR_MINACC = 11` eşiğini aşınca
> 0.2 saniye beklenir, sonra gaz **anında %100**'e çıkar
> (`TKOFF_THR_SLEW = -1`, rampa yok) ve 5 saniye orada kalır.

> **Kalkış yönü seçilemez.** ArduPlane takeoff waypoint'inin konumunu yok sayar
> ve uçak fırlatıldığı yöne tırmanır. Şeklin yönünü panelden ayarlayın ki
> kalkıştan hemen sonra sert dönüş yapmasın.

Uçak zaten havadaysa BAŞLAT kalkış adımını atlar ve doğrudan şekle geçer.

### 6.3 Görev uçarken

- Verici **açık** ve elinde kalsın
- Durum şeridinde yüklü şekil ve **aktif öğe numarası** görünür
- 3B panelde uçuş izi planlanan şeklin üstüne oturmalı
- **Joystick açılamaz.** `STICK_MIXING = 1` olduğu için RC override AUTO'nun
  rotasına karışır; arayüz isteği reddeder. Elle müdahale gerekiyorsa önce
  GÖREVİ DURDUR

### 6.4 Görevi durdurma

| Yol | Sonuç |
|---|---|
| Arayüzde **GÖREVİ DURDUR** | LOITER — uçak bulunduğu yerde tur atar |
| Arayüzde **RTL — EVE DÖN** | Kalkış noktasına döner |
| **VrA ile mod değiştir** | Otopilot AUTO'dan çıkar |
| Mission Planner'dan mod değiştir | SiK telsiz üzerinden, ~1–2 km |

> Laptobu kapatmak veya telemetri linkinin kopması görevi **durdurmaz** — görev otopilotun
> içinde. Bu bilinçli: arayüz çökse bile uçak görevi tamamlar. Ama durdurmak
> istediğinizde vericiye veya telsize ihtiyacınız olduğunu unutmayın.

### 6.5 Şekil boyutu seçerken

| Şekil | Girilen | Fiziksel alt sınır |
|---|---|---|
| Kare | kenar | kenarın yarısı > dönüş yarıçapı (~49 m) → **en az ~100 m**, temiz köşe için 200 m+ |
| Daire | yarıçap | > ~49 m, rüzgâr payıyla **100 m+ önerilir** |
| Elips | uzun + kısa eksen | en dar kıvrım `b²/a` > ~49 m. **200×60 elips uçulamaz** (kıvrım 18 m), 170×110 uçulur |

Güvenlik çemberi 300 m olduğu için şeklin en uzak noktası kalkış yerine
280 m'den yakın olmalı; panel bunu da denetler.

**İlk otonom uçuşta büyük ve basit başla:** 250 m kare, 60 m irtifa, 2–3 tur.

---

## BÖLÜM 7 — İNİŞ

### 7.1 Elle iniş — İLK UÇUŞLARDA BUNU YAP

1. Görevi durdur (6.4'teki yollardan biri)
2. VrA'yı **sağa** al → **MANUAL** (veya ortaya → FBWA, hangisinde rahatsan)
3. Arayüzde modun değiştiğini doğrula
4. **GÖREVİ SİL** — inişten önce araçtaki görevi temizle. İki gerekçe:
   - Yüklü görev dururken kazara AUTO'ya geçilmesi (mod anahtarı, failsafe,
     MP'den yanlış tık) uçağı yeniden şekle sokar.
   - Görev **inişli** ise `RTL_AUTOLAND=1` yüzünden RTL de iniş başlatır.
     Sen elle yaklaşırken failsafe tetiklenirse uçak kendi inişine geçer.
5. Rüzgâra karşı, alçak yaklaşma
6. Gazı kes
7. Yere yakınken hafif burun yukarı
8. **DISARM** — hemen, uçak durur durmaz

**RTL ile inmez.** RTL uçağı eve getirir ve `RTL_ALTITUDE`'da tur attırır;
görevde `DO_LAND_START` yoksa **sonsuza kadar döner**. İnişi sen yaparsın.

### 7.2 Otomatik iniş — AUTOLAND

Uçak nerede olursa olsun, görev sürerken bile kalkış noktasına iner.
**Üç tetikleme yolu var:**

| Yol | Menzil | Not |
|---|---|---|
| Panelde **🛬 ŞİMDİ İN** | WiFi ~100–250 m | Ana ekranda ve manuel panelde; onay sorar |
| **Vericide SwD aşağı** | ~500–800 m | WiFi'dan bağımsız. Yukarı = vazgeç |
| Mission Planner → mod AUTOLAND | SiK 1–2 km | Yer modülü laptopa takılı olmalı |

Uçak panel menzilinin dışındayken **SwD tek yoldur** — bu yüzden kalkıştan
önce anahtarın yerini bildiğinizden emin olun.

**Şartlar** — sağlanmazsa araç modu reddeder, panel gerekçeyi yazar:

- Uçak **uçuyor** olmalı. Yerde çalışmaz.
- **Kalkış yönü yakalanmış** olmalı. Yön, uçuş sırasında GPS yer rotasından
  alınır ve yalnızca şu modlarda yakalanır: AUTO, FBWA, MANUAL, TAKEOFF,
  ACRO, STABILIZE, TRAINING, AUTOTUNE. LOITER / CRUISE / FBWB / RTL
  yakalamaz. **Disarm yön kaydını siler** — her uçuşta yeniden kalkmak gerek.

Pratikte: normal kalkış (AUTO görev ya da FBWA elle fırlatma) yönü zaten
yakalar. Panelde "Autoland direction= NNN" mesajını görürsen yakalanmıştır.

**Uçtuğu patern:** kalkış noktasından, yakalanan yönün tersinde
`AUTOLAND_WP_DIST` kadar uzakta daire çizip `AUTOLAND_WP_ALT` irtifasına
alçalır, sonra düz süzülerek kalkış noktasına iner.

> ⚠️ **Kartta şu anki değerlerle bu patern çiti aşıyor.** Arayüzdeki
> "Otomatik iniş — hazır mı" kutusu bunu kalkıştan önce gösterir ve şart
> sağlanmıyorsa 🛬 butonunu kapatır. Aşağıdaki parametre setini uygulayın.

### 7.3 Göreve gömülü iniş

Şekil panelinde **OTOMATİK İN** seçilirse görev inişle biter; şekil bitince
uçak kendiliğinden iner. Bu seçildiğinde **RTL de iniş yapar** (7.1'deki not).

> ⚠️ **Uçakta çalışan pitot yok** (`ARSPD_TYPE` ayarlı ama sensör yok).
> Otomatik iniş hava hızına dayanır; yer hızıyla inişe kalkmak rüzgârda stall
> veya sert çarpma demektir. Elle inişle başla.

### 7.4 Otomatik iniş parametre seti — ✅ UYGULANDI (19 Ağu 2026)

Üç özelliğin (görev sonu inişi, 🛬 anında iniş, batarya 2. kademe inişi)
hepsi bu dört değere bağlı. Fabrika değerleriyle patern güvenlik çemberinin
dışına çıkıyor ve iniş yarıda kalıyordu.

> **Bu set karta yazıldı ve doğrulandı.** Aşağıdaki tablo tarihsel kayıttır;
> "Eski" sütunu fabrika/başlangıç değerleri, "Yeni" sütunu **kartta şu an
> duran** değerlerdir. 26 Ağu 2026'da panelden okunarak yeniden doğrulandı:
> patern 333 m / kullanılabilir 380 m, süzülme 7.1°, engel yok.

| # | Parametre | Eski | **Kartta şu an** | Neden |
|---|---|---|---|---|
| 1 | `FENCE_RADIUS` | 300 | **500** | 300 m normal KALKIŞTA bile aşılıyordu (aşağı bak). 19 Ağu'da 400 yazıldı, **27 Ağu'da 500'e çıkarıldı** — elle kurulan görevlerde iniş dairesi 400'e fazla yaklaşıyordu |
| 2 | `AUTOLAND_WP_DIST` | 400 | **240** | Patern çembere sığsın |
| 3 | `AUTOLAND_WP_ALT` | 55 | **20** | Süzülme 7.1°'de kalsın |
| 4 | `BATT_FS_CRT_ACT` | 1 | **7** | 20.4 V'ta AUTOLAND (olmazsa RTL) |

Doğrulayıcı çıktısı (19 Ağu 2026, `sekil_geometri.inis_plani`):

```
alçalma dairesi yarıçapı      80 m
göreve gömülü iniş, en uzak  320 m
AUTOLAND modu, en uzak       333 m   <- denetim buna göre
çit eylemi 400 m             pay 67 m
süzülme (temkinli/nominal)   7.1° / 4.8°
flare'e (6 m) kadar süzülme  112 m
kalkış çıkıntısı ~303 m      pay 97 m
uyarı/engel                  YOK
```

**Neden `FENCE_RADIUS` 300'de kalamıyor:** kalkışın kendisi ~300 m'ye çıkıyor.
`TKOFF_ALT` 50 m ÷ `TECS_CLMB_MAX` 5 m/s = 10 sn tırmanış, 20 m/s'te 200 m;
üstüne ilk waypoint'e dönüş ~100 m. SITL'de ölçüldü: **303 m**. Çit armlı halde
sürekli aktif (`FENCE_AUTOENABLE` = 0), yani mevcut ayarla **normal kalkışta
bile** `FENCE_ACTION` tetiklenebilir. 400, bu ihlali kapatan en küçük değer.

#### SITL doğrulaması (19 Ağu 2026)

Bu set SITL'de uçuruldu; üç özellik de çalıştı.

**Kalkış çıkıntısı:** 311 m ölçüldü (hesap 303 m). Çit 400 ile **89 m pay**.
Çit 300 olsaydı ihlal edilirdi.

**Batarya 2. kademe inişi** — `BATT_FS_CRT_ACT = 7`, uçak 80 m'de sonsuz daire
çizerken kritik eşik aşıldı. **Hiçbir komut gönderilmedi:**

```
18:50:13  Battery 1 is critical 12.59V used 332 mAh
          -> uçak kendiliğinden AUTOLAND'e geçti
18:50:39  Loiter to alt complete
18:50:39  Landing approach start at 19.5m
18:50:41  Landing glide slope 6.1 degrees
18:50:49  Flare 4.2m sink=1.43 speed=15.1
18:50:54  SIM Hit ground at 0.375 m/s
18:51:05  Auto disarmed
18:51:05  Distance from LAND point=5.38m
```

| Ölçülen | Değer | Beklenen |
|---|---|---|
| Failsafe → tekerlek teması | **41 saniye** | — |
| Kalkış noktasına uzaklık | **5.4 m** | — |
| Dokunuş alçalma hızı | **0.375 m/s** | `TECS_LAND_SINK` 0.25 |
| Paternin eve en uzak noktası | **336 m** | hesap **333 m** ✅ |
| Süzülme açısı | **6.1°** | temkinli 7.1° / nominal 4.8° ✅ |

Ayak izi tahmini %1 hatayla tuttu — denetim güvenilir. Süzülme de temkinli
tahminin altında kaldı, yani denetim güvenli tarafta yanılıyor.

> Dokunuş 0.375 m/s, önceki 55 m'lik yaklaşmadaki 0.25 m/s'den biraz sert.
> Sebep: alçak yaklaşmada flare 4.2 m'de başlıyor (55 m'likte 7.7 m'de) ve
> alçalmayı kesecek yükseklik daha az. Yine de çok yumuşak — mutlak değerde
> yürüyüş hızının altında bir düşey hız.

> ⚠️ **303 m rakamı SITL'den.** Gerçek uçağınız daha yavaş tırmanıyorsa daha
> uzağa çıkar. İlk kalkışta paneldeki sol alt kutuya (eve uzaklık) bakıp tepe
> değerini not edin; 350 m'yi aşıyorsa çiti büyütün.

**Neden 500 değil:** çit 500 ile yaklaşma 30 m'den başlardı (10 m fazla pay),
ama patern 427 m'ye çıkardı. Talon'un 1.72 m kanadı 427 metrede 13.8 yay
dakikası — burnunun yönünü okuyamazsınız, üstelik iniş sırasında uçak alçak
olduğu için gökyüzüne değil arazi fonuna karşı görünür. Otomatik inişi
izlemenin tek amacı gerektiğinde devralmak; göremiyorsanız anlamı kalmıyor.
340 m'de yön hâlâ seçilebiliyor.

> Birkaç başarılı otomatik inişten sonra istenirse çit 500 / dist 325 / alt 30
> setine geçilebilir. Ters sıra (geniş başlayıp daraltmak) daha risklidir.

#### Yumuşak iniş — gerçekten işe yarayan ayarlar

| Parametre | Şu an | Yeni | Neden |
|---|---|---|---|
| `LAND_PITCH_DEG` | 2.5 | **5** | Dokunuşta burun yukarı. Gövde inişinde temas burun yerine arka gövdeye gelir |
| `LAND_THEN_NEUTRL` | 0 | **1** | İniş sonrası disarm'da servolar nötre. Uçak ters/yan durursa servolar zorlanmaz |
| `TECS_LAND_SINK` | 0.25 | 0.25 (aynı) | Dokunuş alçalma hızı. SITL'de ölçülen temas: **0.25–0.27 m/s** — zaten en yumuşak değer |
| `LAND_FLARE_SEC` / `LAND_FLARE_ALT` | 3.0 / 6.0 | aynı | SITL'de düzgün çalıştı. Gerçek iniş verisi olmadan flare ayarlamak tahmin olur |

> ⚠️ **`TECS_LAND_ARSPD` ve `LAND_PF_ARSPD`'ye DOKUNMAYIN.** Uçakta pitot yok.
> `AP_TECS.cpp:445-447`: hava hızı sensörü yoksa TECS ölçüm yapmaz, uçağın
> `AIRSPEED_CRUISE` hızında olduğunu **varsayar**. İniş hızı komutunu
> değiştirmek, TECS'in düzeltmeye çalışacağı sabit bir hata üretir.
> `TECS_SYNAIRSPEED = 0` (sentetik hava hızı kapalı) — ArduPilot'un kendi
> belgesi bunu "considerable limitations" diye uyarıyor, açmayın.
>
> Yumuşaklığın gerçek kaldıracı **süzülme açısı** (yukarıdaki geometri) ve
> `TECS_LAND_SINK`; ikisi de irtifa/alçalma hızıyla çalışır, hava hızıyla değil.

#### Batarya 2. kademesinde otomatik iniş

| Parametre | Şu an | Yeni | Sonuç |
|---|---|---|---|
| `BATT_FS_LOW_ACT` | 1 | 1 (aynı) | 21.6 V → RTL. Eve gelir, siz karar verirsiniz |
| `BATT_FS_CRT_ACT` | 1 | **7** | 20.4 V → **AUTOLAND**, olmazsa RTL'e düşer |

`Failsafe_Action_AUTOLAND_OR_RTL = 7` (ArduPlane/Plane.h). `events.cpp`
`handle_battery_failsafe()` önce `set_mode(mode_autoland)` deniyor; kalkış yönü
yakalanmamışsa mod reddediliyor ve **otomatik olarak RTL'e düşüyor** — yani
7 her durumda 1'den kötü değil.

> İki kademe artık iki ayrı iş yapıyor: **21.6 V uyarı ve eve çağrı**,
> **20.4 V son çare iniş.** Önceden ikisi de RTL'di, yani ikinci kademe boşa
> gidiyordu.

### 7.5 İndikten sonra tekrar kalkmak — "In landing sequence"

**Göreve gömülü inişten sonra uçak arm'ı reddeder:**

```
PreArm: In landing sequence
Arm: In landing sequence
```

Sebep: görev bir iniş dizisine girdiğinde ArduPilot `_flags.in_landing_sequence`
bayrağını kaldırır ve inişten sonra kaldırılmış bırakır.

**Çözüm: arayüzde GÖREVİ SİL'e bas, sonra arm et.** 19 Ağu 2026 SITL'de
doğrulandı: silmeden arm reddedildi, sildikten sonra kabul edildi.

> Not: görevi silmek TEK BAŞINA yetmiyordu — `AP_Mission::clear()` bu bayrağa
> dokunmuyor. Arayüz bu yüzden silme sonrası ayrıca `MISSION_SET_CURRENT 0`
> gönderiyor; `set_current_cmd()` bayrağı en başta koşulsuz siliyor.
> Mission Planner kullanıyorsanız orada görevi silmek yetmeyebilir; yeni bir
> görev yükleyip başlatmak da bayrağı temizler.

**AUTOLAND modu (🛬 ŞİMDİ İN) ile inişte bu sorun yok** — o bir görev inişi
değil, mod inişidir; bayrağı hiç kaldırmaz. Aynı SITL oturumunda doğrulandı:
AUTOLAND'la indikten sonra arm doğrudan kabul edildi.

---

## BÖLÜM 8 — Kapanış

Güç kesme sırası, açılışın **tersi**:

```
1. DISARM
2. Paneli kapat (siyah pencerede Ctrl+C)
3. Uçağın bataryasını çıkar
4. VERİCİYİ KAPAT        ← her zaman son
```

- [ ] Uçuş kayıtlarını al: Pixhawk'ın SD kartındaki `.BIN` log'ları
- [ ] Bataryayı depolama voltajına (≈3.8 V/hücre) çek

---

## REFERANS

### Kumanda düzeni — VrA (CH5) + SwD (CH6)

**Mod knob'u — VrA (CH5).** Karttan ve canlı PWM okumasıyla doğrulandı
(19 Ağu 2026). Tablo daha önce TERS yazılmıştı, düzeltildi.

| Düğme konumu | PWM | `FLTMODE` | Mod |
|---|---|---|---|
| bir uç | ≤1230 | 1 | **MANUAL** |
| | 1231–1360 | 2 | FBWA |
| orta | 1361–1490 | 3 | FBWA |
| | 1491–1620 | 4 | FBWA |
| | 1621–1749 | 5 | FBWA |
| diğer uç | ≥1750 | 6 | **RTL** |

Pratikte üç bölge: **MANUAL — FBWA — RTL**.

**Joystick yönleri — verici ile arayüz AYNI konvansiyonda.**

| Girdi | Sonuç |
|---|---|
| Verici sağ çubuk **aşağı** (kendine çek) | V yüzeyleri yukarı → **burun yukarı** (climb) |
| Arayüz padi **aşağı** | aynı — burun yukarı |
| Verici sağ çubuk **yukarı** (ileri it) | V yüzeyleri aşağı → **burun aşağı** (dive) |
| Arayüz padi **yukarı** | aynı — burun aşağı |

Ölçümle doğrulandı (21 Ağu 2026): verici sağ çubuk aşağı → `RC2 = 1000`,
`SERVO5 = 1900` (V yukarı). Arayüz padi yukarı → RC2 override 2000, ters yön.

> ⚠️ **Paneldeki pad etiketleri 21 Ağu 2026'ya kadar TERS yazılıydı** — üstte
> "BURUN YUKARI", altta "BURUN AŞAĞI" diyordu. Davranış hep doğruydu, yalnızca
> yazı yanlıştı. Sahada pilot etikete güvenip pad'i yukarı itseydi uçak dalışa
> geçerdi. Düzeltildi; artık üstte "BURUN AŞAĞI", altta "BURUN YUKARI".

**Otomatik iniş anahtarı — SwD (CH6), `RC6_OPTION = 183`.**

| SwD | PWM | Ne olur |
|---|---|---|
| **yukarı** (dinlenme, açılış) | ~1000 (<1300) | Normal — VrA ne diyorsa o |
| **aşağı** | ~2000 (>1700) | **AUTOLAND** — kalkış yerine iner |

Yukarı almak **vazgeçer**: AUTOLAND'deyse VrA'nın gösterdiği moda döner
(`RC_Channel_Plane.cpp` `do_aux_function_change_mode`). Karar geri alınabilir.

> **Yön neden böyle:** FS-i6 verici, SwD yukarıdayken açılıyor — aşağıdayken
> açılış kontrolünü geçmiyor. Dolayısıyla "yukarı" zorunlu bir dinlenme
> konumu. Eğer AUTOLAND yukarıya atansaydı, verici her açılışta uçağı iniş
> komutu bekleyen bir anahtarla başlatırdı.
>
> CH6 bu yüzden **vericide** ters çevrildi (Functions → Reverse → Channel 6).
> Ayarın Nor/Rev etiketi önemli değil; ölçüt şu: **SwD yukarıdayken CH6 = 1000.**
> Kart tarafında `RC6_REVERSED` KULLANILMADI — ham PWM'in gerçeği söylemesi,
> Mission Planner'da ve logda kafa karıştırmaması için.

> **Bu yol WiFi'dan bağımsızdır.** Uçak panel menzilinin (100–250 m) dışına
> çıktığında otomatik inişi başlatmanın tek verici yolu budur.

> **Yer testi (19 Ağu 2026, doğrulandı):** uçak disarm haldeyken SwD aşağı
> indirildiğinde otopilot `Must already be flying!` + `Flight mode change
> failed` yazıyor ve mod MANUAL'de kalıyor. Zincir çalışıyor ve yerde kazara
> tetiklenmiyor. Ölçülen PWM: yukarı 1000, aşağı 2000.
>
> Anahtar atanmadan önce CH6 boştaydı ve 1500 µs (orta) okuyordu — bu, FS-i6'da
> **Aux. channels** ekranında Channel 6'ya kaynak atanmadığının işareti.
> **System → Aux. switches** ekranında SwD'yi "on" yapmak yetmiyor; ikinci
> menüde kanala bağlamak da gerekiyor.

### Failsafe eşikleri

| Olay | Eşik | Uçak ne yapar |
|---|---|---|
| Telsiz kesilmesi (kısa) | anında | MANUAL/FBWA'da RTL · AUTO'da **görev devam** (`FS_SHORT_ACTN`=0) |
| Telsiz kesilmesi (uzun) | 5 sn (`FS_LONG_TIMEOUT`) | **RTL** — AUTO dahil (`FS_LONG_ACTN`=**1**, karar 18 Ağu 2026) |
| Düşük batarya | **21.6 V** | **RTL** (`BATT_FS_LOW_ACT`=1) |
| Kritik batarya | **20.4 V** | **RTL** (`BATT_FS_CRT_ACT`=1) |
| Geofence yarıçap | **300 m** (`FENCE_RADIUS`, kartta girili) | RTL |
| Geofence tavan | **100 m** (`FENCE_ALT_MAX`, kartta girili) | RTL |
| Arayüz/GCS kesilmesi | — | **hiçbir şey** (`FS_GCS_ENABL`=0) |

RTL irtifası 100 m (`RTL_ALTITUDE`). Otonom kalkış hedefi 50 m (`TKOFF_ALT`).

> ✅ **`FS_LONG_ACTN` = 1 (RTL) — kartta doğrulandı, 18 Ağu 2026 21:30.**
>
> Bu satır gün içinde iki kez yanlış yazıldı, düzeltmesi burada:
> `mav.parm` dosyasındaki 17 Ağu dökümü **0 (Continue)** diyordu ve belge ona
> göre "kartta 0, 1'e çekilecek" olarak düzeltilmişti. Pixhawk bağlanıp
> parametre doğrudan karttan okununca değerin **zaten 1** olduğu görüldü.
>
> Karışıklığın sebebi: **`mav.parm` bir kayıt değil, canlı anlık görüntüdür.**
> `mavlink_koprusu.sh` her bağlanışında MAVProxy parametreleri karttan çekip
> bu dosyanın üzerine yazıyor ("Saved 992 parameters to mav.parm"). 17 Ağu'daki
> 0 değeri o anın gerçeğiydi; sonradan 1 yapılmış ve dosya bir daha
> güncellenmemişti.
>
> **Kural: parametre tartışmasında `mav.parm`'a değil, karta sorun.**
> ```bat
> set MAV_ENDPOINT=COM3 & set MAV_BAUD=57600
> python -m control.komut parametre FS_LONG_ACTN
> ```
>
> Sonuç: AUTO'da uzun telsiz failsafe'i (5 sn) uçağı RTL'e alır, görev kesilir.
> İnişten önce yüklü görevi temizlemek için arayüzdeki **GÖREVİ SİL** butonu var.

`RTL_AUTOLAND` = 1: göreve `DO_LAND_START` eklendiği an **her RTL otomatik inişe döner** —
failsafe RTL de, arayüzdeki EVE DÖN butonu da. Şu an görevde yok, etkisiz.

### Çıkış pinleri (17 Ağu 2026 — karttan okundu)

| Pin | Görev | `SERVOn_FUNCTION` |
|---|---|---|
| MAIN 1 | Kanatçık **sol** | 4 (Aileron) |
| MAIN 2 | Kanatçık **sağ** | 4 (Aileron) |
| ~~MAIN 3~~ | **ÖLÜ — kullanma** | 0 |
| ~~MAIN 4~~ | **ÖLÜ — kullanma** | 0 |
| MAIN 5 | V-kuyruk **sol** | 79 (VTailLeft) |
| MAIN 6 | **motor / ESC** | 70 (Throttle) |
| MAIN 7 | V-kuyruk **sağ** | 80 (VTailRight) |
| MAIN 8 | boş — servo koluna uygun | 0 |

> Bu harita 17 Ağu 2026'da Pixhawk sıfırlanıp yeniden kurulduktan sonra
> değişti. Eski kayıtlarda MAIN 1/2 V-kuyruk, MAIN 5/7 kanatçık yazıyordu —
> **artık tersi.** MAIN 3 ve 4 fiziksel olarak ölü, `SERVO3/4_FUNCTION = 0`.

Boş pin (MAIN 8) servo kolunu düz takmak için 1500 µs'ye sabitlenebilir:

```
python -m control.servo_ortala
```

### Terminal araçları (arayüz çalışmazsa)

Önce ortamı yükle:

```bat
set MAV_ENDPOINT=COM3 & set MAV_BAUD=57600
```

| Komut | Ne yapar |
|---|---|
| `python -m control.preflight` | uçuş öncesi kontrol |
| `python -m control.servo_ortala` | boş pinleri 1500 µs'ye sabitle |
| `python -m control.run_plane_scenario square` | senaryoyu doğrudan çalıştır |
| `python -m control.zorla_arm` | **yalnız tezgâh testi** — pre-arm kontrollerini atlar |

---

## BİLİNEN AÇIK İŞLER — uçuştan önce kapatılmalı

| # | Konu | Durum |
|---|---|---|
| 1 | ~~**Pusula kalibrasyonu YAPILMADI**~~ — **kapandı** (21 Ağu 2026): dışarıda, SiK telemetri üzerinden Mission Planner ile yapıldı. Karttan doğrulandı: `COMPASS_OFS` = 30.1 / −49.2 / −80.4 (büyüklük 99 mGauss, sınır 1800), `COMPASS_DIA` = 0.986 / 0.997 / 1.009 (ideal 1.0), `COMPASS_ODI` ≈ 0.00x (ideal 0), `COMPASS_SCALE` = 1.141, `COMPASS_DEC` = 0.104 rad. **26 Ağu 2026'da sahada YENİDEN kalibre edildi** — eski kalibrasyonun ölçeği bozuktu: `COMPASS_SCALE` 1.141 → **1.021**, offsetler → 27.2 / −50.3 / −78.6, uyum 3.19. Ölçülen alan 534 mG → **479 mG** (beklenen ~485), yani %10 hata %1'e indi | ✅ kapandı |
| 1b | **`COMPASS_USE2` = 0 — ikinci pusula kapalı ve kalibre değil.** Uçakta 2 manyetometre var (harici GPS içindeki 0x0D kullanımda, dahili 0x0E kapalı). Tek pusula yedeksiz demek. Açılırsa ArduPilot ikisini karşılaştırıp tutarsızlık yakalar, ama "Compasses inconsistent" hatası da çıkabilir. İlk uçuşlardan sonra değerlendirilecek | bilgi |
| 2 | ~~**`FS_LONG_ACTN` karta yazılacak**~~ — **kapandı** (18 Ağu 21:30, karttan okunarak doğrulandı: zaten 1 = RTL) | ✅ kapandı |
| 3 | **`ARSPD_TYPE` = 1 ama pitot yok** — `ARSPD_DEVID` = 0, sensör bulunamıyor. `ARSPD_USE` = 0 olduğu için arm'ı engellemiyor, ama her açılışta olmayan I2C sensörü aranıyor. `0` (None) yapılması öneriliyor. | ⚠️ açık |
| 4 | **`TKOFF_ALT` = 50 m**, görev planında 60–80 m yazıyor. TAKEOFF modu 50 m'de duruyor. | ⚠️ açık |
| 5 | **Akım kalibrasyonu** — `BATT_AMP_PERVLT` = 17.0 (varsayılan). İlk uçuştan sonra log mAh ile şarj cihazı mAh'ı karşılaştırılarak. | ⚠️ açık |
| 6 | **`BATT_VOLT_MULT` = 10.9377** — kalibre görünüyor ama sıfırlama sonrası multimetreyle bir kez daha doğrula. Yanlışsa 21.6 V failsafe'i ya boşuna tetiklenir ya hiç tetiklenmez. | ⚠️ açık |
| 7 | Pervane dönüş yönü hava akışıyla doğrulanacak (hava kuyruğa esmeli) | ⚠️ açık |
| 8 | Wattmetreyle itki testi | ⚠️ açık |
| 9 | **Tek IMU** — `INS_ACC2_ID` = 0, ikinci IMU kartta yok/bozuk. Yedeklilik yok; IMU arızasında EKF'in dönebileceği ikinci sensör bulunmuyor. | bilgi |
| 13 | ~~**`FENCE_RADIUS` = 300 m normal KALKIŞTA bile aşılıyor**~~ — **kapandı** (19 Ağu 2026): `FENCE_RADIUS` = 400 yazıldı, karttan doğrulandı. SITL'de ölçülen kalkış çıkıntısı 311 m → 89 m pay. İlk gerçek kalkışta paneldeki eve-uzaklık kutusunun tepe değerini doğrulayın | ✅ kapandı |
| 13b | ~~eski #13 metni~~ **`FENCE_RADIUS` = 300 m normal KALKIŞTA bile aşılıyor** — `TKOFF_ALT` 50 m ÷ `TECS_CLMB_MAX` 5 m/s = 10 sn tırmanış ≈ 200 m, üstüne ilk waypoint'e dönüş ≈ 100 m. SITL'de 303 m ölçüldü. Çit armlı halde sürekli aktif (`FENCE_AUTOENABLE` = 0), yani kalkış tırmanışında `FENCE_ACTION=1` tetiklenip uçak RTL'e geçebilir. Bölüm 7.4'teki setlerden biri uygulanmalı. | ✅ kapandı — #13'ün arşiv metni |
| 12 | ~~**Otomatik iniş paterni güvenlik çemberinin DIŞINA çıkıyor**~~ — **kapandı** (19 Ağu 2026): `AUTOLAND_WP_DIST` = 240, `AUTOLAND_WP_ALT` = 20 yazıldı. Patern 333 m, kullanılabilir 380 m. Panel "Otomatik iniş — hazır mı" kutusu dört satırı da yeşil gösteriyor | ✅ kapandı |
| 12b | ~~eski #12 metni~~ **Otomatik iniş paterni güvenlik çemberinin DIŞINA çıkıyor** — `AUTOLAND_WP_DIST` = 400, `WP_LOITER_RAD` = 80 → patern eve 480 m; `FENCE_RADIUS` = 300, `FENCE_MARGIN` = 20 → kullanılabilir 280 m. Uçak çiti aşınca `FENCE_ACTION=1` ile RTL'e geçer ve **iniş yarıda kalır**. Hem 🛬 ŞİMDİ İN butonunu hem göreve gömülü inişi etkiler. Çözüm: `AUTOLAND_WP_DIST`'i ~200'e çekmek (süzülme 55/200 = 15°, çok dik → `AUTOLAND_WP_ALT`'ı da ~25'e indirmek gerekir) **ya da** `FENCE_RADIUS`'u alana göre büyütmek (600 m patern için rahat). Alan büyüklüğüne göre karar verilecek. | ✅ kapandı — #12'nin arşiv metni |
| 14 | ~~`LAND_THEN_NEUTRL` = 0~~ — **kapandı** (19 Ağu 2026): 1 yazıldı, karttan doğrulandı. İniş sonrası disarm'da servolar nötre döner | ✅ kapandı |
| 16 | ~~🔴 `ARMING_SKIPCHK` = −1~~ — **kapandı** (19 Ağu 2026, 21:25): 0 yazıldı. Arm denemesiyle doğrulandı — otopilot artık `Compass not calibrated`, `GPS 1: Bad fix`, `Fence requires position`, `Hardware safety switch`, `RTL mode not armable` diye gerçek engelleri sayıyor. Öncesinde hepsi sessizce atlanıyordu | ✅ kapandı |
| 17 | ~~🔴 `SERVO6_MAX` = 1150~~ — **kapandı** (19 Ağu 2026, 21:25): 2000 yazıldı. Gaz artık tam aralık | ✅ kapandı |
| 16b | ~~eski #16 metni~~ 🔴 **`ARMING_SKIPCHK` = −1 — TÜM pre-arm kontrolleri atlanıyor.** ArduPilot varsayılanı 0. Belge: *"a value of -1 can be used to skip all non-mandatory checks"*. Şu an uçak kalibre olmamış pusula, GPS fix'i yok, sağlıksız INS ile **arm oluyor**. Yalnızca 3 zorunlu kontrol çalışıyor (OpenDroneID, RC-in-kalibrasyon, seri protokol). **`ARMING_SKIPCHK = 0` yapılmalı** — o zaman pusula kalibrasyonu ve GPS fix gerçekten arm'ı engeller. Dokümanda "pusula kalibrasyonu arm engelleyici" yazıyordu; bu ayarla DEĞİLDİ | ✅ kapandı — #16'nın arşiv metni |
| 17b | ~~eski #17 metni~~ 🔴 **`SERVO6_MAX` = 1150 — gaz çıkışı %15'te kilitli.** Gaz kanalı 1000–1150 µs veriyor; `SRV_Channel::pwm_from_range` %100 gazı `SERVO6_MAX`'a eşliyor. Motor tam gaza çıkamaz, **uçak kalkamaz**. Muhtemelen tezgah testinden kalma bir emniyet sınırı; hiçbir belgede kaydı yok. Uçuştan önce **`SERVO6_MAX = 2000`** yapılmalı ve ESC kalibrasyonuyla uyumu doğrulanmalı | ✅ kapandı — #17'nin arşiv metni |
| 15 | **`TECS_LAND_PMAX` ölçülecek** — motor ARKADA (itici). `LAND_PITCH_DEG` sadece TABAN; gerçek dokunuş açısını `TECS_LAND_PMAX` (tavan, şu an 10°) belirliyor. Uçağı gövdesi üstüne koyup burnu kaldırın, arka parça (pervane/V-kuyruk ucu) yere değene kadar; o açı − 4° = yazılacak değer. 14°'den büyük çıkarsa mevcut 10 zaten doğru. **`LAND_PITCH_DEG` = 5 önerisi GERİ ALINDI** — o çekici motor mantığıydı, itici için ters | ⚠️ açık (ölçüm bekliyor) |
| 10 | `TERRAIN_ENABLE` = 1 ama arazi verisi yok — SYS_STATUS'ta sağlıksız görünüyor, arm'ı engellemiyor | bilgi |
| 11 | ~~Arayüzdeki daire yarıçapı hesabı `AIRSPEED_CRUISE` = 20 m/s'ye göre tekrar bakılmalı~~ — **kapandı** (18 Ağu 2026): şekil denetleyicisi `AIRSPEED_CRUISE` ve `ROLL_LIMIT_DEG`'i karttan okuyup `R = v²/(g·tanθ)` ile minimum yarıçapı hesaplıyor, uçulamayacak şekli yüklemiyor | ✅ kapandı |

### Kapanmış olanlar (17 Ağu 2026 karttan doğrulandı)

- ✅ **İvmeölçer kalibrasyonu** — `INS_ACCSCAL` 0.992 / 1.000 / 0.986
- ✅ **Seviye kalibrasyonu** — `AHRS_TRIM_X/Y` sıfırdan farklı
- ✅ **RC kalibrasyonu** — RC1–6 ölçülmüş değerlerde, `RC2_REVERSED` = 1
- ✅ `SERVO6_FUNCTION` = 70 (Throttle) — gaz kanalında arm koruması var
- ✅ **Kanatçık aralıkları eşitlendi** — MAIN 1 ve MAIN 2 artık 1180–1820
- ✅ **Kritik batarya artık RTL** — `BATT_FS_CRT_ACT` = 1 (eskiden 2 = görev tabanlı iniş, etkisizdi)
- ✅ `BATT_CAPACITY` = 3000, `BATT_LOW_VOLT` = 21.6, `BATT_CRT_VOLT` = 20.4
- ✅ `TECS_SINK_MAX` = 5 (sıfırlama sonrası 0 kalmıştı, geri konuldu)
- ✅ `FS_LONG_ACTN` = 1 — AUTO'da bile uzun failsafe RTL. **Bu satır baştan
  doğruymuş:** 18 Ağu'da `mav.parm` dökümüne bakılıp "yanlış, kartta 0" diye
  işaretlenmişti; Pixhawk bağlanınca karttan okunan değer 1 çıktı. Hata
  dökümün eskiliğindeydi (bkz. failsafe bölümündeki not).
- ✅ **Geofence saha rakamları girili** — `FENCE_RADIUS` = **500 m**
  (300 → 400 → 500; son artış 27 Ağu), `FENCE_ALT_MAX` = 100 m,
  `FENCE_TYPE` = **3** (26 Ağu'da 7'den düşürüldü, poligon biti ARM'ı kilitliyordu).
- ✅ `MAV_GCS_SYSID` = 255 — RC override izni doğru
- ✅ `RC_OVERRIDE_TIME` = 3 — arayüz joystick ve senaryoları çalışır
- ✅ `SERIAL0_PROTOCOL` = 2 / `SERIAL0_BAUD` = 115 — USB hattı (masa bağlantısı)
- ✅ `RALLY_TOTAL` = 0 — `RTL_AUTOLAND`=1 sapma rally noktasına gitmez
- ✅ `LOG_DISARMED` = 0
- ✅ ESC kalibrasyonu (alıcıdan yapıldı)
- ✅ Motor MAIN 6'da, saat yönünün tersine dönüyor (pervane tarafından bakınca)
- ✅ Uçuş öncesi kontrol arayüze taşındı
