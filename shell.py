import os
import shlex
import subprocess

jobs = []
job_counter = 1


def update_jobs():
    for job in jobs:
        if job["status"] == "Running":
            if job["process"].poll() is not None:
                job["status"] = "Finished"


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

            else:
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
            break


if __name__ == "__main__":
    main()