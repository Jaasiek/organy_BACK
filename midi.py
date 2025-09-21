import time
import serial
import threading
import mido
from gpio import disable_keyboard

# === KONFIG ===
SERIAL_DEV = "/dev/ttyAMA0"
# albo /dev/ttyAMA0 w zależności od RPi
BAUD = 31250

# mapowanie kanałów: stary -> nowy (0-15)
# tu zakładamy, że używasz trzech kanałów: 0,1,2
channel_map = {
    0: 0,  # kanał 1 -> 1
    1: 1,  # kanał 2 -> 2
    2: 2,  # kanał 3 -> 3
}


def compute_total_seconds(mid: mido.MidiFile) -> float:
    """
    Dokładne obliczenie długości MIDI w sekundach.
    Łączymy tracki (merge_tracks) i iterujemy po komunikatach w tickach,
    konwertując każdy delta-tick -> delta-sekundy z użyciem aktualnego tempa.
    """
    ticks_per_beat = mid.ticks_per_beat
    tempo = 500000  # domyślne tempo w mikrosekundach na beat
    total = 0.0

    # mido.merge_tracks zwraca iterator/track z komunikatami, z time w tickach
    for msg in mido.merge_tracks(mid.tracks):
        if msg.time:
            # przelicz delta-ticks na sekundy przy aktualnym tempie
            total += mido.tick2second(msg.time, ticks_per_beat, tempo)
        # jeśli napotkamy zmianę tempa — zaktualizujmy tempo dla kolejnych delta
        if msg.type == "set_tempo":
            tempo = msg.tempo

    return total


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
        self, file_path, serial_dev=SERIAL_DEV, baud=BAUD, channel_map=channel_map
    ):
        self.file_path = file_path
        self.serial_dev = serial_dev
        self.baud = baud
        self.channel_map = channel_map or {}
        self.mid = mido.MidiFile(file_path)

        # dokladne total seconds
        try:
            self.total_length = compute_total_seconds(self.mid)
        except Exception:
            try:
                self.total_length = float(self.mid.length)
            except Exception:
                self.total_length = None

        # thread / sync
        self._thread = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._lock = threading.Lock()

        # timing (monotonic-based)
        self._start_time = None  # moment startu odtwarzania (time.monotonic)
        self._paused_total = 0.0  # skumulowany czas pauzy (sekundy)
        self._pause_start = None  # moment rozpoczęcia obecnej pauzy (jeśli pauza)

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
            timeout=0,
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
            # write może być blokujące; jeśli testujemy bez portu można złapać wyjątki
            self._ser.write(raw)
        except Exception as e:
            print("Błąd wysyłki MIDI:", e)

    def _play_worker(self):
        """Wątek odtwarzający — nie liczymy w nim pozycji, tylko wysyłamy komunikaty."""
        self._stop_event.clear()
        self._pause_event.clear()

        # ustawienie start_time jeśli nie ustawiono (chroni przypadek restartu)
        with self._lock:
            if self._start_time is None:
                self._start_time = time.monotonic()
                self._paused_total = 0.0
                self._pause_start = None

        disable_keyboard(True)

        for msg in self.mid.play():
            if self._stop_event.is_set():
                break

            # implementacja pauzy: jeśli pauza, to czekamy tutaj dopóki nie wznowione
            wait = msg.time
            start_wait = time.monotonic()
            remaining = wait
            while remaining > 0:
                if self._stop_event.is_set():
                    break
                if self._pause_event.is_set():
                    # jeśli pauzujemy po raz pierwszy -> zapamiętaj moment pauzy
                    with self._lock:
                        if self._pause_start is None:
                            self._pause_start = time.monotonic()
                    # czekamy aż pauza się skończy
                    while self._pause_event.is_set() and not self._stop_event.is_set():
                        time.sleep(0.05)
                    # po wznowieniu zaktualizuj skumulowaną pauzę
                    with self._lock:
                        if self._pause_start is not None:
                            self._paused_total += time.monotonic() - self._pause_start
                            self._pause_start = None
                    # przesuwamy punkt start_wait zgodnie z czasem spędzonym w pauzie
                    start_wait = time.monotonic()
                    remaining = wait
                    continue
                # krótka pauza dla responsywności
                to_sleep = min(0.02, remaining)
                time.sleep(to_sleep)
                remaining = wait - (time.monotonic() - start_wait)

            if self._stop_event.is_set():
                break

            # mapowanie kanału (jak wcześniej)
            if hasattr(msg, "channel"):
                if msg.channel in self.channel_map:
                    msg.channel = self.channel_map[msg.channel]
                else:
                    # ignoruj inne kanały
                    continue

            # note_on vel=0 -> note_off
            if msg.type == "note_on" and getattr(msg, "velocity", 0) == 0:
                msg = mido.Message(
                    "note_off", note=msg.note, velocity=0, channel=msg.channel
                )

            if msg.is_meta or msg.type == "sysex":
                continue

            raw = msg_to_bytes(msg)
            if raw:
                self._send_raw(raw)

        # zakończenie odtwarzania
        self._close_serial()
        disable_keyboard(False)

        # opcjonalnie: oznacz, że odtwarzanie zakończone
        with self._lock:
            # ustawiamy start_time na None aby get_position zwracało 0 po stopie
            self._start_time = None
            self._paused_total = 0.0
            self._pause_start = None

    def play(self):
        # start odtwarzania od początku
        if self._thread and self._thread.is_alive():
            # jeśli już gra, nic nie robimy
            return

        # ustawianie czasów startu
        with self._lock:
            self._start_time = time.monotonic()
            self._paused_total = 0.0
            self._pause_start = None

        self._stop_event.clear()
        self._pause_event.clear()
        self._thread = threading.Thread(target=self._play_worker, daemon=True)
        self._thread.start()
        disable_keyboard(True)

    def pause(self):
        # zaznaczamy pauzę; worker zajmie się zapamiętaniem _pause_start
        self._pause_event.set()

    def resume(self):
        # wznowienie: worker dokona akumulacji pauzy przy następnym cyklu
        self._pause_event.clear()

    def stop(self):
        self._stop_event.set()
        # skasowanie pauzy
        self._pause_event.clear()
        if self._thread:
            self._thread.join(timeout=1.0)
        with self._lock:
            self._start_time = None
            self._paused_total = 0.0
            self._pause_start = None

    def get_position(self) -> float:
        """Zwraca przebieg w sekundach (float)."""
        with self._lock:
            if self._start_time is None:
                return 0.0
            if self._pause_event.is_set() and self._pause_start is not None:
                # jeśli aktualnie pauzujemy, pozycja to moment pauzy minus czas startu minus skumulowane poprzednie pauzy
                return max(
                    0.0, self._pause_start - self._start_time - self._paused_total
                )
            else:
                # zwykłe liczenie: bieżący monotonic - start - skumulowane pauzy
                elapsed = time.monotonic() - self._start_time - self._paused_total
                if self.total_length is not None:
                    return min(self.total_length, max(0.0, elapsed))
                return max(0.0, elapsed)

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
