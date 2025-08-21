import os, time, pigpio

# ---- CONFIG (BCM numbers) ----
SER_PIN = 17  # 74HC595 SER (DS)
SRCLK = 27  # 74HC595 SH_CP
RCLK = 22  # 74HC595 ST_CP

OE_PIN = None  # set to GPIO number if /OE is wired to RPi (active low)
MR_PIN = None  # set to GPIO number if /MR is wired to RPi (active low)

NUM_BITS = 32  # 4×74HC595 = 32 bits
ACTIVE_LOW = False  # set True if LEDs are active-low (1=off, 0=on)

HOST = os.getenv("PIGPIO_HOST", None)
PORT = int(os.getenv("PIGPIO_PORT", "8888"))


def latch(pi):
    pi.write(RCLK, 0)
    time.sleep(5e-6)
    pi.write(RCLK, 1)
    time.sleep(5e-6)
    pi.write(RCLK, 0)
    time.sleep(5e-6)


def clock(pi):
    pi.write(SRCLK, 1)
    pi.write(SRCLK, 0)


def shift_constant(pi, bit, count):
    # push 'count' copies of 'bit' (bool) into the chain
    val = (
        0
        if (bit and ACTIVE_LOW)
        else (1 if (bit and not ACTIVE_LOW) else (1 if ACTIVE_LOW else 0))
    )
    for _ in range(count):
        pi.write(SER_PIN, val)
        clock(pi)


pi = pigpio.pi(HOST, PORT)
if not pi.connected:
    raise SystemExit(
        f"Cannot connect to pigpio daemon on {HOST or 'localhost'}:{PORT}. Run: sudo pigpiod"
    )

for pin in (SER_PIN, SRCLK, RCLK):
    pi.set_mode(pin, pigpio.OUTPUT)
    pi.write(pin, 0)

if OE_PIN is not None:
    pi.set_mode(OE_PIN, pigpio.OUTPUT)
    pi.write(OE_PIN, 0)  # enable outputs (active low)
if MR_PIN is not None:
    pi.set_mode(MR_PIN, pigpio.OUTPUT)
    pi.write(MR_PIN, 1)  # no reset (active low)

print("ALL-CLEAR test starting. Ctrl+C to stop.")
while True:
    # All OFF (depends on ACTIVE_LOW)
    print("-> all OFF")
    shift_constant(pi, False, NUM_BITS)
    latch(pi)
    time.sleep(1.0)

    # All ON
    print("-> all ON")
    shift_constant(pi, True, NUM_BITS)
    latch(pi)
    time.sleep(1.0)
