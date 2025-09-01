import time
import serial
import mido
from gpio import toggle_keyboard

# === KONFIG ===
MIDI_FILE = "/home/pi/utwor.mid"
SERIAL_DEV = "/dev/serial0"  # albo /dev/ttyAMA0 w zależności od RPi
BAUD = 31250

# mapowanie kanałów: stary -> nowy (0-15)
# tu zakładamy, że używasz trzech kanałów: 0,1,2
channel_map = {
    0: 0,  # kanał 1 -> 1
    1: 1,  # kanał 2 -> 2
    2: 2,  # kanał 3 -> 3
    # wszystkie inne możesz np. skomentować lub wskazać na któryś z powyższych
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


def MIDI():
    ser = serial.Serial(
        SERIAL_DEV,
        BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
    )
    mf = mido.MidiFile(MIDI_FILE)
    toggle_keyboard(True)
    start = time.monotonic()
    current = start

    for msg in mf:  # mido uwzględnia msg.time jako sekundowe opóźnienia
        # odczekaj czas między zdarzeniami
        if msg.time > 0:
            time.sleep(msg.time)

        # przemapuj kanał dla komunikatów kanałowych
        if hasattr(msg, "channel"):
            if msg.channel in channel_map:
                msg.channel = channel_map[msg.channel]
            else:
                # np. ignoruj inne kanały
                continue

        # zamień NoteOn vel=0 -> NoteOff (niekonieczne, ale schludne)
        if msg.type == "note_on" and msg.velocity == 0:
            msg.type = "note_off"

        # pomiń meta i SysEx (chyba że potrzebujesz)
        if msg.is_meta or msg.type == "sysex":
            continue

        raw = msg_to_bytes(msg)
        if raw:
            ser.write(raw)

    ser.close()
    toggle_keyboard(False)


if __name__ == "__main__":
    MIDI()
