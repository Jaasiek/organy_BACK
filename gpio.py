import pigpio
import serial
import time

# ======= WYJŚCIA 74HC595 (jak było) =======
SER_1 = 17
SRCLK = 27
RCLK = 22

# ======= ENKODER (jak było) =======
ENC_CLK = 5
ENC_DT = 6

REG_MANUAL = 7
REG_PEDAL = 4

# ======= WEJŚCIA 4x 74HC165 =======
PIN_165_PL = 19  # SH/LD (aktywny niski)
PIN_165_CP = 26  # CLK
PIN_165_Q7 = 13  # DATA z łańcucha do RPi
NUM_165 = 4  # liczba układów w łańcuchu
ACTIVE_LOW_165 = True  # jeśli wejścia zwierają do GND

POLL_INTERVAL_S = 0.01  # 10 ms (100 Hz)

pi = pigpio.pi()
if not pi.connected:
    print("Nie można połączyć z pigpiod.")
    exit(1)

# --- init 74HC595 ---
for pin in [SER_1, SRCLK, RCLK]:
    pi.set_mode(pin, pigpio.OUTPUT)
    pi.write(pin, 0)

# --- init enkodera ---
pi.set_mode(ENC_CLK, pigpio.INPUT)
pi.set_pull_up_down(ENC_CLK, pigpio.PUD_UP)
pi.set_mode(ENC_DT, pigpio.INPUT)
pi.set_pull_up_down(ENC_DT, pigpio.PUD_UP)

# --- init 74HC165 ---
pi.set_mode(PIN_165_PL, pigpio.OUTPUT)
pi.set_mode(PIN_165_CP, pigpio.OUTPUT)
pi.set_mode(PIN_165_Q7, pigpio.INPUT)
# delikatny pull-up na wejściu odczytu, żeby nie "pływało" gdy łańcuch nieaktywny
pi.set_pull_up_down(PIN_165_Q7, pigpio.PUD_UP)

# domyślne stany
pi.write(PIN_165_PL, 1)  # tryb przesuwania
pi.write(PIN_165_CP, 0)

cords = {str(i): 0 for i in range(1, 33)}

position = 0
last_encoded = (pi.read(ENC_CLK) << 1) | pi.read(ENC_DT)


# ======= 74HC595 =======
def shift_out(bit_list, pinout):
    for bit in reversed(bit_list):
        pi.write(pinout, bit)
        pi.write(SRCLK, 1)
        pi.write(SRCLK, 0)
    pi.write(RCLK, 1)
    pi.write(RCLK, 0)


def update_cords_divisions(selected_ids):
    for key in cords:
        cords[key] = 0
    for i in selected_ids:
        key = str(i)
        if key in cords:
            cords[key] = 1
    bit_list = [cords[key] for key in sorted(cords.keys(), key=lambda x: int(x))]
    shift_out(bit_list, SER_1)


# ======= 74HC165 =======
def read_165_bits(num_chips=NUM_165):
    total_bits = num_chips * 8
    # Załaduj równolegle wejścia do rejestru (aktywny niski)
    pi.write(PIN_165_PL, 0)
    # krótka pauza na pewność
    time.sleep(0.000001)
    pi.write(PIN_165_PL, 1)

    bits = []
    for _ in range(total_bits):
        # odczytaj aktualny Q7
        bit = pi.read(PIN_165_Q7)
        if ACTIVE_LOW_165:
            bit = 1 - bit
        bits.append(bit)
        # i przesuń dalej
        pi.write(PIN_165_CP, 1)
        pi.write(PIN_165_CP, 0)

    return bits  # lista 32 elementów 0/1


def bits_to_bytes(bits):
    """Pomocniczo: pakuje 8-bitowe kawałki do bajtów (MSB pierwszy w każdej ósemce)."""
    out = []
    for i in range(0, len(bits), 8):
        b = 0
        chunk = bits[i : i + 8]
        for j, val in enumerate(chunk):
            b |= (val & 1) << (7 - j)
        out.append(b)
    return out


