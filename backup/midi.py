import time
import serial
import mido
from gpio import toggle_keyboard

# === KONFIG ===
MIDI_FILE = "/home/pi/utwor.mid"
SERIAL_DEV = "/dev/serial0"   # albo /dev/ttyAMA0 zaleznie od RPi
BAUD = 31250

# Mapowanie kanalow: stary -> nowy (0-15). Uzywamy trzech kanalow: 0,1,2
channel_map = {0: 0, 1: 1, 2: 2}

# --- WYBOR KOMUNIKATOW / TEMPERING RUCHU ---
ALLOW_TYPES = {"note_on", "note_off", "control_change", "program_change"}
ALLOW_CC = {64}                      # sustain
INCLUDE_PROGRAM_CHANGE = True

SPREAD_CHORD_US = 300                # rozsun rownoczesne zdarzenia o 300 us
MAX_MSG_PER_MS = 6                   # limit komunikatow na 1 ms
MIN_GAP_BETWEEN_MSG_US = 300         # minimalna przerwa miedzy komunikatami

WRITE_TIMEOUT_S = 0.05               # timeout na serial.write
WRITE_RETRY_SLEEP_S = 0.002          # pauza gdy bufor pelny
# --------------------------------------------


def msg_to_bytes(msg):
    """Zamienia mido.Message na surowe bajty MIDI (bez running status)."""
    if msg.type == "note_on":
        ch = msg.channel & 0x0F
        return bytes([0x90 | ch, msg.note & 0x7F, msg.velocity & 0x7F])
    if msg.type == "note_off":
        ch = msg.channel & 0x0F
        return bytes([0x80 | ch, msg.note & 0x7F, msg.velocity & 0x7F])
    if msg.type == "control_change":
        ch = msg.channel & 0x0F
        return bytes([0xB0 | ch, msg.control & 0x7F, msg.value & 0x7F])
    if msg.type == "program_change" and INCLUDE_PROGRAM_CHANGE:
        ch = msg.channel & 0x0F
        return bytes([0xC0 | ch, msg.program & 0x7F])
    return b""


def all_notes_off(ser):
    """Awaryjne wyciszenie: CC123 + NoteOff dla wszystkich nut i kanalow 0..2."""
    for ch in (0, 1, 2):
        try:
            ser.write(bytes([0xB0 | ch, 123, 0]))  # All Notes Off
            for n in range(128):
                ser.write(bytes([0x80 | ch, n & 0x7F, 64]))
        except Exception:
            pass


def load_events(midi_path):
    """
    Zwraca liste (t_us, bytes) z pliku MIDI:
    - filtruje tylko potrzebne typy,
    - remapuje kanaly,
    - zamienia NoteOn vel=0 -> NoteOff,
    - rozsuwa zdarzenia o tym samym czasie o SPREAD_CHORD_US.
    """
    mf = mido.MidiFile(midi_path)
    events = []
    t_acc = 0.0
    last_t_us = None
    bucket = []  # zdarzenia o tym samym czasie

    def flush_bucket():
        for i, (t_us, raw) in enumerate(bucket):
            events.append((t_us + i * SPREAD_CHORD_US, raw))
        bucket.clear()

    for msg in mf:
        t_acc += msg.time

        if msg.is_meta or msg.type == "sysex":
            continue
        if msg.type not in ALLOW_TYPES:
            continue
        if msg.type == "control_change" and msg.control not in ALLOW_CC:
            continue

        if hasattr(msg, "channel"):
            if msg.channel in channel_map:
                msg.channel = channel_map[msg.channel]
            else:
                continue

        if msg.type == "note_on" and msg.velocity == 0:
            msg = mido.Message("note_off", channel=msg.channel, note=msg.note, velocity=64, time=0)

        raw = msg_to_bytes(msg)
        if not raw:
            continue

        t_us = int(round(t_acc * 1_000_000))
        if last_t_us is None or t_us == last_t_us:
            bucket.append((t_us, raw))
            last_t_us = t_us
        else:
            flush_bucket()
            bucket.append((t_us, raw))
            last_t_us = t_us

    flush_bucket()
    events.sort(key=lambda x: x[0])
    return events


class UartPacer:
    """Limiter przeplywu + minimalny odstep miedzy komunikatami + retry write()."""
    def __init__(self, ser):
        self.ser = ser
        self.last_send_us = 0
        self.bucket_ts_ms = 0
        self.bucket_count = 0

    def _wait_min_gap(self):
        while True:
            now_us = time.perf_counter_ns() // 1000
            if now_us - self.last_send_us >= MIN_GAP_BETWEEN_MSG_US:
                self.last_send_us = now_us
                return
            time.sleep(0)

    def write_msg(self, b: bytes):
        now_ms = time.perf_counter_ns() // 1_000_000
        if now_ms != self.bucket_ts_ms:
            self.bucket_ts_ms = now_ms
            self.bucket_count = 0
        if self.bucket_count >= MAX_MSG_PER_MS:
            target = self.bucket_ts_ms + 1
            while (time.perf_counter_ns() // 1_000_000) < target:
                time.sleep(0)
            self.bucket_ts_ms = target
            self.bucket_count = 0

        self._wait_min_gap()

        i = 0
        while i < len(b):
            try:
                i += self.ser.write(b[i:])
            except serial.SerialTimeoutException:
                time.sleep(WRITE_RETRY_SLEEP_S)
        self.bucket_count += 1


def MIDI():
    ser = serial.Serial(
        SERIAL_DEV,
        BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0,
        write_timeout=WRITE_TIMEOUT_S,
    )

    toggle_keyboard(True)
    try:
        all_notes_off(ser)
        events = load_events(MIDI_FILE)
        pacer = UartPacer(ser)

        start_us = time.perf_counter_ns() // 1000
        idx = 0
        total = len(events)

        while idx < total:
            now_us = time.perf_counter_ns() // 1000
            t_evt_us, _ = events[idx]
            t_target = start_us + t_evt_us

            if now_us < t_target:
                if t_target - now_us > 1000:
                    time.sleep(0.0005)
                continue

            sent_any = False
            while idx < total:
                t_us, raw = events[idx]
                if start_us + t_us > (time.perf_counter_ns() // 1000):
                    break
                pacer.write_msg(raw)
                idx += 1
                sent_any = True

            if not sent_any:
                time.sleep(0)
    finally:
        all_notes_off(ser)
        ser.close()
        toggle_keyboard(False)


if __name__ == "__main__":
    MIDI()
