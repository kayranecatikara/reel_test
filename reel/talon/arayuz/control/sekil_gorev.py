#!/usr/bin/env python3
"""
sekil_gorev.py — sekil_geometri planını ArduPlane görev öğelerine çevirir.

Burada MAVLink SABİTLERİ kullanılır ama araç bağlantısı KURULMAZ. Öğeleri kuran
kod saf bir fonksiyondur; yükleme protokolünü gcs/sunucu.py çalıştırır.

    python -m control.sekil_gorev --test
    python -m control.sekil_gorev --sekil daire --olcu 120 --irtifa 60 --tur 3


YÜKLEME NEDEN ALT SÜREÇTE DEĞİL, ARAYÜZ SÜRECİNDE
--------------------------------------------------
İlk tasarım bunu preflight gibi bir alt süreç yapacaktı. Üç sebeple vazgeçildi:

  * Alt süreç her çağrıda connect_mavlink() + wait_heartbeat yapmak zorunda;
    bu 8-30 saniye sürebiliyor, asıl protokol ise ~1 saniye.
  * Alt süreç SENARYO_ENDPOINT'e (14550) bağlanır ve preflight/senaryo ile aynı
    UDP portunu paylaşır — api_preflight'ın 409 döndürme sebebi tam olarak bu.
    Görev yüklemenin senaryo çalışırken de mümkün olması gerekiyor.
  * Görev İLERLEMESİ (MISSION_CURRENT, MISSION_ITEM_REACHED) zaten arayüzün
    telemetri döngüsünden geliyor. Yükleyiciyi başka bir sürece koymak durumu
    ikiye böler.

Arayüz sürecindeki "yalnızca telemetri_dongusu recv_match çağırabilir" kuralı
korunuyor: telemetri döngüsü görev mesajlarını Durum'daki posta kutusuna
bırakıyor, yükleyici oradan okuyor — ack_bekle/param_bekle deseninin aynısı.


ARDUPLANE KAYNAĞINDAN DOĞRULANAN DÖRT DAVRANIŞ
----------------------------------------------
1. Uçak öğeleri MISSION_REQUEST ile ister, MISSION_REQUEST_INT ile DEĞİL
   (MissionItemProtocol.cpp — mavlink_msg_mission_request_send). Yalnızca _INT
   bekleyen bir istemci sonsuza kadar bekler.
2. NAV_WAYPOINT.param2 = o noktaya özel kabul yarıçapı, metre (AP_Mission.cpp:1092).
   Sıfırdan büyükse WP_RADIUS ve açı ölçeklemesi devre dışı kalır
   (commands_logic.cpp:674). Şekli bozan "birkaç noktayı aynı anda geç" hatasının
   araç parametresine dokunmadan çözümü budur.
3. do_takeoff() NAV_TAKEOFF'un lat/lon'unu home+10 ile EZER. Kalkış yönü
   seçilemez; uçak fırlatıldığı yöne tırmanır. Bu yüzden 0,0 gönderiyoruz.
4. Görev bitince exit_mission_callback() zaten RTL'e geçer. Son öğeyi açıkça
   yazmak Mission Planner'da okunur kalmasını sağlar.


GÖREV SONU İNİŞİ (bitince="inis")
---------------------------------
Üç öğe eklenir: DO_LAND_START + NAV_LOITER_TO_ALT + NAV_LAND. Geometriyi
sekil_geometri.inis_plani() üretir; burada yalnızca MAVLink kodlaması var.

Kaynaktan doğrulanan üç ayrıntı:

  * NAV_LOITER_TO_ALT'ta yarıçap param2'DEDİR, param1'de değil
    (AP_Mission.cpp:1178 — cmd.p1 = fabsf(packet.param2)). param1'e yazmak
    yarıçapı sessizce sıfır bırakır, uçak WP_LOITER_RAD'a düşer.
    param2 NEGATİF ise dönüş saat yönünün tersinedir.
  * param4 = loiter_xtrack. 0 = çapraz rota daire MERKEZİNDEN sonraki noktaya
    çizilir. Burada daire merkezi zaten yaklaşma başlangıcı olduğu için 0
    doğru olan: merkez -> ev doğrusu tam final rotasıdır.
  * DO_LAND_START'ın KONUMU okunur (get_landing_sequence_start,
    AP_Mission.cpp:2473): birden çok iniş dizisi varsa uçak en yakınını seçer.
    Konum boş bırakılırsa sonraki nav komutunun konumu kullanılır. Yine de
    açıkça yazıyoruz — Mission Planner'da da okunur kalsın.

DİKKAT — GÖREVE İNİŞ EKLEMEK RTL'İN DAVRANIŞINI DA DEĞİŞTİRİR.
Bu uçakta RTL_AUTOLAND = 1. mode_rtl.cpp:105-124'e göre uçak eve varıp çemberi
yakaladığında ve irtifa hatası 10 m'nin altına düştüğünde görevde
DO_LAND_START arar; bulursa AUTO'ya geçip iner. Yani iniş içeren bir görev
yüklüyken RTL butonu artık "eve dön ve bekle" değil "eve dön ve İN" demektir.
"""

