import os
import platform
import shlex
import signal
import subprocess
import sys
import threading
import shutil

IS_WINDOWS = platform.system() == "Windows"

jobs = []
job_counter = 1

# job_id -> threading.Thread for jobs currently foregrounded
fg_threads = {}


# ── helpers ───────────────────────────────────────────────────────────────────

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


def clear_screen():
    if IS_WINDOWS:
        subprocess.call("cls", shell=True)
    else:
        subprocess.call("clear", shell=True)


def kill_process(pid):
    if IS_WINDOWS:
        result = subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ProcessLookupError(f"Process {pid} not found or could not be killed")
    else:
        os.kill(pid, signal.SIGKILL)


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


# ── fg runner ─────────────────────────────────────────────────────────────────

def _run_fg(job):
    """
    Runs in a daemon thread.
    Launches the process with its output going straight to the real console
    (no PIPE — Windows console apps like ping bypass pipes anyway).
    The thread just waits for the process to finish or be killed.
    """
    try:
        fg_proc = subprocess.Popen(job["args"])   # stdout/stderr → console directly
        job["process"] = fg_proc
        job["pid"]     = fg_proc.pid
        job["status"]  = "Running"
        fg_proc.wait()
    except Exception as e:
        print(f"\n[Job {job['job_id']}] error: {e}")
    finally:
        if job["status"] != "Terminated":
            job["status"] = "Finished"
        print(f"\n[Job {job['job_id']}] '{job['command']}' finished\nmyshell> ", end="", flush=True)


# ── main shell loop ───────────────────────────────────────────────────────────

def main():
    global job_counter

    while True:
        try:
            update_jobs()

            sys.stdout.write("myshell> ")
            sys.stdout.flush()
            command = input().strip()

            if not command:
                continue

            background = command.endswith("&")
            if background:
                command = command[:-1].strip()

            args = shlex.split(command)
            if not args:
                continue

            cmd = args[0]

            # ── exit ──────────────────────────────────────────────────────────
            if cmd == "exit":
                print("Exiting shell...")
                break

            # ── pwd ───────────────────────────────────────────────────────────
            elif cmd == "pwd":
                print(os.getcwd())

            # ── cd ────────────────────────────────────────────────────────────
            elif cmd == "cd":
                if len(args) < 2:
                    print("cd: missing directory")
                else:
                    try:
                        os.chdir(args[1])
                    except FileNotFoundError:
                        print("cd: directory not found")

            # ── echo ──────────────────────────────────────────────────────────
            elif cmd == "echo":
                print(" ".join(args[1:]))

            # ── clear ─────────────────────────────────────────────────────────
            elif cmd == "clear":
                clear_screen()

            # ── ls ────────────────────────────────────────────────────────────
            elif cmd == "ls":
                try:
                    for item in os.listdir():
                        print(item)
                except Exception as e:
                    print(f"ls: error: {e}")

            # ── cat ───────────────────────────────────────────────────────────
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

            # ── mkdir ─────────────────────────────────────────────────────────
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

            # ── rmdir ─────────────────────────────────────────────────────────
            elif cmd == "rmdir":
                if len(args) < 2:
                    print("rmdir: missing directory name")
                else:
                    target = args[1]
                    try:
                        if not os.path.exists(target):
                            print("rmdir: directory not found")
                        elif not os.path.isdir(target):
                            print("rmdir: not a directory")
                        else:
                            visible = [
                                f for f in os.listdir(target)
                                if not (IS_WINDOWS and f.lower() in ("desktop.ini", "thumbs.db"))
                            ]
                            if visible:
                                print("rmdir: directory not empty")
                            else:
                                shutil.rmtree(target)
                    except PermissionError:
                        print("rmdir: permission denied")
                    except Exception as e:
                        print(f"rmdir: error: {e}")

            # ── rm ────────────────────────────────────────────────────────────
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

            # ── touch ─────────────────────────────────────────────────────────
            elif cmd == "touch":
                if len(args) < 2:
                    print("touch: missing filename")
                else:
                    try:
                        with open(args[1], "a", encoding="utf-8"):
                            pass
                    except Exception as e:
                        print(f"touch: error: {e}")

            # ── jobs ──────────────────────────────────────────────────────────
            elif cmd == "jobs":
                update_jobs()
                if not jobs:
                    print("No jobs found")
                else:
                    for job in jobs:
                        display_status = job["status"]
                        if job["job_id"] in fg_threads and fg_threads[job["job_id"]].is_alive():
                            display_status = "Foregrounded"
                        print(
                            f'[{job["job_id"]}] PID={job["pid"]} '
                            f'{display_status} - {job["command"]}'
                        )

            # ── fg ────────────────────────────────────────────────────────────
            elif cmd == "fg":
                if len(args) < 2:
                    print("fg: missing job id")
                else:
                    try:
                        job_id = int(args[1])
                        job = find_job(job_id)

                        if not job:
                            print("fg: job not found")
                            continue
                        if job["status"] == "Finished":
                            print(f"fg: job [{job_id}] has already finished")
                            continue
                        if job_id in fg_threads and fg_threads[job_id].is_alive():
                            print(f"fg: job [{job_id}] is already foregrounded")
                            continue

                        # Kill the silent background copy
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

            # ── bg ────────────────────────────────────────────────────────────
            elif cmd == "bg":
                if len(args) < 2:
                    print("bg: missing job id")
                else:
                    try:
                        job_id = int(args[1])
                        job = find_job(job_id)

                        if not job:
                            print("bg: job not found")
                            continue

                        is_foregrounded = (
                            job_id in fg_threads and fg_threads[job_id].is_alive()
                        )

                        if is_foregrounded:
                            # Kill the foregrounded process — its thread will notice
                            # and mark the job Finished.  Then relaunch silently.
                            old_proc = job["process"]
                            if old_proc.poll() is None:
                                try:
                                    kill_process(old_proc.pid)
                                except Exception:
                                    pass
                            # Wait for the fg thread to finish cleaning up
                            fg_threads[job_id].join(timeout=2.0)

                            # Relaunch silently
                            kwargs = {}
                            if IS_WINDOWS:
                                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                            bg_proc = subprocess.Popen(
                                job["args"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                **kwargs
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
                        else:
                            print(f"bg: unknown status for job [{job_id}]: {job['status']}")

                    except ValueError:
                        print("bg: invalid job id")

            # ── kill ──────────────────────────────────────────────────────────
            elif cmd == "kill":
                if len(args) < 2:
                    print("kill: missing pid")
                else:
                    try:
                        pid = int(args[1])
                        kill_process(pid)
                        print(f"Process {pid} killed")
                        for job in jobs:
                            if job["pid"] == pid:
                                job["status"] = "Terminated"
                    except ProcessLookupError:
                        print("kill: process not found")
                    except ValueError:
                        print("kill: invalid pid")
                    except Exception as e:
                        print(f"kill error: {e}")

            # ── external commands ─────────────────────────────────────────────
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
                            **kwargs
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
                    print("Command not recognized")
                except Exception as e:
                    print(f"Command error: {e}")

        except KeyboardInterrupt:
            print("\nUse 'exit' to quit the shell.")
        except EOFError:
            print("\nExiting shell...")
            break


if __name__ == "__main__":
    main()