#!/usr/bin/env python3
"""
OS Mini-Shell — Final Integrated Deliverable
=============================================
Combines all previous deliverables into one cohesive shell:

  Deliverable 1 (osh_2.py)       — Core shell: built-ins, background jobs, fg/bg/kill
  Deliverable 2 (shell_deliverable4.py) — Auth, permissions, pipelines, user management
  Deliverable 3 (scheduler.py)   — Process scheduling: Round-Robin & Priority
  Deliverable 4 (os_minisim.py)  — Memory management (paging, FIFO/LRU) & Producer-Consumer

New shell commands
------------------
  scheduler rr               Run Round-Robin scheduling demo
  scheduler priority         Run Priority scheduling demo
  scheduler all              Run both scheduling demos

--
mem --frames 3 --algo LRU --free-after 1
mem --frames 3 --algo FIFO
mem --frames 3 --algo LRU
pc --producers 2 --consumers 2 --bufsize 3 --items 4
--
  mem [--frames N] [--algo FIFO|LRU] [--quiet] [--free-after PID]
                             Run paging/memory management simulation

  pc [--producers N] [--consumers N] [--bufsize N] [--items N]
                             Run Producer-Consumer synchronization demo

  showperm <path>            Show permissions for a path
  chmodsim <path> <admin_perm> <user_perm>
                             Set simulated permissions for a path

All original commands remain intact.
"""

# ─────────────────────────────────────────────────────────────────────────────
# Standard library imports
# ─────────────────────────────────────────────────────────────────────────────
import argparse
import getpass
import heapq
import json
import os
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Platform detection
# ─────────────────────────────────────────────────────────────────────────────
IS_WINDOWS = platform.system() == "Windows"

# ─────────────────────────────────────────────────────────────────────────────
# Global job table
# ─────────────────────────────────────────────────────────────────────────────
jobs = []
job_counter = 1
fg_threads = {}          # job_id -> threading.Thread for foregrounded jobs

# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 1: Authentication & User Management ───────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

users_db = {
    "admin":   {"password": "admin123",   "role": "admin"},
    "student": {"password": "student123", "role": "user"},
}

current_user = None   # set after successful login


def login_prompt():
    """Prompt for credentials and set current_user."""
    global current_user
    while True:
        print("\nLogin required")
        username = input("Username: ").strip()
        password = getpass.getpass("Password: ")
        user = users_db.get(username)
        if user and user["password"] == password:
            current_user = {"username": username, "role": user["role"]}
            print(f"Login successful. Logged in as {username} ({user['role']})")
            return
        print("Invalid credentials. Try again.")


def add_user(username, password, role):
    users_db[username] = {"password": password, "role": role}


# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 2: Permissions ────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

PERM_FILE = Path(__file__).with_name("permissions_db.json")
permissions_db = {}


def normalize_path(path_str):
    return os.path.abspath(os.path.expanduser(path_str))


def load_permissions():
    global permissions_db
    if PERM_FILE.exists():
        try:
            permissions_db = json.loads(PERM_FILE.read_text())
        except Exception:
            permissions_db = {}


def save_permissions():
    PERM_FILE.write_text(json.dumps(permissions_db, indent=2))


def set_permissions(path_str, admin_perm, user_perm):
    abs_path = normalize_path(path_str)
    permissions_db[abs_path] = {"admin": admin_perm, "user": user_perm}
    save_permissions()


def get_permissions(path_str):
    abs_path = normalize_path(path_str)
    if abs_path in permissions_db:
        return permissions_db[abs_path]
    if os.path.isdir(abs_path):
        return {"admin": "rwx", "user": "rwx"}
    return {"admin": "rwx", "user": "rw"}


def has_permission(path_str, action):
    role = current_user["role"]
    perms = get_permissions(path_str)
    role_key = "admin" if role == "admin" else "user"
    allowed = perms.get(role_key, "")
    return action in allowed


