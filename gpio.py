import pigpio
import serial
import time

# --- GPIO konfiguracja ---
SER_1 = 17
SRCLK = 27
RCLK = 22
ENC_CLK = 5
ENC_DT = 6

REG_MANUAL = 7
REG_PEDAL = 4


pi = pigpio.pi()
if not pi.connected:
    print("Nie można połączyć z pigpiod.")
    exit(1)

for pin in [SER_1, SRCLK, RCLK]:
    pi.set_mode(pin, pigpio.OUTPUT)
    pi.write(pin, 0)

pi.set_mode(ENC_CLK, pigpio.INPUT)
pi.set_pull_up_down(ENC_CLK, pigpio.PUD_UP)
pi.set_mode(ENC_DT, pigpio.INPUT)
pi.set_pull_up_down(ENC_DT, pigpio.PUD_UP)

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
    # uart = serial.Serial("/dev/serial0", baudrate=31250, timeout=1)
    print("Oczekiwanie na dane MIDI oraz ruchy enkodera...")