import argparse
import json
import sys

from pymavlink import mavutil

from control.sekil_geometri import SEKILLER, plan_uret

# Kalkışta istenen minimum tırmanış açısı (derece). Firmware p1 <= 0 ise 4°
# kullanıyor; bu uçak için düşük. PTCH_LIM_MAX_DEG=20 ve TKOFF_LVL_PITCH=15
# olduğuna göre 10-12° güvenli aralık.
KALKIS_PITCH = 10.0

# Kalkış irtifası tavanı. Şekil irtifası daha yüksekse kalan tırmanış ilk şekil
# noktasına giderken yapılır. Kalkışta 80 m beklemek TECS_CLMB_MAX=5 m/s ile
# 16 saniye ≈ 320 m menzil demek; 300 m'lik güvenlik çemberinde bu risklidir.
KALKIS_IRTIFA_TAVAN = 50.0

BITIS_SECENEKLERI = ("rtl", "bekle", "inis")

# MAV_MISSION_RESULT kodlarının Türkçesi. Arayüzde "hata 13" yerine ne olduğu
# yazsın diye — MAV_SONUC_ADLARI'nın görev karşılığı.
MAV_GOREV_ADLARI = {
    0: "kabul edildi",
    1: "genel hata (araç görevi kabul etmedi)",
    2: "bu komut türü desteklenmiyor",
    3: "koordinat çerçevesi desteklenmiyor",
    4: "param1 geçersiz",
    5: "param2 geçersiz",
    6: "param3 geçersiz",
    7: "param4 geçersiz",
    8: "enlem (x) geçersiz",
    9: "boylam (y) geçersiz",
    10: "irtifa (z) geçersiz",
    11: "sıra numarası beklenenden farklı",
    12: "araçta yer yok — görev çok uzun",
    13: "reddedildi (başka bir yer istasyonu şu an görev yüklüyor olabilir)",
    14: "yükleme iptal edildi (araç zaman aşımına uğradı)",
    None: "araç yanıt vermedi (zaman aşımı)",
}


def _oge(seq, command, frame=6, param1=0.0, param2=0.0, param3=0.0,
         param4=0.0, lat=0.0, lon=0.0, irtifa=0.0, current=0, autocontinue=1):
    """
    Tek bir MISSION_ITEM_INT alan sözlüğü.

    MISSION_ITEM (deprecated) kullanılmıyor: lat/lon float'tır, 1e-7 derece
    çözünürlüğü kaybolur (~1 m kuantalama) ve ArduPilot'un iç işleyicisi zaten
    mavlink_mission_item_int_t alıyor.

    mission_type ALANI YOK. Bu proje pymavlink'in v1.0 ardupilotmega
    diyalektiyle çalışıyor (hiçbir yerde MAVLINK20 ayarlanmıyor) ve o sürümde
    mission_type bir MAVLink 2 uzantısı olduğu için mesajda bulunmuyor.
    Sorun değil: ArduPilot mavlink2_requirement_met() içinde NORMAL görev tipi
    için MAVLink 2 şartı KOYMUYOR, yalnızca fence/rally gibi diğer tipler için
    koyuyor. Alan yoksa tip 0 (MAV_MISSION_TYPE_MISSION) kabul edilir — zaten
    istediğimiz bu.
    """
    return {
        "seq": seq,
        "frame": frame,
        "command": command,
        "current": current,
        "autocontinue": autocontinue,
        "param1": float(param1),
        "param2": float(param2),
        "param3": float(param3),
        "param4": float(param4),
        "x": int(round(lat * 1e7)),
        "y": int(round(lon * 1e7)),
        "z": float(irtifa),
    }