def ensure_demo_security_files():
    system_dir = normalize_path("system_files")
    if not os.path.exists(system_dir):
        os.mkdir(system_dir)
    config_file = os.path.join(system_dir, "config.txt")
    if not os.path.exists(config_file):
        with open(config_file, "w") as f:
            f.write("system configuration\n")
    set_permissions(system_dir, "rwx", "rx")
    set_permissions(config_file, "rw", "r")


# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 3: Pipeline Support ───────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def split_pipeline(command_line):
    """Split a command line on unquoted '|' characters."""
    parts = []
    current = []
    single = False
    double = False
    for ch in command_line:
        if ch == "'" and not double:
            single = not single
        elif ch == '"' and not single:
            double = not double
        if ch == "|" and not single and not double:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 4: Scheduler ──────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class Process:
    """Represents a schedulable process."""
    def __init__(self, pid, name, burst_time, priority=0, arrival_delay=0):
        self.pid           = pid
        self.name          = name
        self.burst_time    = burst_time
        self.remaining_time = burst_time
        self.priority      = priority
        self.arrival_delay = arrival_delay

        self.arrival_time  = None
        self.start_time    = None
        self.finish_time   = None

        self.waiting_time    = 0.0
        self.turnaround_time = 0.0
        self.response_time   = 0.0

    def __lt__(self, other):
        return self.priority < other.priority


def _timestamp():
    return time.strftime("%H:%M:%S")


