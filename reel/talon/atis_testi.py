#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
ATIŞ TESTİ — "attığımda otopilot bunu ALGILAR MI?"  (ARM YOK, PERVANE YOK)
================================================================================
⛔⛔ NİYE BU TEST: AUTO kalkışta motorun çalışmasının TEK tetiği, uçağın
   `TKOFF_THR_MINACC` (m/s²) eşiğini aşan bir ileri ivme görmesidir.
   Yumuşak atarsan otopilot "atıldım" DEMEZ ve motor HİÇ ÇALIŞMAZ —
   uçak elinden çıkar ve süzülerek yere iner. Bu, atış kazalarının
   en sinsi sebebidir çünkü hiçbir hata mesajı vermez.

⭐ BU TEST ARM GEREKTİRMEZ:
     * arm yok      -> motor dönemez
     * pervane yok  -> zaten dönemez
     * GPS yok      -> gerek yok, ivmeölçer GPS'siz çalışır
   Yani KAPALI ORTAMDA, GÜVENLE yapılır. Ölçtüğü şey senin KOLUN.

NASIL ÇALIŞIR:
   Uçağın gövde-X (ileri) eksenindeki ivmesini okur ve tepe değeri
   `TKOFF_THR_MINACC` ile karşılaştırır. Sen uçağı elinde tutup ATAR
   GİBİ ileri savurursun (bırakmadan!); araç sana kaç m/s² ürettiğini
   söyler.

⚠ YERÇEKİMİ ÇIKARILIR: uçak yatay dururken X ekseni ~0 okur, ama burnu
  kaldırınca yerçekiminin bir bileşeni X'e düşer. Bu test İLERİ ivmeyi
  ölçtüğü için ölçüm sırasında uçağı YATAY tutmak gerekir.

Kullanım:
    python3 reel/talon/atis_testi.py