def gorev_ogeleri(plan, ev_lat, ev_lon, ev_irtifa=0.0, bitince="rtl"):
    """
    plan_uret() çıktısını araca gönderilecek MISSION_ITEM_INT listesine çevirir.

    Dönen listede öğeler seq sırasındadır. target_system / target_component
    alanları YOKTUR — gönderim anında sunucu ekler.

    Ayrıca ("ilk_sekil_seq") döndürülür: uçak zaten havadaysa görev buradan
    başlatılır, kalkış adımı atlanır.
    """
    if bitince not in BITIS_SECENEKLERI:
        raise ValueError(f"bilinmeyen bitiş: {bitince}")

    m = mavutil.mavlink
    ogeler = []

    # seq 0 — ev yer tutucu.
    # AP_Mission::read_cmd_from_storage(0) her zaman AHRS home'unu döndürür,
    # yani gönderdiğimiz içerik yok sayılır. Ama protokol seq 0'ı da ister
    # (init_send_requests(0, count-1)); göndermezsek yükleme hiç başlamaz.
    ogeler.append(_oge(0, m.MAV_CMD_NAV_WAYPOINT, frame=m.MAV_FRAME_GLOBAL,
                       lat=ev_lat, lon=ev_lon, irtifa=ev_irtifa, current=1))

    # seq 1 — otomatik kalkış.
    # lat/lon 0: do_takeoff() bunları home+10 ile ezdiği için anlamsız; sıfır
    # göndermek "buranın önemi yok"u belgeliyor.
    kalkis_irtifa = min(plan["irtifa"], KALKIS_IRTIFA_TAVAN)
    ogeler.append(_oge(1, m.MAV_CMD_NAV_TAKEOFF, param1=KALKIS_PITCH,
                       irtifa=kalkis_irtifa))

    ilk_sekil_seq = len(ogeler)

    for n in plan["gorev_noktalari"]:
        seq = len(ogeler)
        if n["tip"] == "loiter_turns":
            # param3 = yarıçap (tamsayı metre, işaret yönü verir). param3'e
            # ASLA 0 gönderilmez: ArduPlane o zaman kullanıcının yarıçapını yok
            # sayıp WP_LOITER_RAD'ı (bu uçakta 90 m) kullanır.
            yaricap = max(1.0, float(n["yaricap"]))
            if int(n["tur"]) == 0:
                # Sonsuz daire. LOITER_TURNS param1=0 "sıfır tur" demektir ve
                # komut anında tamamlanır — sonsuz için LOITER_UNLIM gerekir.
                ogeler.append(_oge(seq, m.MAV_CMD_NAV_LOITER_UNLIM,
                                   param3=yaricap, lat=n["lat"], lon=n["lon"],
                                   irtifa=n["irtifa"]))
            else:
                ogeler.append(_oge(seq, m.MAV_CMD_NAV_LOITER_TURNS,
                                   param1=int(n["tur"]), param3=yaricap,
                                   param4=1.0, lat=n["lat"], lon=n["lon"],
                                   irtifa=n["irtifa"]))
        else:
            # param2 = bu noktaya özel kabul yarıçapı (bkz. modül başlığı, 2)
            ogeler.append(_oge(seq, m.MAV_CMD_NAV_WAYPOINT,
                               param2=int(n.get("kabul", 0)),
                               lat=n["lat"], lon=n["lon"], irtifa=n["irtifa"]))

    # Tur tekrarı — yalnızca poligonlar için. Daire tur sayısını kendi taşıyor.
    # tur = 0 SONSUZ demek; "or 1" yazılırsa 0 sessizce 1'e döner.
    tur = plan.get("tur")
    tur = 1 if tur is None else int(tur)
    if plan["yontem"] == "poligon" and tur != 1:
        # param2 = kaç kez geri sıçranacak. İlk geçiş 1. turdur, bu yüzden
        # tur-1. tur=0 (sonsuz) istenirse -1 gönderilir.
        tekrar = -1 if tur == 0 else tur - 1
        ogeler.append(_oge(len(ogeler), m.MAV_CMD_DO_JUMP, frame=0,
                           param1=ilk_sekil_seq, param2=tekrar))

    # Son öğe.
    if bitince == "inis":
        inis = plan.get("inis")
        if not inis:
            raise ValueError("bitince=inis istendi ama planda iniş paterni yok "
                             "— plan_uret(inis=True) ile üretilmeli")
        bas = inis["baslangic"]
        # Yarıçap işareti dönüş yönünü verir; pozitif = saat yönü.
        yaricap = max(1.0, float(inis["loiter_yaricap"]))

        # 1) İniş dizisinin başlangıç işareti. RTL bunu arar (RTL_AUTOLAND=1).
        ogeler.append(_oge(len(ogeler), m.MAV_CMD_DO_LAND_START,
                           lat=bas["lat"], lon=bas["lon"],
                           irtifa=inis["yaklasma_irtifa"]))

        # 2) Yaklaşma başlangıcında daire çizerek yaklaşma irtifasına alçal.
        #    verify_loiter_to_alt irtifaya varınca bırakmaz; burun EVE dönene
        #    kadar bekletir, yani daireden çıkış hizalıdır.
        ogeler.append(_oge(len(ogeler), m.MAV_CMD_NAV_LOITER_TO_ALT,
                           param2=yaricap, param4=0.0,
                           lat=bas["lat"], lon=bas["lon"],
                           irtifa=inis["yaklasma_irtifa"]))

        # 3) İniş. param1 = pas geçme irtifası; 0 bırakılırsa kalkış irtifası
        #    kullanılır (do_land, commands_logic.cpp).
        ogeler.append(_oge(len(ogeler), m.MAV_CMD_NAV_LAND,
                           lat=ev_lat, lon=ev_lon, irtifa=0.0))

    elif bitince == "rtl":
        ogeler.append(_oge(len(ogeler), m.MAV_CMD_NAV_RETURN_TO_LAUNCH,
                           frame=0))
    else:
        # Şekil merkezinde süresiz bekle — hedef İHA senaryosunda uçağın
        # alanda kalması genelde istenen davranış.
        merkez = plan["merkez"]
        ogeler.append(_oge(len(ogeler), m.MAV_CMD_NAV_LOITER_UNLIM,
                           lat=merkez["lat"], lon=merkez["lon"],
                           irtifa=plan["irtifa"]))

    return {"ogeler": ogeler, "ilk_sekil_seq": ilk_sekil_seq,
            "kalkis_irtifa": kalkis_irtifa, "bitince": bitince,
            "inis_var": bitince == "inis"}