def _show_results(processes, title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print(f"{'PID':<5} {'Name':<15} {'Burst':>6} {'Wait':>8} {'Response':>10} {'Turnaround':>12}")
    print("-" * 70)

    total_wait = total_response = total_turnaround = 0.0

    for p in processes:
        if p.finish_time is not None and p.arrival_time is not None:
            p.turnaround_time = round(p.finish_time - p.arrival_time, 2)
            p.waiting_time    = round(p.turnaround_time - p.burst_time, 2)
        else:
            p.turnaround_time = p.waiting_time = 0.0

        if p.start_time is not None and p.arrival_time is not None:
            p.response_time = round(p.start_time - p.arrival_time, 2)
        else:
            p.response_time = 0.0

        total_wait       += p.waiting_time
        total_response   += p.response_time
        total_turnaround += p.turnaround_time

        print(
            f"{p.pid:<5} {p.name:<15} {p.burst_time:>5.1f}s "
            f"{p.waiting_time:>7.2f}s {p.response_time:>9.2f}s {p.turnaround_time:>11.2f}s"
        )

    count = len(processes)
    if count:
        print("-" * 70)
        print(
            f"{'AVG':<21} "
            f"{total_wait/count:>7.2f}s {total_response/count:>9.2f}s {total_turnaround/count:>11.2f}s"
        )


def run_round_robin_scheduler(processes, quantum=1.5):
    print("\nPROCESS SCHEDULING SIMULATOR")
    print("\nROUND-ROBIN SCHEDULING")
    print(f"Time Quantum: {quantum}s")

    start_clock = time.time()
    queue = deque()

    for p in processes:
        p.arrival_time = start_clock
        queue.append(p)

    while queue:
        p = queue.popleft()
        if p.start_time is None:
            p.start_time = time.time()

        run_for = min(quantum, p.remaining_time)
        print(f"[{_timestamp()}] Running '{p.name}' for {run_for:.1f}s [{p.remaining_time:.1f}s left]")
        time.sleep(run_for)
        p.remaining_time -= run_for

        if p.remaining_time > 0:
            print(f"[{_timestamp()}]   [NEXT] '{p.name}' re-queued [{p.remaining_time:.1f}s left]")
            queue.append(p)
        else:
            p.finish_time = time.time()
            elapsed = round(p.finish_time - start_clock, 2)
            print(f"[{_timestamp()}]   [DONE] '{p.name}' finished at {elapsed:.2f}s")

    print(f"[{_timestamp()}] Round-Robin done.")
    _show_results(processes, "ROUND-ROBIN RESULTS")


def run_priority_scheduler(processes):
    print("\nPRIORITY-BASED SCHEDULING")

    start_clock = time.time()
    future = sorted(processes, key=lambda p: p.arrival_delay)
    heap = []
    current = None
    time_slice = 0.1

    while future or heap or current:
        now     = time.time()
        elapsed = now - start_clock

        while future and future[0].arrival_delay <= elapsed:
            p = future.pop(0)
            p.arrival_time = start_clock + p.arrival_delay
            heapq.heappush(heap, p)
            print(f"[{_timestamp()}] + Queued '{p.name}' (priority {p.priority})")
            if current and p.priority < current.priority:
                print(f"[{_timestamp()}]   [PREEMPT] '{current.name}' -- urgent process arrived!")
                heapq.heappush(heap, current)
                current = None

        if current is None and heap:
            current = heapq.heappop(heap)
            if current.start_time is None:
                current.start_time = time.time()

        if current:
            print(
                f"[{_timestamp()}] Running '{current.name}' "
                f"(priority {current.priority}) [{current.remaining_time:.1f}s left]"
            )
            time.sleep(time_slice)
            current.remaining_time -= time_slice
            if current.remaining_time <= 0.001:
                current.remaining_time = 0
                current.finish_time = time.time()
                elapsed_finish = round(current.finish_time - start_clock, 2)
                print(f"[{_timestamp()}]   [DONE] '{current.name}' finished at {elapsed_finish:.2f}s")
                current = None
        else:
            time.sleep(time_slice)

    print(f"[{_timestamp()}] Priority scheduling done.")
    _show_results(processes, "PRIORITY SCHEDULING RESULTS")


def cmd_scheduler(args_list):
    """Handle the 'scheduler' shell command."""
    mode = args_list[1] if len(args_list) > 1 else "all"

    rr_processes = [
        Process(1, "Browser",  4.0),
        Process(2, "Music App", 2.0),
        Process(3, "File Copy", 5.0),
        Process(4, "Antivirus", 3.0),
    ]
    priority_processes = [
        Process(5, "Backup",        5.0, priority=3, arrival_delay=0),
        Process(6, "DB Query",      3.0, priority=2, arrival_delay=0),
        Process(7, "Critical Alert", 2.0, priority=1, arrival_delay=2),
    ]

    if mode in ("rr", "all"):
        run_round_robin_scheduler(rr_processes, quantum=1.5)
    if mode in ("priority", "all"):
        run_priority_scheduler(priority_processes)
    if mode not in ("rr", "priority", "all"):
        print(f"scheduler: unknown mode '{mode}'. Use: rr | priority | all")


# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 5: Memory Management (Paging) ────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Frame:
    frame_id:  int
    pid:       int
    vpn:       int
    load_time: int
    last_used: int


class Pager:
    """Fixed-size physical frame pool with FIFO or LRU replacement."""

    def __init__(self, frames: int, algo: str = "LRU"):
        assert frames > 0
        assert algo in ("FIFO", "LRU")
        self.n      = frames
        self.algo   = algo
        self.frames = [None] * frames
        self.free   = deque(range(frames))
        self.map    = {}     # (pid, vpn) -> frame_id
        self.t      = 0      # logical clock
        self.total_refs   = 0
        self.total_faults = 0
        self.stats  = {}     # pid -> {refs, faults, resident}

    def _ensure(self, pid):
        if pid not in self.stats:
            self.stats[pid] = {"refs": 0, "faults": 0, "resident": 0}

    def access(self, pid, vpn):
        """Return True on hit, False on page fault."""
        self._ensure(pid)
        self.t += 1
        self.total_refs += 1
        self.stats[pid]["refs"] += 1

        key = (pid, vpn)
        if key in self.map:
            self.frames[self.map[key]].last_used = self.t
            return True

        # Page fault
        self.total_faults += 1
        self.stats[pid]["faults"] += 1
        if not self.free:
            self._evict_one()

        f  = self.free.popleft()
        fr = Frame(f, pid, vpn, load_time=self.t, last_used=self.t)
        self.frames[f] = fr
        self.map[key]  = f
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
        print(f"[EVICT] algo={self.algo} frame={victim_idx} victim=PID {v.pid} VPN {v.vpn}")
        self.map.pop((v.pid, v.vpn), None)
        self.stats[v.pid]["resident"] = max(0, self.stats[v.pid]["resident"] - 1)
        self.frames[victim_idx] = None
        self.free.append(victim_idx)

    def free_process(self, pid):
        """Deallocate all frames belonging to pid."""
        to_free = [(i, fr.vpn) for i, fr in enumerate(self.frames) if fr is not None and fr.pid == pid]
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
                "faults":     s["faults"],
                "resident":   s["resident"],
                "hit_rate":   1.0 - (s["faults"] / refs),
            }
        overall_hit = 0.0 if self.total_refs == 0 else 1.0 - (self.total_faults / self.total_refs)
        return {
            "algo":          self.algo,
            "frames":        self.n,
            "total_refs":    self.total_refs,
            "total_faults":  self.total_faults,
            "overall_hit_rate": overall_hit,
            "by_process":    per_proc,
        }


