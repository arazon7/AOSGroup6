# Process Scheduling Simulator

Simulates two CPU scheduling algorithms in Python.

## Requirements

- Python 3.7+
- No extra libraries needed

## How to Run

```bash
python scheduler.py
```

## What It Does

**Round-Robin** — each process takes turns getting 1.5 seconds of CPU time. If it's not done, it goes to the back of the line.

**Priority-Based** — the most urgent process (lowest priority number) always runs first. If a more urgent process arrives mid-run, it immediately takes over.
