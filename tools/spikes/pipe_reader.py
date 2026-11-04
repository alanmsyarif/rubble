import subprocess, threading, time, os, statistics
N, PAY = 300, 3535872
here = os.path.dirname(os.path.abspath(__file__))
p = subprocess.Popen(["node", os.path.join(here, "pipe_writer.mjs")], stdout=subprocess.PIPE, bufsize=0)
ts = []
def rd():
    buf = bytearray(16 + PAY); mv = memoryview(buf)
    for _ in range(N):
        got = 0
        while got < len(buf):
            n = p.stdout.readinto(mv[got:])
            if not n: return
            got += n
        ts.append(time.perf_counter())
t0 = time.perf_counter()
th = threading.Thread(target=rd); th.start(); th.join(); p.wait()
d = [(b - a) * 1000 for a, b in zip([t0] + ts, ts)]
s = sorted(d)
print(f"messages={len(ts)} median_ms={statistics.median(d):.2f} p95_ms={s[int(len(s)*0.95)-1]:.2f} "
      f"MBps={len(ts)*(PAY+16)/1e6/(ts[-1]-t0):.0f}")
