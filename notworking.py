import pigpio
import serial
import time
import threading

# GPIO konfig
SER_MANUAL_1 = 23
SER_MANUAL_2 = 21
SER_PEDAL = 26
SER_DIVISIONS = 17
SRCLK = 27
RCLK = 22
ENC_CLK = 5
ENC_DT = 6

# Rozmiary rejestrów
NUM_MANUAL_KEYS = 56
NUM_PEDAL_KEYS = 30
NUM_DIVISIONS = 32

# Bufory
keys_manual_1 = [0] * NUM_MANUAL_KEYS
keys_manual_2 = [0] * NUM_MANUAL_KEYS
keys_pedal = [0] * NUM_PEDAL_KEYS
cords = [0] * NUM_DIVISIONS

# pigpio setup
pi = pigpio.pi()
if not pi.connected:
    print("Nie można połączyć z pigpiod.")
    exit(1)

for pin in [SER_MANUAL_1, SER_MANUAL_2, SER_PEDAL, SER_DIVISIONS, SRCLK, RCLK]:
    pi.set_mode(pin, pigpio.OUTPUT)
    pi.write(pin, 0)

pi.set_mode(ENC_CLK, pigpio.INPUT)
pi.set_pull_up_down(ENC_CLK, pigpio.PUD_UP)
pi.set_mode(ENC_DT, pigpio.INPUT)
pi.set_pull_up_down(ENC_DT, pigpio.PUD_UP)

# Encoder
position = 0
last_encoded = (pi.read(ENC_CLK) << 1) | pi.read(ENC_DT)
last_emitted_position = -1

# Lock + flaga aktualizacji
register_lock = threading.Lock()
pending_update = False


# === Funkcje ===


def shift_out_4_parallel(bits_m1, bits_m2, bits_pd, bits_div):
    """Przesyła dane do 4 łańcuchów z wspólnym zegarem"""
    # bits_m1 = list(reversed(bits_m1))
    # bits_m2 = list(reversed(bits_m2))
    # bits_pd = list(reversed(bits_pd))
    # bits_div = list(reversed(bits_div))
    max_len = max(len(bits_m1), len(bits_m2), len(bits_pd), len(bits_div))
    for i in range(max_len):
        pi.write(SER_MANUAL_1, bits_m1[i] if i < len(bits_m1) else 0)
        pi.write(SER_MANUAL_2, bits_m2[i] if i < len(bits_m2) else 0)
        pi.write(SER_PEDAL, bits_pd[i] if i < len(bits_pd) else 0)
        pi.write(SER_DIVISIONS, bits_div[i] if i < len(bits_div) else 0)

        pi.write(SRCLK, 1)
        pi.write(SRCLK, 0)

    pi.write(RCLK, 1)
    pi.write(RCLK, 0)


def update_all_registers():
    with register_lock:
        shift_out_4_parallel(keys_manual_1, keys_manual_2, keys_pedal, cords)


def register_update_loop():
    global pending_update
    while True:
        time.sleep(0.01)
        if pending_update:
            update_all_registers()
            pending_update = False


def schedule_register_update():
    global pending_update
    pending_update = True


def update_cords_divisions(selected_ids):
    global cords
    cords = [1 if i + 1 in selected_ids else 0 for i in range(NUM_DIVISIONS)]
    update_all_registers()


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

    update_all_registers()


def read_encoder(socket):
    global position, last_encoded, last_emitted_position
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

    if position != last_emitted_position:
        socket.emit("crescendo", {"cres": position})
        last_emitted_position = position


def register_encoder_callbacks(socket):
    pi.callback(ENC_CLK, pigpio.EITHER_EDGE, lambda g, l, t: read_encoder(socket))
    pi.callback(ENC_DT, pigpio.EITHER_EDGE, lambda g, l, t: read_encoder(socket))


def midi_scan():
    uart = serial.Serial("/dev/serial0", baudrate=31250, timeout=1)
    while True:
        try:
            data = uart.read(3)
            if len(data) == 3:
                status, note, velocity = data[0], data[1], data[2]
                if status & 0xF0 in [0x80, 0x90]:
                    update_keys(status, note, velocity)
        except Exception as e:
            print("Błąd UART:", e)
            time.sleep(0.1)


def run(socket):
    register_encoder_callbacks(socket)
    threading.Thread(target=register_update_loop, daemon=True).start()
    threading.Thread(target=midi_scan, daemon=True).start()