# ======= ENKODER =======
def read_encoder(socket):
    global position, last_encoded
    MSB = pi.read(ENC_CLK)
    LSB = pi.read(ENC_DT)
    encoded = (MSB << 1) | LSB
    sum_ = (last_encoded << 2) | encoded

    if sum_ in [0b1101, 0b0100, 0b0010, 0b1011]:
        position += 1
    elif sum_ in [0b1110, 0b0111, 0b0001, 0b1011]:
        position -= 1

    # poprawka: prawidłowy kod
    if sum_ in [0b1110, 0b0111, 0b0001, 0b1000]:
        position -= 1

    last_encoded = encoded
    position = max(0, min(48, position))

    if socket:
        socket.emit("crescendo", {"cres": position})


def register_encoder_callbacks(socket):
    pi.callback(ENC_CLK, pigpio.EITHER_EDGE, lambda g, l, t: read_encoder(socket))
    pi.callback(ENC_DT, pigpio.EITHER_EDGE, lambda g, l, t: read_encoder(socket))


# ======= PĘTLA POLLUJĄCA 165 =======
_last_165 = None


def poll_165_once(socket, next_step, previoust_step):
    global _last_165
    bits = read_165_bits()
    if _last_165 is None:
        _last_165 = bits
        # pierwszy zrzut
        print("[74HC165] init:", bits)

    if bits != _last_165:
        pressed = [
            i
            for i, (prev, now) in enumerate(zip(_last_165, bits))
            if now == 1 and prev == 0
        ]
        if pressed:
            for i in pressed:
                match i:
                    case 0:
                        socket.emit("registers", {"number": 8})
                    case 1:
                        socket.emit("registers", {"number": 7})
                    case 2:
                        socket.emit("registers", {"number": 6})
                    case 3:
                        socket.emit("registers", {"number": 5})
                    case 4:
                        socket.emit("registers", {"number": 4})
                    case 5:
                        socket.emit("registers", {"number": 3})
                    case 6:
                        socket.emit("registers", {"number": 2})
                    case 7:
                        socket.emit("registers", {"number": 1})
                    case 8:
                        socket.emit("registers", {"number": 16})
                    case 9:
                        socket.emit("registers", {"number": 15})
                    case 10:
                        socket.emit("registers", {"number": 14})
                    case 11:
                        socket.emit("registers", {"number": 13})
                    case 12:
                        socket.emit("registers", {"number": 12})
                    case 13:
                        socket.emit("registers", {"number": 11})
                    case 14:
                        socket.emit("registers", {"number": 10})
                    case 15:
                        socket.emit("registers", {"number": 9})
                    case 16:
                        socket.emit("registers", {"number": 102})
                    case 17:
                        socket.emit("registers", {"number": 101})
                    case 18:
                        socket.emit("registers", {"number": 100})
                    case 19:
                        socket.emit("TUTTI")
                        print("TUTTI kurwy")
                    case 20:
                        print("czyszczenie KURWA MA BYĆ")
                        socket.emit("clear")
                    case 21:
                        previoust_step()
                        print("poprzedni")
                    case 22:
                        next_step()
                        print("następny")
                    case 23:
                        socket.emit("registers", {"number": 103})
                    case 24:
                        pass
                    case 25:
                        socket.emit("registers", {"number": 25})
                    case 26:
                        socket.emit("registers", {"number": 26})
                    case 27:
                        socket.emit("registers", {"number": 27})
                    case 28:
                        pass
                    case 29:
                        pass
                    case 30:
                        pass
                    case 31:
                        pass
                    case 32:
                        pass
            print(f"Kliknięto: {pressed}")

    _last_165 = bits


def run(socket, next_step, previoust_step):
    register_encoder_callbacks(socket)
    print("Oczekiwanie na dane MIDI oraz ruchy enkodera i rejestry 74HC165...")

    try:
        while True:
            poll_165_once(socket, next_step, previoust_step)
            time.sleep(POLL_INTERVAL_S)
    except KeyboardInterrupt:
        pass
