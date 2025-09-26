import pigpio
import time

# ====================== KONFIGURACJA OGÓLNA ======================
# *** USTAW TO NA RZECZYWISTĄ LICZBĘ UKŁADÓW 74HC595 W ŁAŃCUCHU ***
NUM_595_CHIPS = 4              # <- ZMIEŃ (np. 24 dla 192 wyjść)
LED_SECTION_OFFSET = 0         # <- przesunięcie (w bitach) sekcji 32 LED względem początku łańcucha
                               #    0 oznacza początek. Jeśli Twoje 32 LED są w dalszej części długiego łańcucha,
                               #    ustaw tutaj właściwy offset (0..NUM_595_CHIPS*8-32).

ACTIVE_LOW_595 = False         # True jeśli diody/sterowanie są aktywne stanem niskim
SAFE_LATCH_US = 2e-6           # krótka pauza na ustalenie sygnałów przed zboczem RCLK

# ====================== PINY RPi (BCM) ======================
# 74HC595
SER_PIN  = 17   # dane
SRCLK    = 27   # zegar przesuwający (SH_CP)
RCLK     = 22   # latch (ST_CP) – próbkowanie wyjść na zboczu narastającym

# (opcjonalnie, jeżeli NIE są trwale podciągnięte sprzętowo)
OE_PIN   = None # /OE (aktywny niski): ustaw na numer GPIO, jeżeli chcesz sterować z RPi
MR_PIN   = None # /MR (aktywny niski): jw.

# 74HC165 (jeśli używasz)
PIN_165_PL = 19  # SH/LD (aktywny niski)
PIN_165_CP = 26  # CLK
PIN_165_Q7 = 13  # DATA z łańcucha do RPi
NUM_165 = 4
ACTIVE_LOW_165 = True

# ====================== INICJALIZACJA pigpio ======================
pi = pigpio.pi()
if not pi.connected:
    raise SystemExit("Nie można połączyć z pigpiod. Uruchom: sudo pigpiod")

# 595
for pin in (SER_PIN, SRCLK, RCLK):
    pi.set_mode(pin, pigpio.OUTPUT)
    pi.write(pin, 0)

if OE_PIN is not None:
    pi.set_mode(OE_PIN, pigpio.OUTPUT)
    pi.write(OE_PIN, 0)  # aktywuj wyjścia (OE=0)
if MR_PIN is not None:
    pi.set_mode(MR_PIN, pigpio.OUTPUT)
    pi.write(MR_PIN, 1)  # brak resetu (MR=1)

# 165
pi.set_mode(PIN_165_PL, pigpio.OUTPUT)
pi.set_mode(PIN_165_CP, pigpio.OUTPUT)
pi.set_mode(PIN_165_Q7, pigpio.INPUT)
pi.set_pull_up_down(PIN_165_Q7, pigpio.PUD_UP)
pi.write(PIN_165_PL, 1)
pi.write(PIN_165_CP, 0)

NUM_595_BITS = NUM_595_CHIPS * 8

# Bufor dla Twojej 32-bitowej sekcji (np. LED-y rejestrów)
cords = {str(i): 0 for i in range(1, 33)}


# ====================== NISKIE POZIOMY: 595 ======================
def _latch():
    # bezpieczne zbocze narastające RCLK z niewielką pauzą
    pi.write(RCLK, 0)
    time.sleep(SAFE_LATCH_US)
    pi.write(RCLK, 1)
    time.sleep(SAFE_LATCH_US)
    pi.write(RCLK, 0)

def _clock_sr():
    pi.write(SRCLK, 1)
    pi.write(SRCLK, 0)

def hard_clear_595():
    """Wypycha przez łańcuch same zera i zatrzaskuje. Powtórzone 2× dla pewności."""
    pi.write(SER_PIN, 0)
    for _ in range(NUM_595_BITS * 2):
        _clock_sr()
    _latch()

def _normalize_bit(v):
    b = 1 if v else 0
    return (0 if ACTIVE_LOW_595 else 1) if b else (1 if ACTIVE_LOW_595 else 0)

