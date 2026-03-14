import os
import shlex
import subprocess
import threading
import time
import heapq
from collections import deque
from dataclasses import dataclass, field

# -----------------------------
# Simulated CPU Scheduler with RR & Priority + Metrics
# -----------------------------

@dataclass(order=False)
class SimProcess:
    spid: int
    name: str
    priority: int
    total_time: float
    remaining_time: float
    arrival_index: int
    status: str = field(default="Ready")   # Ready | Running | Finished | Terminated

    # Metrics timestamps (monotonic)
    arrival_ts: float = field(default=0.0)
    first_start_ts: float | None = field(default=None)
    finish_ts: float | None = field(default=None)

class Scheduler:
    """
    A preemptive priority and RR scheduler simulation with metrics.
    - Priority mode: Highest priority first (ties FCFS), immediate preemption.
    - RR mode: time-sliced round-robin with configurable quantum.
    Uses time.sleep() to simulate execution time.
    """

    def __init__(self, mode: str = "priority", quantum: float = 0.5, priority_tick: float = 0.05):
        self.mode = mode  # "priority" or "rr"
        self.quantum = float(quantum)
        self.priority_tick = float(priority_tick)  # small tick to react quickly to preemption in priority mode

        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)

        # Ready structures (one active at a time depending on mode)
        self._ready_deque = deque()  # for RR
        self._ready_heap = []        # for Priority, stores tuples: (-priority, arrival_index, spid)

        # Process table and metadata
        self._processes: dict[int, SimProcess] = {}  # spid -> SimProcess
        self._spid_counter = 1
        self._arrival_counter = 0

        self._running: SimProcess | None = None
        self._shutdown = False
        self._preempt_event = False

        # Event log for demo/traceability
        # each event: {"ts": float, "event": str, "spid": int|None, "detail": str}
        self._event_log: list[dict] = []

        self._thread = threading.Thread(target=self._schedule_loop, daemon=True)
        self._thread.start()

    # -------- Public API --------

    def add_process(self, name: str, duration: float, priority: int = 0) -> int:
        """Add a new simulated process."""
        with self._cond:
            now = time.monotonic()
            spid = self._spid_counter
            self._spid_counter += 1
            self._arrival_counter += 1
            p = SimProcess(
                spid=spid,
                name=name,
                priority=int(priority),
                total_time=float(duration),
                remaining_time=float(duration),
                arrival_index=self._arrival_counter,
                status="Ready",
                arrival_ts=now,
            )
            self._processes[spid] = p

            if self.mode == "priority":
                heapq.heappush(self._ready_heap, (-p.priority, p.arrival_index, p.spid))
                # Preempt if higher priority than the current running one
                if self._running is not None and p.priority > self._running.priority:
                    self._preempt_event = True
                    self._log("arrival", spid, f"prio={p.priority} (will preempt running SPID {self._running.spid})")
                else:
                    self._log("arrival", spid, f"prio={p.priority}")
            else:
                self._ready_deque.append(p.spid)
                self._log("arrival", spid, f"queued RR")

            self._cond.notify()
            return spid

    def list_processes(self):
        """Return a snapshot of all simulated processes."""
        with self._lock:
            return [
                {
                    "spid": sp.spid,
                    "name": sp.name,
                    "priority": sp.priority,
                    "total_time": sp.total_time,
                    "remaining_time": round(sp.remaining_time, 3),
                    "status": ("Running" if self._running and self._running.spid == sp.spid else sp.status)
                }
                for sp in sorted(self._processes.values(), key=lambda x: x.spid)
            ]

    def kill_process(self, spid: int) -> bool:
        """Terminate a simulated process."""
        with self._cond:
            sp = self._processes.get(spid)
            if not sp:
                return False

            sp.status = "Terminated"
            sp.finish_ts = sp.finish_ts or time.monotonic()

            if self.mode == "priority":
                # Lazy removal; marked terminated and skipped on pop
                pass
            else:
                try:
                    self._ready_deque.remove(spid)
                except ValueError:
                    pass

            # If running, force preemption
            if self._running and self._running.spid == spid:
                self._preempt_event = True

            self._log("terminated", spid, "killed by user")
            self._cond.notify()
            return True

    def set_mode(self, mode: str):
        """Switch between 'priority' and 'rr' at runtime."""
        mode = mode.lower()
        if mode not in ("priority", "rr"):
            raise ValueError("Mode must be 'priority' or 'rr'")

        with self._cond:
            if self.mode == mode:
                return

            if mode == "priority":
                # move all READY from deque to heap
                for spid in list(self._ready_deque):
                    sp = self._processes.get(spid)
                    if sp and sp.status == "Ready" and sp.remaining_time > 0:
                        heapq.heappush(self._ready_heap, (-sp.priority, sp.arrival_index, spid))
                self._ready_deque.clear()
            else:
                # move all READY from heap to deque
                while self._ready_heap:
                    _, _, spid = heapq.heappop(self._ready_heap)
                    sp = self._processes.get(spid)
                    if sp and sp.status == "Ready" and sp.remaining_time > 0:
                        self._ready_deque.append(spid)

            self.mode = mode
            self._preempt_event = True  # re-evaluate current running
            self._log("mode", None, f"switched to {mode}")
            self._cond.notify()

    def set_quantum(self, quantum: float):
        with self._lock:
            self.quantum = max(0.01, float(quantum))
            self._log("quantum", None, f"set to {self.quantum:.3f}s")

    def wait_all(self, include_terminated: bool = True, poll: float = 0.05):
        """Block until all processes are Finished or Terminated."""
        with self._cond:
            while True:
                unfinished = [
                    sp for sp in self._processes.values()
                    if (sp.status not in ("Finished", "Terminated")) and sp.remaining_time > 0
                ]
                if not unfinished and self._running is None:
                    return
                self._cond.wait(timeout=poll)

    def stats(self):
        """Return metrics per process and global averages (for Finished ones)."""
        with self._lock:
            rows = []
            finished = []

            for sp in sorted(self._processes.values(), key=lambda x: x.spid):
                A = sp.arrival_ts
                S = sp.first_start_ts
                F = sp.finish_ts
                B = sp.total_time

                def none_safe(x): return x if x is None else float(x)
                T = (none_safe(F) - A) if F is not None else None
                W = (T - B) if T is not None else None
                R = (none_safe(S) - A) if S is not None else None

                # clamp tiny negatives from floating error
                def clamp(x):
                    if x is None:
                        return None
                    return max(0.0, x)

                T = clamp(T); W = clamp(W); R = clamp(R)

                row = {
                    "spid": sp.spid, "name": sp.name, "prio": sp.priority,
                    "burst": B,
                    "arrival": A, "start": S, "finish": F,
                    "turnaround": T, "waiting": W, "response": R,
                    "status": sp.status
                }
                rows.append(row)
                if sp.status == "Finished" and T is not None:
                    finished.append(row)

            def avg(field):
                vals = [r[field] for r in finished if r[field] is not None]
                return sum(vals) / len(vals) if vals else None

            avgs = {
                "avg_turnaround": avg("turnaround"),
                "avg_waiting": avg("waiting"),
                "avg_response": avg("response"),
                "n_finished": len(finished),
            }
            return rows, avgs

    def events(self, last_n: int | None = None):
        with self._lock:
            if last_n is None or last_n <= 0:
                return list(self._event_log)
            return self._event_log[-last_n:]

    def shutdown(self):
        with self._cond:
            self._shutdown = True
            self._cond.notify_all()
        self._thread.join(timeout=2.0)

    # -------- Internal Helpers --------

    def _log(self, event: str, spid: int | None, detail: str = ""):
        self._event_log.append({
            "ts": time.monotonic(),
            "event": event,
            "spid": spid,
            "detail": detail
        })

    def _pop_next_priority(self) -> SimProcess | None:
        while self._ready_heap:
            _, _, spid = heapq.heappop(self._ready_heap)
            sp = self._processes.get(spid)
            if sp and sp.status == "Ready" and sp.remaining_time > 0:
                return sp
        return None

    def _pop_next_rr(self) -> SimProcess | None:
        while self._ready_deque:
            spid = self._ready_deque.popleft()
            sp = self._processes.get(spid)
            if sp and sp.status == "Ready" and sp.remaining_time > 0:
                return sp
        return None

    def _dispatch(self, sp: SimProcess):
        if sp.first_start_ts is None:
            sp.first_start_ts = time.monotonic()
        sp.status = "Running"
        self._running = sp
        self._log("dispatch", sp.spid, f"mode={self.mode}")

    def _finish(self, sp: SimProcess):
        sp.status = "Finished"
        sp.finish_ts = sp.finish_ts or time.monotonic()
        self._log("finish", sp.spid, "completed")

    def _schedule_loop(self):
        while True:
            with self._cond:
                if self._shutdown:
                    return

                # If no running process, get one
                if self._running is None:
                    nxt = self._pop_next_priority() if self.mode == "priority" else self._pop_next_rr()
                    if nxt:
                        self._dispatch(nxt)

                # If nothing ready, wait
                if self._running is None:
                    self._cond.wait(timeout=0.1)
                    continue

            # Execute one step based on mode
            if self.mode == "rr":
                self._run_rr_slice()
            else:
                self._run_priority_ticks()

    def _run_rr_slice(self):
        with self._lock:
            sp = self._running
            if not sp or sp.status in ("Terminated", "Finished"):
                self._running = None
                return
            time_slice = min(self.quantum, sp.remaining_time)

        # Simulate execution
        time.sleep(time_slice)

        with self._cond:
            sp = self._running
            if not sp:
                return

            # Accounting
            sp.remaining_time -= time_slice
            sp.remaining_time = max(0.0, sp.remaining_time)

            if sp.status == "Terminated":
                sp.finish_ts = sp.finish_ts or time.monotonic()
                self._log("drop", sp.spid, "terminated during slice")
                self._running = None
                return

            if sp.remaining_time <= 0.0:
                self._finish(sp)
                self._running = None
            else:
                # Time slice expired: requeue at tail
                sp.status = "Ready"
                self._running = None
                self._ready_deque.append(sp.spid)
                self._log("timeslice_expire", sp.spid, f"quantum={self.quantum:.3f}s")

            self._cond.notify()

    def _run_priority_ticks(self):
        tick = max(0.01, self.priority_tick)

        while True:
            with self._lock:
                sp = self._running
                if not sp or sp.status in ("Terminated", "Finished"):
                    self._running = None
                    return

                # If a higher-priority process arrived, preempt
                if self._preempt_event:
                    old = sp
                    old.status = "Ready"
                    heapq.heappush(self._ready_heap, (-old.priority, old.arrival_index, old.spid))
                    self._running = None
                    self._preempt_event = False

                    # Select new highest
                    new = self._pop_next_priority()
                    if new:
                        self._log("preempt", old.spid, f"by SPID {new.spid} (prio {new.priority} > {old.priority})")
                        self._dispatch(new)
                    continue

                if sp.remaining_time <= 0.0:
                    self._finish(sp)
                    self._running = None
                    return

                run_for = min(tick, sp.remaining_time)

            # Execute one small tick
            time.sleep(run_for)

            with self._cond:
                sp = self._running
                if not sp:
                    return

                sp.remaining_time -= run_for
                sp.remaining_time = max(0.0, sp.remaining_time)

                if sp.status == "Terminated":
                    sp.finish_ts = sp.finish_ts or time.monotonic()
                    self._log("drop", sp.spid, "terminated during tick")
                    self._running = None
                    return

                if sp.remaining_time <= 0.0:
                    self._finish(sp)
                    self._running = None
                    self._cond.notify()
                    return
                # else loop and continue running (unless preempted)

