#!/usr/bin/env python3
"""
OS Mini-Simulator (simple and sufficient)

Features:
- Paging with fixed-size frames
- Page faults, FIFO and LRU replacement (choose by CLI)
- Per-process stats: references, faults, resident frames, hit rate
- Producer-Consumer with semaphores + mutex
- Clear eviction logs and explicit deallocation for screenshots

Run examples:
  python3 os_minisim.py mem --frames 3 --algo FIFO
  python3 os_minisim.py mem --frames 4 --algo LRU --quiet
  python3 os_minisim.py mem --frames 3 --algo LRU --free-after 1
  python3 os_minisim.py pc --producers 2 --consumers 2 --bufsize 3 --items 4
"""

from collections import deque
from dataclasses import dataclass
import argparse
import threading
import time

# -------------------------
# Part 1: Memory Management
# -------------------------

@dataclass
class Frame:
    frame_id: int
    pid: int
    vpn: int
    load_time: int
    last_used: int

class Pager:
    """Small, clear pager with FIFO or LRU. Global replacement for simplicity."""
    def __init__(self, frames: int, algo: str = "LRU"):
        assert frames > 0
        assert algo in ("FIFO", "LRU")
        self.n = frames
        self.algo = algo
        self.frames = [None] * frames           # type: list[Frame|None]
        self.free = deque(range(frames))
        self.map = {}                           # (pid, vpn) -> frame_id
        self.t = 0                              # logical time
        self.total_refs = 0
        self.total_faults = 0
        self.stats = {}                         # pid -> dict

    def _ensure(self, pid: int):
        if pid not in self.stats:
            self.stats[pid] = {"refs": 0, "faults": 0, "resident": 0}

    def access(self, pid: int, vpn: int) -> bool:
        """Return True on hit, False on page fault."""
        self._ensure(pid)
        self.t += 1
        self.total_refs += 1
        self.stats[pid]["refs"] += 1

        key = (pid, vpn)
        if key in self.map:
            fr = self.frames[self.map[key]]
            fr.last_used = self.t
            return True

        # MISS -> page fault
        self.total_faults += 1
        self.stats[pid]["faults"] += 1

        if not self.free:
            self._evict_one()

        f = self.free.popleft()
        fr = Frame(f, pid, vpn, load_time=self.t, last_used=self.t)
        self.frames[f] = fr
        self.map[key] = f
        self.stats[pid]["resident"] += 1
        return False

    def _evict_one(self):
        victim_idx = None
        best = None
        for i, fr in enumerate(self.frames):
            if fr is None:
                continue
            metric = fr.load_time if self.algo == "FIFO" else fr.last_used
            if best is None or metric < best:
                best = metric
                victim_idx = i
        v = self.frames[victim_idx]
        # Visible eviction log (great for screenshots)
        print(f"[EVICT] algo={self.algo} frame={victim_idx} victim=PID {v.pid} VPN {v.vpn}")

        # Unmap victim
        self.map.pop((v.pid, v.vpn), None)
        # Update resident count
        self.stats[v.pid]["resident"] = max(0, self.stats[v.pid]["resident"] - 1)
        # Free the frame
        self.frames[victim_idx] = None
        self.free.append(victim_idx)

    def free_process(self, pid: int):
        """Deallocate all frames belonging to pid (simulate process exit)."""
        to_free = []
        for i, fr in enumerate(self.frames):
            if fr is not None and fr.pid == pid:
                to_free.append((i, fr.vpn))
        for frame_idx, vpn in to_free:
            self.frames[frame_idx] = None
            self.free.append(frame_idx)
            self.map.pop((pid, vpn), None)
            print(f"[FREE]  released frame={frame_idx} from PID {pid} VPN {vpn}")
        if pid in self.stats:
            self.stats[pid]["resident"] = 0

    def summary(self):
        per_proc = {}
        for pid, s in self.stats.items():
            refs = max(1, s["refs"])
            per_proc[pid] = {
                "references": s["refs"],
                "faults": s["faults"],
                "resident": s["resident"],
                "hit_rate": 1.0 - (s["faults"] / refs)
            }
        overall_hit = 0.0 if self.total_refs == 0 else 1.0 - (self.total_faults / self.total_refs)
        return {
            "algo": self.algo,
            "frames": self.n,
            "total_refs": self.total_refs,
            "total_faults": self.total_faults,
            "overall_hit_rate": overall_hit,
            "by_process": per_proc
        }

