# scheduler.py - Process Scheduling Simulator
# Demonstrates Round-Robin and Priority-Based scheduling algorithms

import time
import heapq
from collections import deque


# a Process holds all the info about one task we want to run
class Process:

    def __init__(self, pid, name, burst_time, priority=0):
        self.pid = pid
        self.name = name
        self.burst_time = burst_time        # total time the process needs
        self.remaining_time = burst_time    # counts down as it runs
        self.priority = priority            # lower number = runs first
        self.arrival_time = time.time()
        self.start_time = None
        self.finish_time = None
        self.waiting_time = 0

    # lets heapq compare two processes by priority
    def __lt__(self, other):
        if self.priority == other.priority:
            return self.arrival_time < other.arrival_time
        return self.priority < other.priority


# prints a log line with the current time
def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


# prints the results table after all processes finish
def show_results(processes):
    print("-" * 55)
    print(f"{'PID':<5} {'Name':<15} {'Burst':>6} {'Wait':>6} {'Turnaround':>11}")
    print("-" * 55)
    for p in processes:
        turnaround = round(p.finish_time - p.arrival_time, 2) if p.finish_time else "N/A"
        print(f"{p.pid:<5} {p.name:<15} {p.burst_time:>6.1f}s "
              f"{p.waiting_time:>5.2f}s {str(turnaround):>10}s")
    print("-" * 55)


# Round-Robin: give each process a turn, then rotate
def round_robin(processes, quantum):

    print("\nROUND-ROBIN SCHEDULING")
    print(f"Time Quantum: {quantum}s")

    queue = deque(processes)
    start = time.time()

    while queue:
        p = queue.popleft()

        if p.start_time is None:
            p.start_time = time.time()

        # run for quantum or whatever time is left, whichever is shorter
        run_for = min(quantum, p.remaining_time)
        log(f"Running '{p.name}' for {run_for:.1f}s  [{p.remaining_time:.1f}s left]")

        time.sleep(run_for)
        p.remaining_time -= run_for

        if p.remaining_time <= 0:
            # process finished
            p.finish_time = time.time()
            log(f"  [DONE] '{p.name}' finished at {p.finish_time - start:.2f}s")
        else:
            # not done yet, send to the back of the queue
            log(f"  [NEXT] '{p.name}' re-queued  [{p.remaining_time:.1f}s left]")
            for other in queue:
                other.waiting_time += run_for
            queue.append(p)

    log("Round-Robin done.")
    show_results(processes)


# Priority-Based: always run the most urgent process, preempt if needed
def priority_scheduling(processes, incoming=None):

    print("\nPRIORITY-BASED SCHEDULING")

    heap = []
    incoming = incoming or []
    start = time.time()

    # add starting processes to the heap
    counter = 0
    for p in processes:
        heapq.heappush(heap, (p.priority, counter, p))
        counter += 1
        log(f"  + Queued '{p.name}' (priority {p.priority})")

    all_processes = list(processes)
    pending = sorted(incoming, key=lambda x: x["arrive_at"])
    current = None

    while heap or current or pending:

        # check if any new process has arrived
        now = time.time() - start
        for item in pending[:]:
            if item["arrive_at"] <= now:
                p = item["process"]
                heapq.heappush(heap, (p.priority, counter, p))
                counter += 1
                all_processes.append(p)
                pending.remove(item)
                log(f"  + Queued '{p.name}' (priority {p.priority})")

        # pick the most urgent process if nothing is running
        if current is None and heap:
            _, _, current = heapq.heappop(heap)
            if current.start_time is None:
                current.start_time = time.time()
            log(f"Running '{current.name}' (priority {current.priority})  "
                f"[{current.remaining_time:.1f}s left]")

        if current is None:
            time.sleep(0.1)
            continue

        # run one small tick
        time.sleep(0.1)
        current.remaining_time -= 0.1

        # check again for new arrivals after the tick
        now = time.time() - start
        for item in pending[:]:
            if item["arrive_at"] <= now:
                p = item["process"]
                heapq.heappush(heap, (p.priority, counter, p))
                counter += 1
                all_processes.append(p)
                pending.remove(item)
                log(f"  + Queued '{p.name}' (priority {p.priority})")

        # preempt if something more urgent just arrived
        if heap and heap[0][0] < current.priority:
            log(f"  [PREEMPT] '{current.name}' -- urgent process arrived!")
            heapq.heappush(heap, (current.priority, counter, current))
            counter += 1
            current = None
            continue

        # check if current process is done
        if current.remaining_time <= 0.001:
            current.finish_time = time.time()
            log(f"  [DONE] '{current.name}' finished at {current.finish_time - start:.2f}s")
            current = None

    log("Priority scheduling done.")
    show_results(all_processes)


def main():
    print("\nPROCESS SCHEDULING SIMULATOR")

    # Round-Robin demo
    rr_processes = [
        Process(pid=1, name="Browser",   burst_time=4.0),
        Process(pid=2, name="Music App", burst_time=2.0),
        Process(pid=3, name="File Copy", burst_time=5.0),
        Process(pid=4, name="Antivirus", burst_time=3.0),
    ]
    round_robin(rr_processes, quantum=1.5)

    # Priority-Based demo
    pb_processes = [
        Process(pid=5, name="Backup",   burst_time=5.0, priority=3),
        Process(pid=6, name="DB Query", burst_time=3.0, priority=2),
    ]

    # Critical Alert arrives 2 seconds in and preempts whatever is running
    pb_incoming = [
        {"process": Process(pid=7, name="Critical Alert", burst_time=2.0, priority=1),
         "arrive_at": 2.0},
    ]
    priority_scheduling(pb_processes, incoming=pb_incoming)

    print("\nDone!\n")


if __name__ == "__main__":
    main()