def shift_out_full(full_bits):
    """
    Wysyła DOKŁADNIE NUM_595_BITS do łańcucha 595.
    full_bits[0] -> pierwszy wysyłany bit -> wyląduje na NAJDALEJ położonym rejestrze.
    """
    if len(full_bits) != NUM_595_BITS:
        raise ValueError(f"full_bits musi mieć {NUM_595_BITS} bitów, a ma {len(full_bits)}")
    # 74HC595 próbuje dane na zboczu SRCLK; latch na zboczu narastającym RCLK
    for bit in reversed(full_bits):  # wysyłamy w odwrotnej kolejności (pierwszy element na końcu)
        pi.write(SER_PIN, _normalize_bit(bit))
        _clock_sr()
    _latch()

def shift_out_from_cords():
    """Buduje pełną ramkę NUM_595_BITS i wstrzykuje 32 bity 'cords' z przesunięciem."""
    # pusta ramka
    full = [0] * NUM_595_BITS
    # nasza sekcja 32b
    section = [cords[k] for k in sorted(cords.keys(), key=lambda x: int(x))]
    if LED_SECTION_OFFSET < 0 or LED_SECTION_OFFSET + 32 > NUM_595_BITS:
        raise ValueError("LED_SECTION_OFFSET poza zakresem dla zadanego NUM_595_CHIPS")
    # wstaw sekcję do ramki
    full[LED_SECTION_OFFSET:LED_SECTION_OFFSET + 32] = section
    shift_out_full(full)


# ====================== 165: ODCZYT ======================
def read_165_bits(num_chips=NUM_165):
    total_bits = num_chips * 8
    pi.write(PIN_165_PL, 0)
    time.sleep(1e-6)
    pi.write(PIN_165_PL, 1)

    bits = []
    for _ in range(total_bits):
        bit = pi.read(PIN_165_Q7)
        if ACTIVE_LOW_165:
            bit ^= 1
        bits.append(bit)
        pi.write(PIN_165_CP, 1)
        pi.write(PIN_165_CP, 0)
    return bits


# ====================== API WYSOKIEGO POZIOMU ======================
def clear_outputs():
    for k in cords:
        cords[k] = 0
    shift_out_from_cords()

def set_only(idx: int):
    for k in cords:
        cords[k] = 0
    if 1 <= idx <= 32:
        cords[str(idx)] = 1
    shift_out_from_cords()

def toggle(idx: int):
    if 1 <= idx <= 32:
        k = str(idx)
        cords[k] = 0 if cords[k] else 1
        shift_out_from_cords()

# ====================== TESTY SERWISOWE ======================
def test_walker(delay_s=0.2):
    """Przesuwa pojedynczą zapaloną LED po sekcji 32b (wcześniej twardy CLEAR całości)."""
    hard_clear_595()
    clear_outputs()
    for i in range(1, 33):
        set_only(i)
        time.sleep(delay_s)
    clear_outputs()

def test_fill_unfill(delay_s=0.05):
    """Najpierw dopełnia 32b do 1, potem gasi."""
    hard_clear_595()
    clear_outputs()
    # fill
    for i in range(1, 33):
        cords[str(i)] = 1
        shift_out_from_cords()
        time.sleep(delay_s)
    # unfill
    for i in range(32, 0, -1):
        cords[str(i)] = 0
        shift_out_from_cords()
        time.sleep(delay_s)
    clear_outputs()

def test_blink(times=5, delay_s=0.2):
    hard_clear_595()
    for _ in range(times):
        for v in (1, 0):
            for k in cords:
                cords[k] = v
            shift_out_from_cords()
            time.sleep(delay_s)
    clear_outputs()

if __name__ == "__main__":
    # Bezpieczny zestaw testów nie zostawiający przypadkowych śmieci w łańcuchu:
    print("[TEST] hard_clear_595...")
    hard_clear_595()
    print("[TEST] walker...")
    test_walker(0.1)
    print("[TEST] fill/unfill...")
    test_fill_unfill(0.02)
    print("[TEST] blink...")
    test_blink(3, 0.1)
    print("[TEST] OK")
