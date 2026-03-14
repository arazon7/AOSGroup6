#!/usr/bin/env python3
import os
import shlex
import signal
import sys
import time
from subprocess import Popen

# -------------------------
# Job Table (basic)
# -------------------------
RUNNING, STOPPED, DONE = "Running", "Stopped", "Done"

class Job:
    _next_id = 1
    def __init__(self, proc: Popen, cmdline: str):
        self.job_id = Job._next_id
        Job._next_id += 1
        self.proc = proc                          # subprocess.Popen handle
        self.pgid = os.getpgid(proc.pid)          # process group id
        self.cmdline = cmdline
        self.status = RUNNING

    def refresh_status(self):
        rc = self.proc.poll()
        if rc is not None:
            self.status = DONE
        return self.status

class JobTable:
    def __init__(self):
        self.jobs = []

    def add(self, job: Job):
        self.jobs.append(job)
        return job.job_id

    def remove_done(self):
        self.jobs = [j for j in self.jobs if j.refresh_status() != DONE]

    def find_by_id(self, jid: int):
        for j in self.jobs:
            if j.job_id == jid:
                return j
        return None

    def find_by_pgid(self, pgid: int):
        for j in self.jobs:
            if j.pgid == pgid:
                return j
        return None

    def list(self):
        # Refresh statuses before printing
        for j in self.jobs:
            j.refresh_status()
        return self.jobs[:]

JOBS = JobTable()
FOREGROUND_PGID = None  # Track current foreground job’s pgid (optional)

# -------------------------
# Built-ins (in-process)
# -------------------------
def builtin_cd(args):
    target = args[1] if len(args) > 1 else os.environ.get("HOME", ".")
    try:
        os.chdir(target)
    except Exception as e:
        print(f"cd: {e}", file=sys.stderr)
        return 1
    return 0

def builtin_pwd(args):
    print(os.getcwd())
    return 0

def builtin_echo(args):
    print(" ".join(args[1:]))
    return 0

def builtin_clear(args):
    # ANSI clear screen and home cursor
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    return 0

def builtin_exit(args):
    # Optional: terminate background jobs gracefully first
    # for j in JOBS.list():
    #     try: os.killpg(j.pgid, signal.SIGTERM)
    #     except ProcessLookupError: pass
    raise SystemExit(0)

def builtin_jobs(args):
    for j in JOBS.list():
        print(f"[{j.job_id}] {j.status:7} {j.pgid}   {j.cmdline}")
    return 0

def builtin_fg(args):
    if len(args) < 2 or not args[1].lstrip("%").isdigit():
        print("fg: usage: fg %<job_id>", file=sys.stderr)
        return 1
    jid = int(args[1].lstrip("%"))
    job = JOBS.find_by_id(jid)
    if not job:
        print(f"fg: no such job {jid}", file=sys.stderr)
        return 1
    return move_job_foreground(job)

def builtin_bg(args):
    if len(args) < 2 or not args[1].lstrip("%").isdigit():
        print("bg: usage: bg %<job_id>", file=sys.stderr)
        return 1
    jid = int(args[1].lstrip("%"))
    job = JOBS.find_by_id(jid)
    if not job:
        print(f"bg: no such job {jid}", file=sys.stderr)
        return 1
    try:
        os.killpg(job.pgid, signal.SIGCONT)
        job.status = RUNNING
        print(f"[{job.job_id}] Continued   {job.cmdline}")
        return 0
    except ProcessLookupError:
        job.status = DONE
        print(f"[{job.job_id}] Done        {job.cmdline}")
        return 0

def builtin_kill(args):
    if len(args) < 2 or not args[1].isdigit():
        print("kill: usage: kill <pid_or_pgid>", file=sys.stderr)
        return 1
    pid_or_pgid = int(args[1])
    try:
        # Prefer killing a process group if possible
        try:
            os.killpg(pid_or_pgid, signal.SIGTERM)
        except Exception:
            os.kill(pid_or_pgid, signal.SIGTERM)
        return 0
    except ProcessLookupError:
        print(f"kill: {pid_or_pgid}: no such process", file=sys.stderr)
        return 1

def builtin_help(args):
    print("""Built-ins:
  cd [dir]        change directory
  pwd             print working directory
  echo [text]     print text
  clear           clear screen
  exit            exit shell

Process & job control:
  jobs            list background jobs
  fg %<id>        bring job to foreground
  bg %<id>        resume job in background
  kill <pid|pgid> terminate process or process group

External commands run via PATH (e.g., ls, cat, sleep, etc.).
Use '&' for background:  sleep 5 &""")
    return 0

