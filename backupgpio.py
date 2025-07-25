import pigpio
import serial
import time

# --- GPIO konfiguracja ---
SER_1 = 17
SER_MANUAL_ST = 23
SER_MANUAL_ND = 21
SER_PEDAL = 26
SRCLK = 27
RCLK = 22
ENC_CLK = 5
ENC_DT = 6

REG_MANUAL = 7
REG_PEDAL = 4

NUM_MANUAL_KEYS = REG_MANUAL * 8  # 56
NUM_PEDAL_KEYS = REG_PEDAL * 8  # 32


pi = pigpio.pi()
if not pi.connected:
    print("Nie można połączyć z pigpiod.")
    exit(1)

for pin in [SER_1, SER_MANUAL_ST, SER_MANUAL_ND, SER_PEDAL, SRCLK, RCLK]:
    pi.set_mode(pin, pigpio.OUTPUT)
    pi.write(pin, 0)

pi.set_mode(ENC_CLK, pigpio.INPUT)
pi.set_pull_up_down(ENC_CLK, pigpio.PUD_UP)
pi.set_mode(ENC_DT, pigpio.INPUT)
pi.set_pull_up_down(ENC_DT, pigpio.PUD_UP)

keys_manual_1 = [0] * NUM_MANUAL_KEYS
keys_manual_2 = [0] * NUM_MANUAL_KEYS
keys_pedal = [0] * NUM_PEDAL_KEYS

cords = {str(i): 0 for i in range(1, 33)}

position = 0
last_encoded = (pi.read(ENC_CLK) << 1) | pi.read(ENC_DT)


# --- Funkcje ---


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


def update_cords_manuals():
    combined = keys_manual_1 + keys_manual_2 + keys_pedal
    shift_out_manuals(combined)


def shift_out_manuals(manual_1, manual_2, pedal):
    # Debug
    print(f"shift_out_manuals: m1={len(manual_1)} m2={len(manual_2)} pd={len(pedal)}")
    ser_pins = [SER_MANUAL_ST, SER_MANUAL_ND, SER_PEDAL]

    m1 = list(reversed(manual_1))
    m2 = list(reversed(manual_2))
    pd = list(reversed(pedal))

    max_len = max(len(m1), len(m2), len(pd))

    for i in range(max_len):
        pi.write(ser_pins[0], m1[i] if i < len(m1) else 0)
        pi.write(ser_pins[1], m2[i] if i < len(m2) else 0)
        pi.write(ser_pins[2], pd[i] if i < len(pd) else 0)

        pi.write(SRCLK, 1)
        pi.write(SRCLK, 0)

    pi.write(RCLK, 1)
    pi.write(RCLK, 0)


def update_keys(status, note, velocity):
    channel = status & 0x0F
    msg_type = status & 0xF0

    is_on = 1 if msg_type == 0x90 and velocity > 0 else 0

    idx_manual = note - 36
    idx_pedal = note - 24

    if channel == 0 and 0 <= idx_manual < NUM_MANUAL_KEYS:
        keys_manual_1[idx_manual] = is_on
    elif channel == 1 and 0 <= idx_manual < NUM_MANUAL_KEYS:
        keys_manual_2[idx_manual] = is_on
    elif channel == 2 and 0 <= idx_pedal < NUM_PEDAL_KEYS:
        keys_pedal[idx_pedal] = is_on

    shift_out_manuals(keys_manual_1, keys_manual_2, keys_pedal)


def read_encoder(socket):
    global position, last_encoded
    MSB = pi.read(ENC_CLK)
    LSB = pi.read(ENC_DT)
    encoded = (MSB << 1) | LSB
    sum_ = (last_encoded << 2) | encoded

    if sum_ in [0b1101, 0b0100, 0b0010, 0b1011]:
        position += 1
    elif sum_ in [0b1110, 0b0111, 0b0001, 0b1000]:
        position -= 1

    last_encoded = encoded
    position = max(0, min(48, position))

    socket.emit("crescendo", {"cres": position})


def register_encoder_callbacks(socket):
    pi.callback(ENC_CLK, pigpio.EITHER_EDGE, lambda g, l, t: read_encoder(socket))
    pi.callback(ENC_DT, pigpio.EITHER_EDGE, lambda g, l, t: read_encoder(socket))


def run(socket):
    register_encoder_callbacks(socket)
    uart = serial.Serial("/dev/serial0", baudrate=31250, timeout=1)
    print("Oczekiwanie na dane MIDI oraz ruchy enkodera...")

    while True:
        try:
            data = uart.read(3)
            if len(data) == 3:
                status, note, velocity = data[0], data[1], data[2]
                print(f"MIDI: {hex(status)} Note: {note} Vel: {velocity}")
                if status & 0xF0 in [0x80, 0x90]:
                    update_keys(status, note, velocity)

        except Exception as e:
            print("Błąd UART:", e)
            time.sleep(0.1)