# -----------------------------
# Shell (original + scheduler + demos & metrics)
# -----------------------------

jobs = []
job_counter = 1
scheduler = Scheduler(mode="priority", quantum=0.5)  # default policy & quantum

def update_jobs():
    for job in jobs:
        if job["status"] == "Running":
            if job["process"].poll() is not None:
                job["status"] = "Finished"

def _fmt_time(x):
    return "—" if x is None else f"{x:.3f}s"

def main():
    global job_counter

    while True:
        try:
            update_jobs()
            command = input("myshell> ").strip()

            if not command:
                continue

            background = command.endswith("&")
            if background:
                command = command[:-1].strip()

            args = shlex.split(command)
            if not args:
                continue

            cmd = args[0]

            if cmd == "exit":
                print("Exiting shell...")
                scheduler.shutdown()
                break

            elif cmd == "pwd":
                print(os.getcwd())

            elif cmd == "cd":
                if len(args) < 2:
                    print("cd: missing directory")
                else:
                    try:
                        os.chdir(args[1])
                    except FileNotFoundError:
                        print("cd: directory not found")

            elif cmd == "echo":
                print(" ".join(args[1:]))

            elif cmd == "clear":
                os.system("cls" if os.name == "nt" else "clear")

            elif cmd == "ls":
                try:
                    for item in os.listdir():
                        print(item)
                except Exception as e:
                    print(f"ls: error: {e}")

            elif cmd == "cat":
                if len(args) < 2:
                    print("cat: missing filename")
                else:
                    try:
                        with open(args[1], "r", encoding="utf-8") as f:
                            print(f.read(), end="")
                    except FileNotFoundError:
                        print("cat: file not found")
                    except Exception as e:
                        print(f"cat: error: {e}")

            elif cmd == "mkdir":
                if len(args) < 2:
                    print("mkdir: missing directory name")
                else:
                    try:
                        os.mkdir(args[1])
                    except FileExistsError:
                        print("mkdir: directory already exists")
                    except Exception as e:
                        print(f"mkdir: error: {e}")

            elif cmd == "rmdir":
                if len(args) < 2:
                    print("rmdir: missing directory name")
                else:
                    try:
                        os.rmdir(args[1])
                    except FileNotFoundError:
                        print("rmdir: directory not found")
                    except OSError:
                        print("rmdir: directory not empty")
                    except Exception as e:
                        print(f"rmdir: error: {e}")

            elif cmd == "rm":
                if len(args) < 2:
                    print("rm: missing filename")
                else:
                    try:
                        os.remove(args[1])
                    except FileNotFoundError:
                        print("rm: file not found")
                    except Exception as e:
                        print(f"rm: error: {e}")

            elif cmd == "touch":
                if len(args) < 2:
                    print("touch: missing filename")
                else:
                    try:
                        with open(args[1], "a", encoding="utf-8"):
                            pass
                    except Exception as e:
                        print(f"touch: error: {e}")

            elif cmd == "jobs":
                update_jobs()
                if not jobs:
                    print("No jobs found")
                else:
                    for job in jobs:
                        print(f'[{job["job_id"]}] PID={job["pid"]} {job["status"]} - {job["command"]}')

            elif cmd == "kill":
                if len(args) < 2:
                    print("kill: missing pid")
                else:
                    try:
                        pid = int(args[1])
                        found = False
                        for job in jobs:
                            if job["pid"] == pid:
                                job["process"].terminate()
                                job["status"] = "Terminated"
                                print(f"Process {pid} terminated")
                                found = True
                                break
                        if not found:
                            print("kill: pid not found")
                    except ValueError:
                        print("kill: invalid pid")

            # -----------------------------
            # New scheduler commands
            # -----------------------------
            elif cmd == "addproc":
                # addproc <name> <duration_sec> [priority]
                if len(args) < 3:
                    print("Usage: addproc <name> <duration_sec> [priority]")
                else:
                    try:
                        name = args[1]
                        duration = float(args[2])
                        priority = int(args[3]) if len(args) >= 4 else 0
                        spid = scheduler.add_process(name, duration, priority)
                        print(f"Sim process created: SPID={spid} name='{name}' duration={duration}s priority={priority}")
                    except ValueError:
                        print("addproc: duration must be float and priority must be int (if provided)")

            elif cmd == "pjobs":
                plist = scheduler.list_processes()
                if not plist:
                    print("No simulated processes")
                else:
                    for p in plist:
                        print(
                            f"[SPID {p['spid']}] {p['status']:>9} | "
                            f"name={p['name']} | prio={p['priority']} | "
                            f"remaining={p['remaining_time']}/{p['total_time']}s"
                        )

            elif cmd == "pkill":
                if len(args) < 2:
                    print("Usage: pkill <spid>")
                else:
                    try:
                        spid = int(args[1])
                        ok = scheduler.kill_process(spid)
                        if ok:
                            print(f"Sim process {spid} terminated")
                        else:
                            print("pkill: spid not found")
                    except ValueError:
                        print("pkill: invalid spid")

            elif cmd == "setmode":
                if len(args) < 2:
                    print("Usage: setmode <priority|rr>")
                else:
                    try:
                        scheduler.set_mode(args[1])
                        print(f"Scheduler mode set to: {args[1]}")
                    except ValueError as e:
                        print(f"setmode: {e}")

            elif cmd == "setquantum":
                if len(args) < 2:
                    print("Usage: setquantum <seconds>")
                else:
                    try:
                        q = float(args[1])
                        scheduler.set_quantum(q)
                        print(f"RR quantum set to: {q}s")
                    except ValueError:
                        print("setquantum: invalid value")

            elif cmd == "pwait":
                scheduler.wait_all()
                print("All simulated processes finished or terminated.")

            elif cmd == "pstats":
                rows, avgs = scheduler.stats()
                if not rows:
                    print("No simulated processes")
                else:
                    print("SPID  Name    Prio  Burst   Turnaround  Waiting  Response  Status")
                    for r in rows:
                        print(f"{r['spid']:>4}  {r['name']:<6}  {r['prio']:>4}  "
                              f"{r['burst']:>5.2f}   "
                              f"{_fmt_time(r['turnaround']):>10}  {_fmt_time(r['waiting']):>7}  {_fmt_time(r['response']):>8}  {r['status']}")
                    print("\nAverages (Finished only):")
                    at = "—" if avgs['avg_turnaround'] is None else f"{avgs['avg_turnaround']:.3f}s"
                    aw = "—" if avgs['avg_waiting'] is None else f"{avgs['avg_waiting']:.3f}s"
                    ar = "—" if avgs['avg_response'] is None else f"{avgs['avg_response']:.3f}s"
                    print(f"- Count: {avgs['n_finished']}")
                    print(f"- Avg Turnaround: {at}")
                    print(f"- Avg Waiting:    {aw}")
                    print(f"- Avg Response:   {ar}")

            elif cmd == "plog":
                # plog [N]
                n = None
                if len(args) >= 2:
                    try:
                        n = int(args[1])
                    except ValueError:
                        print("plog: invalid N; showing all events")
                evs = scheduler.events(n)
                if not evs:
                    print("No events yet.")
                else:
                    base = evs[0]["ts"]
                    print("time(+s)   event               spid   detail")
                    for e in evs:
                        dt = e["ts"] - base
                        spid = "-" if e["spid"] is None else str(e["spid"])
                        print(f"{dt:8.3f}   {e['event']:<18} {spid:>4}   {e['detail']}")

            else:
                # external command execution (unchanged)
                try:
                    if background:
                        process = subprocess.Popen(args)
                        jobs.append({
                            "job_id": job_counter,
                            "pid": process.pid,
                            "command": command,
                            "status": "Running",
                            "process": process
                        })
                        print(f"[{job_counter}] {process.pid} running in background")
                        job_counter += 1
                    else:
                        process = subprocess.Popen(args)
                        process.wait()
                except FileNotFoundError:
                    print("Command not recognized")
                except Exception as e:
                    print(f"Command error: {e}")

        except KeyboardInterrupt:
            print("\nUse 'exit' to quit the shell.")
        except EOFError:
            print("\nExiting shell...")
            scheduler.shutdown()
            break

if __name__ == "__main__":
    main()
