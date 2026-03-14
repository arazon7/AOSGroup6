import time
import heapq
from collections import deque


class Process:
    def __init__(self, pid, name, burst_time, priority=0, arrival_delay=0):
        self.pid = pid
        self.name = name
        self.burst_time = burst_time
        self.remaining_time = burst_time
        self.priority = priority
        self.arrival_delay = arrival_delay

        self.arrival_time = None
        self.start_time = None
        self.finish_time = None

        self.waiting_time = 0.0
        self.turnaround_time = 0.0
        self.response_time = 0.0

    def __lt__(self, other):
        return self.priority < other.priority


def timestamp():
    return time.strftime("%H:%M:%S")


def show_results(processes, title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)
    print(f"{'PID':<5} {'Name':<15} {'Burst':>6} {'Wait':>8} {'Response':>10} {'Turnaround':>12}")
    print("-" * 70)

    total_wait = 0.0
    total_response = 0.0
    total_turnaround = 0.0

    for p in processes:
        if p.finish_time is not None and p.arrival_time is not None:
            p.turnaround_time = round(p.finish_time - p.arrival_time, 2)
            p.waiting_time = round(p.turnaround_time - p.burst_time, 2)
        else:
            p.turnaround_time = 0.0
            p.waiting_time = 0.0

        if p.start_time is not None and p.arrival_time is not None:
            p.response_time = round(p.start_time - p.arrival_time, 2)
        else:
            p.response_time = 0.0

        total_wait += p.waiting_time
        total_response += p.response_time
        total_turnaround += p.turnaround_time

        print(
            f"{p.pid:<5} {p.name:<15} {p.burst_time:>5.1f}s "
            f"{p.waiting_time:>7.2f}s {p.response_time:>9.2f}s {p.turnaround_time:>11.2f}s"
        )

    count = len(processes)
    if count > 0:
        print("-" * 70)
        print(
            f"{'AVG':<21} "
            f"{total_wait / count:>7.2f}s {total_response / count:>9.2f}s {total_turnaround / count:>11.2f}s"
        )


def round_robin(processes, quantum=1.5):
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
        print(f"[{timestamp()}] Running '{p.name}' for {run_for:.1f}s [{p.remaining_time:.1f}s left]")
        time.sleep(run_for)

        p.remaining_time -= run_for

        if p.remaining_time > 0:
            print(f"[{timestamp()}]   [NEXT] '{p.name}' re-queued [{p.remaining_time:.1f}s left]")
            queue.append(p)
        else:
            p.finish_time = time.time()
            elapsed = round(p.finish_time - start_clock, 2)
            print(f"[{timestamp()}]   [DONE] '{p.name}' finished at {elapsed:.2f}s")

    print(f"[{timestamp()}] Round-Robin done.")
    show_results(processes, "ROUND-ROBIN RESULTS")


def priority_scheduler(processes):
    print("\nPRIORITY-BASED SCHEDULING")

    start_clock = time.time()
    future = sorted(processes, key=lambda p: p.arrival_delay)
    heap = []
    current = None
    time_slice = 0.1

    while future or heap or current:
        now = time.time()
        elapsed = now - start_clock

        while future and future[0].arrival_delay <= elapsed:
            p = future.pop(0)
            p.arrival_time = start_clock + p.arrival_delay
            heapq.heappush(heap, p)
            print(f"[{timestamp()}] + Queued '{p.name}' (priority {p.priority})")

            if current and p.priority < current.priority:
                print(f"[{timestamp()}]   [PREEMPT] '{current.name}' -- urgent process arrived!")
                heapq.heappush(heap, current)
                current = None

        if current is None and heap:
            current = heapq.heappop(heap)
            if current.start_time is None:
                current.start_time = time.time()

        if current:
            print(
                f"[{timestamp()}] Running '{current.name}' "
                f"(priority {current.priority}) [{current.remaining_time:.1f}s left]"
            )
            time.sleep(time_slice)
            current.remaining_time -= time_slice

            if current.remaining_time <= 0.001:
                current.remaining_time = 0
                current.finish_time = time.time()
                elapsed_finish = round(current.finish_time - start_clock, 2)
                print(f"[{timestamp()}]   [DONE] '{current.name}' finished at {elapsed_finish:.2f}s")
                current = None
        else:
            time.sleep(time_slice)

    print(f"[{timestamp()}] Priority scheduling done.")
    show_results(processes, "PRIORITY SCHEDULING RESULTS")


def main():
    rr_processes = [
        Process(1, "Browser", 4.0),
        Process(2, "Music App", 2.0),
        Process(3, "File Copy", 5.0),
        Process(4, "Antivirus", 3.0),
    ]

    priority_processes = [
        Process(5, "Backup", 5.0, priority=3, arrival_delay=0),
        Process(6, "DB Query", 3.0, priority=2, arrival_delay=0),
        Process(7, "Critical Alert", 2.0, priority=1, arrival_delay=2),
    ]

    round_robin(rr_processes, quantum=1.5)
    priority_scheduler(priority_processes)

    print("\nDone!")


if __name__ == "__main__":
    main()