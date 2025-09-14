import pigpio
import serial
import time
import os

# ======= WYJŚCIA 74HC595 (jak było) =======
SER_1 = 17
SRCLK = 27
RCLK = 22

# ======= ENKODER (jak było) =======
ENC_CLK = 5
ENC_DT = 6
POWER_OFF = 4

REG_MANUAL = 7
P_I = 16
P_II = 20
I_II = 21
MIDI = 12

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
pi.set_mode(POWER_OFF, pigpio.INPUT)
pi.set_pull_up_down(POWER_OFF, pigpio.PUD_UP)

# --- init 74HC165 ---
pi.set_mode(PIN_165_PL, pigpio.OUTPUT)
pi.set_mode(PIN_165_CP, pigpio.OUTPUT)
pi.set_mode(I_II, pigpio.OUTPUT)
pi.set_mode(P_II, pigpio.OUTPUT)
pi.set_mode(P_I, pigpio.OUTPUT)
pi.set_mode(MIDI, pigpio.OUTPUT)
pi.set_mode(PIN_165_Q7, pigpio.INPUT)
# delikatny pull-up na wejściu odczytu, żeby nie "pływało" gdy łańcuch nieaktywny
pi.set_pull_up_down(PIN_165_Q7, pigpio.PUD_UP)

# domyślne stany
pi.write(PIN_165_PL, 1)  # tryb przesuwania
pi.write(PIN_165_CP, 0)

cords = {str(i): 0 for i in range(1, 33)}


position = 0
last_encoded = (pi.read(ENC_CLK) << 1) | pi.read(ENC_DT)


_last_power_off_time = 0
DEBOUNCE_TIME_S = 1.0


def power_off_callback(level, socket):
    global _last_power_off_time
    now = time.time()
    if level == 0 and (now - _last_power_off_time) > DEBOUNCE_TIME_S:
        _last_power_off_time = now
        socket.emit("shutdown")
        time.sleep(1)
        os.system("sudo shutdown now")


copel_states = {
    100: 0,
    101: 0,
    102: 0,
}


def disable_keyboard(state):
    pi.write(MIDI, 0 if state == True else 1)


def apply_copel(type: int):
    if type == 100:
        pi.write(P_I, copel_states[100])
    elif type == 101:
        pi.write(P_II, copel_states[101])
    elif type == 102:
        pi.write(I_II, copel_states[102])


def copels(type: int):
    # toggle – tylko zmiana w słowniku
    copel_states[type] ^= 1
    apply_copel(type)
    print(f"copels({type}) -> {copel_states[type]}")


def set_copel(type: int, state: bool):
    # ustawienie na sztywno
    copel_states[type] = 1 if state else 0
    apply_copel(type)
    print(f"set_copel({type}, {state}) -> {copel_states[type]}")


def output_all_one(state: bool):
    for k in cords:
        cords[k] = 0 if state == False else 1
        if k == "17":
            cords[k] = 0
    shift_out_from_cords()
    set_copel(100, state)
    set_copel(101, state)
    set_copel(102, state)


# ======= 74HC595 =======
def shift_out(bit_list, pinout):
    # pierwszy bit na liście -> pierwszy wysłany -> trafia na ostatni rejestr
    # dlatego trzeba odwrócić
    for bit in reversed(bit_list):
        pi.write(pinout, bit)
        pi.write(SRCLK, 1)
        pi.write(SRCLK, 0)
    pi.write(RCLK, 1)
    pi.write(RCLK, 0)


def shift_out_from_cords():
    # bierzemy 1..32 w kolejności rosnącej
    bit_list = [cords[k] for k in sorted(cords.keys(), key=lambda x: int(x))]
    shift_out(bit_list, SER_1)


def update_cords_divisions(selected_ids):
    for key in cords:
        cords[key] = 0
    for i in selected_ids:
        key = str(i)
        if key in cords:
            cords[key] = 1
    bit_list = [cords[key] for key in sorted(cords.keys(), key=lambda x: int(x))]
    shift_out_from_cords()


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
    global _last_165, cords
    bits = read_165_bits()
    if _last_165 is None:
        _last_165 = bits

    if bits != _last_165:
        pressed = [
            i
            for i, (prev, now) in enumerate(zip(_last_165, bits))
            if now == 1 and prev == 0
        ]
        if pressed:
            for i in pressed:
                # Mapowanie wejść -> rejestry
                number = None
                match i:
                    case 0:
                        number = 8
                    case 1:
                        number = 7
                    case 2:
                        number = 6
                    case 3:
                        number = 5
                    case 4:
                        number = 4
                    case 5:
                        number = 3
                    case 6:
                        number = 2
                    case 7:
                        number = 1
                    case 8:
                        number = 16
                    case 9:
                        number = 15
                    case 10:
                        number = 14
                    case 11:
                        number = 13
                    case 12:
                        number = 12
                    case 13:
                        number = 11
                    case 14:
                        number = 10
                    case 15:
                        number = 9
                    case 16:
                        number = 102
                        copels(102)
                    case 17:
                        number = 101
                        copels(101)
                    case 18:
                        number = 100
                        copels(100)
                    case 19:
                        socket.emit("TUTTI")
                        output_all_one(True)
                    case 20:
                        socket.emit("clear")
                        output_all_one(False)
                    case 21:
                        previoust_step()
                        print("poprzedni")
                    case 22:
                        next_step()
                        print("następny")
                    case 23:
                        number = 17
                    case 25:
                        number = 25
                    case 26:
                        number = 26
                    case 27:
                        number = 27

                # Jeśli jest numer rejestru → ustaw w cords i wyślij
                if number is not None:
                    if 1 <= number <= 32:
                        key = str(number)
                        cords[key] = 1 - cords[key]  # toggle bitu
                        shift_out_from_cords()
                        socket.emit("registers", {"number": number})
                    else:
                        # Funkcje pomocnicze, nie sterują wyjściami
                        socket.emit("registers", {"number": number})

            print(f"Kliknięto: {pressed}")

    _last_165 = bits


def run(socket, next_step, previoust_step):
    register_encoder_callbacks(socket)
    output_all_one(False)
    pi.callback(
        POWER_OFF,
        pigpio.FALLING_EDGE,
        lambda g, l, t: power_off_callback(l, socket),
    )

    try:
        while True:
            poll_165_once(socket, next_step, previoust_step)
            time.sleep(POLL_INTERVAL_S)
    except KeyboardInterrupt:
        pass
