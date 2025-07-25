# zapal wszystkie nuty w manual_1, reszta zera
import pigpio
import time

# Nowy wspólny SER
SER = 17
SRCLK = 27
RCLK = 22
ENC_CLK = 5
ENC_DT = 6

# Liczba rejestrów
REG_MANUAL = 7
REG_PEDAL = 4

NUM_MANUAL_KEYS = REG_MANUAL * 8  # 56
NUM_PEDAL_KEYS = REG_PEDAL * 8  # 32
NUM_TOTAL_KEYS = NUM_MANUAL_KEYS + NUM_PEDAL_KEYS  # 88

pi = pigpio.pi()
if not pi.connected:
    print("Nie można połączyć z pigpiod.")
    exit(1)

# Ustawienie pinów
for pin in [SER, SRCLK, RCLK]:
    pi.set_mode(pin, pigpio.OUTPUT)
    pi.write(pin, 0)

pi.set_mode(ENC_CLK, pigpio.INPUT)
pi.set_pull_up_down(ENC_CLK, pigpio.PUD_UP)
pi.set_mode(ENC_DT, pigpio.INPUT)
pi.set_pull_up_down(ENC_DT, pigpio.PUD_UP)


def shift_out_all(*segments):
    """Przesyła dowolne segmenty bitów do łańcucha rejestrów"""
    all_bits = []
    for seg in segments:
        all_bits.extend(seg)

    if len(all_bits) != 88:
        raise ValueError(f"Oczekiwano 88 bitów, otrzymano {len(all_bits)}")

    bits = list(reversed(all_bits))  # Pierwszy bit na końcu rejestru

    for bit in bits:
        pi.write(SER, bit)
        pi.write(SRCLK, 1)
        pi.write(SRCLK, 0)

    pi.write(RCLK, 1)
    pi.write(RCLK, 0)


def reset():
    keys_manual_1 = [0] * NUM_MANUAL_KEYS
    keys_pedal = [0] * NUM_PEDAL_KEYS
    all_keys = keys_manual_1 + keys_pedal
    shift_out_all(all_keys)


while True:
    # zapalamy tylko manual_1, reszta zera
    keys_manual_1 = [1] * NUM_MANUAL_KEYS
    keys_pedal = [0] * NUM_PEDAL_KEYS
    all_keys = keys_manual_1 + keys_pedal
    reset()
    print("OFF")
    time.sleep(2)

    shift_out_all(all_keys)
    print("ON")
    time.sleep(2)