BUILTINS = {
    "cd": builtin_cd,
    "pwd": builtin_pwd,
    "echo": builtin_echo,
    "clear": builtin_clear,
    "exit": builtin_exit,
    "help": builtin_help,
    # Job control / process mgmt
    "jobs": builtin_jobs,
    "fg": builtin_fg,
    "bg": builtin_bg,
    "kill": builtin_kill,
}

def is_builtin(cmd):
    return cmd in BUILTINS

# -------------------------
# Parsing & Prompt
# -------------------------
def parse_line(line: str):
    """
    Returns (argv:list[str], background:bool)
    - Uses shlex for shell-like parsing (quotes, escaped spaces).
    - Detects trailing '&' for background (works with or without space).
    """
    line = line.strip()
    if not line:
        return [], False

    # Background detection that works for 'cmd &' and also 'cmd&'
    bg = False
    if line.endswith("&"):
        # Important: ensure '&' is not within quotes. shlex can help parse.
        tokens = shlex.split(line[:-1].rstrip(), posix=True)
        bg = True
    else:
        tokens = shlex.split(line, posix=True)

    # Also handle the case where user typed a separated '&' token
    if tokens and tokens[-1] == "&":
        tokens = tokens[:-1]
        bg = True

    return tokens, bg

def prompt():
    try:
        cwd = os.getcwd()
    except Exception:
        cwd = "?"
    # Show only basename of cwd for a compact prompt
    return f"osh:{os.path.basename(cwd) or '/'}$ "

# -------------------------
# Execution
# -------------------------
def launch_external(argv, background: bool, raw_cmdline: str):
    """
    Launch external command using subprocess.
    - preexec_fn=os.setsid starts a new process group (pgid == child pid).
    - For FG: wait() here; for BG: return immediately and add to job table.
    """
    if not argv:
        return 0
    try:
        proc = Popen(argv, preexec_fn=os.setsid)  # new process group
    except FileNotFoundError:
        print(f"{argv[0]}: command not found", file=sys.stderr)
        return 127
    except PermissionError:
        print(f"{argv[0]}: permission denied", file=sys.stderr)
        return 126
    except Exception as e:
        print(f"exec error: {e}", file=sys.stderr)
        return 1

    pgid = os.getpgid(proc.pid)
    if background:
        job = Job(proc, raw_cmdline)
        JOBS.add(job)
        print(f"[{job.job_id}] {pgid}")
        return 0
    else:
        return wait_foreground(proc, pgid)

def wait_foreground(proc: Popen, pgid: int):
    """
    Wait for foreground job to complete. We keep it simple for D1:
    - Block until child finishes.
    - Let Ctrl+C interrupt the child (shell ignores SIGINT).
    """
    global FOREGROUND_PGID
    FOREGROUND_PGID = pgid

    rc = None
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            time.sleep(0.05)
    finally:
        FOREGROUND_PGID = None

    return rc if rc is not None else 0

def move_job_foreground(job: Job):
    """
    Bring a background job to the foreground:
    - Send SIGCONT in case it was stopped
    - Wait until it finishes
    """
    try:
        os.killpg(job.pgid, signal.SIGCONT)
    except ProcessLookupError:
        job.status = DONE
        print(f"[{job.job_id}] Done        {job.cmdline}")
        return 0

    rc = wait_foreground(job.proc, job.pgid)
    job.refresh_status()
    if job.status == DONE:
        JOBS.remove_done()
    return rc

# -------------------------
# Signal Handling (Shell)
# -------------------------
def install_shell_signal_handlers():
    # Shell ignores SIGINT and SIGTSTP so it isn't killed/stopped by Ctrl+C/Z
    signal.signal(signal.SIGINT, lambda s, f: None)
    signal.signal(signal.SIGTSTP, lambda s, f: None)
    # Optional: handle SIGCHLD; here we just lazily poll in jobs()
    try:
        signal.signal(signal.SIGCHLD, lambda s, f: None)
    except AttributeError:
        pass

# -------------------------
# REPL
# -------------------------
def main():
    install_shell_signal_handlers()

    while True:
        try:
            line = input(prompt())
        except EOFError:
            print()  # newline on Ctrl+D
            break
        except KeyboardInterrupt:
            # User pressed Ctrl+C at the prompt; just go to next line
            print()
            continue

        argv, background = parse_line(line)
        if not argv:
            continue

        if is_builtin(argv[0]):
            try:
                _ = BUILTINS[argv[0]](argv)   # call the builtin
            except SystemExit:
                break                          # exit builtin
            except Exception as e:
                print(f"builtin error: {e}", file=sys.stderr)
            continue

        # External command
        launch_external(argv, background, raw_cmdline=line)

if __name__ == "__main__":
    main()