def _run_round_robin_pager(pager, traces, verbose=True):
    iters  = {pid: iter(v) for pid, v in traces.items()}
    active = set(traces.keys())
    order  = sorted(active)
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


def cmd_mem(args_list):
    """Handle the 'mem' shell command."""
    parser = argparse.ArgumentParser(prog="mem", add_help=False)
    parser.add_argument("--frames",     type=int,   default=3)
    parser.add_argument("--algo",       choices=["FIFO", "LRU"], default="LRU")
    parser.add_argument("--quiet",      action="store_true")
    parser.add_argument("--free-after", type=int,   default=-1, dest="free_after")
    try:
        opts = parser.parse_args(args_list[1:])
    except SystemExit:
        return

    pager = Pager(frames=opts.frames, algo=opts.algo)
    traces = {
        1: [0, 1, 2, 0, 1, 3, 0, 1, 2, 3],
        2: [0, 2, 4, 0, 2, 4],
    }

    _run_round_robin_pager(pager, traces, verbose=not opts.quiet)

    if opts.free_after in traces:
        print(f"\n--- Deallocating PID {opts.free_after} ---")
        pager.free_process(opts.free_after)
        followup = {pid: [0, 1, 2] for pid in traces if pid != opts.free_after}
        _run_round_robin_pager(pager, followup, verbose=not opts.quiet)

    s = pager.summary()
    print("\n=== STATS ===")
    print(f"Frames={s['frames']} Algo={s['algo']}")
    print(f"Total refs={s['total_refs']}  faults={s['total_faults']}  hit={s['overall_hit_rate']:.3f}")
    for pid in sorted(s["by_process"]):
        b = s["by_process"][pid]
        print(f"PID {pid}: refs={b['references']}, faults={b['faults']}, "
              f"resident={b['resident']}, hit={b['hit_rate']:.3f}")


# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 6: Producer-Consumer ─────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

class BoundedBuffer:
    """Semaphore-based bounded buffer with a mutex."""
    def __init__(self, capacity):
        assert capacity > 0
        self.capacity = capacity
        self.q     = deque()
        self.empty = threading.Semaphore(capacity)
        self.full  = threading.Semaphore(0)
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


def _run_pc(producers=1, consumers=1, bufsize=3, items=5):
    buf  = BoundedBuffer(bufsize)
    STOP = ("STOP",)

    def prod(pid):
        for i in range(items):
            buf.put((pid, i), pid=pid)
            time.sleep(0.01)

    def cons(cid):
        while True:
            item = buf.get(cid=cid)
            if item == STOP:
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

    for t in threads[:producers]:
        t.join()
    for _ in range(consumers):
        buf.put(STOP, pid=-1)
    for t in threads[producers:]:
        t.join()


