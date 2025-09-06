import time
import serial
import threading
import mido
from gpio import disable_keyboard

# === KONFIG ===
SERIAL_DEV = "/dev/serial0"  # albo /dev/ttyAMA0 w zależności od RPi
BAUD = 31250

# mapowanie kanałów: stary -> nowy (0-15)
# tu zakładamy, że używasz trzech kanałów: 0,1,2
channel_map = {
    0: 0,  # kanał 1 -> 1
    1: 1,  # kanał 2 -> 2
    2: 2,  # kanał 3 -> 3
}


def msg_to_bytes(msg):
    """Zamień mido.Message na surowe bajty MIDI (bez running status)."""
    status = None
    data = []

    if msg.type in (
        "note_on",
        "note_off",
        "control_change",
        "program_change",
        "pitchwheel",
        "aftertouch",
        "polytouch",
    ):
        ch = msg.channel & 0x0F
        if msg.type == "note_on":
            status = 0x90 | ch
            note = msg.note & 0x7F
            vel = msg.velocity & 0x7F
            data = [note, vel]
        elif msg.type == "note_off":
            status = 0x80 | ch
            note = msg.note & 0x7F
            vel = msg.velocity & 0x7F
            data = [note, vel]
        elif msg.type == "control_change":
            status = 0xB0 | ch
            data = [msg.control & 0x7F, msg.value & 0x7F]
        elif msg.type == "program_change":
            status = 0xC0 | ch
            data = [msg.program & 0x7F]
        elif msg.type == "pitchwheel":
            status = 0xE0 | ch
            v = msg.pitch + 8192  # 0..16383
            data = [v & 0x7F, (v >> 7) & 0x7F]
        elif msg.type == "aftertouch":
            status = 0xD0 | ch
            data = [msg.value & 0x7F]
        elif msg.type == "polytouch":
            status = 0xA0 | ch
            data = [msg.note & 0x7F, msg.value & 0x7F]

    if status is None:
        return b""

    return bytes([status] + data)


class MidiPlayer:
    def __init__(
        self, file_path, serial_dev="/dev/serial0", baud=31250, channel_map=channel_map
    ):
        self.file_path = file_path
        self.serial_dev = serial_dev
        self.baud = baud
        self.channel_map = channel_map or {}
        self.mid = mido.MidiFile(file_path)
        # total length (seconds) — mido provides .length dla type 0/1 plików
        try:
            self.total_length = self.mid.length
        except Exception:
            # alternatywnie można policzyć manualnie albo użyć pretty_midi
            self.total_length = None

        self._thread = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()  # when set -> paused
        self._lock = threading.Lock()
        self._elapsed = 0.0  # elapsed seconds of playback
        self._ser = None

    def _open_serial(self):
        if self._ser and self._ser.is_open:
            return
        self._ser = serial.Serial(
            self.serial_dev,
            self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
        )

    def _close_serial(self):
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass
            self._ser = None

    def _send_raw(self, raw: bytes):
        if not raw:
            return
        try:
            self._open_serial()
            self._ser.write(raw)
        except Exception as e:
            print("Błąd wysyłki MIDI:", e)

    def _play_worker(self):
        # worker który iteruje przez wiadomości z czasem (seconds)
        self._stop_event.clear()
        self._pause_event.clear()
        self._elapsed = 0.0
        last_time = time.monotonic()

        disable_keyboard(True)
        # mido.MidiFile.play() yields messages with .time == seconds since last message
        for msg in self.mid.play():
            if self._stop_event.is_set():
                break

            # jeśli pauza aktywna -> czekaj (przy utrzymaniu poprawnego czasu)
            wait = msg.time
            start_wait = time.monotonic()
            remaining = wait
            while remaining > 0:
                if self._stop_event.is_set():
                    break
                if self._pause_event.is_set():
                    # w pauzie — czekamy do wznowienia i przesuwamy punkt startu
                    pause_start = time.monotonic()
                    while self._pause_event.is_set() and not self._stop_event.is_set():
                        time.sleep(0.05)
                    # po wznowieniu: policz ile byliśmy zatrzymani i przesuwamy czas oczekiwania
                    paused_for = time.monotonic() - pause_start
                    start_wait += paused_for
                    remaining = wait - (time.monotonic() - start_wait)
                    continue
                # niepauzujemy, krótkie sleepy by być responsywnym
                to_sleep = min(0.02, remaining)
                time.sleep(to_sleep)
                remaining = wait - (time.monotonic() - start_wait)

            if self._stop_event.is_set():
                break

            # przemapuj kanał jeśli trzeba
            if hasattr(msg, "channel"):
                if msg.channel in self.channel_map:
                    msg.channel = self.channel_map[msg.channel]
                else:
                    # ignoruj inne kanały (jak w Twoim przykładzie)
                    continue

            # note_on vel=0 -> note_off (porządkujące)
            if msg.type == "note_on" and getattr(msg, "velocity", 0) == 0:
                msg.type = "note_off"

            if msg.is_meta or msg.type == "sysex":
                # pomiń meta i sysex, chyba że chcesz je wysyłać
                continue

            raw = msg_to_bytes(msg)
            if raw:
                self._send_raw(raw)

            # zaktualizuj elapsed (safe)
            with self._lock:
                self._elapsed += msg.time

        # zakończenie
        self._close_serial()
        disable_keyboard(False)

    def play(self):
        if self._thread and self._thread.is_alive():
            # już gramy — restartuj od początku jeśli chcesz
            return
        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = threading.Thread(target=self._play_worker, daemon=True)
        self._thread.start()
        disable_keyboard(True)

    def pause(self):
        self._pause_event.set()

    def resume(self):
        self._pause_event.clear()

    def stop(self):
        self._stop_event.set()
        self._pause_event.clear()
        if self._thread:
            self._thread.join(timeout=1.0)
        # reset elapsed
        with self._lock:
            self._elapsed = 0.0

    def get_position(self):
        with self._lock:
            return self._elapsed

    def get_total(self):
        return self.total_length

    def is_playing(self):
        return (
            self._thread is not None
            and self._thread.is_alive()
            and not self._pause_event.is_set()
        )

    def is_paused(self):
        return self._pause_event.is_set()


# def MIDI(file_path):
#     ser = serial.Serial(
#         SERIAL_DEV,
#         BAUD,
#         bytesize=serial.EIGHTBITS,
#         parity=serial.PARITY_NONE,
#         stopbits=serial.STOPBITS_ONE,
#     )
#     mf = mido.MidiFile(file_path)
#     toggle_keyboard(True)
#     start = time.monotonic()
#     current = start

#     for msg in mf:  # mido uwzględnia msg.time jako sekundowe opóźnienia
#         # odczekaj czas między zdarzeniami
#         if msg.time > 0:
#             time.sleep(msg.time)

#         # przemapuj kanał dla komunikatów kanałowych
#         if hasattr(msg, "channel"):
#             if msg.channel in channel_map:
#                 msg.channel = channel_map[msg.channel]
#             else:
#                 # np. ignoruj inne kanały
#                 continue

#         # zamień NoteOn vel=0 -> NoteOff (niekonieczne, ale schludne)
#         if msg.type == "note_on" and msg.velocity == 0:
#             msg.type = "note_off"

#         # pomiń meta i SysEx (chyba że potrzebujesz)
#         if msg.is_meta or msg.type == "sysex":
#             continue

#         raw = msg_to_bytes(msg)
#         if raw:
#             ser.write(raw)

#     ser.close()
#     toggle_keyboard(False)