# ---------------------------------------------------------------------------
# CLI — masada test
# ---------------------------------------------------------------------------

def _testler():
    hata = []

    def kontrol(ad, kosul, ayrinti=""):
        print(f"{'  [OK]  ' if kosul else ' [HATA] '} {ad}"
              + (f" — {ayrinti}" if ayrinti else ""))
        if not kosul:
            hata.append(ad)

    m = mavutil.mavlink
    lat0, lon0 = 37.6193, -122.3816

    # --- Kare, 3 tur, RTL ile bitiyor ---
    plan = plan_uret("kare", lat0, lon0, 60.0, tur=3, olcu_m=250.0,
                     ev_lat=lat0, ev_lon=lon0)
    g = gorev_ogeleri(plan, lat0, lon0)
    o = g["ogeler"]
    kontrol("kare görevi 8 öğe (ev+kalkış+4 köşe+jump+rtl)", len(o) == 8,
            f"{len(o)} öğe")
    kontrol("seq 0 ev yer tutucu, current=1, GLOBAL çerçeve",
            o[0]["seq"] == 0 and o[0]["current"] == 1
            and o[0]["frame"] == m.MAV_FRAME_GLOBAL)
    kontrol("seq 1 NAV_TAKEOFF, pitch 10°, lat/lon sıfır",
            o[1]["command"] == m.MAV_CMD_NAV_TAKEOFF
            and o[1]["param1"] == 10.0 and o[1]["x"] == 0 and o[1]["y"] == 0)
    kontrol("kalkış irtifası 50 m tavanına uyuyor", o[1]["z"] == 50.0,
            f"{o[1]['z']} m")
    kontrol("köşelere kabul yarıçapı (param2) yazılmış",
            all(o[i]["param2"] > 0 for i in range(2, 6)),
            f"param2 = {o[2]['param2']:.0f} m")
    kontrol("seq sıraları boşluksuz artıyor",
            [x["seq"] for x in o] == list(range(len(o))))
    kontrol("DO_JUMP hedefi ilk şekil öğesi, tekrar = tur-1",
            o[6]["command"] == m.MAV_CMD_DO_JUMP
            and o[6]["param1"] == g["ilk_sekil_seq"] and o[6]["param2"] == 2.0,
            f"hedef seq {o[6]['param1']:.0f}, {o[6]['param2']:.0f} tekrar")
    kontrol("son öğe RTL", o[-1]["command"] == m.MAV_CMD_NAV_RETURN_TO_LAUNCH)
    kontrol("koordinatlar 1e7 tamsayı olarak kodlanmış",
            isinstance(o[2]["x"], int) and abs(o[2]["x"]) > 1e8,
            f"x = {o[2]['x']}")

    # --- Tek tur: DO_JUMP hiç olmamalı ---
    plan1 = plan_uret("kare", lat0, lon0, 60.0, tur=1, olcu_m=250.0,
                      ev_lat=lat0, ev_lon=lon0)
    o1 = gorev_ogeleri(plan1, lat0, lon0)["ogeler"]
    kontrol("tek turda DO_JUMP eklenmiyor",
            not any(x["command"] == m.MAV_CMD_DO_JUMP for x in o1),
            f"{len(o1)} öğe")

    # --- Sonsuz tur: param2 = -1 ---
    plan0 = plan_uret("kare", lat0, lon0, 60.0, tur=0, olcu_m=250.0,
                      ev_lat=lat0, ev_lon=lon0)
    o0 = gorev_ogeleri(plan0, lat0, lon0)["ogeler"]
    jump = [x for x in o0 if x["command"] == m.MAV_CMD_DO_JUMP][0]
    kontrol("sonsuz turda DO_JUMP param2 = -1", jump["param2"] == -1.0)

    # --- Daire: tek LOITER_TURNS, param3 asla sıfır ---
    plan_d = plan_uret("daire", lat0, lon0, 60.0, tur=3, olcu_m=120.0,
                       ev_lat=lat0, ev_lon=lon0)
    od = gorev_ogeleri(plan_d, lat0, lon0)["ogeler"]
    loiter = [x for x in od if x["command"] == m.MAV_CMD_NAV_LOITER_TURNS]
    kontrol("daire görevi 4 öğe (ev+kalkış+loiter+rtl)", len(od) == 4,
            f"{len(od)} öğe")
    kontrol("LOITER_TURNS param1=tur, param3=yarıçap (sıfır değil)",
            len(loiter) == 1 and loiter[0]["param1"] == 3.0
            and loiter[0]["param3"] == 120.0)
    kontrol("dairede DO_JUMP yok (tur sayısı komutun içinde)",
            not any(x["command"] == m.MAV_CMD_DO_JUMP for x in od))

    # --- Elips: nokta sayısı kadar waypoint ---
    plan_e = plan_uret("elips", lat0, lon0, 60.0, tur=2, olcu_m=170.0,
                       olcu2_m=110.0, ev_lat=lat0, ev_lon=lon0)
    oe = gorev_ogeleri(plan_e, lat0, lon0)["ogeler"]
    wp = [x for x in oe if x["command"] == m.MAV_CMD_NAV_WAYPOINT
          and x["seq"] > 0]
    kontrol("elips waypoint sayısı planla aynı",
            len(wp) == len(plan_e["gorev_noktalari"]),
            f"{len(wp)} nokta")

    # --- "bekle" seçeneği ---
    ob = gorev_ogeleri(plan, lat0, lon0, bitince="bekle")["ogeler"]
    kontrol("bitince=bekle → son öğe LOITER_UNLIM",
            ob[-1]["command"] == m.MAV_CMD_NAV_LOITER_UNLIM)

    # --- Görev sonu inişi --------------------------------------------------
    esik = {"AUTOLAND_WP_ALT": 55.0, "AUTOLAND_WP_DIST": 400.0,
            "WP_LOITER_RAD": 90.0, "FENCE_RADIUS": 600.0,
            "FENCE_MARGIN": 20.0, "FENCE_ALT_MAX": 100.0}
    plan_i = plan_uret("kare", lat0, lon0, 60.0, tur=1, olcu_m=250.0,
                       ev_lat=lat0, ev_lon=lon0, esikler=esik,
                       inis=True, inis_yon=270.0)
    gi = gorev_ogeleri(plan_i, lat0, lon0, bitince="inis")
    oi = gi["ogeler"]
    kontrol("inişli kare 9 öğe (ev+kalkış+4 köşe+land_start+loiter+land)",
            len(oi) == 9, f"{len(oi)} öğe")
    kontrol("son üç öğe DO_LAND_START, LOITER_TO_ALT, NAV_LAND",
            [x["command"] for x in oi[-3:]] == [m.MAV_CMD_DO_LAND_START,
                                                m.MAV_CMD_NAV_LOITER_TO_ALT,
                                                m.MAV_CMD_NAV_LAND])
    kontrol("LOITER_TO_ALT yarıçapı param2'de, param1 boş",
            oi[-2]["param2"] == 90.0 and oi[-2]["param1"] == 0.0,
            f"param1={oi[-2]['param1']}, param2={oi[-2]['param2']}")
    kontrol("NAV_LAND kalkış noktasında, irtifa 0",
            oi[-1]["x"] == int(round(lat0 * 1e7))
            and oi[-1]["y"] == int(round(lon0 * 1e7)) and oi[-1]["z"] == 0.0)
    kontrol("DO_LAND_START konumu yaklaşma başlangıcıyla aynı",
            oi[-3]["x"] == oi[-2]["x"] and oi[-3]["y"] == oi[-2]["y"])
    kontrol("yaklaşma başlangıcı iniş noktasından farklı bir yerde",
            oi[-2]["y"] != oi[-1]["y"])
    kontrol("inişte de seq boşluksuz",
            [x["seq"] for x in oi] == list(range(len(oi))))
    kontrol("dönüşte inis_var bayrağı var", gi["inis_var"] is True)

    # İniş paterni olmayan bir planla bitince=inis istemek SESSİZCE
    # RTL'e düşmemeli — yarım iniş sahada en tehlikeli hata.
    try:
        gorev_ogeleri(plan, lat0, lon0, bitince="inis")
        kontrol("iniş planı yokken bitince=inis hata veriyor", False)
    except ValueError:
        kontrol("iniş planı yokken bitince=inis hata veriyor", True)

    # Daire + iniş: LOITER_TURNS ile NAV_LOITER_TO_ALT karışmamalı.
    plan_di = plan_uret("daire", lat0, lon0, 60.0, tur=2, olcu_m=120.0,
                        ev_lat=lat0, ev_lon=lon0, esikler=esik,
                        inis=True, inis_yon=0.0)
    odi = gorev_ogeleri(plan_di, lat0, lon0, bitince="inis")["ogeler"]
    kontrol("daire+iniş 6 öğe, son öğe NAV_LAND",
            len(odi) == 6 and odi[-1]["command"] == m.MAV_CMD_NAV_LAND,
            f"{len(odi)} öğe")
    kontrol("daire+inişte hem LOITER_TURNS hem LOITER_TO_ALT var",
            any(x["command"] == m.MAV_CMD_NAV_LOITER_TURNS for x in odi)
            and any(x["command"] == m.MAV_CMD_NAV_LOITER_TO_ALT for x in odi))

    # --- Öğeler bu pymavlink sürümünün mission_item_int_send'ine uyuyor mu ---
    # Alan listesini elle yazmak yerine kurucudan okuyoruz: pymavlink sürümü
    # değişip mission_type eklenirse test kendiliğinden haber verir.
    beklenen = set(mavutil.mavlink.MAVLink_mission_item_int_message.fieldnames)
    beklenen -= {"target_system", "target_component"}   # gönderirken eklenir
    kontrol("öğe alanları mission_item_int_send ile birebir uyuşuyor",
            all(set(x.keys()) == beklenen for x in o + oi),
            f"beklenen {sorted(beklenen)}")

    print()
    if hata:
        print(f"SONUÇ: {len(hata)} test BAŞARISIZ — {', '.join(hata)}")
        return 1
    print("SONUÇ: tüm testler geçti")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Şekil görev öğelerini kurar")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--sekil", choices=SEKILLER, default="kare")
    ap.add_argument("--lat", type=float, default=37.6193)
    ap.add_argument("--lon", type=float, default=-122.3816)
    ap.add_argument("--olcu", type=float, default=250.0)
    ap.add_argument("--olcu2", type=float, default=None)
    ap.add_argument("--irtifa", type=float, default=60.0)
    ap.add_argument("--yon", type=float, default=0.0)
    ap.add_argument("--tur", type=int, default=3)
    ap.add_argument("--bitince", choices=BITIS_SECENEKLERI, default="rtl")
    ap.add_argument("--inis-yon", type=float, default=0.0,
                    help="iniş yönü (pusula derecesi, uçağın final rotası)")
    args = ap.parse_args()

    if args.test:
        return _testler()

    plan = plan_uret(args.sekil, args.lat, args.lon, args.irtifa, args.tur,
                     args.olcu, args.olcu2, args.yon,
                     ev_lat=args.lat, ev_lon=args.lon,
                     inis=(args.bitince == "inis"), inis_yon=args.inis_yon)
    if plan["engel"]:
        for u in plan["uyarilar"]:
            print(f"[{u['seviye'].upper()}] {u['metin']}", file=sys.stderr)
        return 1
    g = gorev_ogeleri(plan, args.lat, args.lon, bitince=args.bitince)
    print(json.dumps(g, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
