# AOSGroup6 — OS Mini-Shell

A Python-based Unix-style shell that integrates four OS concepts into one cohesive program: a core interactive shell, user authentication and permissions, process scheduling, and memory management with synchronization.

## Repository Structure

| File | Description |
|------|-------------|
| `shell.py` | **Main entry point.** Integrated shell combining all deliverables |
| `osh_2.py` | Deliverable 1 — Core shell with built-ins, background jobs, fg/bg/kill |
| `scheduler.py` | Deliverable 3 — Round-Robin and Priority scheduling simulator |
| `os_minisim.py` | Deliverable 4 — Paging memory manager and Producer-Consumer demo |
| `permissions_db.json` | Persisted simulated file permissions (auto-created on first run) |

---

## Requirements

- Python 3.7+
- No third-party libraries — standard library only

---

## How to Run

```bash
python shell.py
```

You will be prompted to log in before the shell starts.

**Default credentials:**

| Username | Password | Role |
|----------|----------|------|
| `admin` | `admin123` | admin |
| `student` | `student123` | user |

---

## Features

### 1. Core Shell (`osh_2.py` / `shell.py`)

An interactive command-line shell with a `username@myshell>` prompt.

**File system commands:**

| Command | Description |
|---------|-------------|
| `pwd` | Print working directory |
| `cd <dir>` | Change directory |
| `ls` | List directory contents |
| `cat <file>` | Print file contents |
| `mkdir <dir>` | Create a directory |
| `rmdir <dir>` | Remove a directory |
| `rm <file>` | Remove a file |
| `touch <file>` | Create or update a file |
| `echo [args]` | Print arguments |
| `clear` | Clear the screen |

**Background jobs and process control:**

| Command | Description |
|---------|-------------|
| `<command> &` | Run a command in the background |
| `jobs` | List all background jobs |
| `fg <id>` | Bring a background job to the foreground |
| `bg <id>` | Send a foregrounded job back to the background |
| `kill <pid>` | Kill a process by PID |

**Pipeline support** — pipe output of one command into another:

```bash
ls | grep txt
cat file.txt | grep error | sort
ls | sort | head -n 5
cat log.txt | grep error | sort | wc -l
```

**Pipeline filter commands:**

| Command | Description |
|---------|-------------|
| `grep [-i] [-v] <pattern> [file]` | Filter lines matching a pattern (`-i` = case-insensitive, `-v` = invert) |
| `sort [-r]` | Sort lines alphabetically (`-r` = reverse, `-f` = force case-sensitive) |
| `wc [-l\|-w\|-c]` | Count lines, words, or characters |
| `head [-n N]` | Output first N lines (default 10) |
| `tail [-n N]` | Output last N lines (default 10) |

---

### 2. Authentication & Permissions (`shell.py`)

The shell requires login on startup. Sessions are role-based (`admin` or `user`).

**User management (admin only):**

```bash
whoami                          # show current user and role
adduser <username> <password> <role>   # create a new user
listusers                       # list all users
logout                          # log out and return to login prompt
```

**Simulated file permissions:**

Permissions are stored in `permissions_db.json` and enforced on `cat`, `rm`, and `rmdir`. Each path has separate `admin` and `user` permission strings (e.g. `rwx`, `rx`, `r`).

```bash
showperm <path>                          # show permissions for a path
chmodsim <path> <admin_perm> <user_perm> # set permissions (admin only)
```

Example:
```bash
chmodsim system_files/config.txt rw r
showperm system_files/config.txt
```

A `system_files/` directory with a `config.txt` is created automatically on startup as a demo of restricted access.

---

### 3. Process Scheduling (`scheduler.py`)

Simulates two CPU scheduling algorithms using real `time.sleep()` to model CPU burst time.

```bash
scheduler rr          # Round-Robin demo
scheduler priority    # Priority-based (preemptive) demo
scheduler all         # Run both in sequence
```

