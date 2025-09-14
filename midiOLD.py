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