def run_round_robin(pager: Pager, traces: dict, verbose=True):
    iters = {pid: iter(v) for pid, v in traces.items()}
    active = set(traces.keys())
    order = sorted(active)
    while active:
        for pid in order:
            if pid not in active:
                continue
            it = iters[pid]
            try:
                vpn = next(it)
            except StopIteration:
                active.remove(pid)
                continue
            hit = pager.access(pid, vpn)
            if verbose:
                print(f"[{pager.algo}] PID {pid} -> VPN {vpn:>2} : {'HIT' if hit else 'MISS'}")

# --------------------------------
# Part 2: Producer–Consumer (simple)
# --------------------------------

class BoundedBuffer:
    """Semaphore-based bounded buffer with a mutex to avoid races."""
    def __init__(self, capacity: int):
        assert capacity > 0
        self.capacity = capacity
        self.q = deque()
        self.empty = threading.Semaphore(capacity)
        self.full = threading.Semaphore(0)
        self.mutex = threading.Lock()

    def put(self, item, pid=0):
        self.empty.acquire()
        with self.mutex:
            self.q.append(item)
            print(f"[PUT]  P{pid}: {item} (size={len(self.q)}/{self.capacity})")
        self.full.release()

    def get(self, cid=0):
        self.full.acquire()
        with self.mutex:
            item = self.q.popleft()
            print(f"[GET]  C{cid}: {item} (size={len(self.q)}/{self.capacity})")
        self.empty.release()
        return item

def run_pc(producers=1, consumers=1, bufsize=3, items=5):
    buf = BoundedBuffer(bufsize)
    STOP = ("STOP",)

    def prod(pid):
        for i in range(items):
            buf.put((pid, i), pid=pid)
            time.sleep(0.01)

    def cons(cid):
        while True:
            item = buf.get(cid=cid)
            if item == STOP:
                # pass along the stop token for other consumers
                buf.put(STOP, pid=-1)
                break
            time.sleep(0.01)

    threads = []
    for p in range(producers):
        t = threading.Thread(target=prod, args=(p,), daemon=True)
        t.start(); threads.append(t)
    for c in range(consumers):
        t = threading.Thread(target=cons, args=(c,), daemon=True)
        t.start(); threads.append(t)

    # Wait for producers then send stop tokens
    for t in threads[:producers]:
        t.join()
    for _ in range(consumers):
        buf.put(STOP, pid=-1)
    for t in threads[producers:]:
        t.join()

# -----------
# CLI
# -----------

def main():
    ap = argparse.ArgumentParser(description="Simple OS pager + producer-consumer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pm = sub.add_parser("mem", help="Run paging memory manager simulation")
    pm.add_argument("--frames", type=int, default=3, help="Number of physical frames")
    pm.add_argument("--algo", choices=["FIFO", "LRU"], default="LRU", help="Replacement policy")
    pm.add_argument("--quiet", action="store_true", help="Hide per-access output")
    pm.add_argument("--free-after", type=int, default=-1,
                    help="PID to deallocate after phase 1; -1 disables (useful for deallocation screenshot)")

    pc = sub.add_parser("pc", help="Run producer-consumer synchronization demo")
    pc.add_argument("--producers", type=int, default=1)
    pc.add_argument("--consumers", type=int, default=1)
    pc.add_argument("--bufsize", type=int, default=3)
    pc.add_argument("--items", type=int, default=5)

    args = ap.parse_args()

    if args.cmd == "mem":
        pager = Pager(frames=args.frames, algo=args.algo)

        # Small, illustrative traces (touching all features)
        traces = {
            1: [0,1,2,0,1,3,0,1,2,3],  # locality with occasional new page
            2: [0,2,4,0,2,4],          # stride pattern
        }

        # Phase 1
        run_round_robin(pager, traces, verbose=not args.quiet)

        # Optional deallocation for screenshots
        if args.free_after in traces:
            print(f"\n--- Deallocating PID {args.free_after} ---")
            pager.free_process(args.free_after)

            # Phase 2: short follow-up to show freed frames reused
            followup = {pid: [0,1,2] for pid in traces if pid != args.free_after}
            run_round_robin(pager, followup, verbose=not args.quiet)

        # Final stats
        s = pager.summary()
        print("\n=== STATS ===")
        print(f"Frames={s['frames']} Algo={s['algo']}")
        print(f"Total refs={s['total_refs']}  faults={s['total_faults']}  hit={s['overall_hit_rate']:.3f}")
        for pid in sorted(s["by_process"]):
            b = s["by_process"][pid]
            print(f"PID {pid}: refs={b['references']}, faults={b['faults']}, "
                  f"resident={b['resident']}, hit={b['hit_rate']:.3f}")

    elif args.cmd == "pc":
        run_pc(args.producers, args.consumers, args.bufsize, args.items)

if __name__ == "__main__":
    main()
