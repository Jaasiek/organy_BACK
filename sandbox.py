import pigpio
import time

# ======= WEJŚCIA 4x 74HC165 =======
PIN_165_PL = 19  # SH/LD (aktywny niski)
PIN_165_CP = 26  # CLK
PIN_165_Q7 = 13  # DATA z łańcucha do RPi
NUM_165 = 4  # liczba układów w łańcuchu
ACTIVE_LOW_165 = True  # jeśli wejścia zwierają do GND

pi = pigpio.pi()
if not pi.connected:
    print("Nie można połączyć z pigpiod.")
    exit(1)

# ustawienie pinów
pi.set_mode(PIN_165_PL, pigpio.OUTPUT)
pi.set_mode(PIN_165_CP, pigpio.OUTPUT)
pi.set_mode(PIN_165_Q7, pigpio.INPUT)
pi.set_pull_up_down(PIN_165_Q7, pigpio.PUD_UP)

pi.write(PIN_165_PL, 1)
pi.write(PIN_165_CP, 0)


def read_165_bits(num_chips=NUM_165):
    total_bits = num_chips * 8

    # załaduj równolegle dane z wejść
    pi.write(PIN_165_PL, 0)
    time.sleep(0.000001)
    pi.write(PIN_165_PL, 1)

    bits = []
    for _ in range(total_bits):
        bit = pi.read(PIN_165_Q7)
        if ACTIVE_LOW_165:
            bit = 1 - bit
        bits.append(bit)
        pi.write(PIN_165_CP, 1)
        pi.write(PIN_165_CP, 0)

    return bits


print("Start testu — naciskaj przyciski podpięte do 74HC165...")
last_bits = None

try:
    while True:
        bits = read_165_bits()

        print("Nowe dane:", bits)
        last_bits = bits
        time.sleep(0.05)  # 20 Hz odświeżania
except KeyboardInterrupt:
    print("Koniec testu")
    pi.stop()
