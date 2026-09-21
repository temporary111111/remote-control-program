import pyaudiowpatch as pyaudio
import numpy as np
import time

p = pyaudio.PyAudio()
w = p.get_host_api_info_by_type(pyaudio.paWASAPI)
default = p.get_device_info_by_index(w['defaultOutputDevice'])

print("Default output:", default["name"])
print()

loopback = None
for i in range(p.get_device_count()):
    d = p.get_device_info_by_index(i)
    if d.get("isLoopbackDevice"):
        print("Loopback [%d]: %s (in=%d, rate=%d)" % (i, d["name"], d["maxInputChannels"], d["defaultSampleRate"]))
        if d["name"] == default["name"]:
            loopback = d
            print("  ^ EXACT MATCH")
        elif default["name"] in d["name"] or d["name"] in default["name"]:
            if not loopback:
                loopback = d
                print("  ^ PARTIAL MATCH (using this)")

if not loopback:
    print()
    print("No matching loopback device! Trying first loopback device...")
    for i in range(p.get_device_count()):
        d = p.get_device_info_by_index(i)
        if d.get("isLoopbackDevice") and d["maxInputChannels"] > 0:
            loopback = d
            print("Using: [%d] %s" % (i, d["name"]))
            break

if not loopback:
    print("ERROR: No loopback device found at all!")
    p.terminate()
    exit(1)

print()
print("PLAY YOUTUBE NOW! Capturing for 10 seconds...")
print()

stream = p.open(
    format=pyaudio.paFloat32,
    channels=2,
    rate=48000,
    input=True,
    input_device_index=loopback["index"],
    frames_per_buffer=1024,
)

rms_values = []
for i in range(47):
    data = np.frombuffer(stream.read(1024), dtype=np.float32)
    rms = float(np.sqrt(np.mean(data ** 2)))
    peak = float(np.max(np.abs(data)))
    rms_values.append(rms)
    if rms > 0.001:
        print("  [%d] rms=%.6f peak=%.6f *** AUDIO DETECTED ***" % (i, rms, peak))
    elif i % 10 == 0:
        print("  [%d] rms=%.6f peak=%.6f" % (i, rms, peak))
    time.sleep(0.02)

stream.stop_stream()
stream.close()
p.terminate()

print()
avg = float(np.mean(rms_values))
mx = float(np.max(rms_values))
above = sum(1 for r in rms_values if r > 0.001)
print("Average RMS: %.6f" % avg)
print("Max RMS: %.6f" % mx)
print("Frames with audio: %d/%d" % (above, len(rms_values)))
if mx > 0.001:
    print("RESULT: WASAPI loopback is WORKING!")
else:
    print("RESULT: NO AUDIO detected. Check YouTube is playing and volume is up.")