**Round-Robin** — each process gets a fixed time quantum (1.5s). Unfinished processes are re-queued at the back.

Demo processes: Browser (4s), Music App (2s), File Copy (5s), Antivirus (3s).

**Priority-based (preemptive)** — the process with the lowest priority number always runs first. If a higher-priority process arrives while another is running, it immediately preempts the current process.

Demo processes: Backup (priority 3), DB Query (priority 2), Critical Alert (priority 1, arrives at t=2s).

Both algorithms print a results table showing **wait time**, **response time**, and **turnaround time** per process with averages.

Can also be run standalone:
```bash
python scheduler.py
```

---

### 4. Memory Management & Synchronization (`os_minisim.py`)

#### Paging simulation

Simulates a fixed pool of physical frames shared across multiple processes, with page fault handling and frame eviction.

```bash
mem                                  # LRU with 3 frames (default)
mem --frames 4 --algo FIFO           # FIFO replacement with 4 frames
mem --frames 3 --algo LRU --quiet    # suppress per-access output
mem --frames 3 --algo LRU --free-after 1   # deallocate PID 1 mid-run
```

Two processes (PID 1 and PID 2) run in round-robin, accessing virtual page numbers from preset traces. Every access is logged as `HIT` or `MISS`. On a miss when all frames are full, an eviction is triggered and logged as `[EVICT]`.

With `--free-after`, all frames belonging to the given PID are explicitly released (`[FREE]`) to simulate a process exiting, then a follow-up phase shows the freed frames being reused.

A final stats table shows total references, page faults, and hit rate per process and overall.

Can also be run standalone:
```bash
python os_minisim.py mem --frames 3 --algo LRU
python os_minisim.py mem --frames 3 --algo FIFO
```

#### Producer-Consumer synchronization

Demonstrates the classic bounded-buffer problem using semaphores and a mutex to prevent race conditions.

```bash
pc                                              # 1 producer, 1 consumer, buffer 3, 5 items
pc --producers 2 --consumers 2 --bufsize 3 --items 4
```

Producers and consumers run as concurrent threads. The buffer enforces:
- Producers block when the buffer is full (`empty` semaphore).
- Consumers block when the buffer is empty (`full` semaphore).
- A `mutex` lock prevents simultaneous access to the queue.

Every `[PUT]` and `[GET]` is logged with the current buffer size. Shutdown is signalled by injecting a `STOP` token per consumer.

Can also be run standalone:
```bash
python os_minisim.py pc --producers 2 --consumers 2 --bufsize 3 --items 4
```

---

## Example Session

```
Login required
Username: admin
Password:
Login successful. Logged in as admin (admin)

admin@myshell> ls | sort | head -n 5
os_minisim.py
osh_2.py
README.md
scheduler.py
shell.py

admin@myshell> scheduler rr
PROCESS SCHEDULING SIMULATOR
ROUND-ROBIN SCHEDULING
Time Quantum: 1.5s
...

admin@myshell> mem --frames 3 --algo LRU
[LRU] PID 1 -> VPN  0 : MISS
[LRU] PID 2 -> VPN  0 : MISS
...

admin@myshell> pc --producers 2 --consumers 2 --bufsize 3 --items 4
[PUT]  P0: (0, 0) (size=1/3)
[PUT]  P1: (1, 0) (size=2/3)
[GET]  C0: (0, 0) (size=1/3)
...

admin@myshell> exit
Exiting shell.
```

---

## Notes

- `permissions_db.json` is optional — if absent the shell starts with default permissions and creates the file automatically when `chmodsim` is first used.
- The scheduling and memory simulations use `time.sleep()` to model real elapsed time, so they take as long as the sum of the burst times to complete.
- Pipeline filters (`grep`, `sort`, `wc`, `head`, `tail`) are implemented as cross-platform builtins so they work on Windows where these tools may not be available natively.
- Background job management (`&`, `fg`, `bg`, `kill`) is platform-aware and handles Windows process groups and re-spawned GUI windows correctly.