def cmd_pc(args_list):
    """Handle the 'pc' shell command."""
    parser = argparse.ArgumentParser(prog="pc", add_help=False)
    parser.add_argument("--producers", type=int, default=1)
    parser.add_argument("--consumers", type=int, default=1)
    parser.add_argument("--bufsize",   type=int, default=3)
    parser.add_argument("--items",     type=int, default=5)
    try:
        opts = parser.parse_args(args_list[1:])
    except SystemExit:
        return
    _run_pc(opts.producers, opts.consumers, opts.bufsize, opts.items)


# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 7: Core Shell Helpers ─────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def clear_screen():
    if IS_WINDOWS:
        subprocess.call("cls", shell=True)
    else:
        subprocess.call("clear", shell=True)


def kill_process(pid):
    if IS_WINDOWS:
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, text=True,
        )
        if result.returncode not in (0, 128):
            raise ProcessLookupError(f"Process {pid} not found or could not be killed")
    else:
        os.kill(pid, signal.SIGKILL)


def kill_job_fully(job):
    """Kill the job's PID and any re-spawned windows (Windows-aware)."""
    if not IS_WINDOWS:
        try:
            os.kill(job["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass
        return

    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(job["pid"])],
        capture_output=True, text=True,
    )
    exe = job["args"][0]
    if not exe.lower().endswith(".exe"):
        exe += ".exe"
    exe_name = os.path.basename(exe)
    subprocess.run(["taskkill", "/F", "/IM", exe_name], capture_output=True, text=True)


def resume_process(process):
    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.kernel32.ResumeThread(
                ctypes.windll.kernel32.OpenThread(0x0002, False, process.pid)
            )
        except Exception:
            pass
    else:
        os.kill(process.pid, signal.SIGCONT)


def update_jobs():
    for job in jobs:
        if job["status"] == "Running":
            if job["process"].poll() is not None:
                job["status"] = "Finished"


def find_job(job_id):
    for job in jobs:
        if job["job_id"] == job_id:
            return job
    return None