================================================================================
"""
import argparse
import math
import sys
import time


def main():
    ap = argparse.ArgumentParser(description="Elle atış algılama testi")
    ap.add_argument("--mav", default="udp:127.0.0.1:14550")
    ap.add_argument("--sure", type=float, default=45.0)
    a = ap.parse_args()

    from pymavlink import mavutil
    M = mavutil.mavlink

    print("=" * 72)
    print("  ATIŞ TESTİ — otopilot atışını algılar mı?")
    print("=" * 72)
    print("  ⛔ PERVANE SÖKÜLÜ olsun. Arm ETME. Motor çalışmayacak.")
    print("  MAVLink: %s\n" % a.mav)

    m = mavutil.mavlink_connection(a.mav)
    if m.wait_heartbeat(timeout=15) is None:
        print("⛔ araç yok. Önce ./baslat_talon.sh çalışıyor olmalı.")
        return 2
    print("  ✔ araca bağlandı (sistem %d)" % m.target_system)

    # eşiği araçtan oku
    esik = 11.0
    m.mav.param_request_read_send(m.target_system, m.target_component,
                                  b"TKOFF_THR_MINACC", -1)
    t0 = time.time()
    while time.time() - t0 < 5.0:
        msg = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=1.0)
        if msg and msg.param_id.strip("\x00") == "TKOFF_THR_MINACC":
            esik = float(msg.param_value)
            break
    print("  ✔ TKOFF_THR_MINACC = %.1f m/s²  (aşman gereken eşik)" % esik)

    # ⛔ IVMEOLCER AKISI HIZLI OLMALI: yayıncı ham sensör akışını bant
    #   genişliği için 1 Hz'e kısıyor. 1 Hz'te bir atışın tepesi KAÇAR
    #   (atış ~0.1 s sürer). Test süresince yükseltiyoruz.
    for _ in range(3):
        m.mav.request_data_stream_send(m.target_system, m.target_component,
                                       M.MAV_DATA_STREAM_RAW_SENSORS, 50, 1)
        time.sleep(0.1)
    try:
        m.mav.command_long_send(
            m.target_system, m.target_component,
            M.MAV_CMD_SET_MESSAGE_INTERVAL, 0,
            M.MAVLINK_MSG_ID_RAW_IMU, 20000, 0, 0, 0, 0, 0)   # 50 Hz
    except Exception:
        pass
    print("  ✔ ivmeölçer akışı yükseltildi (57600 baud'un izin verdiği kadar)")
    print()
    print("  ⚠ ÖLÇÜM SINIRI — DÜRÜSTÇE: telsiz linki 57600 baud ve ivmeölçer")
    print("     bize ~15-25 Hz ulaşıyor. Bir atışın ivme TEPESİ ~0.1 s sürer,")
    print("     yani tepeye 1-3 örnek düşer ve GERÇEK TEPEYİ DÜŞÜK ölçebiliriz.")
    print("     ⭐ OTOPİLOT bunu 400 Hz'te görüyor — yani:")
    print("        bu araç 'ALGILANDI' diyorsa  -> otopilot KESİN algılar")
    print("        'algılanmadı' diyorsa        -> otopilot yine de algılamış")
    print("        olabilir. Yani bu test TEK YÖNLÜ kanıttır.\n")

    print("  " + "-" * 68)
    print("  ŞİMDİ: uçağı iki elinle tut, YATAY tutarak ATAR GİBİ İLERİ")
    print("  SAVUR — ama BIRAKMA. Birkaç kez dene, gittikçe sertleştir.")
    print("  Ctrl+C ile bitir.")
    print("  " + "-" * 68 + "\n")

    tepe = 0.0
    n_gecen = 0
    n_ornek = 0
    son_yazim = 0.0
    son_olay = 0.0
    t0 = time.time()
    try:
        while time.time() - t0 < a.sure:
            msg = m.recv_match(type=["RAW_IMU", "SCALED_IMU", "SCALED_IMU2"],
                               blocking=True, timeout=1.0)
            if msg is None:
                continue
            n_ornek += 1
            # mG -> m/s²
            ax = msg.xacc / 1000.0 * 9.80665
            simdi = time.time()
            if ax > tepe:
                tepe = ax
            # eşiği geçen bir "atış" olayı (0.7 s içinde tekrar sayma)
            if ax >= esik and (simdi - son_olay) > 0.7:
                son_olay = simdi
                n_gecen += 1
                print("\r  ⭐ ATIŞ ALGILANDI!  %.1f m/s²  (eşik %.1f)      "
                      % (ax, esik))
            if simdi - son_yazim > 0.15:
                son_yazim = simdi
                cubuk = int(min(40, max(0, ax / esik * 20)))
                print("\r  ileri ivme %6.1f m/s²  |%s%s| tepe %.1f  algılanan %d "
                      % (ax, "█" * cubuk, "·" * (40 - cubuk), tepe, n_gecen),
                      end="", flush=True)
    except KeyboardInterrupt:
        pass

    print("\n\n" + "=" * 72)
    print("  SONUÇ")
    print("=" * 72)
    hz = n_ornek / max(1.0, time.time() - t0)
    print("  örnek        : %d  (%.0f Hz)%s"
          % (n_ornek, hz,
             "   ⚠ DÜŞÜK — tepe olduğundan az ölçülmüş olabilir"
             if hz < 20 else ""))
    print("  EN YÜKSEK    : %.1f m/s²" % tepe)
    print("  eşik         : %.1f m/s²" % esik)
    print("  algılanan atış: %d" % n_gecen)
    print()
    if n_ornek < 20:
        print("  ⛔ YETERİNCE ÖRNEK GELMEDİ — araç bağlı mı, akış açık mı?")
        return 2
    if n_gecen == 0 and tepe < 1.0:
        print("  ⚠ UÇAK HİÇ HAREKET ETTİRİLMEMİŞ (tepe %.1f m/s²)." % tepe)
        print("     Testi tekrar çalıştır ve uçağı ATAR GİBİ savur.")
        return 0
    if n_gecen == 0:
        print("  ⛔⛔ HİÇBİR ATIŞ ALGILANMADI.")
        print("     Bu ayarla AUTO kalkışta MOTOR HİÇ ÇALIŞMAZ ve uçak")
        print("     elinden çıkıp süzülerek yere iner. İki seçenek:")
        print("       1) DAHA SERT AT — kolunu hızlandırarak, takip ederek")
        print("       2) Eşiği düşür:  kalkis_ayari.py --yaz TKOFF_THR_MINACC=%.0f"
              % max(8.0, tepe * 0.8))
        print("          ⚠ ÇOK DÜŞÜRME: elde taşırken tetiklenir ve pervane")
        print("            elinde döner. 8'in altına inme.")
    elif tepe < esik * 1.4:
        print("  ⚠ ALGILANDI AMA PAY AZ (tepe %.1f, eşik %.1f)." % (tepe, esik))
        print("     Sahada heyecanla ya da rüzgârda daha yumuşak atarsan")
        print("     kaçırabilirsin. Ya daha sert at ya eşiği %.0f'e indir."
              % max(8.0, tepe * 0.7))
    else:
        print("  ✔ ALGILAMA SAĞLAM: tepe eşiğin %.1f katı." % (tepe / esik))
        print("     Bu sertlikte atarsan motor çalışır.")
    print()
    print("  ⚠ BU TEST YALNIZ ALGILAMAYI ÖLÇER. Uçağın uçabilmesi için")
    print("     ayrıca YETERİ KADAR HIZLI atılması gerekir (≈14 m/s) —")
    print("     onu kalkis_ayari.py'nin [2b] bölümü hesaplıyor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
