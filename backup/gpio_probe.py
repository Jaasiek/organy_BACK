import os, time, pigpio

# ---- CONFIG (BCM numbers) ----
SER_PIN  = 17   # 74HC595 SER (DS)
SRCLK    = 27   # 74HC595 SH_CP
RCLK     = 22   # 74HC595 ST_CP

OE_PIN   = None # set to GPIO number if /OE is wired to RPi (active low)
MR_PIN   = None # set to GPIO number if /MR is wired to RPi (active low)

HOST = os.getenv("PIGPIO_HOST", None)
PORT = int(os.getenv("PIGPIO_PORT", "8888"))

pi = pigpio.pi(HOST, PORT)
if not pi.connected:
    raise SystemExit(f"Cannot connect to pigpio daemon on {HOST or 'localhost'}:{PORT}. Run: sudo pigpiod")

for pin in (SER_PIN, SRCLK, RCLK):
    pi.set_mode(pin, pigpio.OUTPUT)
    pi.write(pin, 0)

if OE_PIN is not None:
    pi.set_mode(OE_PIN, pigpio.OUTPUT)
    pi.write(OE_PIN, 0)  # enable outputs (active low)
if MR_PIN is not None:
    pi.set_mode(MR_PIN, pigpio.OUTPUT)
    pi.write(MR_PIN, 1)  # no reset (active low)

def pulse(pin, times=3, period=0.5):
    print(f"Pulsing GPIO{pin} {times}×")
    for _ in range(times):
        pi.write(pin, 1); time.sleep(period/2)
        pi.write(pin, 0); time.sleep(period/2)

def srclk_burst(n=100, us=500):
    # n pulses at us microseconds high + us microseconds low
    print(f"SRCLK burst: {n} pulses")
    for _ in range(n):
        pi.write(SRCLK, 1); time.sleep(us/1e6)
        pi.write(SRCLK, 0); time.sleep(us/1e6)

print("Setting SER=0, SRCLK=0, RCLK=0 ...")
pi.write(SER_PIN, 0)
pi.write(SRCLK, 0)
pi.write(RCLK, 0)
time.sleep(0.5)

print("SER -> 1 (steady for 2s)")
pi.write(SER_PIN, 1)
time.sleep(2.0)
print("SER -> 0")
pi.write(SER_PIN, 0)
time.sleep(0.5)

print("Pulsing RCLK (watch with meter/scope)")
pulse(RCLK, times=4, period=0.5)

print("SRCLK burst (watch with meter/scope)")
srclk_burst(200, us=200)

print("Done. If you saw no activity on the pins, check BCM numbering, wiring and pigpio host.")
