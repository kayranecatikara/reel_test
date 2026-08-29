"""Araçtaki BÜTÜN parametreleri okuyup zaman damgalı bir dosyaya yazar.

NEDEN AYRI BİR DÖKÜM: Mission Planner / MAVProxy gibi araçların yazdığı
mav.parm canlı bir anlık görüntüdür, her bağlanışta üzerine yazılır — kalıcı
kayıt değildir. Bu araç kendi bağlantısını açıp okuduğunu zaman damgalı ayrı
bir dosyaya yazar; dosya bir daha değişmez.

Ayrı component ID (197) kullanır ki arayüzün (192) trafiğine karışmasın.
"""
import sys, time
from pymavlink import mavutil

hedef = sys.argv[1]
m = mavutil.mavlink_connection("udp:127.0.0.1:14550", source_system=255,
                               source_component=197)
m.wait_heartbeat(timeout=25)
print(f"bağlandı — sistem {m.target_system}")

m.mav.param_request_list_send(m.target_system, m.target_component)
paramlar, toplam, son = {}, None, time.time()
while time.time() - son < 12:
    msg = m.recv_match(type="PARAM_VALUE", blocking=True, timeout=3)
    if msg is None:
        # Eksik varsa listeyi bir kez daha iste
        if toplam and len(paramlar) < toplam:
            m.mav.param_request_list_send(m.target_system, m.target_component)
            son = time.time()
            continue
        break
    ad = msg.param_id
    if isinstance(ad, bytes):
        ad = ad.decode(errors="ignore")
    paramlar[ad.rstrip("\x00")] = msg.param_value
    toplam = msg.param_count
    son = time.time()
    if len(paramlar) == toplam:
        break

print(f"okunan: {len(paramlar)} / {toplam}")
# encoding açıkça: Windows varsayılanı cp1254'tür, dosya orada bozuk yazılırdı.
with open(hedef, "w", encoding="utf-8") as f:
    for ad in sorted(paramlar):
        f.write(f"{ad:<20}{paramlar[ad]:.6f}\n")
print(f"yazıldı: {hedef}")
sys.exit(0 if toplam and len(paramlar) == toplam else 1)