def _run_fg(job):
    """Thread target: run a job in the foreground, output goes to console."""
    try:
        fg_proc = subprocess.Popen(job["args"])
        job["process"] = fg_proc
        job["pid"]     = fg_proc.pid
        job["status"]  = "Running"
        fg_proc.wait()
    except Exception as e:
        print(f"\n[Job {job['job_id']}] error: {e}")
    finally:
        if job["status"] != "Terminated":
            job["status"] = "Finished"
        print(f"\n[Job {job['job_id']}] '{job['command']}' finished\n"
              f"{current_user['username']}@myshell> ", end="", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 8: Built-in Command Registry ─────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

BUILTINS = {
    "pwd", "exit", "echo", "clear", "ls", "cat", "mkdir", "rmdir",
    "rm", "touch", "jobs", "kill", "fg", "bg", "whoami",
    "login", "logout", "adduser", "listusers",
    "showperm", "chmodsim",
    "scheduler", "mem", "pc",
    "help",
}


def builtin_help():
    return """
Available commands:
  ── File System ──────────────────
  cd [dir]           Change directory
  pwd                Print working directory
  ls                 List directory contents
  cat <file>         Print file contents
  mkdir <dir>        Make directory
  rmdir <dir>        Remove directory
  rm <file>          Remove file
  touch <file>       Create/update file
  echo [args]        Print arguments
  clear              Clear screen

  ── Jobs & Processes ─────────────
  jobs               List background jobs
  fg <id>            Foreground a job
  bg <id>            Background a job
  kill <pid>         Kill a process

  ── Authentication ───────────────
  whoami             Show current user
  login              Log in as a user
  logout             Log out (returns to login prompt)
  adduser <u> <p> <role>   Add a user (admin only)
  listusers          List all users

  ── Permissions ──────────────────
  showperm <path>    Show permissions for a path
  chmodsim <path> <admin_perm> <user_perm>
                     Set permissions (admin only)

  ── Scheduler ────────────────────
  scheduler rr       Run Round-Robin scheduling demo
  scheduler priority Run Priority scheduling demo
  scheduler all      Run both scheduling demos

  ── Memory Management ────────────
  mem [--frames N] [--algo FIFO|LRU] [--quiet] [--free-after PID]
                     Paging simulation

  ── Producer-Consumer ────────────
  pc [--producers N] [--consumers N] [--bufsize N] [--items N]
                     Synchronization demo

  exit               Exit the shell
  help               Show this help
"""


def run_builtin(args, input_data=None):
    """Execute a built-in command. Returns output string or None."""
    cmd = args[0]

    # ── pwd ───────────────────────────────────────────────────────────────────
    if cmd == "pwd":
        return os.getcwd() + "\n"

    # ── whoami ────────────────────────────────────────────────────────────────
    elif cmd == "whoami":
        return f'{current_user["username"]} ({current_user["role"]})\n'

    # ── echo ──────────────────────────────────────────────────────────────────
    elif cmd == "echo":
        return " ".join(args[1:]) + "\n"

    # ── clear ─────────────────────────────────────────────────────────────────
    elif cmd == "clear":
        clear_screen()
        return None

    # ── ls ────────────────────────────────────────────────────────────────────
    elif cmd == "ls":
        path = args[1] if len(args) > 1 else "."
        try:
            return "\n".join(os.listdir(path)) + "\n"
        except Exception as e:
            return f"ls: {e}\n"

    # ── cat ───────────────────────────────────────────────────────────────────
    elif cmd == "cat":
        if len(args) < 2:
            return "cat: missing filename\n"
        if not has_permission(args[1], "r"):
            return "permission denied\n"
        try:
            with open(args[1], encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return "cat: file not found\n"
        except Exception as e:
            return f"cat: {e}\n"

    # ── mkdir ─────────────────────────────────────────────────────────────────
    elif cmd == "mkdir":
        if len(args) < 2:
            return "mkdir: missing directory name\n"
        try:
            os.mkdir(args[1])
        except FileExistsError:
            return "mkdir: directory already exists\n"
        except Exception as e:
            return f"mkdir: {e}\n"
        return None

    # ── rmdir ─────────────────────────────────────────────────────────────────
    elif cmd == "rmdir":
        if len(args) < 2:
            return "rmdir: missing directory name\n"
        target = args[1]
        if not has_permission(target, "w"):
            return "permission denied\n"
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
            else:
                return "rmdir: not a directory\n"
        except PermissionError:
            return "rmdir: permission denied\n"
        except Exception as e:
            return f"rmdir: {e}\n"
        return None

    # ── rm ────────────────────────────────────────────────────────────────────
    elif cmd == "rm":
        if len(args) < 2:
            return "rm: missing filename\n"
        if not has_permission(args[1], "w"):
            return "permission denied\n"
        try:
            os.remove(args[1])
        except FileNotFoundError:
            return "rm: file not found\n"
        except Exception as e:
            return f"rm: {e}\n"
        return None

    # ── touch ─────────────────────────────────────────────────────────────────
    elif cmd == "touch":
        if len(args) < 2:
            return "touch: missing filename\n"
        try:
            with open(args[1], "a", encoding="utf-8"):
                pass
        except Exception as e:
            return f"touch: {e}\n"
        return None

    # ── jobs ──────────────────────────────────────────────────────────────────
    elif cmd == "jobs":
        update_jobs()
        if not jobs:
            return "No jobs found\n"
        lines = []
        for job in jobs:
            status = job["status"]
            if job["job_id"] in fg_threads and fg_threads[job["job_id"]].is_alive():
                status = "Foregrounded"
            lines.append(f'[{job["job_id"]}] PID={job["pid"]} {status} - {job["command"]}')
        return "\n".join(lines) + "\n"

    # ── kill ──────────────────────────────────────────────────────────────────
    elif cmd == "kill":
        if len(args) < 2:
            return "kill: missing pid\n"
        try:
            pid = int(args[1])
            matched = next((j for j in jobs if j["pid"] == pid), None)
            if matched:
                kill_job_fully(matched)
                matched["status"] = "Terminated"
            else:
                kill_process(pid)
            return f"Process {pid} killed\n"
        except ProcessLookupError:
            return "kill: process not found\n"
        except ValueError:
            return "kill: invalid pid\n"
        except Exception as e:
            return f"kill error: {e}\n"

    # ── adduser ───────────────────────────────────────────────────────────────
    elif cmd == "adduser":
        if current_user["role"] != "admin":
            return "only admin can add users\n"
        if len(args) < 4:
            return "usage: adduser <username> <password> <role>\n"
        add_user(args[1], args[2], args[3])
        return "user added\n"

    # ── listusers ─────────────────────────────────────────────────────────────
    elif cmd == "listusers":
        return "\n".join(f"{u} ({users_db[u]['role']})" for u in users_db) + "\n"

    # ── login ─────────────────────────────────────────────────────────────────
    elif cmd == "login":
        login_prompt()
        return None

    # ── logout ────────────────────────────────────────────────────────────────
    elif cmd == "logout":
        print(f"Logged out of {current_user['username']}.")
        login_prompt()
        return None

    # ── showperm ──────────────────────────────────────────────────────────────
    elif cmd == "showperm":
        if len(args) < 2:
            return "usage: showperm <path>\n"
        perms = get_permissions(args[1])
        return f"Permissions for '{normalize_path(args[1])}':\n  admin: {perms.get('admin','?')}\n  user:  {perms.get('user','?')}\n"

    # ── chmodsim ──────────────────────────────────────────────────────────────
    elif cmd == "chmodsim":
        if current_user["role"] != "admin":
            return "only admin can change permissions\n"
        if len(args) < 4:
            return "usage: chmodsim <path> <admin_perm> <user_perm>\n"
        set_permissions(args[1], args[2], args[3])
        return f"Permissions updated for '{normalize_path(args[1])}'\n"

    # ── help ──────────────────────────────────────────────────────────────────
    elif cmd == "help":
        return builtin_help()

    return None   # not handled here — caller will try as external command


# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 9: Pipeline Execution ────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(command_line):
    """Execute a pipe-separated command line, returning final output."""
    stages = split_pipeline(command_line)
    data = None

    for stage in stages:
        args = shlex.split(stage)
        if not args:
            continue
        cmd = args[0]

        if cmd in BUILTINS:
            output = run_builtin(args, data)
            data = output if output else ""
        else:
            result = subprocess.run(
                stage,
                input=data,
                text=True,
                capture_output=True,
                shell=True,
            )
            data = result.stdout

    return data


# ─────────────────────────────────────────────────────────────────────────────
# ── SECTION 10: Main Shell Loop ──────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def main():
    global job_counter

    load_permissions()
    ensure_demo_security_files()
    login_prompt()

    while True:
        try:
            update_jobs()

            prompt = f'{current_user["username"]}@myshell> '
            sys.stdout.write(prompt)
            sys.stdout.flush()
            command = input().strip()

            if not command:
                continue

            # ── Pipeline ──────────────────────────────────────────────────────
            if "|" in command:
                output = run_pipeline(command)
                if output:
                    print(output, end="")
                continue

            # ── Background job flag ───────────────────────────────────────────
            background = command.endswith("&")
            if background:
                command = command[:-1].strip()

            args = shlex.split(command)
            if not args:
                continue

            cmd = args[0]

            # ── exit ──────────────────────────────────────────────────────────
            if cmd == "exit":
                print("Exiting shell.")
                break

            # ── cd (must stay in main loop — changes process CWD) ─────────────
            elif cmd == "cd":
                if len(args) < 2:
                    print("cd: missing directory")
                else:
                    try:
                        os.chdir(args[1])
                    except FileNotFoundError:
                        print("cd: directory not found")
                    except Exception as e:
                        print(f"cd: {e}")

            # ── fg (must stay in main loop — manages threads) ─────────────────
            elif cmd == "fg":
                if len(args) < 2:
                    print("fg: missing job id")
                else:
                    try:
                        job_id = int(args[1])
                        job = find_job(job_id)
                        if not job:
                            print("fg: job not found")
                        elif job["status"] == "Finished":
                            print(f"fg: job [{job_id}] has already finished")
                        elif job_id in fg_threads and fg_threads[job_id].is_alive():
                            print(f"fg: job [{job_id}] is already foregrounded")
                        else:
                            old_proc = job["process"]
                            if old_proc.poll() is None:
                                try:
                                    kill_process(old_proc.pid)
                                except Exception:
                                    pass
                            print(f"Foregrounding job [{job_id}] {job['command']}")
                            print(f"  -> type  bg {job_id}  to send back to background\n")
                            t = threading.Thread(target=_run_fg, args=(job,), daemon=True)
                            fg_threads[job_id] = t
                            t.start()
                    except ValueError:
                        print("fg: invalid job id")

            # ── bg (must stay in main loop — manages threads) ─────────────────
            elif cmd == "bg":
                if len(args) < 2:
                    print("bg: missing job id")
                else:
                    try:
                        job_id = int(args[1])
                        job = find_job(job_id)
                        if not job:
                            print("bg: job not found")
                        else:
                            is_fg = job_id in fg_threads and fg_threads[job_id].is_alive()
                            if is_fg:
                                old_proc = job["process"]
                                if old_proc.poll() is None:
                                    try:
                                        kill_job_fully(job)
                                    except Exception:
                                        pass
                                fg_threads[job_id].join(timeout=2.0)
                                kwargs = {}
                                if IS_WINDOWS:
                                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                                bg_proc = subprocess.Popen(
                                    job["args"],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    **kwargs,
                                )
                                job["process"] = bg_proc
                                job["pid"]     = bg_proc.pid
                                job["status"]  = "Running"
                                print(f"Job [{job_id}] sent to background  PID={bg_proc.pid}")
                            elif job["status"] == "Running":
                                print("bg: job is already running in background")
                            elif job["status"] == "Finished":
                                print("bg: job has already finished")
                            elif job["status"] in ("Stopped", "Terminated"):
                                resume_process(job["process"])
                                job["status"] = "Running"
                                print(f"Job [{job_id}] resumed in background")
                    except ValueError:
                        print("bg: invalid job id")

            # ── scheduler ─────────────────────────────────────────────────────
            elif cmd == "scheduler":
                cmd_scheduler(args)

            # ── mem ───────────────────────────────────────────────────────────
            elif cmd == "mem":
                cmd_mem(args)

            # ── pc ────────────────────────────────────────────────────────────
            elif cmd == "pc":
                cmd_pc(args)

            # ── other builtins ────────────────────────────────────────────────
            elif cmd in BUILTINS:
                output = run_builtin(args)
                if output:
                    print(output, end="")

            # ── external command ──────────────────────────────────────────────
            else:
                try:
                    if background:
                        kwargs = {}
                        if IS_WINDOWS:
                            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                        process = subprocess.Popen(
                            args,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            **kwargs,
                        )
                        jobs.append({
                            "job_id":  job_counter,
                            "pid":     process.pid,
                            "command": command,
                            "args":    args,
                            "status":  "Running",
                            "process": process,
                        })
                        print(f"[{job_counter}] {process.pid} running in background")
                        job_counter += 1
                    else:
                        process = subprocess.Popen(args)
                        process.wait()

                except FileNotFoundError:
                    print(f"{cmd}: command not recognized")
                except Exception as e:
                    print(f"command error: {e}")

        except KeyboardInterrupt:
            print("\nUse 'exit' to quit the shell.")
        except EOFError:
            print("\nExiting shell.")
            break


if __name__ == "__main__":
    main()